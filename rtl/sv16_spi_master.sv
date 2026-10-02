// SV-16 Rev B — SPI Master Engine
// Module: sv16_spi_master
//
// A small, mode-configurable (CPOL/CPHA 0..3) MSB-first SPI master used by
//   * the generic SPI0 peripheral (0xF050) for external devices, and
//   * the SPI flash controller (0xF060) / hardware boot engine.
//
// Byte-stream interface:
//   * `start` (pulse) with `len` = number of bytes to transfer drives CS low.
//   * For every byte the engine waits for `tx_valid` (with `tx_data`) and
//     shifts it out MSB first.
//   * Every received byte is presented with `rx_valid` and must be accepted
//     with a one-cycle `rx_ack` before the engine continues (back-pressure).
//   * `done` pulses for one cycle after the last byte; CS returns high.
//
// Timing: SCLK half period = (clk_div + 1) system clocks. The engine uses four
// phases per bit (setup / leading edge / trailing edge / hold) so that data is
// stable around the sampling edge for all four SPI modes.
//
// Rev B: new module for the MCU (external flash + expansion bus support).

`timescale 1ns / 1ps

module sv16_spi_master (
    input  logic        clk,
    input  logic        rst_n,

    // Transaction control
    input  logic        start,       // pulse: begin transfer
    input  logic [7:0]  len,         // number of bytes (1..255)
    input  logic [1:0]  mode,        // {CPOL, CPHA}
    input  logic [15:0] clk_div,     // half period = clk_div + 1 clocks
    input  logic        cs_hold,     // keep CS asserted between transfers
                                     // (multi-chunk transactions)
    output logic        busy,
    output logic        done,        // pulse: transfer complete

    // TX byte stream (host -> SPI)
    input  logic [7:0]  tx_data,
    input  logic        tx_valid,
    output logic        tx_ready,
    output logic        tx_taken,    // pulse: tx_data was shifted into the shifter

    // RX byte stream (SPI -> host)
    output logic [7:0]  rx_data,
    output logic        rx_valid,
    input  logic        rx_ack,

    // Physical pins
    output logic        sck,
    output logic        mosi,
    input  logic        miso,
    output logic        cs_n
);

    typedef enum logic [2:0] {
        S_IDLE  = 3'd0,
        S_BSTART= 3'd1,   // wait for the first TX byte of a new byte
        S_SETUP = 3'd2,   // phase 0: mosi setup, sck idle
        S_LEAD  = 3'd3,   // phase 1: leading clock edge
        S_TRAIL = 3'd4,   // phase 2: trailing clock edge
        S_HOLD  = 3'd5,   // phase 3: bit complete
        S_WAIT  = 3'd6,   // wait for rx_ack before the next byte
        S_CSLOW = 3'd7    // transaction finished, CS held low for chaining
    } state_e;

    state_e      state;
    logic [7:0]  len_reg;
    logic [7:0]  byte_cnt;
    logic [2:0]  bit_idx;
    logic [7:0]  tx_shift;
    logic [7:0]  rx_shift;
    logic [15:0] phase_timer;   // counts half periods
    logic        sck_reg, mosi_reg, cs_reg;

    assign sck    = sck_reg;
    assign mosi   = mosi_reg;
    assign cs_n   = cs_reg;
    assign busy   = (state != S_IDLE) && (state != S_CSLOW);
    assign tx_ready = (state == S_BSTART);

    localparam logic [15:0] HALF_MAX = 16'hFFFF;

    logic [15:0] half_div;
    assign half_div = (clk_div == 16'd0) ? 16'd1 : clk_div;

    logic phase_tick;
    assign phase_tick = (phase_timer >= half_div - 16'd1);

    // Sample on the leading edge for CPHA=0, on the trailing edge for CPHA=1
    logic sample_phase;
    assign sample_phase = mode[0];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state       <= S_IDLE;
            len_reg     <= 8'd0;
            byte_cnt    <= 8'd0;
            bit_idx     <= 3'd0;
            tx_shift    <= 8'h00;
            rx_shift    <= 8'h00;
            phase_timer <= 16'd0;
            sck_reg     <= 1'b0;
            mosi_reg    <= 1'b0;
            cs_reg      <= 1'b1;
            done        <= 1'b0;
            rx_data     <= 8'h00;
            rx_valid    <= 1'b0;
            tx_taken    <= 1'b0;
        end else begin
            done     <= 1'b0;
            tx_taken <= 1'b0;

            // rx_valid is cleared when the host accepts the byte
            if (rx_valid && rx_ack) rx_valid <= 1'b0;

            case (state)
                S_IDLE: begin
                    sck_reg  <= mode[1];         // CPOL: idle clock level
                    cs_reg   <= 1'b1;
                    mosi_reg <= 1'b0;
                    if (start) begin
                        len_reg     <= (len == 8'd0) ? 8'd1 : len;
                        byte_cnt    <= 8'd0;
                        phase_timer <= 16'd0;
                        cs_reg      <= 1'b0;
                        state       <= S_BSTART;
                    end
                end

                S_BSTART: begin
                    if (tx_valid) begin
                        tx_taken    <= 1'b1;
                        tx_shift    <= tx_data;
                        mosi_reg    <= tx_data[7];   // MSB first
                        bit_idx     <= 3'd0;
                        phase_timer <= 16'd0;
                        state       <= S_SETUP;
                    end
                end

                S_SETUP: begin
                    // Clock idle (CPOL), data already valid on MOSI
                    sck_reg <= mode[1];
                    if (phase_tick) begin
                        phase_timer <= 16'd0;
                        state       <= S_LEAD;
                    end else begin
                        phase_timer <= phase_timer + 16'd1;
                    end
                end

                S_LEAD: begin
                    sck_reg <= ~mode[1];              // leading edge
                    if (phase_tick) begin
                        if (!sample_phase) begin      // CPHA = 0: sample now
                            rx_shift <= {rx_shift[6:0], miso};
                        end
                        phase_timer <= 16'd0;
                        state       <= S_TRAIL;
                    end else begin
                        phase_timer <= phase_timer + 16'd1;
                    end
                end

                S_TRAIL: begin
                    sck_reg <= mode[1];               // trailing edge
                    if (phase_tick) begin
                        if (sample_phase) begin       // CPHA = 1: sample now
                            rx_shift <= {rx_shift[6:0], miso};
                        end
                        phase_timer <= 16'd0;
                        state       <= S_HOLD;
                    end else begin
                        phase_timer <= phase_timer + 16'd1;
                    end
                end

                S_HOLD: begin
                    if (phase_tick) begin
                        phase_timer <= 16'd0;
                        if (bit_idx == 3'd7) begin
                            // Byte finished: publish TX/RX and move on
                            rx_data <= rx_shift;   // all 8 bits sampled
                            rx_valid <= 1'b1;
                            byte_cnt <= byte_cnt + 8'd1;
                            state    <= S_WAIT;
                        end else begin
                            bit_idx  <= bit_idx + 3'd1;
                            // Next bit on MOSI is set up before the next
                            // leading edge; shift left one position.
                            tx_shift <= {tx_shift[6:0], 1'b0};
                            mosi_reg <= tx_shift[6];
                            state    <= S_SETUP;
                        end
                    end else begin
                        phase_timer <= phase_timer + 16'd1;
                    end
                end

                S_WAIT: begin
                    if (!rx_valid || rx_ack) begin
                        if (byte_cnt >= len_reg) begin
                            sck_reg <= mode[1];
                            done   <= 1'b1;
                            if (cs_hold) begin
                                state <= S_CSLOW;   // keep CS asserted
                            end else begin
                                cs_reg <= 1'b1;
                                state  <= S_IDLE;
                            end
                        end else begin
                            state <= S_BSTART;
                        end
                    end
                end

                S_CSLOW: begin
                    // CS stays low: a follow-up transfer continues the
                    // same flash command (opcode/address/data phases).
                    sck_reg <= mode[1];
                    if (start) begin
                        len_reg     <= (len == 8'd0) ? 8'd1 : len;
                        byte_cnt    <= 8'd0;
                        phase_timer <= 16'd0;
                        state       <= S_BSTART;
                    end
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule : sv16_spi_master
