// SV-16 Rev A — Synthesizable On-Chip Synchronous RAM (BRAM)
// Module: sv16_ram
//
// Target: Lattice ECP5 sysMEM DP16KD block RAM primitive inferrable
// Parameterized depth: Defaults to 4096 words (8 KB) or 8192 words (16 KB)
// Supports optional hexadecimal memory file initialization via $readmemh

`timescale 1ns / 1ps

module sv16_ram #(
    parameter int DEPTH      = 4096,        // 4K words (8 KB)
    parameter int ADDR_WIDTH = 12,          // 2^12 = 4096
    parameter     INIT_FILE  = ""           // Path to initial firmware hex
)(
    input  logic                  clk,
    input  logic                  rst_n,

    // Bus Slave Interface
    input  logic [ADDR_WIDTH-1:0] addr,
    input  logic [15:0]           wdata,
    output logic [15:0]           rdata,
    input  logic                  we,
    input  logic                  req,
    output logic                  ack
);

    // Memory array
    logic [15:0] mem [DEPTH-1:0];

    // Single-cycle acknowledge response
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ack <= 1'b0;
        end else begin
            ack <= req;
        end
    end

    // Synchronous Read and Write
    always_ff @(posedge clk) begin
        if (req) begin
            if (we) begin
                mem[addr] <= wdata;
            end
            rdata <= mem[addr];
        end
    end

    // Optional Hex initialization
    initial begin
        if (INIT_FILE != "") begin
            $readmemh(INIT_FILE, mem);
        end
    end

endmodule : sv16_ram
