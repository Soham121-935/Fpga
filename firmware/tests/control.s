; =====================================================================
; SV-16 Rev B — control-instruction program (DI / EI / NOP / HALT)
; =====================================================================
;
; Run by simulation/regression/control_tb.sv.  Until now no firmware used
; any of these five mnemonics, because scripts/sv16_as.py encoded all of them
; as 0x0000 (NOP): `EI` could not enable interrupts, `RETI` could not return
; from a handler, and `HALT` could not stop the core.  The ISA regression
; never noticed because it only exercises the arithmetic/memory/branch groups.
;
; The program is built to make every one of those five instructions observable:
;
;   phase 1  DI, EI, NOP, HALT
;              -> ends with SR.IE = 1, so the core must stop and an interrupt
;                 must wake it and reach the handler
;   phase 2  DI, EI, DI, HALT
;              -> ends with SR.IE = 0, so a later interrupt must NOT wake it
;   the handler is two words plus RETI, so the return path is exercised too

.ORG 0x0000

        DI                        ; 0x0003  SR.IE <- 0
        EI                        ; 0x0002  SR.IE <- 1
        NOP                       ; 0x0000
        HALT                      ; 0x0001  stop until an interrupt

after:
        DI                        ; 0x0003  SR.IE <- 0
        EI                        ; 0x0002  SR.IE <- 1
        DI                        ; 0x0003  SR.IE <- 0: nothing may wake us
        HALT                      ; 0x0001
        JMP  after                ; park here if anything does wake us

; ---------------------------------------------------------------------
; Interrupt vector table (8 words at 0x0020, one handler per source).
; Only source 0 has a handler; the rest stay zero, which the core treats as
; "no handler installed".
; ---------------------------------------------------------------------
.ORG 0x0020
        .WORD handler             ; index 0

.ORG 0x0040

handler:
        LDI  R7, 0x00A5           ; evidence that the handler ran
        RETI
