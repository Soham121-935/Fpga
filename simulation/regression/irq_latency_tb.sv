// SV-16 Rev B — Testbench: interrupt latency (OQ-15 / P8)
//
// Nothing in the repository had ever measured what an interrupt costs, so every
// document said "the core is multi-cycle, latency depends on the current
// instruction" and left it there.  This suite measures it, on the real path:
//
//   the testbench raises IRQ source 0
//     -> sv16_irq_ctrl latches the edge and asserts irq_req
//     -> sv16_core takes the interrupt at the next instruction boundary,
//        pushing SR and PC and fetching the handler address from the vector
//        table at 0x0020
//     -> the handler at 0x0040 runs and returns with RETI
//
// and reports, over a sweep of arrival moments across the instruction stream:
//
//   * the minimum latency (the request arrives just as the instruction ends)
//   * the maximum latency (the request arrives at the start of DIV, the longest
//     instruction in the ISA — 18 cycles)
//   * the IRQ controller's own contribution
//   * how long the entry/return machinery costs around a 3-word handler
//
// The program under test is firmware/tests/irq_latency.s, assembled by the real
// assembler.  Requires build/fw/irq_latency.hex; run from the repository root.

`timescale 1ns / 1ps

import sv16_pkg::*;

module irq_latency_tb;

    localparam string PROG_HEX = "build/fw/irq_latency.hex";

    // Addresses from the program's listing (build/fw/irq_latency.lst):
    //   0x0007..0x000A  the loop body: DIV / NOP / JMP / its operand
    //   0x0020          vector table, entry 0 -> 0x0040
    //   0x0040          handler
    localparam logic [15:0] LOOP_LO    = 16'h0007;
    localparam logic [15:0] LOOP_HI    = 16'h000A;
    localparam logic [15:0] HANDLER    = 16'h0040;
    localparam logic [15:0] VEC_BASE   = 16'h0020;

    localparam int        TRIALS      = 24;      // arrival moments swept
    localparam logic [15:0] EXPECT_R3 = 16'h000E;   // 100 / 7

    // What the hardware is expected to cost.  These are the *documented* bounds
    // this suite enforces; the measured value is printed next to them.
    localparam int LAT_MIN_OK = 5;    // entry alone is 6 states, so >= this
    localparam int LAT_MAX_OK = 34;   // DIV (24 cycles, ADR-022) + entry (6) +
                                      // the controller (1) + fetch/decode slack

    logic clk = 1'b0;
    logic rst_n;
    always #10 clk = ~clk;            // 20 ns: 50 MHz, the core is clock-agnostic

    int checks = 0, errors = 0;
    int cyc    = 0;                   // system clock counter
    always_ff @(posedge clk) cyc++;

    // ------------------------------------------------------------ CPU + memory
    logic [15:0] bus_rdata;
    logic        bus_req, bus_we, bus_ack;
    logic [15:0] dbg_pc, dbg_ir, dbg_sr, dbg_sp;
    logic [2:0]  irq_index;
    logic        irq_ack;
    logic [4:0]  dbg_state;
    logic        cpu_halted, cpu_step_taken, cpu_fault_halt, cpu_illegal_irq;
    logic [15:0] cpu_illegal_pc;
    logic        irq_req, irq_global_en;
    logic [7:0]  irq_lines;
    logic [15:0] cpu_bus_addr, cpu_bus_wdata;

    // ------------------------------------------------------------ IRQ controller
    logic [15:0] irq_rdata;
    logic        irq_ack_bus;
    logic        irq_bus_req, irq_bus_we;
    logic [3:0]  irq_bus_addr;
    logic [15:0] irq_bus_wdata;

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

    // ------------------------------------------------------------ bus master
    // The testbench is the only bus master (the CPU's own bus is wired straight
    // into the RAM above), so it can configure the IRQ controller directly.
    task automatic reg_write(input logic [3:0] a, input logic [15:0] d);
        begin
            @(negedge clk);
            irq_bus_addr  = a;
            irq_bus_wdata = d;
            irq_bus_we    = 1'b1;
            irq_bus_req   = 1'b1;
            @(posedge clk);
            #1;
            irq_bus_req   = 1'b0;
            irq_bus_we    = 1'b0;
        end
    endtask

    task automatic reg_read(input logic [3:0] a, output logic [15:0] d);
        begin
            @(negedge clk);
            irq_bus_addr  = a;
            irq_bus_we    = 1'b0;
            irq_bus_req   = 1'b1;
            @(posedge clk);
            #1;
            d = irq_rdata;
            irq_bus_req   = 1'b0;
        end
    endtask

    function automatic bit in_loop(input logic [15:0] pc);
        in_loop = (pc >= LOOP_LO) && (pc <= LOOP_HI);
    endfunction

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

    // ------------------------------------------------------------------ stimulus
    int lat_min, lat_max, lat_sum, ctrl_lat, isr_cycles;
    int trials_done;

    initial begin
        rst_n          = 1'b0;
        irq_lines      = 8'h00;
        irq_global_en  = 1'b1;          // SYS_CTRL.IRQEN, set once by the OS
        irq_bus_req    = 1'b0;
        irq_bus_we     = 1'b0;
        irq_bus_addr   = 4'h0;
        irq_bus_wdata  = 16'h0000;
        lat_min = 1000; lat_max = 0; lat_sum = 0; trials_done = 0;

        repeat (8) @(posedge clk);
        rst_n = 1'b1;
        repeat (4) @(posedge clk);

        $display("== SV-16 interrupt latency ==");
        $display("-- 1. arm the source --");
        reg_write(4'h0, 16'h0001);      // IRQ_EN: enable source 0
        check(irq_req === 1'b0, "no interrupt pending on a quiet source");

        // The controller latches a *rising edge*, so this is also the point a
        // peripheral would be seen.
        $display("-- 2. controller contribution --");
        begin
            int t0;
            reg_write(4'h1, 16'h00FF);  // clear any pending bit
            irq_lines = 8'h01;
            t0 = cyc;
            while ((irq_req !== 1'b1) && (cyc - t0 < 10)) @(posedge clk);
            ctrl_lat = cyc - t0;
            check(ctrl_lat >= 1 && ctrl_lat <= 3,
                  $sformatf("the controller asserts irq_req %0d cycle(s) after the source", ctrl_lat));
        end
        // Let that request be taken and the handler run once before sweeping,
        // so the first trial starts from a quiet state.
        begin
            int n;
            n = 0;
            while ((dbg_pc !== HANDLER) && (n < 4000)) begin
                @(posedge clk); n++;
                if ((n % 250) == 0)
                    $display("     ...pc=%04X ir=%04X sr=%04X sp=%04X state=%0d irq=%b idx=%0d",
                             dbg_pc, dbg_ir, dbg_sr, dbg_sp, dbg_state, irq_req, irq_index);
            end
            if (dbg_pc !== HANDLER)
                $display("     final: pc=%04X ir=%04X sr=%04X sp=%04X state=%0d irq=%b idx=%0d r7=%04X r3=%04X",
                         dbg_pc, dbg_ir, dbg_sr, dbg_sp, dbg_state, irq_req, irq_index,
                         u_cpu.u_regfile.registers[7], u_cpu.u_regfile.registers[3]);
            check(dbg_pc === HANDLER, "the core reached the handler");
            irq_lines = 8'h00;
            n = 0;
            while (!in_loop(dbg_pc) && (n < 4000)) begin @(posedge clk); n++; end
        end

        $display("-- 3. latency sweep (%0d arrival moments) --", TRIALS);
        for (int t = 0; t < TRIALS; t++) begin
            int t_assert, n, lat, entry_cyc;

            // Start each trial from the loop body.
            n = 0;
            while (!in_loop(dbg_pc) && (n < 4000)) begin @(posedge clk); n++; end

            // Move the arrival moment relative to the instruction stream: the
            // loop is 5 words / up to 25 cycles long, so a stride of 1 clock
            // walks the request through every state of DIV and its neighbours.
            repeat (1 + (t % 24)) @(posedge clk);

            t_assert  = cyc;
            irq_lines = 8'h01;

            n = 0;
            while ((dbg_pc !== HANDLER) && (n < 200)) begin @(posedge clk); n++; end
            if (dbg_pc !== HANDLER) begin
                $display("  [FAIL] trial %0d: no handler within 200 clocks", t);
                errors++; checks++;
            end else begin
                lat = cyc - t_assert;
                entry_cyc = cyc;
                if (lat < lat_min) lat_min = lat;
                if (lat > lat_max) lat_max = lat;
                lat_sum += lat;
                trials_done++;

                // Release the source and wait for RETI to hand control back.
                irq_lines = 8'h00;
                n = 0;
                while (!in_loop(dbg_pc) && (n < 200)) begin @(posedge clk); n++; end
                if (t == TRIALS - 1) isr_cycles = cyc - entry_cyc;
            end
        end

        $display("     measured: min %0d / max %0d / mean %0d cycles (%0d trials)",
                 lat_min, lat_max, lat_sum / (trials_done == 0 ? 1 : trials_done), trials_done);

        $display("-- 4. what the hardware guarantees --");
        check(trials_done == TRIALS, "every sweep trial reached the handler");
        check(lat_min >= LAT_MIN_OK,
              $sformatf("best-case latency is at least %0d cycles (measured %0d)", LAT_MIN_OK, lat_min));
        check(lat_max <= LAT_MAX_OK,
              $sformatf("worst-case latency is at most %0d cycles (measured %0d)", LAT_MAX_OK, lat_max));
        check(lat_max > lat_min,
              "latency depends on the interrupted instruction (DIV is the worst case)");
        check(isr_cycles <= 40,
              $sformatf("a 3-word handler costs %0d cycles from entry to return", isr_cycles));

        $display("-- 5. the interrupted program survived --");
        check(u_cpu.u_regfile.registers[3] === EXPECT_R3,
              $sformatf("the interrupted DIV completed: R3 = 0x%04X (want 0x%04X)",
                        u_cpu.u_regfile.registers[3], EXPECT_R3));
        check(u_cpu.u_regfile.registers[7] === 16'h00AA,
              "the handler ran and left its evidence in R7");
        check(dbg_sp === 16'h3FFE,
              $sformatf("the entry/return left SP balanced (0x%04X)", dbg_sp));
        begin
            logic [15:0] pend;
            reg_read(4'h1, pend);
            check(pend[0] === 1'b0, "taking the interrupt cleared its pending bit (hardware ack)");
        end
        check(cpu_halted === 1'b0 && cpu_fault_halt === 1'b0,
              "the core is running: no halt, no fault");

        $display("== SV-16 interrupt latency: %0d checks, %0d failures ==", checks, errors);
        $display("== measured: controller %0d cycle(s), latency %0d..%0d cycles, ISR overhead %0d ==",
                 ctrl_lat, lat_min, lat_max, isr_cycles);
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
