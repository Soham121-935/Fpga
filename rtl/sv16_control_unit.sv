// SV-16 Rev B — CPU Control Unit
// Module: sv16_control_unit
//
// Multi-cycle synchronous Finite State Machine (FSM):
//   S_FETCH      ( 0): Request instruction word from bus at PC
//   S_DECODE     ( 1): Latch IR, decode, check for 2-word instruction
//   S_FETCH_IMM  ( 2): Fetch 2nd 16-bit word if LDI, JMP, or CALL
//   S_EXECUTE    ( 3): ALU operation, branch evaluation, compute effective addr
//   S_DIV_WAIT   (16): wait for the ALU's iterative divider (DIV/MOD, ADR-018)
//   S_MEMORY     ( 4): Bus access for LOAD, STORE, PUSH, POP, CALL, RET
//   S_WRITEBACK  ( 5): Write register file / update status flags
//   S_HALTED     ( 6): Core stopped (HALT, debug hold, unresolvable fault)
//   S_IRQ_*      (7..12): Interrupt/exception entry (push SR, push PC, vector)
//   S_RETI_*     (13..15): RETI (pop PC, pop SR)
//
// System bus protocol (Rev B, see docs/BUS_ARCHITECTURE.md):
//   * A bus transfer starts with a request: the master asserts bus_req and
//     holds addr/we/wdata stable.
//   * A slave that answers in the following cycle (RAM, ROM, all register
//     based peripherals) sees bus_req for one cycle and asserts bus_ack one
//     cycle later, with valid bus_rdata in that same cycle.
//   * A slave that needs wait states (the flash data port) keeps bus_req
//     asserted and asserts bus_ack whenever the transfer can complete; the
//     CPU stays in its memory state until then.  Such a slave must be written
//     so that a sustained request performs the transfer once.
//   * The control unit tracks whether the request of the current state has
//     already been issued (`bus_issued`), which guarantees that a stale ack
//     from a previous transfer can never be mistaken for the completion of a
//     new one. (Rev A evaluated bus_ack in the first cycle of a new state and
//     therefore sampled old data whenever the FSM moved between bus states.)
//
// Rev B function changes (see docs/ARCHITECTURE_DECISIONS.md):
//   * LDI reaches S_WRITEBACK (Rev A skipped writeback: LDI never wrote Rd).
//   * CTRL sub-opcodes HALT / EI / DI / RETI implemented.
//   * Hardware interrupt entry and RETI with architectural SR save/restore.
//   * Illegal opcodes trap via vector index IRQ_TRAP (7); a zero vector halts
//     the core instead of jumping to an arbitrary address.
//   * Debug hold (halt_req) and single step (step_en) support.
//   * DIV/MOD run on the ALU's iterative divider: S_EXECUTE pulses
//     `alu_div_start`, S_DIV_WAIT holds until `alu_div_busy` falls, and only
//     then are the flags updated (they would otherwise latch intermediate
//     remainders) and the quotient/remainder written back.

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
    input  logic        is_illegal,
    input  logic        is_nop,
    input  logic        is_halt,
    input  logic        is_ei,
    input  logic        is_di,
    input  logic        is_reti,

    // Iterative divider handshake (ADR-018)
    input  logic        ext_is_div,     // current EXT_ALU instruction is DIV/MOD
    input  logic        alu_div_busy,
    output logic        alu_div_start,

    // Status flags from Status Register
    input  logic        flag_z,
    input  logic        flag_c,
    input  logic        flag_n,
    input  logic        flag_v,
    input  logic        flag_ie,

    // Interrupt interface
    input  logic        irq_req,        // level: >=1 enabled pending source
    input  logic [2:0]  irq_index,      // index of highest priority source
    input  logic [15:0] irq_vec_base,   // word address of the vector table
    input  logic        vector_zero,    // latched vector == 0 (unhandled)

    // Debug / boot hold
    input  logic        halt_req,       // stop at the next instruction boundary
    input  logic        step_en,        // single step while halted

    // Bus handshake
    input  logic        bus_ack,
    output logic        bus_req,
    output logic        bus_we,
    output logic [1:0]  bus_addr_sel,   // 0 = PC, 1 = SP, 2 = effective, 3 = vector
    output logic [1:0]  bus_wdata_sel,  // 0 = Rs2, 1 = Rs1, 2 = PC, 3 = SR

    // PC Controls
    output logic        pc_inc,
    output logic        pc_load,
    output logic        pc_branch,
    output logic [1:0]  pc_sel,         // 0 = imm, 1 = bus_rdata,
                                        // 2 = vector, 3 = RETI frame

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

    // Status register controls
    output logic        ie_set,
    output logic        ie_clr,
    output logic        sr_write_en,

    // Interrupt / trap bookkeeping
    output logic        irq_ack,        // 1-cycle pulse when an IRQ is taken
    output logic        illegal_irq,    // 1-cycle pulse when a trap is taken
    output logic        fault_halt,     // core stopped because vector == 0
    output logic        step_taken,     // 1-cycle pulse: one step executed

    // Datapath latch enables for vector/return-frame registers
    output logic        vec_latch_en,
    output logic        ret_latch_en,
    output logic        rd_data_latch_en,
    output logic        sr_latch_en,

    // State Output for Debug/Trace
    output logic        halted,
    output logic [4:0]  fsm_state
);

    typedef enum logic [4:0] {
        S_FETCH      = 5'd0,
        S_DECODE     = 5'd1,
        S_FETCH_IMM  = 5'd2,
        S_EXECUTE    = 5'd3,
        S_MEMORY     = 5'd4,
        S_WRITEBACK  = 5'd5,
        S_HALTED     = 5'd6,
        S_IRQ_DEC_SR = 5'd7,
        S_IRQ_WR_SR  = 5'd8,
        S_IRQ_DEC_PC = 5'd9,
        S_IRQ_WR_PC  = 5'd10,
        S_IRQ_VEC    = 5'd11,
        S_IRQ_JUMP   = 5'd12,
        S_RETI_PC    = 5'd13,
        S_RETI_SR    = 5'd14,
        S_RETI_DONE  = 5'd15,
        S_DIV_WAIT   = 5'd16
    } state_e;

    state_e current_state, next_state;
    logic   trap_active;   // current entry sequence is an exception (not an IRQ)
    logic   bus_issued;    // request of the current state has been presented

    assign fsm_state = current_state;
    assign halted    = (current_state == S_HALTED);

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

    // Interrupt entry is evaluated at instruction boundaries only.
    logic irq_enter;
    assign irq_enter = (current_state == S_FETCH) && irq_req && flag_ie;

    // A transfer completes in the cycle after the request was presented.
    logic access_wanted;
    logic access_done;
    assign access_done = bus_issued && bus_ack;

    // ------------------------------------------------------ State register
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            current_state <= S_FETCH;
            trap_active   <= 1'b0;
            bus_issued    <= 1'b0;
        end else begin
            current_state <= next_state;

            if (current_state == S_DECODE && is_illegal) begin
                trap_active <= 1'b1;
            end else if (current_state == S_IRQ_JUMP) begin
                trap_active <= 1'b0;
            end

            // Request bookkeeping: one request pulse per state, cleared on
            // every state change so a new transfer always starts clean.
            if (next_state != current_state) begin
                bus_issued <= 1'b0;
            end else if (access_wanted && !bus_issued) begin
                bus_issued <= 1'b1;
            end
        end
    end

    // ------------------------------------------------- Next-State Logic
    always_comb begin
        next_state = current_state;

        case (current_state)
            S_FETCH: begin
                if (halt_req && !step_en) begin
                    next_state = S_HALTED;
                end else if (irq_enter) begin
                    next_state = S_IRQ_DEC_SR;
                end else if (access_done) begin
                    next_state = S_DECODE;
                end
            end

            S_DECODE: begin
                if (is_illegal) begin
                    next_state = S_IRQ_DEC_SR;   // unmaskable trap
                end else if (is_two_word) begin
                    next_state = S_FETCH_IMM;
                end else begin
                    next_state = S_EXECUTE;
                end
            end

            S_FETCH_IMM: begin
                if (access_done) begin
                    next_state = S_EXECUTE;
                end
            end

            S_EXECUTE: begin
                if (is_halt) begin
                    next_state = S_HALTED;
                end else if (is_reti) begin
                    next_state = S_RETI_PC;
                end else if (is_load || is_store || is_push || is_pop || is_call || is_ret) begin
                    next_state = S_MEMORY;
                end else if (is_alu_rr || is_alu_imm || is_ext_alu || is_mov ||
                             (is_two_word && opcode == 4'h4)) begin
                    next_state = S_WRITEBACK;   // includes LDI (see ADR-015)
                end else begin
                    // JMP, Branch, CMP, NOP, EI, DI
                    next_state = S_FETCH;
                end
            end

            S_MEMORY: begin
                if (access_done) begin
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

            S_HALTED: begin
                // Resume conditions: single step, or the halt request going
                // away.  Without the second term a halted core could only ever
                // move again by stepping: the reset-time handover (startup
                // holds the CPU in halt until the boot loader has verified an
                // image, then releases it) and any debugger "continue" would
                // leave the CPU parked in S_HALTED forever.
                if (step_en || !halt_req) begin
                    next_state = S_FETCH;
                end
            end

            S_DIV_WAIT:   if (!alu_div_busy) next_state = S_WRITEBACK;

            S_IRQ_DEC_SR: next_state = S_IRQ_WR_SR;
            S_IRQ_WR_SR:  if (access_done) next_state = S_IRQ_DEC_PC;
            S_IRQ_DEC_PC: next_state = S_IRQ_WR_PC;
            S_IRQ_WR_PC:  if (access_done) next_state = S_IRQ_VEC;
            S_IRQ_VEC:    if (access_done) next_state = S_IRQ_JUMP;

            S_IRQ_JUMP: begin
                if (vector_zero) begin
                    next_state = S_HALTED;       // no handler installed
                end else begin
                    next_state = S_FETCH;
                end
            end

            S_RETI_PC:   if (access_done) next_state = S_RETI_SR;
            S_RETI_SR:   if (access_done) next_state = S_RETI_DONE;
            S_RETI_DONE: next_state = S_FETCH;

            default: next_state = S_FETCH;
        endcase

        // Instruction-boundary hold: never halt in the middle of a bus access.
        if (next_state == S_FETCH && halt_req && !step_en) begin
            next_state = S_HALTED;
        end
    end

    // --------------------------------------------------- Output control
    always_comb begin
        // Safe Defaults
        access_wanted   = 1'b0;
        bus_we          = 1'b0;
        bus_addr_sel    = 2'b00; // 0 = PC
        bus_wdata_sel   = 2'b00; // 0 = Rs2
        pc_inc          = 1'b0;
        pc_load         = 1'b0;
        pc_branch       = 1'b0;
        pc_sel          = 2'b00;
        ir_load         = 1'b0;
        imm_load        = 1'b0;
        reg_wen         = 1'b0;
        reg_wdata_sel   = 2'b00;
        flag_update_en  = 1'b0;
        alu_src_b_sel   = 1'b0;
        sp_dec          = 1'b0;
        sp_inc          = 1'b0;
        ie_set          = 1'b0;
        ie_clr          = 1'b0;
        sr_write_en     = 1'b0;
        irq_ack         = 1'b0;
        illegal_irq     = 1'b0;
        fault_halt      = 1'b0;
        step_taken      = 1'b0;
        vec_latch_en    = 1'b0;
        ret_latch_en      = 1'b0;
        rd_data_latch_en  = 1'b0;
        sr_latch_en     = 1'b0;
        alu_div_start   = 1'b0;

        case (current_state)
            S_FETCH: begin
                if (!irq_enter && !(halt_req && !step_en)) begin
                    access_wanted = 1'b1;
                    bus_we        = 1'b0;
                    bus_addr_sel  = 2'b00; // Fetch from PC
                    if (access_done) begin
                        ir_load = 1'b1;
                        pc_inc  = 1'b1;
                    end
                end
            end

            S_DECODE: begin
                // Register read occurs combinationally in decode
                if (is_illegal) begin
                    illegal_irq = 1'b1;   // report faulting PC to the system block
                end
            end

            S_FETCH_IMM: begin
                access_wanted = 1'b1;
                bus_we        = 1'b0;
                bus_addr_sel  = 2'b00; // Fetch immediate from PC
                if (access_done) begin
                    imm_load = 1'b1;
                    pc_inc   = 1'b1;
                end
            end

            S_EXECUTE: begin
                alu_src_b_sel = is_alu_imm;

                if ((is_alu_rr || is_alu_imm || is_ext_alu || is_cmp) && !ext_is_div) begin
                    flag_update_en = 1'b1;
                end

                if (ext_is_div) begin
                    alu_div_start = 1'b1;   // one-cycle pulse: S_EXECUTE exits next cycle
                end

                if (is_branch && branch_condition_met) begin
                    pc_branch = 1'b1;
                end

                if (is_jmp) begin
                    pc_load = 1'b1; // Load 16-bit immediate word into PC
                end

                if (is_ei) begin
                    ie_set = 1'b1;
                end

                if (is_di) begin
                    ie_clr = 1'b1;   // takes precedence over ie_set in the SR
                end

                if (is_call || is_push) begin
                    sp_dec = 1'b1; // Pre-decrement SP for the pending push
                end
            end

            S_DIV_WAIT: begin
                // Flags may only be captured once the divider has finished:
                // before that they would reflect an intermediate remainder.
                if (!alu_div_busy) begin
                    flag_update_en = 1'b1;
                end
            end

            S_MEMORY: begin
                access_wanted = 1'b1;
                // LOAD/STORE use the effective address; stack ops use SP
                bus_addr_sel  = (is_load || is_store) ? 2'b10 : 2'b01;

                // Capture the read data in the very cycle the slave
                // acknowledges it.  S_WRITEBACK is one cycle later, and by
                // then the address mux has already moved back to the program
                // counter: a slave that drives rdata combinationally from the
                // address (every peripheral) would hand back the wrong word.
                // RAM and the boot ROM register their read data and so hid
                // this; the latch makes all slaves behave identically.
                if (access_done && !bus_we) rd_data_latch_en = 1'b1;

                if (is_call) begin
                    bus_we        = 1'b1;
                    bus_wdata_sel = 2'b10;  // PC (return address)
                end else if (is_push) begin
                    bus_we        = 1'b1;
                    bus_wdata_sel = 2'b01;  // Rs1 (the pushed register)
                end else if (is_store) begin
                    bus_we        = 1'b1;
                    bus_wdata_sel = 2'b00;  // Rs2 (the store data register)
                end else begin
                    bus_we = 1'b0; // LOAD, POP, RET
                end

                if (access_done) begin
                    if (is_call) begin
                        pc_load = 1'b1; // Target address to PC
                        pc_sel  = 2'b00;
                    end else if (is_ret) begin
                        pc_load = 1'b1; // Pop return address into PC
                        pc_sel  = 2'b01; // source = bus_rdata
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

            S_HALTED: begin
                if (step_en) begin
                    step_taken = 1'b1;
                end
            end

            S_IRQ_DEC_SR: begin
                sp_dec = 1'b1;            // make room for the saved SR
            end

            S_IRQ_WR_SR: begin
                access_wanted = 1'b1;
                bus_we        = 1'b1;
                bus_addr_sel  = 2'b01;    // SP
                bus_wdata_sel = 2'b11;    // SR
            end

            S_IRQ_DEC_PC: begin
                sp_dec = 1'b1;            // make room for the return address
            end

            S_IRQ_WR_PC: begin
                access_wanted = 1'b1;
                bus_we        = 1'b1;
                bus_addr_sel  = 2'b01;    // SP
                bus_wdata_sel = 2'b10;    // PC (return address)
            end

            S_IRQ_VEC: begin
                access_wanted = 1'b1;
                bus_we        = 1'b0;
                bus_addr_sel  = 2'b11;    // vector table entry
                if (access_done) begin
                    vec_latch_en = 1'b1;
                end
            end

            S_IRQ_JUMP: begin
                if (vector_zero) begin
                    fault_halt = 1'b1;    // no handler: stop the core safely
                end else begin
                    pc_load = 1'b1;       // PC <- vector
                    pc_sel  = 2'b10;      // source = latched vector
                    ie_clr  = 1'b1;       // global interrupts masked during ISR
                    irq_ack = !trap_active;
                end
            end

            S_RETI_PC: begin
                access_wanted = 1'b1;
                bus_we        = 1'b0;
                bus_addr_sel  = 2'b01;     // SP: return address
                if (access_done) begin
                    ret_latch_en = 1'b1;
                    sp_inc       = 1'b1;
                end
            end

            S_RETI_SR: begin
                access_wanted = 1'b1;
                bus_we        = 1'b0;
                bus_addr_sel  = 2'b01;     // SP: saved status register
                if (access_done) begin
                    sr_latch_en = 1'b1;
                    sp_inc      = 1'b1;
                end
            end

            S_RETI_DONE: begin
                pc_load     = 1'b1;       // PC <- popped return address
                pc_sel      = 2'b11;      // source = latched RETI frame
                sr_write_en = 1'b1;       // SR <- popped value (restores IE)
            end

            default: ;
        endcase
    end

    // The request is presented until the slave acknowledges it.  Slaves that
    // answer in the next cycle (RAM, ROM, every register-based peripheral) see
    // exactly the single-cycle pulse they always saw, because the acknowledge
    // arrives before the request could be repeated.  A slave that needs bus
    // wait states - the flash controller, which cannot answer a data-port
    // access until the SPI transfer it depends on has completed - simply keeps
    // the request asserted until it is ready, and the CPU's memory state waits
    // for the same acknowledge.  Slaves with side effects must act once per
    // request assertion and use their own serviced/pending flags when they
    // stretch a transfer over several cycles.
    assign bus_req = access_wanted && (!bus_issued || !bus_ack);

endmodule : sv16_control_unit
