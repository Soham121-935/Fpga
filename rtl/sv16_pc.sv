// SV-16 Rev A — Program Counter (PC)
// Module: sv16_pc
//
// Features:
// - 16-bit register tracking execution instruction word address
// - Deterministic reset to 16'h0000 (Reset Vector)
// - Increment by 1 (fetch sequential instruction word)
// - Direct load (target address from register or immediate word for JMP / CALL / RET)
// - Relative branch load (PC + sign_extended_offset)
// - Stall / Hold (retains current value during multi-cycle waits or decode states)

`timescale 1ns / 1ps

module sv16_pc (
    input  logic        clk,
    input  logic        rst_n,

    // Controls
    input  logic        pc_inc,         // Increment PC by 1
    input  logic        pc_load,        // Load absolute target (target_addr)
    input  logic        pc_branch,      // Load relative branch (pc + branch_offset)
    input  logic [15:0] target_addr,    // Absolute target address
    input  logic [7:0]  branch_offset,  // 8-bit signed branch offset

    // Current PC Output
    output logic [15:0] pc
);

    logic [15:0] pc_reg;
    logic [15:0] branch_target;

    // Sign extend 8-bit offset to 16-bit
    assign branch_target = pc_reg + {{8{branch_offset[7]}}, branch_offset};
    assign pc            = pc_reg;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pc_reg <= 16'h0000;
        end else begin
            if (pc_load) begin
                pc_reg <= target_addr;
            end else if (pc_branch) begin
                pc_reg <= branch_target;
            end else if (pc_inc) begin
                pc_reg <= pc_reg + 16'd1;
            end
            // Implicit hold if neither pc_load, pc_branch, nor pc_inc is asserted
        end
    end

endmodule : sv16_pc
