# Restoring the old outer loop around the current engine

**Date:** 2026-09-16
**Starting HEAD:** `d5566b08ab5cdfeadf8c03e885cf7fdd299e500e` — *Powerup Token mechanic added*
**Starting working tree:** **clean.** Nothing was uncommitted, so nothing needed preserving; nothing was reset, stashed, cleaned, committed or pushed.
**Behavioural reference:** `~/Desktop/c64Shooter-main.zip`, extracted read-only to `/tmp/oldshooter`.

**Final working tree** — two new files, six modified:

```
 M Makefile           M src/hud.asm    M src/main.asm
 M src/player.asm     M src/renderer.asm
 M tests/harness.py
?? src/gamestate.asm  ?? tests/test_lifecycle.py
```

(`.claude/` is also untracked. It is Claude Code's own settings directory, not
part of this task, and was left alone.)

---

## 1. The old outer loop, as actually implemented

Read out of the old `src/main.asm` rather than assumed. Four states, dispatched
by a cmp/beq router in which **each handler owns its own per-frame loop and
returns when the state changes**:

```
GAME_STATE_MENU (0)  attract: starfield + alternating title / high-score pages
GAME_STATE_PLAYING (1)
GAME_STATE_GAME_OVER (2)
GAME_STATE_ENTER_INITIALS (3)
```

| thing | old value / behaviour |
|---|---|
| boot | black screen, seed the table, `GAME_STATE_MENU`, `enterMenu`, `mainLoop` |
| attract cycle | `ATTRACT_CYCLE_FRAMES = 250` (~5 s), toggles title ↔ scores, clears and repaints on each flip, **re-stamps the page's text every frame** |
| title page | "MY FIRST C64 SHOOTER" row 6 col 10; "FIRE TO START" row 20 col 13 |
| score page | "HIGH SCORES" row 4 col 14; eight rows `"III  DDDDDD"` on rows 7, 9, 11 … 21, column 15 |
| start | fire (port 2, active-low bit 4) → `waitFireRelease` → `startGame` |
| game over | `GAME_OVER_HOLD_FRAMES = 180` (~3.6 s), text re-stamped every frame, **no fire test at all** |
| qualification | 8 entries, descending, 24-bit compare MSB-first, **an equal score does not displace** |
| initials | three slots, all start on "A", slot 0 selected, **edge-triggered** stick (`edge = ~current AND previous`), up/down wrap Z↔A, left/right clamp 0..2, fire commits |
| after commit | insert, then show the table **immediately** and return to attract **already on the scores page**, then `waitFireRelease` |
| fire gating | `waitFireRelease` at exactly three points: after the attract start, on entering initials, after the commit |

## 2. Migration map

| old component | class | note |
|---|---|---|
| state constants, values and order | **LIFT** | identical values, identical meaning |
| cmp/beq router, handler-owns-its-loop shape | **LIFT** | `gsRouter` is the old `mainLoop` |
| `ATTRACT_CYCLE_FRAMES` 250, `GAME_OVER_HOLD_FRAMES` 180 | **LIFT** | unchanged |
| attract page toggle + per-frame re-stamp | **LIFT** | same structure, same order |
| `waitFireRelease` and its three call sites | **LIFT** | same mechanism, same reasons |
| initials edge detection, wrap and clamp rules | **LIFT** | the old two-line `eor #$ff / and prev` |
| commit → scores page → attract | **LIFT** | including showing the table at once |
| qualification rule incl. equal-does-not-displace | **LIFT** | rule unchanged |
| table shape: 8 entries, 3 initials, 6 digits | **LIFT** | unchanged |
| seeding: random initials, all equal, so already descending | **LIFT** | same LCG-ish CIA-timer mix |
| insertion: shift the tail down, drop the last | **ADAPT** | two flat arrays, so it is a backwards byte copy per array rather than the old per-field shuffle |
| score storage | **ADAPT** | old: 24-bit binary + a decimal renderer. New: **the six HUD digits are the storage**, so qualification is a digit compare and the renderer disappears |
| text drawing | **ADAPT** | same strings, same screen positions; `(ptr),y` blits from new zero-page pairs |
| `startGame`'s reset work | **REIMPLEMENT** | the old one cleared object slots and player fields by hand; this engine has `gameInit` for exactly that, and doing it any other way would be two writers of one truth |
| non-game VIC setup | **REIMPLEMENT** | the old menus assumed a simple display; here it is an IRQ stub (§6) |
| starfield behind the menus | **RETIRE** | the only retirement. See §4 |
| per-line/per-slot text colour | **RETIRE** (partly) | colour RAM belongs to the terrain; the initials highlight became reverse video. See §4 |
| `$ffd2` screen clear, KERNAL font copy to `$3800` | **RETIRE** | KERNAL is banked out and `$3800` is the aperture mask; the VIC sees the character ROM at `$1000` instead, so the stock font costs nothing |

## 3. What is substantially the old code

`gsRouter`, `gsAttractLoop`, `gsGameOverLoop`, `gsInitialsLoop`,
`gsWaitFireRelease`, `gsScoreQualifies`, `gsSeedTable`/`gsRandomLetter` and the
whole initials input block are the old routines with the old control flow,
renamed and re-pointed at current engine symbols. The screen constants are the
old arithmetic. The two timers are the old numbers.

## 4. Old behaviour that could not be kept, and why

1. **The starfield.** The old menus drew and animated stars into screen RAM
   under the text. This engine's non-game display is a plain text screen, and
   an animated starfield is presentation work that belongs with the
   Parallax-grade title rather than being rebuilt now against a display that is
   about to be replaced. The state/timing hooks are all present: a starfield is
   a call in each loop beside the re-stamp.
2. **Per-line and per-slot text colour.** Colour RAM is uniformly
   `TERRAIN_COLOUR_RAM` and belongs to the terrain; writing it for text would
   mean restoring the whole 1000 bytes on every entry to GAME. The text is
   therefore hires white on black, and the **selected initials slot is reverse
   video instead of yellow** — a screen-RAM-only highlight that says the same
   thing at a glance.
3. **Menu music.** The old loop had none, so nothing was deferred.

## 5. State constants and dispatcher

`GS_ATTRACT/PLAYING/GAMEOVER/INITIALS` = 0/1/2/3, the old values. `gsRouter`
is the old cmp/beq chain; `gamePlayLoop` in `src/main.asm` is the **old
`mainLoop` unchanged** apart from its name and three instructions at the bottom
that let it return when `gsState` leaves `GS_PLAYING`. No scene framework, no
callback table, no event bus.

`mainLoop` survives as a label that jumps to the router, because
`tests/harness.py`'s `call()` returns the program counter there and every
existing test depends on it. It now means "the top of the program", which is
more correct than it was: a test that hijacks the CPU during GAME OVER resumes
into GAME OVER rather than into gameplay that is not running.

## 6. VIC / raster / sprite ownership, and the IRQ seam

The seam is **one byte and five instructions**. `irqHandler` tests `gsNonGame`
immediately after acknowledging the raster IRQ; non-zero jumps to
`gsAttractIrq`, a stub that touches no schedule, no batch, no phase chain and no
page. The raster executor was not redesigned.

| register | while a non-game state is up | how gameplay takes it back |
|---|---|---|
| `$d011` | plain 25-row text (`$1b`) | `exFrame` rewrites it from `frameD011` every frame |
| `$d018` | `$14` — screen `$0400` + **the character ROM at `$1000`**, which is where the VIC sees it in this bank, so the attract text needs no font of its own | the aperture splits rewrite it twice a frame |
| `$d015` | held at 0 — no gameplay or HUD sprite can leak in | the batch executor rewrites it from the schedule |
| `$d020`/`$d021` | black, as the old menu | the aperture splits own `$d021` |
| `$d016` | **multicolour off** | does **not** restore itself — `terrain.asm` sets MCM once at boot, so `gsEnterGame` puts it back explicitly |
| colour RAM | **never touched** | nothing to restore; this is what makes re-entry free |

The stub also advances `frameCounter`, so the non-game states pace on the same
byte the gameplay loop does and the program has one notion of "a frame".

**For the later extravagant title:** replace `gsAttractIrq` and the draw
routines. The router, the states, the timers, the input rules and the
high-score system do not move. The segment's guard was widened to `$c000` (the
next occupied address) so a much larger title presentation has somewhere to go.

## 7. New-game reset audit

`gsStartGame` runs `gsResetRun`, then `gameInit`, `hudInit`, `scrollInit`, then
hands the display back **last**, so the first gameplay IRQ finds a schedule
`gameInit` has already published.

| reset by | what |
|---|---|
| `gameInit` (already existed) | object pool, sorter, player, weapon, collision, SFX silence, level assets, enemy, clip, waves/director, Dropper, token encounter |
| `scrollInit` | both terrain pages, world progress, frame 0 |
| `hudInit` | every HUD bitmap and its dirty flags |
| **`gsResetRun` (new)** | **score, lives, P/token currency** — the three nothing else owned |

`gsResetRun` also answers a question `src/pickup.asm` deliberately left open:
**P currency is run-scoped** and a new game starts at zero.

`gsStartGame` finally zeroes `gameOverrun`/`gameSpanMax`/`gameSpanOver` and
seeds `lastFrameSeen` from the live `frameCounter`. The transition legitimately
costs one missed frame — it rebuilds both terrain pages in one main-thread pass
— and that frame is not a frame the game was running. Seeding `lastFrameSeen`
matters: zeroing it made the first comparison a hundred-frame delta and counted
the whole boot as an overrun (measured, then fixed).

## 8. Ordinary vs terminal death

**The current engine had no death at all.** `playerTakeHit` only granted
invulnerability and bumped a saturating counter; `hudDemoTick` cycled lives on a
128-frame timer with no connection to gameplay. There was therefore no terminal
death for the outer loop to hang off, and the brief's assumption that one
existed does not hold.

Following the old game (which had lives and `PLAYER_STATE_GAME_OVER`) and the
HUD's own written instruction — *"whatever comes to own score, lives or upgrade
must REPLACE the block below rather than run alongside it"* — lives were given a
real owner:

- **ordinary death**: `playerTakeHit` decrements `hudLives`, marks the HUD
  dirty, and the engine's existing 100-frame invulnerable blink runs. The state
  stays `GS_PLAYING`. **No damage or death balance changed.**
- **terminal death**: the hit that empties the stock sets `plyFatal`. The state
  does **not** change on the collision frame. The ordinary blink plays out as
  the fatal presentation, and `playerFatalTick` hands over to `gsEnterGameOver`
  only when `plyInvuln` reaches zero.

`playerFatalTick` is called **last in `gameFrame`**, after `regenTick` and
`scrollTick`. Calling it earlier meant the rest of that same frame repainted
terrain straight over the GAME OVER text — measured, the row came back full of
terrain glyphs. The state loops also re-stamp their text every frame, which is
what the old game did and what makes a text page immune to whatever drew last.

The HUD's demo score and upgrade cadences are untouched.

## 9. High scores

Eight entries, three initials, six digits, seeded with random initials at
`000100` so the table starts descending. Qualification walks the table MSD-first
and an equal score does not displace. Insertion shifts the tail down and drops
the last. Initials entry is edge triggered with the old wrap and clamp rules,
and the commit shows the updated table at once and returns to attract on the
scores page.

The table lives in `$c700` module state and is seeded **once, at boot** — it is
the only session-persistent thing here, and it survives games by not being in
any reset path.

## 10. FIRE / input gating

`gsWaitFireRelease` at the old three points. Proven: held fire on the attract
screen does **not** start a game, and only the release does; initials entry
cannot be committed by fire held over from GAME OVER; the commit press cannot
start the next game. GAME OVER has no fire test at all, as before, so the press
that killed you cannot skip it.

## 11. SID / SFX across transitions

`gsBeginNonGame` calls `sfxSilence` first — every voice gated off and channel
state reset, so no effect can resume. Proven: all three channels read idle in
attract and immediately after GAME OVER. Entering GAME goes through `gameInit`,
which calls `sfxSilence` again, so gameplay starts deterministic. No audio
architecture was added or changed.

## 12. Persistence classification

| class | state |
|---|---|
| **boot / session** | the high-score table (`hsDigits`, `hsName`), `gsSeed`, the `gsGames`/`gsQualified` diagnostics |
| **game / run** | score (`hudScore`), lives (`hudLives`), **P currency (`pkTokensP`)**, and everything `gameInit` resets |
| **level / reset-on-level** | world progress and both terrain pages (`scrollInit`), the wave/director cursor, the token encounter and Dropper liveness — **these are what the next LEVEL COMPLETE task must decide about**: today they are reset per *game* only |
| **life / transient** | `plyInvuln`, `plyFatal`, live objects and projectiles, SFX channel state |

## 13. Memory

| segment | before | after | delta |
|---|---|---|---|
| **game state code** (new) | — | `$8b00-$8fa3` **1,188 B** | **+1,188** |
| **game state** (new) | — | `$c700-$c759` **90 B** | **+90** |
| player code | `$4000-$4232` 563 B | `$4000-$4265` **614 B** | +51 |
| main | `$5000-$52a2` 675 B | `$5000-$52b0` **689 B** | +14 |
| raster executor | `$8600-$8a97` 1,176 B | `$8600-$8a9f` **1,184 B** | +8 (the seam) |
| hud code | `$1400-$1768` 873 B | `$1400-$174a` **843 B** | **−30** (demo lives removed) |
| **total** | | | **+1,321 B** |

**PRG unchanged at 51,164 bytes.** Zero page: `gsSrc = $fb/$fc`, `gsDst =
$f9/$fa`, asserted distinct from `scrPtr` and terrain's `trSrc`. Game state has
**518 bytes** of headroom to the HUD state at `$c960`; the code segment now runs
to `$c000`, leaving ~12 KB for the future title.

**No VIC bank 0 capacity was consumed at all** — the attract display reuses the
character ROM and screen page A.

## 14. Build and tests

Build clean. `tests/test_lifecycle.py`: **ALL PASS** — cold boot into attract
with the stub owning the display and no sprites; both attract pages drawing the
old text at the old positions on the old timer; held fire refused and the
release accepted; a fresh game; ordinary death costing one life and staying in
GAME; terminal death waiting for the presentation; the old GAME OVER text and
hold; qualification routing into initials; edge-triggered initials with the
reverse-video highlight; commit inserting and returning to attract on the scores
page; equal-does-not-displace; a second game that is fresh while the table
persists; and catastrophic diagnostics at zero over a smoke run.

**Clean boot-to-game smoke, no breakpoints at all** (the honest steady-state
measurement): `gameOverrun 0, scrollLate 0, statPageMismatch 0,
statPtrMismatch 0, publishSkip 3` over six warp-seconds of real gameplay.

### Full suite, once each

| suite | result |
|---|---|
| `test_boot` | **ALL PASS** |
| `test_turret_regression` | **ALL PASS** |
| `test_player_ship` | `publishSkip` only |
| `test_production` | `publishSkip` only |
| `test_encounter_director` | `publishSkip`, `schedBuildDefer 1` |
| `test_level_assets` | `publishSkip`, `schedBuildDefer 1` |
| `test_enemy_fire` | **ALL PASS** |
| `test_lifecycle` | **ALL PASS** |
| `test_sfx` | 4 failures — see below |
| `test_pickup` | errors — see below |

**`publishSkip` and `schedBuildDefer` are the known limitation this brief said
not to investigate.** Not investigated, not asserted anywhere new, and no
existing assertion about them was edited.

### Unrelated failures, from commits that predate this task

I modified none of `sfx.asm`, `waves.asm`, `pickup.asm`, `token.asm` or
`dropper.asm` (`git diff` on all five is empty), so these come from the user's
own `Powerup tokens` / `Powerup Token mechanic` commits:

- **`test_sfx`**: "sfx state is nine bytes — 10"; an SFX request with **effect
  id 6 from `$7aee`**, which is inside the `dropper flight` segment — the
  Dropper's sonar ping, which the test's legal-hook table does not know about;
  and the request-accounting check, which is off by exactly that one ping.
- **`test_pickup`**: `KeyError: 'waveTrigTokenLo'` — the authored token column
  it tests no longer exists, having been replaced by `src/token.asm`.

Both are stale tests describing superseded designs. **Recorded, not fixed.**

### One deliberate change to shared test infrastructure

`tests/harness.py` gained `start_game=True`: the machine no longer boots into
gameplay, and every pre-existing test assumes it does. The harness now presses
and releases fire once, in the single place that owns bringing a machine up, and
then sets a life stock the probe cannot exhaust — **restoring** the assumption
those tests were written against (before this task the ship literally could not
die). Without it, a parked ship in warp loses five lives in a fraction of a
probe and the suite measures the attract screen. `test_lifecycle` passes
`start_game=False` and drives the lifecycle itself.

## 15. VICE and build hygiene

`pgrep -fl x64sc` **before: nothing. After: nothing.** Every launch used
`-console` and `+saveres`, never `-default`, no joystick-disable or
global-detach override, no focus theft; each run owned and reaped its exact PID
(the harness prints `launched and reaped`), and no broad `pkill` was used. The
four probe scripts live in the session scratchpad, not the repository; the old
shooter was extracted read-only to `/tmp/oldshooter`. No temporary logs or
captures were left in `/tmp`, and `build/` holds only its three fixed artifacts.

```
du -sh build/     92K        (shmup.prg, main.sym, main.vs)
du -sh .          6.3M
```

## 16. Manual judgement — what only you can settle

1. **Does the attract loop feel like the old one?** Five seconds a page, title
   then scores, fire to start. It is the old timing and the old layout, but
   without the starfield — say whether that absence matters before the big title
   task, since that is where it would come back.
2. **Is the text legible?** White hires on black, stock font, 25-row screen.
3. **Initials usability.** Up/down to change a letter, left/right to choose one,
   fire to commit, one action per push. **The selected slot is reverse video
   rather than yellow** — check that reads clearly.
4. **Game-over sequencing.** ~3.6 seconds of GAME OVER, then either initials or
   straight back to attract. Does the hold feel right?
5. **Transition cleanliness.** Watch for stale gameplay sprites or a torn frame
   at each boundary — game→over, over→initials, initials→attract,
   attract→game. Automated checks say `$d015` is zero one frame after the
   handover; your eyes are the authority on the frame itself.
6. **Gameplay unchanged.** The engine should look and play exactly as it did.
7. **Lives are real now.** Five of them, and the ship genuinely dies. Confirm
   the pace feels right — it is the first time this game could end.
8. **The full loop, twice.** Attract → game → die out → high scores → attract →
   second game. The second must be genuinely fresh and the table must persist.

## 17. Constraints for the next LEVEL COMPLETE / UPGRADE task

- Add states **between** `GS_PLAYING` and the rest; the router is a cmp/beq
  chain and a new arm is three instructions.
- `gsResetRun` is the run-scoped reset; a level transition needs a **narrower**
  one. §12's "level / reset-on-level" row lists what currently resets per game
  and will need to be split: world progress and both pages (`scrollInit`), the
  director cursor, the token encounter, Dropper liveness.
- `pkTokensP` is run-scoped and reset by `gsResetRun`. P spending must decide
  whether it survives a level, and that decision belongs in the same place.
- An upgrade screen is a non-game state: set `gsNonGame`, draw, and it gets the
  text display and silence for free. It must not assume colour RAM.
- Do not put level-completion logic in `playerFatalTick`; that path is terminal
  death only.
