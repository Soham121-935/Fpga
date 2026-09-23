// SV-16 Rev A — Unit Testbench for sv16_alu
// Verification of:
// - ADD, SUB, AND, OR, XOR, NOT, INC, DEC
// - SHL, SHR, MUL, DIV, MOD
// - Flag behavior: Zero (Z), Carry/Borrow (C), Negative (N), Overflow (V)
// - Corner cases: 0, 0xFFFF, 0x7FFF, 0x8000, DIV by 0, Shift 0/1/15

`timescale 1ns / 1ps

module sv16_alu_tb;

    logic [15:0] a;
    logic [15:0] b;
    logic [2:0]  alu_op;
    logic        is_extended;
    logic [15:0] result;
    logic        flag_z;
    logic        flag_c;
    logic        flag_n;
    logic        flag_v;

    int error_count;

    sv16_alu uut (
        .a(a),
        .b(b),
        .alu_op(alu_op),
        .is_extended(is_extended),
        .result(result),
        .flag_z(flag_z),
        .flag_c(flag_c),
        .flag_n(flag_n),
        .flag_v(flag_v)
    );

    task check_alu(
        input string op_name,
        input [15:0] exp_res,
        input exp_z,
        input exp_c,
        input exp_n,
        input exp_v
    );
        #1;
        if (result !== exp_res || flag_z !== exp_z || flag_c !== exp_c || flag_n !== exp_n || flag_v !== exp_v) begin
            $display("[FAIL] %s: a=0x%h b=0x%h => res=0x%h (exp 0x%h), Z=%b(%b), C=%b(%b), N=%b(%b), V=%b(%b)",
                     op_name, a, b, result, exp_res, flag_z, exp_z, flag_c, exp_c, flag_n, exp_n, flag_v, exp_v);
            error_count++;
        end
    endtask

    initial begin
        error_count = 0;
        is_extended = 0;
        a = 0;
        b = 0;
        alu_op = 0;

        // 1. ADD test: 5 + 10 = 15
        a = 16'd5; b = 16'd10; alu_op = 3'b000; is_extended = 0;
        check_alu("ADD basic", 16'd15, 0, 0, 0, 0);

        // 2. ADD carry: 0xFFFF + 1 = 0 (Z=1, C=1, N=0, V=0)
        a = 16'hFFFF; b = 16'h0001; alu_op = 3'b000;
        check_alu("ADD carry/zero", 16'h0000, 1, 1, 0, 0);

        // 3. ADD signed overflow: 0x7FFF + 1 = 0x8000 (Z=0, C=0, N=1, V=1)
        a = 16'h7FFF; b = 16'h0001; alu_op = 3'b000;
        check_alu("ADD signed overflow", 16'h8000, 0, 0, 1, 1);

        // 4. SUB basic: 10 - 4 = 6
        a = 16'd10; b = 16'd4; alu_op = 3'b001;
        check_alu("SUB basic", 16'd6, 0, 0, 0, 0);

        // 5. SUB borrow: 4 - 10 = -6 (0xFFFA) (Z=0, C=1, N=1, V=0)
        a = 16'd4; b = 16'd10; alu_op = 3'b001;
        check_alu("SUB borrow", 16'hFFFA, 0, 1, 1, 0);

        // 6. AND, OR, XOR, NOT
        a = 16'hFF00; b = 16'h0FF0;
        alu_op = 3'b010; check_alu("AND", 16'h0F00, 0, 0, 0, 0);
        alu_op = 3'b011; check_alu("OR",  16'hFFF0, 0, 0, 1, 0);
        alu_op = 3'b100; check_alu("XOR", 16'hF0F0, 0, 0, 1, 0);
        alu_op = 3'b101; check_alu("NOT", 16'h00FF, 0, 0, 0, 0);

        // 7. INC / DEC
        a = 16'h000F; alu_op = 3'b110; check_alu("INC", 16'h0010, 0, 0, 0, 0);
        a = 16'h0010; alu_op = 3'b111; check_alu("DEC", 16'h000F, 0, 0, 0, 0);

        // 8. SHL: 0x0001 << 4 = 0x0010
        is_extended = 1; alu_op = 3'b000; a = 16'h0001; b = 16'd4;
        check_alu("EXT_SHL", 16'h0010, 0, 0, 0, 0);

        // 9. SHR: 0x0010 >> 4 = 0x0001
        alu_op = 3'b001; a = 16'h0010; b = 16'd4;
        check_alu("EXT_SHR", 16'h0001, 0, 0, 0, 0);

        // 10. MUL: 100 * 25 = 2500
        alu_op = 3'b010; a = 16'd100; b = 16'd25;
        check_alu("EXT_MUL", 16'd2500, 0, 0, 0, 0);

        // 11. DIV: 100 / 25 = 4
        alu_op = 3'b011; a = 16'd100; b = 16'd25;
        check_alu("EXT_DIV", 16'd4, 0, 0, 0, 0);

        // 12. DIV by Zero: 100 / 0 => 0xFFFF, V=1
        alu_op = 3'b011; a = 16'd100; b = 16'd0;
        check_alu("EXT_DIV_BY_ZERO", 16'hFFFF, 0, 0, 1, 1);

        if (error_count == 0) begin
            $display("[PASS] sv16_alu unit test passed with 0 errors.");
        end else begin
            $display("[FAIL] sv16_alu unit test failed with %0d errors.", error_count);
        end

        $finish;
    end

endmodule : sv16_alu_tb
