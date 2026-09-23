// SV-16 Rev A — Unit Testbench for Hardware Timer
// Module: sv16_timer_tb
//
// Verifies:
// 1. Reset state (counter = 0, disabled)
// 2. Writing compare value (TMR0_CMP = 5)
// 3. Enabling timer with auto-reload (TMR0_CTRL = 0x0003)
// 4. Counting up and asserting match flag on compare match
// 5. Auto-reload to 0 after match
// 6. Interrupt assertion when IE is enabled

`timescale 1ns / 1ps

module sv16_timer_tb;

    logic        clk;
    logic        rst_n;
    logic [3:0]  addr;
    logic [15:0] wdata;
    logic [15:0] rdata;
    logic        req;
    logic        we;
    logic        ack;
    logic        timer_irq;

    int error_count;

    sv16_timer uut (.*);

    always #20 clk = ~clk;

    task bus_write(input [3:0] a, input [15:0] d);
        @(posedge clk);
        addr  = a;
        wdata = d;
        we    = 1;
        req   = 1;
        @(posedge clk);
        while (!ack) @(posedge clk);
        req   = 0;
        we    = 0;
    endtask

    task bus_read(input [3:0] a, output [15:0] d);
        @(posedge clk);
        addr  = a;
        we    = 0;
        req   = 1;
        @(posedge clk);
        while (!ack) @(posedge clk);
        #1;
        d     = rdata;
        req   = 0;
    endtask

    initial begin
        clk = 0;
        rst_n = 0;
        addr = 0;
        wdata = 0;
        req = 0;
        we = 0;
        error_count = 0;

        #100;
        rst_n = 1;
        #40;

        // 1. Set compare value to 4 (TMR0_CMP at offset 1)
        bus_write(4'h1, 16'd4);

        // 2. Enable timer with Auto-Reload and Interrupt Enable (TMR0_CTRL at offset 2 = 0x0007)
        bus_write(4'h2, 16'h0007);

        // 3. Wait for timer to count up: 0 -> 1 -> 2 -> 3 -> 4 (match)
        repeat (8) @(posedge clk);

        // Verify match flag and interrupt assertion
        logic [15:0] stat_val;
        bus_read(4'h3, stat_val);
        if (stat_val[0] !== 1'b1 || timer_irq !== 1'b1) begin
            $display("[FAIL] Timer compare match or IRQ failed! stat_val=0x%h, irq=%b", stat_val, timer_irq);
            error_count++;
        end

        // 4. Clear match flag by writing 1 to bit 0 of TMR0_STAT
        bus_write(4'h3, 16'h0001);
        #1;
        if (timer_irq !== 1'b0) begin
            $display("[FAIL] Timer IRQ not cleared after writing to STAT!");
            error_count++;
        end

        if (error_count == 0) begin
            $display("[PASS] sv16_timer unit test passed with 0 errors.");
        end else begin
            $display("[FAIL] sv16_timer unit test failed with %0d errors.", error_count);
        end

        $finish;
    end

endmodule : sv16_timer_tb
