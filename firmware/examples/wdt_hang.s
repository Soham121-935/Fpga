; =====================================================================
; SV-16 Rev B — watchdog recovery example
; =====================================================================
;
; The smallest interesting MCU program: enable the watchdog, do the work once,
; then hang on purpose.  The hardware watchdog restarts the SoC, the boot loader
; reloads this image out of flash (AUTO boot is set by the engine after the
; first successful load) and the program starts over — which is exactly what an
; application that crashes in the field should do without anyone touching the
; board.
;
; Observed by simulation/regression/wdt_reset_tb.sv:
;   * GPIOA is driven with a pattern, so the test can see this program ran
;   * the watchdog is then enabled with a period long enough to outlast a
;     reset + image load (PRESC = /16, PRESET = 512 -> 513 x 16 = 8208 clocks)
;   * the program never feeds it again, so it bites, RSTCAUSE.WDT is set and
;     the whole sequence repeats
;
; Timing note: keep (PRESET + 1) x 2^PRESC comfortably larger than reset hold
; plus image load, or the watchdog will bite again during boot.  See
; docs/PERIPHERALS.md for the register semantics.

.ORG 0x0000

.EQU SYS_STAT,     0xF002     ; [0] halted .. [3] boot failed
.EQU SYS_RSTCAUSE, 0xF003     ; [3] = watchdog, sticky
.EQU GPIO_DATA,    0xF010
.EQU GPIO_DIR,     0xF011
.EQU WDT_CTRL,     0xF080     ; [0] ENABLE, [1] LOCK, [6:4] PRESC, key 0x5A
.EQU WDT_PRESET,   0xF082     ; reload value in prescaled ticks

main:
        ; 1. leave a visible mark, so the test (and a logic analyser on a real
        ;    board) can tell this program reached its startup code
        LDI  R0, GPIO_DIR
        LDI  R1, 0x00FF          ; GPIOA[7:0] are outputs
        STORE R1, [R0 + 0]

        LDI  R1, 0x005A          ; a recognisable pattern
        LDI  R0, GPIO_DATA
        STORE R1, [R0 + 0]

        ; 2. arm the watchdog: PRESET first, then CTRL (key 0x5A in [15:8])
        LDI  R0, WDT_PRESET
        LDI  R1, 0x0200          ; 512 prescaled ticks
        STORE R1, [R0 + 0]

        LDI  R0, WDT_CTRL
        LDI  R1, 0x5A41          ; key | ENABLE | PRESC = 4 (/16)
        STORE R1, [R0 + 0]

        ; 3. "work": read the reset cause, so the first pass and the passes
        ;    after a watchdog bite differ in SYS_RSTCAUSE
        LDI  R0, SYS_RSTCAUSE
        LOAD R2, [R0 + 0]

hang:
        ; 4. and now hang, exactly like a stuck control loop would.  Nothing
        ;    feeds the watchdog, so it bites and the SoC restarts.
        NOP
        NOP
        JMP  hang
