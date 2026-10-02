// SV-16 Rev B — Testbench: UART 0 (`sv16_uart`, `0xF040`)
//
// UART0 is the firmware-update port: the ROM monitor's whole protocol and every
// `make upload` byte go through it, so its register semantics and its framing
// are worth checking at the electrical level (bit by bit) rather than only
// through the monitor's own testbench.
//
//   1. reset state: TX idle high, both directions enabled, 115200 divisor
//   2. the baud divisor is clamped at 4 and reads back
//   3. a transmitted byte is framed 8-N-1, LSB first, at exactly `divisor`
//      clocks per bit -- decoded from the pin, not assumed
//   4. the TX FIFO holds 4 bytes, reports full, and clears on CTRL.TXCLR
//   5. a byte received on the pin appears in the RX FIFO and reading DATA pops
//      it
//   6. a fifth byte with the FIFO full is dropped and flags RX overrun, which is
//      write-1-to-clear
//   7. a missing stop bit flags a frame error
//   8. the CTRL write-only bits (FIFO clears) are not stored, so a
//      read-modify-write of CTRL cannot clear the FIFOs by accident

`timescale 1ns / 1ps

module sv16_uart_tb;

    logic        clk = 1'b0;
    always #10 clk = ~clk;          // 50 MHz

    logic        rst_n;
    logic [3:0]  addr;
    logic [15:0] wdata, rdata;
    logic        req, we, ack;
    logic        uart_rx, uart_tx;
    logic        uart_tx_irq, uart_rx_irq;

    int          checks = 0, errors = 0;
    logic [15:0] rd;
    int          bit_time = 16;     // clocks per bit: slow enough that the
                                    // receiver's two-flop synchroniser has no
                                    // influence on the result

    // STATUS bits, exactly as the RTL implements them (see rtl/sv16_uart.sv)
    localparam int ST_TX_READY = 0, ST_RX_VALID = 1, ST_OVERRUN = 2,
                   ST_FRAME   = 3, ST_TX_BUSY = 4, ST_TX_EMPTY = 5,
                   ST_RX_FULL = 6, ST_TX_FULL = 7;

    localparam logic [3:0] DATA = 4'h0,
                           STAT = 4'h1,
                           BAUD = 4'h2,
                           CTRL = 4'h3,
                           FIFO = 4'h4;

    sv16_uart dut (
        .clk(clk), .rst_n(rst_n),
        .addr(addr), .wdata(wdata), .rdata(rdata),
        .req(req), .we(we), .ack(ack),
        .uart_rx(uart_rx), .uart_tx(uart_tx),
        .uart_tx_irq(uart_tx_irq), .uart_rx_irq(uart_rx_irq)
    );

    `include "periph_tb.svh"

    // ---------------------------------------------------------------- helpers
    // Decode one frame from the TX pin the way a receiver does: wait for the
    // start bit's falling edge, then sample the middle of each following bit.
    task automatic decode_tx_frame(output logic [7:0] byte_out,
                                   output bit start_ok, output bit stop_ok);
        int half;
        begin
            half = bit_time / 2;
            start_ok = 1'b0;
            stop_ok  = 1'b0;
            byte_out = 8'h00;
            // wait for the line to leave idle
            while (uart_tx === 1'b1) @(negedge clk);
            // half a bit into the start bit: this is where a real UART samples
            for (int i = 0; i < half; i++) @(negedge clk);
            start_ok = (uart_tx === 1'b0);
            // one bit period later is the middle of data bit 0
            for (int b = 0; b < 8; b++) begin
                for (int i = 0; i < bit_time; i++) @(negedge clk);
                byte_out[b] = uart_tx;
            end
            for (int i = 0; i < bit_time; i++) @(negedge clk);
            stop_ok = (uart_tx === 1'b1);
        end
    endtask

    // Drive one frame into the RX pin: start, 8 data bits LSB first, stop.
    task automatic drive_rx_frame(input logic [7:0] byte_in, input bit stop_bit);
        begin
            uart_rx = 1'b0;                       // start bit
            for (int i = 0; i < bit_time; i++) @(negedge clk);
            for (int b = 0; b < 8; b++) begin
                uart_rx = byte_in[b];
                for (int i = 0; i < bit_time; i++) @(negedge clk);
            end
            uart_rx = stop_bit;
            for (int i = 0; i < bit_time; i++) @(negedge clk);
            uart_rx = 1'b1;
            for (int i = 0; i < bit_time; i++) @(negedge clk);
        end
    endtask

    initial begin
        rst_n = 1'b0;
        addr = 4'h0; wdata = 16'h0; req = 1'b0; we = 1'b0;
        uart_rx = 1'b1;

        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (4) @(posedge clk);

        $display("== SV-16 UART 0 test ==");

        // ---- 1. reset ------------------------------------------------------
        $display("-- 1. reset state --");
        check(uart_tx == 1'b1, "TX line idles high");
        bus_read(CTRL, rd);
        check_eq16(rd, 16'h0003, "CTRL after reset: TX and RX enabled");
        bus_read(BAUD, rd);
        check_eq16(rd, 217, "reset divisor = 25 MHz / 115200");
        bus_read(STAT, rd);
        check(rd[ST_TX_READY] == 1'b1, "TX ready after reset");
        check(rd[ST_TX_EMPTY] == 1'b1, "TX FIFO empty after reset");
        check(rd[ST_RX_VALID] == 1'b0, "no byte waiting after reset");
        check(rd[ST_TX_FULL] == 1'b0, "TX FIFO not full after reset");

        // ---- 2. divisor clamp ----------------------------------------------
        $display("-- 2. baud divisor --");
        bus_write(BAUD, 16'd3);
        bus_read(BAUD, rd);
        check_eq16(rd, 16'd4, "divisor 3 is clamped to 4");
        bus_write(BAUD, bit_time);
        bus_read(BAUD, rd);
        check_eq16(rd, bit_time, "divisor reads back");

        // ---- 3. framing ----------------------------------------------------
        $display("-- 3. a transmitted byte is 8-N-1 at the programmed rate --");
        begin
            logic [7:0] got;
            bit st, sp;
            fork
                decode_tx_frame(got, st, sp);
                begin
                    repeat (2) @(negedge clk);
                    bus_write(DATA, 16'h00A5);
                end
            join
            check(st == 1'b1, "start bit present");
            check(got == 8'hA5, $sformatf("payload decoded as 0x%02X", got));
            check(sp == 1'b1, "stop bit present");
        end

        // ---- 4. the TX FIFO -------------------------------------------------
        $display("-- 4. TX FIFO depth, full flag, clear --");
        repeat (bit_time * 12) @(negedge clk);        // let the shifter drain
        for (int i = 0; i < 4; i++) bus_write(DATA, 16'h0011 + i);
        bus_read(FIFO, rd);
        check(rd[6:4] == 3'd4, $sformatf("TX FIFO holds 4 bytes (%0d)", rd[6:4]));
        bus_read(STAT, rd);
        check(rd[ST_TX_FULL] == 1'b1, "TX_FULL is set with the FIFO full");
        bus_read(CTRL, rd);
        bus_write(CTRL, rd | 16'h0040);               // TXCLR
        bus_read(FIFO, rd);
        check(rd[6:4] == 3'd0, "CTRL.TXCLR emptied the TX FIFO");
        bus_read(CTRL, rd);
        check(rd[6] == 1'b0, "the TXCLR pulse is not stored in CTRL");
        check(rd[5:0] == 16'h0003, "the rest of CTRL survived the clear");
        bus_write(CTRL, 16'h0003);

        // ---- 5. receiving ---------------------------------------------------
        $display("-- 5. a received byte is pushed into the RX FIFO --");
        fork
            drive_rx_frame(8'h5A, 1'b1);
            begin
                int guard = 0;
                bus_read(STAT, rd);
                while ((rd[ST_RX_VALID] != 1'b1) && (guard < 200)) begin
                    @(negedge clk);
                    bus_read(STAT, rd);
                    guard++;
                end
                check(rd[ST_RX_VALID] == 1'b1, "RX valid after a frame arrived");
                bus_read(DATA, rd);
                check(rd[7:0] == 8'h5A, $sformatf("DATA popped 0x%02X", rd[7:0]));
                bus_read(STAT, rd);
                check(rd[ST_RX_VALID] == 1'b0, "RX FIFO empty after the read");
            end
        join

        // ---- 6. overrun ------------------------------------------------------
        $display("-- 6. a fifth byte overruns the 4-byte RX FIFO --");
        for (int i = 0; i < 5; i++) drive_rx_frame(8'h10 + i, 1'b1);
        bus_read(STAT, rd);
        check(rd[ST_OVERRUN] == 1'b1, "RX overrun flagged");
        bus_read(FIFO, rd);
        check(rd[2:0] == 3'd4, $sformatf("the FIFO kept the first 4 bytes (%0d)", rd[2:0]));
        bus_write(STAT, 16'h0004);                    // W1C the overrun bit
        bus_read(STAT, rd);
        check(rd[ST_OVERRUN] == 1'b0, "overrun is write-1-to-clear");
        bus_write(CTRL, 16'h0083);                    // RXCLR | TXCLR | enable

        // ---- 7. frame error --------------------------------------------------
        // A byte whose stop bit is missing is delivered *and* flagged (the
        // documented behaviour: the receiver must not silently eat a byte, and
        // the monitor's CRC16 is what rejects a damaged command).
        $display("-- 7. missing stop bit --");
        fork
            drive_rx_frame(8'h77, 1'b0);
            begin
                int guard = 0;
                bus_read(STAT, rd);
                while ((rd[ST_RX_VALID] != 1'b1) && (guard < 200)) begin
                    @(negedge clk);
                    bus_read(STAT, rd);
                    guard++;
                end
                check(rd[ST_RX_VALID] == 1'b1, "the byte is delivered despite the error");
                check(rd[ST_FRAME] == 1'b1, "frame error flagged");
                bus_read(DATA, rd);
                check(rd[7:0] == 8'h77, $sformatf("the byte itself is intact (0x%02X)", rd[7:0]));
            end
        join
        bus_write(STAT, 16'h0008);                    // W1C the frame error
        bus_read(STAT, rd);
        check(rd[ST_FRAME] == 1'b0, "frame error is write-1-to-clear");

        finish_suite("SV-16 UART 0 test");
    end

    initial suite_timeout(2_000_000);

endmodule
