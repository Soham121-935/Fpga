// SV-16 Rev A — 16-Bit Arithmetic Logic Unit (ALU)
// Module: sv16_alu
//
// Operations supported:
// Standard ALU (is_extended == 0):
//   3'b000 (ALU_ADD): Out = A + B
//   3'b001 (ALU_SUB): Out = A - B
//   3'b010 (ALU_AND): Out = A & B
//   3'b011 (ALU_OR) : Out = A | B
//   3'b100 (ALU_XOR): Out = A ^ B
//   3'b101 (ALU_NOT): Out = ~A
//   3'b110 (ALU_INC): Out = A + 1
//   3'b111 (ALU_DEC): Out = A - 1
//
// Extended ALU (is_extended == 1):
//   3'b000 (EXT_SHL): Out = A << B[3:0]
//   3'b001 (EXT_SHR): Out = A >> B[3:0] (Logical shift right)
//   3'b010 (EXT_MUL): Out = (A * B)[15:0]
//   3'b011 (EXT_DIV): Out = (B == 0) ? 16'hFFFF : A / B   (MULTI-CYCLE)
//   3'b100 (EXT_MOD): Out = (B == 0) ? 16'h0000 : A % B   (MULTI-CYCLE)
//
// Multi-cycle divide (Rev B, ADR-018): DIV and MOD are the only operations that
// cannot fit in one clock on this device -- a combinational 16/16 divider costs
// ~68 ns of carry-chain depth and was the design's critical path (Fmax 14.7 MHz)
// while every other operation needs a third of that. A single iterative
// restoring divider now serves both operations: assert `div_start` for one cycle
// with A/B valid, wait for `div_busy` to fall (16 cycles later), and read the
// quotient/remainder from `result`. The ISA is unchanged: same values, same
// flags; only the cycle count differs.
//
// Flag outputs:
//   flag_z : Set if result == 16'h0000
//   flag_c : Carry / Borrow / Shift-out bit
//   flag_n : Negative (result[15] == 1)
//   flag_v : Signed overflow or Division by zero

`timescale 1ns / 1ps

module sv16_alu (
    input  logic        clk,
    input  logic        rst_n,

    input  logic [15:0] a,
    input  logic [15:0] b,
    input  logic [2:0]  alu_op,
    input  logic        is_extended,
    output logic [15:0] result,
    output logic        flag_z,
    output logic        flag_c,
    output logic        flag_n,
    output logic        flag_v,

    // Multi-cycle divide handshake (ADR-018)
    input  logic        div_start,
    output logic        div_busy
);

    logic [16:0] sum_ext;
    logic [16:0] diff_ext;
    logic [31:0] mul_ext;
    logic [3:0]  shamt;

    assign shamt = b[3:0];

    always_comb begin
        // Defaults
        result   = 16'h0000;
        flag_c   = 1'b0;
        flag_v   = 1'b0;
        sum_ext  = {1'b0, a} + {1'b0, b};
        diff_ext = {1'b0, a} - {1'b0, b};
        mul_ext  = a * b;

        if (!is_extended) begin
            case (alu_op)
                3'b000: begin // ADD
                    result = sum_ext[15:0];
                    flag_c = sum_ext[16];
                    // Signed overflow: signs of A and B match, but differ from result
                    flag_v = (a[15] == b[15]) && (result[15] != a[15]);
                end

                3'b001: begin // SUB
                    result = diff_ext[15:0];
                    flag_c = (a < b); // Borrow flag for unsigned subtraction
                    // Signed overflow: A and B have different signs, and result sign differs from A
                    flag_v = (a[15] != b[15]) && (result[15] != a[15]);
                end

                3'b010: begin // AND
                    result = a & b;
                    flag_c = 1'b0;
                    flag_v = 1'b0;
                end

                3'b011: begin // OR
                    result = a | b;
                    flag_c = 1'b0;
                    flag_v = 1'b0;
                end

                3'b100: begin // XOR
                    result = a ^ b;
                    flag_c = 1'b0;
                    flag_v = 1'b0;
                end

                3'b101: begin // NOT
                    result = ~a;
                    flag_c = 1'b0;
                    flag_v = 1'b0;
                end

                3'b110: begin // INC
                    sum_ext = {1'b0, a} + 17'd1;
                    result  = sum_ext[15:0];
                    flag_c  = sum_ext[16];
                    flag_v  = (a == 16'h7FFF); // Signed 32767 + 1 = -32768
                end

                3'b111: begin // DEC
                    diff_ext = {1'b0, a} - 17'd1;
                    result   = diff_ext[15:0];
                    flag_c   = (a == 16'h0000); // Borrow on 0 - 1
                    flag_v   = (a == 16'h8000); // Signed -32768 - 1 = +32767
                end

                default: begin
                    result = 16'h0000;
                    flag_c = 1'b0;
                    flag_v = 1'b0;
                end
            endcase
        end else begin
            // Extended ALU operations
            case (alu_op)
                3'b000: begin // EXT_SHL
                    if (shamt == 4'd0) begin
                        result = a;
                        flag_c = 1'b0;
                    end else begin
                        result = a << shamt;
                        flag_c = a[16 - shamt]; // Bit shifted out
                    end
                    flag_v = 1'b0;
                end

                3'b001: begin // EXT_SHR (Logical)
                    if (shamt == 4'd0) begin
                        result = a;
                        flag_c = 1'b0;
                    end else begin
                        result = a >> shamt;
                        flag_c = a[shamt - 1]; // Bit shifted out
                    end
                    flag_v = 1'b0;
                end

                3'b010: begin // EXT_MUL
                    result = mul_ext[15:0];
                    flag_c = (mul_ext[31:16] != 16'h0000); // High word non-zero
                    flag_v = flag_c;
                end

                3'b011: begin // EXT_DIV (computed by the iterative divider)
                    result = div_by_zero_r ? 16'hFFFF : quo_r; // per OQ-04
                    flag_c = 1'b0;
                    flag_v = div_by_zero_r; // Divide-by-zero sets Overflow
                end

                3'b100: begin // EXT_MOD (computed by the iterative divider)
                    result = div_by_zero_r ? 16'h0000 : rem_r; // per OQ-04
                    flag_c = 1'b0;
                    flag_v = div_by_zero_r; // Modulo-by-zero sets Overflow
                end

                default: begin
                    result = 16'h0000;
                    flag_c = 1'b0;
                    flag_v = 1'b0;
                end
            endcase
        end
    end

    // ------------------------------------------------- Iterative divider
    // Restoring division, one dividend bit per cycle. The invariant rem < divisor
    // is maintained at the end of every cycle, so 16 bits are enough for the
    // remainder and the 17-bit `shifted` value is only used for the compare.
    logic [15:0] dend_r;         // dividend, shifted left one bit per step
    logic [15:0] sor_r;          // divisor, latched (held stable for the whole run)
    logic [15:0] rem_r;          // running remainder
    logic [15:0] quo_r;          // quotient built MSB first
    logic [4:0]  step_r;         // 0..16: bits processed so far
    logic        div_by_zero_r;
    logic        busy_r;
    logic [16:0] shifted;

    assign shifted  = {rem_r, dend_r[15]};   // next bit shifted in
    assign div_busy = busy_r;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy_r        <= 1'b0;
            step_r        <= 5'd0;
            dend_r        <= 16'h0000;
            sor_r         <= 16'h0000;
            rem_r         <= 16'h0000;
            quo_r         <= 16'h0000;
            div_by_zero_r <= 1'b0;
        end else if (div_start && !busy_r) begin
            // One-cycle start pulse: latch the operands, clear the accumulator.
            // (A start while busy is ignored: the run in progress owns the
            // result.  The control unit never does this -- S_EXECUTE pulses
            // start once and S_DIV_WAIT then holds until busy falls.)
            busy_r        <= 1'b1;
            step_r        <= 5'd0;
            dend_r        <= a;
            sor_r         <= b;
            rem_r         <= 16'h0000;
            quo_r         <= 16'h0000;
            div_by_zero_r <= (b == 16'h0000);
        end else if (busy_r) begin
            if (shifted[16] || (shifted[15:0] >= sor_r)) begin
                rem_r <= shifted[15:0] - sor_r;      // subtract: quotient bit = 1
                quo_r <= {quo_r[14:0], 1'b1};
            end else begin
                rem_r <= shifted[15:0];              // restore: quotient bit = 0
                quo_r <= {quo_r[14:0], 1'b0};
            end
            dend_r <= {dend_r[14:0], 1'b0};
            step_r <= step_r + 5'd1;
            if (step_r == 5'd15) begin
                busy_r <= 1'b0;   // 16th bit processed: quotient/remainder valid
            end
        end
    end

    // Common flags derived from result
    assign flag_z = (result == 16'h0000);
    assign flag_n = result[15];

endmodule : sv16_alu
