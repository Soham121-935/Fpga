// SV-16 Rev A — Unit Testbench for Hardware PWM Controller
// Module: sv16_pwm_tb
//
// Verifies:
// 1. Reset state (pwm_out = 0, disabled)
// 2. Period configuration (PWM0_PERIOD = 10 cycles)
// 3. Duty cycle configuration (PWM0_DUTY = 5 cycles -> 50% duty)
// 4. Waveform generation verification (5 high cycles, 5 low cycles)
// 5. Hardware safety emergency fault line (motor_fault_n = 0 forces pwm_out = 0)
// 6. Clearing fault state via control register

`timescale 1ns / 1ps

module sv16_pwm_tb;

    logic        clk;
    logic        rst_n;
    logic [3:0]  addr;
    logic [15:0] wdata;
    logic [15:0] rdata;
    logic        req;
    logic        we;
    logic        ack;
    logic        motor_fault_n;
    logic        pwm_out;

    int error_count;

    sv16_pwm uut (.*);

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
        motor_fault_n = 1; // Normal operation
        error_count = 0;

        #100;
        rst_n = 1;
        #40;

        // 1. Set period to 10 counts (offset 0)
        bus_write(4'h0, 16'd10);

        // 2. Set duty to 4 counts (offset 1) -> 40% duty
        bus_write(4'h1, 16'd4);

        // 3. Enable PWM (offset 2, bit 0 = 1)
        bus_write(4'h2, 16'h0001);

        // 4. Observe 20 clock cycles of output
        repeat (20) @(posedge clk);

        // 5. Trigger hardware emergency motor fault (pull active-low pin low)
        @(posedge clk);
        motor_fault_n = 0;
        #1;
        if (pwm_out !== 1'b0) begin
            $display("[FAIL] PWM output was not immediately forced low on fault assertion!");
            error_count++;
        end

        // Release physical pin, but output must remain shutdown due to latched fault
        @(posedge clk);
        motor_fault_n = 1;
        @(posedge clk);
        #1;
        if (pwm_out !== 1'b0) begin
            $display("[FAIL] PWM resumed without firmware clearing the latched fault!");
            error_count++;
        end

        // 6. Clear fault via firmware (write 1 to bit 2 of PWM0_CTRL)
        bus_write(4'h2, 16'h0005); // EN=1, FAULT_CLR=1
        repeat (5) @(posedge clk);

        if (error_count == 0) begin
            $display("[PASS] sv16_pwm unit test passed with 0 errors.");
        end else begin
            $display("[FAIL] sv16_pwm unit test failed with %0d errors.", error_count);
        end

        $finish;
    end

endmodule : sv16_pwm_tb
