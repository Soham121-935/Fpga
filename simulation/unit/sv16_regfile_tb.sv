// SV-16 Rev A — Unit Testbench for sv16_regfile
// Verification of:
// 1. Reset state (all registers initialize to 0x0000)
// 2. Sequential writes and reads on all registers R0..R7
// 3. Simultaneous dual-port reads of different registers
// 4. Simultaneous dual-port reads of the same register
// 5. Write enable (wen = 0 prevents register update)
// 6. Overwrite existing register values

`timescale 1ns / 1ps

module sv16_regfile_tb;

    logic        clk;
    logic        rst_n;
    logic [2:0]  raddr1;
    logic [15:0] rdata1;
    logic [2:0]  raddr2;
    logic [15:0] rdata2;
    logic        wen;
    logic [2:0]  waddr;
    logic [15:0] wdata;

    int error_count;

    // Instantiate Unit Under Test (UUT)
    sv16_regfile uut (
        .clk(clk),
        .rst_n(rst_n),
        .raddr1(raddr1),
        .rdata1(rdata1),
        .raddr2(raddr2),
        .rdata2(rdata2),
        .wen(wen),
        .waddr(waddr),
        .wdata(wdata)
    );

    // Clock generator (25 MHz -> 40ns period)
    always #20 clk = ~clk;

    initial begin
        clk = 0;
        rst_n = 0;
        wen = 0;
        waddr = 0;
        wdata = 0;
        raddr1 = 0;
        raddr2 = 0;
        error_count = 0;

        #100;
        // Test 1: Release reset and verify all registers are 0x0000
        rst_n = 1;
        #40;
        for (int i = 0; i < 8; i++) begin
            raddr1 = i[2:0];
            #1;
            if (rdata1 !== 16'h0000) begin
                $display("[ERROR] Reg R%0d reset value mismatch! Got: 0x%h, Expected: 0x0000", i, rdata1);
                error_count++;
            end
        end

        // Test 2: Write unique patterns to all 8 registers
        for (int i = 0; i < 8; i++) begin
            @(posedge clk);
            wen   = 1;
            waddr = i[2:0];
            wdata = 16'hA000 | (i << 4) | i;
        end

        @(posedge clk);
        wen = 0;

        // Verify all 8 registers retain their written values
        for (int i = 0; i < 8; i++) begin
            raddr1 = i[2:0];
            #1;
            if (rdata1 !== (16'hA000 | (i << 4) | i)) begin
                $display("[ERROR] Reg R%0d readback error! Got: 0x%h, Expected: 0x%h",
                         i, rdata1, (16'hA000 | (i << 4) | i));
                error_count++;
            end
        end

        // Test 3: Dual-port simultaneous read of distinct registers
        raddr1 = 3'd2; // R2
        raddr2 = 3'd5; // R5
        #1;
        if (rdata1 !== (16'hA000 | (2 << 4) | 2) || rdata2 !== (16'hA000 | (5 << 4) | 5)) begin
            $display("[ERROR] Dual-port distinct read failed!");
            error_count++;
        end

        // Test 4: Dual-port simultaneous read of the same register
        raddr1 = 3'd3;
        raddr2 = 3'd3;
        #1;
        if (rdata1 !== rdata2 || rdata1 !== (16'hA000 | (3 << 4) | 3)) begin
            $display("[ERROR] Dual-port same reg read failed!");
            error_count++;
        end

        // Test 5: Write-enable disabled (wen = 0)
        @(posedge clk);
        wen   = 0;
        waddr = 3'd4;
        wdata = 16'hDEAD;
        @(posedge clk);
        raddr1 = 3'd4;
        #1;
        if (rdata1 === 16'hDEAD) begin
            $display("[ERROR] Register updated when wen == 0!");
            error_count++;
        end

        // Test 6: Overwrite R4 with wen = 1
        @(posedge clk);
        wen   = 1;
        waddr = 3'd4;
        wdata = 16'hBEEF;
        @(posedge clk);
        wen   = 0;
        raddr1 = 3'd4;
        #1;
        if (rdata1 !== 16'hBEEF) begin
            $display("[ERROR] Failed to overwrite R4! Got: 0x%h", rdata1);
            error_count++;
        end

        // Summary
        if (error_count == 0) begin
            $display("[PASS] sv16_regfile unit test passed with 0 errors.");
        end else begin
            $display("[FAIL] sv16_regfile unit test failed with %0d errors.", error_count);
        end

        $finish;
    end

endmodule : sv16_regfile_tb
