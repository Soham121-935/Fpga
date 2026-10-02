// SV-16 Rev B — Hardware UART Transceiver (with TX/RX FIFOs)
// Module: sv16_uart
//
// Register Map (Base: 0xF040):
//   Offset 0 (0xF040): UART0_DATA   — Read: pop next RX byte [7:0]
//                                     Write: push byte [7:0] into the TX FIFO
//   Offset 1 (0xF041): UART0_STATUS — Status:
//                        Bit 0: TX_READY (TX FIFO has room: write accepted)
//                        Bit 1: RX_VALID (RX FIFO not empty)
//                        Bit 2: OVERRUN_ERR (RX FIFO overflow, sticky)
//                        Bit 3: FRAME_ERR   (stop bit was 0, sticky)
//                        Bit 4: TX_BUSY     (shifter active)
//                        Bit 5: TX_EMPTY    (FIFO empty and idle)
//                        Bit 6: RX_FULL     (RX FIFO full)
//                        Bit 7: TX_FULL     (TX FIFO full)
//   Offset 2 (0xF042): UART0_BAUD   — 16-bit baud divisor (clk / baud)
//   Offset 3 (0xF043): UART0_CTRL   — Control:
//                        Bit 0: TX_EN
//                        Bit 1: RX_EN
//                        Bit 2: TX_IE (interrupt when TX FIFO has room)
//                        Bit 3: RX_IE (interrupt when RX FIFO is not empty)
//                        Bit 4: reserved (read 0)
//                        Bit 5: LOOPBACK (TX output is fed back into RX)
//                        Bit 6: TX_FIFO clear (self-clearing)
//                        Bit 7: RX_FIFO clear (self-clearing)
//   Offset 4 (0xF044): UART0_FIFO   — {9'b0, TX count[2:0], 1'b0, RX count[2:0]}:
//                                      TX count in bits [6:4], RX count in bits
//                                      [2:0] (3-bit counts of 4-deep FIFOs),
//                                      bit 3 reserved
//
// Framing: 8-N-1 (8 data bits, no parity, 1 stop bit). 4-byte TX and RX FIFOs.
//
// Rev B changes (see docs/ARCHITECTURE_DECISIONS.md, ADR-012): Rev A never
// assembled received bytes and had no FIFOs, so no firmware could be uploaded
// over the serial port. The receiver is fully implemented here, which enables
// the ROM monitor / UART field-update path.

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

    // Interrupt Lines (level, gated by the control register)
    output logic        uart_tx_irq,
    output logic        uart_rx_irq
);

    // BAUD_DIV_RESET is the divisor loaded into the baud register at reset:
    // the SoC clock frequency divided by the console baud rate.  The SoC top
    // derives it from its own clock configuration, so the console is always
    // 115200 8-N-1 whatever the system clock divider is set to.
    parameter int BAUD_DIV_RESET = 217;   // 25 MHz / 115200

    localparam int FIFO_DEPTH = 4;

    logic [15:0] baud_div_reg;
    logic [15:0] ctrl_reg;

    // ------------------------------------------------------------- RX path
    logic        rx_sync1, rx_sync2;
    logic        rx_line;          // internal RX line (loopback capable)

    logic [1:0]  rx_state;
    logic [15:0] rx_timer;
    logic [2:0]  rx_bit_idx;
    logic [7:0]  rx_shift;

    logic [7:0]  rx_fifo [0:FIFO_DEPTH-1];
    logic [2:0]  rx_wr_ptr, rx_rd_ptr;   // extra bit holds the wrap
    logic [2:0]  rx_count;
    logic        rx_overrun, rx_frame_err;

    // ------------------------------------------------------------- TX path
    logic [7:0]  tx_fifo [0:FIFO_DEPTH-1];
    logic [2:0]  tx_wr_ptr, tx_rd_ptr;
    logic [2:0]  tx_count;

    logic [15:0] tx_timer;
    logic [3:0]  tx_bit_idx;
    logic [9:0]  tx_shift;      // start (0) + 8 data + stop (1)
    logic        tx_busy;

    logic        rx_fifo_clr, tx_fifo_clr;

    localparam logic [1:0] RX_IDLE  = 2'd0,
                           RX_START = 2'd1,
                           RX_DATA  = 2'd2,
                           RX_STOP  = 2'd3;

    assign rx_line   = ctrl_reg[5] ? uart_tx : uart_rx;  // loopback self-test
    assign rx_valid  = (rx_count != 3'd0);
    assign tx_full   = (tx_count == 3'd4);
    assign rx_full   = (rx_count == 3'd4);
    assign rx_valid_w = rx_valid;

    // Input synchronizer
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_sync1 <= 1'b1;
            rx_sync2 <= 1'b1;
        end else begin
            rx_sync1 <= rx_line;
            rx_sync2 <= rx_sync1;
        end
    end

    // Single-cycle acknowledge (single-cycle request protocol)
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) ack <= 1'b0;
        else ack <= req;
    end

    // Band-rate helpers
    logic [15:0] baud_div_safe;
    assign baud_div_safe = (baud_div_reg < 16'd4) ? 16'd4 : baud_div_reg;
    logic [15:0] rx_half_bit;
    assign rx_half_bit = baud_div_safe >> 1;

    // Control / configuration registers and FIFO clear
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            baud_div_reg <= BAUD_DIV_RESET[15:0];
            ctrl_reg     <= 16'h0003;  // TX_EN | RX_EN
        end else if (req && we) begin
            case (addr[2:0])
                3'd0: ;                            // DATA write: handled in TX path
                3'd2: baud_div_reg <= (wdata < 16'd4) ? 16'd4 : wdata;
                // CTRL[7:6] are write-only, self-clearing FIFO-clear pulses:
                // storing them would make a read-modify-write of CTRL (the
                // natural way to set an interrupt enable) clear both FIFOs.
                3'd3: ctrl_reg     <= wdata & 16'h003F;
                default: ;
            endcase
        end
    end

    assign rx_fifo_clr = (req && we && (addr[2:0] == 3'd3) && wdata[7]);
    assign tx_fifo_clr = (req && we && (addr[2:0] == 3'd3) && wdata[6]);

    // ---------------------------------------------------------- TX FIFO
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tx_wr_ptr <= 3'd0;
            tx_rd_ptr <= 3'd0;
            tx_count  <= 3'd0;
        end else if (tx_fifo_clr) begin
            tx_wr_ptr <= 3'd0;
            tx_rd_ptr <= 3'd0;
            tx_count  <= 3'd0;
        end else begin
            // push
            if (req && we && (addr[2:0] == 3'd0) && !tx_full && ctrl_reg[0]) begin
                tx_fifo[tx_wr_ptr[1:0]] <= wdata[7:0];
                tx_wr_ptr <= tx_wr_ptr + 3'd1;
            end
            // pop (loaded into the shifter)
            if (!tx_busy && (tx_count != 3'd0) && ctrl_reg[0]) begin
                tx_rd_ptr <= tx_rd_ptr + 3'd1;
            end

            case ({req && we && (addr[2:0] == 3'd0) && !tx_full && ctrl_reg[0],
                   !tx_busy && (tx_count != 3'd0) && ctrl_reg[0]})
                2'b10: tx_count <= tx_count + 3'd1;
                2'b01: tx_count <= tx_count - 3'd1;
                default: tx_count <= tx_count;
            endcase
        end
    end

    // ---------------------------------------------------------- TX shifter
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tx_timer   <= 16'd0;
            tx_bit_idx <= 4'd0;
            tx_shift   <= 10'h3FF;
            tx_busy    <= 1'b0;
            uart_tx    <= 1'b1;
        end else if (tx_fifo_clr) begin
            tx_busy  <= 1'b0;
            uart_tx  <= 1'b1;
            tx_timer <= 16'd0;
        end else if (!tx_busy) begin
            uart_tx <= 1'b1;
            if ((tx_count != 3'd0) && ctrl_reg[0]) begin
                // Load: stop(1) | data | start(0); bit 0 is transmitted first
                tx_shift   <= {1'b1, tx_fifo[tx_rd_ptr[1:0]], 1'b0};
                tx_busy    <= 1'b1;
                tx_timer   <= 16'd0;
                tx_bit_idx <= 4'd0;
            end
        end else begin
            if (tx_timer >= baud_div_safe - 16'd1) begin
                tx_timer     <= 16'd0;
                uart_tx      <= tx_shift[0];
                tx_shift     <= {1'b1, tx_shift[9:1]};
                tx_bit_idx   <= tx_bit_idx + 4'd1;
                if (tx_bit_idx == 4'd9) begin
                    tx_busy <= 1'b0;
                    uart_tx <= 1'b1;
                end
            end else begin
                tx_timer <= tx_timer + 16'd1;
            end
        end
    end

    // ---------------------------------------------------------- RX FIFO
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_wr_ptr <= 3'd0;
            rx_rd_ptr <= 3'd0;
            rx_count  <= 3'd0;
        end else if (rx_fifo_clr) begin
            rx_wr_ptr <= 3'd0;
            rx_rd_ptr <= 3'd0;
            rx_count  <= 3'd0;
        end else begin
            // push (from the receiver)
            if (rx_push && !rx_full) begin
                rx_fifo[rx_wr_ptr[1:0]] <= rx_byte;
                rx_wr_ptr <= rx_wr_ptr + 3'd1;
            end
            // pop (bus read of DATA)
            if (req && !we && (addr[2:0] == 3'd0) && rx_valid) begin
                rx_rd_ptr <= rx_rd_ptr + 3'd1;
            end

            case ({rx_push && !rx_full,
                   req && !we && (addr[2:0] == 3'd0) && rx_valid})
                2'b10: rx_count <= rx_count + 3'd1;
                2'b01: rx_count <= rx_count - 3'd1;
                default: rx_count <= rx_count;
            endcase
        end
    end

    // -------------------------------------------------------- RX receiver
    logic       rx_push;
    logic [7:0] rx_byte;

    assign rx_push = (rx_state == RX_STOP) && (rx_timer >= baud_div_safe - 16'd1) && ctrl_reg[1];
    assign rx_byte = rx_shift;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_state     <= RX_IDLE;
            rx_timer     <= 16'd0;
            rx_bit_idx   <= 3'd0;
            rx_shift     <= 8'h00;
            rx_overrun   <= 1'b0;
            rx_frame_err <= 1'b0;
        end else if (rx_fifo_clr) begin
            rx_state     <= RX_IDLE;
            rx_timer     <= 16'd0;
            rx_overrun   <= 1'b0;
            rx_frame_err <= 1'b0;
        end else begin
            // Sticky error flags: write 1 to the status register bits to clear
            if (req && we && (addr[2:0] == 3'd1)) begin
                if (wdata[2]) rx_overrun   <= 1'b0;
                if (wdata[3]) rx_frame_err <= 1'b0;
            end

            if (rx_push && rx_full) begin
                rx_overrun <= 1'b1;
            end

            if (!ctrl_reg[1]) begin
                rx_state <= RX_IDLE;
                rx_timer <= 16'd0;
            end else begin
                case (rx_state)
                    RX_IDLE: begin
                        rx_timer <= 16'd0;
                        if (!rx_sync2) begin
                            rx_state <= RX_START;   // possible start bit
                        end
                    end

                    RX_START: begin
                        if (rx_timer >= rx_half_bit) begin
                            rx_timer <= 16'd0;
                            if (!rx_sync2) begin
                                rx_state   <= RX_DATA; // confirmed: sample data
                                rx_bit_idx <= 3'd0;
                            end else begin
                                rx_state <= RX_IDLE;   // glitch
                            end
                        end else begin
                            rx_timer <= rx_timer + 16'd1;
                        end
                    end

                    RX_DATA: begin
                        if (rx_timer >= baud_div_safe - 16'd1) begin
                            rx_timer <= 16'd0;
                            rx_shift <= {rx_sync2, rx_shift[7:1]};
                            if (rx_bit_idx == 3'd7) begin
                                rx_state <= RX_STOP;
                            end else begin
                                rx_bit_idx <= rx_bit_idx + 3'd1;
                            end
                        end else begin
                            rx_timer <= rx_timer + 16'd1;
                        end
                    end

                    RX_STOP: begin
                        if (rx_timer >= baud_div_safe - 16'd1) begin
                            rx_timer <= 16'd0;
                            if (!rx_sync2) begin
                                // Stop bit low.  The byte is still pushed (the
                                // owner gets it *and* the error flag) because
                                // that is what a real UART does and it keeps the
                                // receiver from silently eating a byte; the
                                // monitor's CRC16 is what rejects a corrupted
                                // command, so a dropped byte would only look
                                // like a stall.
                                rx_frame_err <= 1'b1;
                            end
                            rx_state <= RX_IDLE;
                        end else begin
                            rx_timer <= rx_timer + 16'd1;
                        end
                    end

                    default: rx_state <= RX_IDLE;
                endcase
            end
        end
    end

    // ------------------------------------------------------ Register reads
    logic rx_valid, tx_full, rx_full, rx_valid_w;

    // The DATA read pops the RX FIFO on the request cycle, but a master
    // samples bus_rdata one cycle later (in the acknowledge cycle).  Drive
    // the read data from a latch taken on the pop so the byte handed to the
    // CPU is the one that was at the head of the FIFO, not the next one.
    logic [7:0] rx_data_reg;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) rx_data_reg <= 8'h00;
        else if (req && !we && (addr[2:0] == 3'd0) && rx_valid)
            rx_data_reg <= rx_fifo[rx_rd_ptr[1:0]];
    end

    always_comb begin
        case (addr[2:0])
            3'd0: rdata = {8'h00, rx_data_reg};
            3'd1: rdata = {8'h00, tx_full, rx_full, tx_empty, tx_busy,
                           rx_frame_err, rx_overrun, rx_valid, tx_ready};
            3'd2: rdata = baud_div_reg;
            3'd3: rdata = ctrl_reg;
            3'd4: rdata = {9'd0, tx_count, 1'b0, rx_count};
            default: rdata = 16'h0000;
        endcase
    end

    logic tx_ready, tx_empty;
    assign tx_ready = !tx_full;
    assign tx_empty = (tx_count == 3'd0) && !tx_busy;

    // Interrupts (level sensitive, gated by the control register)
    assign uart_tx_irq = ctrl_reg[2] && tx_ready;
    assign uart_rx_irq = ctrl_reg[3] && rx_valid;

endmodule : sv16_uart
