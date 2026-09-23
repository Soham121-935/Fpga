// SV-16 Rev A — Minimal CPU Core
// Module: sv16_core
//
// Integrates:
// - sv16_pc           (Program Counter)
// - sv16_decoder      (Instruction Decoder)
// - sv16_regfile      (8 x 16-bit Register File)
// - sv16_alu          (16-bit ALU)
// - sv16_status_reg   (Status Register Z, C, N, V, IE)
// - sv16_control_unit (Multi-cycle execution FSM)
// - System Bus Master Interface

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

    // Core Debug & Observability
    output logic [15:0] dbg_pc,
    output logic [15:0] dbg_ir,
    output logic [15:0] dbg_sr,
    output logic [15:0] dbg_sp,
    output logic [2:0]  dbg_state
);

    // Internal Registers
    logic [15:0] ir_reg;
    logic [15:0] imm_reg;
    logic [15:0] sp_reg;

    // Interconnect wires
    logic [15:0] pc_val;
    assign dbg_pc = pc_val;
    assign dbg_ir = ir_reg;
    assign dbg_sp = sp_reg;

    // Decoder outputs
    logic [3:0]  opcode;
    logic [2:0]  dec_rd;
    logic [2:0]  dec_rs1;
    logic [2:0]  dec_rs2;
    logic [2:0]  subop;
    logic [3:0]  cond;
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

    // Control Unit outputs
    logic        bus_addr_sel;
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
    logic [2:0]  fsm_state;

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

    // Stack Pointer register
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sp_reg <= 16'h1FFE; // Top of internal data RAM per ADR-007
        end else if (sp_dec) begin
            sp_reg <= sp_reg - 16'd1;
        end else if (sp_inc) begin
            sp_reg <= sp_reg + 16'd1;
        end
    end

    // Instruction Register and Immediate Register
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ir_reg  <= 16'h0000; // NOP
            imm_reg <= 16'h0000;
        end else begin
            if (ir_load)  ir_reg  <= bus_rdata;
            if (imm_load) imm_reg <= bus_rdata;
        end
    end

    // Bus address multiplexer
    assign bus_addr = (bus_addr_sel == 1'b0) ? pc_val :
                      (is_push || is_pop || is_call || is_ret) ? sp_reg : effective_addr;

    // Bus write data multiplexer
    assign bus_wdata = (is_call) ? pc_val : (is_push) ? reg_rdata1 : reg_rdata2;

    // Target address for PC direct load
    logic [15:0] pc_target;
    assign pc_target = (is_ret) ? bus_rdata : imm_reg;

    // Program Counter Instance
    sv16_pc u_pc (
        .clk(clk),
        .rst_n(rst_n),
        .pc_inc(pc_inc),
        .pc_load(pc_load),
        .pc_branch(pc_branch),
        .target_addr(pc_target),
        .branch_offset(branch_offset),
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
        .is_illegal(is_illegal)
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
    assign effective_alu_op = (is_alu_imm) ? ((opcode == 4'h2) ? 3'b000 : 3'b001) : subop;

    // ALU Instance
    sv16_alu u_alu (
        .a(alu_in_a),
        .b(alu_in_b),
        .alu_op(effective_alu_op),
        .is_extended(is_ext_alu),
        .result(alu_result),
        .flag_z(alu_flag_z),
        .flag_c(alu_flag_c),
        .flag_n(alu_flag_n),
        .flag_v(alu_flag_v)
    );

    // Status Register Instance
    sv16_status_reg u_status_reg (
        .clk(clk),
        .rst_n(rst_n),
        .flag_z_in(alu_flag_z),
        .flag_c_in(alu_flag_c),
        .flag_n_in(alu_flag_n),
        .flag_v_in(alu_flag_v),
        .flag_update_en(flag_update_en),
        .sr_write_en(1'b0),
        .sr_write_data(16'h0000),
        .ie_set(1'b0),
        .ie_clr(1'b0),
        .sr_out(sr_val),
        .flag_z(flag_z),
        .flag_c(flag_c),
        .flag_n(flag_n),
        .flag_v(flag_v),
        .flag_ie(flag_ie)
    );

    // Register Writeback Multiplexer
    always_comb begin
        case (reg_wdata_sel)
            2'b00: reg_wdata = (is_mov) ? reg_rdata1 : alu_result;
            2'b01: reg_wdata = bus_rdata;
            2'b10: reg_wdata = imm_reg; // 16-bit immediate from LDI
            2'b11: reg_wdata = pc_val;
            default: reg_wdata = alu_result;
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
        .flag_z(flag_z),
        .flag_c(flag_c),
        .flag_n(flag_n),
        .flag_v(flag_v),
        .bus_ack(bus_ack),
        .bus_req(bus_req),
        .bus_we(bus_we),
        .bus_addr_sel(bus_addr_sel),
        .pc_inc(pc_inc),
        .pc_load(pc_load),
        .pc_branch(pc_branch),
        .ir_load(ir_load),
        .imm_load(imm_load),
        .reg_wen(reg_wen),
        .reg_wdata_sel(reg_wdata_sel),
        .flag_update_en(flag_update_en),
        .alu_src_b_sel(alu_src_b_sel),
        .sp_dec(sp_dec),
        .sp_inc(sp_inc),
        .fsm_state(fsm_state)
    );

endmodule : sv16_core
