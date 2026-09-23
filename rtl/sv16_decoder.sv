// SV-16 Rev B — Instruction Register & Decoder
// Module: sv16_decoder
//
// Formats decoded:
//   Format R (Register-Register ALU / MOV / CMP / EXT_ALU):
//     [15:12] Opcode | [11:9] Rd | [8:6] Rs1 | [5:3] Rs2 | [2:0] SubOp
//   Format I (Immediate ALU):
//     [15:12] Opcode | [11:9] Rd | [8:0] Imm9 (signed)
//   Format M (Memory LOAD / STORE):
//     [15:12] Opcode | [11:9] Rd/Rs (data) | [8:6] Rb (base) | [5:0] Offset6 (signed)
//   Format B (Branch):
//     [15:12] Opcode | [11:8] Cond | [7:0] Offset8 (signed)
//   Format S (Special: LDI, JMP, CALL, RET, PUSH, POP, CTRL):
//     [15:12] Opcode | [11:9] Rx | [8:0] SubOp9
//
// Register read-port mapping (fixed in Rev B):
//   rs1 -> register file read port 1, rs2 -> read port 2.
//   * Format M (LOAD):  port1 = base register Rb, destination = Rd
//   * Format M (STORE): port1 = base register Rb, port2 = data register Rd
//   * PUSH Rx:          port1 = Rx (data to push)
//   * CMP Rs1, Rs2:     port1 = Rs1, port2 = Rs2
//   Rev A mis-mapped STORE data (used the offset field) and PUSH (used bits
//   [8:6] which are zero for PUSH), so stores and pushes never wrote the
//   intended register value. See docs/ARCHITECTURE_DECISIONS.md ADR-015.

`timescale 1ns / 1ps

module sv16_decoder (
    input  logic [15:0] instr,

    // Decoded fields
    output logic [3:0]  opcode,
    output logic [2:0]  rd,
    output logic [2:0]  rs1,
    output logic [2:0]  rs2,
    output logic [2:0]  subop,
    output logic [3:0]  cond,
    output logic [8:0]  ctrl_subop,
    output logic [15:0] imm9_ext,
    output logic [15:0] offset6_ext,
    output logic [7:0]  branch_offset,

    // Instruction classification control flags
    output logic        is_alu_rr,
    output logic        is_alu_imm,
    output logic        is_ext_alu,
    output logic        is_load,
    output logic        is_store,
    output logic        is_mov,
    output logic        is_branch,
    output logic        is_jmp,
    output logic        is_call,
    output logic        is_ret,
    output logic        is_push,
    output logic        is_pop,
    output logic        is_cmp,
    output logic        is_two_word,     // Requires 2nd 16-bit immediate word
    output logic        is_illegal,

    // Decoded CTRL opcodes (opcode 0x0)
    output logic        is_nop,
    output logic        is_halt,
    output logic        is_ei,
    output logic        is_di,
    output logic        is_reti
);

    assign opcode     = instr[15:12];
    assign rd         = instr[11:9];
    assign subop      = instr[2:0];
    assign cond       = instr[11:8];
    assign ctrl_subop = instr[8:0];

    // Read port 1: base register for LOAD/STORE, pushed register for PUSH,
    // first compare operand for CMP, otherwise the format-R/I source.
    assign rs1 = (opcode == 4'h5) ? instr[8:6] :   // LOAD   : base Rb
                 (opcode == 4'h6) ? instr[8:6] :   // STORE  : base Rb
                 (opcode == 4'hC) ? instr[11:9] :  // PUSH   : data Rx
                 (opcode == 4'hE) ? instr[11:9] :  // CMP    : Rs1
                 instr[8:6];

    // Read port 2: store data register for STORE, second compare operand for
    // CMP, otherwise the format-R source.
    assign rs2 = (opcode == 4'h6) ? instr[11:9] :  // STORE  : data Rd
                 (opcode == 4'hE) ? instr[8:6] :   // CMP    : Rs2
                 instr[5:3];

    // Immediate & Offset Sign Extensions
    assign imm9_ext      = {{7{instr[8]}}, instr[8:0]};
    assign offset6_ext   = {{10{instr[5]}}, instr[5:0]};
    assign branch_offset = instr[7:0];

    always_comb begin
        is_alu_rr   = 1'b0;
        is_alu_imm  = 1'b0;
        is_ext_alu  = 1'b0;
        is_load     = 1'b0;
        is_store    = 1'b0;
        is_mov      = 1'b0;
        is_branch   = 1'b0;
        is_jmp      = 1'b0;
        is_call     = 1'b0;
        is_ret      = 1'b0;
        is_push     = 1'b0;
        is_pop      = 1'b0;
        is_cmp      = 1'b0;
        is_two_word = 1'b0;
        is_illegal  = 1'b0;

        is_nop      = 1'b0;
        is_halt     = 1'b0;
        is_ei       = 1'b0;
        is_di       = 1'b0;
        is_reti     = 1'b0;

        case (opcode)
            4'h0: begin // CTRL (NOP, HALT, EI, DI, RETI) — sub-op in [8:0]
                case (instr[8:0])
                    9'h000: is_nop  = 1'b1;
                    9'h001: is_halt = 1'b1;
                    9'h002: is_ei   = 1'b1;
                    9'h003: is_di   = 1'b1;
                    9'h004: is_reti = 1'b1;
                    default: is_illegal = 1'b1; // reserved CTRL sub-opcode
                endcase
            end

            4'h1: is_alu_rr = 1'b1; // Standard ALU R-format

            4'h2: is_alu_imm = 1'b1; // ADDI
            4'h3: is_alu_imm = 1'b1; // SUBI

            4'h4: begin // LDI (Load 16-bit Immediate, 2-word)
                is_two_word = 1'b1;
            end

            4'h5: is_load = 1'b1;  // LOAD Rd, [Rb + offset]
            4'h6: is_store = 1'b1; // STORE Rd, [Rb + offset]  (Rd = data)
            4'h7: is_mov = 1'b1;   // MOV Rd, Rs1
            4'h8: is_branch = 1'b1;// BRANCH Cond, Offset8

            4'h9: begin // JMP (2-word)
                is_jmp = 1'b1;
                is_two_word = 1'b1;
            end

            4'hA: begin // CALL (2-word)
                is_call = 1'b1;
                is_two_word = 1'b1;
            end

            4'hB: is_ret = 1'b1;   // RET
            4'hC: is_push = 1'b1;  // PUSH Rx
            4'hD: is_pop = 1'b1;   // POP Rx
            4'hE: is_cmp = 1'b1;   // CMP Rs1, Rs2
            4'hF: is_ext_alu = 1'b1;// Extended ALU (MUL, DIV, Shifts)

            default: is_illegal = 1'b1;
        endcase
    end

endmodule : sv16_decoder
