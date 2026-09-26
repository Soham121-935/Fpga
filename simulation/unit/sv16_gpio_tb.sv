// SV-16 Rev B — Testbench: GPIO port (`sv16_gpio`, `0xF010` / `0xF070`)
//
// Both GPIO ports are the same module, so one testbench covers both.  What is
// checked is what firmware actually depends on:
//
//   1. reset state: every pin an input, output-enable low, pad data clear
//   2. DIR drives the pad output enable, and DATA drives the pad latch
//   3. reading DATA returns the pin for inputs and the latch for outputs
//   4. inputs are synchronised (a change appears two clocks later, not on the
//      clock that caused it)
//   5. SET and CLR are atomic: they change only the bits named, and they are
//      safe with a mixed input/output port -- which a read-modify-write write to
//      DATA is not, because DATA reads back *pins* on the input bits

`timescale 1ns / 1ps

module sv16_gpio_tb;

    logic        clk = 1'b0;
    always #10 clk = ~clk;          // 50 MHz

    logic        rst_n;
    logic [3:0]  addr;
    logic [15:0] wdata, rdata;
    logic        req, we, ack;
    logic [15:0] gpio_in, gpio_out, gpio_oen;

    int          checks = 0, errors = 0;
    logic [15:0] rd;

    localparam logic [3:0] DATA = 4'h0,
                           DIR  = 4'h1,
                           SET  = 4'h2,
                           CLR  = 4'h3;

    sv16_gpio dut (
        .clk(clk), .rst_n(rst_n),
        .addr(addr), .wdata(wdata), .rdata(rdata),
        .req(req), .we(we), .ack(ack),
        .gpio_in(gpio_in), .gpio_out(gpio_out), .gpio_oen(gpio_oen)
    );

    `include "periph_tb.svh"

    initial begin
        rst_n = 1'b0;
        addr = 4'h0; wdata = 16'h0; req = 1'b0; we = 1'b0;
        gpio_in = 16'h0000;

        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (4) @(posedge clk);

        $display("== SV-16 GPIO test ==");

        // ---- 1. reset ------------------------------------------------------
        $display("-- 1. reset state --");
        bus_read(DIR, rd);
        check_eq16(rd, 16'h0000, "DIR after reset (all inputs)");
        check_eq16(gpio_oen, 16'h0000, "pad output enable off after reset");
        bus_read(DATA, rd);
        check_eq16(rd, 16'h0000, "DATA after reset");
        check_eq16(gpio_out, 16'h0000, "pad data clear after reset");

        // ---- 2. direction and data -----------------------------------------
        $display("-- 2. DIR and DATA reach the pads --");
        bus_write(DIR, 16'h00FF);
        check_eq16(gpio_oen, 16'h00FF, "pads 7:0 became outputs");
        bus_write(DATA, 16'h00A5);
        check_eq16(gpio_out, 16'h00A5, "pad data latch follows DATA");
        bus_read(DIR, rd);
        check_eq16(rd, 16'h00FF, "DIR reads back");
        bus_read(DATA, rd);
        check_eq16(rd, 16'h00A5, "output pins read back the latch");

        // ---- 3. inputs read as pins ----------------------------------------
        $display("-- 3. reading DATA mixes pins (inputs) and latch (outputs) --");
        gpio_in = 16'h5A00;
        repeat (4) @(posedge clk);
        bus_read(DATA, rd);
        check_eq16(rd, 16'h5AA5, "inputs read as pins, outputs as the latch");

        // ---- 4. the input synchroniser -------------------------------------
        // The pin is not readable in the same clock it changes (no combinational
        // path), and it reaches the bus register exactly two clocks later: that
        // latency is what stops a mid-transition pin from being sampled.
        $display("-- 4. inputs are synchronised (two flops) --");
        begin
            int cycles;
            gpio_in[8] = 1'b1;
            check(dut.sync_stage2[8] == 1'b0,
                  "no combinational path from the pin to the register");
            cycles = 0;
            while ((dut.sync_stage2[8] !== 1'b1) && (cycles < 6)) begin
                @(negedge clk);
                cycles++;
            end
            check(cycles == 2,
                  $sformatf("pin reaches the register after 2 clocks (%0d)", cycles));
            bus_read(DATA, rd);
            check(rd[8] == 1'b1, "and the bus reads it back once it is there");
        end

        // ---- 5. SET and CLR are atomic -------------------------------------
        $display("-- 5. SET / CLR touch only the bits named --");
        bus_write(SET, 16'h0010);
        bus_read(DATA, rd);
        // high byte = pins (0x5B now that pin 8 is high), low byte = latch
        check_eq16(rd, 16'h5BB5, "SET adds one bit");
        bus_write(CLR, 16'h0001);
        bus_read(DATA, rd);
        check_eq16(rd, 16'h5BB4, "CLR removes one bit");
        check_eq16(gpio_oen, 16'h00FF, "SET/CLR leave DIR alone");
        bus_write(SET, 16'hFF00);             // bits that are *inputs* here
        check_eq16(gpio_out[15:8], 16'hFF, "SET latches the pad data");

        // Why SET/CLR matter: DATA reads back *pins* on the input bits, so a
        // read-modify-write of DATA writes those pin values into the output
        // latch.  Writing back exactly what was read is enough to corrupt it.
        bus_read(DATA, rd);
        bus_write(DATA, rd);
        check_eq16(gpio_out[15:8], 16'h5B,
                   "RMW on DATA folded the input pins into the latch (0xFF -> 0x5B)");
        check_eq16(gpio_out[7:0], 16'hB4, "the output bits themselves survived");

        // SET/CLR are write-only: a read of those offsets returns 0
        bus_read(SET, rd);
        check_eq16(rd, 16'h0000, "SET is write-only");
        bus_read(CLR, rd);
        check_eq16(rd, 16'h0000, "CLR is write-only");

        finish_suite("SV-16 GPIO test");
    end

    initial suite_timeout(200_000);

endmodule
