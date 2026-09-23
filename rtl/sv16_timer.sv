// SV-16 Rev A — 16-Bit Hardware Timer Controller
// Module: sv16_timer
//
// Register Map (Base: 0xF020):
//   Offset 0 (0xF020): TMR0_CNT  — Current 16-bit counter value (R/W)
//   Offset 1 (0xF021): TMR0_CMP  — 16-bit compare match register (R/W)
//   Offset 2 (0xF022): TMR0_CTRL — Control register:
//                        Bit 0: EN (Timer enable)
//                        Bit 1: AUTO_RELOAD (Reset counter to 0 on match)
//                        Bit 2: IE (Interrupt enable on match)
//                        Bits [7:4]: Prescaler select (div 1, 2, 4, 8, 16, 64, 256, 1024)
//   Offset 3 (0xF023): TMR0_STAT — Status register:
//                        Bit 0: MATCH (Set when CNT == CMP, write 1 to clear)
//
// Interrupt Output:
//   timer_irq : Asserts when MATCH == 1 and IE == 1

`timescale 1ns / 1ps

module sv16_timer (
    input  logic        clk,
    input  logic        rst_n,

    // Bus Slave Interface
    input  logic [3:0]  addr,
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    input  logic        req,
    input  logic        we,
    output logic        ack,

    // Interrupt Line
    output logic        timer_irq
);

    logic [15:0] cnt_reg;
    logic [15:0] cmp_reg;
    logic [15:0] ctrl_reg;
    logic        match_flag;

    // Prescaler counter
    logic [9:0]  prescaler_cnt;
    logic        prescaler_tick;

    // Prescaler decode:
    // 0: div 1, 1: div 2, 2: div 4, 3: div 8, 4: div 16, 5: div 64, 6: div 256, 7: div 1024
    always_comb begin
        case (ctrl_reg[7:4])
            4'd0: prescaler_tick = 1'b1;                          // Div 1
            4'd1: prescaler_tick = (prescaler_cnt[0] == 1'b0);     // Div 2
            4'd2: prescaler_tick = (prescaler_cnt[1:0] == 2'b00);  // Div 4
            4'd3: prescaler_tick = (prescaler_cnt[2:0] == 3'b000); // Div 8
            4'd4: prescaler_tick = (prescaler_cnt[3:0] == 4'b0000);// Div 16
            4'd5: prescaler_tick = (prescaler_cnt[5:0] == 6'b000000); // Div 64
            4'd6: prescaler_tick = (prescaler_cnt[7:0] == 8'h00);  // Div 256
            4'd7: prescaler_tick = (prescaler_cnt[9:0] == 10'd0);  // Div 1024
            default: prescaler_tick = 1'b1;
        endcase
    end

    // Single-cycle acknowledge
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) ack <= 1'b0;
        else ack <= req;
    end

    // Timer Counting & Compare Logic
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt_reg       <= 16'h0000;
            cmp_reg       <= 16'hFFFF;
            ctrl_reg      <= 16'h0000;
            match_flag    <= 1'b0;
            prescaler_cnt <= 10'd0;
        end else begin
            // Bus register write
            if (req && we) begin
                case (addr[1:0])
                    2'b00: cnt_reg  <= wdata;
                    2'b01: cmp_reg  <= wdata;
                    2'b10: ctrl_reg <= wdata;
                    2'b11: begin
                        if (wdata[0]) match_flag <= 1'b0; // Write 1 to clear
                    end
                endcase
            end else if (ctrl_reg[0]) begin // If Timer Enabled (EN == 1)
                prescaler_cnt <= prescaler_cnt + 10'd1;

                if (prescaler_tick) begin
                    if (cnt_reg == cmp_reg) begin
                        match_flag <= 1'b1;
                        if (ctrl_reg[1]) begin // Auto reload
                            cnt_reg <= 16'h0000;
                        end else begin
                            cnt_reg <= cnt_reg + 16'd1;
                        end
                    end else begin
                        cnt_reg <= cnt_reg + 16'd1;
                    end
                end
            end
        end
    end

    // Register Read Logic
    always_comb begin
        case (addr[1:0])
            2'b00: rdata = cnt_reg;
            2'b01: rdata = cmp_reg;
            2'b10: rdata = ctrl_reg;
            2'b11: rdata = {15'd0, match_flag};
            default: rdata = 16'h0000;
        endcase
    end

    // Interrupt Generation
    assign timer_irq = match_flag && ctrl_reg[2]; // match && IE

endmodule : sv16_timer
