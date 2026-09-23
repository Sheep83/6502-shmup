# level2 — the PCB stage

The second real level. Its terrain is the printed-circuit-board vocabulary
promoted from the `level2pcb` prototype; the palette, charset, metatiles, map,
stage config and encounter data in `level.v6.json` are authoritative and are
authored **in the editor**.

    tools/level_editor/levels/level2/level.v6.json   <- this, the editable source
    src/level2/                                      <- its generated ASM package

`tools/level_editor/gen_level2_pcb.py` is how the PCB tile vocabulary was
originally constructed. It is **no longer the source of truth** and refuses to
write here without `--force`, because doing so would discard every edit made in
the editor since the promotion. Keep it for the tile-contract documentation and
for its edge-contract checks, not as a build step.

## Edit it

```
python3 tools/level_editor/editor.py
```
**File → Open Level** → `tools/level_editor/levels/level2/level.v6.json`.
**File → Rename Level…** changes the level's identity, which is what sets the
default save path and the default export directory.

## Export and build it

```
python3 tools/level_editor/export_level.py \
    --project tools/level_editor/levels/level2/level.v6.json --dest src/level2

make build LEVELDIR=$PWD/src/level2
make run
make build          # IMPORTANT: restores canonical Level 1 into build/
```

That last `make build` matters: `build/` holds whichever level was compiled
last, so leaving it on Level 2 would make the next `make run` and the whole test
suite silently exercise the wrong level.

There is **no runtime Level 1 → Level 2 transition**. `src/levelload.asm` loads
one package named `LEVEL1` once at boot, so a build carries exactly one level.
Selecting a level at runtime is a separate piece of work.

## Encounters

The movement programs, wave definitions and triggers are carried from Level 1
and are not yet authored for this stage. They are here so that real sprites fly
over the terrain. Movement Programs and Wave Definitions are expected to become
repository-scoped shared assets later; nothing here should make that harder.
