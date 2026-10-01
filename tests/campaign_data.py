#!/usr/bin/env python3
"""THE AUTHORED CAMPAIGN, READ RATHER THAN REMEMBERED.

WHY THIS FILE EXISTS
--------------------
Automated tests are here to catch the engine, the exporter, the schema and the
package layout misbehaving. They are NOT here to hold Brian's current Level 1
and Level 2 design still. Authored campaign content is DATA: a trigger can be
added, a species swapped, a colour or a speed changed, a wave definition
re-pointed, and none of that is a regression. Every test that wrote one of
those values down as a literal turned a legal authoring change into a wall of
red, and -- worse -- made "the test is green" mean "the level has not changed"
rather than "the machine is correct".

The measured history in this repository:

    tests/test_wave_triggers.py     12 failures, every one a frozen literal
    tests/test_no_spawn_row.py       3 failures, all from `WAVE_TRIGGERS = 4`
    tests/test_wave_colour_mode.py   frozen 7 definitions, 12 triggers, names
    tests/test_trigger_speed.py      frozen `SWEEP_VX = 6` and "all 1.00x"
    tests/test_movement_pool.py      TRIG_SLOTS 180 -> 154 -> 135 -> 120

So the authored content comes from the generated level the engine was actually
built against, through the editor's OWN declaration parser -- the same reader
the importer uses. If this module and the engine can ever disagree about what
the level says, it is because somebody edited the level, which is exactly the
thing a test must not care about.

WHAT IS STILL WORTH ASSERTING is structure, not content:

    "Level 1 has 12 Triggers"                        -- a bad test
    "Every Trigger references a valid Wave Definition" -- a good test

Capacity is DERIVED at both ends (src/levelpkg.asm and the editor's
contract_v2), never retyped as today's number.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "level_editor"))

import asm_decl                                                    # noqa: E402
import contract_v2 as C                                            # noqa: E402

# ---------------------------------------------------------------------------
# THE PACKAGE GEOMETRY, DERIVED. contract_v2 reads src/levelpkg.asm for its
# SIZES; the ADDRESSES are read here from the same file, so no test has to
# restate `$ff92` or `$f530` from a comment again. Those two literals were the
# last magic numbers in the runtime suites.
# ---------------------------------------------------------------------------
_PKG_SRC = (ROOT / "src" / "levelpkg.asm").read_text(encoding="utf-8")
_PKG = {}
for _m in re.finditer(r"^\s*\.const\s+(LEVELPKG_\w+)\s*=\s*(.+)$", _PKG_SRC, re.M):
    # A `//` comment ends the expression; `floor(a / b)` means `/` cannot be
    # used as the comment marker, so the split is on the doubled slash only.
    _expr = _m.group(2).split("//")[0].strip()
    # Only the plain arithmetic the file actually uses: names, $hex, decimal,
    # + - * / and floor(). Anything else is left unresolved rather than guessed.
    _py = re.sub(r"\$([0-9a-fA-F]+)", lambda g: str(int(g.group(1), 16)), _expr)
    _py = _py.replace("floor(", "_floor(")
    try:
        _PKG[_m.group(1)] = int(eval(                       # noqa: S307
            _py, {"_floor": lambda x: int(x), "__builtins__": {}}, dict(_PKG)))
    except Exception:                                       # noqa: BLE001
        pass


def pkg(name):
    """A `.const LEVELPKG_*` from src/levelpkg.asm, resolved."""
    if name not in _PKG:
        raise SystemExit(f"{name} is not a resolvable .const in src/levelpkg.asm")
    return _PKG[name]


TRIG_BASE = pkg("LEVELPKG_TRIG")
TRIG_SLOTS = C.LEVELPKG_TRIG_SLOTS
TRIG_COLS = ("rowLo", "rowHi", "def", "species", "fire", "side",
             "colour", "fireMode", "speed", "dropProg")
assert len(TRIG_COLS) == C.LEVELPKG_TRIG_COLS, (
    f"tests/campaign_data.py names {len(TRIG_COLS)} trigger columns and "
    f"src/levelpkg.asm declares {C.LEVELPKG_TRIG_COLS}")
assert TRIG_SLOTS == pkg("LEVELPKG_TRIG_SLOTS"), (
    "the editor's contract and src/levelpkg.asm disagree about the slot count")

WAVEDEF_BASE = pkg("LEVELPKG_WAVEDEF")
WAVEDEF_SIZE = C.LEVELPKG_WAVEDEF_SIZE
WAVEDEF_SLOTS = C.LEVELPKG_WAVEDEF_SLOTS
POOL_BASE = pkg("LEVELPKG_MOVE")
POOL_MAX = C.LEVELPKG_MOVE_MAX
STAGE_BASE = pkg("LEVELPKG_STAGE")
NOSPAWN_ADDR = pkg("LEVELPKG_NOSPAWN")
TRIGN_ADDR = pkg("LEVELPKG_TRIGN")
SIG_ADDR = pkg("LEVELPKG_SIG")

WM_STAGE_SIZE = C.WM_STAGE_SIZE

# ---------------------------------------------------------------------------
# THE ENGINE'S OWN MOVEMENT AND ENCOUNTER VOCABULARY, from the two files both
# builds import. WM_ARC_SPEED in particular was written as a literal 6 in a
# runtime test; it is an engine constant and belongs here.
# ---------------------------------------------------------------------------
_FMT = asm_decl.parse_files([ROOT / "src" / n for n in
                             ("movement_format.asm", "encounter_format.asm")])


def fmt(name):
    """A `.const` from src/movement_format.asm or src/encounter_format.asm."""
    return _FMT.const(name)


WM_ARC_SPEED = fmt("WM_ARC_SPEED")
WM_ARC_STEP = fmt("WM_ARC_STEP")
WM_HEAD_LEN = fmt("WM_HEAD_LEN")
WM_HEAD_CONT = fmt("WM_HEAD_CONT")
TRIG_FIRE_MAX = fmt("TRIG_FIRE_MAX")

# Wave-definition field offsets, named so no caller writes `+ 9` again.
WD_COUNT, WD_INTERVAL, WD_XLO, WD_XHI, WD_Y = 0, 1, 2, 3, 4
WD_XSTEP, WD_YSTEP, WD_RESERVED, WD_HEADING, WD_PROG = 5, 6, 7, 8, 9


class Level:
    """One authored level, as the generated assembly declares it.

    Nothing here is an expectation. It is a READING, used by tests that need to
    know what the level says in order to check what the machine then does with
    it.
    """

    def __init__(self, name="level1", root=ROOT):
        self.name = name
        self.root = Path(root)
        d = self.root / "src" / name
        self._d = asm_decl.parse_files(
            [self.root / "src" / n
             for n in ("movement_format.asm", "encounter_format.asm")]
            + [d / "wave_programs.asm", d / "wave_encounters.asm"])

        self.n_defs = self._d.const("WAVE_DEFS")
        self.n_triggers = self._d.const("WAVE_TRIGGERS")

        self.trig_row = list(self._d.list_("trigRow"))
        self.trig_def = list(self._d.list_("trigDef"))
        self.trig_species = list(self._d.list_("trigSpecies"))
        self.trig_side = list(self._d.list_("trigSide"))
        self.trig_fire = list(self._d.list_("trigFire"))
        self.trig_colour = list(self._d.list_("trigColour"))
        self.trig_fire_mode = list(self._d.list_("trigFireMode"))
        self.trig_speed = list(self._d.list_("trigSpeed"))
        # WHAT EACH APPEARANCE'S DROPPER FLIES: TRIG_DROP_LEGACY for the
        # hard-coded trajectory, or a movement program INDEX for member 0.
        self.trig_drop_prog = list(self._d.list_("trigDropProg"))

        # Ten bytes each, program field still an INDEX at this stage.
        self.wave_defs = [list(x) for x in self._d.list_("waveDefs")]
        self.progs = [[list(r) for r in p] for p in self._d.list_("progs")]

        # THE POOL'S SHAPE, DERIVED. The package lays the programs end to end
        # and a definition's field 9 is emitted as its program's BYTE OFFSET.
        self.prog_offset, acc = [], 0
        for prog in self.progs:
            self.prog_offset.append(acc)
            acc += len(prog) * WM_STAGE_SIZE
        self.pool_bytes = acc
        self.prog_at = [self.prog_offset[d[WD_PROG]] for d in self.wave_defs]

    # -- the level's own stage_config.asm -----------------------------------
    def const(self, key):
        """A `.const NAME = n` from this level's stage_config.asm."""
        cfg = (self.root / "src" / self.name
               / "stage_config.asm").read_text(encoding="utf-8")
        m = re.search(rf"^\s*\.const\s+{re.escape(key)}\s*=\s*(\d+)", cfg, re.M)
        if not m:
            raise SystemExit(f"{key} not found in src/{self.name}/stage_config.asm")
        return int(m.group(1))

    def turret_count(self):
        """How many turrets this level authors, from its generated list."""
        f = self.root / "src" / self.name / "stage_turrets.asm"
        d = asm_decl.parse_files([f])
        return len(list(d.list_("turretCols")))

    # -- derived views the tests actually ask for ---------------------------
    def rows(self):
        return list(self.trig_row)

    def shared_definitions(self):
        """{definition index: [trigger indices]} for definitions used twice+.

        MAY LEGITIMATELY BE EMPTY. A test that needs two triggers on one
        definition must BUILD that arrangement (see tests/synth.py) rather than
        depend on the author having happened to write one.
        """
        groups = {}
        for i, d in enumerate(self.trig_def):
            groups.setdefault(d, []).append(i)
        return {d: g for d, g in groups.items() if len(g) > 1}

    def straight_legs(self):
        """(program index, vx, vy) for every program opening with WM_STRAIGHT."""
        out = []
        for i, prog in enumerate(self.progs):
            if prog and prog[0][0] == 0:            # WM_STRAIGHT
                out.append((i, _s8(prog[0][2]), _s8(prog[0][3])))
        return out

    def speeds_used(self):
        return sorted(set(self.trig_speed))

    def __repr__(self):
        return (f"<Level {self.name}: {self.n_triggers} triggers, "
                f"{self.n_defs} definitions, {len(self.progs)} programs, "
                f"{self.pool_bytes}-byte pool>")


def _s8(b):
    return b - 256 if b > 127 else b


# ---------------------------------------------------------------------------
# THE CAMPAIGN SEQUENCE, from the engine that owns it.
# ---------------------------------------------------------------------------
def campaign(root=ROOT):
    """(names, CMP_NAME_LEN) from src/campaign.asm -- the run's level order."""
    src = (Path(root) / "src" / "campaign.asm").read_text(encoding="utf-8")
    width = int(re.search(r"^\s*\.const\s+CMP_NAME_LEN\s*=\s*(\d+)",
                          src, re.M).group(1))
    count = int(re.search(r"^\s*\.const\s+CMP_LEVELS\s*=\s*(\d+)",
                          src, re.M).group(1))
    body = src.split("cmpLevelNames:", 1)[1].split("cmpLevelNamesEnd", 1)[0]
    names = re.findall(r'\.text\s+"([^"]*)"', body)
    if len(names) != count:
        raise SystemExit(f"src/campaign.asm declares CMP_LEVELS = {count} but "
                         f"lists {len(names)} names")
    return names, width


_CACHE = {}


def level(name="level1"):
    """The authored level, parsed once per process."""
    if name not in _CACHE:
        _CACHE[name] = Level(name)
    return _CACHE[name]


if __name__ == "__main__":                       # a readable dump, for humans
    for nm in campaign()[0]:
        lv = level(nm.lower())
        print(lv)
        print(f"  rows      {lv.trig_row}")
        print(f"  defs      {lv.trig_def}")
        print(f"  species   {lv.trig_species}")
        print(f"  fire      {[bin(f) for f in lv.trig_fire]}")
        print(f"  colour    {[hex(c) for c in lv.trig_colour]}")
        print(f"  fireMode  {lv.trig_fire_mode}")
        print(f"  speed     {lv.trig_speed}")
        print(f"  dropProg  {lv.trig_drop_prog}")
        print(f"  shared    {lv.shared_definitions()}")
        print(f"  straights {lv.straight_legs()}")
    print(f"\ncapacity: {len(TRIG_COLS)} columns x {TRIG_SLOTS} slots "
          f"= {len(TRIG_COLS) * TRIG_SLOTS} of {C.LEVELPKG_TRIG_RESERVATION} "
          f"reserved bytes; editor ceiling {C.MAX_TRIGGERS}")
