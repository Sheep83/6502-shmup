#!/usr/bin/env python3
"""SYNTHETIC ENCOUNTERS, BUILT IN THE LOADED PACKAGE, FOR MACHINERY TESTS.

WHY
---
A test that needs an exact arrangement -- two triggers sharing one wave at two
different speeds, a six-member fire mask, a known straight leg at a known
velocity, a capacity boundary -- must BUILD that arrangement. Reaching for
whatever the author happens to have written today produces a test that is green
by coincidence and red the moment Brian re-authors the level:

    tests/test_trigger_speed.py leant on `sweep`'s opening leg being vx = 6.
    Level 1 no longer opens with `sweep`, so eleven checks failed about an
    engine that was entirely correct.

    tests/test_wave_colour_mode.py needed one FIXED and eleven RANDOM
    appearances, and a shared non-Dropper definition, all of which were true of
    Level 1 in August and none of which are engine properties.

So the arrangement is written into the LOADED PACKAGE IN RAM, in the spare room
the package reserves and the level does not use. That is authored data and
nothing else -- the same technique tests/test_wave_triggers.py has always used
on the trigger ROW columns, and tests/test_aimed_fire.py on the firing mode.
The disk is never touched, so no authored level is edited to make a test pass.

WHERE THE SPARE ROOM IS, AND WHY IT IS SAFE
-------------------------------------------
The package reserves more of each region than any level yet uses:

    movement pool      LEVELPKG_MOVE       LEVELPKG_MOVE_MAX bytes
    wave definitions   LEVELPKG_WAVEDEF    LEVELPKG_WAVEDEF_SLOTS slots
    trigger columns    LEVELPKG_TRIG       LEVELPKG_TRIG_SLOTS slots

HOW MUCH IS SPARE IS DERIVED, not written down here: the reservations come from
src/levelpkg.asm and what the level uses comes from the generated level
(tests/campaign_data.py). Everything installed goes STRICTLY PAST what the level
uses, and every installer refuses rather than overflowing a reservation -- so a
level that grows until the spare room is gone gets a clear failure naming the
budget, not a corrupted package. Nothing overwrites an authored record.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import campaign_data as CD                                         # noqa: E402
from harness import poke, rd1                                      # noqa: E402

# THE PRIMITIVES, FROM src/movement_format.asm. Written out as 0..4 and $ff they
# would be a second copy of the engine's vocabulary, which is the kind of
# duplicate this whole module exists to stop.
WM_STRAIGHT = CD.fmt("WM_STRAIGHT")
WM_ARC = CD.fmt("WM_ARC")
WM_ARC_MIRROR = CD.fmt("WM_ARC_MIRROR")
WM_EXIT = CD.fmt("WM_EXIT")
WM_HOLD = CD.fmt("WM_HOLD")
WM_HEAD_CONT = CD.WM_HEAD_CONT
# WHAT A DROPPER TRIGGER'S TENTH COLUMN SAYS WHEN IT MEANS "the hard-coded
# flight". From src/encounter_format.asm for the same reason as everything above.
TRIG_DROP_LEGACY = CD.fmt("TRIG_DROP_LEGACY")

# The engine's species row offsets. ENEMY_ANIM_STEPS * slot; slot 0 is the
# level's first authored identity. Named by SLOT, not by any level's choice of
# artwork, because a level's identities are content and the row offsets are not.
SLOT_ROW = tuple(i * CD.C.ENEMY_ANIM_STEPS for i in range(CD.C.ENEMY_SLOTS))


def s8(v):
    return v & 0xFF


class Package:
    """The loaded level package, with room to install synthetic content.

    `level` is the parsed authored level (tests/campaign_data.py) so every
    "first spare" is derived from what the level really uses, not assumed.
    """

    def __init__(self, mon, sym, level="level1"):
        self.mon, self.sym = mon, sym
        self.level = CD.level(level) if isinstance(level, str) else level
        self._pool_next = self.level.pool_bytes
        self._def_next = self.level.n_defs
        self.pool_base = sym.get("waveStageTable", CD.POOL_BASE)
        self.def_base = sym.get("waveDefTable", CD.WAVEDEF_BASE)

    # -- writes ------------------------------------------------------------
    def _poke_checked(self, addr, val, tries=6):
        """Write and READ BACK. The monitor drops a write now and again, and a
        dropped write to a package column is a test that measures the authored
        value while believing it measures a synthetic one."""
        for _ in range(tries):
            poke(self.mon, addr, val & 0xFF)
            if rd1(self.mon, addr) == (val & 0xFF):
                return
        raise RuntimeError(f"could not write ${addr:04x} = {val & 0xFF:02x}")

    # -- the movement pool -------------------------------------------------
    def install_program(self, records):
        """Append 4-byte stage records PAST the authored pool. Returns the
        byte offset a wave definition's field 9 wants."""
        need = len(records) * CD.WM_STAGE_SIZE
        off = self._pool_next
        if off + need > CD.POOL_MAX:
            raise AssertionError(
                f"no spare movement pool: the level uses "
                f"{self.level.pool_bytes} of {CD.POOL_MAX} reserved bytes and "
                f"this fixture wants {need} more from offset {off}")
        for i, rec in enumerate(records):
            if len(rec) != CD.WM_STAGE_SIZE:
                raise AssertionError(f"a stage record is {CD.WM_STAGE_SIZE} "
                                     f"bytes, not {len(rec)}")
            for j, b in enumerate(rec):
                self._poke_checked(self.pool_base + off + i * CD.WM_STAGE_SIZE + j,
                                   s8(b))
        self._pool_next = off + need
        return off

    def straight_then_exit(self, vx, vy, frames=250):
        """The simplest useful program: one long STRAIGHT leg, then EXIT.

        A KNOWN VELOCITY THAT NO LEVEL OWNS. Scaling, integration and despawn
        can all be measured against it without asking what the author wrote.
        """
        return self.install_program([
            [WM_STRAIGHT, frames & 0xFF, s8(vx), s8(vy)],
            [WM_EXIT, 0, 0, 0],
        ])

    # -- the wave definitions ----------------------------------------------
    def install_definition(self, *, count=4, interval=22, start_x=120,
                           start_y=60, x_step=0, y_step=16, heading=0,
                           program=0):
        """Write a definition into a SPARE slot. Returns its index."""
        slot = self._def_next
        if slot >= CD.WAVEDEF_SLOTS:
            raise AssertionError(
                f"no spare wave-definition slot: the level uses "
                f"{self.level.n_defs} of {CD.WAVEDEF_SLOTS} reserved slots")
        b = [0] * CD.WAVEDEF_SIZE
        b[CD.WD_COUNT] = count
        b[CD.WD_INTERVAL] = interval
        b[CD.WD_XLO] = start_x & 0xFF
        b[CD.WD_XHI] = (start_x >> 8) & 1
        b[CD.WD_Y] = start_y
        b[CD.WD_XSTEP] = s8(x_step)
        b[CD.WD_YSTEP] = s8(y_step)
        b[CD.WD_RESERVED] = 0        # byte 7 is reserved and must stay zero
        b[CD.WD_HEADING] = heading
        b[CD.WD_PROG] = program      # a BYTE OFFSET in the package
        for j, v in enumerate(b):
            self._poke_checked(self.def_base + slot * CD.WAVEDEF_SIZE + j, v)
        self._def_next = slot + 1
        return slot

    # -- the trigger columns -----------------------------------------------
    def write_trigger(self, i, *, row=None, definition=None, species=None,
                      fire=None, side=None, colour=None, fire_mode=None,
                      speed=None, drop_prog=None):
        """Overwrite named fields of trigger `i` in the loaded package.

        Only what is passed is written, so a caller can change one column of an
        authored trigger and leave the rest exactly as the level authored it.

        `drop_prog` is a movement-pool BYTE OFFSET -- what install_program
        returns -- or TRIG_DROP_LEGACY for the hard-coded flight. It is the one
        column whose harmless value is NOT zero: zero is the first program's
        offset, so a caller that means "legacy" has to say so.
        """
        if i >= CD.TRIG_SLOTS:
            raise AssertionError(f"trigger {i} is past the package's "
                                 f"{CD.TRIG_SLOTS} slots")
        sym = self.sym
        if row is not None:
            self._poke_checked(sym["waveTrigRowLo"] + i, row & 0xFF)
            self._poke_checked(sym["waveTrigRowHi"] + i, (row >> 8) & 0xFF)
        for val, col in ((definition, "waveTrigDef"), (species, "waveTrigSpecies"),
                         (fire, "waveTrigFire"), (side, "waveTrigSide"),
                         (colour, "waveTrigColour"),
                         (fire_mode, "waveTrigFireMode"),
                         (speed, "waveTrigSpeed"),
                         (drop_prog, "waveTrigDropProg")):
            if val is not None:
                self._poke_checked(sym[col] + i, val)

    def set_trigger_count(self, n):
        """How many triggers the director will read. LEVELPKG_TRIGN is package
        data like any other column."""
        if n > CD.TRIG_SLOTS:
            raise AssertionError(f"{n} triggers is past the package's "
                                 f"{CD.TRIG_SLOTS} slots")
        self._poke_checked(CD.TRIGN_ADDR, n)

    def trigger_count(self):
        return rd1(self.mon, CD.TRIGN_ADDR)

    def rewind_cursor(self):
        self._poke_checked(self.sym["wvNextTrig"], 0)
        self._poke_checked(self.sym["wvStarted"], 0)

    def open_the_approach(self):
        """Remove STAGE_NO_SPAWN_ROW for the duration, so a synthetic schedule
        anywhere in the stage is reachable. The approach has its own file."""
        self._poke_checked(CD.NOSPAWN_ADDR + 0, 0xFF)
        self._poke_checked(CD.NOSPAWN_ADDR + 1, 0xFF)

    def set_no_spawn_row(self, row):
        self._poke_checked(CD.NOSPAWN_ADDR + 0, row & 0xFF)
        self._poke_checked(CD.NOSPAWN_ADDR + 1, (row >> 8) & 0xFF)

    # -- the whole thing at once -------------------------------------------
    def only_trigger(self, *, row, definition, species=None, fire=0, side=0,
                     colour=1, fire_mode=0, speed=None, drop_prog=None):
        """Replace the schedule with ONE synthetic trigger and rewind.

        The single most useful fixture: a wave whose row, definition, species,
        mask, colour, mode, speed and Dropper movement are all chosen by the
        test. `drop_prog` defaults to the legacy flight, which is what a level
        that says nothing about it means.
        """
        if species is None:
            species = SLOT_ROW[0]
        if speed is None:
            speed = CD.C.TRIG_SPEED_1X
        if drop_prog is None:
            drop_prog = TRIG_DROP_LEGACY
        self.write_trigger(0, row=row, definition=definition, species=species,
                           fire=fire, side=side, colour=colour,
                           fire_mode=fire_mode, speed=speed,
                           drop_prog=drop_prog)
        self.set_trigger_count(1)
        self.open_the_approach()
        self.rewind_cursor()

    def pair_on_one_definition(self, *, rows, definition, speeds=(None, None),
                               colours=(1, 1), fire_modes=(0, 0), fire=(0, 0),
                               species=None):
        """Two triggers, ONE definition, and whatever differs between them.

        THE ARRANGEMENT EVERY OWNERSHIP MOVE EXISTS FOR -- colour, firing mode
        and speed all became TRIGGER fields so that one reusable formation can
        arrive differently at two rows. It is built, not looked for.
        """
        if species is None:
            species = SLOT_ROW[0]
        for i in (0, 1):
            self.write_trigger(
                i, row=rows[i], definition=definition, species=species,
                fire=fire[i], side=0, colour=colours[i],
                fire_mode=fire_modes[i],
                speed=CD.C.TRIG_SPEED_1X if speeds[i] is None else speeds[i])
        self.set_trigger_count(2)
        self.open_the_approach()
        self.rewind_cursor()
