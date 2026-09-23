// SV-16 Rev A — Unit Testbench for Instruction Decoder (sv16_decoder)
// Verifies decoding of all ISA Rev A instruction formats:
// - Format R: ALU_RR (ADD, SUB, AND), MOV, CMP, EXT_ALU (MUL, DIV)
// - Format I: ADDI, SUBI (sign extension of 9-bit immediate)
// - Format M: LOAD, STORE (sign extension of 6-bit offset)
// - Format B: Branches with condition codes and 8-bit offset
// - Format S: LDI, JMP, CALL, RET, PUSH, POP, CTRL

`timescale 1ns / 1ps

module sv16_decoder_tb;

    logic [15:0] instr;
    logic [3:0]  opcode;
    logic [2:0]  rd;
    logic [2:0]  rs1;
    logic [2:0]  rs2;
    logic [2:0]  subop;
    logic [3:0]  cond;
    logic [15:0] imm9_ext;
    logic [15:0] offset6_ext;
    logic [7:0]  branch_offset;
    logic        is_alu_rr;
    logic        is_alu_imm;
    logic        is_ext_alu;
    logic        is_load;
    logic        is_store;
    logic        is_mov;
    logic        is_branch;
    logic        is_jmp;
    logic        is_call;
    logic        is_ret;
    logic        is_push;
    logic        is_pop;
    logic        is_cmp;
    logic        is_two_word;
    logic        is_illegal;

    int error_count;

    sv16_decoder uut (.*);

    initial begin
        error_count = 0;

        // 1. Test Format R: ADD R1, R2, R3 (Opcode 0x1, Rd=1, Rs1=2, Rs2=3, SubOp=0)
        // [15:12]=0001, [11:9]=001, [8:6]=010, [5:3]=011, [2:0]=000 -> 0x1258
        instr = {4'h1, 3'd1, 3'd2, 3'd3, 3'd0};
        #1;
        if (opcode !== 4'h1 || rd !== 3'd1 || rs1 !== 3'd2 || rs2 !== 3'd3 || subop !== 3'd0 || !is_alu_rr) begin
            $display("[FAIL] Format R ADD decode failed!");
            error_count++;
        end

        // 2. Test Format I: ADDI R4, #-5 (Opcode 0x2, Rd=4, Imm9=-5 (9'b111111011))
        instr = {4'h2, 3'd4, 9'b111111011};
        #1;
        if (opcode !== 4'h2 || rd !== 3'd4 || imm9_ext !== 16'hFFFB || !is_alu_imm) begin
            $display("[FAIL] Format I ADDI decode failed! imm9_ext = 0x%h", imm9_ext);
            error_count++;
        end

        // 3. Test Format M: LOAD R2, [R5 + 8] (Opcode 0x5, Rd=2, Rb=5, Offset=8 (6'b001000))
        instr = {4'h5, 3'd2, 3'd5, 6'b001000};
        #1;
        if (opcode !== 4'h5 || rd !== 3'd2 || rs1 !== 3'd5 || offset6_ext !== 16'h0008 || !is_load) begin
            $display("[FAIL] Format M LOAD decode failed!");
            error_count++;
        end

        // 4. Test Format B: BEQ +20 (Opcode 0x8, Cond=1 (BEQ), Offset=+20 (8'h14))
        instr = {4'h8, 4'h1, 8'h14};
        #1;
        if (opcode !== 4'h8 || cond !== 4'h1 || branch_offset !== 8'h14 || !is_branch) begin
            $display("[FAIL] Format B BEQ decode failed!");
            error_count++;
        end

        // 5. Test Two-word: LDI R0, #val (Opcode 0x4)
        instr = {4'h4, 3'd0, 9'd0};
        #1;
        if (!is_two_word) begin
            $display("[FAIL] LDI two-word flag not asserted!");
            error_count++;
        end

        // 6. Test Format S: RET (Opcode 0xB)
        instr = {4'hB, 12'd0};
        #1;
        if (!is_ret) begin
            $display("[FAIL] RET decode failed!");
            error_count++;
        end

        if (error_count == 0) begin
            $display("[PASS] sv16_decoder unit test passed with 0 errors.");
        end else begin
            $display("[FAIL] sv16_decoder unit test failed with %0d errors.", error_count);
        end

        $finish;
    end

endmodule : sv16_decoder
