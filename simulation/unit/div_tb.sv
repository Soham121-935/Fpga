// SV-16 Rev B — Unit Testbench for the ALU's iterative divider (ADR-018)
//
// Why this testbench exists
// -------------------------
// DIV and MOD used to be single-cycle combinational operations. A 16/16
// combinational divider is ~68 ns of carry-chain depth on an LFE5U-12F-6 and was
// the design's critical path (Fmax 14.7 MHz, and the whole SoC had to run at
// 12.5 MHz because of it). They are now served by one iterative restoring
// divider in `sv16_alu`, driven by a start/busy handshake and held by the new
// S_DIV_WAIT state of the control unit.
//
// Checks:
//   1. every handshake rule (busy duration, when the result becomes valid,
//      what the block does with a start while busy, what it does after a reset)
//   2. the arithmetic, including every edge case the ISA documents
//   3. the flags, including divide-by-zero (OQ-04: V = 1, quotient 0xFFFF,
//      remainder 0x0000)
//   4. that the single-cycle operations are untouched by the new registers
//
// Run:  source scripts/sv16_venv.sh && make sim TB=div_tb

`timescale 1ns / 1ps

module div_tb;

    logic        clk = 1'b0;
    logic        rst_n;
    logic [15:0] a, b;
    logic [2:0]  alu_op;
    logic        is_extended;
    logic [15:0] result;
    logic        flag_z, flag_c, flag_n, flag_v;
    logic        div_start, div_busy;

    int checks = 0;
    int errors = 0;

    always #5 clk = ~clk;   // 100 MHz test clock; the block is cycle-based

    sv16_alu dut (
        .clk(clk),
        .rst_n(rst_n),
        .a(a),
        .b(b),
        .alu_op(alu_op),
        .is_extended(is_extended),
        .result(result),
        .flag_z(flag_z),
        .flag_c(flag_c),
        .flag_n(flag_n),
        .flag_v(flag_v),
        .div_start(div_start),
        .div_busy(div_busy)
    );

    task automatic check(string name, logic [15:0] got, logic [15:0] exp);
        checks++;
        if (got !== exp) begin
            errors++;
            $display("  [FAIL] %s: got 0x%04X, expected 0x%04X", name, got, exp);
        end else begin
            $display("  [PASS] %s = 0x%04X", name, got);
        end
    endtask

    task automatic check1(string name, logic got, logic exp);
        checks++;
        if (got !== exp) begin
            errors++;
            $display("  [FAIL] %s: got %0b, expected %0b", name, got, exp);
        end else begin
            $display("  [PASS] %s = %0b", name, got);
        end
    endtask

    // Combinational operations: drive the inputs, let a clock edge settle the
    // design, then look at the result (no #delays: they are ignored by Verilator).
    task automatic comb_check(input string name, input logic [2:0] op, input logic ext,
                              input logic [15:0] da, input logic [15:0] db,
                              input logic [15:0] exp);
        a = da; b = db; alu_op = op; is_extended = ext; div_start = 1'b0;
        @(negedge clk);
        check(name, result, exp);
    endtask

    // Start a divide and return the number of cycles `div_busy` stayed high.
    task automatic run_div(input logic [2:0] op, input logic [15:0] da,
                           input logic [15:0] db, output int cycles);
        a = da; b = db; alu_op = op; is_extended = 1'b1;
        @(negedge clk);
        div_start = 1'b1;
        @(negedge clk);
        div_start = 1'b0;
        cycles = 0;
        while (div_busy && cycles < 100) begin
            @(negedge clk);
            cycles++;
        end
    endtask

    initial begin
        $dumpvars(0, div_tb);
        $display("== SV-16 ALU iterative divider test (ADR-018) ==");
        rst_n = 1'b0;
        a = 16'h0000; b = 16'h0000; alu_op = 3'b011; is_extended = 1'b0; div_start = 1'b0;
        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        @(negedge clk);

        // ---------------------------------------------------------- 1. reset state
        $display("-- 1. reset state --");
        check1("not busy after reset", div_busy, 1'b0);
        alu_op = 3'b011; is_extended = 1'b1;
        @(negedge clk);
        check("no stale result after reset", result, 16'h0000);

        // ------------------------------------------------------ 2. handshake rules
        $display("-- 2. handshake --");
        begin
            int cycles;
            run_div(3'b011, 16'd100, 16'd25, cycles);
            check("busy was asserted for 16 cycles", cycles[15:0], 16'd16);
            check1("busy is low again", div_busy, 1'b0);
            check("100 / 25", result, 16'd4);
            check1("DIV leaves carry clear", flag_c, 1'b0);
            check1("DIV does not set overflow", flag_v, 1'b0);
            check1("non-zero quotient -> Z clear", flag_z, 1'b0);

            // A second start while busy must not restart the operation: the
            // result of the run in progress still has to appear.
            a = 16'd100; b = 16'd25; alu_op = 3'b011; is_extended = 1'b1;
            @(negedge clk);
            div_start = 1'b1;
            @(negedge clk);
            div_start = 1'b1;   // held high on purpose
            @(negedge clk);
            div_start = 1'b0;
            while (div_busy) @(negedge clk);
            check("start during busy did not restart the divide", result, 16'd4);
        end

        // ------------------------------------------------- 3. arithmetic + flags
        $display("-- 3. arithmetic --");
        begin
            int cycles;
            run_div(3'b011, 16'hFFFF, 16'd1, cycles);       check("0xFFFF / 1", result, 16'hFFFF);
            run_div(3'b011, 16'hFFFF, 16'hFFFF, cycles);    check("0xFFFF / 0xFFFF", result, 16'd1);
            run_div(3'b011, 16'd1000, 16'd7, cycles);       check("1000 / 7", result, 16'd142);
            run_div(3'b011, 16'd1, 16'd2, cycles);          check("1 / 2", result, 16'd0);
            check1("zero quotient sets Z", flag_z, 1'b1);
            run_div(3'b011, 16'd0, 16'd5, cycles);          check("0 / 5", result, 16'd0);
            run_div(3'b011, 16'h8000, 16'd2, cycles);       check("0x8000 / 2", result, 16'h4000);
            run_div(3'b011, 16'h8000, 16'h8000, cycles);    check("0x8000 / 0x8000", result, 16'd1);
            run_div(3'b011, 16'h8001, 16'h8000, cycles);    check("0x8001 / 0x8000", result, 16'd1);
            run_div(3'b011, 16'd40000, 16'd5000, cycles);   check("40000 / 5000", result, 16'd8);
            run_div(3'b011, 16'hFFFE, 16'd3, cycles);       check("0xFFFE / 3", result, 16'd21844);
            run_div(3'b100, 16'hFFFE, 16'd3, cycles);       check("0xFFFE % 3", result, 16'd2);
            run_div(3'b100, 16'd1000, 16'd7, cycles);       check("1000 % 7", result, 16'd6);
            run_div(3'b100, 16'd100, 16'd25, cycles);       check("100 % 25", result, 16'd0);

            // -------------------------------------------------- 4. divide by zero
            $display("-- 4. divide by zero (OQ-04) --");
            run_div(3'b011, 16'd100, 16'd0, cycles);        check("100 / 0", result, 16'hFFFF);
            check1("divide-by-zero sets V", flag_v, 1'b1);
            run_div(3'b100, 16'd100, 16'd0, cycles);        check("100 % 0", result, 16'h0000);
            check1("modulo-by-zero sets V", flag_v, 1'b1);
        end

        // ------------------------------- 5. the single-cycle operations are intact
        $display("-- 5. other operations (still one cycle) --");
        comb_check("ADD", 3'b000, 1'b0, 16'h1234, 16'h1111, 16'h2345);
        comb_check("SUB", 3'b001, 1'b0, 16'h1234, 16'h1111, 16'h0123);
        comb_check("AND", 3'b010, 1'b0, 16'hFFFF, 16'h1111, 16'h1111);
        comb_check("OR",  3'b011, 1'b0, 16'h1200, 16'h0034, 16'h1234);
        comb_check("XOR", 3'b100, 1'b0, 16'h1234, 16'h1111, 16'h0325);
        comb_check("NOT", 3'b101, 1'b0, 16'h1234, 16'h0000, 16'hEDCB);
        comb_check("INC", 3'b110, 1'b0, 16'h00FF, 16'h0000, 16'h0100);
        comb_check("DEC", 3'b111, 1'b0, 16'h0100, 16'h0000, 16'h00FF);
        comb_check("MUL", 3'b010, 1'b1, 16'd300, 16'd7, 16'd2100);
        comb_check("SHL", 3'b000, 1'b1, 16'h0001, 16'd4, 16'h0010);
        comb_check("SHR", 3'b001, 1'b1, 16'h0080, 16'd4, 16'h0008);
        check1("divider idle", div_busy, 1'b0);

        // ------------------------------------------- 6. one-cycle start pulse width
        $display("-- 6. a start pulse must be short --");
        begin
            int cycles;
            run_div(3'b011, 16'h00FF, 16'h000F, cycles);
            check("0x00FF / 0x000F", result, 16'h0011);
            check("and it still took 16 cycles", cycles[15:0], 16'd16);
        end

        $display("== %0d checks, %0d failures ==", checks, errors);
        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL");
        $finish;
    end

    // Watchdog so a handshake bug cannot hang the suite.
    initial begin
        repeat (20000) @(posedge clk);
        $display("[FAIL] timeout: simulation did not finish");
        $display("RESULT: FAIL");
        $finish;
    end

endmodule : div_tb
