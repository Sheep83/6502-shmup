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


.PHONY: p3-fixtures p4-fixtures
.PHONY: all build d64 test test-fast test-engine-full
.PHONY: test-boot test-production test-turret-regression
.PHONY: test-encounter-director
.PHONY: test-p0 test-p1 test-p2 test-p3 test-p4 test-p5 test-renderer-full
.PHONY: run run-d64 clean

all: build

# Fixed output location. No per-run directories, ever.
# The P3 fixture records are generated from tests/p3_model.py. Regenerating is
# not part of `build` on purpose -- a build must never silently rewrite source.
# `make test-p3` fails if the generated file has drifted from its source.
p3-fixtures:
	python3 tools/gen_p3_fixtures.py

p4-fixtures:
	python3 tools/gen_p4_fixtures.py

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

test-p0: build
	python3 tests/test_p0.py

test-p1: build
	python3 tests/test_p1.py

test-p2: build
	python3 tests/test_p2.py

test-p3: build
	python3 tests/test_p3.py

test-p4: build
	python3 tests/test_p4.py

test-p5: build
	python3 tests/test_p5.py

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
# Two heavier, EXPLICITLY NON-DEFAULT targets remain because they still catch
# something the fast gate does not, and are named so nobody mistakes them for
# part of ordinary development:
#
#   make test-engine-full   the inherited P0-P5 qualification ladder, plus
#                           test_engine.py's own posed-fixture (MAXCAP/RING)
#                           stress load. Run it when the renderer, scroller or
#                           aperture itself has been touched -- not for a
#                           gameplay-level change.
#   make test-renderer-full the exhaustive legality-window sweep (4,144
#                           layouts). Run it when the batch-merge window
#                           arithmetic itself has changed.
#
# Future features get their own focused tests for the task at hand, same as
# always -- they just do not accumulate into this file by default afterward.
test: build
	python3 tests/test_boot.py
	python3 tests/test_production.py
	python3 tests/test_turret_regression.py
	python3 tests/test_encounter_director.py

test-boot: build
	python3 tests/test_boot.py

test-production: build
	python3 tests/test_production.py

test-turret-regression: build
	python3 tests/test_turret_regression.py

test-encounter-director: build
	python3 tests/test_encounter_director.py

test-fast: build
	python3 tests/test_engine.py
	python3 tests/p5_model.py
	python3 tools/gen_p5_tables.py --check
	python3 tests/test_p5.py --fast

test-engine-full: build
	python3 tests/test_engine.py
	python3 tests/test_p0.py
	python3 tests/test_p1.py
	python3 tests/test_p2.py
	python3 tests/test_p3.py
	python3 tests/test_p4.py
	python3 tests/test_p5.py

# test-renderer-full — the exhaustive legality-window qualification:
# tests/test_batch_window.py in FULL mode, its 4,144-layout random/shaped
# sweep and all six machine-vs-model layouts. `make test` no longer runs any
# form of this file: its schedule-settle comparison is flaky on an UNTOUCHED
# commit (proven during the turret-firing corrective task -- three failures in
# ten standalone runs with none of that task's changes applied), which is a
# pre-existing harness property of this file, not a signal about ordinary
# gameplay changes. Run this target on demand when the batch-merge window
# arithmetic itself has changed; test_production.py's renderer-sanity section
# is what runs by default instead.
test-renderer-full: build
	python3 tests/test_batch_window.py

# The acceptance configuration.
#
# This is the ONLY target that opens a window. Every automated suite launches
# x64sc with -console instead, because a Gtk3 window takes the macOS keyboard
# focus the moment it maps: a suite that opens a dozen of them steals every
# keystroke from whatever the user is doing in another application. That
# happened, and the emulator had to be killed mid-run.
#
# VICE runs in the FOREGROUND. It used to be launched with a trailing `&`, and
# that is why the VS Code "Run in VICE" task appeared to do nothing: make
# returned the instant it had forked, VS Code treated the task as finished and
# killed its whole process tree, taking the emulator with it. Held in the
# foreground, the task lives exactly as long as the emulator does and ending the
# task stops it cleanly -- which is also the process ownership this repository
# asks for everywhere else.
#
# From a terminal, background it yourself if you want the prompt back: `make run &`.
run: build
	$(X64) $(VICE_OPTS) -autostartprgmode 1 -autostart "$(PRG)"

run-d64: d64
	$(X64) $(VICE_OPTS) -autostart "$(D64)"

clean:
	rm -f build/*.prg build/*.d64 build/*.vs build/*.sym
