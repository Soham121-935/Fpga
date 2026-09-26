; =====================================================================
; SV-16 Rev B — ISA-level regression program
; =====================================================================
;
; Run by simulation/regression/isa_tb.sv: the CPU core alone, with this program
; in the RAM model, and the testbench watching the debug port.  It exists
; because the program suites exercise only the paths their own code happens to
; take, and that turned out to be a real gap -- running this program for the
; first time found that ADDI/SUBI committed a wrong value (ADR-020).
;
; It checks, in order:
;
;   1. every conditional branch through the flag combination that makes it taken
;      and the one that makes it fall through, accumulating a trace in R7
;   2. ADDI/SUBI arithmetic and their sign-extended immediate, in R5
;   3. PUSH/POP through the stack, in R2
;   4. CALL/RET with a subroutine that saves and restores the caller's register
;
; Contract with the testbench:
;
;   R7 = 0x00FF   every branch took the intended path
;   R5 = 0x00FF   the immediate-arithmetic chain ended where it should
;   R2 = 0x0003   the pushed value came back
;   R6 = 0x002A   the subroutine returned 21 * 2
;   R0 = 0x0055   the subroutine restored the caller's R0
;   SP = 0x3FFE   CALL/PUSH/POP left the stack pointer balanced
;   PC = a two-cycle JMP self-loop at the end (the machine has no HALT)

.ORG 0x0000

main:
        ; ------------------------------------------------------- branches
        ; Each pair leaves a trace bit: set = the branch behaved.
        LDI  R7, 0x0000
        LDI  R0, 0x0005
        LDI  R1, 0x0005
        CMP  R0, R1              ; 5 - 5  -> Z = 1
        BNE  z_fail              ; must not be taken
        ADDI R7, 0x0001          ; bit 0: BEQ taken / BNE untaken
z_fail:
        LDI  R0, 0x0005
        LDI  R1, 0x0006
        CMP  R0, R1              ; 5 - 6  -> Z = 0
        BEQ  nz_fail             ; must not be taken
        ADDI R7, 0x0002          ; bit 1: BNE taken / BEQ untaken
nz_fail:
        LDI  R0, 0x0001
        LDI  R1, 0x0002
        CMP  R0, R1              ; 1 - 2 borrows -> C = 1
        BNC  c_fail              ; BNC (no carry) must not be taken
        ADDI R7, 0x0004          ; bit 2: BCS taken / BNC untaken
c_fail:
        LDI  R0, 0x0000
        LDI  R1, 0x0001
        CMP  R0, R1              ; -1 -> N = 1
        BPL  n_fail              ; BPL (positive) must not be taken
        ADDI R7, 0x0008          ; bit 3: BMI taken / BPL untaken
n_fail:
        LDI  R0, 0x7FFF
        LDI  R1, 0x0001
        CMP  R0, R1              ; 32767 - 1: no signed overflow
        BVS  v_ok                ; not taken ...
        LDI  R0, 0x8000
        LDI  R1, 0x0001
        CMP  R0, R1              ; -32768 - 1 overflows -> V = 1
        BVC  v_fail              ; ... BVC must not be taken
v_ok:
        ADDI R7, 0x0010          ; bit 4: BVS taken / BVC untaken
v_fail:
        LDI  R0, 0x0003
        LDI  R1, 0x0005
        CMP  R1, R0              ; 5 - 3: positive, no overflow -> N == V
        BLT  lt_fail             ; must not be taken
        ADDI R7, 0x0040          ; bit 6: BGE taken (5 >= 3)
lt_fail:
        CMP  R0, R1              ; 3 - 5: negative, no overflow -> N != V
        BGE  ge_fail             ; must not be taken
        ADDI R7, 0x0020          ; bit 5: BLT taken (3 < 5)
ge_fail:

        ; ------------------------------- immediate arithmetic (ADDI/SUBI)
        ; The nine-bit immediate is two's complement (bit 8 is the sign), and
        ; the assembler accepts negative literals as well as the raw nine-bit
        ; form.  The chain visits both signs and borrows through zero:
        LDI  R5, 0x0100
        ADDI R5, 0x0025          ; 0x0100 + 37  = 0x0125
        ADDI R5, -5              ; 0x0125 - 5   = 0x0120
        SUBI R5, 0x0005          ; 0x0120 - 5   = 0x011B
        SUBI R5, 0x001B          ; 0x011B - 27  = 0x0100
        ADDI R5, -1              ; 0x0100 - 1   = 0x00FF   <- the expected R5

        ; ------------------------------------------------ stack round trip
        PUSH R0                  ; R0 still holds 3 from the branch section
        POP  R2                  ; R2 must get it back

        ; ------------------------------------------------------- subroutine
        LDI  R0, 0x0055          ; a value the subroutine has to preserve
        LDI  R4, 0x0015          ; argument: 21
        CALL double              ; -> R6 = 42
        LDI  R1, 0x002A
        CMP  R6, R1
        BNE  call_fail
        ADDI R7, 0x0080          ; bit 7: the call returned the right value
call_fail:

done:
        JMP  done                ; self-loop: the testbench watches the PC

; ---------------------------------------------------------------------
; double: R6 = R4 * 2, keeping the caller's R0 intact through the stack.
; ---------------------------------------------------------------------
double:
        PUSH R0
        MOV  R6, R4
        ADD  R6, R6, R4
        POP  R0
        RET
