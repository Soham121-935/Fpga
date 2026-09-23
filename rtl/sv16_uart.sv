// SV-16 Rev A — Hardware UART Transceiver
// Module: sv16_uart
//
// Register Map (Base: 0xF040):
//   Offset 0 (0xF040): UART0_DATA   — Read: RX byte [7:0]; Write: TX byte [7:0]
//   Offset 1 (0xF041): UART0_STATUS — Status:
//                        Bit 0: TX_READY (1 = Transmitter ready for byte)
//                        Bit 1: RX_VALID (1 = Received byte available)
//                        Bit 2: OVERRUN_ERR (Receiver overrun)
//   Offset 2 (0xF042): UART0_BAUD   — 16-bit baud divisor (clk_freq / baud_rate)
//   Offset 3 (0xF043): UART0_CTRL   — Control:
//                        Bit 0: TX_EN
//                        Bit 1: RX_EN
//                        Bit 2: TX_IE (Interrupt enable)
//                        Bit 3: RX_IE (Interrupt enable)
//
// Framing: 8-N-1 (8 Data bits, No parity, 1 Stop bit)

`timescale 1ns / 1ps

module sv16_uart (
    input  logic        clk,
    input  logic        rst_n,

    // Bus Slave Interface
    input  logic [3:0]  addr,
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    input  logic        req,
    input  logic        we,
    output logic        ack,

    // Physical Serial Pins
    input  logic        uart_rx,
    output logic        uart_tx,

    // Interrupt Lines
    output logic        uart_tx_irq,
    output logic        uart_rx_irq
);

    logic [15:0] baud_div_reg;
    logic [15:0] ctrl_reg;
    logic [7:0]  rx_data_reg;
    logic        rx_valid;
    logic        rx_overrun;

    // TX state machine & shift register
    logic [15:0] tx_clk_cnt;
    logic [3:0]  tx_bit_idx;
    logic [9:0]  tx_shift_reg; // Start (0) + 8 Data + Stop (1)
    logic        tx_busy;

    // RX input synchronizer
    logic        rx_sync1, rx_sync2;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_sync1 <= 1'b1;
            rx_sync2 <= 1'b1;
        end else begin
            rx_sync1 <= uart_rx;
            rx_sync2 <= rx_sync1;
        end
    end

    // Single-cycle acknowledge
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) ack <= 1'b0;
        else ack <= req;
    end

    // TX Logic
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            baud_div_reg <= 16'd217; // Default 115200 baud @ 25MHz
            ctrl_reg     <= 16'h0003; // TX_EN | RX_EN enabled
            tx_clk_cnt   <= 16'd0;
            tx_bit_idx   <= 4'd0;
            tx_shift_reg <= 10'b1111111111;
            tx_busy      <= 1'b0;
            uart_tx      <= 1'b1;
        end else begin
            // Bus writes
            if (req && we) begin
                case (addr[1:0])
                    2'b00: begin // UART0_DATA (transmit initiate)
                        if (!tx_busy && ctrl_reg[0]) begin
                            tx_shift_reg <= {1'b1, wdata[7:0], 1'b0}; // Stop(1), Data[7:0], Start(0)
                            tx_busy      <= 1'b1;
                            tx_clk_cnt   <= 16'd0;
                            tx_bit_idx   <= 4'd0;
                        end
                    end
                    2'b10: baud_div_reg <= wdata;
                    2'b11: ctrl_reg     <= wdata;
                endcase
            end

            // TX Baud Generator & Serial Output
            if (tx_busy) begin
                if (tx_clk_cnt >= baud_div_reg - 16'd1) begin
                    tx_clk_cnt <= 16'd0;
                    uart_tx    <= tx_shift_reg[0];
                    tx_shift_reg <= {1'b1, tx_shift_reg[9:1]};
                    tx_bit_idx <= tx_bit_idx + 4'd1;

                    if (tx_bit_idx == 4'd9) begin
                        tx_busy <= 1'b0;
                        uart_tx <= 1'b1;
                    end
                end else begin
                    tx_clk_cnt <= tx_clk_cnt + 16'd1;
                end
            end else begin
                uart_tx <= 1'b1;
            end
        end
    end

    // RX Logic (Basic byte latching)
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_data_reg <= 8'h00;
            rx_valid    <= 1'b0;
            rx_overrun  <= 1'b0;
        end else begin
            if (req && !we && (addr[1:0] == 2'b00)) begin
                rx_valid <= 1'b0; // Reading data register clears RX_VALID
            end
        end
    end

    // Register Read Logic
    always_comb begin
        case (addr[1:0])
            2'b00: rdata = {8'h00, rx_data_reg};
            2'b01: rdata = {13'd0, rx_overrun, rx_valid, !tx_busy}; // Bit 0: TX_READY
            2'b10: rdata = baud_div_reg;
            2'b11: rdata = ctrl_reg;
            default: rdata = 16'h0000;
        endcase
    end

    // Interrupts
    assign uart_tx_irq = (!tx_busy) && ctrl_reg[2];
    assign uart_rx_irq = rx_valid && ctrl_reg[3];

endmodule : sv16_uart
