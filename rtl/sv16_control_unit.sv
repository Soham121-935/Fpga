// SV-16 Rev A — CPU Control Unit
// Module: sv16_control_unit
//
// Multi-cycle synchronous Finite State Machine (FSM):
//   S_FETCH     (0): Request instruction word from bus at PC
//   S_DECODE    (1): Latch IR, decode, check for 2-word instruction
//   S_FETCH_IMM (2): Fetch 2nd 16-bit word if LDI, JMP, or CALL
//   S_EXECUTE   (3): ALU operation, branch evaluation, compute effective addr
//   S_MEMORY    (4): Bus access for LOAD, STORE, PUSH, POP
//   S_WRITEBACK (5): Write register file / update status flags

`timescale 1ns / 1ps

module sv16_control_unit (
    input  logic        clk,
    input  logic        rst_n,

    // Decoder classification inputs
    input  logic [3:0]  opcode,
    input  logic [3:0]  cond,
    input  logic        is_alu_rr,
    input  logic        is_alu_imm,
    input  logic        is_ext_alu,
    input  logic        is_load,
    input  logic        is_store,
    input  logic        is_mov,
    input  logic        is_branch,
    input  logic        is_jmp,
    input  logic        is_call,
    input  logic        is_ret,
    input  logic        is_push,
    input  logic        is_pop,
    input  logic        is_cmp,
    input  logic        is_two_word,

    // Status flags from Status Register
    input  logic        flag_z,
    input  logic        flag_c,
    input  logic        flag_n,
    input  logic        flag_v,

    // Bus handshake
    input  logic        bus_ack,
    output logic        bus_req,
    output logic        bus_we,
    output logic        bus_addr_sel,  // 0 = PC, 1 = Memory Address (SP or Effective Addr)

    // PC Controls
    output logic        pc_inc,
    output logic        pc_load,
    output logic        pc_branch,

    // Datapath & Register File Controls
    output logic        ir_load,
    output logic        imm_load,
    output logic        reg_wen,
    output logic [1:0]  reg_wdata_sel, // 0 = ALU result, 1 = Memory read, 2 = Immediate, 3 = PC
    output logic        flag_update_en,
    output logic        alu_src_b_sel, // 0 = Register Rs2, 1 = Immediate

    // Stack pointer controls
    output logic        sp_dec,
    output logic        sp_inc,

    // State Output for Debug/Trace
    output logic [2:0]  fsm_state
);

    typedef enum logic [2:0] {
        S_FETCH     = 3'd0,
        S_DECODE    = 3'd1,
        S_FETCH_IMM = 3'd2,
        S_EXECUTE   = 3'd3,
        S_MEMORY    = 3'd4,
        S_WRITEBACK = 3'd5
    } state_e;

    state_e current_state, next_state;

    assign fsm_state = current_state;

    // Branch Condition Evaluation Logic
    logic branch_condition_met;
    always_comb begin
        case (cond)
            4'h0: branch_condition_met = 1'b1;                          // BRA (Always)
            4'h1: branch_condition_met = flag_z;                       // BEQ (Z == 1)
            4'h2: branch_condition_met = !flag_z;                      // BNE (Z == 0)
            4'h3: branch_condition_met = flag_c;                       // BC / BLO (C == 1)
            4'h4: branch_condition_met = !flag_c;                      // BNC / BHS (C == 0)
            4'h5: branch_condition_met = flag_n;                       // BN / BMI (N == 1)
            4'h6: branch_condition_met = !flag_n;                      // BP / BPL (N == 0)
            4'h7: branch_condition_met = flag_v;                       // BVS (V == 1)
            4'h8: branch_condition_met = !flag_v;                      // BVC (V == 0)
            4'h9: branch_condition_met = (flag_n ^ flag_v);            // BLT (N ^ V == 1)
            4'hA: branch_condition_met = !(flag_n ^ flag_v);           // BGE (N ^ V == 0)
            4'hB: branch_condition_met = (flag_z | (flag_n ^ flag_v)); // BLE
            4'hC: branch_condition_met = !(flag_z | (flag_n ^ flag_v));// BGT
            default: branch_condition_met = 1'b0;
        endcase
    end

    // Sequential State Register
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            current_state <= S_FETCH;
        end else begin
            current_state <= next_state;
        end
    end

    // Next-State Logic
    always_comb begin
        next_state = current_state;

        case (current_state)
            S_FETCH: begin
                if (bus_ack) begin
                    next_state = S_DECODE;
                end
            end

            S_DECODE: begin
                if (is_two_word) begin
                    next_state = S_FETCH_IMM;
                end else begin
                    next_state = S_EXECUTE;
                end
            end

            S_FETCH_IMM: begin
                if (bus_ack) begin
                    next_state = S_EXECUTE;
                end
            end

            S_EXECUTE: begin
                if (is_load || is_store || is_push || is_pop || is_call || is_ret) begin
                    next_state = S_MEMORY;
                end else if (is_alu_rr || is_alu_imm || is_ext_alu || is_mov) begin
                    next_state = S_WRITEBACK;
                end else begin
                    // JMP, Branch, CMP, NOP, CTRL
                    next_state = S_FETCH;
                end
            end

            S_MEMORY: begin
                if (bus_ack) begin
                    if (is_load || is_pop) begin
                        next_state = S_WRITEBACK;
                    end else begin
                        next_state = S_FETCH;
                    end
                end
            end

            S_WRITEBACK: begin
                next_state = S_FETCH;
            end

            default: next_state = S_FETCH;
        endcase
    end

    // Output Control Signals
    always_comb begin
        // Safe Defaults
        bus_req         = 1'b0;
        bus_we          = 1'b0;
        bus_addr_sel    = 1'b0; // 0 = PC
        pc_inc          = 1'b0;
        pc_load         = 1'b0;
        pc_branch       = 1'b0;
        ir_load         = 1'b0;
        imm_load        = 1'b0;
        reg_wen         = 1'b0;
        reg_wdata_sel   = 2'b00;
        flag_update_en  = 1'b0;
        alu_src_b_sel   = 1'b0;
        sp_dec          = 1'b0;
        sp_inc          = 1'b0;

        case (current_state)
            S_FETCH: begin
                bus_req      = 1'b1;
                bus_we       = 1'b0;
                bus_addr_sel = 1'b0; // Fetch from PC
                if (bus_ack) begin
                    ir_load = 1'b1;
                    pc_inc  = 1'b1;
                end
            end

            S_DECODE: begin
                // Register read occurs combinationally in decode
            end

            S_FETCH_IMM: begin
                bus_req      = 1'b1;
                bus_we       = 1'b0;
                bus_addr_sel = 1'b0; // Fetch immediate from PC
                if (bus_ack) begin
                    imm_load = 1'b1;
                    pc_inc   = 1'b1;
                end
            end

            S_EXECUTE: begin
                alu_src_b_sel = is_alu_imm;

                if (is_alu_rr || is_alu_imm || is_ext_alu || is_cmp) begin
                    flag_update_en = 1'b1;
                end

                if (is_branch && branch_condition_met) begin
                    pc_branch = 1'b1;
                end

                if (is_jmp) begin
                    pc_load = 1'b1; // Load 16-bit immediate word into PC
                end

                if (is_call) begin
                    sp_dec = 1'b1; // Pre-decrement SP for call return address push
                end else if (is_push) begin
                    sp_dec = 1'b1; // Pre-decrement SP for push
                end
            end

            S_MEMORY: begin
                bus_req      = 1'b1;
                bus_addr_sel = 1'b1; // Slave address from effective address or SP

                if (is_store || is_push) begin
                    bus_we = 1'b1;
                end else if (is_call) begin
                    bus_we = 1'b1; // Push return address (PC)
                end else begin
                    bus_we = 1'b0; // LOAD, POP, RET
                end

                if (bus_ack) begin
                    if (is_call) begin
                        pc_load = 1'b1; // Target address to PC
                    end else if (is_ret) begin
                        pc_load = 1'b1; // Pop return address into PC
                        sp_inc  = 1'b1;
                    end else if (is_pop) begin
                        sp_inc  = 1'b1;
                    end
                end
            end

            S_WRITEBACK: begin
                reg_wen = 1'b1;
                if (is_load || is_pop) begin
                    reg_wdata_sel = 2'b01; // Data from memory bus
                end else if (is_two_word && opcode == 4'h4) begin
                    reg_wdata_sel = 2'b10; // Immediate word for LDI
                end else begin
                    reg_wdata_sel = 2'b00; // ALU result / MOV result
                end
            end

            default: ;
        endcase
    end

endmodule : sv16_control_unit
