// SV-16 Rev B — CRC16-CCITT (0x1021) byte engine
// Module: sv16_crc16
//
// Used by the flash controller (VERIFY command) and by the hardware boot
// engine to validate firmware images stored in SPI flash.
//
// Parameters: polynomial 0x1021, initial value 0xFFFF, no input/output
// reflection, no final XOR. The firmware image builder
// (scripts/sv16_fwpack.py) computes the identical CRC so images can be
// validated both on the host and in hardware.

`timescale 1ns / 1ps

module sv16_crc16 (
    input  logic        clk,
    input  logic        rst_n,

    input  logic        crc_init,   // load 0xFFFF (takes precedence)
    input  logic        crc_en,     // advance the CRC by one byte
    input  logic [7:0]  crc_data,

    output logic [15:0] crc_out
);

    localparam logic [15:0] CRC_INIT = 16'hFFFF;
    localparam logic [15:0] CRC_POLY = 16'h1021;

    function automatic [15:0] crc16_byte;
        input [15:0] crc_in;
        input [7:0]  data;
        reg [15:0]   c;
        integer      i;
        begin
            c = crc_in;
            for (i = 7; i >= 0; i = i - 1) begin
                if (c[15] ^ data[i]) c = (c << 1) ^ CRC_POLY;
                else                 c = (c << 1);
            end
            crc16_byte = c;
        end
    endfunction

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)          crc_out <= CRC_INIT;
        else if (crc_init)   crc_out <= CRC_INIT;
        else if (crc_en)     crc_out <= crc16_byte(crc_out, crc_data);
    end

endmodule : sv16_crc16
