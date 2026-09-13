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
JOY2      ?= 1
# Keysets on only when one is actually selected.
KEYSET    := $(if $(filter 2 3,$(JOY2)),-keyset,+keyset)
VICE_OPTS := +saveres -pal -joydev1 0 -joydev2 $(JOY2) $(KEYSET)


.PHONY: p3-fixtures p4-fixtures
.PHONY: all build d64 test test-fast test-engine-full
.PHONY: test-slice-a test-slice-a-prime test-slice-b
.PHONY: test-p0 test-p1 test-p2 test-p3 test-p4 test-p5 run run-d64 clean

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
# The two-tier regression policy.
#
# test-fast is for running CONSTANTLY while implementing: the P5 model and table
# drift check, a short walk of all three ring modes, and the two invariants that
# the expensive bugs of this project actually violated -- the frame transaction
# staying at raster 250, and presentation still being coherent late in the
# frame. It does not free-run for twenty seconds per fixture and it does not
# soak. If it is not quick it will not be run, and a regression suite nobody
# runs is worse than none.
#
# test-full is the qualification gate and is deliberately NOT weakened: the
# whole P0-P4 ladder including the FIX 16 regression, the complete P5 suite, and
# a 20,000-frame soak of the principal mode. Run it once when the work is
# believed finished, not during iteration.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# The regression surface, in three sizes.
#
# `make test` is the one to run constantly: a compact probe that reads the
# engine's OWN instrumentation counters -- the frame transaction's raster, the
# HUD and handoff entry rasters, both aperture splits, page/pointer coherence
# and the HUD bitmap-write window -- across five fixtures in about a minute. It
# protects every invariant that is expensive to get wrong and cheap to break.
#
# `make test-engine-full` is the inherited qualification ladder. It is slow and
# it is not part of ordinary game development; run it when the renderer, the
# scroller or the aperture has been touched.
# ---------------------------------------------------------------------------
# `make test` is THREE probes, and deliberately so.
#
#   test_engine.py        the engine the game is built on
#   test_slice_a.py       the game's own path: production boot, the published
#                         player block, and the full-byte $d015/$d010
#                         composition that lets the player and the mux share
#                         two registers
#   test_slice_a_prime.py the world contract: scroll direction, the coarse
#                         cadence, and that every row of both pages carries the
#                         stage row it should
#   test_slice_b.py       the weapon: fire cadence, heat, overheat, the shot
#                         event, and the HUD heat feed
#   test_slice_c.py       the dynamic object pool: lifecycle, slot reuse, the
#                         stale sorted-ID hazard, one real enemy, and the
#                         production population ladder
#   test_slice_d.py       the player's hitscan: cannon geometry, target
#                         selection, damage, hit feedback, death and the safe
#                         removal of a killed object
#
# The last five are what break while a game is being built on an engine that
# is already qualified, so they belong in the target that gets run constantly
# rather than in a slower gate.
#
# IT IS NO LONGER ABOUT A MINUTE. Each slice adds a probe and the target is
# growing with the game; run a single `make test-slice-X` while working on one
# system, and this before believing anything. When it becomes slow enough that
# it stops being run, that is the moment to split it -- not before.
test: build
	python3 tests/test_engine.py
	python3 tests/test_slice_a.py
	python3 tests/test_slice_a_prime.py
	python3 tests/test_slice_b.py
	python3 tests/test_slice_c.py
	python3 tests/test_slice_d.py

test-slice-a: build
	python3 tests/test_slice_a.py

test-slice-a-prime: build
	python3 tests/test_slice_a_prime.py

test-slice-b: build
	python3 tests/test_slice_b.py

test-slice-c: build
	python3 tests/test_slice_c.py

test-slice-d: build
	python3 tests/test_slice_d.py

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
