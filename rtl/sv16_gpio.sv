// SV-16 Rev A — 16-Bit General Purpose I/O Controller
// Module: sv16_gpio
//
// Register Map (Base: 0xF010):
//   Offset 0 (0xF010): GPIO_DATA — Read: synchronized pin inputs; Write: output data latch
//   Offset 1 (0xF011): GPIO_DIR  — Direction: 1 = Output, 0 = Input (Hi-Z)
//   Offset 2 (0xF012): GPIO_SET  — Atomic pin set (writing 1 sets corresponding pin high)
//   Offset 3 (0xF013): GPIO_CLR  — Atomic pin clear (writing 1 clears corresponding pin low)
//
// External Interfaces:
//   gpio_in  : Input pins from FPGA I/O pads (with 2-stage synchronizer)
//   gpio_out : Output pins driving FPGA output buffers
//   gpio_oen : Output enable control (1 = drive output, 0 = high-Z)

`timescale 1ns / 1ps

module sv16_gpio (
    input  logic        clk,
    input  logic        rst_n,

    // Bus Slave Interface
    input  logic [3:0]  addr,
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    input  logic        req,
    input  logic        we,
    output logic        ack,

    // Physical Pin Interfaces
    input  logic [15:0] gpio_in,
    output logic [15:0] gpio_out,
    output logic [15:0] gpio_oen
);

    logic [15:0] data_out_reg;
    logic [15:0] dir_reg;

    // 2-stage input synchronizer to prevent metastability
    logic [15:0] sync_stage1;
    logic [15:0] sync_stage2;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sync_stage1 <= 16'h0000;
            sync_stage2 <= 16'h0000;
        end else begin
            sync_stage1 <= gpio_in;
            sync_stage2 <= sync_stage1;
        end
    end

    // Single-cycle bus acknowledge
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ack <= 1'b0;
        end else begin
            ack <= req;
        end
    end

    // Register Write Logic
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            data_out_reg <= 16'h0000;
            dir_reg      <= 16'h0000; // All inputs by default on reset
        end else if (req && we) begin
            case (addr[1:0])
                2'b00: data_out_reg <= wdata;                    // GPIO_DATA
                2'b01: dir_reg      <= wdata;                    // GPIO_DIR
                2'b10: data_out_reg <= data_out_reg | wdata;     // GPIO_SET (atomic)
                2'b11: data_out_reg <= data_out_reg & ~wdata;    // GPIO_CLR (atomic)
            endcase
        end
    end

    // Register Read Logic
    always_comb begin
        case (addr[1:0])
            2'b00: rdata = (sync_stage2 & ~dir_reg) | (data_out_reg & dir_reg); // Read pins
            2'b01: rdata = dir_reg;                                              // Read direction
            default: rdata = 16'h0000;
        endcase
    end

    // Connect to external pad drivers
    assign gpio_out = data_out_reg;
    assign gpio_oen = dir_reg;

endmodule : sv16_gpio
