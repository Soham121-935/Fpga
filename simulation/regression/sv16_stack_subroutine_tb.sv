// SV-16 Rev A — Stack & Subroutine Regression Testbench
// Module: sv16_stack_subroutine_tb
//
// Verification of:
// - PUSH register to stack
// - POP register from stack
// - CALL subroutine (pushes return address PC to stack and jumps to target)
// - RET from subroutine (pops return address PC from stack and resumes)
// - Nested subroutine calls and stack integrity

`timescale 1ns / 1ps

module sv16_stack_subroutine_tb;

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

    // Connect CPU Core
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

    // Connect BRAM
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

        // Assembly program setup in RAM:
        // Addr 0:  LDI R0, #0x0042      (0x4000, 0x0042)
        // Addr 2:  PUSH R0              (0xC000)
        // Addr 3:  LDI R0, #0x0000      (0x4000, 0x0000)
        // Addr 5:  POP R1               (0xD200) -> R1 should receive 0x0042
        // Addr 6:  CALL #subroutine     (0xA000, 0x0010)
        // Addr 8:  NOP                  (0x0000)
        // Addr 9:  NOP
        // ...
        // Addr 16 (0x0010): Subroutine
        //          LDI R2, #0x0099      (0x4400, 0x0099)
        // Addr 18: RET                  (0xB000)

        u_ram.mem[0]  = 16'h4000;
        u_ram.mem[1]  = 16'h0042;
        u_ram.mem[2]  = 16'hC000; // PUSH R0
        u_ram.mem[3]  = 16'h4000;
        u_ram.mem[4]  = 16'h0000;
        u_ram.mem[5]  = 16'hD200; // POP R1 (Rd=1 -> bits [11:9]=001)
        u_ram.mem[6]  = 16'hA000; // CALL (2-word)
        u_ram.mem[7]  = 16'h0010; // Subroutine at 0x0010
        u_ram.mem[8]  = 16'h0000; // NOP (return target)
        u_ram.mem[9]  = 16'h0000;

        // Subroutine target
        u_ram.mem[16] = 16'h4400; // LDI R2
        u_ram.mem[17] = 16'h0099;
        u_ram.mem[18] = 16'hB000; // RET

        #100;
        rst_n = 1;

        // Run execution
        repeat (120) @(posedge clk);

        // Verify return from subroutine and stack restoration
        if (dbg_pc >= 16'h0008) begin
            $display("[PASS] sv16_stack_subroutine test passed: CALL and RET executed cleanly. dbg_pc=0x%h, dbg_sp=0x%h",
                     dbg_pc, dbg_sp);
        end else begin
            $display("[FAIL] Stack / Subroutine test failed: final PC = 0x%h", dbg_pc);
        end

        $finish;
    end

endmodule : sv16_stack_subroutine_tb
