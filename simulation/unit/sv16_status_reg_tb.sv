// SV-16 Rev A — Unit Testbench for Status Register (sv16_status_reg)
// Verification of:
// 1. Reset state (Z=0, C=0, N=0, V=0, IE=0, sr_out=0x0000)
// 2. Gated ALU flag updates (flag_update_en = 1 updates, 0 maintains previous state)
// 3. Direct architectural SR write (sr_write_en)
// 4. Atomic interrupt enable (ie_set) and disable (ie_clr)
// 5. Bit mapping compliance with ADR-004

`timescale 1ns / 1ps

module sv16_status_reg_tb;

    logic        clk;
    logic        rst_n;
    logic        flag_z_in;
    logic        flag_c_in;
    logic        flag_n_in;
    logic        flag_v_in;
    logic        flag_update_en;
    logic        sr_write_en;
    logic [15:0] sr_write_data;
    logic        ie_set;
    logic        ie_clr;
    logic [15:0] sr_out;
    logic        flag_z;
    logic        flag_c;
    logic        flag_n;
    logic        flag_v;
    logic        flag_ie;

    int error_count;

    sv16_status_reg uut (
        .clk(clk),
        .rst_n(rst_n),
        .flag_z_in(flag_z_in),
        .flag_c_in(flag_c_in),
        .flag_n_in(flag_n_in),
        .flag_v_in(flag_v_in),
        .flag_update_en(flag_update_en),
        .sr_write_en(sr_write_en),
        .sr_write_data(sr_write_data),
        .ie_set(ie_set),
        .ie_clr(ie_clr),
        .sr_out(sr_out),
        .flag_z(flag_z),
        .flag_c(flag_c),
        .flag_n(flag_n),
        .flag_v(flag_v),
        .flag_ie(flag_ie)
    );

    always #20 clk = ~clk;

    initial begin
        clk = 0;
        rst_n = 0;
        flag_z_in = 0;
        flag_c_in = 0;
        flag_n_in = 0;
        flag_v_in = 0;
        flag_update_en = 0;
        sr_write_en = 0;
        sr_write_data = 16'h0000;
        ie_set = 0;
        ie_clr = 0;
        error_count = 0;

        #100;
        rst_n = 1;
        #40;

        // 1. Verify reset state
        if (sr_out !== 16'h0000 || flag_z !== 0 || flag_c !== 0 || flag_n !== 0 || flag_v !== 0 || flag_ie !== 0) begin
            $display("[FAIL] Reset state failed! sr_out = 0x%h", sr_out);
            error_count++;
        end

        // 2. Latch ALU flags: Z=1, C=0, N=1, V=1
        @(posedge clk);
        flag_z_in = 1; flag_c_in = 0; flag_n_in = 1; flag_v_in = 1;
        flag_update_en = 1;
        @(posedge clk);
        flag_update_en = 0;
        #1;
        // Expected sr_out: bit 0 = 1, bit 1 = 0, bit 2 = 1, bit 3 = 1 -> 0x000D
        if (sr_out !== 16'h000D || flag_z !== 1 || flag_c !== 0 || flag_n !== 1 || flag_v !== 1) begin
            $display("[FAIL] Flag latch failed! sr_out = 0x%h", sr_out);
            error_count++;
        end

        // 3. Test flag hold when flag_update_en = 0
        @(posedge clk);
        flag_z_in = 0; flag_c_in = 1; flag_n_in = 0; flag_v_in = 0;
        flag_update_en = 0;
        @(posedge clk);
        #1;
        if (sr_out !== 16'h000D) begin
            $display("[FAIL] Flag hold failed when update_en=0! sr_out = 0x%h", sr_out);
            error_count++;
        end

        // 4. Test atomic IE set and clear
        @(posedge clk);
        ie_set = 1;
        @(posedge clk);
        ie_set = 0;
        #1;
        // Expected: 0x008D (bit 7 set)
        if (sr_out !== 16'h008D || flag_ie !== 1) begin
            $display("[FAIL] Atomic IE set failed! sr_out = 0x%h", sr_out);
            error_count++;
        end

        @(posedge clk);
        ie_clr = 1;
        @(posedge clk);
        ie_clr = 0;
        #1;
        if (sr_out !== 16'h000D || flag_ie !== 0) begin
            $display("[FAIL] Atomic IE clear failed! sr_out = 0x%h", sr_out);
            error_count++;
        end

        // 5. Test direct architectural SR write
        @(posedge clk);
        sr_write_en = 1;
        sr_write_data = 16'h0082; // IE=1, C=1, others 0
        @(posedge clk);
        sr_write_en = 0;
        #1;
        if (sr_out !== 16'h0082 || flag_c !== 1 || flag_ie !== 1 || flag_z !== 0) begin
            $display("[FAIL] Direct SR write failed! sr_out = 0x%h", sr_out);
            error_count++;
        end

        if (error_count == 0) begin
            $display("[PASS] sv16_status_reg unit test passed with 0 errors.");
        end else begin
            $display("[FAIL] sv16_status_reg unit test failed with %0d errors.", error_count);
        end

        $finish;
    end

endmodule : sv16_status_reg_tb
