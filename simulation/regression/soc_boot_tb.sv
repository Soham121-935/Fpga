// SV-16 Rev B — Testbench: whole-SoC power-on, boot and CPU handover
//
// This is the end-to-end proof that the design behaves like a
// microcontroller rather than an FPGA that happens to contain a CPU:
//
//   power-on reset
//     -> sv16_startup holds the CPU in reset and waits out tVSL
//     -> sv16_boot streams the stored image out of the (modelled) SPI flash
//        through sv16_flash_ctrl and writes it into SRAM over the system bus
//     -> magic + header CRC16 + payload CRC16 are verified
//     -> the CPU is released at the image entry point with the image's SP
//     -> the firmware runs and drives the peripherals
//
// Nothing is preloaded into SRAM: the only copy of the program is in flash.
//
// Checks
//   1. reset cause reports a power-on reset and no CPU activity before release
//   2. the image is authenticated and the CPU is released at entry/SP
//   3. SRAM holds the payload words copied out of flash
//   4. the released CPU executes the firmware: the program counter traverses
//      the image and settles in the firmware's main loop
//   5. the firmware's MMIO writes reach the peripherals (GPIO/PWM)
//
// Requires build/fw/motor_test_flash.hex and build/fw/motor_test_words.hex
// (produced by `make firmware`); run the binary from the repository root.

`timescale 1ns / 1ps

import sv16_pkg::*;

module soc_boot_tb;

    localparam string FLASH_IMAGE = "build/fw/motor_test_flash.hex";
    localparam string IMG_WORDS   = "build/fw/motor_test_words.hex";
    localparam int    IMG_WORDS_N = 39;

    // motor_test.s layout: the program ends with
    //   main_loop: NOP / NOP / JMP main_loop   (words 30..33)
    localparam int    LOOP_LO = 30;
    localparam int    LOOP_HI = 33;

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

    logic [15:0] exp_words [0:IMG_WORDS_N-1];
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

    // ------------------------------------------------------- SPI flash model
    sv16_flash_model #(.MEM_BYTES(131072), .PROG_TICKS(24), .INIT_FILE(FLASH_IMAGE))
    flash (
        .clk(clk), .rst_n(1'b1),
        .sck(flash_sck), .cs_n(flash_cs_n), .mosi(flash_mosi), .miso(flash_miso)
    );

    // --------------------------------------------------------- bus observers
    // The CPU bus is inside the SoC; observe the peripheral-side effects
    // instead, which is what actually matters to an application.

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

    // --------------------------------------------------------- observations
    bit  cpu_ran_early;         // CPU fetched anything before the handover
    int  loop_hits;             // distinct main-loop addresses visited

    initial begin
        // CPU must stay parked while the loader runs; the loader itself is
        // bus master, so the CPU bus must be quiet.
        cpu_ran_early = 1'b0;
    end

    // The CPU must not execute anything before the handover.
    always @(posedge clk) begin
        if (ext_rst_n && dut.cpu_rst_n && !dut.cpu_halt_req) begin
            // released: nothing to check here
        end else if (ext_rst_n && !dut.cpu_rst_n && dut.u_cpu.pc_val !== 16'h0000) begin
            cpu_ran_early = 1'b1;
        end
    end

    // Watch the application program counter once the CPU is released.
    int  last_pc = -1;
    bit  seen_loop [LOOP_LO:LOOP_HI];
    initial begin
        for (int i = LOOP_LO; i <= LOOP_HI; i++) seen_loop[i] = 1'b0;
        loop_hits = 0;
    end

    always @(posedge clk) begin
        if (dut.cpu_rst_n && !dut.cpu_halt_req) begin
            if (dut.dbg_pc !== last_pc) begin
                last_pc = dut.dbg_pc;
                if ((dut.dbg_pc >= LOOP_LO) && (dut.dbg_pc <= LOOP_HI)) begin
                    if (!seen_loop[dut.dbg_pc]) begin
                        seen_loop[dut.dbg_pc] = 1'b1;
                        loop_hits++;
                    end
                end
            end
        end
    end

    // ---------------------------------------------------------------- the test
    logic [15:0] rd;
    bit          all_loop_seen;
    int          guard;

    initial begin
        $readmemh(IMG_WORDS, exp_words);

        ext_rst_n  = 1'b0;
        uart_rx    = 1'b1;          // idle high: do not request the monitor
        motor_fault_n = 1'b1;

        repeat (10) @(posedge clk);
        $display("== SV-16 SoC boot / handover test ==");

        // ---- 1. reset behaviour -----------------------------------------
        $display("-- 1. power-on reset --");
        repeat (10) @(posedge clk);
        check(dut.rst_n == 1'b0, "hard reset asserted while the pin is low");
        check(dut.cpu_rst_n == 1'b0, "CPU held in reset during power-on");
        check(dut.cpu_halt_req == 1'b1, "CPU halt requested during power-on");
        check(dut.boot_auto == 1'b1, "firmware image boot is the default");

        ext_rst_n = 1'b1;

        // ---- 2. wait for the boot sequence ------------------------------
        $display("-- 2. boot sequence --");
        guard = 0;
        while (!dut.img_ok && (guard < 3_000_000)) begin
            @(posedge clk);
            guard++;
        end
        check(dut.img_ok == 1'b1, "image authenticated and loaded from flash");
        check(guard < 3_000_000, "boot completed without timing out");
        check(cpu_ran_early == 1'b0, "CPU did not execute before the handover");

        // the sequencer needs a couple of cycles to act on the verdict
        guard = 0;
        while (dut.cpu_halt_req && (guard < 100)) begin
            @(posedge clk);
            guard++;
        end
        repeat (4) @(posedge clk);

        // ---- 3. reset cause -------------------------------------------
        $display("-- 3. reset cause and status --");
        // SYS_RSTCAUSE is at 0xF003; read it over the (now idle) CPU bus using
        // the debug window would need firmware, so check the startup signals.
        check(dut.rst_cause[RSTCAUSE_POR_BIT] == 1'b1, "RSTCAUSE: power-on reset");
        check(dut.rst_cause[RSTCAUSE_FLASHOK_BIT] == 1'b1, "RSTCAUSE: flash image booted");
        check(dut.rom_monitor == 1'b0, "not running the ROM monitor");

        // ---- 4. CPU handover -------------------------------------------
        $display("-- 4. CPU handover --");
        check(dut.cpu_rst_n == 1'b1, "CPU released from reset");
        check(dut.cpu_halt_req == 1'b0, "CPU halt released");
        check(dut.u_cpu.sp_reg == 16'h3FFE, "stack pointer loaded from the image header");

        // ---- 5. SRAM holds what the loader streamed out of flash --------
        $display("-- 5. SRAM contents --");
        begin
            bit words_match = 1'b1;
            for (int i = 0; i < IMG_WORDS_N; i++) begin
                if (dut.u_ram.mem[i] !== exp_words[i]) begin
                    words_match = 1'b0;
                    $display("    word %0d: ram=0x%04x exp=0x%04x", i, dut.u_ram.mem[i], exp_words[i]);
                end
            end
            check(words_match, "SRAM matches the image payload");
        end

        // ---- 6. the firmware actually runs ------------------------------
        $display("-- 6. firmware execution --");
        guard = 0;
        while ((loop_hits < (LOOP_HI - LOOP_LO + 1)) && (guard < 200000)) begin
            @(posedge clk);
            guard++;
        end
        all_loop_seen = 1'b1;
        for (int i = LOOP_LO; i <= LOOP_HI; i++) if (!seen_loop[i]) all_loop_seen = 1'b0;
        check(all_loop_seen, "PC traversed the firmware main loop (30..33)");

        // ---- 7. firmware effects on the peripherals ---------------------
        $display("-- 7. peripheral effects --");
        check(dut.u_gpio0.dir_reg == 16'h003F, "GPIO direction programmed by firmware");
        check(dut.u_pwm0.period_reg == 16'd1250, "PWM period programmed by firmware");
        check(dut.u_pwm0.duty_reg == 16'd625, "PWM duty programmed by firmware");
        check(dut.u_pwm0.ctrl_reg[0] == 1'b1, "PWM enabled by firmware");
        check(dut.led == ~4'b0001, "status LED 0 driven by the firmware");
        check(dut.motor_dir1 == 1'b1, "motor direction 1 set by the firmware");

        $display("== %0d checks, %0d failures ==", checks, errors);
        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL");
        $finish;
    end

    initial begin
        #5_000_000;
        $display("RESULT: FAIL (timeout)");
        $finish;
    end

endmodule
