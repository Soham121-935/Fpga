// SV-16 Rev B — Interrupt Controller
// Module: sv16_irq_ctrl
//
// Aggregates the eight peripheral interrupt lines into the CPU interrupt
// request (irq_req/irq_index). Sources are fixed priority, index 0 is the
// highest (timer, UART RX, UART TX, SPI, flash, GPIO, WDT, TRAP).
//
// Pending bits are edge-latched on the rising edge of the peripheral line and
// cleared by the CPU acknowledging the interrupt (irq_ack) or by writing 1 to
// the corresponding IRQ_PEND bit. The handler must clear the peripheral's own
// flag as well, exactly like a classic MCU interrupt flag scheme.
//
// Register map (BLK_IRQ = 0xF090):
//   0x0 IRQ_EN   (RW)   per-source interrupt enable
//   0x1 IRQ_PEND (RW1C) latched pending requests
//   0x2 IRQ_ACT  (RO)   live peripheral interrupt lines
//   0x3 IRQ_PRIO (RO)   index of the highest priority pending+enabled source
//
// Rev B: new module (ADR-016).

`timescale 1ns / 1ps

import sv16_pkg::*;

module sv16_irq_ctrl (
    input  logic       clk,
    input  logic       rst_n,

    input  logic [3:0] addr,
    input  logic [15:0]wdata,
    output logic [15:0]rdata,
    input  logic       req,
    input  logic       we,
    output logic       ack,

    input  logic [IRQ_SOURCES-1:0] irq_lines,   // level sensitive
    input  logic       global_en,               // SYS_CTRL.IRQEN

    output logic       irq_req,
    output logic [2:0] irq_index,
    input  logic       irq_ack
);


    logic [IRQ_SOURCES-1:0] en_reg;
    logic [IRQ_SOURCES-1:0] pend_reg;
    logic [IRQ_SOURCES-1:0] line_q;
    logic [IRQ_SOURCES-1:0] active;
    logic [2:0]             prio_idx;
    logic                   prio_valid;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) ack <= 1'b0;
        else        ack <= req;
    end

    logic [IRQ_SOURCES-1:0] pend_mask;
    assign active     = irq_lines & en_reg;
    assign pend_mask  = pend_reg & en_reg;
    assign prio_valid = |pend_mask;

    // fixed priority encoder: lowest index wins
    always_comb begin
        prio_idx = 3'd0;
        for (int i = IRQ_SOURCES-1; i >= 0; i--) begin
            if (pend_mask[i]) prio_idx = 3'(i);
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            en_reg   <= {IRQ_SOURCES{1'b0}};
            pend_reg <= {IRQ_SOURCES{1'b0}};
            line_q   <= {IRQ_SOURCES{1'b0}};
        end else begin
            line_q <= irq_lines;

            // rising edge detect -> latch pending
            pend_reg <= pend_reg | (irq_lines & ~line_q) | (active & ~en_reg);

            if (req && we && (addr == 4'h0)) en_reg   <= wdata[IRQ_SOURCES-1:0];
            if (req && we && (addr == 4'h1)) pend_reg <= pend_reg & ~wdata[IRQ_SOURCES-1:0];
            if (irq_ack)                     pend_reg[prio_idx] <= 1'b0;
        end
    end

    assign irq_req   = prio_valid && global_en;
    assign irq_index = prio_idx;

    always_comb begin
        rdata = 16'h0000;
        case (addr)
            4'h0: rdata = {8'h00, en_reg};
            4'h1: rdata = {8'h00, pend_reg};
            4'h2: rdata = {8'h00, irq_lines};
            4'h3: rdata = {13'd0, prio_idx};
            default: rdata = 16'h0000;
        endcase
    end

endmodule : sv16_irq_ctrl
