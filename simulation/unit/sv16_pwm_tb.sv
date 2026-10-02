// SV-16 Rev B — Testbench: PWM 0 (`sv16_pwm`, `0xF030`)
//
// The PWM drives the board's motor carrier, and it is the one peripheral with a
// hardware safety input, so its timing and its fault path are worth checking
// cycle by cycle rather than trusting the waveform by eye:
//
//   1. reset state (period 1000, duty 0, disabled, output low)
//   2. a disabled PWM is silent and its counter is parked
//   3. period 8 / duty 4 produces exactly 8-cycle periods with 4-cycle runs
//   4. duty 0, duty = period and duty > period all behave
//   5. INVERT flips the waveform
//   6. the fault input forces the output low, latches STAT, and the latch can
//      only be cleared while the pin is high
//   7. writing a period of 0 is clamped to 1 (a 0 period would divide by zero)

`timescale 1ns / 1ps

module sv16_pwm_tb;

    logic        clk = 1'b0;
    always #10 clk = ~clk;          // 50 MHz

    logic        rst_n;
    logic [3:0]  addr;
    logic [15:0] wdata, rdata;
    logic        req, we, ack;
    logic        motor_fault_n;
    logic        pwm_out;

    int          checks = 0, errors = 0;
    logic [15:0] rd;

    localparam logic [3:0] PERIOD = 4'h0,
                           DUTY   = 4'h1,
                           CTRL   = 4'h2,
                           STAT   = 4'h3;

    sv16_pwm dut (
        .clk(clk), .rst_n(rst_n),
        .addr(addr), .wdata(wdata), .rdata(rdata),
        .req(req), .we(we), .ack(ack),
        .motor_fault_n(motor_fault_n), .pwm_out(pwm_out)
    );

    `include "periph_tb.svh"

    // Collect `n` samples of the output, one per clock, at the negedge (after
    // the counter has settled for that cycle).
    task automatic sample_wave(input int n, output string wave);
        begin
            wave = "";
            for (int i = 0; i < n; i++) begin
                @(negedge clk);
                wave = {wave, (dut.pwm_out === 1'b1) ? "1" : "0"};
            end
        end
    endtask

    // Run-length statistics of a sampled waveform: number of runs and the
    // longest one.  Phase-independent, so the checks do not care where in the
    // period the sampling happened to start.
    task automatic run_stats(input string wave, output int edges,
                             output int maxlen, output int high);
        int runlen;
        begin
            edges = 0; maxlen = 1; runlen = 1; high = 0;
            if (wave[0] == "1") high++;
            for (int i = 1; i < wave.len(); i++) begin
                if (wave[i] == wave[i-1]) runlen++;
                else begin edges++; runlen = 1; end
                if (runlen > maxlen) maxlen = runlen;
                if (wave[i] == "1") high++;
            end
        end
    endtask

    initial begin
        rst_n = 1'b0;
        addr = 4'h0; wdata = 16'h0; req = 1'b0; we = 1'b0;
        motor_fault_n = 1'b1;

        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        $display("== SV-16 PWM 0 test ==");

        // ---- 1. reset state ----------------------------------------------
        $display("-- 1. reset state --");
        bus_read(PERIOD, rd); check_eq16(rd, 16'h03E8, "PERIOD after reset");
        bus_read(DUTY, rd);   check_eq16(rd, 16'h0000, "DUTY after reset");
        bus_read(CTRL, rd);   check_eq16(rd, 16'h0000, "CTRL after reset");
        bus_read(STAT, rd);   check(rd[0] == 1'b0, "FAULT clear after reset");
        check(pwm_out == 1'b0, "output low while disabled");

        // ---- 2. disabled: silent, counter parked --------------------------
        $display("-- 2. disabled PWM --");
        bus_write(PERIOD, 16'd8);
        bus_write(DUTY, 16'd4);
        repeat (20) @(posedge clk);
        check(pwm_out == 1'b0, "still low while disabled");
        check_eq16(dut.counter_reg, 16'd0, "counter parked at 0 while disabled");

        // ---- 3. the waveform ---------------------------------------------
        $display("-- 3. period 8, duty 4 --");
        bus_write(CTRL, 16'h0001);            // enable
        begin
            string wave;
            int edges, len, high;
            sample_wave(32, wave);
            run_stats(wave, edges, len, high);
            $display("    waveform: %s", wave);
            check(high == 16, $sformatf("50%% duty gives 16 high clocks in 32 (%0d)", high));
            check(len == 4, $sformatf("every run is 4 clocks long (longest %0d)", len));
            check(edges == 8, $sformatf("8 edges in 32 clocks = period 8 (%0d)", edges));
        end

        // ---- 4. duty extremes --------------------------------------------
        $display("-- 4. duty 0 / duty = period / duty > period --");
        bus_write(DUTY, 16'd0);
        begin
            string wave;
            sample_wave(16, wave);
            check(wave == "0000000000000000", "duty 0 = always low");
        end
        bus_write(DUTY, 16'd8);               // == period
        begin
            string wave;
            sample_wave(16, wave);
            check(wave == "1111111111111111", "duty = period = always high");
        end
        bus_write(DUTY, 16'd20);              // > period
        begin
            string wave;
            sample_wave(16, wave);
            check(wave == "1111111111111111", "duty > period = always high (no glitch)");
        end

        // ---- 5. invert ----------------------------------------------------
        $display("-- 5. INVERT --");
        bus_write(DUTY, 16'd4);
        bus_write(CTRL, 16'h0003);            // enable | invert
        begin
            string wave;
            int edges, len, high;
            sample_wave(32, wave);
            run_stats(wave, edges, len, high);
            check(high == 16 && len == 4 && edges == 8,
                  "inverted duty 4/8 is the complement");
        end
        bus_write(CTRL, 16'h0001);

        // ---- 6. the hardware fault input ---------------------------------
        $display("-- 6. motor_fault_n forces the output low --");
        motor_fault_n = 1'b0;
        repeat (4) @(posedge clk);
        check(pwm_out == 1'b0, "fault kills the output immediately");
        bus_read(STAT, rd);
        check(rd[0] == 1'b1, "FAULT latched in STAT");
        check_eq16(dut.counter_reg, 16'd0, "counter reset by the fault");
        motor_fault_n = 1'b1;
        repeat (4) @(posedge clk);
        bus_read(STAT, rd);
        check(rd[0] == 1'b1, "the latch holds after the pin returns high");
        check(pwm_out == 1'b0, "output stays off while the latch is set");
        // clearing needs the pin high *and* CTRL[2]
        motor_fault_n = 1'b0;
        bus_write(CTRL, 16'h0005);            // enable | clear-fault while pin low
        repeat (2) @(posedge clk);
        bus_read(STAT, rd);
        check(rd[0] == 1'b1, "clearing is refused while the pin is still low");
        motor_fault_n = 1'b1;
        bus_write(CTRL, 16'h0005);            // clear with the pin high
        repeat (4) @(posedge clk);
        bus_read(STAT, rd);
        check(rd[0] == 1'b0, "latch cleared with the pin high");
        bus_write(CTRL, 16'h0001);
        begin
            string wave;
            sample_wave(16, wave);
            check(wave[0] == "1" || wave[1] == "1", "the waveform resumes after a fault");
        end

        // ---- 7. period 0 is clamped --------------------------------------
        $display("-- 7. period 0 --");
        bus_write(CTRL, 16'h0000);
        bus_write(PERIOD, 16'h0000);
        bus_read(PERIOD, rd);
        check_eq16(rd, 16'd1, "period 0 read back as 1 (no divide by zero)");

        finish_suite("SV-16 PWM 0 test");
    end

    initial suite_timeout(200_000);

endmodule
