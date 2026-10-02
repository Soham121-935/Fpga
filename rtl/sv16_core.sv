// SV-16 Rev B — CPU Core
// Module: sv16_core
//
// Integrates:
// - sv16_pc           (Program Counter, boot-vector capable)
// - sv16_decoder      (Instruction Decoder)
// - sv16_regfile      (8 x 16-bit Register File)
// - sv16_alu          (16-bit ALU)
// - sv16_status_reg   (Status Register Z, C, N, V, IE)
// - sv16_control_unit (Multi-cycle execution FSM, interrupt sequencer)
// - System Bus Master Interface
// - Hardware interrupt entry (push SR + PC, vector fetch) and RETI
// - Debug port: halt / single-step, PC / SP / SR read-modify access
//
// Rev B changes (see docs/ARCHITECTURE_DECISIONS.md):
// - Fixed register read-port mapping for STORE / PUSH (Rev A wrote the wrong
//   register value; peripheral stores never reached memory).
// - LDI writeback path fixed (Rev A never wrote the destination register).
// - reset_n now releases the core to an arbitrary boot vector with a
//   configurable initial stack pointer (used by the SPI-flash boot engine).

`timescale 1ns / 1ps

module sv16_core (
    input  logic        clk,
    input  logic        rst_n,

    // System Bus Master Interface
    output logic [15:0] bus_addr,
    output logic [15:0] bus_wdata,
    input  logic [15:0] bus_rdata,
    output logic        bus_req,
    output logic        bus_we,
    input  logic        bus_ack,

    // Interrupt interface
    input  logic        irq_req,       // level: at least one enabled source
    input  logic [2:0]  irq_index,     // highest priority pending source index
    input  logic [15:0] irq_vec_base,  // vector table base (word address)
    output logic        irq_ack,       // pulse: interrupt accepted

    // System / boot control
    input  logic        halt_req,      // debug hold or boot-loader hold
    input  logic        step_en,       // single-step while halted
    input  logic        boot_load,     // pulse: load PC/SP from boot vector
    input  logic [15:0] boot_vec,      // entry address for boot_load
    input  logic [15:0] boot_sp,       // initial stack pointer for boot_load
    output logic        halted,        // core is stopped
    output logic        step_taken,    // pulse: one instruction stepped
    output logic        fault_halt,    // stopped because a vector was zero
    output logic        illegal_irq,   // pulse: illegal opcode trapped
    output logic [15:0] illegal_pc,    // address of the illegal instruction

    // Debug port (write access is only honoured while halted)
    input  logic        dbg_pc_wr,
    input  logic [15:0] dbg_pc_val,
    input  logic        dbg_sp_wr,
    input  logic [15:0] dbg_sp_val,
    input  logic        dbg_sr_wr,
    input  logic [15:0] dbg_sr_val,

    // Core Debug & Observability
    output logic [15:0] dbg_pc,
    output logic [15:0] dbg_ir,
    output logic [15:0] dbg_sr,
    output logic [15:0] dbg_sp,
    output logic [4:0]  dbg_state
);

    // Internal Registers
    logic [15:0] ir_reg;
    logic [15:0] imm_reg;
    logic [15:0] sp_reg;
    logic [15:0] vec_reg;      // latched interrupt/exception handler address
    logic [15:0] ret_pc_reg;   // RETI: popped return address
    logic [15:0] rd_data_reg;  // LOAD/POP data latched on the bus acknowledge
    logic [15:0] ret_sr_reg;   // RETI: popped status register
    logic        vector_zero;  // latched handler address is 0 (unhandled)

    // Interconnect wires
    logic [15:0] pc_val;
    assign dbg_pc = pc_val;
    assign dbg_ir = ir_reg;
    assign dbg_sp = sp_reg;
    assign illegal_pc = pc_val - 16'd1;
    assign vector_zero = (vec_reg == 16'h0000);

    // Decoder outputs
    logic [3:0]  opcode;
    logic [2:0]  dec_rd;
    logic [2:0]  dec_rs1;
    logic [2:0]  dec_rs2;
    logic [2:0]  subop;
    logic [3:0]  cond;
    logic [8:0]  ctrl_subop;
    logic [15:0] imm9_ext;
    logic [15:0] offset6_ext;
    logic [7:0]  branch_offset;
    logic        is_alu_rr;
    logic        is_alu_imm;
    logic        is_ext_alu;
    logic        is_load;
    logic        is_store;
    logic        is_mov;
    logic        is_branch;
    logic        is_jmp;
    logic        is_call;
    logic        is_ret;
    logic        is_push;
    logic        is_pop;
    logic        is_cmp;
    logic        is_two_word;
    logic        is_illegal;
    logic        is_nop;
    logic        is_halt;
    logic        is_ei;
    logic        is_di;
    logic        is_reti;

    // Control Unit outputs
    logic [1:0]  bus_addr_sel;
    logic [1:0]  bus_wdata_sel;
    logic [1:0]  pc_sel;
    logic        pc_inc;
    logic        pc_load;
    logic        pc_branch;
    logic        ir_load;
    logic        imm_load;
    logic        reg_wen;
    logic [1:0]  reg_wdata_sel;
    logic        flag_update_en;
    logic        alu_src_b_sel;
    logic        sp_dec;
    logic        sp_inc;
    logic        ie_set;
    logic        ie_clr;
    logic        sr_write_en;
    logic        vec_latch_en;
    logic        ret_latch_en;
    logic        rd_data_latch_en;
    logic        sr_latch_en;
    logic [4:0]  fsm_state;

    assign dbg_state = fsm_state;

    // Status Register wires
    logic        flag_z;
    logic        flag_c;
    logic        flag_n;
    logic        flag_v;
    logic        flag_ie;
    logic [15:0] sr_val;
    assign dbg_sr = sr_val;

    // Register File wires
    logic [15:0] reg_rdata1;
    logic [15:0] reg_rdata2;
    logic [15:0] reg_wdata;

    // Result register: the ALU's output is combinational on operands that come
    // from the instruction register and the register file, so it is only valid
    // in the cycle the control unit asserts the operand select and the flags
    // are captured (S_EXECUTE, or the last S_DIV_WAIT cycle for DIV/MOD).  The
    // register file commits one state later, so the value travels through here.
    // Without it ADDI/SUBI committed the ALU recomputed with B = the Rs2-field
    // register instead of the immediate.
    logic [15:0] alu_result_r;

    // ALU wires
    logic [15:0] alu_in_a;
    logic [15:0] alu_in_b;
    logic [15:0] alu_result;
    logic        alu_flag_z;
    logic        alu_flag_c;
    logic        alu_flag_n;
    logic        alu_flag_v;

    // Effective Address calculation for memory operations: Rb + offset
    logic [15:0] effective_addr;
    assign effective_addr = reg_rdata1 + offset6_ext;

    // Debug writes are only honoured while the core is held.
    logic dbg_pc_wr_eff, dbg_sp_wr_eff, dbg_sr_wr_eff;
    assign dbg_pc_wr_eff = dbg_pc_wr && halt_req;
    assign dbg_sp_wr_eff = dbg_sp_wr && halt_req;
    assign dbg_sr_wr_eff = dbg_sr_wr && halt_req;

    // ------------------------------------------------------- Stack Pointer
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sp_reg <= 16'h3FFE; // top of the Rev B SRAM (32 KB, 16K words)
        end else if (boot_load) begin
            sp_reg <= boot_sp;
        end else if (dbg_sp_wr_eff) begin
            sp_reg <= dbg_sp_val;
        end else if (sp_dec) begin
            sp_reg <= sp_reg - 16'd1;
        end else if (sp_inc) begin
            sp_reg <= sp_reg + 16'd1;
        end
    end

    // ------------------------------------------- Instruction / Immediate /
    //                              interrupt vector / RETI frame registers
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ir_reg     <= 16'h0000; // NOP
            imm_reg    <= 16'h0000;
            vec_reg    <= 16'h0000;
            ret_pc_reg <= 16'h0000;
            ret_sr_reg <= 16'h0000;
        end else begin
            if (ir_load)       ir_reg     <= bus_rdata;
            if (imm_load)      imm_reg    <= bus_rdata;
            if (vec_latch_en)  vec_reg    <= bus_rdata;
            if (ret_latch_en)  ret_pc_reg <= bus_rdata;
            if (rd_data_latch_en) rd_data_reg <= bus_rdata;
            if (sr_latch_en)   ret_sr_reg <= bus_rdata;
        end
    end

    //------------------------------------------------------ Bus address mux
    logic [15:0] vec_addr;
    assign vec_addr = irq_vec_base + {{13{1'b0}}, irq_index};

    always_comb begin
        case (bus_addr_sel)
            2'b00:   bus_addr = pc_val;        // instruction / immediate fetch
            2'b01:   bus_addr = sp_reg;        // stack frame access
            2'b10:   bus_addr = effective_addr;// LOAD/STORE data address
            2'b11:   bus_addr = vec_addr;      // interrupt vector table
            default: bus_addr = effective_addr;
        endcase
    end

    // --------------------------------------------------- Bus write data mux
    always_comb begin
        case (bus_wdata_sel)
            2'b00:   bus_wdata = reg_rdata2;  // format-R source / STORE data
            2'b01:   bus_wdata = reg_rdata1;  // PUSH source
            2'b10:   bus_wdata = pc_val;      // CALL return address
            2'b11:   bus_wdata = sr_val;      // interrupt entry: saved SR
            default: bus_wdata = reg_rdata2;
        endcase
    end

    // --------------------------------------------------- PC target address
    logic [15:0] pc_target;
    logic        pc_load_eff;
    assign pc_load_eff = pc_load || boot_load || dbg_pc_wr_eff;

    always_comb begin
        if (dbg_pc_wr_eff)          pc_target = dbg_pc_val;
        else if (boot_load)         pc_target = boot_vec;
        else begin
            case (pc_sel)
                2'b00:   pc_target = imm_reg;
                2'b01:   pc_target = bus_rdata;
                2'b10:   pc_target = vec_reg;
                2'b11:   pc_target = ret_pc_reg;
                default: pc_target = imm_reg;
            endcase
        end
    end

    // Program Counter Instance
    sv16_pc u_pc (
        .clk(clk),
        .rst_n(rst_n),
        .pc_inc(pc_inc),
        .pc_load(pc_load_eff),
        .pc_branch(pc_branch),
        .pc_boot(boot_load),
        .target_addr(pc_target),
        .branch_offset(branch_offset),
        .boot_addr(boot_vec),
        .pc(pc_val)
    );

    // Instruction Decoder Instance
    sv16_decoder u_decoder (
        .instr(ir_reg),
        .opcode(opcode),
        .rd(dec_rd),
        .rs1(dec_rs1),
        .rs2(dec_rs2),
        .subop(subop),
        .cond(cond),
        .ctrl_subop(ctrl_subop),
        .imm9_ext(imm9_ext),
        .offset6_ext(offset6_ext),
        .branch_offset(branch_offset),
        .is_alu_rr(is_alu_rr),
        .is_alu_imm(is_alu_imm),
        .is_ext_alu(is_ext_alu),
        .is_load(is_load),
        .is_store(is_store),
        .is_mov(is_mov),
        .is_branch(is_branch),
        .is_jmp(is_jmp),
        .is_call(is_call),
        .is_ret(is_ret),
        .is_push(is_push),
        .is_pop(is_pop),
        .is_cmp(is_cmp),
        .is_two_word(is_two_word),
        .is_illegal(is_illegal),
        .is_nop(is_nop),
        .is_halt(is_halt),
        .is_ei(is_ei),
        .is_di(is_di),
        .is_reti(is_reti)
    );

    // Register File Instance
    sv16_regfile u_regfile (
        .clk(clk),
        .rst_n(rst_n),
        .raddr1(dec_rs1),
        .rdata1(reg_rdata1),
        .raddr2(dec_rs2),
        .rdata2(reg_rdata2),
        .wen(reg_wen),
        .waddr(dec_rd),
        .wdata(reg_wdata)
    );

    // ALU Input Multiplexing
    assign alu_in_a = reg_rdata1;
    assign alu_in_b = (alu_src_b_sel) ? imm9_ext : reg_rdata2;

    // ALU Sub-Opcode selection
    logic [2:0] effective_alu_op;
    // CMP is architecturally "Rs1 - Rs2" (docs/ISA.md), so the ALU operation
    // is forced to SUB regardless of the SubOp field: Rev A/B left it to the
    // encoder, which made CMP add instead of compare and left the Z flag
    // unreachable -- every BEQ/BNE therefore mispredicted.
    assign effective_alu_op = (is_cmp)   ? 3'b001 :
                              (is_alu_imm) ? ((opcode == 4'h2) ? 3'b000 : 3'b001) :
                                             subop;

    // DIV/MOD are the only operations that need more than one clock: they are
    // served by the ALU's iterative divider (ADR-018), so the control unit has
    // to hold the core in a wait state until the result is valid.
    logic ext_is_div;      // this extended-ALU instruction is DIV or MOD
    logic alu_div_start;
    logic alu_div_busy;
    assign ext_is_div = is_ext_alu && ((subop == 3'b011) || (subop == 3'b100));

    // ALU Instance
    sv16_alu u_alu (
        .clk(clk),
        .rst_n(rst_n),
        .a(alu_in_a),
        .b(alu_in_b),
        .alu_op(effective_alu_op),
        .is_extended(is_ext_alu),
        .result(alu_result),
        .flag_z(alu_flag_z),
        .flag_c(alu_flag_c),
        .flag_n(alu_flag_n),
        .flag_v(alu_flag_v),
        .div_start(alu_div_start),
        .div_busy(alu_div_busy)
    );

    // Status Register Instance
    logic        sr_write_en_eff;
    logic [15:0] sr_write_data_eff;
    assign sr_write_en_eff   = sr_write_en || dbg_sr_wr_eff;
    assign sr_write_data_eff = dbg_sr_wr_eff ? dbg_sr_val : ret_sr_reg;

    sv16_status_reg u_status_reg (
        .clk(clk),
        .rst_n(rst_n),
        .flag_z_in(alu_flag_z),
        .flag_c_in(alu_flag_c),
        .flag_n_in(alu_flag_n),
        .flag_v_in(alu_flag_v),
        .flag_update_en(flag_update_en),
        .sr_write_en(sr_write_en_eff),
        .sr_write_data(sr_write_data_eff),
        .ie_set(ie_set),
        .ie_clr(ie_clr),
        .sr_out(sr_val),
        .flag_z(flag_z),
        .flag_c(flag_c),
        .flag_n(flag_n),
        .flag_v(flag_v),
        .flag_ie(flag_ie)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            alu_result_r <= 16'h0000;
        end else if (flag_update_en) begin
            // flag_update_en marks the cycle the ALU's operands and operation
            // are the instruction's own -- exactly when the flags are latched,
            // so the result and the flags always belong to the same evaluation
            alu_result_r <= alu_result;
        end
    end

    // Register Writeback Multiplexer
    always_comb begin
        case (reg_wdata_sel)
            2'b00: reg_wdata = (is_mov) ? reg_rdata1 : alu_result_r;
            2'b01: reg_wdata = rd_data_reg;  // latched on the slave's ack
            2'b10: reg_wdata = imm_reg; // 16-bit immediate from LDI
            2'b11: reg_wdata = pc_val;
            default: reg_wdata = alu_result_r;
        endcase
    end

    // Control Unit Instance
    sv16_control_unit u_control_unit (
        .clk(clk),
        .rst_n(rst_n),
        .opcode(opcode),
        .cond(cond),
        .is_alu_rr(is_alu_rr),
        .is_alu_imm(is_alu_imm),
        .is_ext_alu(is_ext_alu),
        .is_load(is_load),
        .is_store(is_store),
        .is_mov(is_mov),
        .is_branch(is_branch),
        .is_jmp(is_jmp),
        .is_call(is_call),
        .is_ret(is_ret),
        .is_push(is_push),
        .is_pop(is_pop),
        .is_cmp(is_cmp),
        .is_two_word(is_two_word),
        .is_illegal(is_illegal),
        .is_nop(is_nop),
        .is_halt(is_halt),
        .is_ei(is_ei),
        .is_di(is_di),
        .is_reti(is_reti),
        .ext_is_div(ext_is_div),
        .alu_div_busy(alu_div_busy),
        .alu_div_start(alu_div_start),
        .flag_z(flag_z),
        .flag_c(flag_c),
        .flag_n(flag_n),
        .flag_v(flag_v),
        .flag_ie(flag_ie),
        .irq_req(irq_req),
        .irq_index(irq_index),
        .irq_vec_base(irq_vec_base),
        .vector_zero(vector_zero),
        .halt_req(halt_req),
        .step_en(step_en),
        .bus_ack(bus_ack),
        .bus_req(bus_req),
        .bus_we(bus_we),
        .bus_addr_sel(bus_addr_sel),
        .bus_wdata_sel(bus_wdata_sel),
        .pc_inc(pc_inc),
        .pc_load(pc_load),
        .pc_branch(pc_branch),
        .pc_sel(pc_sel),
        .ir_load(ir_load),
        .imm_load(imm_load),
        .reg_wen(reg_wen),
        .reg_wdata_sel(reg_wdata_sel),
        .flag_update_en(flag_update_en),
        .alu_src_b_sel(alu_src_b_sel),
        .sp_dec(sp_dec),
        .sp_inc(sp_inc),
        .ie_set(ie_set),
        .ie_clr(ie_clr),
        .sr_write_en(sr_write_en),
        .irq_ack(irq_ack),
        .illegal_irq(illegal_irq),
        .fault_halt(fault_halt),
        .step_taken(step_taken),
        .vec_latch_en(vec_latch_en),
        .ret_latch_en(ret_latch_en),
        .rd_data_latch_en(rd_data_latch_en),
        .sr_latch_en(sr_latch_en),
        .halted(halted),
        .fsm_state(fsm_state)
    );

endmodule : sv16_core
