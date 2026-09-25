// ===========================================================================
// levelload.asm — pull the level package in from disk, once, at boot
// ===========================================================================
// THE ONLY LOADER IN THE PROJECT, and deliberately not a framework: no asset
// manager, no table of resources, no indirection. One routine loads one file
// to one address, and a second level will be the same call with a different
// name rather than a system to configure.
//
// ---------------------------------------------------------------------------
// WHEN IT RUNS, AND WHY THAT IS THE WHOLE DESIGN
// ---------------------------------------------------------------------------
// FIRST. Before the `sei` at the top of entry, before $d011 is touched, before
// any subsystem initialises. That ordering is not tidiness -- it is the only
// window in which this can work at all:
//
//   * $01 is still $37, the state BASIC left. The KERNAL ROM is MAPPED, so
//     $ffd5 is a routine rather than level data. The engine does not switch to
//     $35 until installRenderer, hundreds of instructions later.
//   * Interrupts are still enabled and still the KERNAL's. The serial routines
//     want their own timing and their own IRQ; taking the machine over first
//     and then asking the KERNAL to load would be asking it to run without the
//     environment it was written for.
//   * Nothing has been initialised yet, so a load that scribbles zero page or
//     takes a hundred milliseconds disturbs nothing -- terrainInit and
//     scrollInit, the two routines that READ the package, both run later.
//
// WRITES REACH RAM EVEN THOUGH ROM IS MAPPED. On a 6510 the ROM at $a000-$ffff
// is read-only: a store always lands in the RAM underneath it. That is what
// lets the KERNAL, executing from $e000, load a file INTO $e000 without
// destroying itself, and it is why this address needs no banking dance here.
//
// ---------------------------------------------------------------------------
// FAILURE
// ---------------------------------------------------------------------------
// A failed load is FATAL AND VISIBLE, not silent. There is no fallback copy of
// the terrain to fall back to -- the package IS the level -- so continuing
// would draw a screenful of whatever happened to be in RAM and look like a
// renderer fault. Instead the border goes red and the machine stops, which is
// unambiguous on real hardware and in an emulator alike.
//
// The signature check is part of that: the KERNAL reporting success is not
// proof that the bytes arrived, only that it thought it sent them.
// ===========================================================================

.const SETLFS = $ffba                   // A = logical file, X = device, Y = SA
.const SETNAM = $ffbd                   // A = length, X/Y = name pointer
.const KLOAD  = $ffd5                   // A = 0 (load, not verify)

// SECONDARY ADDRESS 1, NOT 0. With SA = 0 the KERNAL discards the file's own
// first two bytes and loads to the address in X/Y; with SA = 1 it honours the
// load address stored in the file. The package is assembled `* = LEVELPKG_BASE`
// and carries that address in its first two bytes, so SA = 1 means the one
// place $e000 is written down is src/levelpkg.asm.
.const LEVEL_SA     = 1
.const LEVEL_DEVICE = 8                 // the disk the engine itself came from

// The value levelLoadError takes when the KERNAL reported success but the
// signature was not there. Distinct from every KERNAL status code, which are
// small bit flags, so the two causes can never be confused.
.const LL_ERR_SIGNATURE = $ff

* = $5300 "level loader"

// ---------------------------------------------------------------------------
// levelLoad — the BOOT load. Fatal on failure, as it has always been.
//
// It now names the level through the campaign rather than through a literal, so
// that boot and a mid-run level change read the sequence from the same place.
// At boot cmpLevel is 0, which is LEVEL1.
// ---------------------------------------------------------------------------
levelLoad:
    jsr levelLoadCore
    bcc !ok+                            // A holds why; the border goes red.
    jmp levelLoadFailed                 // a jmp because levelLoadRuntime now
!ok:                                    // sits between the two
    rts

// ---------------------------------------------------------------------------
// levelLoadCore — SETNAM, SETLFS, LOAD, then prove the bytes arrived.
//
// Exit: carry CLEAR on success; carry SET with A = the KERNAL's status byte or
//       LL_ERR_SIGNATURE. It NEVER halts -- the caller decides what a failure
//       means, because at boot it is fatal and mid-run it is not.
//
// IT REQUIRES THE KERNAL MAPPED AND INTERRUPTS ITS OWN AFFAIR. At boot both are
// already true. Mid-run levelLoadRuntime arranges them and puts them back; see
// the long note there for why that is the whole difficulty.
// ---------------------------------------------------------------------------
levelLoadCore:
    jsr cmpLevelName                    // -> A = length, X/Y = name pointer
    jsr SETNAM

    lda #LEVEL_SA                       // logical file number; any free one
    ldx #LEVEL_DEVICE
    ldy #LEVEL_SA
    jsr SETLFS

    lda #0                              // 0 = LOAD (1 would be VERIFY)
    ldx #<LEVELPKG_BASE                 // ignored with SA = 1, supplied anyway
    ldy #>LEVELPKG_BASE                 // so no register reaches the KERNAL
    jsr KLOAD                           // holding whatever BASIC left in it
    bcc !ok+                            // carry set: A holds the KERNAL error.
    jmp levelCoreFailed                 // BRANCHED AROUND A JMP because the
                                        // failure tail is now past a branch's
                                        // reach -- levelLoadRuntime grew
                                        // between the two
!ok:

    // ---- THE BYTES ACTUALLY ARRIVED ---------------------------------------
    // Checked rather than assumed. A short file, a wrong name matching some
    // other file, or a device that answered but sent nothing all return clean
    // from the KERNAL and would leave the terrain reading uninitialised RAM.
    //
    // AND IT CANNOT BE CHECKED WITH THE KERNAL MAPPED, which is the whole
    // subtlety of loading under ROM and cost this implementation its first
    // attempt. A 6510 store at $e000-$ffff always lands in RAM -- that is what
    // lets the KERNAL load a file into the memory it is itself executing from --
    // but a LOAD from those addresses reads the ROM. `lda LEVELPKG_SIG` with
    // $01 = $37 therefore returns a byte of KERNAL, never the byte that just
    // arrived, and the comparison can only ever fail.
    //
    // So the check banks the ROM out for the duration. Interrupts are held off
    // across it because the IRQ vector still points into the KERNAL at this
    // point in the boot: an interrupt taken while $01 = $35 would vector
    // through RAM that holds level data.
    sei
    lda #$35                            // KERNAL out: $e000-$ffff reads as RAM
    sta $01

    ldx #0                              // X = 0 means "matched"
    ldy #3
!check:
    lda LEVELPKG_SIG,y
    cmp levelSigWant,y
    beq !next+
    ldx #$ff
!next:
    dey
    bpl !check-

    lda #$37                            // KERNAL back in: the caller is still
    sta $01                             // mid-boot and has not taken the
    cli                                 // machine over yet

    cpx #0
    bne levelSigBad
    clc                                 // the bytes are there
    rts

levelSigBad:
    lda #LL_ERR_SIGNATURE
levelCoreFailed:
    sec
    rts

// ---------------------------------------------------------------------------
// levelLoadRuntime — the SAME load, from inside a running game.
//
// Exit: carry CLEAR on success, carry SET with A = why on failure. The caller
//       stays alive either way; see gsUpgradeContinue in src/gamestate.asm.
//
// ---------------------------------------------------------------------------
// WHAT HAS TO BE UNDONE AND PUT BACK, AND WHY EACH ONE MATTERS
// ---------------------------------------------------------------------------
// src/levelload.asm's original note explains that the boot load works because
// nothing has happened yet: the KERNAL is mapped, the interrupts are still
// BASIC's, and no subsystem has state to disturb. By the time a level changes,
// all three are false. This routine re-creates that environment and restores
// the engine's afterwards. It does NOT reimplement the load -- levelLoadCore is
// the same code the boot path runs, which is the whole point of the refactor.
//
//   INTERRUPTS OFF, FOR THE WHOLE LOAD. Not merely tidy: the KERNAL's serial
//   routines are timing-critical bit-banging, and a raster interrupt taken in
//   the middle of an IEC byte corrupts it. Masking is also what makes the
//   banking safe -- see below.
//
//   $01 BACK TO $37. The engine runs at $35 with the KERNAL banked out, so
//   $ffd5 is level data rather than a routine; calling it at $35 would execute
//   the previous level's map. The store must happen with interrupts already
//   masked, because the engine's IRQ vector lives at $fffe in the RAM the
//   KERNAL is about to cover: an interrupt taken at $37 vectors through the
//   KERNAL's $fffe, into the KERNAL's handler, which this engine has not
//   prepared for since boot.
//
//   THE RASTER LATCH CLEARED BEFORE THE MASK LIFTS. $d019 latches through the
//   load whether or not anyone is listening, so without the acknowledge below
//   the first instruction after `cli` would take a stale interrupt.
//
//   THE PACKAGE CANNOT REACH THE CODE THAT IS RUNNING. The file is bounded at
//   $fff9 and the hardware vectors at $fffa-$ffff are outside it -- so the
//   engine's own $fffe survives the load untouched -- while every byte of
//   engine CODE lives below $a000. There is no window in which the processor
//   could execute a byte the loader has overwritten, and it is the package's
//   own layout guard in src/levelpkg.asm that keeps that true.
//
//   THE DISPLAY IS LEFT ALONE. The caller is a non-game state, so the screen
//   already shows a static text page that the stub IRQ is merely re-asserting;
//   with interrupts masked the registers simply hold their last values for the
//   half-second the drive takes. Blanking would have been a visible flicker for
//   no gain.
// ---------------------------------------------------------------------------
// THE VERDICT TRAVELS IN MEMORY, NOT ON THE STACK. Three more things have to
// happen after levelLoadCore returns and every one of them disturbs A or the
// flags, so the result is parked in two bytes and rebuilt at the end. A first
// version tried to carry it in php/pha pairs through the restore and was both
// unreadable and wrong.
//
// $35 IS RESTORED UNCONDITIONALLY rather than saved and replaced, because there
// is exactly one state this can be called from: the engine's, which is $35. A
// save/restore would have implied a generality that does not exist and hidden
// the assumption instead of stating it.
// THE CIA HAS TO GO BACK TOO, AND THAT IS THE PART THAT COST THIS A DEBUGGING
// ROUND. installRenderer writes $7f to $dc0d, which disables every CIA
// interrupt, and the engine never wants one again. But the KERNAL's IEC
// routines are built on the CIA: they time the bus with timer A and they expect
// the jiffy interrupt to be running. Called with the CIA as the engine leaves
// it, the LOAD does not fail -- it HANGS, waiting for a timeout that can never
// arrive. The symptom is the machine sitting in the KERNAL's interrupt handler
// at $ea7b for ever with $01 still $37.
//
// The boot load never hit this because it runs BEFORE installRenderer, with the
// CIA exactly as BASIC left it. So this restores that: timer A latched to the
// PAL jiffy period and its interrupt enabled, the VIC's raster interrupt off,
// and then the reverse afterwards.
.const CIA_JIFFY_PAL = $4025            // what the KERNAL programs timer A to

levelLoadRuntime:
    sei
    lda #$37                            // KERNAL in: $ffd5 is a routine again
    sta $01

    // ---- hand the machine back to the KERNAL ------------------------------
    lda #0
    sta $d01a                           // no raster interrupt: the VIC must not
                                        // interrupt an IEC byte
    lda #$01
    sta $d019                           // ...and acknowledge any that latched
    lda #$7f
    sta $dc0d                           // clear every CIA mask bit, then read
    lda $dc0d                           // the register to clear what is pending
    lda #<CIA_JIFFY_PAL
    sta $dc04
    lda #>CIA_JIFFY_PAL
    sta $dc05
    lda #%00010001
    sta $dc0e                           // timer A: continuous, running, latched
    lda #%10000001
    sta $dc0d                           // enable the timer A interrupt

    cli                                 // THE KERNAL EXPECTS TO BE INTERRUPTED.
                                        // Its serial code masks its own critical
                                        // sections; what it cannot survive is
                                        // having no jiffy at all.
    jsr levelLoadCore                   // the boot path's own code, verbatim
    sei

    sta llRunCode                       // why, if it failed
    lda #0
    rol                                 // carry -> bit 0
    sta llRunFail

    // ---- and take it back --------------------------------------------------
    lda #$7f
    sta $dc0d                           // no CIA interrupts, as installRenderer
    lda $dc0d                           // left it; read to clear the pending
    lda #$35                            // KERNAL out: the package is readable
    sta $01                             // and $fffe is the engine's vector again
    lda #$01
    sta $d019                           // acknowledge whatever the VIC latched
    sta $d01a                           // raster interrupt on again ($01 = enable)
    cli

    lda llRunCode
    lsr llRunFail                       // bit 0 -> carry, for the caller
    rts

llRunCode: .byte 0
llRunFail: .byte 0

// ---------------------------------------------------------------------------
// levelLoadFailed — stop, visibly. Never returns.
//
// The border alone, because at this point in the boot there is no charset, no
// screen and no HUD to write a message with: clearCharset has not run and the
// display is still whatever the autostart left. A solid red border is the one
// signal available that cannot be mistaken for content.
// ---------------------------------------------------------------------------
levelLoadFailed:
    sta levelLoadError                  // WHY, not just THAT. A KERNAL status
                                        // byte and a signature mismatch look
                                        // identical on a red border, and this
                                        // is the one byte that tells them apart
                                        // to a monitor or a probe.
    sei
    lda #2
    sta $d020
    sta $d021
!halt:
    jmp !halt-

// The KERNAL's own error code on a failed LOAD, or LL_ERR_SIGNATURE when the
// file loaded cleanly but did not contain what it should have. Lives below
// $c000 so that it is readable whichever way $01 happens to be set.
levelLoadError: .byte 0

levelSigWant:
    .byte LEVELPKG_SIG_0, LEVELPKG_SIG_1, LEVELPKG_SIG_2, LEVELPKG_SIG_3

// THE NAME, IN PETSCII. The disk directory stores the name the way the drive
// was given it; c1541 writes the upper-case ASCII letters below unchanged, and
// upper-case ASCII and PETSCII share $41-$5a, so these bytes match the
// directory entry exactly. Lower case would NOT: ASCII 'a' is $61 where
// PETSCII 'A' is $41, and the compare in the drive would fail.
levelName:
    .text "LEVEL1"
levelNameEnd:

.if (levelNameEnd - levelName > 16) { .error "a CBM filename is at most 16 characters" }
.if (* > $5400) { .error "the level loader has run into the token encounter code at $5400" }
