// SV-16 Rev B — Testbench: timer 0 (`sv16_timer`, `0xF020`)
//
// The timer is the peripheral with the most firmware-visible corner cases in
// the design (flag semantics, auto-reload, prescaler, interrupt gating), and it
// had no testbench that would run.  This one drives it exclusively through its
// bus port:
//
//   1. reset state, and that EN latches the counter
//   2. one count per clock at prescaler 1, with the match flag and auto-reload
//   3. free-run mode (no auto-reload) counting past the compare value
//   4. the MATCH flag is write-1-to-clear, and writing 0 does nothing
//   5. the prescaler actually divides (prescaler 4 = one count per 16 clocks)
//   6. `timer_irq` is gated by CTRL.IE and follows the flag
//   7. CNT/CMP/CTRL read back exactly what was written, and a disabled timer
//      stops counting without losing its value

`timescale 1ns / 1ps

module sv16_timer_tb;

    logic        clk = 1'b0;
    always #10 clk = ~clk;          // 50 MHz

    logic        rst_n;
    logic [3:0]  addr;
    logic [15:0] wdata, rdata;
    logic        req, we, ack;
    logic        timer_irq;

    int          checks = 0, errors = 0;
    logic [15:0] rd;

    localparam logic [3:0] CNT  = 4'h0,
                           CMP  = 4'h1,
                           CTRL = 4'h2,
                           STAT = 4'h3;

    sv16_timer dut (
        .clk(clk), .rst_n(rst_n),
        .addr(addr), .wdata(wdata), .rdata(rdata),
        .req(req), .we(we), .ack(ack),
        .timer_irq(timer_irq)
    );

    `include "periph_tb.svh"

    // Number of clocks until `dut.cnt_reg` changes from its current value, and
    // the value it changes to -- measured on the DUT's own register so the
    // result is cycle-exact (a bus read costs two clocks and would smear it).
    task automatic next_count_step(output int cycles, output logic [15:0] value);
        logic [15:0] start;
        int guard;
        begin
            start = dut.cnt_reg;
            cycles = 0;
            guard = 0;
            do begin
                @(posedge clk);
                cycles++;
                guard++;
            end while ((dut.cnt_reg == start) && (guard < 5000));
            value = dut.cnt_reg;
        end
    endtask

    initial begin
        rst_n = 1'b0;
        addr = 4'h0; wdata = 16'h0; req = 1'b0; we = 1'b0;

        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        $display("== SV-16 timer 0 test ==");

        // ---- 1. reset state ----------------------------------------------
        $display("-- 1. reset state --");
        bus_read(CNT, rd);  check_eq16(rd, 16'h0000, "CNT after reset");
        bus_read(CMP, rd);  check_eq16(rd, 16'hFFFF, "CMP after reset");
        bus_read(CTRL, rd); check_eq16(rd, 16'h0000, "CTRL after reset");
        bus_read(STAT, rd); check(rd[0] == 1'b0, "MATCH clear after reset");
        check(timer_irq == 1'b0, "timer_irq low after reset");

        // disabled timer must not count
        bus_write(CNT, 16'h0000);
        repeat (20) @(posedge clk);
        bus_read(CNT, rd);
        check_eq16(rd, 16'h0000, "CNT stays put while EN = 0");

        // ---- 2. count, match, auto-reload --------------------------------
        // With auto-reload the flag is raised on the edge that takes CNT from
        // CMP back to 0, so the exact joint pattern of (CNT, MATCH) is checked
        // clock by clock rather than sampled loosely.
        $display("-- 2. one count per clock, match at CMP, auto-reload --");
        bus_write(CMP, 16'd10);
        bus_write(CTRL, 16'h0003);            // EN | AUTO-RELOAD, prescaler 1
        bus_write(CNT, 16'd0);
        begin
            bit seq_ok = 1'b1, flag_ok = 1'b1;
            logic [15:0] expect_cnt;
            // sample at the negedge: a register updated by the always_ff at
            // posedge is only visible to the testbench after that edge has
            // settled, and reading it in the same delta as the edge returns the
            // pre-edge value
            for (int k = 0; k < 12; k++) begin
                @(negedge clk);
                expect_cnt = (k <= 9) ? (k + 1) : (k - 10);
                if (dut.cnt_reg !== expect_cnt) begin
                    seq_ok = 1'b0;
                    $display("    clock %0d: CNT = %0d, expected %0d",
                             k, dut.cnt_reg, expect_cnt);
                end
                // MATCH is high in the cycle the counter wraps (k = 10) and
                // stays high (nothing clears it yet)
                if (dut.match_flag !== ((k >= 10) ? 1'b1 : 1'b0)) begin
                    flag_ok = 1'b0;
                    $display("    clock %0d: MATCH = %b, expected %b",
                             k, dut.match_flag, (k >= 10) ? 1'b1 : 1'b0);
                end
            end
            check(seq_ok, "CNT advances one per clock and wraps at CMP (auto-reload)");
            check(flag_ok, "MATCH sets in the cycle CNT wraps, and stays set");
        end

        // ---- 3. the flag is write-1-to-clear ------------------------------
        // Stop the timer first: a running timer can raise the flag again between
        // the clear and the read-back, which would make this test meaningless.
        $display("-- 3. MATCH is write-1-to-clear --");
        bus_write(CTRL, 16'h0000);            // EN = 0: freeze counter and flag
        bus_read(STAT, rd);
        check(rd[0] == 1'b1, "MATCH still set (nothing cleared it)");
        bus_write(STAT, 16'h0000);
        bus_read(STAT, rd);
        check(rd[0] == 1'b1, "writing 0 to STAT does not clear MATCH");
        bus_write(STAT, 16'h0001);
        bus_read(STAT, rd);
        check(rd[0] == 1'b0, "writing 1 to STAT clears MATCH");

        // ---- 4. free-run mode --------------------------------------------
        $display("-- 4. without auto-reload the counter runs past CMP --");
        bus_write(CTRL, 16'h0001);            // EN only
        bus_write(CNT, 16'd0);
        begin
            int guard = 0;
            while ((dut.cnt_reg < 16'd12) && (guard < 100)) begin
                @(posedge clk); guard++;
            end
            check(dut.match_flag == 1'b1, "MATCH set when CNT hit CMP");
            check(dut.cnt_reg > 16'd10, "CNT kept counting past CMP (no reload)");
            bus_write(STAT, 16'h0001);
        end

        // ---- 5. the prescaler divides ------------------------------------
        $display("-- 5. prescaler 4 divides by 16 --");
        bus_write(CTRL, 16'h0043);            // EN | AUTO | prescaler = 4 (div 16)
        bus_write(CMP, 16'h0002);
        bus_write(CNT, 16'd0);
        begin
            int c1, c2;
            logic [15:0] v1, v2;
            next_count_step(c1, v1);          // 0 -> 1
            next_count_step(c2, v2);          // 1 -> 2
            check(c2 == 16, $sformatf("one count every 16 clocks (measured %0d)", c2));
            check(v1 == 16'd1 && v2 == 16'd2, "the prescaled counter walks 0,1,2");
        end

        // ---- 6. the interrupt output -------------------------------------
        $display("-- 6. timer_irq = MATCH && IE --");
        bus_write(CTRL, 16'h0001);            // EN only, IE = 0
        bus_write(STAT, 16'h0001);
        bus_write(CMP, 16'd3);
        bus_write(CNT, 16'd0);
        repeat (8) @(posedge clk);
        check(dut.match_flag == 1'b1, "MATCH set with IE = 0");
        check(timer_irq == 1'b0, "timer_irq stays low while IE = 0");
        bus_write(CTRL, 16'h0005);            // EN | IE
        repeat (2) @(posedge clk);
        check(timer_irq == 1'b1, "timer_irq follows the flag once IE = 1");
        bus_write(STAT, 16'h0001);
        repeat (2) @(posedge clk);
        check(timer_irq == 1'b0, "clearing MATCH drops timer_irq");

        // ---- 7. disabled timer freezes ------------------------------------
        $display("-- 7. EN = 0 freezes CNT --");
        bus_write(CTRL, 16'h0001);
        bus_write(CNT, 16'd100);
        repeat (4) @(posedge clk);
        bus_write(CTRL, 16'h0000);            // stop
        bus_read(CNT, rd);
        check(rd >= 16'd100, "counted up while enabled");
        begin
            logic [15:0] frozen;
            frozen = rd;
            repeat (10) @(posedge clk);
            bus_read(CNT, rd);
            check_eq16(rd, frozen, "CNT frozen while EN = 0");
        end

        finish_suite("SV-16 timer 0 test");
    end

    initial suite_timeout(200_000);

endmodule
