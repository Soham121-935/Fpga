// SV-16 Rev B — System Control Block
// Module: sv16_sys
//
// The "system" peripheral of the MCU (BLK_SYS = 0xF000). It owns device
// identification, reset causes, debug/single-step control, the CPU debug
// window (PC/SP/SR/IR), fault reporting and scratch registers that survive a
// soft reset (used by the ROM monitor / bootloader to hand parameters to the
// application).
//
// Register map:
//   0x0 SYS_ID       (RO) 0x1602 = SV-16 Rev B
//   0x1 SYS_CTRL     (RW) [0] SOFTRST (needs key 0xA5 in [15:8], restarts boot)
//                         [1] HALT    (halt the CPU, debug)
//                         [2] STEP    (single step while halted, self clearing)
//                         [3] IRQEN   (0 = inhibit all interrupts)
//   0x2 SYS_STAT     (RO) [0] HALTED [1] STEP_TAKEN [2] BOOT_IMAGE
//                        [8] PLL_LOCKED [9] CLK_SRC_PLL  (ADR-021)
//                         [3] BOOT_FAIL [4] ROM_MONITOR [5] FLASH_OK
//                         [6] FAULT_HALT [7] ILLEGAL_SEEN
//   0x3 SYS_RSTCAUSE (RW1C) [0] POR [1] SOFT [2] CPU fault [3] watchdog
//                         [4] boot failed -> monitor [5] image booted
//   0x4 SYS_DBG_PC   (RW)  write while halted to set the PC
//   0x5 SYS_DBG_SP   (RW)  write while halted to set the stack pointer
//   0x6 SYS_DBG_SR   (RW)  write while halted to set the status register
//   0x7 SYS_DBG_IR   (RO)  last fetched instruction
//   0x8 SYS_FAULT_ADDR (RO) PC of the last illegal instruction
//   0x9 SYS_FAULT_CNT  (RW) trap counter (write anything to clear)
//   0xA SYS_TICKS_LO (RO)  free running 25 MHz cycle counter [15:0]
//   0xB SYS_TICKS_HI (RO)  ... [31:16]
//   0xC SYS_CPU_STATE(RO)  {10'b0, core_state[4:0], halted}
//   0xD SYS_MEMCFG   (RO)  [3:0] log2(RAM words) [7:4] log2(ROM words)
//   0xE SYS_SCRATCH0 (RW)  retained across soft reset
//   0xF SYS_SCRATCH1 (RW)  retained across soft reset
//
// Rev B: new module (ADR-014).

`timescale 1ns / 1ps

import sv16_pkg::*;

module sv16_sys (
    input  logic        clk,
    input  logic        rst_n,          // hard reset only (survives soft reset)

    // Bus slave interface
    input  logic [3:0]  addr,
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    input  logic        req,
    input  logic        we,
    output logic        ack,

    // Control outputs
    output logic        soft_rst_req,   // pulse: restart the boot sequence
    output logic        cpu_halt,       // debug halt request
    output logic        cpu_step,       // single step pulse
    output logic        irq_global_en,  // global interrupt enable

    // CPU debug window
    output logic        dbg_pc_wr,
    output logic [15:0] dbg_pc_val,
    output logic        dbg_sp_wr,
    output logic [15:0] dbg_sp_val,
    output logic        dbg_sr_wr,
    output logic [15:0] dbg_sr_val,
    input  logic [15:0] core_pc,
    input  logic [15:0] core_sp,
    input  logic [15:0] core_sr,
    input  logic [15:0] core_ir,
    input  logic [4:0]  core_state,
    input  logic        core_halted,
    input  logic        step_taken,
    input  logic        fault_halt,
    input  logic        illegal_irq,
    input  logic [15:0] illegal_pc,

    // Clock / startup status inputs
    input  logic        pll_locked,     // clock source is up (PLL lock, or no PLL)
    input  logic        clk_src_pll,    // 1 = the system clock comes from the PLL

    // Startup / boot status inputs
    input  logic        img_ok,         // boot engine loaded a valid image
    input  logic        boot_fail,      // boot engine rejected the image
    input  logic        rom_monitor,    // running from the boot ROM
    input  logic        flash_ok,       // flash responded to RDID
    input  logic [7:0]  rst_cause_in    // sticky reset-cause bits from startup
);


    localparam logic [15:0] SOFT_KEY = 16'hA500;

    logic [15:0] ctrl_reg;
    logic [15:0] scratch0, scratch1;
    logic [15:0] fault_cnt;
    logic [15:0] fault_addr;
    logic [31:0] ticks;
    logic [7:0]  rst_cause;

    logic illegal_seen;
    logic boot_fail_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) ack <= 1'b0;
        else        ack <= req;
    end

    // Control strobes are registered so that a bus write never creates a
    // combinational path from the peripheral back into the CPU's control unit
    // (which would be both a timing hazard and a simulation race).
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            soft_rst_req <= 1'b0;
            cpu_step     <= 1'b0;
            dbg_pc_wr    <= 1'b0;
            dbg_sp_wr    <= 1'b0;
            dbg_sr_wr    <= 1'b0;
            dbg_pc_val   <= 16'h0000;
            dbg_sp_val   <= 16'h0000;
            dbg_sr_val   <= 16'h0000;
        end else begin
            soft_rst_req <= req && we && (addr == SYS_CTRL) &&
                            (wdata[15:8] == SOFT_KEY[15:8]) &&
                            wdata[SYS_CTRL_SOFTRST_BIT];
            cpu_step     <= req && we && (addr == SYS_CTRL) && wdata[SYS_CTRL_STEP_BIT];
            dbg_pc_wr    <= req && we && (addr == SYS_DBG_PC);
            dbg_sp_wr    <= req && we && (addr == SYS_DBG_SP);
            dbg_sr_wr    <= req && we && (addr == SYS_DBG_SR);
            if (req && we && (addr == SYS_DBG_PC)) dbg_pc_val <= wdata;
            if (req && we && (addr == SYS_DBG_SP)) dbg_sp_val <= wdata;
            if (req && we && (addr == SYS_DBG_SR)) dbg_sr_val <= wdata;
        end
    end

    // ------------------------------------------------------- Free-running tick
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) ticks <= 32'h0000_0000;
        else        ticks <= ticks + 32'd1;
    end

    // ------------------------------------------------------------ Registers
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ctrl_reg    <= 16'h0008;      // IRQEN set by default
            scratch0    <= 16'h0000;
            scratch1    <= 16'h0000;
            fault_cnt   <= 16'h0000;
            fault_addr  <= 16'h0000;
            illegal_seen<= 1'b0;
            boot_fail_q <= 1'b0;
            rst_cause   <= 8'h00;
        end else begin
            // soft reset request is a pulse derived from the write itself
            if (req && we) begin
                case (addr)
                    SYS_CTRL: begin
                        if (wdata[15:8] == SOFT_KEY[15:8]) begin
                            ctrl_reg <= {wdata[15:4], wdata[3:0]};
                        end else begin
                            // unkeyed writes may only change HALT / STEP / IRQEN
                            ctrl_reg <= {ctrl_reg[15:4], wdata[3:0]};
                        end
                    end
                    SYS_RSTCAUSE: rst_cause <= rst_cause & ~wdata[7:0];
                    SYS_FAULT_CNT:fault_cnt <= 16'h0000;
                    SYS_SCRATCH0: scratch0  <= wdata;
                    SYS_SCRATCH1: scratch1  <= wdata;
                    default: ;
                endcase
            end

            rst_cause <= rst_cause | rst_cause_in;

            if (illegal_irq) begin
                fault_cnt    <= fault_cnt + 16'd1;
                fault_addr   <= illegal_pc;
                illegal_seen <= 1'b1;
            end

            if (boot_fail) boot_fail_q <= 1'b1;
        end
    end

    assign cpu_halt     = ctrl_reg[SYS_CTRL_HALT_BIT];
    assign irq_global_en= ctrl_reg[SYS_CTRL_IRQEN_BIT];

    // ------------------------------------------------------------- Readback
    always_comb begin
        rdata = 16'h0000;
        case (addr)
            SYS_ID:        rdata = SV16_ID;
            SYS_CTRL:      rdata = ctrl_reg;
            SYS_STAT:      rdata = {6'h00, clk_src_pll, pll_locked,
                                    illegal_seen, fault_halt, flash_ok,
                                    rom_monitor, boot_fail_q, img_ok,
                                    step_taken, core_halted};
            SYS_RSTCAUSE:  rdata = {8'h00, rst_cause};
            SYS_DBG_PC:    rdata = core_pc;
            SYS_DBG_SP:    rdata = core_sp;
            SYS_DBG_SR:    rdata = core_sr;
            SYS_DBG_IR:    rdata = core_ir;
            SYS_FAULT_ADDR:rdata = fault_addr;
            SYS_FAULT_CNT: rdata = fault_cnt;
            SYS_TICKS_LO:  rdata = ticks[15:0];
            SYS_TICKS_HI:  rdata = ticks[31:16];
            SYS_CPU_STATE: rdata = {10'b0, core_state, core_halted};
            SYS_MEMCFG:    rdata = {8'h00, 4'(RAM_ADDR_W), 4'(ROM_ADDR_W)};
            SYS_SCRATCH0:  rdata = scratch0;
            SYS_SCRATCH1:  rdata = scratch1;
            default:       rdata = 16'h0000;
        endcase
    end

endmodule : sv16_sys
