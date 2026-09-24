// SV-16 Rev B — MCU Top Level
// Module: sv16_top
//
// Target: Lattice ECP5 LFE5U-12F-6TG144C (TQFP-144)
//
// This is the complete microcontroller: CPU, SRAM, boot ROM, bus fabric,
// SPI flash controller with hardware boot engine, UART with RX/TX FIFOs,
// two GPIO ports, timer, PWM/motor interface, SPI master and interrupt
// controller, plus reset/startup sequencing.
//
// What happens at power-on (see docs/RESET_AND_CLOCK.md):
//   1. external reset releases, the reset synchronizer deasserts rst_n
//   2. sv16_startup holds the CPU in reset, waits for the flash power-up
//      delay and - unless the serial RX pin is held low - runs the hardware
//      boot engine
//   3. the boot engine streams the firmware image from SPI flash into SRAM,
//      verifies magic + header CRC + payload CRC and releases the CPU at the
//      image entry point with the image's stack pointer
//   4. if there is no valid image (blank/missing flash, CRC failure, timeout)
//      the CPU is released at the boot ROM monitor instead, which speaks a
//      simple ASCII protocol over the UART and can read/erase/program the
//      flash (field firmware update) or load and run code from RAM
//
// Optional build defines:
//   SV16_RAM_INIT_FILE  preload SRAM from a hex file (patch-in firmware for
//                       flashless bring-up / simulation)
//   SV16_ROM_INIT_FILE  boot ROM contents (normally build/rom/monitor.hex)
//
// Rev B: rewritten (ADR-014).

`timescale 1ns / 1ps

`ifndef SV16_RAM_INIT_FILE
  `define SV16_RAM_INIT_FILE ""
`endif
`ifndef SV16_ROM_INIT_FILE
  `define SV16_ROM_INIT_FILE ""
`endif
// System clock divider: the board oscillator (clk_25m) divided by this value
// feeds the whole SoC.  The default of 1 means "run at the oscillator
// frequency"; `make bitstream CLKDIV=2` builds the 12.5 MHz configuration,
// which is the one that closes timing on an LFE5U-12F-6 (see
// docs/SYNTHESIS_AND_DEPLOYMENT.md).  Firmware is clock-rate agnostic: the
// UART divisor is derived from the same number.
`ifndef SV16_CLKDIV
  `define SV16_CLKDIV 1
`endif

import sv16_pkg::*;

module sv16_top (
    input  logic        clk_25m,        // 25 MHz board oscillator
    input  logic        ext_rst_n,      // active low external reset

    // UART0 (firmware upload / monitor console)
    input  logic        uart_rx,
    output logic        uart_tx,

    // SPI flash: persistent program store
    output logic        flash_sck,
    output logic        flash_cs_n,
    output logic        flash_mosi,
    input  logic        flash_miso,

    // SPI0 expansion bus
    output logic        spi0_sck,
    output logic        spi0_cs_n,
    output logic        spi0_mosi,
    input  logic        spi0_miso,

    // GPIO port A (16-bit, bit 3:0 also drive the status LEDs)
    inout  wire  [15:0] gpio_a,
    // GPIO port B (16-bit, general purpose expansion)
    inout  wire  [15:0] gpio_b,

    // PWM / motor interface
    output logic        pwm_out,
    output logic        motor_dir1,
    output logic        motor_dir2,
    input  logic        motor_fault_n,

    // Status LEDs (active low, mirror GPIOA[3:0])
    output logic [3:0]  led
);


    // ------------------------------------------------------------------ clock
    // Rev B: the SoC clock is the board oscillator divided by CLK_DIV.  At the
    // default (1) this is a straight wire; at 2 the design runs at 12.5 MHz,
    // which is the configuration that meets timing on this device/speed grade.
    localparam int CLK_DIV  = `SV16_CLKDIV;   // 1 = 25 MHz, 2 = 12.5 MHz, ...
    localparam int CLK_HZ   = 25_000_000 / CLK_DIV;      // system clock, Hz
    localparam int BAUD_HZ  = 115_200;                   // fixed console rate
    // rounded divisor so the console stays at 115200 for any divider
    localparam int UART_BAUD_DIV = (CLK_HZ + BAUD_HZ / 2) / BAUD_HZ;

    logic              clk;
    logic [15:0]       div_cnt;
    localparam logic [15:0] CLK_DIV_W = CLK_DIV[15:0];
    localparam logic [15:0] DIV_HALF  = CLK_DIV_W >> 1;

    always_ff @(posedge clk_25m or negedge ext_rst_n) begin
        if (!ext_rst_n) begin
            div_cnt <= 16'd0;
        end else if (div_cnt == CLK_DIV_W - 16'd1) begin
            div_cnt <= 16'd0;
        end else begin
            div_cnt <= div_cnt + 16'd1;
        end
    end

    // 50 % duty cycle; a straight wire when the divider is 1 (the counter is
    // constant-folded away in that configuration)
    assign clk = (CLK_DIV <= 1) ? clk_25m : (div_cnt < DIV_HALF);

    // ------------------------------------------------- reset / startup state
    logic        rst_n;             // hard reset (whole device)
    logic        cpu_rst_n;         // CPU + peripherals (soft resettable)
    logic        cpu_halt_req, cpu_boot_load, rom_monitor;
    logic [15:0] cpu_boot_vec, cpu_boot_sp;
    logic [7:0]  rst_cause;
    logic        boot_go, boot_done, boot_busy, boot_jump, boot_auto, boot_failed;
    logic        boot_ready, boot_failed_p, boot_ok;
    logic [15:0] boot_entry, boot_stack;
    logic        soft_rst_req;
    logic        img_ok;

    // ------------------------------------------------------------ CPU signals
    logic [15:0] cpu_bus_addr, cpu_bus_wdata, cpu_bus_rdata;
    logic        cpu_bus_req, cpu_bus_we, cpu_bus_ack;
    logic [15:0] dbg_pc, dbg_ir, dbg_sr, dbg_sp;
    logic [4:0]  dbg_state;
    logic        cpu_halted, cpu_step_taken, cpu_fault_halt, cpu_illegal_irq;
    logic [15:0] cpu_illegal_pc;
    logic        cpu_irq_ack;

    // --------------------------------------------------------- System control
    logic        sys_halt, sys_step, dbg_pc_wr, dbg_sp_wr, dbg_sr_wr;
    logic [15:0] dbg_pc_val, dbg_sp_val, dbg_sr_val;
    logic        irq_global_en;

    // ------------------------------------------------------------- Bus fabric
    logic [13:0] ram_addr;
    logic [15:0] ram_wdata, ram_rdata;
    logic        ram_we, ram_req, ram_ack;
    logic [10:0] rom_addr;
    logic [15:0] rom_rdata;
    logic        rom_req, rom_ack;
    logic [3:0]  mmio_blk, mmio_reg;
    logic [15:0] mmio_wdata, mmio_req, mmio_ack;
    logic        mmio_we, unmapped_access;

    // ---------------------------------------------------------- Boot engine
    logic        boot_m_req, boot_m_we, boot_m_ack;
    logic [15:0] boot_m_addr, boot_m_wdata, boot_m_rdata;
    logic        f_start, f_valid, f_ack, f_abort, f_busy;
    logic [23:0] f_addr;
    logic [15:0] f_len;
    logic [7:0]  f_data;

    // ------------------------------------------------------------ Peripherals
    logic [15:0] rd_sys, rd_gpio0, rd_timer0, rd_pwm0, rd_uart0;
    logic [15:0] rd_spi0, rd_flash, rd_gpio1, rd_wdt, rd_irq, rd_boot;
    logic        ack_sys, ack_gpio0, ack_timer0, ack_pwm0, ack_uart0;
    logic        ack_spi0, ack_flash, ack_gpio1, ack_wdt, ack_irq, ack_boot;

    // GPIO pads
    logic [15:0] gpio_a_in, gpio_a_out, gpio_a_oen;
    logic [15:0] gpio_b_in, gpio_b_out, gpio_b_oen;

    // Interrupt lines
    logic        timer0_irq, uart0_rx_irq, uart0_tx_irq, spi0_irq, flash_irq;
    logic        wdt_irq, wdt_timeout;
    logic        irq_req;
    logic [2:0]  irq_index;
    logic [7:0]  irq_lines_ext;

    // Flash identity
    logic        flash_id_ok;
    logic [23:0] flash_jedec_id;

    // ------------------------------------------------------------ Startup
    sv16_startup u_startup (
        .clk(clk),
        .ext_rst_n(ext_rst_n),
        .uart_rx(uart_rx),
        .auto_boot(boot_auto),
        .boot_busy(boot_busy),
        .boot_jump(boot_jump),
        .boot_fail(boot_failed),
        .boot_entry(boot_entry),
        .boot_stack(boot_stack),
        .boot_go(boot_go),
        .soft_rst_req(soft_rst_req),
        .wdt_timeout(wdt_timeout),
        .rst_n(rst_n),
        .cpu_rst_n(cpu_rst_n),
        .cpu_halt_req(cpu_halt_req),
        .cpu_boot_load(cpu_boot_load),
        .cpu_boot_vec(cpu_boot_vec),
        .cpu_boot_sp(cpu_boot_sp),
        .rom_monitor(rom_monitor),
        .rst_cause(rst_cause)
    );

    // ------------------------------------------------------------ CPU core
    sv16_core u_cpu (
        .clk(clk),
        .rst_n(cpu_rst_n),
        .bus_addr(cpu_bus_addr),
        .bus_wdata(cpu_bus_wdata),
        .bus_rdata(cpu_bus_rdata),
        .bus_req(cpu_bus_req),
        .bus_we(cpu_bus_we),
        .bus_ack(cpu_bus_ack),
        .irq_req(irq_req),
        .irq_index(irq_index),
        .irq_vec_base(IRQ_VEC_BASE),
        .irq_ack(cpu_irq_ack),
        .halt_req(cpu_halt_req | sys_halt),
        .step_en(sys_step),
        .boot_load(cpu_boot_load),
        .boot_vec(cpu_boot_vec),
        .boot_sp(cpu_boot_sp),
        .halted(cpu_halted),
        .step_taken(cpu_step_taken),
        .fault_halt(cpu_fault_halt),
        .illegal_irq(cpu_illegal_irq),
        .illegal_pc(cpu_illegal_pc),
        .dbg_pc_wr(dbg_pc_wr),
        .dbg_pc_val(dbg_pc_val),
        .dbg_sp_wr(dbg_sp_wr),
        .dbg_sp_val(dbg_sp_val),
        .dbg_sr_wr(dbg_sr_wr),
        .dbg_sr_val(dbg_sr_val),
        .dbg_pc(dbg_pc),
        .dbg_ir(dbg_ir),
        .dbg_sr(dbg_sr),
        .dbg_sp(dbg_sp),
        .dbg_state(dbg_state)
    );

    // ------------------------------------------------------- System control
    sv16_sys u_sys (
        .clk(clk), .rst_n(rst_n),
        .addr(mmio_reg), .wdata(mmio_wdata), .rdata(rd_sys),
        .req(mmio_req[BLK_SYS]), .we(mmio_we), .ack(ack_sys),
        .soft_rst_req(soft_rst_req),
        .cpu_halt(sys_halt),
        .cpu_step(sys_step),
        .irq_global_en(irq_global_en),
        .dbg_pc_wr(dbg_pc_wr), .dbg_pc_val(dbg_pc_val),
        .dbg_sp_wr(dbg_sp_wr), .dbg_sp_val(dbg_sp_val),
        .dbg_sr_wr(dbg_sr_wr), .dbg_sr_val(dbg_sr_val),
        .core_pc(dbg_pc), .core_sp(dbg_sp), .core_sr(dbg_sr), .core_ir(dbg_ir),
        .core_state(dbg_state),
        .core_halted(cpu_halted),
        .step_taken(cpu_step_taken),
        .fault_halt(cpu_fault_halt),
        .illegal_irq(cpu_illegal_irq),
        .illegal_pc(cpu_illegal_pc),
        .img_ok(img_ok),
        .boot_fail(boot_failed),
        .rom_monitor(rom_monitor),
        .flash_ok(flash_id_ok),
        .rst_cause_in(rst_cause)
    );

    // ------------------------------------------------------- SRAM and ROM
    sv16_ram #(
        .DEPTH(RAM_WORDS),
        .ADDR_WIDTH(RAM_ADDR_W),
        .INIT_FILE(`SV16_RAM_INIT_FILE)
    ) u_ram (
        .clk(clk), .rst_n(rst_n),
        .addr(ram_addr), .wdata(ram_wdata), .rdata(ram_rdata),
        .we(ram_we), .req(ram_req), .ack(ram_ack)
    );

    sv16_rom #(
        .DEPTH(ROM_WORDS),
        .ADDR_WIDTH(ROM_ADDR_W),
        .INIT_FILE(`SV16_ROM_INIT_FILE)
    ) u_rom (
        .clk(clk), .rst_n(rst_n),
        .addr(rom_addr), .rdata(rom_rdata),
        .req(rom_req), .ack(rom_ack)
    );

    // ------------------------------------------------------ Bus interconnect
    // block index: 0 SYS, 1 GPIO0, 2 TIMER0, 3 PWM0, 4 UART0, 5 SPI0,
    //              6 FLASH, 7 GPIO1, 8 WDT, 9 IRQ, 10 BOOT
    //
    // MMIO_PRESENT gates both the read mux and the ack: a block that is
    // marked absent is answered by the interconnect's unmapped-access
    // handler instead of the peripheral.  It must match the ack OR below
    // exactly.
    assign mmio_ack = {5'b0,
                       ack_boot,      // 0xA
                       ack_irq,       // 0x9
                       ack_wdt,       // 0x8
                       ack_gpio1,     // 0x7
                       ack_flash,     // 0x6
                       ack_spi0,      // 0x5
                       ack_uart0,     // 0x4
                       ack_pwm0,      // 0x3
                       ack_timer0,    // 0x2
                       ack_gpio0,     // 0x1
                       ack_sys};      // 0x0

    localparam logic [15:0] MMIO_PRESENT = 16'b0000_0111_1111_1111;  // 0x7FF

    sv16_bus_interconnect u_bus (
        .clk(clk), .rst_n(rst_n),
        .cpu_addr(cpu_bus_addr), .cpu_wdata(cpu_bus_wdata),
        .cpu_req(cpu_bus_req), .cpu_we(cpu_bus_we),
        .cpu_rdata(cpu_bus_rdata), .cpu_ack(cpu_bus_ack),
        .boot_addr(boot_m_addr), .boot_wdata(boot_m_wdata),
        .boot_req(boot_m_req), .boot_we(boot_m_we),
        .boot_rdata(boot_m_rdata), .boot_ack(boot_m_ack),
        .boot_master(boot_busy),
        .ram_addr(ram_addr), .ram_wdata(ram_wdata),
        .ram_we(ram_we), .ram_req(ram_req),
        .ram_rdata(ram_rdata), .ram_ack(ram_ack),
        .rom_addr(rom_addr), .rom_req(rom_req),
        .rom_rdata(rom_rdata), .rom_ack(rom_ack),
        .mmio_blk(mmio_blk), .mmio_reg(mmio_reg),
        .mmio_wdata(mmio_wdata), .mmio_we(mmio_we),
        .mmio_req(mmio_req), .mmio_present(MMIO_PRESENT), .mmio_ack(mmio_ack),
        .rd_sys(rd_sys), .rd_gpio0(rd_gpio0), .rd_timer0(rd_timer0),
        .rd_pwm0(rd_pwm0), .rd_uart0(rd_uart0), .rd_spi0(rd_spi0),
        .rd_flash(rd_flash), .rd_gpio1(rd_gpio1), .rd_wdt(rd_wdt),
        .rd_irq(rd_irq), .rd_boot(rd_boot),
        .unmapped_access(unmapped_access)
    );

    // ------------------------------------------------------------ GPIO ports
    sv16_gpio u_gpio0 (
        .clk(clk), .rst_n(cpu_rst_n),
        .addr(mmio_reg), .wdata(mmio_wdata), .rdata(rd_gpio0),
        .req(mmio_req[BLK_GPIO0]), .we(mmio_we), .ack(ack_gpio0),
        .gpio_in(gpio_a_in), .gpio_out(gpio_a_out), .gpio_oen(gpio_a_oen)
    );

    sv16_gpio u_gpio1 (
        .clk(clk), .rst_n(cpu_rst_n),
        .addr(mmio_reg), .wdata(mmio_wdata), .rdata(rd_gpio1),
        .req(mmio_req[BLK_GPIO1]), .we(mmio_we), .ack(ack_gpio1),
        .gpio_in(gpio_b_in), .gpio_out(gpio_b_out), .gpio_oen(gpio_b_oen)
    );

    genvar gi;
    generate
        for (gi = 0; gi < 16; gi++) begin : g_gpio_pads
            assign gpio_a[gi]    = gpio_a_oen[gi] ? gpio_a_out[gi] : 1'bz;
            assign gpio_a_in[gi] = gpio_a[gi];
            assign gpio_b[gi]    = gpio_b_oen[gi] ? gpio_b_out[gi] : 1'bz;
            assign gpio_b_in[gi] = gpio_b[gi];
        end
    endgenerate

    // Status LEDs mirror GPIOA[3:0] (active low)
    assign led          = ~gpio_a_out[3:0];
    assign motor_dir1   = gpio_a_out[4];
    assign motor_dir2   = gpio_a_out[5];

    // --------------------------------------------------------------- Timer 0
    sv16_timer u_timer0 (
        .clk(clk), .rst_n(cpu_rst_n),
        .addr(mmio_reg), .wdata(mmio_wdata), .rdata(rd_timer0),
        .req(mmio_req[BLK_TIMER0]), .we(mmio_we), .ack(ack_timer0),
        .timer_irq(timer0_irq)
    );

    // ----------------------------------------------------------------- PWM 0
    sv16_pwm u_pwm0 (
        .clk(clk), .rst_n(cpu_rst_n),
        .addr(mmio_reg), .wdata(mmio_wdata), .rdata(rd_pwm0),
        .req(mmio_req[BLK_PWM0]), .we(mmio_we), .ack(ack_pwm0),
        .motor_fault_n(motor_fault_n), .pwm_out(pwm_out)
    );

    // ---------------------------------------------------------------- UART 0
    sv16_uart #(
        .BAUD_DIV_RESET(UART_BAUD_DIV)
    ) u_uart0 (
        .clk(clk), .rst_n(cpu_rst_n),
        .addr(mmio_reg), .wdata(mmio_wdata), .rdata(rd_uart0),
        .req(mmio_req[BLK_UART0]), .we(mmio_we), .ack(ack_uart0),
        .uart_rx(uart_rx), .uart_tx(uart_tx),
        .uart_tx_irq(uart0_tx_irq), .uart_rx_irq(uart0_rx_irq)
    );

    // ----------------------------------------------------------- SPI0 (bus)
    sv16_spi u_spi0 (
        .clk(clk), .rst_n(cpu_rst_n),
        .addr(mmio_reg[2:0]), .wdata(mmio_wdata), .rdata(rd_spi0),
        .req(mmio_req[BLK_SPI0]), .we(mmio_we), .ack(ack_spi0),
        .spi_sck(spi0_sck), .spi_mosi(spi0_mosi), .spi_miso(spi0_miso),
        .spi_cs_n(spi0_cs_n), .spi_irq(spi0_irq)
    );

    // ------------------------------------------------- Flash controller (NVM)
    sv16_flash_ctrl u_flash (
        .clk(clk), .rst_n(rst_n),
        .addr(mmio_reg), .wdata(mmio_wdata), .rdata(rd_flash),
        .req(mmio_req[BLK_FLASH]), .we(mmio_we), .ack(ack_flash),
        .boot_start(f_start), .boot_addr(f_addr), .boot_len(f_len),
        .boot_valid(f_valid), .boot_data(f_data), .boot_ack(f_ack),
        .boot_abort(f_abort), .boot_busy(f_busy),
        .slot_wr_req(slot_wr_req), .slot_wr_addr(slot_wr_addr),
        .slot_wr_data(slot_wr_data), .slot_wr_done(slot_wr_done),
        .flash_sck(flash_sck), .flash_cs_n(flash_cs_n),
        .flash_mosi(flash_mosi), .flash_miso(flash_miso),
        .flash_irq(flash_irq), .id_ok(flash_id_ok), .jedec_id(flash_jedec_id)
    );

    // ------------------------------------------------- ADR-019 slot wires
    logic        slot_wr_req;
    logic [23:0] slot_wr_addr;
    logic [7:0]  slot_wr_data;
    logic [1:0]  slot_wr_done;

    // ---------------------------------------------------- Boot loader engine
    // The sequencer talks in pulses ("start a boot attempt", "this attempt
    // finished, and here is the verdict"); the loader talks in levels
    // ("boot_ok is high", "I am busy").  This glue is the whole adapter.
    assign boot_jump      = boot_done && img_ok;      // pulse: image validated
    assign boot_failed_p  = boot_done && !img_ok;     // pulse: attempt failed
    assign boot_failed    = boot_ready;               // level: no usable image

    sv16_boot u_boot (
        .clk(clk), .rst_n(rst_n),
        .addr(mmio_reg), .wdata(mmio_wdata), .rdata(rd_boot),
        .req(mmio_req[BLK_BOOT]), .we(mmio_we), .ack(ack_boot),
        .m_req(boot_m_req), .m_we(boot_m_we), .m_addr(boot_m_addr),
        .m_wdata(boot_m_wdata), .m_ack(boot_m_ack), .m_rdata(boot_m_rdata),
        .f_start(f_start), .f_addr(f_addr), .f_len(f_len),
        .f_valid(f_valid), .f_data(f_data), .f_ack(f_ack),
        .f_abort(f_abort), .f_busy(f_busy),
        .boot_start(boot_go),
        .boot_done(boot_done),
        .boot_ok(boot_ok),
        .boot_entry(boot_entry),
        .boot_stack(boot_stack),
        .auto_boot(boot_auto),
        .busy(boot_busy),
        // ADR-019: the loader maintains the A/B slot records itself
        .slot_wr_req(slot_wr_req),
        .slot_wr_addr(slot_wr_addr),
        .slot_wr_data(slot_wr_data),
        .slot_wr_done(slot_wr_done)
    );

    // `boot_ready` is a sticky, one-shot "this power-on has no image" flag:
    // the sequencer must never see it as a *fresh* failure on a later
    // attempt, and SYS_BOOT_FAIL must not flap while the monitor runs.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            boot_ready <= 1'b0;
        end else if (soft_rst_req) begin
            boot_ready <= 1'b0;
        end else if (boot_failed_p) begin
            boot_ready <= 1'b1;
        end
    end

    assign img_ok = boot_ok;

    // ------------------------------------------------- Interrupt controller
    assign irq_lines_ext = {1'b0,          // 7: TRAP (handled inside the CPU)
                            wdt_irq,       // 6: watchdog early warning
                            1'b0,          // 5: GPIO (no pin interrupts in Rev B)
                            flash_irq,     // 4: flash command complete
                            spi0_irq,      // 3: SPI0 byte received
                            uart0_tx_irq,  // 2: UART0 TX ready
                            uart0_rx_irq,  // 1: UART0 RX byte available
                            timer0_irq};   // 0: timer 0 match

    sv16_irq_ctrl u_irq (
        .clk(clk), .rst_n(cpu_rst_n),
        .addr(mmio_reg), .wdata(mmio_wdata), .rdata(rd_irq),
        .req(mmio_req[BLK_IRQ]), .we(mmio_we), .ack(ack_irq),
        .irq_lines(irq_lines_ext),
        .global_en(irq_global_en),
        .irq_req(irq_req),
        .irq_index(irq_index),
        .irq_ack(cpu_irq_ack)
    );

    // ------------------------------------------------------------- Watchdog
    // Reset by the external pin only (rst_n), never by cpu_rst_n: an
    // application must not be able to escape its own watchdog with a restart.
    // A bite pulses `wdt_timeout`, which the sequencer turns into a full
    // restart of the boot sequence plus RSTCAUSE.WDT (ADR-017).
    sv16_wdt u_wdt (
        .clk(clk), .rst_n(rst_n),
        .addr(mmio_reg), .wdata(mmio_wdata), .rdata(rd_wdt),
        .req(mmio_req[BLK_WDT]), .we(mmio_we), .ack(ack_wdt),
        .irq(wdt_irq),
        .timeout(wdt_timeout)
    );

endmodule : sv16_top
