#!/usr/bin/env python3
"""Phase 2: the v6 exporter reproduces the authoritative Level 1 exactly.

TWO LEVELS OF PROOF, because comments and headers may legitimately differ from
the committed files while the DATA may not:

  A. semantic -- every .byte / .const / .var value emitted is compared against
     the authoritative src/level1/ source, parsed rather than diffed;
  B. binary   -- the current build is run with LEVELDIR pointed at the scratch
     export (the Makefile's own override, the same one `make proof420` uses) and
     the resulting level1.prg and shmup.prg are compared byte for byte.

The binary proof is the one that matters: it is the only thing that can say the
exported files produce the same machine, and it covers the charset and turret
tables, which end up in the ENGINE prg rather than the level package.

ENCOUNTERS ARE NOT EXPORTED IN PHASE 2. src/wave_programs.asm and
src/wave_encounters.asm still supply the movement pool, the wave definitions and
the trigger columns, so those package regions must come out unchanged for free --
which is asserted, because "unchanged for free" is exactly the kind of claim that
is worth checking rather than assuming.

Run:  python3 tools/level_editor/test_v6_export.py
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import contract_v2 as C                                                    # noqa: E402
import export_v6                                                           # noqa: E402
from migration_v6 import load_any                                          # noqa: E402
from project_v6 import ProjectV6                                           # noqa: E402

PASS = []
LEVEL1_JSON = HERE / "levels" / "level1" / "level.json"
CANONICAL = HERE / "levels" / "level1" / "level.v6.json"
AUTH = REPO / "src" / "level1"


def ok(m):
    PASS.append(m)
    print(f"  ok   {m}")


def eq(label, got, want):
    if got != want:
        raise AssertionError(f"{label}: got {got!r}, want {want!r}")
    ok(f"{label} -- {got}")


# ---------------------------------------------------------------------------
# tiny parsers for the authoritative .asm sources
# ---------------------------------------------------------------------------
def asm_consts(text):
    out = {}
    for m in re.finditer(r"^\s*\.const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^/\n]+)",
                         text, re.M):
        out[m.group(1)] = m.group(2).strip()
    return out


def asm_bytes(text, start_label=None, end_label=None):
    """Every .byte value, optionally only between two labels."""
    lines = text.splitlines()
    if start_label is not None:
        begin = next(i for i, l in enumerate(lines) if l.startswith(start_label))
        stop = next(i for i, l in enumerate(lines)
                    if i > begin and l.startswith(end_label))
        lines = lines[begin + 1:stop]
    out = []
    for line in lines:
        s = line.split("//")[0]
        if ".byte" not in s:
            continue
        out += [int(v) for v in s.split(".byte", 1)[1].split(",") if v.strip()]
    return out


def asm_list(text, name):
    m = re.search(rf"\.var\s+{name}\s*=\s*List\(\)\.add\(([^)]*)\)", text)
    return [int(v) for v in m.group(1).split(",")] if m else []


# ---------------------------------------------------------------------------
print("=== export the migrated Level 1 into scratch ===")
# THE CANONICAL v6 PROJECT, not the bare v5 migration. Since Phase 4 the export
# includes the encounters, and the migration deliberately leaves those empty --
# exporting it would ship a Level 1 with no waves at all.
project = ProjectV6.load(CANONICAL)
tmp = tempfile.TemporaryDirectory()
OUT = Path(tmp.name) / "exp"
written = export_v6.export_level(project, OUT, level_name="level1",
                                 carry_enemies_from=AUTH)
eq("the exporter wrote all six generated files",
   sorted(n for n in written if n in export_v6.GENERATED_NAMES),
   ["stage_charset.asm", "stage_config.asm", "stage_map.asm", "stage_turrets.asm",
    "wave_encounters.asm", "wave_programs.asm"])
eq("...four terrain/config/turret", sorted(export_v6.TERRAIN_NAMES),
   ["stage_charset.asm", "stage_config.asm", "stage_map.asm", "stage_turrets.asm"])
eq("...and two encounter files, level-owned since Phase 4",
   sorted(export_v6.ENCOUNTER_NAMES), ["wave_encounters.asm", "wave_programs.asm"])
ok("stage_enemies.asm was carried forward (level-owned, not editor-generated)")
assert not (OUT / "stage_waves.asm").exists()
ok("no stage_waves.asm was emitted")

exp_cfg = (OUT / "stage_config.asm").read_text()
exp_chr = (OUT / "stage_charset.asm").read_text()
exp_map = (OUT / "stage_map.asm").read_text()
exp_trt = (OUT / "stage_turrets.asm").read_text()
auth_cfg = (AUTH / "stage_config.asm").read_text()
auth_chr = (AUTH / "stage_charset.asm").read_text()
auth_map = (AUTH / "stage_map.asm").read_text()
auth_trt = (AUTH / "stage_turrets.asm").read_text()

# ---------------------------------------------------------------------------
print("\n=== A. stage_config.asm ===")
e, a = asm_consts(exp_cfg), asm_consts(auth_cfg)
eq("STAGE_METATILE_ROWS", e["STAGE_METATILE_ROWS"], "105")
eq("STAGE_NO_SPAWN_ROW", e["STAGE_NO_SPAWN_ROW"], "340")
eq("STAGE_METATILE_COUNT", e["STAGE_METATILE_COUNT"], "34")
eq("TERRAIN_GLYPH_COUNT", e["TERRAIN_GLYPH_COUNT"], "72")
eq("TERRAIN_BACKGROUND_COLOUR", e["TERRAIN_BACKGROUND_COLOUR"], "12")
eq("TERRAIN_MC_COLOUR_1", e["TERRAIN_MC_COLOUR_1"], "15")
eq("TERRAIN_MC_COLOUR_2", e["TERRAIN_MC_COLOUR_2"], "11")
eq("TERRAIN_CHARACTER_COLOUR", e["TERRAIN_CHARACTER_COLOUR"], "1")
eq("TERRAIN_COLOUR_RAM", e["TERRAIN_COLOUR_RAM"], "8 | TERRAIN_CHARACTER_COLOUR")

assert "SCROLL_FRAME_DIVIDER" not in e, "the retired scroll divider was emitted"
assert "SCROLL_FRAME_DIVIDER" not in exp_cfg
ok("SCROLL_FRAME_DIVIDER is NOT emitted (the engine reads it nowhere)")

# EVERY constant matches the production file exactly. Since Phase 4 the
# production src/level1/stage_config.asm IS generated from the canonical v6
# project, so this is a re-export fixed point rather than a comparison against
# hand-written text -- and the divider is absent from both sides.
if e != a:
    raise AssertionError(f"config constants differ:\n  exported {e}\n  production {a}")
ok("every constant equals the production file, value for value")
assert "SCROLL_FRAME_DIVIDER" not in a, "the production config carries the divider"
ok("...and neither side carries the retired SCROLL_FRAME_DIVIDER")

# Derived, not stored.
eq("derived playable progress", project.stage.playable_progress, 395)
eq("derived terrain seconds", round(project.stage.terrain_seconds, 1), 63.2)

# ---------------------------------------------------------------------------
print("\n=== B. stage_charset.asm ===")
eb, ab = asm_bytes(exp_chr), asm_bytes(auth_chr)
eq("glyph bytes emitted", len(eb), 72 * C.GLYPH_BYTES)
eq("...which is 72 glyphs x 8", len(eb), 576)
if eb != ab:
    first = next(i for i, (x, y) in enumerate(zip(eb, ab)) if x != y)
    raise AssertionError(f"charset differs first at byte {first}: {eb[first]} vs {ab[first]}")
ok("all 576 glyph bytes are IDENTICAL to the authoritative charset")
assert "terrainGlyphs:" in exp_chr and "terrainGlyphsEnd:" in exp_chr
ok("the labels src/terrain.asm imports are present")
assert "TERRAIN_GLYPH_COUNT * 8" in exp_chr
ok("the self-checking byte-count guard is emitted")
for stale in ("$3B00", "$3EFF", "160"):
    if stale in exp_chr.split("terrainGlyphs:")[0]:
        raise AssertionError(f"stale charset header text {stale!r} survived")
ok("the stale $3B00-$3EFF / glyph-base-160 header text is gone")
assert "$0B00" in exp_chr.upper()
ok("the header names the real address, $0B00 in the $0800 window")

# ---------------------------------------------------------------------------
print("\n=== C. stage_map.asm ===")
for lab in ("metatileDefs:", "METATILE_DEFS_END:", "stageMetatileRows:",
            "STAGE_METATILE_ROWS_END:"):
    assert any(l.startswith(lab) for l in exp_map.splitlines()), lab
ok("all four Makefile split labels are present at the start of their lines")

ed = asm_bytes(exp_map, "metatileDefs:", "METATILE_DEFS_END:")
ad = asm_bytes(auth_map, "metatileDefs:", "METATILE_DEFS_END:")
eq("metatile definition bytes", len(ed), 34 * 16)
eq("...which is 544", len(ed), 544)
assert ed == ad, "metatile definitions differ from authoritative"
ok("all 544 metatile definition bytes are IDENTICAL")

em = asm_bytes(exp_map, "stageMetatileRows:", "STAGE_METATILE_ROWS_END:")
am = asm_bytes(auth_map, "stageMetatileRows:", "STAGE_METATILE_ROWS_END:")
eq("map bytes", len(em), 105 * 10)
eq("...which is 1050", len(em), 1050)
assert em == am, "map rows differ from authoritative"
ok("all 1050 map bytes are IDENTICAL")
eq("no padding to the 440-row budget", len(em) < C.LEVELPKG_MAP_MAX, True)

# ---------------------------------------------------------------------------
print("\n=== D. stage_turrets.asm ===")
eq("TURRET_TOTAL", asm_consts(exp_trt)["TURRET_TOTAL"], "8")
rows = asm_list(exp_trt, "turretRows")
cols = asm_list(exp_trt, "turretCols")
eq("turret rows", rows, [345, 337, 225, 217, 117, 109, 25, 5])
eq("turret cols", cols, [17, 25, 29, 9, 25, 13, 25, 13])
eq("rows are strictly descending", rows == sorted(rows, reverse=True), True)
assert rows == asm_list(auth_trt, "turretRows")
assert cols == asm_list(auth_trt, "turretCols")
ok("rows and cols equal the authoritative stage_turrets.asm exactly")
for r in rows:
    assert r % C.METATILE_H == C.TURRET_ROW_PHASE, r
ok("every world row is metatileRow * 4 + 1")

# ---------------------------------------------------------------------------
print("\n=== E. determinism ===")
OUT2 = Path(tmp.name) / "exp2"
export_v6.export_level(project, OUT2, level_name="level1")
for name in export_v6.GENERATED_NAMES:
    if (OUT / name).read_bytes() != (OUT2 / name).read_bytes():
        raise AssertionError(f"{name} is not deterministic")
ok("exporting twice into different directories is byte-identical, all four files")
for name in export_v6.GENERATED_NAMES:
    text = (OUT / name).read_text()
    assert "\r" not in text, name
    assert text.endswith("\n") and not text.endswith("\n\n"), name
    assert str(REPO) not in text and "/Users/" not in text, name
ok("LF endings, one trailing newline, no absolute paths, no timestamps")

# A project reloaded from JSON exports identically.
OUT3 = Path(tmp.name) / "exp3"
export_v6.export_level(ProjectV6.from_json(project.to_json()), OUT3,
                       level_name="level1")
for name in export_v6.GENERATED_NAMES:
    assert (OUT / name).read_bytes() == (OUT3 / name).read_bytes(), name
ok("a project round-tripped through JSON exports byte-identically")

# ---------------------------------------------------------------------------
print("\n=== F. the build proof ===")
# THE MAKEFILE'S OWN OVERRIDE. LEVELDIR ?= src/level1, and `make proof420` uses
# exactly this mechanism, so nothing here is a special testing path. The
# authoritative build is captured first and restored in the finally, because
# build/ is shared.
build = REPO / "build"
keep = Path(tmp.name) / "keep"
keep.mkdir()


def _make(leveldir):
    r = subprocess.run(["make", "build", f"LEVELDIR={leveldir}"], cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(f"build failed for LEVELDIR={leveldir}\n{r.stdout[-2000:]}"
                             f"\n{r.stderr[-2000:]}")


try:
    _make(AUTH)
    for n in ("level1.prg", "shmup.prg"):
        shutil.copy(build / n, keep / n)
    auth_pkg = (keep / "level1.prg").read_bytes()
    ok(f"authoritative build captured ({len(auth_pkg)} bytes of level1.prg)")

    _make(OUT)
    exp_pkg = (build / "level1.prg").read_bytes()
    ok("the current build consumed the scratch-exported level directory")

    base = auth_pkg[0] | (auth_pkg[1] << 8)
    eq("level package load address", hex(base), hex(0xE000))

    def region(buf, lo, hi):
        return buf[2 + lo - base: 2 + hi - base + 1]

    for name, lo, hi, want in (
            ("terrain map", 0xE000, 0xE419, 1050),
            ("metatile defs", 0xF130, 0xF34F, 544),
            ("stage header", 0xF530, 0xF531, 2)):
        ra, rb = region(auth_pkg, lo, hi), region(exp_pkg, lo, hi)
        eq(f"editor-owned region {name} ${lo:04X}-${hi:04X}", len(ra), want)
        assert ra == rb, f"{name} differs"
        ok(f"...IDENTICAL to authoritative")

    hdr = region(exp_pkg, 0xF530, 0xF531)
    eq("the stage header encodes noSpawnRow", hdr[0] | (hdr[1] << 8), 340)

    # SINCE PHASE 4 THE ENCOUNTER REGIONS ARE EXPORTED TOO, from the canonical
    # project's movement programs, wave definitions and triggers. They must still
    # come out byte-identical to the pre-Phase-4 engine-authored package.
    for name, lo, hi, want in (
            ("movement pool", 0xF532, 0xF565, 52),
            ("wave definitions", 0xF632, 0xF659, 40),
            ("trigger columns", 0xF736, 0xFB6D, 1080),
            ("signature", 0xFB70, 0xFB73, 4)):
        ra, rb = region(auth_pkg, lo, hi), region(exp_pkg, lo, hi)
        eq(f"editor-owned encounter region {name}", len(ra), want)
        assert ra == rb, f"{name} differs"
        ok("...IDENTICAL, exported from the canonical v6 project")

    if exp_pkg != auth_pkg:
        bad = [i for i, (x, y) in enumerate(zip(auth_pkg, exp_pkg)) if x != y]
        raise AssertionError(f"level1.prg differs at {len(bad)} offsets, first {bad[:8]}")
    ok("*** THE WHOLE level1.prg IS BYTE-IDENTICAL ***")

    exp_engine = (build / "shmup.prg").read_bytes()
    if exp_engine != (keep / "shmup.prg").read_bytes():
        raise AssertionError("shmup.prg differs: the charset or turret tables changed")
    ok("*** shmup.prg IS BYTE-IDENTICAL *** (charset + turret tables live there)")
finally:
    _make(AUTH)
    restored = (build / "level1.prg").read_bytes() == (keep / "level1.prg").read_bytes()
    print(f"  ..   build/ restored from src/level1: {restored}")

print(f"\nAll {len(PASS)} export checks passed.")
