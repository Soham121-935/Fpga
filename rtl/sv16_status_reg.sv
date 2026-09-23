// SV-16 Rev A — Status Register (SR)
// Module: sv16_status_reg
//
// Architectural Flag Mapping:
//   Bit 0: Z (Zero Flag)
//   Bit 1: C (Carry / Borrow Flag)
//   Bit 2: N (Negative Flag)
//   Bit 3: V (Signed Overflow Flag)
//   Bit 7: IE (Global Interrupt Enable)
//   Bits [6:4], [15:8]: Reserved (read as 0)
//
// Control Inputs:
//   flag_update_en : Enables latching of new flags from ALU
//   sr_write_en    : Enables direct architectural write to SR (e.g. from MOV or POP SR)
//   ie_set         : Atomic enable of global interrupts (EI instruction)
//   ie_clr         : Atomic disable of global interrupts (DI instruction)

`timescale 1ns / 1ps

module sv16_status_reg (
    input  logic        clk,
    input  logic        rst_n,

    // Flag inputs from ALU
    input  logic        flag_z_in,
    input  logic        flag_c_in,
    input  logic        flag_n_in,
    input  logic        flag_v_in,
    input  logic        flag_update_en,

    // Architectural bus/register write
    input  logic        sr_write_en,
    input  logic [15:0] sr_write_data,

    // Atomic interrupt enable/disable control
    input  logic        ie_set,
    input  logic        ie_clr,

    // Status Register output
    output logic [15:0] sr_out,
    output logic        flag_z,
    output logic        flag_c,
    output logic        flag_n,
    output logic        flag_v,
    output logic        flag_ie
);

    logic reg_z;
    logic reg_c;
    logic reg_n;
    logic reg_v;
    logic reg_ie;

    assign flag_z  = reg_z;
    assign flag_c  = reg_c;
    assign flag_n  = reg_n;
    assign flag_v  = reg_v;
    assign flag_ie = reg_ie;

    // Architectural SR read word
    assign sr_out = {8'h00, reg_ie, 3'b000, reg_v, reg_n, reg_c, reg_z};

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            reg_z  <= 1'b0;
            reg_c  <= 1'b0;
            reg_n  <= 1'b0;
            reg_v  <= 1'b0;
            reg_ie <= 1'b0;
        end else if (sr_write_en) begin
            // Direct architectural overwrite of Status Register
            reg_z  <= sr_write_data[0];
            reg_c  <= sr_write_data[1];
            reg_n  <= sr_write_data[2];
            reg_v  <= sr_write_data[3];
            reg_ie <= sr_write_data[7];
        end else begin
            // Flag latching from ALU execution
            if (flag_update_en) begin
                reg_z <= flag_z_in;
                reg_c <= flag_c_in;
                reg_n <= flag_n_in;
                reg_v <= flag_v_in;
            end

            // Atomic IE control (takes precedence or can be set concurrently)
            if (ie_set) begin
                reg_ie <= 1'b1;
            end else if (ie_clr) begin
                reg_ie <= 1'b0;
            end
        end
    end

endmodule : sv16_status_reg
