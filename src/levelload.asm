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

levelLoad:
    lda #levelNameEnd - levelName
    ldx #<levelName
    ldy #>levelName
    jsr SETNAM

    lda #LEVEL_SA                       // logical file number; any free one
    ldx #LEVEL_DEVICE
    ldy #LEVEL_SA
    jsr SETLFS

    lda #0                              // 0 = LOAD (1 would be VERIFY)
    ldx #<LEVELPKG_BASE                 // ignored with SA = 1, supplied anyway
    ldy #>LEVELPKG_BASE                 // so no register reaches the KERNAL
    jsr KLOAD                           // holding whatever BASIC left in it
    bcs levelLoadFailed                 // carry set: A holds the KERNAL error

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
    rts

levelSigBad:
    lda #LL_ERR_SIGNATURE
    // falls through

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
