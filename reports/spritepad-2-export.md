# Export existing engine sprites to SpritePad 2.0

43 sprites exported to a structurally valid SpritePad 2.0 project. Every one of
the 2,709 payload bytes reads back out of the file identical to the bytes the
VIC fetches. The game build is byte-identical, both levels are untouched, and
no reverse pipeline exists.

**Final acceptance is still yours**: open `assets/sprites/19656-sprites.spd` in
Spritemate and confirm the sprites display and edit correctly.

---

## 1. Starting state

| | |
|---|---|
| HEAD | `a931958bb1657474b159267b83f1f03d9fd53e5e` |
| Branch / upstream | `main` … `origin/main`, in sync |
| Working tree at start | **clean** |
| VICE running | none (and none was launched — this task needs no emulator) |

---

## 2. Audit: where the sprites actually are

`src/main.asm` carries the authoritative VIC-bank memory map, and it is where
the audit started — but **two of its comments are stale**, which is exactly why
the binary was checked rather than trusted:

* it calls `$25c0-$27ff` "free, 9 blocks", yet `playerBoomArt` is assembled there;
* it calls `$3580-$367f` "the Ring's former pinned home … Kept EMPTY", yet
  `bossArt` is assembled there.

Both were confirmed against `build/main.vs` and against non-zero data in
`build/shmup.prg`. (Noted for your records; nothing was changed.)

### How the bytes are produced

Three different mechanisms, which is what settled the extraction strategy:

| Mechanism | Example |
|---|---|
| literal `.byte` rows | `enemy_art.asm`, `enemy_dropper_art.asm` |
| rows a header says were **row-replicated** 16→21 by a deterministic mapping | `player_art.asm` |
| bytes produced entirely by **assembler functions inside `.for` loops** | `hud.asm`'s `livesByte(n,r,c)` / `pchargeByte(n,r,c)` |

Re-parsing `.asm` would mean re-implementing KickAssembler and would be simply
wrong for the third kind. So the exporter reads **the assembled program at the
addresses the symbol file reports** — by definition what the VIC fetches.

### Runtime authority

`levelAssetsLoad` (`src/level_assets.asm`) was checked in case enemy art is
copied into the window at run time. It is not: it resolves **sprite pointers**
into `enemyAnimSeq`. Every sprite bitmap in this game is static in the PRG, so
there is no runtime-assembled artwork to miss.

### Complete inventory

**Exported — 43 logical sprites, all multicolour:**

| Index | Symbol | Blocks | Role | `$d027` | Address | Pointers |
|---|---|---|---|---|---|---|
| 0–15 | `player_art_frames` | 16 | player ship | 14 | `$2000-$23ff` | `$80-$8f` |
| 16–20 | `playerFlashBitmaps` | 5 | muzzle flash | 2 | `$2400-$253f` | `$90-$94` |
| 21 | `tokenBitmap` | 1 | collectible token | 1 | `$2580-$25bf` | `$96` |
| 22–29 | `playerBoomArt` | 8 | player death fireball | 2 | `$25c0-$27bf` | `$97-$9e` |
| 30–33 | `sonicRingFrames` | 4 | enemy: Sonic Ring | 13\* | `$2c00-$2cff` | `$b0-$b3` |
| 34–37 | `orbitalDropperFrames` | 4 | enemy: Orbital Dropper | 13\* | `$2d00-$2dff` | `$b4-$b7` |
| 38–41 | `bossArt` | 4 | boss | 4 | `$3580-$367f` | `$d6-$d9` |
| 42 | `ebulletBitmap` | 1 | hostile projectile | 7 | `$36c0-$36ff` | `$db` |

\* per-wave, not fixed — see §5.

**Animation/frame relationships.** Player = 5 banking attitudes × 3 engine
frames, bank-major (`index = bank*3 + engine`), plus one blank. Muzzle flash =
one per attitude. Ring and Dropper = 4 rotation frames each. Boom = 8-frame
sequence. Boss = 4 cells of one larger machine. Token/ebullet = single images.

**Aliases and duplicates: none.** All 43 payloads are unique — verified by
hashing, not assumed. One block (`ship_blank_hw1`, index 15) is a **deliberate
blank**: `PLAYER_BLOCKS = 5*3 + 1` and `PLAYER_PTR_BLANK = PLAYER_PTR_FIRST + 15`.
It is exported as a logical entry rather than dropped, because the engine
addresses player frames by pointer and removing it would renumber every
following block.

**Obsolete/dead sprite data: none found.** The 12 unused blocks at the tail of
the enemy sprite window (`$2e00-$30ff`) are spare capacity in a 20-block window,
not orphaned artwork.

### Inventoried but deliberately not exported

`hudBitmaps` (`$3200`, 14 blocks) — the only other sprite memory with a symbol:

* blocks 0–3 (heat L/R, score L/R) are `.fill 64, 0` in the source and drawn
  into by the CPU every frame. They are **zero in the binary**: framebuffers,
  not pictures. Exporting four blank sprites would be actively misleading.
* blocks 4–13 (lives 0–5, upgrade 0–3) are emitted by `livesByte()` /
  `pchargeByte()` inside `.for` loops, so they are **regenerated from code on
  every build** — a pixel edited in Spritemate could not survive.

They are also the game's **only hires sprites**, so including them would make
the project mixed-mode for no gain. The omission is recorded in the manifest's
`excluded` array, so it is a decision rather than an oversight.

---

## 3. SpritePad 2.0 format — established, not guessed

Evidence, in order of authority:

1. **Spritemate's own source** — the editor you will open the file in, so its
   writer defines what it reads back. `src/js/Save.ts` carries the layout as a
   comment and then emits exactly it:

   ```
   // bytes 00,01,02 = "SPD"
   // byte 03 = version number of spritepad
   // byte 04 = number of sprites
   // byte 05 = number of animations
   // byte 06 = color transparent
   // byte 07 = color multicolor 1
   // byte 08 = color multicolor 2
   // byte 09 = start of sprite data
   // byte 73 = 0-3 color, 4 overlay, 7 multicolor/singlecolor
   // bytes xx = "00","00","01","00" added at the end of file

   data.push(83, 80, 68);                              // "SPD"
   data.push(1, this.savedata.sprites.length - 1, 0);  // version, count-1, anims
   ...
   data.push(0, 0, 1, 0);   // SpritePad animation info (currently unused)
   ```

2. **Spritemate's parser** — `src/js/Load.ts` reads it back with
   `start_of_sprite_data = 6`, `number_of_sprites = file[4] + 1`, shared colours
   at 6/7/8, sprite *n*'s bitmap at `9 + 64n` and its metadata byte at
   `9 + 64n + 63`.

3. **Three real `.spd` files** shipped in that repository's `examples/`. All
   three satisfy the derived length law **exactly**, which is what pins the
   trailing section down:

   | File | Sprites | Animations | Length | `9 + 64·N + 4 + 4·A` |
   |---|---|---|---|---|
   | Antiriad | 162 | 26 | 10,485 | 10,485 ✓ |
   | Armalyte | 122 | 16 | 7,885 | 7,885 ✓ |
   | Io | 103 | 18 | 6,677 | 6,677 ✓ |

### The format

```
offset 0..2    "SPD"
offset 3       version byte, 1 = SpritePad 2.0
offset 4       sprite count MINUS ONE  (so max 256 sprites)
offset 5       animation count
offset 6       colour: transparent / background   ($d021)
offset 7       colour: multicolour 1              ($d025, bit-pair 01)
offset 8       colour: multicolour 2              ($d026, bit-pair 11)
offset 9..     N blocks of 64 = 63 bitmap bytes + 1 metadata byte
               metadata: bit 7 multicolour, bit 4 overlay, bits 0-3 sprite colour
then           4-byte animation preamble (00 00 01 00) + 4 bytes per animation
EOF
```

**1.8 vs 2.0:** the old format has **no signature at all** — three colour bytes
followed by N 64-byte blocks, count inferred as `(len - 3) / 64`. Spritemate
distinguishes them with `file.startsWith("SPD")`. 2.0 was chosen because it
carries an explicit count and version and Spritemate reads both.

**No per-sprite names.** SpritePad 2.0 has no string table — the 64th byte is
colour/mode/overlay and nothing else. None of the three reference files carries
names, and Spritemate synthesises `"sprite1"`, `"sprite2"`… on load. Rather than
invent a private extension real SpritePad would not understand, names live in
the adjacent manifest (§6).

**No bytes were invented.** Everything written is either in the layout comment,
in the emitting code, or confirmed by all three reference files.

---

## 4. Exporter architecture

`tools/sprite_export/`, Python 3 standard library only:

| File | Role |
|---|---|
| `sprite_source.py` | authoritative extraction from `build/shmup.prg` + `build/main.vs` |
| `spd_writer.py` | SpritePad 2.0 serialiser |
| `spd_reader.py` | **independent** strict parser |
| `export_spd.py` | CLI: extract → write → verify → manifest |
| `contact_sheet.py` | optional visual diagnostic (needs Pillow) |
| `test_spd_export.py` | 66 checks |

```
build/shmup.prg + build/main.vs
    -> sprite_source.extract()    63 bytes/sprite, counts PROVED against symbols
    -> spd_writer.build()         SpritePad 2.0
    -> spd_reader.parse()         an independent parse of what we wrote
    -> byte-for-byte comparison   against the extractor's own bytes
```

**No second copy of any artwork exists.** The only hand-declared thing is the
group table — which run of blocks is what, its mode and its colour — and every
entry is cross-checked against the build before use:

* groups with an end symbol (`playerFlashBitmapsEnd`, `playerBoomArtEnd`,
  `sonicRingFramesEnd`, `orbitalDropperFramesEnd`, `bossArtEnd`) must land on it
  exactly;
* `player_art_frames` has no end symbol, so its 16 blocks must end exactly where
  `playerFlashBitmaps` begins;
* every base address must be 64-byte aligned;
* every bitmap must be exactly 63 bytes and the 64th byte is kept separate.

Corrupting any of those raises `SpriteSourceError` rather than exporting — and
each refusal is tested.

**Writer/reader independence.** `spd_reader.py` imports nothing from
`spd_writer.py`. Its offsets, constants and length arithmetic are written out
again from the format description, so "it reads back correctly" is a real claim
rather than one serialiser agreeing with itself. The reader was additionally
validated by parsing all three real SpritePad files under strict length
checking before it was used to verify anything of ours.

---

## 5. Colour semantics

| Register | Source | Value |
|---|---|---|
| `$d021` background | `gameInit` sets 0; terrain then sets the level's | **0** exported |
| `$d025` multicolour 1 (pair 01) | `SPR_MC_DARK` (`src/main.asm:272`) | **11** dark grey |
| `$d026` multicolour 2 (pair 11) | `SPR_MC_LIGHT` (`src/main.asm:273`) | **1** white |
| `$d027+n` per sprite (pair 10) | per subsystem | see below |
| `$d01c` mode | `D01C_GAMEPLAY` | **all gameplay sprites multicolour** |

Bit-pair meaning, which is what makes the packed representation transferable:
`00` transparent · `01` `$d025` · `10` the sprite's own `$d027+n` · `11` `$d026`.
This maps 1:1 onto SpritePad's three shared colours plus per-sprite colour, so
**the packed two-bit data is carried through unchanged** — nothing is rendered
and reconstructed.

Mode is not guessed: `src/renderer.asm` sets `D01C_GAMEPLAY` for all six mux
slots plus the player's two and asserts *"the gameplay phase's `$d01c` leaves a
mux slot in hires"*. The HUD's are the only hires sprites and are excluded.

### Runtime behaviour SPD cannot express

SpritePad stores **one** colour per sprite. Where the runtime varies it, the
authored/primary value is exported and the manifest records what really happens:

| Sprite | Exported | Runtime reality |
|---|---|---|
| Sonic Ring, Orbital Dropper | **13** | **No fixed colour.** Pair 10 is the *wave's* authored colour. Level 1 authors 10, 3, 7, 13 and 1. 13 was chosen because it is an authored value and differs from both shared multicolours, so all four pens stay distinguishable while editing. |
| boss | **4** | `BOSS_COL=4` purple; flashes to `BOSS_COL_HIT=1` white while taking a hit. |
| token | **1** | Pulses `PICKUP_P_COL_LIT=1` ↔ `PICKUP_P_COL_DARK=15` as a brightness flash. Note 1 also equals `$d026`, so pairs 10 and 11 will look identical on this one sprite in the editor — that is the true lit-phase appearance, not an export fault. |
| player blank (15) | **0** | `PLAYER_COL_BLANK`; HW1 draws nothing. |

**Background = 0** is an editing backdrop only. The game writes `$d021` twice:
`gameInit` leaves it black, then terrain sets the level's background (12 for
Level 1, 5 for Level 2). No single value is true for both levels; black is what
the engine initialises to and what all three reference files use. **It is not
part of any sprite's 63 bytes**, so bitmap fidelity is unaffected.

---

## 6. Output

| Path | Size |
|---|---|
| `assets/sprites/19656-sprites.spd` | **2,765 bytes** |
| `assets/sprites/19656-sprites.json` | 18,382 bytes |

`9 + 64×43 + 4 = 2765` ✓

**No superior asset convention exists** — the repository had no `assets/`,
`art/` or `gfx/` directory (only `src/mnt/data/` holding a single ad-hoc PNG),
so the brief's suggested path was used and establishes the convention.

One combined project, not many files: all 43 sprites share one palette and one
mode, so a single SpritePad project is the natural unit and keeps indices
contiguous.

The manifest records, per sprite: index, name, role, source symbol, address,
VIC sprite pointer, mode, colour, the runtime-colour note, whether it is blank,
and `duplicateOf` — plus the bit-pair legend and the `excluded` list.

---

## 7. Verification

### Read-back (mandatory)

```
sprites          43
payload bytes    2709 compared (43 x 63)
mismatches       0
```

`authoritative engine bytes → SPD writer → .spd on disk → independent SPD
reader → identical 63 bytes`, for all 43. Modes, per-sprite colours, all three
shared colours, the overlay bit and the total file length were all checked too.

### Determinism

```
byte-identical on re-run (spd and manifest)
sha256  9d4b752266f28138c8a6b8f5abd966e0b30ca3254abd02fa2f54ea476aa3d328
```

Two independent extract+build passes produce identical bytes. There is no
timestamp, path or ordering nondeterminism in the output.

### Visual sanity proof (§8, optional)

`contact_sheet.py` renders all 43 sprites twice — once from the authoritative
engine bytes, once from the bytes parsed back out of the `.spd` — expanding the
C64 encoding with no scaling, mirroring or recolouring:

```
rendered 43 sprites twice
pixels compared  21672
differing pixels 0
```

Sheet: `reports/spritepad-2-export/contact-sheet.png`. The ship's 15 attitudes,
the blank block, five muzzle flashes, the "P" token, the 8-frame fireball, the
Ring and Dropper rotations, the four boss cells and the projectile are all
present and correct.

---

## 8. Build and level preservation

Hashed before any file was added, and again after everything:

```
0f82cf55604652412ad7713109be47f6768d50827a9a7f294fc3bd7b1c8d7cb4  build/shmup.prg    OK
1d8667c75b8558e91ee03cafccfabfd2a7ef6d77dcd361db2fc65975ca61b371  build/level1.prg   OK
184c328647dcf54e273a427fde945c5e2fa5f3a8b18768f3e86577cce1c4d889  build/shmup.d64    OK
```

**All three byte-identical**, as they must be — nothing in the build consumes a
`.spd`. No difference to investigate.

**Level 1 and Level 2 untouched.** `git status` reports no modification to
`src/level1/`, `src/level2/` or `tools/level_editor/levels/`, and none anywhere
under `src/`. This is additionally enforced as a *behavioural* test: the suite
hashes every `.asm` under `src/` and both level projects, runs the exporter for
real, and re-hashes.

---

## 9. Tests

**`tools/sprite_export/test_spd_export.py` — 66 checks, all passing.**

Expected values do not duplicate the writer. Reader tests parse a
**hand-assembled** byte literal the writer never produced; writer tests check
properties it cannot satisfy by accident (`len == 9 + 64n + 4`, signature,
count-minus-one, tail); round-trip tests use synthetic sprites neither component
chose.

| Area | Covers |
|---|---|
| reader | hand-built file, count+1 rule, shared colours, payloads, bit 7 mode, bit 4 overlay, low-nibble colour |
| reader rejection | no signature, bad version, truncated, trailing junk, count/length mismatch, bad colour, empty |
| writer | length law at 1/2/43/256 sprites, signature, version, count-1, animations, colour placement, tail |
| writer rejection | empty list, >256 sprites, 62- and 64-byte bitmaps, out-of-range sprite and shared colours |
| round trip | count, every payload, every mode, every colour, shared colours (mixed MC/hires) |
| extraction | 63 bytes each, 64-byte alignment, pointer = addr/64, dense ordering, unique names, stable group order, pad byte separate and unused, all multicolour, valid colours, blank block kept |
| extraction rejection | count vs end symbol, missing symbol, misaligned sprite, missing symbol file |
| aliases | duplicates reported not collapsed; identical payloads map to first occurrence |
| CLI | `--check` writes nothing; unknown argument refused |
| determinism | two runs identical |
| on disk | the `.spd` parses, matches a fresh export, every payload equals engine bytes, modes/colours match |
| one-way | Makefile doesn't consume `.spd`, no `.asm` references one, running the exporter leaves `src/` and both level projects byte-identical |

---

## 10. Files added, changed, deleted

**Added** (all untracked):

```
assets/sprites/19656-sprites.spd          the SpritePad 2.0 project
assets/sprites/19656-sprites.json         names / provenance manifest
tools/sprite_export/sprite_source.py      authoritative extraction
tools/sprite_export/spd_writer.py         SpritePad 2.0 writer
tools/sprite_export/spd_reader.py         independent reader
tools/sprite_export/export_spd.py         CLI
tools/sprite_export/contact_sheet.py      optional visual diagnostic
tools/sprite_export/test_spd_export.py    66 checks
reports/spritepad-2-export.md             this report
reports/spritepad-2-export/contact-sheet.png
```

**Changed: none. Deleted: none.** No engine source, level data, Makefile or
build behaviour was modified.

---

## 11. Known limitations

* **One colour per sprite.** The Ring, Dropper, boss and token vary their
  `$d027` at run time; the exported value is an authored/primary choice
  (§5). Bitmaps are unaffected.
* **Token colour collides with `$d026`.** Exporting the token's lit value (1)
  means pairs 10 and 11 render alike on that one sprite in the editor. That is
  its true lit-phase appearance; the dark phase (15) would separate them.
* **No names in the file.** SpritePad 2.0 has no name field; Spritemate will
  show `sprite1`…`sprite43`. The manifest is the mapping — index *n* in the
  `.spd` is `sprites[n]` in the JSON.
* **HUD sprites excluded** (§2). Adding them would need a second, hires project.
* **The exporter needs a build.** It reads `build/shmup.prg` and
  `build/main.vs`, so `make build` must have run. It says so when they are missing.
* **The group table is hand-declared.** Adding a new sprite run to the engine
  needs one entry here; the count assertions make a stale table fail loudly
  rather than silently export the wrong thing.
* **Not yet opened in Spritemate.** Structural validity is proven mechanically
  against Spritemate's own reader semantics and three real files, but the final
  acceptance is yours.

---

## 12. Scope confirmations

* **SPD has NOT become authoritative.** The engine's `.asm` sprite data remains
  the single source of truth. The `.spd` is a derived view.
* **No SpritePad → game importer was implemented.** Nothing reads a `.spd` into
  the game, no Makefile change consumes one, no sprite definition was replaced
  and no engine sprite data was regenerated. Three tests assert this.
* The exporter is shaped so a later importer is straightforward: the group
  table already records address, pointer, count, mode and colour for every run,
  which is exactly what a writer back into `.asm` would need.

---

## 13. Hygiene

**Processes.** No VICE was launched — this task needs no emulator. `pgrep -fl
x64sc` was empty at the start and nothing was started since. No `pkill`/`killall`.

**Disk.**

| Path | Size |
|---|---|
| `assets/` | 24K |
| `tools/sprite_export/` | 100K |
| `reports/spritepad-2-export/` | 8.0K |
| `build/` | 300K (unchanged; no per-run directories) |

Scratch (`/tmp/spm_probe`, the downloaded reference files and the determinism
copies) is disposable and outside the repository.

**Final `git status`:**

```
?? assets/
?? reports/spritepad-2-export/
?? tools/sprite_export/
```

Three new untracked directories; nothing modified, nothing deleted.

**Nothing was committed and nothing was pushed.**

---

## Acceptance gate

| # | Criterion | Status |
|---|---|---|
| 1 | structurally valid SpritePad 2.0 per a mechanically established spec | ✅ §3 |
| 2 | every 63-byte payload reads back identically | ✅ 43/43, 2,709 bytes, 0 mismatches |
| 3 | modes/colours correct or limitations documented | ✅ §5, §11 |
| 4 | output deterministic | ✅ byte-identical on re-run |
| 5 | game build unchanged | ✅ all three hashes OK |
| 6 | Level 1 unchanged | ✅ |
| 7 | Level 2 unchanged | ✅ |
| 8 | no reverse/import pipeline | ✅ asserted by test |
| 9 | nothing committed or pushed | ✅ |

Sources for the format: [Spritemate (Esshahn/spritemate)](https://github.com/Esshahn/spritemate) — `src/js/Save.ts`, `src/js/Load.ts` and `examples/*.spd`; [CSDb: Details of the SpritePad SPD format](https://csdb.dk/forums/?roomid=7&topicid=125812).
