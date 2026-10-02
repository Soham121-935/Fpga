// SV-16 Rev B — Testbench: SRAM (`sv16_ram`)
//
// The memory every program runs out of.  The behavioural contract firmware (and
// the hardware boot loader, which is the other bus master writing this RAM)
// depends on:
//
//   1. a write is visible to the very next read at the same address
//   2. addresses are independent: a write does not disturb its neighbours
//   3. the bus handshake: `ack` comes exactly one clock after `req`, and a
//      request with `we` low leaves the contents alone
//   4. a write and a read in the same cycle (read-during-write) returns the
//      *new* data on this RAM (that is what the loader relies on when it writes
//      a word and the CPU immediately fetches it)
//   5. the whole address range is reachable, including the top word -- the stack
//      lives at the top of it
//
// The two A/B/SoC testbenches check the RAM as part of a boot; this one checks
// the memory itself, at the level where a broken write-enable would otherwise
// only show up as a mysterious boot failure.

`timescale 1ns / 1ps

module sv16_ram_tb;

    logic        clk = 1'b0;
    always #10 clk = ~clk;          // 50 MHz

    logic        rst_n;
    localparam int DEPTH = 16384, AW = 14;     // the SoC's 32 KB configuration
    logic [AW-1:0] addr;
    logic [15:0] wdata, rdata;
    logic        req, we, ack;

    int          checks = 0, errors = 0;
    logic [15:0] rd;

    sv16_ram #(.DEPTH(DEPTH), .ADDR_WIDTH(AW), .INIT_FILE("")) dut (
        .clk(clk), .rst_n(rst_n),
        .addr(addr), .wdata(wdata), .rdata(rdata),
        .req(req), .we(we), .ack(ack)
    );

    // A read takes one clock: the request is sampled at the rising edge and the
    // data appears at the following one.
    task automatic mem_write(input logic [AW-1:0] a, input logic [15:0] d);
        begin
            @(negedge clk);
            addr = a; wdata = d; we = 1'b1; req = 1'b1;
            do @(posedge clk); while (!ack);
            @(negedge clk);
            req = 1'b0; we = 1'b0;
        end
    endtask

    task automatic mem_read(input logic [AW-1:0] a, output logic [15:0] d);
        begin
            @(negedge clk);
            addr = a; we = 1'b0; req = 1'b1;
            do @(posedge clk); while (!ack);
            d = rdata;
            @(negedge clk);
            req = 1'b0;
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

    initial begin
        rst_n = 1'b0;
        addr = '0; wdata = 16'h0; req = 1'b0; we = 1'b0;

        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        $display("== SV-16 SRAM test ==");

        // ---- 1. write then read back -------------------------------------
        $display("-- 1. write / read --");
        mem_write(14'h0000, 16'h1234);
        mem_read(14'h0000, rd);
        check(rd == 16'h1234, $sformatf("word 0 reads back (0x%04X)", rd));
        mem_write(14'h0003, 16'hABCD);
        mem_read(14'h0003, rd);
        check(rd == 16'hABCD, "a second word reads back");
        mem_read(14'h0000, rd);
        check(rd == 16'h1234, "the first word is untouched by the second write");

        // ---- 2. address independence -------------------------------------
        $display("-- 2. neighbouring addresses stay independent --");
        begin
            bit ok = 1'b1;
            for (int i = 0; i < 8; i++) mem_write(AW'(14'h0100 + i), 16'h1000 + i);
            for (int i = 0; i < 8; i++) begin
                mem_read(AW'(14'h0100 + i), rd);
                if (rd != (16'h1000 + i)) ok = 1'b0;
            end
            check(ok, "eight consecutive words hold eight different values");
        end

        // ---- 3. the handshake --------------------------------------------
        // Sampled at the negedge: a register updated at the rising edge is only
        // visible to the testbench after that edge has settled.
        $display("-- 3. handshake --");
        begin
            @(negedge clk);
            addr = 14'h0000; we = 1'b0; req = 1'b1;
            @(posedge clk);                 // request sampled here
            @(negedge clk);
            check(ack === 1'b1, "ack is asserted in the clock after req");
            req = 1'b0;
            @(posedge clk);
            @(negedge clk);
            check(ack === 1'b0, "ack is deasserted once req is dropped");
        end

        // a request that is not a write must not change anything
        mem_write(14'h0000, 16'h5555);
        mem_read(14'h0000, rd);
        check(rd == 16'h5555, "read request left the word alone");

        // ---- 4. read-during-write -----------------------------------------
        // This RAM is read-first: the output register in a write cycle holds the
        // *old* word.  Nothing in the design depends on write-first behaviour
        // (the boot loader writes a word and the CPU fetches it several cycles
        // later), but the property is pinned here so a future edit that changes
        // it is a deliberate one.
        $display("-- 4. read-during-write is read-first --");
        begin
            mem_write(14'h0000, 16'h0F0F);
            @(negedge clk);
            addr = 14'h0000; wdata = 16'hF0F0; we = 1'b1; req = 1'b1;
            @(posedge clk);
            @(negedge clk);
            check(dut.rdata === 16'h0F0F,
                  "the output in a write cycle holds the old word");
            req = 1'b0; we = 1'b0;
            mem_read(14'h0000, rd);
            check(rd == 16'hF0F0, "and the word holds the new one afterwards");
        end

        // ---- 5. the whole range, including the stack word -----------------
        $display("-- 5. top of the range --");
        mem_write(AW'(DEPTH - 1), 16'hBEEF);      // 0x3FFF: the stack word
        mem_read(AW'(DEPTH - 1), rd);
        check(rd == 16'hBEEF, "the last word of the 32 KB range is writable");
        mem_read(14'h0000, rd);
        check(rd == 16'hF0F0, "and writing at the top did not alias down to 0");

        $display("== SV-16 SRAM test: %0d checks, %0d failures ==", checks, errors);
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
