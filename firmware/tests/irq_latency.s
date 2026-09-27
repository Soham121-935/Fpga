; =====================================================================
; SV-16 Rev B — interrupt latency program
; =====================================================================
;
; Run by simulation/regression/irq_latency_tb.sv.  The testbench drives the
; IRQ controller's source 0 (as a peripheral would), sweeps the moment the
; request arrives across the instruction stream, and measures how long the
; hardware takes to reach the handler — the number OQ-15 asked for and that
; nothing in the repository had ever produced.
;
; The loop deliberately contains DIV, the longest instruction in the ISA
; (18 cycles, ADR-018), so the sweep hits the worst case as well as the
; best case (interrupting a NOP).
;
;   R3 must be 14 afterwards: the instruction that was interrupted completed
;      and its result survived the entry/return (100 / 7)
;   R7 is the handler's own evidence that it ran (0x00AA)
;   SP must be back where it started: the entry pushes SR and PC, RETI pops
;      them, and the program never touches SP itself

.ORG 0x0000

main:
        LDI  R7, 0x0000           ; no evidence yet
        LDI  R1, 0x0064           ; 100
        LDI  R2, 0x0007           ; 7
        EI                        ; interrupts on

loop:
        DIV  R3, R1, R2           ; the long instruction: worst case to interrupt
        NOP
        JMP  loop

; ---------------------------------------------------------------------
; Interrupt vector table: 8 words at 0x0020, one handler address per source.
; Entry 0 is the source the testbench raises; the rest are left at zero, which
; the core treats as "no handler" (a trap halts rather than jumping to 0).
; ---------------------------------------------------------------------
.ORG 0x0020
        .WORD handler             ; index 0

; ---------------------------------------------------------------------
; Handler: two words of evidence and a return.  It must not disturb R1/R2
; (the interrupted instruction's operands), and it must end in RETI so the
; saved SR (and its interrupt-enable bit) comes back.
; ---------------------------------------------------------------------
.ORG 0x0040

handler:
        LDI  R7, 0x00AA           ; proof that the handler ran
        RETI
