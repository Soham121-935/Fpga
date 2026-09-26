// SV-16 Rev B — Testbench: ALU (`sv16_alu`)
//
// `div_tb` covers the multi-cycle divider handshake and the divide/modulo
// results (ADR-018).  This suite covers the other half of the ALU, which is the
// part every other instruction depends on: the eight standard operations with
// all four flags, and the extended shift/multiply operations.  The flags are
// what the ISA promises to firmware (`Z`, `C`, `N`, `V`) and they are also what
// the CPU's conditional branches and the DIV-flag capture in `S_DIV_WAIT` read,
// so a wrong flag is a wrong program.
//
//   1. ADD: result, carry, signed overflow, zero and negative
//   2. SUB: result, borrow, signed overflow
//   3. AND / OR / XOR / NOT: results and the always-zero C/V
//   4. INC / DEC: wrap, carry-on-wrap and signed overflow at both ends
//   5. Z and N are derived from the result for every operation
//   6. extended SHL / SHR: shift amount, shifted-out bit in C
//   7. extended MUL: low word result, C/V on overflow out of 16 bits
//   8. extended DIV / MOD: cross-checked against the divider (div_tb owns the
//      handshake itself)

`timescale 1ns / 1ps

module sv16_alu_tb;

    logic        clk = 1'b0;
    always #10 clk = ~clk;

    logic        rst_n;
    logic [15:0] a, b;
    logic [2:0]  alu_op;
    logic        is_extended;
    logic [15:0] result;
    logic        flag_z, flag_c, flag_n, flag_v;
    logic        div_start;
    logic        div_busy;

    int          checks = 0, errors = 0;

    sv16_alu dut (
        .clk(clk), .rst_n(rst_n),
        .a(a), .b(b), .alu_op(alu_op), .is_extended(is_extended),
        .result(result),
        .flag_z(flag_z), .flag_c(flag_c), .flag_n(flag_n), .flag_v(flag_v),
        .div_start(div_start), .div_busy(div_busy)
    );

    // one combinational check: result and all four flags
    task automatic chk(input string name, input logic [2:0] op,
                       input logic ext, input logic [15:0] av, input logic [15:0] bv,
                       input logic [15:0] want,
                       input logic wz, wc, wn, wv);
        begin
            checks++;
            a = av; b = bv; alu_op = op; is_extended = ext;
            #1;
            if ((result !== want) || (flag_z !== wz) || (flag_c !== wc) ||
                (flag_n !== wn) || (flag_v !== wv)) begin
                errors++;
                $display("  [FAIL] %s: %04X,%04X -> %04X C%b V%b Z%b N%b, expected %04X C%b V%b Z%b N%b",
                         name, av, bv, result, flag_c, flag_v, flag_z, flag_n,
                         want, wc, wv, wz, wn);
            end else begin
                $display("  [PASS] %s = 0x%04X (C=%b V=%b Z=%b N=%b)",
                         name, result, flag_c, flag_v, flag_z, flag_n);
            end
        end
    endtask

    task automatic check(input bit cond, input string msg);
        begin
            checks++;
            if (cond) $display("  [PASS] %s", msg);
            else begin
                errors++;
                $display("  [FAIL] %s", msg);
            end
        end
    endtask

    localparam logic [2:0] ADD = 3'b000, SUB = 3'b001, AND_ = 3'b010,
                           OR_ = 3'b011, XOR_ = 3'b100, NOT_ = 3'b101,
                           INC = 3'b110, DEC = 3'b111;
    localparam logic [2:0] SHL = 3'b000, SHR = 3'b001, MUL = 3'b010,
                           DIV = 3'b011, MOD = 3'b100;

    initial begin
        rst_n = 1'b0;
        a = 16'h0; b = 16'h0; alu_op = 3'b0; is_extended = 1'b0; div_start = 1'b0;
        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        $display("== SV-16 ALU test ==");

        $display("-- 1. ADD --");
        chk("ADD 0x1234+0x1111", ADD, 1'b0, 16'h1234, 16'h1111, 16'h2345, 0, 0, 0, 0);
        chk("ADD carry out", ADD, 1'b0, 16'hFFFF, 16'h0001, 16'h0000, 1, 1, 0, 0);
        chk("ADD +ve overflow", ADD, 1'b0, 16'h7FFF, 16'h0001, 16'h8000, 0, 0, 1, 1);
        chk("ADD -ve wrap", ADD, 1'b0, 16'h8000, 16'h8000, 16'h0000, 1, 1, 0, 1);

        $display("-- 2. SUB --");
        chk("SUB 0x1234-0x1111", SUB, 1'b0, 16'h1234, 16'h1111, 16'h0123, 0, 0, 0, 0);
        chk("SUB borrow", SUB, 1'b0, 16'h0001, 16'h0002, 16'hFFFF, 0, 1, 1, 0);
        chk("SUB -ve overflow", SUB, 1'b0, 16'h8000, 16'h0001, 16'h7FFF, 0, 0, 0, 1);
        chk("SUB equal", SUB, 1'b0, 16'h4321, 16'h4321, 16'h0000, 1, 0, 0, 0);

        $display("-- 3. AND / OR / XOR / NOT --");
        chk("AND", AND_, 1'b0, 16'hF0F0, 16'h0FF0, 16'h00F0, 0, 0, 0, 0);
        chk("AND to zero", AND_, 1'b0, 16'hFF00, 16'h00FF, 16'h0000, 1, 0, 0, 0);
        chk("OR", OR_, 1'b0, 16'hF000, 16'h00F0, 16'hF0F0, 0, 0, 1, 0);
        chk("XOR", XOR_, 1'b0, 16'hFFFF, 16'h0F0F, 16'hF0F0, 0, 0, 1, 0);
        chk("XOR same", XOR_, 1'b0, 16'hABCD, 16'hABCD, 16'h0000, 1, 0, 0, 0);
        chk("NOT", NOT_, 1'b0, 16'h00FF, 16'h0000, 16'hFF00, 0, 0, 1, 0);
        chk("NOT zero", NOT_, 1'b0, 16'h0000, 16'h0000, 16'hFFFF, 0, 0, 1, 0);

        $display("-- 4. INC / DEC --");
        chk("INC", INC, 1'b0, 16'h0000, 16'h0000, 16'h0001, 0, 0, 0, 0);
        chk("INC wrap", INC, 1'b0, 16'hFFFF, 16'h0000, 16'h0000, 1, 1, 0, 0);
        chk("INC +ve overflow", INC, 1'b0, 16'h7FFF, 16'h0000, 16'h8000, 0, 0, 1, 1);
        chk("DEC", DEC, 1'b0, 16'h0002, 16'h0000, 16'h0001, 0, 0, 0, 0);
        chk("DEC borrow", DEC, 1'b0, 16'h0000, 16'h0000, 16'hFFFF, 0, 1, 1, 0);
        chk("DEC -ve overflow", DEC, 1'b0, 16'h8000, 16'h0000, 16'h7FFF, 0, 0, 0, 1);

        $display("-- 5. N follows the result sign for every operation --");
        chk("N set for AND", AND_, 1'b0, 16'h8001, 16'h8000, 16'h8000, 0, 0, 1, 0);
        chk("N set for SHR", SHR, 1'b1, 16'hFFFF, 16'h0000, 16'hFFFF, 0, 0, 1, 0);

        $display("-- 6. extended shifts --");
        chk("SHL by 1", SHL, 1'b1, 16'h0001, 16'h0001, 16'h0002, 0, 0, 0, 0);
        chk("SHL by 4", SHL, 1'b1, 16'h000F, 16'h0004, 16'h00F0, 0, 0, 0, 0);
        chk("SHL shifts a bit out", SHL, 1'b1, 16'h8000, 16'h0001, 16'h0000, 1, 1, 0, 0);
        chk("SHL by 0", SHL, 1'b1, 16'hBEEF, 16'h0000, 16'hBEEF, 0, 0, 1, 0);
        chk("SHR logical by 1", SHR, 1'b1, 16'h8001, 16'h0001, 16'h4000, 0, 1, 0, 0);
        chk("SHR by 15", SHR, 1'b1, 16'hFFFF, 16'h000F, 16'h0001, 0, 1, 0, 0);
        chk("SHR by 0", SHR, 1'b1, 16'h1234, 16'h0000, 16'h1234, 0, 0, 0, 0);

        $display("-- 7. extended multiply --");
        chk("MUL small", MUL, 1'b1, 16'h0002, 16'h0003, 16'h0006, 0, 0, 0, 0);
        chk("MUL 0x0100 x 0x0100", MUL, 1'b1, 16'h0100, 16'h0100, 16'h0000, 1, 1, 0, 1);
        chk("MUL 0xFFFF x 0x0002", MUL, 1'b1, 16'hFFFF, 16'h0002, 16'hFFFE, 0, 1, 1, 1);

        $display("-- 8. divide / modulo reach the divider --");
        // The handshake and the arithmetic corner cases belong to div_tb; these
        // two checks only prove the ALU routes the operations to it and that
        // the divide-by-zero contract (OQ-04) is visible from this level too.
        begin
            int guard;
            a = 16'd100; b = 16'd7; alu_op = DIV; is_extended = 1'b1;
            @(negedge clk); div_start = 1'b1; @(negedge clk); div_start = 1'b0;
            guard = 0;
            while (div_busy && (guard < 64)) begin @(posedge clk); guard++; end
            repeat (2) @(negedge clk);
            check(result == 16'd14 && flag_v == 1'b0,
                  $sformatf("100 / 7 = %0d via the divider", result));
            a = 16'd100; b = 16'd0; alu_op = MOD; is_extended = 1'b1;
            @(negedge clk); div_start = 1'b1; @(negedge clk); div_start = 1'b0;
            guard = 0;
            while (div_busy && (guard < 64)) begin @(posedge clk); guard++; end
            repeat (2) @(negedge clk);
            check(result == 16'h0000 && flag_v == 1'b1,
                  "100 % 0 = 0 with V set (OQ-04)");
        end

        $display("== SV-16 ALU test: %0d checks, %0d failures ==", checks, errors);
        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL");
        $finish;
    end

    initial begin
        #200_000;
        $display("RESULT: FAIL (timeout)");
        $finish;
    end

endmodule
