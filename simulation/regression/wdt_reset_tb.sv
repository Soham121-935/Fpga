// SV-16 Rev B — Testbench: watchdog recovery of a hung application (whole SoC)
//
// The point of a watchdog is not that it counts, it is that a program which
// hangs gets restarted without anyone touching the board.  This test proves
// that end to end, with no host and no CPU assistance:
//
//   power-on
//     -> the hardware boot loader loads build/fw/wdt_hang_flash.hex out of the
//        modelled SPI flash and releases the CPU
//     -> the application marks GPIOA and arms the watchdog (PRESC = /16,
//        PRESET = 512 -> 8208 clocks), then spins forever without feeding it
//     -> the watchdog bites: sv16_startup restarts the sequence with
//        RSTCAUSE.WDT set, the loader re-boots the same image (AUTO boot)
//     -> the application starts over and hangs again, so it is restarted again
//
// Checks
//   1. the reset cause starts as POR and does not claim a watchdog bite
//   2. the loaded application runs and arms the watchdog
//   3. the first bite restarts the SoC and sets RSTCAUSE.WDT
//   4. the CPU is released again at the image entry and the application runs
//   5. a second bite follows (the watchdog survived the restart: it is cleared
//      only by the external reset pin), i.e. a program that hangs twice is
//      restarted twice
//
// Requires build/fw/wdt_hang_flash.hex (produced by `make firmware`); run the
// binary from the repository root.

`timescale 1ns / 1ps

import sv16_pkg::*;

module wdt_reset_tb;

    localparam string FLASH_IMAGE = "build/fw/wdt_hang_flash.hex";
    localparam int    ENTRY       = 16'h0000;
    localparam logic [15:0] GPIO_MARK = 16'h005A;   // what wdt_hang.s writes

    // ------------------------------------------------------------ clock/reset
    logic clk = 1'b0;
    logic ext_rst_n;

    always #10 clk = ~clk;      // 25 MHz: 40 ns period

    // ------------------------------------------------------------ SoC pins
    logic       uart_rx, uart_tx;
    logic       flash_sck, flash_cs_n, flash_mosi, flash_miso;
    logic       spi0_sck, spi0_cs_n, spi0_mosi;
    wire [15:0] gpio_a, gpio_b;
    logic       pwm_out, motor_dir1, motor_dir2, motor_fault_n;
    logic [3:0] led;

    int          errors = 0, checks = 0;

    // ---------------------------------------------------------------- the SoC
    sv16_top dut (
        .clk_25m(clk),
        .ext_rst_n(ext_rst_n),
        .uart_rx(uart_rx), .uart_tx(uart_tx),
        .flash_sck(flash_sck), .flash_cs_n(flash_cs_n),
        .flash_mosi(flash_mosi), .flash_miso(flash_miso),
        .spi0_sck(spi0_sck), .spi0_cs_n(spi0_cs_n), .spi0_mosi(spi0_mosi),
        .spi0_miso(1'b0),
        .gpio_a(gpio_a), .gpio_b(gpio_b),
        .pwm_out(pwm_out), .motor_dir1(motor_dir1), .motor_dir2(motor_dir2),
        .motor_fault_n(motor_fault_n),
        .led(led)
    );

    sv16_flash_model #(
        .MEM_BYTES(65536), .PROG_TICKS(24), .INIT_FILE(FLASH_IMAGE)
    ) flash (
        .clk(clk), .rst_n(1'b1),
        .sck(flash_sck), .cs_n(flash_cs_n), .mosi(flash_mosi), .miso(flash_miso)
    );

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

    // Wait for a watchdog bite, but fail rather than hang.
    task automatic wait_for_bite(output bit got_bite, input int limit);
        int waited;
        begin
            got_bite = 1'b0;
            waited   = 0;
            while ((waited < limit) && !got_bite) begin
                @(posedge clk);
                waited++;
                if (dut.wdt_timeout) got_bite = 1'b1;
            end
        end
    endtask

    logic        bite1, bite2;
    bit          seen_app;
    int          i;

    initial begin
        $dumpfile("wdt_reset_tb.vcd");
        $dumpvars(0, wdt_reset_tb);

        ext_rst_n = 1'b0;
        uart_rx   = 1'b1;
        repeat (8) @(posedge clk);
        ext_rst_n = 1'b1;

        // ------------------------------------------- 1. boot begins cleanly
        $display("-- 1. power-on --");
        // the sequencer holds the CPU for BOOT_DELAY_CYCLES (~32 k clocks before
        // the reset cause is recorded), so wait for it rather than guessing
        i = 0;
        while ((i < 60000) && (dut.rst_cause[RSTCAUSE_POR_BIT] == 1'b0)) begin
            @(posedge clk);
            i++;
        end
        check(dut.rst_cause[RSTCAUSE_POR_BIT] == 1'b1,
              "reset cause reports power-on after the reset hold");
        check(dut.rst_cause[RSTCAUSE_WDT_BIT] == 1'b0,
              "the power-on reset did not come from the watchdog");
        check(dut.rst_cause[RSTCAUSE_WDT_BIT] == 1'b0, "no watchdog bite yet");
        check(dut.u_wdt.enable == 1'b0, "the watchdog is disabled at reset");

        // ------------------------------- 2. the loaded application arms it
        $display("-- 2. application startup --");
        seen_app = 1'b0;
        for (i = 0; i < 400000 && !seen_app; i++) begin
            @(posedge clk);
            if (dut.u_wdt.enable && (gpio_a[7:0] == GPIO_MARK[7:0])) seen_app = 1'b1;
        end
        check(seen_app, "the application ran, marked GPIOA and armed the watchdog");
        check(dut.rst_cause[RSTCAUSE_FLASHOK_BIT] == 1'b1,
              "the image was loaded out of flash");
        check(dut.dbg_pc >= ENTRY, "the CPU is executing the image");

        // -------------------------------- 3. first bite restarts the system
        $display("-- 3. first watchdog bite --");
        wait_for_bite(bite1, 40000);
        check(bite1, "the watchdog bit the hung application");
        repeat (4) @(posedge clk);
        check(dut.rst_cause[RSTCAUSE_WDT_BIT] == 1'b1,
              "RSTCAUSE.WDT is set for the restart");
        check(dut.rst_cause[RSTCAUSE_POR_BIT] == 1'b1,
              "the earlier causes are still latched (sticky)");

        // ------------------------ 4. the application is re-booted and re-runs
        $display("-- 4. restart --");
        seen_app = 1'b0;
        for (i = 0; i < 400000 && !seen_app; i++) begin
            @(posedge clk);
            if (dut.u_wdt.enable && (gpio_a[7:0] == GPIO_MARK[7:0])) seen_app = 1'b1;
        end
        check(seen_app, "the SoC re-booted the image and the application ran again");
        check(dut.u_wdt.enable == 1'b1,
              "the watchdog stayed enabled across the restart");

        // -------------------------- 5. a second hang is caught as well
        $display("-- 5. second bite --");
        wait_for_bite(bite2, 40000);
        check(bite2, "the watchdog bit again: a program that hangs twice is restarted twice");

        // and the external reset pin does clear it
        ext_rst_n = 1'b0;
        repeat (8) @(posedge clk);
        check(dut.u_wdt.enable == 1'b0, "the external reset pin clears the watchdog");
        ext_rst_n = 1'b1;

        $display("== %0d checks, %0d failures ==", checks, errors);
        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL");
        $finish;
    end

    // fail loudly instead of hanging
    initial begin
        #60_000_000;
        $display("== TIMEOUT: testbench watchdog fired ==");
        $display("RESULT: FAIL");
        $finish;
    end

endmodule : wdt_reset_tb
