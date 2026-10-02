// SV-16 Rev B — Testbench: watchdog timer (sv16_wdt)
//
// Functional test of the windowed, key-protected watchdog (ADR-017).  The DUT is
// driven directly on its bus port, the same way flash_ctrl_tb drives the flash
// controller.
//
// All period measurements are bite-to-bite: the DUT counts down from PRESET and
// reloads itself on expiry, so the interval between two consecutive `timeout`
// pulses is exactly (PRESET + 1) x 2^PRESC clocks, independent of when the test
// happened to look.  That makes the checks exact instead of approximate.
//
//   1. reset state
//   2. keyed writes (enable, readback, BAD_KEY)
//   3. timeout period, reset-request pulse width, auto-rearm
//   4. feeds: correct key reloads, wrong key does not
//   5. prescaler divides the period by 2^PRESC
//   6. early-warning interrupt, MARGIN ticks before expiry
//   7. windowed feeding (first period exempt, later early feeds fault)
//   8. LOCK freezes ENABLE / PRESC / PRESET / WINDOW / MARGIN (WRITE_BLOCKED)
//   9. sticky flags clear on write-1-to-clear
//  10. only the hard reset clears the block
//
// Run:  scripts/sv16_run_tb.sh simulation/unit/wdt_tb.sv wdt_tb

`timescale 1ns / 1ps

module wdt_tb;

    // ------------------------------------------------------------- clock
    logic clk = 1'b0;
    always #10 clk = ~clk;      // 50 MHz: clocks, not nanoseconds, are what matter

    // ------------------------------------------------------------ DUT pins
    logic        rst_n;
    logic [3:0]  addr;
    logic [15:0] wdata, rdata;
    logic        req, we, ack;
    logic        irq, timeout;

    int          errors = 0;
    int          checks = 0;

    sv16_wdt dut (
        .clk(clk), .rst_n(rst_n),
        .addr(addr), .wdata(wdata), .rdata(rdata),
        .req(req), .we(we), .ack(ack),
        .irq(irq), .timeout(timeout)
    );

    // ------------------------------------------------------- bus helpers
    task automatic bus_write(input logic [3:0] a, input logic [15:0] d);
        begin
            @(negedge clk);
            addr = a; wdata = d; we = 1'b1; req = 1'b1;
            do @(posedge clk); while (!ack);
            @(negedge clk);
            req = 1'b0; we = 1'b0;
        end
    endtask

    // write without waiting for the (already registered) ack: used when the test
    // must not lose cycles relative to the watchdog period
    task automatic bus_write_now(input logic [3:0] a, input logic [15:0] d);
        begin
            @(negedge clk);
            addr = a; wdata = d; we = 1'b1; req = 1'b1;
            @(posedge clk);
            @(negedge clk);
            req = 1'b0; we = 1'b0;
        end
    endtask

    task automatic bus_read(input logic [3:0] a, output logic [15:0] d);
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

    // --------------------------------------------------- timing helpers
    // Wait for the reset-request pulse and step off it, so the caller is one
    // clock after a bite with the counter freshly reloaded.
    task automatic wait_bite();
        begin
            while (!timeout) @(posedge clk);
            @(posedge clk);
        end
    endtask

    // Clocks from *now* until the next rising edge of the pulse.
    task automatic clocks_to_bite(output int cycles);
        begin
            cycles = 0;
            while (!timeout) begin
                @(posedge clk);
                cycles++;
                if (cycles > 200000) break;
            end
        end
    endtask

    // Full period: from one rising edge (inclusive) to the next.  The DUT
    // reloads on expiry, so this is exactly (PRESET + 1) x 2^PRESC clocks.
    task automatic period_clocks(output int cycles);
        begin
            while (!timeout) @(posedge clk);   // align to the pulse
            cycles = 0;
            do begin
                @(posedge clk);
                cycles++;
                if (cycles > 200000) break;
            end while (!timeout);
        end
    endtask

    // Width of the reset-request pulse, in clocks.
    task automatic pulse_width(output int cycles);
        begin
            while (!timeout) @(posedge clk);
            cycles = 1;
            @(posedge clk);
            while (timeout) begin
                @(posedge clk);
                cycles++;
            end
        end
    endtask

    // -------------------------------------------------------------- test
    localparam logic [15:0] KEY        = 16'h5A00;
    localparam logic [15:0] EN         = 16'h0001;
    localparam logic [15:0] EN_LOCK    = 16'h0003;
    localparam logic [15:0] EN_WIN     = 16'h0005;
    localparam logic [15:0] EN_IRQ     = 16'h0009;
    localparam logic [15:0] EN_PRESC_1 = 16'h0011;   // ENABLE | PRESC=1 (/2)
    localparam logic [15:0] FEED       = 16'h5A5A;

    logic [15:0] rd;
    int          cyc, cyc2, pw, offset;

    initial begin
        $dumpfile("wdt_tb.vcd");
        $dumpvars(0, wdt_tb);

        rst_n = 1'b0;
        addr  = 4'h0; wdata = 16'h0; req = 1'b0; we = 1'b0;
        repeat (5) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        // ------------------------------------------------ 1. reset state
        $display("-- 1. reset state --");
        bus_read(4'h1, rd);
        check(rd[0] == 1'b0, "not running after reset");
        check(rd[3] == 1'b0, "not locked after reset");
        check(rd[1] == 1'b0, "no timeout flag after reset");
        bus_read(4'h0, rd);
        check(rd[0] == 1'b0, "CTRL.ENABLE reads 0");
        check(rd[15:8] == 8'h00, "write-only key bits do not leak into readback");
        check(irq == 1'b0, "no interrupt while disabled");

        bus_write(4'h3, FEED);
        repeat (20) @(posedge clk);
        check(timeout == 1'b0, "a feed while disabled is ignored");

        // ---------------------------------------- 2. keyed enable + readback
        $display("-- 2. keyed writes --");
        bus_write(4'h0, 16'h0101);            // wrong key
        bus_read(4'h0, rd);
        check(rd[0] == 1'b0, "enable without the key is ignored");
        bus_read(4'h1, rd);
        check(rd[5] == 1'b1, "BAD_KEY flagged for an unkeyed write");

        bus_write(4'h2, 16'h0020);            // PRESET = 32 ticks (plain write)
        bus_read(4'h2, rd);
        check(rd == 16'h0020, "PRESET readback");

        bus_write(4'h0, KEY | EN_IRQ);        // ENABLE | IRQ_EN
        bus_read(4'h0, rd);
        check(rd[0] == 1'b1, "enabled with the key");
        check(rd[3] == 1'b1, "IRQ_EN set with the key");
        bus_read(4'h1, rd);
        check(rd[0] == 1'b1, "STAT.RUNNING follows ENABLE");

        // ------------------------------------------ 3. period and self-rearm
        $display("-- 3. timeout period --");
        period_clocks(cyc);
        check(cyc == 33, $sformatf("period is PRESET+1 = 33 clocks at PRESC=0 (got %0d)", cyc));
        bus_read(4'h1, rd);
        check(rd[1] == 1'b1, "TIMEOUT latched");
        check(rd[0] == 1'b1, "still running after a bite");

        pulse_width(pw);
        check(pw == 1, $sformatf("the reset request is a one-cycle pulse (got %0d)", pw));

        period_clocks(cyc2);
        check(cyc2 == cyc, $sformatf("counter rearmed to a full period (%0d vs %0d)", cyc2, cyc));

        // ---------------------------------------------------- 4. feed keys
        $display("-- 4. feeds --");
        bus_read(4'h1, rd);
        check(rd[5] == 1'b1, "BAD_KEY still set from the unkeyed write");
        bus_write(4'h1, 16'h0020);            // W1C BAD_KEY
        bus_read(4'h1, rd);
        check(rd[5] == 1'b0, "BAD_KEY cleared by writing a 1");

        wait_bite();
        bus_write_now(4'h3, 16'h1234);        // wrong feed value, mid-period
        clocks_to_bite(cyc);
        check((cyc >= 30) && (cyc <= 32),
              $sformatf("a rejected feed does not reload (next bite in %0d of 32)", cyc));
        bus_read(4'h1, rd);
        check(rd[5] == 1'b1, "BAD_KEY flagged for a bad feed value");

        wait_bite();
        repeat (15) @(posedge clk);           // halfway through the period: 17 left
        bus_write_now(4'h3, FEED);
        clocks_to_bite(cyc);
        // a reload shows a full period from the feed; an ignored feed would show
        // the 17 clocks that were left
        check((cyc >= 30) && (cyc <= 36),
              $sformatf("a good feed postpones the bite by a full period (got %0d, 17 if ignored)", cyc));

        // ------------------------------------------------------ 5. prescaler
        $display("-- 5. prescaler --");
        bus_write(4'h3, FEED);                // keep it quiet
        bus_write(4'h0, KEY | EN_PRESC_1);    // ENABLE | PRESC=1 -> /2
        bus_read(4'h0, rd);
        check(rd[6:4] == 3'd1, "PRESC reads back as 1");
        period_clocks(cyc);
        check((cyc >= 65) && (cyc <= 67),
              $sformatf("PRESC=1 doubles the period to 66 clocks (got %0d)", cyc));

        bus_write(4'h0, KEY | EN);            // back to /1, no IRQ
        bus_write(4'h3, FEED);

        // ----------------------------------------------- 6. early warning
        $display("-- 6. early-warning interrupt --");
        bus_write(4'h5, 16'h0004);            // MARGIN = 4 ticks
        bus_write(4'h0, KEY | EN_IRQ);        // ENABLE | IRQ_EN
        wait_bite();                          // start from a known bite
        bus_write(4'h1, 16'h0010);            // W1C IRQ_PENDING
        // Watch the interrupt and the bite in a single pass: polling a register
        // in between would itself consume clocks and skew the measurement.
        cyc = 0; cyc2 = 0;
        while (!timeout && cyc < 100) begin
            @(posedge clk);
            cyc++;
            if (irq && (cyc2 == 0)) cyc2 = cyc;   // first clock with IRQ asserted
        end
        check(cyc2 != 0, "early-warning interrupt asserted before the timeout");
        check((cyc - cyc2 >= 3) && (cyc - cyc2 <= 5),
              $sformatf("interrupt leads the bite by MARGIN = 4 ticks (got %0d)", cyc - cyc2));
        check((cyc2 >= 25) && (cyc2 <= 31),
              $sformatf("and comes only near expiry (fired %0d clocks in)", cyc2));
        bus_read(4'h1, rd);
        check(rd[4] == 1'b1, "IRQ_PENDING latched");
        bus_write(4'h1, 16'h0010);            // W1C IRQ_PENDING

        // ------------------------------------------------ 7. windowed feed
        $display("-- 7. windowed feeding --");
        bus_write(4'h2, 16'h0020);            // PRESET = 32
        bus_write(4'h4, 16'h0010);            // WINDOW = 16 ticks
        bus_write(4'h0, KEY);                 // disable, so ENABLE is a 0 -> 1 edge
        bus_write(4'h0, KEY | EN_WIN);        // ENABLE | WINDOW_EN
        bus_write_now(4'h3, FEED);            // immediately: legal (first period)
        bus_read(4'h1, rd);
        check(rd[2] == 1'b0, "the first feed after ENABLE is exempt from the window");
        check(timeout == 1'b0, "and it did not bite");

        bus_write_now(4'h3, FEED);            // again, well inside the window
        bus_read(4'h1, rd);
        check(rd[2] == 1'b1, "a feed inside the window faults");
        check(rd[1] == 1'b1, "and it requests an immediate restart");

        bus_write(4'h1, 16'h0004);            // W1C WINDOW_FAULT
        bus_read(4'h1, rd);
        check(rd[2] == 1'b0, "WINDOW_FAULT cleared by writing a 1");

        wait_bite();                          // the fault reloaded: start clean
        repeat (20) @(posedge clk);           // past the 16-tick window
        bus_write_now(4'h3, FEED);            // legal now, and re-arms the window
        bus_read(4'h1, rd);
        check(rd[2] == 1'b0, "a feed after the window is accepted");
        check(timeout == 1'b0, "and the watchdog stayed quiet");

        // ---------------------------------------------------------- 8. lock
        $display("-- 8. lock --");
        bus_write(4'h0, KEY | EN_LOCK);       // ENABLE | LOCK
        bus_read(4'h1, rd);
        check(rd[3] == 1'b1, "STAT.LOCKED follows CTRL.LOCK");

        bus_write(4'h2, 16'h0008);            // try to shorten the period
        bus_read(4'h2, rd);
        check(rd == 16'h0020, "a locked watchdog refuses a PRESET change");
        bus_write(4'h4, 16'h0001);            // try to change the window
        bus_read(4'h4, rd);
        check(rd == 16'h0010, "a locked watchdog refuses a WINDOW change");
        bus_write(4'h0, KEY | EN_PRESC_1);    // try to change the prescaler
        bus_read(4'h0, rd);
        check(rd[6:4] == 3'd0, "a locked watchdog refuses a PRESC change");
        bus_read(4'h1, rd);
        check(rd[6] == 1'b1, "WRITE_BLOCKED flagged for the refused writes");

        bus_write(4'h0, KEY);                 // try to clear ENABLE
        bus_read(4'h0, rd);
        check(rd[0] == 1'b1, "a locked watchdog cannot be disabled");

        wait_bite();
        repeat (20) @(posedge clk);           // past the window, so this is legal
        bus_write_now(4'h3, FEED);
        clocks_to_bite(cyc);
        check((cyc >= 30) && (cyc <= 36),
              $sformatf("feeds still work while locked (next bite in %0d)", cyc));

        // --------------------------------------------- 9. sticky flag clearing
        $display("-- 9. sticky flags --");
        period_clocks(cyc);                   // get a fresh TIMEOUT
        bus_read(4'h1, rd);
        check(rd[1] == 1'b1, "TIMEOUT set before clearing");
        bus_write(4'h1, 16'h0002);            // W1C TIMEOUT
        bus_read(4'h1, rd);
        check(rd[1] == 1'b0, "TIMEOUT cleared by writing a 1");
        check(rd[0] == 1'b1, "RUNNING is not clearable");

        // ------------------------------------- 10. only the hard reset clears
        $display("-- 10. hard reset --");
        rst_n = 1'b0;
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);
        bus_read(4'h0, rd);
        check(rd[0] == 1'b0, "the hard reset cleared ENABLE");
        bus_read(4'h1, rd);
        check(rd[3] == 1'b0, "the hard reset cleared LOCK");
        check(rd[1] == 1'b0, "the hard reset cleared the sticky flags");

        $display("== %0d checks, %0d failures ==", checks, errors);
        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL");
        $finish;
    end

    // fail loudly instead of hanging if the DUT stops responding
    initial begin
        #20_000_000;
        $display("== TIMEOUT: testbench watchdog fired ==");
        $display("RESULT: FAIL");
        $finish;
    end

endmodule : wdt_tb
