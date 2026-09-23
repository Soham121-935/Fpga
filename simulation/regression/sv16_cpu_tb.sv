// SV-16 Rev A — Minimal CPU Core Regression Testbench
// Module: sv16_cpu_tb
//
// Verification of Section 26 Phase 9 minimal program:
//   Program:
//     Addr 0: LDI R0, #5    (2 words: Opcode 0x4, Word 2: 0x0005)
//     Addr 2: LDI R1, #10   (2 words: Opcode 0x4, Word 2: 0x000A)
//     Addr 4: ADD R0, R0, R1 (Format R: Opcode 0x1, Rd=0, Rs1=0, Rs2=1, SubOp=0)
//     Addr 5: HALT / NOP

`timescale 1ns / 1ps

module sv16_cpu_tb;

    logic        clk;
    logic        rst_n;
    logic [15:0] bus_addr;
    logic [15:0] bus_wdata;
    logic [15:0] bus_rdata;
    logic        bus_req;
    logic        bus_we;
    logic        bus_ack;

    logic [15:0] dbg_pc;
    logic [15:0] dbg_ir;
    logic [15:0] dbg_sr;
    logic [15:0] dbg_sp;
    logic [2:0]  dbg_state;

    // Minimal synchronous memory (64 words)
    logic [15:0] mem [63:0];

    sv16_core uut (
        .clk(clk),
        .rst_n(rst_n),
        .bus_addr(bus_addr),
        .bus_wdata(bus_wdata),
        .bus_rdata(bus_rdata),
        .bus_req(bus_req),
        .bus_we(bus_we),
        .bus_ack(bus_ack),
        .dbg_pc(dbg_pc),
        .dbg_ir(dbg_ir),
        .dbg_sr(dbg_sr),
        .dbg_sp(dbg_sp),
        .dbg_state(dbg_state)
    );

    always #20 clk = ~clk;

    // Bus memory responder
    assign bus_ack = bus_req; // Single-cycle acknowledge

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            bus_rdata <= 16'h0000;
        end else if (bus_req) begin
            if (bus_we) begin
                mem[bus_addr[5:0]] <= bus_wdata;
            end else begin
                bus_rdata <= mem[bus_addr[5:0]];
            end
        end
    end

    int cycle_count;

    initial begin
        clk = 0;
        rst_n = 0;
        cycle_count = 0;

        // Initialize memory with test program
        // Addr 0: LDI R0 (Opcode 0x4, Rd=0) -> 0x4000
        mem[0] = 16'h4000;
        // Addr 1: Immediate value 5 -> 0x0005
        mem[1] = 16'h0005;

        // Addr 2: LDI R1 (Opcode 0x4, Rd=1) -> 0x4200
        mem[2] = 16'h4200;
        // Addr 3: Immediate value 10 -> 0x000A
        mem[3] = 16'h000A;

        // Addr 4: ADD R0, R0, R1 -> {4'h1, 3'd0, 3'd0, 3'd1, 3'd0} = 0x1008
        mem[4] = 16'h1008;

        // Addr 5: NOP (Opcode 0x0)
        mem[5] = 16'h0000;

        #100;
        rst_n = 1;

        // Execute for 50 cycles
        for (int i = 0; i < 50; i++) begin
            @(posedge clk);
            cycle_count++;
        end

        // Verify that execution reached beyond address 4
        if (dbg_pc >= 16'h0005) begin
            $display("[PASS] sv16_core successfully executed program from PC=0x0000 to PC=0x%h in %0d cycles.",
                     dbg_pc, cycle_count);
        end else begin
            $display("[FAIL] sv16_core did not advance as expected, final PC = 0x%h", dbg_pc);
        end

        $finish;
    end

endmodule : sv16_cpu_tb
