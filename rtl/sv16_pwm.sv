// SV-16 Rev A — 16-Bit Hardware PWM Controller
// Module: sv16_pwm
//
// Target Application: DC Motor Speed Control & External H-Bridge Driving
//
// Register Map (Base: 0xF030):
//   Offset 0 (0xF030): PWM0_PERIOD — 16-bit PWM period value (carrier frequency)
//   Offset 1 (0xF031): PWM0_DUTY   — 16-bit duty threshold (pulse width)
//   Offset 2 (0xF032): PWM0_CTRL   — Control register:
//                        Bit 0: EN (PWM output enable)
//                        Bit 1: POL (Polarity: 0 = active-high, 1 = active-low)
//                        Bit 2: FAULT_CLR (Write 1 to clear latched fault condition)
//   Offset 3 (0xF033): PWM0_STAT   — Status register:
//                        Bit 0: FAULT_LATCHED (Emergency shutdown occurred)
//
// Hardware Safety:
//   motor_fault_n input: Active-low external overcurrent / emergency-stop pin.
//   When motor_fault_n is driven low, pwm_out is IMMEDIATELY forced to inactive (0),
//   and the FAULT status bit latches high until cleared by firmware.

`timescale 1ns / 1ps

module sv16_pwm (
    input  logic        clk,
    input  logic        rst_n,

    // Bus Slave Interface
    input  logic [3:0]  addr,
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    input  logic        req,
    input  logic        we,
    output logic        ack,

    // Hardware Safety & External Motor Driver Pins
    input  logic        motor_fault_n,
    output logic        pwm_out
);

    logic [15:0] period_reg;
    logic [15:0] duty_reg;
    logic [15:0] ctrl_reg;
    logic [15:0] counter_reg;
    logic        fault_latched;
    logic        raw_pwm;

    // Single-cycle acknowledge
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) ack <= 1'b0;
        else ack <= req;
    end

    // Safety Fault Monitor (Active-Low)
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fault_latched <= 1'b0;
        end else begin
            if (!motor_fault_n) begin
                fault_latched <= 1'b1; // Latch emergency stop
            end else if (req && we && (addr[1:0] == 2'b10) && wdata[2]) begin
                fault_latched <= 1'b0; // Clear fault on explicit firmware command
            end
        end
    end

    // Register Write Logic & PWM Counter
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            period_reg  <= 16'h03E8; // Default 1000 counts
            duty_reg    <= 16'h0000; // Default 0% duty
            ctrl_reg    <= 16'h0000; // Disabled
            counter_reg <= 16'h0000;
        end else begin
            if (req && we) begin
                case (addr[1:0])
                    2'b00: period_reg <= (wdata == 16'd0) ? 16'd1 : wdata;
                    2'b01: duty_reg   <= wdata;
                    2'b10: ctrl_reg   <= wdata;
                endcase
            end

            // Counter increment
            if (ctrl_reg[0] && !fault_latched) begin
                if (counter_reg >= period_reg - 16'd1) begin
                    counter_reg <= 16'h0000;
                end else begin
                    counter_reg <= counter_reg + 16'd1;
                end
            end else begin
                counter_reg <= 16'h0000;
            end
        end
    end

    // Raw PWM waveform generation
    always_comb begin
        if (ctrl_reg[0] && !fault_latched) begin
            raw_pwm = (counter_reg < duty_reg);
        end else begin
            raw_pwm = 1'b0;
        end
    end

    // Polarity inversion and output assignment
    assign pwm_out = (ctrl_reg[1]) ? ~raw_pwm : raw_pwm;

    // Register Read Logic
    always_comb begin
        case (addr[1:0])
            2'b00: rdata = period_reg;
            2'b01: rdata = duty_reg;
            2'b10: rdata = ctrl_reg;
            2'b11: rdata = {15'd0, fault_latched};
            default: rdata = 16'h0000;
        endcase
    end

endmodule : sv16_pwm
