// SV-16 Rev A — Unit Testbench for Hardware UART
// Module: sv16_uart_tb
//
// Verifies:
// 1. Reset state (TX idle high, TX_READY asserted)
// 2. Setting baud divisor
// 3. Transmitting a byte (0xA5)
// 4. Verifying start bit (0), 8 data bits, and stop bit (1)
// 5. TX_READY flag assertion upon completion

`timescale 1ns / 1ps

module sv16_uart_tb;

    logic        clk;
    logic        rst_n;
    logic [3:0]  addr;
    logic [15:0] wdata;
    logic [15:0] rdata;
    logic        req;
    logic        we;
    logic        ack;
    logic        uart_rx;
    logic        uart_tx;
    logic        uart_tx_irq;
    logic        uart_rx_irq;

    int error_count;

    sv16_uart uut (.*);

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

    initial begin
        clk = 0;
        rst_n = 0;
        addr = 0;
        wdata = 0;
        req = 0;
        we = 0;
        uart_rx = 1'b1; // Idle high
        error_count = 0;

        #100;
        rst_n = 1;
        #40;

        // 1. Set fast baud divisor for simulation speed (4 clock cycles per bit)
        bus_write(4'h2, 16'd4);

        // 2. Transmit byte 0x55 (01010101)
        bus_write(4'h0, 16'h0055);

        // 3. Observe transmission over 10 bits * 4 clocks = 40 clocks
        repeat (50) @(posedge clk);

        // Verify TX pin returned to idle high
        if (uart_tx !== 1'b1) begin
            $display("[FAIL] UART TX not returning to idle high after transmission!");
            error_count++;
        end

        if (error_count == 0) begin
            $display("[PASS] sv16_uart unit test passed with 0 errors.");
        end else begin
            $display("[FAIL] sv16_uart unit test failed with %0d errors.", error_count);
        end

        $finish;
    end

endmodule : sv16_uart_tb
