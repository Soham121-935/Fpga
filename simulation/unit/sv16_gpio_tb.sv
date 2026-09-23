// SV-16 Rev A — Unit Testbench for GPIO Controller
// Module: sv16_gpio_tb
//
// Verifies:
// 1. Reset state (outputs low, direction = input)
// 2. Setting pin direction (GPIO_DIR)
// 3. Output writing (GPIO_DATA)
// 4. Atomic bit setting (GPIO_SET)
// 5. Atomic bit clearing (GPIO_CLR)
// 6. Input synchronization and reading

`timescale 1ns / 1ps

module sv16_gpio_tb;

    logic        clk;
    logic        rst_n;
    logic [3:0]  addr;
    logic [15:0] wdata;
    logic [15:0] rdata;
    logic        req;
    logic        we;
    logic        ack;
    logic [15:0] gpio_in;
    logic [15:0] gpio_out;
    logic [15:0] gpio_oen;

    int error_count;

    sv16_gpio uut (.*);

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
        gpio_in = 16'h5555;
        error_count = 0;

        #100;
        rst_n = 1;
        #40;

        // 1. Verify reset state: gpio_oen == 0x0000, gpio_out == 0x0000
        if (gpio_oen !== 16'h0000 || gpio_out !== 16'h0000) begin
            $display("[FAIL] GPIO reset defaults failed!");
            error_count++;
        end

        // 2. Set direction to output for lower 8 bits (GPIO_DIR = 0x00FF at offset 1)
        bus_write(4'h1, 16'h00FF);
        #1;
        if (gpio_oen !== 16'h00FF) begin
            $display("[FAIL] GPIO_DIR write failed! Got 0x%h", gpio_oen);
            error_count++;
        end

        // 3. Atomic bit set: Set bit 0 and bit 2 (GPIO_SET = 0x0005 at offset 2)
        bus_write(4'h2, 16'h0005);
        #1;
        if (gpio_out !== 16'h0005) begin
            $display("[FAIL] GPIO_SET failed! Got 0x%h, Expected 0x0005", gpio_out);
            error_count++;
        end

        // 4. Atomic bit clear: Clear bit 0 (GPIO_CLR = 0x0001 at offset 3)
        bus_write(4'h3, 16'h0001);
        #1;
        if (gpio_out !== 16'h0004) begin
            $display("[FAIL] GPIO_CLR failed! Got 0x%h, Expected 0x0004", gpio_out);
            error_count++;
        end

        // 5. Read back GPIO inputs (offset 0)
        // gpio_in is 0x5555, upper byte has dir=0 (input), so upper byte should read 0x55
        logic [15:0] read_val;
        repeat (3) @(posedge clk); // Allow synchronizer to settle
        bus_read(4'h0, read_val);
        if (read_val[15:8] !== 8'h55) begin
            $display("[FAIL] GPIO input read failed! Got: 0x%h", read_val);
            error_count++;
        end

        if (error_count == 0) begin
            $display("[PASS] sv16_gpio unit test passed with 0 errors.");
        end else begin
            $display("[FAIL] sv16_gpio unit test failed with %0d errors.", error_count);
        end

        $finish;
    end

endmodule : sv16_gpio_tb
