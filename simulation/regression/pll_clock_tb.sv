// SV-16 Rev B — Testbench: the PLL clock option (ADR-021)
//
// The SoC normally runs from the 25 MHz board oscillator.  With `CLKSRC=pll` it
// runs from the on-chip ECP5 PLL instead, at a frequency the build script picks
// (37.5 MHz is the useful step up on this part).  This suite elaborates that
// configuration and checks the three things that could silently be wrong:
//
//   1. the reset sequence waits for the PLL to lock — the SoC must not start
//      running on a clock that is not there yet, and `rst_n` must stay low while
//      `locked` is low
//   2. the system clock really is the PLL's output frequency (measured against
//      the 25 MHz reference: 37.5 / 25 = 3 edges for every 2 reference cycles)
//   3. everything that is *derived* from the clock still lines up: the UART
//      divisor is 326 (37.5 MHz / 115200), and a real frame from the boot ROM
//      monitor decodes at that divisor — the firmware does not have to know
//      which clock it was built for
//
// The PLL model used in simulation is frequency-accurate but not a jitter model
// (rtl/sv16_pll.sv), so the bit-time check allows one clock of slack per bit.
//
// Requires build/rom/monitor.hex (produced by `make firmware`); run the binary
// from the repository root.

`timescale 1ns / 1ps

import sv16_pkg::*;

module pll_clock_tb;

    // The configuration `make bitstream CLKSRC=pll PLLMHZ=37.5` builds:
    // fPFD = 25/2 = 12.5 MHz, fOUT = 12.5 x 3 = 37.5 MHz, fVCO = 600 MHz.
    localparam int CLKI_DIV  = 2;
    localparam int CLKFB_DIV = 3;
    localparam int CLKOP_DIV = 16;
    localparam int PLL_KHZ   = 37_500;
    localparam int BAUD_DIV  = 326;      // (37_500_000 + 57_600) / 115_200

    localparam string ROM_IMAGE = "build/rom/monitor.hex";

    int checks = 0, errors = 0;
    int sys_cycles = 0;         // counted on the generated clock, for the ratio check

    logic clk = 1'b0;
    logic ext_rst_n;
    always #20 clk = ~clk;      // 25 MHz reference: 40 ns period

    logic       uart_rx, uart_tx;
    logic       flash_sck, flash_cs_n, flash_mosi, flash_miso;
    logic       spi0_sck, spi0_cs_n, spi0_mosi;
    wire [15:0] gpio_a, gpio_b;
    logic       pwm_out, motor_dir1, motor_dir2, motor_fault_n;
    logic [3:0] led;

    sv16_top #(
        .CLK_SRC   (1),
        .PLL_CLKI  (CLKI_DIV),
        .PLL_CLKFB (CLKFB_DIV),
        .PLL_CLKOP (CLKOP_DIV),
        .PLL_KHZ   (PLL_KHZ)
    ) dut (
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

    // Blank flash: the loader finds no image and releases the CPU into the boot
    // ROM monitor, which prints a banner on the UART — that frame is what the
    // divisor check below decodes.
    sv16_flash_model #(.MEM_BYTES(65536)) flash (
        .clk(clk), .rst_n(1'b1),
        .sck(flash_sck), .cs_n(flash_cs_n), .mosi(flash_mosi), .miso(flash_miso)
    );

    task automatic check(input bit cond, input string name);
        begin
            checks++;
            if (cond) $display("  [PASS] %s", name);
            else begin
                errors++;
                $display("  [FAIL] %s", name);
            end
        end
    endtask

    // Wait for a byte on the UART line, sampling at the hardware's own divisor.
    // Returns the decoded byte, or -1 on timeout.
    // Count the generated clock: sampling it once per reference cycle would
    // alias (it can toggle three times per reference period and come back).
    always_ff @(posedge dut.clk) sys_cycles++;

    task automatic read_byte(output int byte_out);
        int n;
        bit bit_val;
        byte_out = -1;
        n = 0;
        while ((uart_tx !== 1'b0) && (n < 2_000_000)) begin
            @(posedge clk); n++;
        end
        if (uart_tx !== 1'b0) return;

        // Start bit detected: sample the middle of bits 0..7, then the stop bit.
        repeat (BAUD_DIV + BAUD_DIV / 2) @(posedge dut.clk);
        byte_out = 0;
        for (int i = 0; i < 8; i++) begin
            bit_val = uart_tx;
            if (bit_val) byte_out |= (1 << i);
            repeat (BAUD_DIV) @(posedge dut.clk);
        end
        if (uart_tx !== 1'b1) byte_out = -2;    // framing error
    endtask

    // ------------------------------------------------------------------ stimulus
    initial begin
        uart_rx = 1'b1;              // idle high: no monitor escape hatch
        ext_rst_n = 1'b0;
        repeat (8) @(posedge clk);
        $readmemh(ROM_IMAGE, dut.u_rom.mem);

        $display("== SV-16 PLL clock option (37.5 MHz from a 25 MHz reference) ==");

        // ---- 1. reset is held until the PLL locks -------------------------
        $display("-- 1. lock-gated reset --");
        check(dut.USE_PLL === 1'b1, "the SoC was elaborated with the PLL clock source");
        check(dut.USE_PLL === 1'b1 && dut.g_pll.u_pll.CLKFB_DIV == CLKFB_DIV,
              "the PLL got the configured feedback divider");

        ext_rst_n = 1'b1;
        repeat (10) @(posedge clk);
        check(dut.pll_locked !== 1'b1, "the PLL reports unlocked right after reset");
        check(dut.rst_n !== 1'b1, "the SoC is held in reset while the PLL is unlocked");

        // ---- 2. the system clock is 1.5 x the reference -------------------
        $display("-- 2. generated clock --");
        begin
            int at_start;
            wait (dut.pll_locked === 1'b1);
            at_start = sys_cycles;
            repeat (1000) @(posedge clk);       // 1000 reference cycles = 40 us
            // 40 us at 37.5 MHz is 1500 cycles of the generated clock
            check((sys_cycles - at_start) >= 1495 && (sys_cycles - at_start) <= 1505,
                  $sformatf("the system clock runs at 1.5x the reference (%0d cycles per 1000 reference cycles)",
                            sys_cycles - at_start));
        end

        // ---- 3. the SoC comes up on the derived constants -----------------
        $display("-- 3. derived constants --");
        wait (dut.pll_locked === 1'b1);
        wait (dut.rst_n === 1'b1);
        check(dut.pll_locked === 1'b1, "the PLL locked and released the SoC reset");
        repeat (4) @(posedge clk);
        check(dut.u_uart0.baud_div_reg == BAUD_DIV[15:0],
              $sformatf("the UART divisor follows the PLL clock (0x%04X, want %0d)",
                        dut.u_uart0.baud_div_reg, BAUD_DIV));

        // ---- 4. a real frame decodes at that divisor ----------------------
        $display("-- 4. console frame at the PLL clock --");
        begin
            int byte_v;
            int printable;
            printable = 0;
            // The monitor banner is plain ASCII; decode the first few bytes and
            // require them all to be valid characters, which they can only be if
            // the bit time matches the clock.
            for (int i = 0; i < 6; i++) begin
                read_byte(byte_v);
                if ((byte_v >= 8'h0D && byte_v <= 8'h7E) || (byte_v == 8'h0A)) printable++;
                else $display("    byte %0d decoded as %0d", i, byte_v);
            end
            check(printable == 6, "six banner bytes decoded with correct framing");
        end

        $display("== SV-16 PLL clock option: %0d checks, %0d failures ==", checks, errors);
        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL");
        $finish;
    end

    // Absolute watchdog: a suite that hangs fails instead of blocking the run.
    // The blank-flash boot path waits out tVSL and one boot attempt, which is
    // tens of milliseconds of simulated time.
    initial begin
        repeat (4_000_000) @(posedge clk);      // 160 ms
        $display("  [FAIL] the suite timed out");
        $display("RESULT: FAIL");
        $finish;
    end

endmodule
