// SV-16 Rev A — 8 x 16-Bit General Purpose Register File
// Module: sv16_regfile
//
// Features:
// - 8 registers (R0 through R7), each 16 bits wide
// - 2 independent asynchronous read ports (rdata1, rdata2)
// - 1 synchronous write port (wdata) with active-high write enable (wen)
// - Synchronous/Asynchronous active-low reset to clear all registers to 0x0000

`timescale 1ns / 1ps

module sv16_regfile (
    input  logic        clk,
    input  logic        rst_n,

    // Read Port 1
    input  logic [2:0]  raddr1,
    output logic [15:0] rdata1,

    // Read Port 2
    input  logic [2:0]  raddr2,
    output logic [15:0] rdata2,

    // Write Port
    input  logic        wen,
    input  logic [2:0]  waddr,
    input  logic [15:0] wdata
);

    // 8 x 16-bit register storage
    logic [15:0] registers [7:0];

    // Read ports (combinational / asynchronous read)
    assign rdata1 = registers[raddr1];
    assign rdata2 = registers[raddr2];

    // Synchronous write port with active-low reset
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (int i = 0; i < 8; i++) begin
                registers[i] <= 16'h0000;
            end
        end else if (wen) begin
            registers[waddr] <= wdata;
        end
    end

endmodule : sv16_regfile
