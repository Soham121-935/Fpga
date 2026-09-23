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
//   3'b011 (EXT_DIV): Out = (B == 0) ? 16'hFFFF : A / B
//   3'b100 (EXT_MOD): Out = (B == 0) ? 16'h0000 : A % B
//
// Flag outputs:
//   flag_z : Set if result == 16'h0000
//   flag_c : Carry / Borrow / Shift-out bit
//   flag_n : Negative (result[15] == 1)
//   flag_v : Signed overflow or Division by zero

`timescale 1ns / 1ps

module sv16_alu (
    input  logic [15:0] a,
    input  logic [15:0] b,
    input  logic [2:0]  alu_op,
    input  logic        is_extended,
    output logic [15:0] result,
    output logic        flag_z,
    output logic        flag_c,
    output logic        flag_n,
    output logic        flag_v
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

                3'b011: begin // EXT_DIV
                    if (b == 16'h0000) begin
                        result = 16'hFFFF; // Defined per OQ-04
                        flag_c = 1'b0;
                        flag_v = 1'b1;     // Divide-by-zero sets Overflow
                    end else begin
                        result = a / b;
                        flag_c = 1'b0;
                        flag_v = 1'b0;
                    end
                end

                3'b100: begin // EXT_MOD
                    if (b == 16'h0000) begin
                        result = 16'h0000;
                        flag_c = 1'b0;
                        flag_v = 1'b1;     // Modulo-by-zero sets Overflow
                    end else begin
                        result = a % b;
                        flag_c = 1'b0;
                        flag_v = 1'b0;
                    end
                end

                default: begin
                    result = 16'h0000;
                    flag_c = 1'b0;
                    flag_v = 1'b0;
                end
            endcase
        end
    end

    // Common flags derived from result
    assign flag_z = (result == 16'h0000);
    assign flag_n = result[15];

endmodule : sv16_alu
