// SV-16 Rev B — Regression: ISA-level instruction behaviour
//                 (`firmware/tests/isa_regress.s`)
//
// The program suites (soc_boot, monitor, watchdog) run real firmware, but they
// only ever execute the branch paths their own code happens to take.  This suite
// runs the CPU core on the RAM alone, with a program that walks *every*
// conditional branch through the flag combination that makes it taken and the
// one that makes it fall through, then calls a subroutine and checks the stack
// came back balanced.
//
// The program is assembled by the real assembler (`make firmware`), so what runs
// here is what a developer would write; the testbench only reads the CPU's
// debug port and the RAM.
//
//   1. the core starts at the image entry with the image's stack pointer
//   2. every conditional branch takes the right path (trace bits in R7)
//   3. ADDI/SUBI produce the right values, including a negative immediate (R5)
//      -- these two instructions are the reason this suite exists: their result
//      used to be committed from a re-evaluated ALU (ADR-020)
//   4. PUSH/POP round-trips through the stack (R2)
//   5. the subroutine returns the right value and restores the caller's register
//   6. CALL/PUSH/POP leave the stack pointer exactly where it started
//   7. the program reaches its self-loop and stays there (no runaway PC)

`timescale 1ns / 1ps

module isa_tb;

    logic        clk = 1'b0;
    always #10 clk = ~clk;          // 50 MHz

    localparam string ISA_HEX = "build/fw/isa_regress.hex";
    localparam logic [15:0] RESET_SP = 16'h3FFE;

    logic        rst_n;
    logic [15:0] bus_addr, bus_wdata, bus_rdata;
    logic        bus_req, bus_we, bus_ack;
    logic [15:0] dbg_pc, dbg_ir, dbg_sr, dbg_sp;
    logic [4:0]  dbg_state;

    int          checks = 0, errors = 0;

    sv16_core u_cpu (
        .clk(clk), .rst_n(rst_n),
        .bus_addr(bus_addr), .bus_wdata(bus_wdata), .bus_rdata(bus_rdata),
        .bus_req(bus_req), .bus_we(bus_we), .bus_ack(bus_ack),
        .irq_req(1'b0), .irq_index(3'd0), .irq_vec_base(16'h0020),
        .irq_ack(),
        .halt_req(1'b0), .step_en(1'b0),
        .boot_load(1'b0), .boot_vec(16'h0000), .boot_sp(RESET_SP),
        .halted(), .step_taken(), .fault_halt(), .illegal_irq(), .illegal_pc(),
        .dbg_pc_wr(1'b0), .dbg_pc_val(16'h0),
        .dbg_sp_wr(1'b0), .dbg_sp_val(16'h0),
        .dbg_sr_wr(1'b0), .dbg_sr_val(16'h0),
        .dbg_pc(dbg_pc), .dbg_ir(dbg_ir), .dbg_sr(dbg_sr), .dbg_sp(dbg_sp),
        .dbg_state(dbg_state)
    );

    sv16_ram #(.DEPTH(16384), .ADDR_WIDTH(14), .INIT_FILE(ISA_HEX)) u_ram (
        .clk(clk), .rst_n(rst_n),
        .addr(bus_addr[13:0]), .wdata(bus_wdata), .rdata(bus_rdata),
        .we(bus_we), .req(bus_req), .ack(bus_ack)
    );

    task automatic check(input bit cond, input string msg);
        begin
            checks++;
            if (cond) $display("  [PASS] %s", msg);
            else begin
                errors++;
                $display("  [FAIL] %s", msg);
            end
        end
    endtask

    // Run for up to `max` clocks and stop as soon as the PC has been unchanged
    // for `settle` clocks: the program ends in a `JMP self` loop, which is the
    // only way to stop on a machine with no HALT instruction.
    task automatic run_until_settled(input int max, input int settle);
        logic [15:0] last;
        int quiet, i;
        begin
            last = 16'hFFFF;
            quiet = 0;
            i = 0;
            while ((quiet < settle) && (i < max)) begin
                @(posedge clk);
                #1;
                if (dbg_pc === last) quiet++;
                else begin
                    quiet = 0;
                    last  = dbg_pc;
                end
                i++;
            end
            $display("    (%0d clocks, stopped at PC=0x%04X, SP=0x%04X, R7=0x%04X)",
                     i, dbg_pc, dbg_sp, u_cpu.u_regfile.registers[7]);
        end
    endtask

    initial begin
        rst_n = 1'b0;
        repeat (8) @(posedge clk);   // hold reset; the core must be parked at 0
        #1;

        $display("== SV-16 ISA regression ==");

        // ---- 1. boot state ------------------------------------------------
        // Sampled while reset is still asserted: four clocks after release the
        // PC has already walked past the first NOPs, so the entry point can
        // only be observed here.
        $display("-- 1. reset state --");
        check(dbg_pc === 16'h0000, $sformatf("the core resets to the image entry (PC = 0x%04X)",
                                            dbg_pc));
        check(dbg_sp === RESET_SP, $sformatf("stack pointer starts at 0x%04X", RESET_SP));

        rst_n = 1'b1;
        repeat (4) @(posedge clk);

        // ---- 2..5 run the program -----------------------------------------
        $display("-- 2. run firmware/tests/isa_regress.s --");
        run_until_settled(4000, 20);

        check(u_cpu.u_regfile.registers[7] === 16'h00FF,
              $sformatf("every branch took the right path (R7 = 0x%04X, want 0x00FF)",
                        u_cpu.u_regfile.registers[7]));
        check(u_cpu.u_regfile.registers[5] === 16'h00FF,
              $sformatf("the ADDI/SUBI chain landed on 0x00FF (R5 = 0x%04X)",
                        u_cpu.u_regfile.registers[5]));
        check(u_cpu.u_regfile.registers[2] === 16'h0003,
              $sformatf("PUSH/POP round-tripped the value (R2 = 0x%04X)",
                        u_cpu.u_regfile.registers[2]));
        check(u_cpu.u_regfile.registers[6] === 16'h002A,
              $sformatf("the subroutine returned 21*2 = 42 (R6 = 0x%04X)",
                        u_cpu.u_regfile.registers[6]));
        check(u_cpu.u_regfile.registers[0] === 16'h0055,
              $sformatf("the subroutine left the caller's R0 intact (R0 = 0x%04X, want 0x0055)",
                        u_cpu.u_regfile.registers[0]));
        check(dbg_sp === RESET_SP,
              $sformatf("CALL/PUSH/POP left SP balanced (0x%04X)", dbg_sp));

        // The self-loop is `JMP` to itself, and JMP carries its target in a
        // second word -- so the PC cycles through a handful of adjacent
        // addresses rather than standing still.  A runaway PC would keep
        // walking; a parked one stays inside one instruction's worth of words.
        begin
            logic [15:0] lo, hi;
            lo = dbg_pc;
            hi = dbg_pc;
            repeat (60) begin
                @(posedge clk);
                #1;
                if (dbg_pc < lo) lo = dbg_pc;
                if (dbg_pc > hi) hi = dbg_pc;
            end
            check((hi - lo) <= 16'd3,
                  $sformatf("the program is parked in its self-loop (PC window 0x%04X..0x%04X)",
                            lo, hi));
        end

        $display("== SV-16 ISA regression: %0d checks, %0d failures ==", checks, errors);
        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL");
        $finish;
    end

    initial begin
        #500_000;
        $display("RESULT: FAIL (timeout)");
        $finish;
    end

endmodule
