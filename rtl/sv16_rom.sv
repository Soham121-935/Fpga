// SV-16 Rev B — Boot ROM
// Module: sv16_rom
//
// Small read-only memory holding the immutable monitor firmware (assembled
// from firmware/monitor/*.s by the Makefile and loaded through INIT_FILE).
// Behaviourally identical to the SRAM read port so the bus fabric treats it
// the same way: one-cycle acknowledge, synchronous registered read data.
//
// Mapped at ROM_BASE = 0xE000 (2K words / 4 KB) in the Rev B memory map.

`timescale 1ns / 1ps

module sv16_rom #(
    parameter int          DEPTH     = 2048,
    parameter int          ADDR_WIDTH= 11,
    parameter              INIT_FILE = ""
)(
    input  logic                  clk,
    input  logic                  rst_n,

    input  logic [ADDR_WIDTH-1:0] addr,
    output logic [15:0]           rdata,
    input  logic                  req,
    output logic                  ack
);

    logic [15:0] mem [DEPTH-1:0];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) ack <= 1'b0;
        else        ack <= req;
    end

    always_ff @(posedge clk) begin
        if (req) rdata <= mem[addr];
    end

    initial begin
        if (INIT_FILE != "") $readmemh(INIT_FILE, mem);
    end

endmodule : sv16_rom
