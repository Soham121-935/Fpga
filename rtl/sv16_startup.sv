// SV-16 Rev B — Reset and Startup Sequencer
// Module: sv16_startup
//
// Owns everything that happens between power-on and the first instruction the
// application executes. This is what turns the design from "an FPGA that runs
// whatever is in BRAM" into an MCU that comes up running its stored firmware:
//
//   1. produces the asynchronous-assert / synchronous-release system reset
//   2. waits out the SPI flash power-up delay (tVSL)
//   3. runs the hardware boot engine and hands the CPU the validated entry
//      point and initial stack pointer
//   4. falls back to the boot ROM monitor when there is no valid image, the
//      flash is missing/blank, or the user holds the serial RX line low during
//      reset (a jumper/wired-AND escape hatch - no extra pin required)
//   5. supports soft reset (SYS_CTRL.SOFTRST) that restarts this sequence
//   6. restarts the sequence on a watchdog timeout, recording RSTCAUSE.WDT
//      (ADR-017)
//      without reconfiguring the FPGA, and keeps the peripherals/CPU in reset
//      until the CPU is released
//
// CPU reset domain: cpu_rst_n. The boot engine, flash controller and system
// control block are only reset by the external reset, so boot status and
// scratch registers survive a soft reset.
//
// Rev B: new module (ADR-014).

`timescale 1ns / 1ps

import sv16_pkg::*;

module sv16_startup #(
    parameter int BOOT_DELAY_CYCLES   = 32768,      // ~1.3 ms @25 MHz (tVSL)
    parameter int SOFT_RST_CYCLES     = 16,
    parameter int BOOT_TIMEOUT_CYCLES = 1 << 21,    // ~84 ms @25 MHz
    parameter int RX_HOLD_CYCLES      = 4096
)(
    input  logic        clk,            // 25 MHz system clock
    input  logic        ext_rst_n,      // raw external reset pin (active low)

    // Escape hatch: keep the serial RX line low during reset to force the
    // ROM monitor instead of booting the stored image.
    input  logic        uart_rx,

    // Boot engine handshake
    input  logic        auto_boot,      // BOOT_CTRL.AUTO
    input  logic        boot_busy,
    input  logic        boot_jump,      // pulse: image validated
    input  logic        boot_fail,      // level: boot engine gave up
    input  logic [15:0] boot_entry,
    input  logic [15:0] boot_stack,
    output logic        boot_go,        // pulse: start a boot attempt
    input  logic        soft_rst_req,   // pulse from SYS_CTRL
    input  logic        wdt_timeout,    // pulse from the watchdog (ADR-017)

    // Reset outputs
    output logic        rst_n,          // hard reset (whole device)
    output logic        cpu_rst_n,      // CPU + peripherals (soft resettable)

    // CPU release
    output logic        cpu_halt_req,   // hold the CPU until we are ready
    output logic        cpu_boot_load,  // pulse: load PC/SP for the CPU
    output logic [15:0] cpu_boot_vec,
    output logic [15:0] cpu_boot_sp,

    // Status
    output logic        rom_monitor,    // CPU was released into the monitor
    output logic [7:0]  rst_cause       // sticky reset-cause bits
);


    // ------------------------------------------------- Reset synchronizer
    logic rst_sync1, rst_sync2;

    always_ff @(posedge clk or negedge ext_rst_n) begin
        if (!ext_rst_n) begin
            rst_sync1 <= 1'b0;
            rst_sync2 <= 1'b0;
        end else begin
            rst_sync1 <= 1'b1;
            rst_sync2 <= rst_sync1;
        end
    end

    assign rst_n = rst_sync2;

    // ------------------------------------------------------------ Startup FSM
    typedef enum logic [2:0] {
        S_RESET   = 3'd0,   // hold everything in reset (delay / soft reset)
        S_BOOT    = 3'd1,   // start a boot attempt
        S_WAIT    = 3'd2,   // wait for the boot engine
        S_MONITOR = 3'd3,   // release the CPU into the ROM monitor
        S_IMAGE   = 3'd4,   // release the CPU at the image entry point
        S_RUN     = 3'd5    // CPU is running
    } sstate_e;

    sstate_e     sstate;
    logic [31:0] delay_cnt;
    logic [31:0] boot_tmo;
    logic [15:0] vec_lat, sp_lat;
    logic        first_boot;

    // Monitor escape hatch detector
    logic [12:0] rx_low_cnt;
    logic        force_monitor;
    logic        wdt_pend;         // a watchdog bite we have not acted on yet

    // A watchdog bite is latched rather than sampled: the pulse can arrive while
    // the sequencer is busy with a boot attempt, and a watchdog that is ignored
    // is worse than no watchdog at all.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wdt_pend <= 1'b0;
        end else if (wdt_timeout) begin
            wdt_pend <= 1'b1;
        end else if (sstate == S_RUN) begin
            wdt_pend <= 1'b0;      // acted on below
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_low_cnt    <= 13'd0;
            force_monitor <= 1'b0;
        end else if (sstate == S_RESET && first_boot) begin
            if (uart_rx == 1'b0) begin
                if (rx_low_cnt >= RX_HOLD_CYCLES[12:0]) force_monitor <= 1'b1;
                else                                    rx_low_cnt <= rx_low_cnt + 13'd1;
            end else begin
                rx_low_cnt <= 13'd0;
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sstate        <= S_RESET;
            delay_cnt     <= 32'd0;
            boot_tmo      <= 32'd0;
            cpu_rst_n     <= 1'b0;
            cpu_halt_req  <= 1'b1;
            cpu_boot_load <= 1'b0;
            cpu_boot_vec  <= ROM_BASE;
            cpu_boot_sp   <= BOOT_DEFAULT_SP;
            boot_go       <= 1'b0;
            rom_monitor   <= 1'b0;
            rst_cause     <= 8'h00;
            first_boot    <= 1'b1;
            vec_lat       <= 16'h0000;
            sp_lat        <= BOOT_DEFAULT_SP;
        end else begin
            cpu_boot_load <= 1'b0;
            boot_go       <= 1'b0;

            case (sstate)
                // ------------------------------------------- reset hold
                S_RESET: begin
                    cpu_rst_n    <= 1'b0;
                    cpu_halt_req <= 1'b1;
                    rom_monitor  <= 1'b0;

                    if (delay_cnt >= (first_boot ? BOOT_DELAY_CYCLES : SOFT_RST_CYCLES)) begin
                        cpu_rst_n <= 1'b1;
                        delay_cnt <= 32'd0;
                        boot_tmo  <= 32'd0;
                        sstate    <= S_BOOT;
                        if (!first_boot) begin
                            rst_cause[RSTCAUSE_SOFT_BIT] <= 1'b1;
                        end else begin
                            rst_cause[RSTCAUSE_POR_BIT]  <= 1'b1;
                        end
                    end else begin
                        delay_cnt <= delay_cnt + 32'd1;
                    end
                end

                // --------------------------------------- decide what to run
                S_BOOT: begin
                    first_boot <= 1'b0;
                    if (!auto_boot || force_monitor) begin
                        sstate <= S_MONITOR;
                    end else if (boot_busy) begin
                        // an attempt is already streaming (soft reset landed
                        // mid-load): let it finish rather than starting over
                        sstate <= S_WAIT;
                    end else begin
                        boot_go   <= 1'b1;
                        boot_tmo  <= 32'd0;
                        sstate    <= S_WAIT;
                    end
                end

                S_WAIT: begin
                    boot_tmo <= boot_tmo + 32'd1;

                    if (boot_jump) begin
                        vec_lat <= (boot_entry == 16'h0000) ? RAM_BASE : boot_entry;
                        sp_lat  <= boot_stack;
                        sstate  <= S_IMAGE;
                    end else if (boot_fail || (boot_tmo >= BOOT_TIMEOUT_CYCLES)) begin
                        rst_cause[RSTCAUSE_BOOTFAIL_BIT] <= 1'b1;
                        sstate <= S_MONITOR;
                    end
                end

                // ------------------------------- release the CPU into the ROM
                S_MONITOR: begin
                    rom_monitor   <= 1'b1;
                    cpu_halt_req  <= 1'b0;
                    cpu_boot_load <= 1'b1;
                    cpu_boot_vec  <= ROM_BASE;
                    cpu_boot_sp   <= BOOT_DEFAULT_SP;
                    sstate        <= S_RUN;
                end

                // ----------------------------- release the CPU into the image
                S_IMAGE: begin
                    rom_monitor   <= 1'b0;
                    cpu_halt_req  <= 1'b0;
                    cpu_boot_load <= 1'b1;
                    cpu_boot_vec  <= vec_lat;
                    cpu_boot_sp   <= sp_lat;
                    rst_cause[RSTCAUSE_FLASHOK_BIT] <= 1'b1;
                    sstate        <= S_RUN;
                end

                // ---------------------------------------------------- running
                S_RUN: begin
                    if (wdt_pend) begin
                        // the watchdog bit is sticky, and the WDT itself keeps
                        // running across this restart (it is only cleared by the
                        // external reset pin), so a program that hangs again is
                        // restarted again
                        delay_cnt  <= 32'd0;
                        rst_cause[RSTCAUSE_WDT_BIT] <= 1'b1;
                        sstate     <= S_RESET;
                    end else if (soft_rst_req) begin
                        delay_cnt  <= 32'd0;
                        rst_cause[RSTCAUSE_SOFT_BIT] <= 1'b1;
                        sstate     <= S_RESET;
                    end
                end

                default: sstate <= S_RESET;
            endcase
        end
    end

endmodule : sv16_startup
