// SV-16 Rev B — SPI Master Peripheral (SPI0)
// Module: sv16_spi
//
// General purpose SPI master for external devices (sensors, displays, SD
// cards...). Byte oriented: write a byte to SPI0_DATA to start an 8-bit
// transfer, poll/receive the reply in SPI0_DATA. The clock generator and
// shift engine are shared with the flash controller through sv16_spi_master.
//
// Register map (BLK_SPI0 = 0xF050):
//   0x0 SPI_DATA   (RW) write: byte to transmit (starts a transfer)
//                        read:  last received byte (clears RX_READY)
//   0x1 SPI_STATUS (RO) [0] BUSY [1] RX_READY [2] TX_READY [3] CS_N
//   0x2 SPI_CTRL   (RW) [0] EN [1] CPOL [2] CPHA [3] CS_HOLD
//                            (keep CS asserted between bytes)
//   0x3 SPI_DIV    (RW) SCLK half period = (DIV+1) clocks
//
// Rev B: new module (ADR-016).

`timescale 1ns / 1ps

import sv16_pkg::*;

module sv16_spi (
    input  logic        clk,
    input  logic        rst_n,

    input  logic [2:0]  addr,
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    input  logic        req,
    input  logic        we,
    output logic        ack,

    output logic        spi_sck,
    output logic        spi_mosi,
    input  logic        spi_miso,
    output logic        spi_cs_n,

    output logic        spi_irq
);


    logic [15:0] ctrl_reg;
    logic [15:0] div_reg;
    logic [7:0]  tx_byte;
    logic        tx_pending;
    logic [7:0]  rx_byte;
    logic        rx_ready;

    logic        m_start, m_busy, m_done, m_tx_ready, m_tx_taken;
    logic [7:0]  m_len;
    logic        m_tx_valid, m_rx_valid, m_rx_ack, m_cs_hold;
    logic [7:0]  m_tx_data, m_rx_data;

    assign m_cs_hold = ctrl_reg[3];
    assign m_len     = 8'd1;
    assign m_tx_data = tx_byte;
    assign m_tx_valid= tx_pending;

    sv16_spi_master u_master (
        .clk(clk), .rst_n(rst_n),
        .start(m_start), .len(m_len), .mode(ctrl_reg[2:1]),
        .clk_div(div_reg), .cs_hold(m_cs_hold),
        .busy(m_busy), .done(m_done),
        .tx_data(m_tx_data), .tx_valid(m_tx_valid), .tx_ready(m_tx_ready),
        .tx_taken(m_tx_taken),
        .rx_data(m_rx_data), .rx_valid(m_rx_valid), .rx_ack(m_rx_ack),
        .sck(spi_sck), .mosi(spi_mosi), .miso(spi_miso), .cs_n(spi_cs_n)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) ack <= 1'b0;
        else        ack <= req;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ctrl_reg   <= 16'h0000;
            div_reg    <= 16'd1;         // 6.25 MHz SCLK @25 MHz
            tx_byte    <= 8'h00;
            tx_pending <= 1'b0;
            rx_byte    <= 8'h00;
            rx_ready   <= 1'b0;
            m_start    <= 1'b0;
        end else begin
            m_start <= 1'b0;

            if (req && we) begin
                case (addr)
                    SPI_DATA: begin
                        if (ctrl_reg[0]) begin
                            tx_byte    <= wdata[7:0];
                            tx_pending <= 1'b1;
                            rx_ready   <= 1'b0;
                        end
                    end
                    SPI_CTRL: ctrl_reg <= wdata;
                    SPI_DIV:  div_reg  <= (wdata == 16'd0) ? 16'd1 : wdata;
                    default: ;
                endcase
            end

            // start the transfer as soon as the engine is free
            if (tx_pending && !m_busy && !m_start) m_start <= 1'b1;
            if (m_tx_taken) tx_pending <= 1'b0;

            // capture the received byte
            if (m_rx_valid) begin
                rx_byte  <= m_rx_data;
                rx_ready <= 1'b1;
            end
        end
    end

    assign m_rx_ack = m_rx_valid && rx_ready;

    always_comb begin
        rdata = 16'h0000;
        case (addr)
            SPI_DATA:   rdata = {8'h00, rx_byte};
            SPI_STATUS: rdata = {12'h000, spi_cs_n, 1'b1, rx_ready,
                                 (m_busy || tx_pending)};
            SPI_CTRL:   rdata = ctrl_reg;
            SPI_DIV:    rdata = div_reg;
            default:    rdata = 16'h0000;
        endcase
    end

    // Reading SPI_DATA clears the receive flag
    assign spi_irq = rx_ready && ctrl_reg[0];

endmodule : sv16_spi
