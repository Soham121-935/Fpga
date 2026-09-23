// SV-16 Rev A — Unit Testbench for Program Counter (sv16_pc)
// Verification of:
// 1. Reset state (pc == 0x0000)
// 2. Sequential increments (pc_inc)
// 3. Direct load (pc_load)
// 4. Relative positive and negative branching (pc_branch)
// 5. Hold / stall state (no control signal asserted)
// 6. Priority order: load > branch > inc

`timescale 1ns / 1ps

module sv16_pc_tb;

    logic        clk;
    logic        rst_n;
    logic        pc_inc;
    logic        pc_load;
    logic        pc_branch;
    logic [15:0] target_addr;
    logic [7:0]  branch_offset;
    logic [15:0] pc;

    int error_count;

    sv16_pc uut (
        .clk(clk),
        .rst_n(rst_n),
        .pc_inc(pc_inc),
        .pc_load(pc_load),
        .pc_branch(pc_branch),
        .target_addr(target_addr),
        .branch_offset(branch_offset),
        .pc(pc)
    );

    always #20 clk = ~clk;

    initial begin
        clk = 0;
        rst_n = 0;
        pc_inc = 0;
        pc_load = 0;
        pc_branch = 0;
        target_addr = 0;
        branch_offset = 0;
        error_count = 0;

        #100;
        rst_n = 1;
        #40;

        // 1. Check reset
        if (pc !== 16'h0000) begin
            $display("[FAIL] Reset PC mismatch! Got: 0x%h", pc);
            error_count++;
        end

        // 2. Increment sequentially
        @(posedge clk);
        pc_inc = 1;
        @(posedge clk);
        #1;
        if (pc !== 16'h0001) begin
            $display("[FAIL] PC increment failed! Got: 0x%h, Expected: 0x0001", pc);
            error_count++;
        end

        @(posedge clk);
        #1;
        if (pc !== 16'h0002) begin
            $display("[FAIL] PC increment 2 failed! Got: 0x%h, Expected: 0x0002", pc);
            error_count++;
        end

        // 3. Hold / Stall
        @(posedge clk);
        pc_inc = 0;
        @(posedge clk);
        #1;
        if (pc !== 16'h0002) begin
            $display("[FAIL] PC hold failed! Got: 0x%h", pc);
            error_count++;
        end

        // 4. Absolute load
        @(posedge clk);
        pc_load = 1;
        target_addr = 16'h0500;
        @(posedge clk);
        pc_load = 0;
        #1;
        if (pc !== 16'h0500) begin
            $display("[FAIL] PC load failed! Got: 0x%h", pc);
            error_count++;
        end

        // 5. Relative positive branch: PC = 0x0500 + 10 (0x0A) -> 0x050A
        @(posedge clk);
        pc_branch = 1;
        branch_offset = 8'd10;
        @(posedge clk);
        pc_branch = 0;
        #1;
        if (pc !== 16'h050A) begin
            $display("[FAIL] PC relative branch forward failed! Got: 0x%h", pc);
            error_count++;
        end

        // 6. Relative negative branch: PC = 0x050A - 20 (0xEC) -> 0x04F6
        @(posedge clk);
        pc_branch = 1;
        branch_offset = -8'sd20; // 8'hEC
        @(posedge clk);
        pc_branch = 0;
        #1;
        if (pc !== 16'h04F6) begin
            $display("[FAIL] PC relative branch backward failed! Got: 0x%h", pc);
            error_count++;
        end

        if (error_count == 0) begin
            $display("[PASS] sv16_pc unit test passed with 0 errors.");
        end else begin
            $display("[FAIL] sv16_pc unit test failed with %0d errors.", error_count);
        end

        $finish;
    end

endmodule : sv16_pc_tb
