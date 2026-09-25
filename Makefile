# 6502-shmup — deliberately uncomplicated.
#
# The game project, built on the qualified engine from the sibling
# 6502-engine repository. Nothing here reaches outside this directory except
# the three external tools below.
KA    ?= /Users/brianmorrice/dev/tools/kickassembler/KickAss.jar
X64   ?= /opt/homebrew/bin/x64sc
C1541 ?= /opt/homebrew/bin/c1541
ROOT  := $(CURDIR)

PRG   := $(ROOT)/build/shmup.prg
D64   := $(ROOT)/build/shmup.d64

# THE LEVEL PACKAGE, a second loadable artefact.
#
# $e000-$fff9 is RAM under the banked-out KERNAL and a single PRG cannot reach
# it: a contiguous file spanning $d000-$dfff writes into the I/O registers on
# the way past. So the level is its own file, loaded by the KERNAL at boot --
# which is also the shape a multi-level game and the level editor's export
# workflow both want. See reports/definitive-440-row-memory-audit.md.
LEVELPRG := $(ROOT)/build/level1.prg
# THE CAMPAIGN'S SECOND LEVEL. A runnable disk carries every level the sequence
# can reach, so that Continue on the upgrade screen loads from the same disk the
# engine booted from rather than needing one swapped in. See CAMPAIGN_SEQUENCE
# in src/campaign.asm.
LEVEL2PRG := $(ROOT)/build/level2.prg
LEVEL2DIR := $(ROOT)/src/level2

# WHICH LEVEL DIRECTORY THE BUILD COMPILES AGAINST.
#
# The engine imports its level files by bare name and KickAssembler resolves
# them through -libdir, so pointing this elsewhere swaps the entire authored
# level without editing a line of source. Production is src/level1; the 420-row
# capacity proof generates its own directory under build/ and overrides this.
LEVELDIR ?= $(ROOT)/src/level1

# The level editor emits metatileDefs FIRST and stageMetatileRows second, while
# the audited package contract puts the MAP at the base of the region. The two
# halves are therefore separated mechanically at build time, byte for byte,
# rather than by hand -- so a regenerated map still drops straight in.
MAPSRC   := $(LEVELDIR)/stage_map.asm
MAPROWS  := $(ROOT)/build/stage_map_rows.asm
MAPDEFS  := $(ROOT)/build/stage_map_defs.asm

# The acceptance launch options, defined ONCE.
#
# They live here and nowhere else because drift between two copies of this
# command line is exactly what broke manual fixture selection: .vscode/tasks.json
# carried its own hand-written x64sc invocation, that copy had no -default, and
# the user's saved vicerc bound the host SPACE key to an emulated joystick.
#
#   +saveres    never write our settings back over the user's own
#
#               `-default` IS DELIBERATELY ABSENT HERE, and that is a fix rather
#               than an omission. It means "ignore the user's vicerc and use
#               factory defaults", and in combination with ANY save it does not
#               merely ignore the file -- it OVERWRITES it with those defaults.
#               Measured, on a throwaway config under /tmp:
#
#                   no -default, -saveres   KeySet1Fire and all four
#                                           directions survive
#                   -default,    -saveres   KeySet1Fire, all four directions
#                                           and JoyDevice2 ALL DESTROYED
#                   -default,   +saveres    config untouched
#
#               A manual session opens a real window, and a real window can save
#               settings from its own menu no matter what the command line said.
#               So a manual run must not start from factory defaults: it would
#               be one menu click away from erasing the player's control
#               bindings. It also could not honour JOY2=2 in the first place,
#               because the keyset bindings it needs live in the very file
#               -default discards.
#
#               THE AUTOMATED SUITES STILL PASS -default, and must: they need a
#               known machine, and they pair it with +saveres, which the table
#               above shows is harmless. See tests/test_p0.py.
#   -joydev1 0  Control port 1 stays detached. It is CIA1 $DC01, which is the
#               keyboard ROW drive; a device on it can pull matrix lines and
#               make the keyboard read keys nobody pressed.
#   -joydev2    THE PLAYER'S STICK. Control port 2 is CIA1 $DC00 and
#               src/player.asm's readInput is the only thing that reads it.
#               Override it per run rather than editing this file:
#
#                   make run JOY2=1     numpad          (the default)
#                   make run JOY2=2     keyset A        (your own vicerc bindings)
#                   make run JOY2=3     keyset B
#                   make run JOY2=4     the first real joystick or gamepad
#
#               A MacBook keyboard has no numpad, so a laptop without a
#               controller wants JOY2=4 with something plugged in. If the ship
#               does not move, this is the first thing to change -- the C64 side
#               cannot tell the difference between "no stick" and "no device".
#   -keyset     keysets are ENABLED only when JOY2 actually selects one (2 or
#                3), and disabled otherwise so nothing silently eats a host key.
#               Passing +keyset while also selecting keyset A, as this line used
#               to, asks for a control method and then switches it off.
#
#               A KEYSET NEEDS A FIRE BINDING, AND FIRE IS NOT FIRE2.
#               KeySet1Fire drives the C64's single fire line, CIA1 $DC00 bit 4,
#               which is the only fire the hardware has. KeySet1Fire2 and Fire3
#               are extra buttons on multi-button host controllers and reach no
#               C64 register at all. A vicerc with directions and Fire2 but no
#               Fire therefore moves the ship and never shoots.
#
# The automated suites build their OWN command line in tests/test_p0.py and
# detach both ports there. A test must never depend on a host device.
#
# Normal speed, no monitor, no warp: the only configuration in which what you
# see is what the machine really does.
# ---------------------------------------------------------------------------
# MANUAL AND AUTOMATED VICE ARE TWO DIFFERENT CONFIGURATION CONTEXTS, and the
# options below are the MANUAL one. The automated suites build their own
# command line in tests/test_p0.py and must keep `-default +saveres` with both
# control ports detached: they need a known machine and must never write the
# user's settings back.
#
# A manual session is the opposite. It is the player's own machine and it must
# come up the way they left it:
#
#   save settings on exit   ENABLED, so a change made from the menus persists.
#                           `-saveres` is "save on exit"; `+saveres` is "do not".
#                           This target used to pass `+saveres`, which protected
#                           the config from the AUTOMATED runs -- a concern that
#                           belongs to those runs and not to this one.
#   joystick port 2         KEYSET A, which is what the user's own vicerc
#                           selects and what their bindings are written for.
#   keysets                 ON, unconditionally: port 2 is a keyset.
#   port 1                  LEFT ALONE. It used to be detached so the fixture
#                           selector's $dc00/$dc01 keyboard scan could see the
#                           SPACE key -- and that scan was compiled out when the
#                           fixtures left the startup path (FIXTURE_KEYS in
#                           src/main.asm). Detaching a port the player may want
#                           to use, to protect a scan that no longer runs, is
#                           the kind of thing that outlives its reason.
#
# `-default` IS STILL ABSENT, and that is still the important one: with any
# save it does not merely ignore the user's vicerc, it OVERWRITES it with
# factory defaults, and their keyset bindings go with it.
JOY2      ?= 2
KEYSET    := -keyset
VICE_OPTS := -saveres -pal -joydev2 $(JOY2) $(KEYSET)


.PHONY: all build d64 proof420 test sprites sprites-check
.PHONY: test-boot test-production test-movement-pool test-no-spawn-row test-turret-regression
.PHONY: test-encounter-director test-player-ship test-flight-paths test-ingress-egress test-clip-scratch
.PHONY: test-sfx test-enemy-fire test-pickup test-lifecycle test-player-death test-boss
.PHONY: test-heat-cadence
.PHONY: run run-proof420 run-d64 clean

all: build

# Fixed output location. No per-run directories, ever.
#
# THE DISK IMAGE IS NOW PART OF THE BUILD, not an optional extra. The engine
# loads its level from disk at boot, so a bare PRG is no longer a runnable
# artefact and every test launches the d64.
# SPRITE ART IS GENERATED FROM THE .spd, AND THIS IS THE GATE.
#
# assets/sprites/19656-sprites.spd is the source of truth for every editable
# gameplay sprite. The build does NOT regenerate from it -- tools/level_editor/
# export_level.py states the principle for level data and it holds for artwork:
# "regenerating source on every build would make `make` able to change the
# program's content, so the generation step is explicit and its output is
# reviewable in the diff". Instead each generated file records the .spd's hash
# and this check fails the build loudly when they diverge, so editing sprites
# and forgetting to regenerate can never quietly ship the previous artwork.
sprites:
	@python3 tools/sprite_export/import_spd.py

sprites-check:
	@python3 tools/sprite_export/import_spd.py --check

build: sprites-check
	@mkdir -p build
	@python3 tools/pad_stage_map.py "$(LEVELDIR)" "$(ROOT)/build"
# THE SECOND -libdir IS WHAT LETS A LEVEL OWN ITS ENCOUNTER SOURCE. The level's
# wave_programs.asm / wave_encounters.asm live in $(LEVELDIR) and import the
# ENGINE-owned vocabulary -- movement_format.asm, encounter_format.asm -- which
# stays in src/. KickAssembler resolves an #import against the importing file's
# own directory first and then the libdirs, so a level-owned file cannot reach
# src/ without this. (That same precedence is why src/ may not keep copies of the
# encounter files: while it did, the engine silently used those and editing the
# level-owned ones did nothing -- measured, not assumed.)
	java -jar "$(KA)" src/main.asm -libdir "$(LEVELDIR)" -libdir "$(ROOT)/src" \
	      -odir "$(ROOT)/build" -o "$(PRG)" -vicesymbols
	java -jar "$(KA)" src/level_package.asm -libdir "$(ROOT)/build" \
	      -libdir "$(LEVELDIR)" -libdir "$(ROOT)/src" \
	      -odir "$(ROOT)/build" -o "$(LEVELPRG)"
	@rm -f "$(D64)"
	@$(C1541) -format "6502engine,01" d64 "$(D64)" >/dev/null
	@$(C1541) "$(D64)" -write "$(PRG)" engine >/dev/null
	@$(C1541) "$(D64)" -write "$(LEVELPRG)" level1 >/dev/null
# LEVEL 2'S PACKAGE, built with ITS OWN directory on the libdir path so it picks
# up level 2's map, encounters, charset, palette and turret list. The ENGINE is
# still built against $(LEVELDIR) -- it needs one level's constants to size
# nothing at all now, but stage_enemies.asm still claims the sprite window.
	@python3 tools/pad_stage_map.py "$(LEVEL2DIR)" "$(ROOT)/build/level2"
	java -jar "$(KA)" src/level_package.asm -libdir "$(ROOT)/build/level2" \
	      -libdir "$(LEVEL2DIR)" -libdir "$(ROOT)/src" \
	      -odir "$(ROOT)/build/level2" -o "$(LEVEL2PRG)"
	@$(C1541) "$(D64)" -write "$(LEVEL2PRG)" level2 >/dev/null

# The disk image is built by `build` above; this target remains so that
# `make d64` still means something to anyone who types it.
d64: build
	@echo "wrote $(D64)"

# THE 420-ROW CAPACITY PROOF. Generates the four-copy stage into build/ and
# builds against it, leaving src/level1 -- the authored production level --
# untouched. `make build` afterwards returns the default content.
proof420:
	@python3 tools/gen_proof420.py "$(ROOT)/build/proof420"
	@$(MAKE) --no-print-directory build LEVELDIR="$(ROOT)/build/proof420"







# ---------------------------------------------------------------------------
# The regression surface, in two sizes.
#
# `make test` is THE EVERYDAY GATE, rewritten from scratch at the
# `legacy-tests-retired` tag. It answers one question -- "does the current
# game actually work, and did we obviously break the engine" -- against the
# game AS IT EXISTS NOW, not by replaying the historical migration path one
# slice at a time. Three VICE launches, a few minutes:
#
#   test_boot.py               builds, boots into the real production loop,
#                               and the frame counter advances. Fails fast and
#                               cheaply before anything heavier runs.
#   test_production.py         one production session proving: the fault
#                               counters stay clean over ordinary play; the
#                               scroll/world-progress contract holds every
#                               sampled frame; the object pool cycles with no
#                               corrupted membership (an enemy bullet is an
#                               ordinary pool object now, not a special case);
#                               the player moves, takes a hit, blinks and
#                               returns solid without ever publishing a stray
#                               $d015 bit; and the schedule the renderer
#                               adopts stays inside its allocated size with no
#                               page/pointer coherence fault.
#   test_turret_regression.py  the compact, permanent regression for the
#                               turret-firing production defect: a turret
#                               watched through the REAL production loop keeps
#                               counting down its fire timer across a genuine
#                               coarse scroll step instead of re-arming, and
#                               the real game launches a projectile with
#                               nothing poked. This is retained specifically
#                               because the bug it catches is a cross-
#                               subsystem interaction that a direct routine
#                               call cannot see -- see constraint #4 in
#                               reports/production-test-suite-rewrite.md.
#   test_sfx.py                the sound-effects subsystem: the module is
#                               resident CPU-only memory, every SID write a
#                               running game performs lands in voice 3 (watched
#                               on the bus, not read out of the source), each of
#                               the four hook sites is caught asking for its own
#                               effect through the real frame loop, the number
#                               of requests equals the number of logical events
#                               exactly, priority holds, and a quiet game writes
#                               nothing to the chip at all. It is here rather
#                               than in a non-default target because what it
#                               guards is a hook in production code that a
#                               future change could silently unwire, which is
#                               the same reason the turret regression is here.
#   test_enemy_fire.py         enemy firing: the species declares the
#                               capability and the encounter declares the
#                               opportunity, member by member through the real
#                               spawner; a live eligible enemy fires straight
#                               down from its own logical box through the real
#                               frame loop while a dying one and a stale licence
#                               on a free slot do not; turret and enemy bolts
#                               share ONE cap of three, a refused shot is
#                               counted, silent and lossless, and the existing
#                               player damage path is unchanged. Here rather
#                               than in a non-default target for the same reason
#                               as the turret regression: what it guards is
#                               authored content wired to production hooks.
#   test_pickup.py             token pickups: the authored token column spawns
#                               through the real director at the authored X and
#                               nowhere else, the object is a TYPE_PICKUP of
#                               kind P wearing the P bitmap, it drifts at the
#                               scroll's own speed and despawns itself past the
#                               aperture, the flash moves logCol and nothing
#                               else, the ship collects it exactly once and the
#                               slot comes back whole, a stale slot collects
#                               nothing, the hostile cap is untouched and a full
#                               pool refuses cleanly.
#   test_lifecycle.py          the restored outer loop: attract cycling on the
#                               old 250-frame timer, the old fire-release start
#                               gate, a fresh game, ordinary vs terminal death,
#                               the old game-over hold, score qualification and
#                               insertion on the old rules, edge-triggered
#                               initials entry, the return to attract on the
#                               scores page, and a second game that is fresh
#                               while the table persists.
#   test_player_death.py       the death pass: a dead craft cannot be steered
#                               or fired and leaves HW1 dark, the eight-frame
#                               fireball runs once on HW0 and never loops,
#                               ordinary death respawns with its invulnerability
#                               blink, terminal death hides HW0 and reaches
#                               GAME OVER, and ramming a LIVE enemy damages the
#                               player through the existing playerTakeHit path
#                               while a dying enemy, a bolt and a token do not.
#   test_boss.py               the end of a level: the stage boundary derived
#                               from the authored geometry, the scroller frozen
#                               on the last full screen with no wrap, encounter
#                               generation stopped, an arena clear that cannot
#                               deadlock, one 50-HP boss drawn by four TYPE_BOSS
#                               cells, a seam ray counting once, the health bar
#                               and hit flash, death into a 100-frame pause, an
#                               accelerating scripted exit and LEVEL COMPLETE
#                               with the run intact.
#   test_encounter_director.py the encounter director: an authored trigger off
#                               worldProgress starts a wave, a SECOND wave
#                               instance runs concurrently with the first,
#                               enemies from both coexist, the curved movement
#                               primitive progresses through several phases,
#                               and a slot comes back through the ordinary
#                               pool. Watched through the real frame loop, for
#                               the same reason the turret regression is. The
#                               synthetic all-16-slots pool-pressure
#                               qualification that proved the defer-on-
#                               allocation-failure policy was implementation-
#                               time work and is not part of this permanent
#                               regression; the policy itself is unchanged in
#                               production.
#
# What used to run here -- Slices A/A'/B/C/D, the terrain and turret
# migration-porting proofs, and the historical batch-window schedule-settle
# comparison (which was flaky on the untouched commit, not on anything this
# game does) -- proved that the ORIGINAL PORT from the old game was faithful.
# That job is done and the proof is preserved at the `legacy-tests-retired`
# git tag; it does not need re-running on every future change to a system
# those slices already certified once.
#
# THE P0-P5 LADDER AND ITS FIXTURES ARE RETIRED. The posed-fixture stress
# targets, the exhaustive legality-window sweep and the fixture generators went
# with the fixture system itself; the geometry they certified is exercised by
# test_production.py's renderer-sanity section against the real game. Git has
# them.
#
# Future features get their own focused tests for the task at hand, same as
# always -- they just do not accumulate into this file by default afterward.
test: build
	python3 tests/test_boot.py
	python3 tests/test_production.py
	python3 tests/test_turret_regression.py
	python3 tests/test_encounter_director.py
	python3 tests/test_player_ship.py
	python3 tests/test_level_assets.py
	python3 tests/test_sfx.py
	python3 tests/test_enemy_fire.py
	python3 tests/test_pickup.py
	python3 tests/test_lifecycle.py
	python3 tests/test_player_death.py
	python3 tests/test_boss.py
	python3 tests/test_heat_cadence.py

test-boot: build
	python3 tests/test_boot.py

test-production: build
	python3 tests/test_production.py

test-no-spawn-row: build
	@python3 tests/test_no_spawn_row.py

test-movement-pool: build
	@python3 tests/test_movement_pool.py

test-turret-regression: build
	python3 tests/test_turret_regression.py

test-encounter-director: build
	python3 tests/test_encounter_director.py

test-player-ship: build
	python3 tests/test_player_ship.py

test-level-assets: build
	python3 tests/test_level_assets.py

test-sfx: build
	python3 tests/test_sfx.py

test-enemy-fire: build
	python3 tests/test_enemy_fire.py

test-pickup: build
	python3 tests/test_pickup.py

test-lifecycle: build
	python3 tests/test_lifecycle.py

test-player-death: build
	python3 tests/test_player_death.py

test-boss: build
	python3 tests/test_boss.py

# The heat gauge is published at the same rate in the boss arena as in ordinary
# play. The arena runs in VIC bank 2, where the HUD is a mirror walked across a
# slice a frame -- and the gauge is slice 0, so it used to reach the player only
# every VB_HUD_SLICES frames while it changes every 2-3. It asserts the heat
# STATE cadence and the PUBLISHED cadence separately, because the state was
# never wrong and a test that only checked it passes against the defect.
test-heat-cadence: build
	python3 tests/test_heat_cadence.py

# NON-DEFAULT ON PURPOSE. The composable-movement vocabulary (v1.1): stage
# transitions, a three-stage path walked end to end, an arc and its mirror on
# one enemy, a linger that ends by itself, and repeated arcs carrying an enemy
# most of the way round a circle. It waits for four specific authored patterns
# to come round on a ten-second cycle, which is a minute of gate time to
# re-prove content that only changes when somebody edits it deliberately --
# so `make test` keeps the fast architecture proof and this stays here, for
# when the patterns or the movement primitives themselves are touched.
test-flight-paths: build
	python3 tests/test_flight_paths.py

# NON-DEFAULT ON PURPOSE, same reasoning as test-flight-paths. The enemy
# lifecycle bounds: enemies are born entirely outside the visible playfield,
# fly in through an edge, and are freed only once they have genuinely cleared
# one -- never at the old premature Y=226 cutoff, which was the renderer's
# admission ceiling being used as the edge of the world. It watches most of a
# twenty-second authored cycle so that every pattern arrives and leaves, which
# does not belong in the fast gate.
test-ingress-egress: build
	python3 tests/test_ingress_egress.py

# NON-DEFAULT ON PURPOSE, same reasoning as the other two. Runtime vertical
# clipping: a clipped enemy keeps its true logY, is scheduled at the aperture
# boundary, and is drawn from a scratch block holding the canonical art shifted
# by exactly the rows that hang outside. Waits for enemies to cross the edges
# on the authored schedule, which is content timing, not engine behaviour.
test-clip-scratch: build
	python3 tests/test_clip_scratch.py



# THE DISK, NOT THE PRG. The engine loads its level package from disk during
# the first instruction of entry; autostarting a bare PRG leaves no drive to
# load "LEVEL1" from and the boot halts on a red border by design.
run: build
	$(X64) $(VICE_OPTS) -autostart "$(D64)"

# THE 420-ROW CAPACITY PROOF, regenerated, built and launched in one command.
#
# `proof420` has already put the long stage into the disk image, so this only
# has to start the machine -- the same line `run` uses, and deliberately not a
# second copy of the option list. `make run` still gives the authored 105-row
# production level; nothing here changes what the default build is.
run-proof420: proof420
	$(X64) $(VICE_OPTS) -autostart "$(D64)"

run-d64: d64
	$(X64) $(VICE_OPTS) -autostart "$(D64)"

clean:
	rm -f build/*.prg build/*.d64 build/*.vs build/*.sym
