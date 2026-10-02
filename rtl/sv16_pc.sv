// SV-16 Rev B — Program Counter (PC)
// Module: sv16_pc
//
// Features:
// - 16-bit register tracking execution instruction word address
// - Deterministic reset to 16'h0000
// - Boot-vector load: on reset release the core can be started at an arbitrary
//   entry point supplied by the system/boot controller (Rev B)
// - Increment by 1 (fetch sequential instruction word)
// - Direct load (target address from register or immediate word for
//   JMP / CALL / RET / interrupt vector / RETI)
// - Relative branch load (PC + sign_extended_offset)
// - Stall / Hold (retains current value during multi-cycle waits)

`timescale 1ns / 1ps

module sv16_pc (
    input  logic        clk,
    input  logic        rst_n,

    // Controls
    input  logic        pc_inc,         // Increment PC by 1
    input  logic        pc_load,        // Load absolute target (target_addr)
    input  logic        pc_branch,      // Load relative branch (pc + branch_offset)
    input  logic        pc_boot,        // Load boot vector (cold boot release)
    input  logic [15:0] target_addr,    // Absolute target address
    input  logic [7:0]  branch_offset,  // 8-bit signed branch offset
    input  logic [15:0] boot_addr,      // Boot entry address

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
            if (pc_boot) begin
                pc_reg <= boot_addr;        // highest priority: boot release
            end else if (pc_load) begin
                pc_reg <= target_addr;
            end else if (pc_branch) begin
                pc_reg <= branch_target;
            end else if (pc_inc) begin
                pc_reg <= pc_reg + 16'd1;
            end
            // Implicit hold if no control signal is asserted
        end
    end

endmodule : sv16_pc
