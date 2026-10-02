// SV-16 Rev B — Testbench: the control-instruction group (opcode 0x0)
//
// Covers the five CTRL instructions end to end, at all three levels that can
// disagree with each other:
//
//   1. the assembler  -- NOP/HALT/EI/DI/RETI must encode to distinct words
//                        (0x0000/0x0001/0x0002/0x0003/0x0004).  They all
//                        encoded as 0x0000 until scripts/sv16_as.py was fixed,
//                        which is why no firmware could enable interrupts.
//   2. the decoder    -- each word selects exactly its own instruction, and a
//                        reserved CTRL sub-opcode is illegal rather than NOP.
//   3. the core       -- DI/EI really move SR.IE; HALT really stops the core
//                        (PC frozen); an *enabled* interrupt wakes a halted
//                        core into the handler; with SR.IE = 0 the same
//                        request leaves the core halted and pending.
//
// Requires build/fw/control.hex; run from the repository root.

`timescale 1ns / 1ps

import sv16_pkg::*;

module control_tb;

    localparam string PROG_HEX = "build/fw/control.hex";

    // Program addresses (build/fw/control.lst):
    //   0x0000 DI, 0x0001 EI, 0x0002 NOP, 0x0003 HALT
    //   0x0004 DI, 0x0005 EI, 0x0006 DI, 0x0007 HALT, 0x0008 JMP after
    //   0x0020 vector 0 -> 0x0040, handler at 0x0040
    localparam logic [15:0] PHASE1_AFTER = 16'h0004;
    localparam logic [15:0] PHASE2_LO    = 16'h0004;
    localparam logic [15:0] PHASE2_HI    = 16'h0009;
    localparam logic [15:0] HANDLER      = 16'h0040;
    localparam logic [15:0] VEC_BASE     = 16'h0020;

    logic clk = 1'b0;
    always #10 clk = ~clk;

    int cyc = 0;
    always_ff @(posedge clk) cyc++;

    // Counts accepted interrupts: the observable of "the core took it".
    int irq_acks = 0;
    always_ff @(posedge clk) if (irq_ack) irq_acks++;

    // ------------------------------------------------------------ CPU + memory
    logic [15:0] bus_rdata;
    logic        bus_req, bus_we, bus_ack;
    logic [15:0] cpu_bus_addr, cpu_bus_wdata;
    logic [15:0] dbg_pc, dbg_ir, dbg_sr, dbg_sp;
    logic [4:0]  dbg_state;
    logic [2:0]  irq_index;
    logic        irq_ack, irq_req, irq_global_en;
    logic        cpu_halted, cpu_step_taken, cpu_fault_halt, cpu_illegal_irq;
    logic [15:0] cpu_illegal_pc;
    logic [7:0]  irq_lines;
    logic [15:0] irq_rdata;
    logic        irq_ack_bus, irq_bus_req, irq_bus_we;
    logic [3:0]  irq_bus_addr;
    logic [15:0] irq_bus_wdata;
    logic        rst_n;

    sv16_irq_ctrl u_irq (
        .clk(clk), .rst_n(rst_n),
        .addr(irq_bus_addr), .wdata(irq_bus_wdata), .rdata(irq_rdata),
        .req(irq_bus_req), .we(irq_bus_we), .ack(irq_ack_bus),
        .irq_lines(irq_lines), .global_en(irq_global_en),
        .irq_req(irq_req), .irq_index(irq_index),
        .irq_ack(irq_ack)
    );

    sv16_core u_cpu (
        .clk(clk), .rst_n(rst_n),
        .bus_addr(cpu_bus_addr), .bus_wdata(cpu_bus_wdata), .bus_rdata(bus_rdata),
        .bus_req(bus_req), .bus_we(bus_we), .bus_ack(bus_ack),
        .irq_req(irq_req), .irq_index(irq_index),
        .irq_vec_base(VEC_BASE), .irq_ack(irq_ack),
        .halt_req(1'b0), .step_en(1'b0),
        .boot_load(1'b0), .boot_vec(16'h0000), .boot_sp(16'h3FFE),
        .halted(cpu_halted), .step_taken(cpu_step_taken),
        .fault_halt(cpu_fault_halt), .illegal_irq(cpu_illegal_irq),
        .illegal_pc(cpu_illegal_pc),
        .dbg_pc_wr(1'b0), .dbg_pc_val(16'h0000),
        .dbg_sp_wr(1'b0), .dbg_sp_val(16'h0000),
        .dbg_sr_wr(1'b0), .dbg_sr_val(16'h0000),
        .dbg_pc(dbg_pc), .dbg_ir(dbg_ir), .dbg_sr(dbg_sr), .dbg_sp(dbg_sp),
        .dbg_state(dbg_state)
    );

    sv16_ram #(.DEPTH(16384), .ADDR_WIDTH(14), .INIT_FILE(PROG_HEX)) u_ram (
        .clk(clk), .rst_n(rst_n),
        .addr(cpu_bus_addr[13:0]), .wdata(cpu_bus_wdata), .rdata(bus_rdata),
        .we(bus_we), .req(bus_req), .ack(bus_ack)
    );

    // ------------------------------------------------ decoder under test (level 2)
    logic [3:0] dec_opcode;
    logic [2:0] dec_subop;
    logic [8:0] dec_ctrl_subop;
    logic       dec_illegal, dec_nop, dec_halt, dec_ei, dec_di, dec_reti;
    logic [15:0] dec_instr;

    sv16_decoder u_dec (
        .instr(dec_instr), .opcode(dec_opcode), .subop(dec_subop),
        .ctrl_subop(dec_ctrl_subop), .is_illegal(dec_illegal),
        .is_nop(dec_nop), .is_halt(dec_halt), .is_ei(dec_ei), .is_di(dec_di),
        .is_reti(dec_reti)
    );

    // ------------------------------------------------------------------ helpers
    int checks = 0, errors = 0;

    task automatic check(input bit cond, input string name);
        begin
            checks++;
            if (cond) $display("  [PASS] %s", name);
            else begin
                errors++;
                $display("  [FAIL] %s", name);
            end
        end
    endtask

    task automatic reg_write(input logic [3:0] a, input logic [15:0] d);
        begin
            @(negedge clk);
            irq_bus_addr = a; irq_bus_wdata = d;
            irq_bus_we = 1'b1; irq_bus_req = 1'b1;
            @(posedge clk); #1;
            irq_bus_req = 1'b0; irq_bus_we = 1'b0;
        end
    endtask

    task automatic reg_read(input logic [3:0] a, output logic [15:0] d);
        begin
            @(negedge clk);
            irq_bus_addr = a; irq_bus_we = 1'b0; irq_bus_req = 1'b1;
            @(posedge clk); #1;
            d = irq_rdata;
            irq_bus_req = 1'b0;
        end
    endtask

    // Wait for the core to report S_HALTED, sampling at the clock edge.
    task automatic wait_halted(output bit ok, input int limit);
        int n;
        begin
            ok = 1'b0; n = 0;
            while (!ok && (n < limit)) begin
                @(posedge clk); #1;
                ok = cpu_halted;
                n++;
            end
        end
    endtask

    // ------------------------------------------------------------------ stimulus
    logic [15:0] pend;
    int          phase;
    bit          halted_ok, pc_frozen;
    logic [15:0] pc_before, pc_after;

    initial begin
        rst_n         = 1'b0;
        irq_lines     = 8'h00;
        irq_global_en = 1'b1;              // SYS_CTRL.IRQEN, set once by the OS
        irq_bus_req   = 1'b0;
        irq_bus_we    = 1'b0;
        irq_bus_addr  = 4'h0;
        irq_bus_wdata = 16'h0000;
        dec_instr     = 16'h0000;

        $display("== SV-16 control instructions (opcode 0x0) ==");

        // ---------------------------------------------------------- level 1: encoder
        $display("-- 1. the assembler must emit five distinct words --");
        check(u_ram.mem[16'h0000] === 16'h0003, "DI   assembles to 0x0003");
        check(u_ram.mem[16'h0001] === 16'h0002, "EI   assembles to 0x0002");
        check(u_ram.mem[16'h0002] === 16'h0000, "NOP  assembles to 0x0000");
        check(u_ram.mem[16'h0003] === 16'h0001, "HALT assembles to 0x0001");
        check(u_ram.mem[16'h0020] === 16'h0040, "the vector table holds the handler address");

        // ---------------------------------------------------------- level 2: decoder
        $display("-- 2. the decoder must select exactly one instruction --");
        dec_instr = 16'h0000; #1;
        check(dec_nop && !dec_illegal, "0x0000 decodes as NOP");
        dec_instr = 16'h0001; #1;
        check(dec_halt && !dec_illegal, "0x0001 decodes as HALT");
        dec_instr = 16'h0002; #1;
        check(dec_ei && !dec_illegal, "0x0002 decodes as EI");
        dec_instr = 16'h0003; #1;
        check(dec_di && !dec_illegal, "0x0003 decodes as DI");
        dec_instr = 16'h0004; #1;
        check(dec_reti && !dec_illegal, "0x0004 decodes as RETI");
        dec_instr = 16'h0005; #1;
        check(dec_illegal && !dec_nop && !dec_halt,
              "a reserved CTRL sub-opcode (0x0005) is illegal, not NOP");
        dec_instr = 16'h0000; #1;

        // ---------------------------------------------------------- level 3: the core
        repeat (8) @(posedge clk);
        rst_n = 1'b1;
        repeat (4) @(posedge clk);
        reg_write(4'h0, 16'h0001);         // IRQ_EN: source 0 (not yet pending)

        $display("-- 3. phase 1: DI, EI, NOP, HALT -> SR.IE = 1, core stopped --");
        wait_halted(halted_ok, 4000);
        check(halted_ok, "the HALT instruction stopped the core");
        check(dbg_sr[7] === 1'b1, "EI set SR.IE (and the earlier DI did not win)");
        check(dbg_pc === PHASE1_AFTER,
              $sformatf("HALT stopped with PC at the next instruction (0x%04X)", dbg_pc));

        pc_before = dbg_pc; pc_frozen = 1'b1;
        repeat (20) begin
            @(posedge clk); #1;
            if (dbg_pc !== pc_before) pc_frozen = 1'b0;
        end
        check(pc_frozen, "the halted core does not advance (PC frozen for 20 clocks)");

        $display("-- 4. an enabled interrupt wakes the halted core --");
        irq_lines = 8'h01;                 // rising edge -> pending
        begin
            int n; bit reached;
            reached = 1'b0; n = 0;
            while (!reached && (n < 4000)) begin
                @(posedge clk); #1;
                reached = (dbg_pc === HANDLER);
                n++;
            end
            check(reached, "the halted core entered the handler");
        end
        irq_lines = 8'h00;

        begin
            int n; bit resumed; logic [15:0] resumed_at;
            resumed = 1'b0; resumed_at = 16'hFFFF; n = 0;
            while (!resumed && (n < 4000)) begin
                @(posedge clk); #1;
                if ((dbg_pc >= PHASE2_LO) && (dbg_pc <= PHASE2_HI) && !resumed) begin
                    resumed    = 1'b1;
                    resumed_at = dbg_pc;
                end
                n++;
            end
            check(resumed && (resumed_at === PHASE2_LO),
                  $sformatf("RETI returned to the instruction after HALT (0x%04X)", resumed_at));
        end
        check(u_cpu.u_regfile.registers[7] === 16'h00A5,
              $sformatf("the handler ran (R7 = 0x%04X)", u_cpu.u_regfile.registers[7]));
        check(dbg_sp === 16'h3FFE, "the entry/return left SP balanced");
        check(irq_acks == 1, "exactly one interrupt has been accepted so far");

        $display("-- 5. phase 2: DI, EI, DI, HALT -> SR.IE = 0 --");
        wait_halted(halted_ok, 4000);
        check(halted_ok, "the second HALT stopped the core again");
        check(dbg_sr[7] === 1'b0,
              $sformatf("DI cleared SR.IE (dbg_sr = 0x%04X)", dbg_sr));

        $display("-- 6. with SR.IE = 0 the same request must not wake it --");
        pc_before = dbg_pc;
        irq_lines = 8'h01;                 // fresh rising edge, still disabled
        repeat (200) begin
            @(posedge clk); #1;
        end
        check(cpu_halted === 1'b1, "the core is still halted");
        check(dbg_pc === pc_before,
              $sformatf("the core did not move (PC still 0x%04X)", dbg_pc));
        check(irq_acks == 1, "the core never accepted the masked interrupt");
        check(irq_req === 1'b1, "the controller is still asking (request is not lost)");
        reg_read(4'h1, pend);
        check(pend[0] === 1'b1,
              $sformatf("the request is still pending (IRQ_PEND = 0x%04X)", pend));
        irq_lines = 8'h00;

        $display("== SV-16 control instructions: %0d checks, %0d failures ==", checks, errors);
        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL");
        $finish;
    end

    initial begin
        repeat (200_000) @(posedge clk);
        $display("  [FAIL] the suite timed out");
        $display("RESULT: FAIL");
        $finish;
    end

endmodule
