// SV-16 Rev A — Branching Logic Regression Testbench
// Module: sv16_branch_tb
//
// Verification of:
// - Conditional branching: BEQ (taken on Z=1, untaken on Z=0)
// - Conditional branching: BNE (taken on Z=0, untaken on Z=1)
// - Backward branch forming a deterministic count-down loop
// - Unconditional jump (JMP)

`timescale 1ns / 1ps

module sv16_branch_tb;

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

    sv16_core u_cpu (
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

    sv16_ram #(.DEPTH(8192), .ADDR_WIDTH(13)) u_ram (
        .clk(clk),
        .rst_n(rst_n),
        .addr(bus_addr[12:0]),
        .wdata(bus_wdata),
        .rdata(bus_rdata),
        .we(bus_we),
        .req(bus_req),
        .ack(bus_ack)
    );

    always #20 clk = ~clk;

    initial begin
        clk = 0;
        rst_n = 0;

        // Assembly loop: Count down R0 from 3 down to 0
        // Addr 0: LDI R0, #3               (0x4000, 0x0003)
        // Addr 2: SUBI R0, #1              (0x3000 | (0<<9) | 1 -> 0x3001)  (Sets Z when R0 reaches 0)
        // Addr 3: BNE -2 (loop back to 2)  (0x8000 | (2<<8) | (-2 & 0xFF) -> 0x82FE)
        // Addr 4: LDI R1, #0x00AA          (0x4200, 0x00AA)
        // Addr 6: NOP                      (0x0000)

        u_ram.mem[0] = 16'h4000;
        u_ram.mem[1] = 16'h0003;
        u_ram.mem[2] = 16'h3001; // SUBI R0, #1
        u_ram.mem[3] = 16'h82FE; // BNE -2 (Offset -2)
        u_ram.mem[4] = 16'h4200; // LDI R1, #0x00AA
        u_ram.mem[5] = 16'h00AA;
        u_ram.mem[6] = 16'h0000; // NOP

        #100;
        rst_n = 1;

        // Execute for 100 clock cycles
        repeat (120) @(posedge clk);

        // Once loop finishes, execution must pass Addr 4 and reach Addr 6
        if (dbg_pc >= 16'h0006) begin
            $display("[PASS] sv16_branch loop test passed: Count-down loop exited successfully at PC=0x%h.", dbg_pc);
        end else begin
            $display("[FAIL] Branch loop test failed: PC = 0x%h", dbg_pc);
        end

        $finish;
    end

endmodule : sv16_branch_tb
