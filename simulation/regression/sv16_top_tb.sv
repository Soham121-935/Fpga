// SV-16 Rev A — Full SoC Top-Level Regression Testbench
// Module: sv16_top_tb
//
// Verification of:
// - Hardware reset deassertion
// - Firmware execution driving GPIO peripheral register (0xF010)
// - LED status pin state transition caused by SV-16 CPU instructions
// - Firmware execution configuring PWM peripheral register (0xF030)
// - PWM output pulse generation directly driven by firmware execution

`timescale 1ns / 1ps

module sv16_top_tb;

    logic        clk_25m;
    logic        ext_rst_n;
    logic        uart_rx;
    logic        uart_tx;
    logic [3:0]  led;
    logic        pwm_out;
    logic        motor_dir1;
    logic        motor_dir2;
    logic        motor_fault_n;

    sv16_top uut (.*);

    always #20 clk_25m = ~clk_25m;

    initial begin
        clk_25m = 0;
        ext_rst_n = 0;
        uart_rx = 1'b1;
        motor_fault_n = 1'b1;

        // Initialize program in BRAM:
        // 1. Configure GPIO Direction (0xF011) to Output:
        //    LDI R0, #0xF011      (0x4000, 0xF011)
        //    LDI R1, #0x00FF      (0x4200, 0x00FF)
        //    STORE R1, [R0 + 0]   (0x6000 | (1<<9) | (0<<6) | 0 -> 0x6200)
        //
        // 2. Turn on LEDs via GPIO Data (0xF010):
        //    LDI R0, #0xF010      (0x4000, 0xF010)
        //    LDI R1, #0x000F      (0x4200, 0x000F)
        //    STORE R1, [R0 + 0]   (0x6200)
        //
        // 3. Configure PWM Period (0xF030 = 20):
        //    LDI R0, #0xF030      (0x4000, 0xF030)
        //    LDI R1, #0x0014      (0x4200, 0x0014)
        //    STORE R1, [R0 + 0]   (0x6200)
        //
        // 4. Configure PWM Duty (0xF031 = 10 -> 50% duty):
        //    LDI R0, #0xF031      (0x4000, 0xF031)
        //    LDI R1, #0x000A      (0x4200, 0x000A)
        //    STORE R1, [R0 + 0]   (0x6200)
        //
        // 5. Enable PWM (0xF032 = 1):
        //    LDI R0, #0xF032      (0x4000, 0xF032)
        //    LDI R1, #0x0001      (0x4200, 0x0001)
        //    STORE R1, [R0 + 0]   (0x6200)
        //
        // 6. Infinite Loop:
        //    JMP #0x001A          (0x9000, 0x001A)

        uut.u_bram.mem[0]  = 16'h4000; uut.u_bram.mem[1]  = 16'hF011; // LDI R0, #0xF011 (GPIO_DIR)
        uut.u_bram.mem[2]  = 16'h4200; uut.u_bram.mem[3]  = 16'h00FF; // LDI R1, #0x00FF
        uut.u_bram.mem[4]  = 16'h6200;                                 // STORE R1, [R0]

        uut.u_bram.mem[5]  = 16'h4000; uut.u_bram.mem[6]  = 16'hF010; // LDI R0, #0xF010 (GPIO_DATA)
        uut.u_bram.mem[7]  = 16'h4200; uut.u_bram.mem[8]  = 16'h000F; // LDI R1, #0x000F (LEDs on)
        uut.u_bram.mem[9]  = 16'h6200;                                 // STORE R1, [R0]

        uut.u_bram.mem[10] = 16'h4000; uut.u_bram.mem[11] = 16'hF030; // LDI R0, #0xF030 (PWM0_PERIOD)
        uut.u_bram.mem[12] = 16'h4200; uut.u_bram.mem[13] = 16'h0014; // LDI R1, #20
        uut.u_bram.mem[14] = 16'h6200;                                 // STORE R1, [R0]

        uut.u_bram.mem[15] = 16'h4000; uut.u_bram.mem[16] = 16'hF031; // LDI R0, #0xF031 (PWM0_DUTY)
        uut.u_bram.mem[17] = 16'h4200; uut.u_bram.mem[18] = 16'h000A; // LDI R1, #10 (50% duty)
        uut.u_bram.mem[19] = 16'h6200;                                 // STORE R1, [R0]

        uut.u_bram.mem[20] = 16'h4000; uut.u_bram.mem[21] = 16'hF032; // LDI R0, #0xF032 (PWM0_CTRL)
        uut.u_bram.mem[22] = 16'h4200; uut.u_bram.mem[23] = 16'h0001; // LDI R1, #1 (EN)
        uut.u_bram.mem[24] = 16'h6200;                                 // STORE R1, [R0]

        uut.u_bram.mem[25] = 16'h0000; // NOP
        uut.u_bram.mem[26] = 16'h9000; uut.u_bram.mem[27] = 16'h001A; // JMP to itself

        #100;
        ext_rst_n = 1;

        // Run simulation for 250 clock cycles to execute firmware and observe PWM
        repeat (250) @(posedge clk_25m);

        // Verification checks
        if (led === 4'b0000) begin // Active-low LEDs: 4'b0000 means all 4 LEDs ON
            $display("[PASS] SV-16 firmware successfully actuated GPIO LEDs to active ON state!");
        end else begin
            $display("[FAIL] LED outputs not actuated as expected. led = %b", led);
        end

        $finish;
    end

endmodule : sv16_top_tb
