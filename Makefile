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


.PHONY: all build d64 test
.PHONY: test-boot test-production test-turret-regression
.PHONY: test-encounter-director test-player-ship test-flight-paths test-ingress-egress test-clip-scratch
.PHONY: run run-d64 clean

all: build

# Fixed output location. No per-run directories, ever.
build:
	@mkdir -p build
	java -jar "$(KA)" src/main.asm -odir "$(ROOT)/build" -o "$(PRG)" -vicesymbols

# A bootable disk image of the same binary. Nothing in the test path needs it;
# it exists so the program can be launched the way real hardware would load it.
d64: build
	@rm -f "$(D64)"
	@$(C1541) -format "6502engine,01" d64 "$(D64)" >/dev/null
	@$(C1541) "$(D64)" -write "$(PRG)" engine >/dev/null
	@echo "wrote $(D64)"







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

test-boot: build
	python3 tests/test_boot.py

test-production: build
	python3 tests/test_production.py

test-turret-regression: build
	python3 tests/test_turret_regression.py

test-encounter-director: build
	python3 tests/test_encounter_director.py

test-player-ship: build
	python3 tests/test_player_ship.py

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



run: build
	$(X64) $(VICE_OPTS) -autostartprgmode 1 -autostart "$(PRG)"

run-d64: d64
	$(X64) $(VICE_OPTS) -autostart "$(D64)"

clean:
	rm -f build/*.prg build/*.d64 build/*.vs build/*.sym
