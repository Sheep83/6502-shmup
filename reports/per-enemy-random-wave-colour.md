# Per-Enemy Random Wave Colour

**A Wave Definition can now ask for a random individual colour per enemy, chosen once at spawn from the colours the resident level leaves safe.**

**One spare bit in a byte that was already full, ~60 bytes of 6502, the full Tkinter → JSON → exporter → runtime path, and two authored waves switched over so it can be seen. Nothing committed.**

---

## 1. What the existing representation turned out to be

A wave definition is **ten bytes**, and byte 7 was already carrying two things:

```
bits 0-3   the C64 colour, 0..15          WAVEDEF_COLOUR_MASK = $0f
bits 4-5   the firing mode                WAVEDEF_FIRE_BITS   = $30  (AIMED = $10)
bits 6-7   nothing
```

The ten is not arbitrary. `waveDefBase` forms `def * 10` as a shift-and-add in a
single byte (`n*8 + n*2`), so an eleventh byte would cap a level at 24
definitions instead of 26 and turn that into a multiply. That is why the firing
mode went into the colour byte's spare nibble in the first place, and it is the
same reason the colour mode could not have a byte of its own either.

The full path, established before choosing anything:

| stage | where | what it holds |
|---|---|---|
| authoring | `tools/level_editor/encounters_ui.py` | a colour entry and a firing combobox |
| model | `project_v6.WaveDefinition` | `colour: int`, `fire_mode: str` |
| persistence | `encounter_library.v6.json` | **the shared library**, not the level file |
| validation | `validation_v6.py` | colour 0..15, fire mode in `FIRE_MODES` |
| export | `export_v6.py` | `colour \| FIRE_MODES[mode] << 4` |
| package | `src/level1/wave_encounters.asm` → `src/level_package.asm` | the ten bytes |
| runtime | `waveSpawnMember` | `and #WAVEDEF_COLOUR_MASK` → `logCol`, `wmBaseCol` |

Wave definitions live in the **shared encounter library**, not in
`levels/<name>/level.v6.json` — the level file carries only triggers. That
matters here: switching a definition to random changes it for every level that
uses it.

---

## 2. The encoding, and why it cannot collide

**Bit 6 of byte 7.** `WAVEDEF_COL_RANDOM = $40`.

A sentinel colour was considered and rejected. **All sixteen low-nibble values
are real C64 colours and every one of them is authored somewhere in the
library**, so "colour 16 means random" has nowhere to live; and bits 4-5 are the
firing mode, where a third mode would still be inside `$30`. Bit 6 is outside
both fields and has never been written by anything.

Old packages are safe by the same argument that made the firing mode safe:
validation has always held colour to 0..15 and mode to 0..1, so **every byte
ever exported is at most `$1f`** and has bit 6 clear — which reads as FIXED,
exactly what it already meant.

Three guards make that structural rather than a promise:

```asm
// the fields must be disjoint or the byte means two things at once
.if ((WAVEDEF_COLOUR_MASK & WAVEDEF_FIRE_BITS) != 0
     || (WAVEDEF_COLOUR_MASK & WAVEDEF_COL_RANDOM) != 0
     || (WAVEDEF_FIRE_BITS & WAVEDEF_COL_RANDOM) != 0) {
    .error "the colour, firing-mode and random-colour fields overlap in one byte"
}
```

```asm
// and no authored byte may set bit 7, which nothing reads
.if (def.get(7) > WAVEDEF_COLOUR_MASK + WAVEDEF_FIRE_BITS + WAVEDEF_COL_RANDOM) {
    .error "a wave definition's colour byte has a bit outside colour, firing mode and random colour"
}
```

**The authored colour is kept, not cleared.** A RANDOM definition still carries
its colour in the low nibble, so switching to random and back returns the colour
that was there. The runtime simply stops reading it.

The case that would expose a collision is a wave that is **random and aimed at
once**, and level 1 now has one: `sweep` exports as **`$5a` = 10 | $10 | $40**,
and the runtime test reads back colour 10, mode AIMED, random set — all three
recovered from the one byte.

---

## 3. The exclusion set, and where each value comes from

Built **once per level**, as an explicit set:

```asm
wvColPool:   .fill 16, 0    // the eligible colours, packed low
wvColCount:  .byte 0        // 12..15 of them
wvColBan:    .fill 4, 0     // the four exclusions
```

| excluded | read from | why |
|---|---|---|
| black | the constant 0 | a black enemy on a dark playfield is an invisible enemy |
| shared multicolour 1 | **`$d025`**, masked `$0f` | pair 01 of every multicolour sprite — an enemy wearing it loses its shading |
| shared multicolour 2 | **`$d026`**, masked `$0f` | pair 11 — it loses its highlight |
| terrain charset colour | **`trnCramValue`**, masked `$07` | the busiest colour in the playfield; an enemy wearing it vanishes into the scenery |

**Read, never assumed.** The two sprite multicolours come from the registers
rather than from `SPR_MC_DARK`/`SPR_MC_LIGHT`, and the charset colour from
`trnCramValue` rather than `TERRAIN_CHARACTER_COLOUR` — because a compile-time
constant is the colour of whatever level the *engine* was built against. That is
exactly the bug that turned level 2's PCB terrain grey (`terrainInit`, in
`src/terrain.asm`), and it is worth not repeating.

**`$d021`, the background, is deliberately not excluded**, and the routine says
so: bit pair 00 of the terrain art is transparent, so on a detailed playfield
the background is mostly covered, and removing its colour would cost a usable
one for little gain.

**The player's colour is deliberately eligible**, as required. An enemy the same
colour as the ship is still a different shape in a different place.

### Proof that the set really is the level's

This is the claim a plausible-but-wrong implementation would also seem to
satisfy, so it is measured rather than argued. Level 1's charset colour is 1 —
which is *also* the shared highlight — so its pool is **13**. Level 2 asks for 7,
a colour level 1 allows, so its pool is **12**:

```
level 1   bans [0, 11, 1, 1]   pool (13) [2,3,4,5,6,7,8,9,10,12,13,14,15]
level 2   bans [0, 11, 1, 7]   pool (12) [2,3,4,5,6,8,9,10,12,13,14,15]
                        ^                            ^
                 the new terrain colour        7 is gone
```

Taken across the production level transition (`levelLoadRuntime` →
`gsEnterNextLevel`), not synthesised. A pool built from constants would be
identical in both.

### When it is built

`waveColourPool` is called at the end of `waveInit`, which `gameInit` calls on
the **boot path** (`src/main.asm`) and the **level-change path**
(`gsEnterNextLevel`) alike — in both cases after `terrainApplyPackage` has
installed the palette, and after `$d025`/`$d026` are written at entry. One call
site, both paths, no new ordering to get wrong.

---

## 4. Selection: bounded, with no retry loop

```asm
waveRandomColour:
    jsr gsRandom8                       // X, Y preserved
    and #$0f                            // 0..15
    cmp wvColCount
    bcc !pick+
    sbc wvColCount                      // carry set by the cmp that got here
!pick:
    tay
    lda wvColPool,y
    rts
```

**One conditional subtraction, never a loop.** A nibble is 0..15 and the pool is
12..15 long, so a value off the end is folded back with a single subtraction —
and one is always enough because `15 - count < count` whenever count exceeds
seven. The pool cannot be shorter than twelve: there are four exclusions, each
masked into range before use, and duplicates among them only make it longer.

**The fold is slightly biased and that is deliberate.** With a pool of twelve the
first four entries come up twice as often as the rest. Removing the bias costs a
rejection loop; the thing being decided is which of a dozen colours a spaceship
is. Recorded rather than hidden.

Pool construction is likewise bounded: exactly sixteen iterations, four compares
each, once per level.

---

## 5. RNG

The project already had one — `gsSeed`, stirred inline in `gsRandomLetter` for
placeholder hiscore initials. It is now a named routine, `gsRandom8`, with
`gsRandomLetter` as a caller: **one RNG, one seed byte, two users.**

The step did have to change, and this is the one place I went slightly beyond
"add a feature". The old feedback was:

```asm
lda gsSeed / asl / eor gsSeed / eor $dc04
```

That is an affine map with no feedback from the bit the shift drops, and **with
a stationary `$dc04` it has a fixed point at zero** — the sequence can stop dead.
It never showed, because the only caller ran eight times at boot with the CIA
free-running. A per-spawn caller during gameplay, where `installRenderer` has
written `$dc0d` and nobody is looking at the timer, would have been betting a
visible feature on that. So:

```asm
gsRandom8:
    lda gsSeed
    asl
    bcc !noTaps+
    eor #$1d                    // x^8 + x^4 + x^3 + x^2 + 1, maximal period 255
!noTaps:
    eor $dc04                   // kept as an extra stir, not the only change
    bne !live+
    lda #$a5                    // zero is the LFSR's one absorbing state
!live:
    sta gsSeed
    rts
```

Nine bytes, no new state, no new subsystem. The observable effect on the
existing caller is that seeded placeholder initials differ; `test_lifecycle`
asserts the initials a player *enters*, not the seeded ones, and passes.

That the sequence really does vary is visible in the test output: successive
runs of the same suite picked `[4,5,6,8,13]`, then `[3,4,5,7,8,12,15]`, then
`[2,3,7]`.

---

## 6. Spawn behaviour

```asm
    lda waveDefTable + 7,y
    and #WAVEDEF_COL_RANDOM
    beq !fixed+
    jsr waveRandomColour                // X preserved; Y is not
    jmp !chosen+
!fixed:
    lda waveDefTable + 7,y
    and #WAVEDEF_COLOUR_MASK
!chosen:
    sta logCol,x
    sta wmBaseCol,x                     // what a hit flash returns to
    ldy wvDefBase                       // reloaded, exactly as after enemyAnimPtr
```

* **Per member, not per wave** — the roll is inside `waveSpawnMember`, so members
  of one wave differ from each other.
* **Once** — the result is stored and never recomputed. `enemyBaseColour`
  restores a hit flash *to* `wmBaseCol`, and `src/enemy.asm` already states that
  animation changes which frame is shown and never touches `logCol`.
* **Through the existing mechanism** — `logCol`/`wmBaseCol`, the same two bytes
  a fixed wave has always used. No new per-object field.
* **Nothing else moved** — movement, firing, health, animation, collision and
  wave timing are untouched. The only added work on the spawn path is one masked
  load and, for a random wave, about thirty cycles.

`waveRandomColour` clobbers Y, so the definition offset is reloaded — the same
thing `enemyAnimPtr` already required two instructions earlier, for the same
reason.

---

## 7. Editor

**UI** (`encounters_ui.py`) — a readonly combobox, **Fixed colour / Random per
enemy**, placed in the colour row itself rather than in a panel of its own:
"fixed or random?" is a question about that entry, and separating them would
leave an author reading a number the runtime is ignoring. Choosing Random
**disables the colour entry** immediately, and the value stays visible rather
than being blanked — it is still in the file, and it comes back.

One trap worth naming, because it is a real bug the test now guards: **a disabled
`ttk.Entry` ignores `insert`/`delete` from code as well as from the keyboard.**
Selecting another wave after a Random one would have shown the previous wave's
colour. The entry is re-enabled before the detail pane fills it.

**Model** (`project_v6.py`) — `colour_mode: str = "FIXED"`, serialised as
`colourMode`, following `fire_mode`/`fireMode` exactly.

**Validation** (`validation_v6.py`) — membership in `COLOUR_MODES`, and the
colour range is still checked **in both modes**, because a RANDOM definition
keeps its low nibble and an out-of-range value would corrupt the byte the mode
bit shares.

**Controller** (`controller_v6.py`) — `colour_mode` added to the string fields
that must not be coerced with `int()`.

### Compatibility

* **A missing `colourMode` key means FIXED.** Opening a file is not an opt-in.
* **No manual migration.** The committed library was brought forward by loading
  and re-saving it through the model — the same normalisation `save()` performs
  in the editor.
* **Round-trip is preserved.** Proved rather than asserted: the full
  save → reload → export → switch back → export cycle returns **every generated
  file byte-identical**, and the whole wave-definition model identical.
* A FIXED, DOWN definition still exports as exactly its colour, so a level that
  uses neither feature re-exports byte-for-byte.

---

## 8. Demonstration content

Two of the seven library definitions, **and no others**:

| definition | was | now | where it is seen |
|---|---|---|---|
| **`sweep`** | `26` = colour 10 + AIMED | **`90` = `$5a`** | level 1's **first** wave, worldProgress 20 — four Rings entering through the left border on different rasters |
| **`loop_5`** | `13` = colour 13 | **`77` = `$4d`** | worldProgress 160 — five Rings, the most members on screen at once |

Both carry RING triggers. The Dropper waves were left alone: a Dropper's death
is special presentation (it drops the P token) and is not the place to be
changing how it reads.

`sweep` was chosen deliberately as one of the two because it is **AIMED**, so the
demonstration and the collision case are the same wave.

The generated diff is **two data bytes**, plus the header comment that documents
the byte:

```diff
-    26,                       // colour (low nibble) + firing mode AIMED
+    90,                       // RANDOM colour per enemy (low nibble unused) + firing mode AIMED
-    13,                       // colour
+    77,                       // RANDOM colour per enemy; the low nibble is unused
```

---

## 9. Validation

### Build and smoke

```
make build   OK    wave state $77c0-$77ed (46 of 64 bytes)   waves $7c00-$7f4c
make smoke   PASS
  BOOT PASS   CAMPAIGN LOOP PASS   ENGINE HEALTH PASS   ROUTINE REGRESSION PASS
  4008 frames: gameOverrun 0  scrollLate 0  edgeLate 0  statOverflow 0
                publishSkip 0  schedBuildDefer 0  statLate 0  clipPoolFull 0
                objDoubleFree 0  objAllocFail 0
```

### `tests/test_wave_colour_mode.py` — new, **all pass**, three VICE launches

Nothing is poked in the first two launches: the authored level already contains
both a fixed and a random wave, so the comparison is between two *real* authored
waves. Enemies are attributed to their definition by breaking on
`objectActivate` and reading `wvDefBase`, which is still live — production state
only.

```
  ok  the engine latched the four exclusions it was asked to -- [0,11,1,1]
  ok  the pool is every colour that is not excluded -- 13 colours
  ok  BLACK is not in the pool
  ok  shared multicolour 1 ($d025) is not in the pool
  ok  shared multicolour 2 ($d026) is not in the pool
  ok  the terrain's charset colour is not in the pool -- charset colour 1
  ok  THE PLAYER'S COLOUR IS STILL ELIGIBLE, as required -- colour 14
  ok  exactly the two demonstration waves ask for random colour
  ok  no authored colour byte sets bit 7
  ok  'sweep' is random AND aimed -- the collision case -- $5a
  ok  a fixed wave gives EVERY member its one authored colour
         -- s, linger, loop, dive_4 -- all members exact
  ok  'sweep' spawned members with more than one colour  -- colours [4, 6, 8, 13]
  ok  'loop_5' spawned members with more than one colour -- colours [5, 6, 8, 13]
  ok  every random colour ever handed out was in the eligible pool
  ok  no random pick was ever one of the four forbidden colours
  ok  'sweep' members that may fire are armed AIMED -- modes [2]
  ok  NO enemy's stored colour ever changed while it was alive
  ok  a colour held for a long life -- longest lifetime 182 frames, one colour
  ok  the presented colour was the stored one except while flashing or dying
  ok  the pool was rebuilt from the NEW level's colours -- [0,11,1,1] -> [0,11,1,7]
  ok  ...and the pool length moved with it -- level 1 13 colours, level 2 12
  ok  the player's colour is still eligible in the new level
```

The authored table as the engine holds it:

```
  sweep      $5a  RANDOM colour 10 AIMED
  s          $03  fixed  colour 3
  linger     $07  fixed  colour 7
  loop       $0d  fixed  colour 13
  loop_5     $4d  RANDOM colour 13
  dive_4     $01  fixed  colour 1
  up_n_over  $01  fixed  colour 1
```

**One check was written and then removed as unsound**, which is worth recording:
"no stored colour is ever the hit-flash colour". `HIT_COL_FLASH` is 4 and 4 is an
*eligible* random colour, so a purple enemy is correct and the check was
measuring a coincidence. What actually rules out a flash leaking into the stored
colour is the check above it — the stored colour does not move for the whole
lifetime, flashes included. Replaced rather than weakened.

### `tools/level_editor/test_wave_colour_mode.py` — new, **49 passed, 0 failed**

Everything writes to a temporary directory; the committed level and library are
compared byte-for-byte at the end and are untouched.

The brief's eight editor steps, and where each is covered:

| | check |
|---|---|
| 1. a pre-feature project loads as Fixed | `a definition with no colourMode key loads as FIXED`; the whole committed library resolves FIXED |
| 2. change one wave to Random in the editor | real Tk: `choosing Random sets the model's colour mode` |
| 3. save | `the saved library records the colour mode` |
| 4. reload, Random persists | `reloading brings RANDOM back` |
| 5. export | via `controller.export`, the editor's own path |
| 6. the data carries Random without damage | `bit 6 set` + `low nibble still the authored colour` + `firing mode undamaged` |
| 7. back to Fixed, original semantics | `the generated byte is the original one again -- $1a vs $1a` |
| 8. no unrelated drift | `EVERY generated file is byte-identical after the round trip -- 6 files` |

Plus: all 16 colours × both firing modes × both colour modes are round-tripped
through the byte and recovered; the editor's `WAVEDEF_COL_RANDOM` is checked
against the literal in `src/waves.asm` so the two halves cannot drift; exporting
and saving twice are byte-identical.

The widget section needs a working Tk. `/usr/local/bin/python3` has one (as
`test_encounters_gui.py` already documents); `/opt/homebrew/bin/python3`
**segfaults at baseline**, unchanged by this work. The section skips with a
notice rather than failing.

### Visible output — headless framebuffer captures

No window and no focus theft: `x64sc -console`, launched through the harness,
frames taken with the monitor's own `screenshot`. (PNG is not compiled into this
VICE build; BMP, converted afterwards.)

* **Random wave, frame 5357** — four enemies on screen, engine-recorded colours
  `[2, 3, 7]`: the formation is visibly mixed, a **red** Ring flying alongside
  **cyan** ones.
* **Fixed wave, frame 5624** — three enemies on screen, colour `[3]`: all the
  same cyan, exactly as authored.

That is the behaviour the feature is for, seen rather than counted. **Final
visual acceptance is still yours** — a long, normal-speed, non-warp session on
real output is the thing I cannot do, and per `AGENTS.md` it outranks everything
above. What to watch for: that no random colour ever reads as invisible against
the terrain, and that the mixed formation still reads as one formation.

### Regressions — separated from baseline

Every failure below was reproduced **at HEAD with the change stashed**, and the
build was redone each way.

| suite | baseline | with the change | verdict |
|---|---|---|---|
| `test_boot`, `test_aimed_fire`, `test_aimed_velocity`, `test_p_economy_colours` | — | **0 FAIL** | pass |
| `test_lifecycle` | 0 FAIL | **0 FAIL** in isolation | pass (10 FAIL only under host load, a known flake) |
| `test_encounter_director` | 2 FAIL | 2 FAIL, **the same two** | pre-existing (wave concurrency) |
| `test_wave_triggers` | 3 FAIL | 3 FAIL + `gameOverrun is zero` in **2 of 3** runs | pre-existing; the extra one is load-flaky, not deterministic |
| `test_enemy_fire` | **0/1/1** over three runs | 1/1/1, a **different check each time** | pre-existing flake, same failing check as baseline |
| editor: `test_wave_schema`, `test_v6_roundtrip`, `test_v6_validation`, `test_v6_migration`, `test_level_packages`, `test_v6_phase5b_encounters`, `test_v6_phase5a_gui`, `test_semantic_gui`, `test_encounters_gui` | — | **all pass** | pass |
| `test_encounter_library` | 1 FAIL | 1 FAIL, the same one | pre-existing (`Level 1 still has all nine triggers`; it has 12) |
| `test_multi_level_layout` | 1 FAIL | 1 FAIL, the same one | pre-existing (`exactly two levels`; there are 3) |
| `test_v6_export`, `test_v6_import`, `test_v6_phase4_roundtrip` | FAIL | FAIL, **identical signature** | pre-existing (see §10) |

`test_encounter_library` briefly gained a second failure — "what is on disk is
exactly what the model round-trips" — because the committed library predated the
new field. Re-saving it through the model, which is the migration, resolved it.
Nothing was weakened to get there.

`make test` is not reported as a single verdict because it aborts at the first
failing suite and therefore stopped in different places on the two runs; the
suites are listed individually above instead.

---

## 10. Unrelated problems found, and deliberately left

1. **`src/level2/wave_encounters.asm` is stale.** Its `sweep` exports as `10`
   where the shared library says `sweep` is AIMED (`26`), so level 2's committed
   encounter data predates the aimed-fire change. **This is why I re-exported
   level 1 only** — re-exporting level 2 would have silently given its sweep
   aimed fire, which is a behaviour change nobody asked for. Consequence worth
   knowing: **the demonstration appears in level 1 and not in level 2**, until
   somebody deliberately re-exports it.
2. **`src/level3/wave_encounters.asm`** differs from a fresh export only by the
   byte-7 header comment. Left alone for the same reason.
3. **`import_engine_v6.py` does not separate the packed fields.** Line 244 reads
   `colour=_u8(d[7])` with no mask, so a re-imported AIMED definition comes back
   as colour 26 with mode DOWN, and `reference_encode_wave_definitions` re-emits
   the bare colour. This is why `test_v6_import` and `test_v6_phase4_roundtrip`
   fail at baseline. It is pre-existing and predates this task; the module is
   used only by those two test files, not by the live export path. **Adding bit 6
   makes nothing newly wrong there** — the tests fail on the `colour` field
   before the mode is reached, with identical signatures either way.
4. **`test_encounter_library`** expects nine level-1 triggers (there are 12) and
   **`test_multi_level_layout`** expects two levels (there are three) — both
   stale against the current content.
5. **`/opt/homebrew/bin/python3` segfaults** on any real-Tk editor test.
   `/usr/local/bin/python3` works, as `test_encounters_gui.py`'s docstring says.

None of these was touched.

---

## 11. Files changed

| file | change |
|---|---|
| `src/waves.asm` | `WAVEDEF_COL_RANDOM`; two assembly-time guards; `wvColPool`/`wvColCount`/`wvColBan`; `waveColourPool`; `waveRandomColour`; the spawn branch |
| `src/gamestate.asm` | `gsRandom8` extracted and given sound feedback; `gsRandomLetter` calls it |
| `src/level1/wave_encounters.asm` | **generated** — two colour bytes and the byte-7 header comment |
| `tools/level_editor/contract_v2.py` | `COLOUR_MODES`, `COLOUR_MODE_LABELS`, `WAVEDEF_COL_RANDOM` |
| `tools/level_editor/project_v6.py` | `colour_mode` field, `colourMode` key, FIXED default |
| `tools/level_editor/validation_v6.py` | colour-mode membership; colour range now explicitly checked in both modes |
| `tools/level_editor/export_v6.py` | `wavedef_colour_byte`, `wavedef_colour_comment`, header comment |
| `tools/level_editor/controller_v6.py` | `colour_mode` treated as a string field |
| `tools/level_editor/encounters_ui.py` | the mode combobox, `_sync_colour_enabled`, the disabled-entry fix |
| `tools/level_editor/encounter_library.v6.json` | **content** — `colourMode` on all seven; `sweep` and `loop_5` RANDOM |
| `tests/test_wave_colour_mode.py` | new |
| `tools/level_editor/test_wave_colour_mode.py` | new |

Scope held: no renderer, multiplexer, scroller or raster change; scroll speed
still 1 px/frame; no player-colour change; no shared-multicolour change; no
wave/movement redesign; `publishSkip` untouched; no AngryLoad, no Level 3 turret
work, no runtime-variable stage length.

---

## 12. Final state

```
 M src/gamestate.asm
 M src/level1/wave_encounters.asm
 M src/waves.asm
 M tools/level_editor/contract_v2.py
 M tools/level_editor/controller_v6.py
 M tools/level_editor/encounter_library.v6.json
 M tools/level_editor/encounters_ui.py
 M tools/level_editor/export_v6.py
 M tools/level_editor/project_v6.py
 M tools/level_editor/validation_v6.py
?? tests/test_wave_colour_mode.py
?? tools/level_editor/test_wave_colour_mode.py

10 files changed, 377 insertions(+), 24 deletions(-)
```

* **Nothing committed. Nothing pushed.** HEAD is still `d5fc70d`.
* VICE: every instance launched through the harness with `-console`, owned by
  exact PID and reaped in a `finally`. No broad `pkill`/`killall`, no
  user-launched instance touched, no focus stolen. `pgrep -fl x64sc` confirms
  **none running**.
* `build/` is **340 K**, current artefacts only — no per-run directories. Scratch
  captures and logs live in the session scratchpad (2.5 M) and the `/tmp` logs
  from this task were deleted. **92 GiB free of 228 GiB.**
