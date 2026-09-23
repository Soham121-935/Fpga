// SV-16 Rev B — SPI Flash Controller (persistent program storage)
// Module: sv16_flash_ctrl
//
// Gives the SV-16 MCU its non-volatile program store. It drives a standard
// JEDEC SPI NOR flash (any 25-series part, no vendor commands required):
//   * RDID(0x9F) / RDSR(0x05) / WREN(0x06) / WRDI(0x04) / RELEASE(0xAB)
//   * READ(0x03)         byte stream into an 8-byte RX FIFO, auto prefetch
//   * PAGE PROGRAM(0x02) 256-byte page buffer, automatic programming at flash
//                        page boundaries - firmware writes bytes, not pages
//   * SECTOR ERASE(0x20) / CHIP ERASE(0x60)
//   * hardware CRC16-CCITT over any region (firmware image verification)
//   * a boot-stream port consumed by the hardware boot engine (sv16_boot)
//
// Register map (BLK_FLASH = 0xF060, offsets defined in sv16_pkg):
//   0x0 FLASH_CMD     (WO) command code, see FCMD_* in sv16_pkg
//   0x1 FLASH_STAT    (RO) [7]SR.WIP [6]CRC_READY [5]PGM_BUSY [4]WEL
//                          [3]RD_READY [2]ID_OK [1]ERR [0]BUSY
//   0x2 FLASH_ADDR_LO (RW) byte address [15:0]
//   0x3 FLASH_ADDR_HI (RW) byte address [23:16]
//   0x4 FLASH_LEN     (RW) byte count for READ / WRITE / CRC
//   0x5 FLASH_DATA    (RW) write: byte into the page buffer
//                          read:  next received byte from the RX FIFO
//   0x6 FLASH_ID      (RO) {device type, manufacturer}
//   0x7 FLASH_ID2     (RO) {0x00, capacity}
//   0x8 FLASH_CRC_LO  (RO) CRC16 result [7:0]
//   0x9 FLASH_CRC_HI  (RO) CRC16 result [15:8]
//   0xA FLASH_CTRL    (RW) [3:0] SCLK divider (SCLK = clk/(2*(div+1)))
//                          [4] CPOL [5] CPHA
//   0xB FLASH_WRCNT   (RO) bytes held in the page buffer
//   0xC FLASH_SR      (RO) last flash status byte
//   0xD FLASH_TOTAL   (RO) bytes programmed since reset
//
// Programming contract (docs/PROGRAMMING_GUIDE.md):
//   1. FCMD_WR_ENABLE, poll STAT.BUSY
//   2. set ADDR_LO/HI and LEN, then FCMD_WRITE_START
//   3. write LEN bytes to FLASH_DATA - the controller inserts a bus wait state
//      if it has to flush a flash page while the CPU is writing
//   4. poll STAT.PGM_BUSY until clear (last page is flushed automatically)
//
// Bus protocol: single-cycle request pulse plus a shared acknowledge. The
// master holds address/data until it sees ack; this slave answers normal
// registers one cycle later and stalls FLASH_DATA writes until the byte is
// actually buffered.
//
// Rev B: new module (ADR-013).
//
// Implementation note: every register is assigned in exactly one always_ff
// block ("single owner" rule) — assigning the same signal from two blocks is
// illegal in SystemVerilog and yosys silently resolves such conflicts to a
// constant, which would break the controller.

`timescale 1ns / 1ps

import sv16_pkg::*;

module sv16_flash_ctrl (
    input  logic        clk,
    input  logic        rst_n,

    // CPU bus slave interface
    input  logic [3:0]  addr,
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    input  logic        req,
    input  logic        we,
    output logic        ack,

    // Boot-stream interface (used by sv16_boot)
    input  logic        boot_start,     // pulse: start streaming
    input  logic [23:0] boot_addr,      // flash byte address
    input  logic [15:0] boot_len,       // number of bytes to stream
    output logic        boot_valid,
    output logic [7:0]  boot_data,
    input  logic        boot_ack,       // consume the presented byte
    input  logic        boot_abort,     // cancel a not-yet-started request
    output logic        boot_busy,

    // Flash pins
    output logic        flash_sck,
    output logic        flash_cs_n,
    output logic        flash_mosi,
    input  logic        flash_miso,

    // Status
    output logic        flash_irq,      // pulse: CPU command completed
    output logic        id_ok,
    output logic [23:0] jedec_id
);

    // ------------------------------------------------------- Flash opcodes
    localparam logic [7:0] SPIF_WREN    = 8'h06,
                           SPIF_WRDI    = 8'h04,
                           SPIF_RDSR    = 8'h05,
                           SPIF_READ    = 8'h03,
                           SPIF_PP      = 8'h02,
                           SPIF_SE      = 8'h20,
                           SPIF_CE      = 8'h60,
                           SPIF_RDID    = 8'h9F,
                           SPIF_RELEASE = 8'hAB;

    // ------------------------------------------------------ Requester owner
    localparam logic [1:0] OWN_NONE = 2'd0,
                           OWN_CPU  = 2'd1,
                           OWN_PGM  = 2'd2,
                           OWN_BOOT = 2'd3;

    // ---------------------------------------------------- CPU command kind
    localparam logic [1:0] KIND_DATA = 2'd0,   // read into the RX FIFO
                           KIND_ID   = 2'd1,
                           KIND_SR   = 2'd2,
                           KIND_CRC  = 2'd3;

    localparam logic [7:0] CHUNK_MAX = 8'd192; // payload bytes per SPI chunk

    // ------------------------------------------------- Engine state encoding
    localparam logic [2:0] E_IDLE    = 3'd0,
                           E_WREN    = 3'd1,   // implicit write-enable preamble
                           E_OPCODE  = 3'd2,
                           E_ADDR    = 3'd3,
                           E_PAYLOAD = 3'd4,
                           E_FINISH  = 3'd5;

    // ------------------------------------------------- Page FSM state
    // P_POLL reads the flash status register and repeats until the device has
    // finished its previous internal program/erase. Real flash parts ignore
    // commands while WIP is set, so the sequencer waits before every WREN/PP.
    localparam logic [2:0] P_IDLE   = 3'd0,
                           P_POLL   = 3'd1,
                           P_POLL_W = 3'd2,
                           P_WREN   = 3'd3,
                           P_WREN_W = 3'd4,
                           P_PP     = 3'd5,
                           P_PP_W   = 3'd6,
                           P_UPDATE = 3'd7;

    // ------------------------------------------------------------- Registers
    logic [15:0] ctrl_reg, len_reg;
    logic [23:0] addr_reg;
    logic        err_flag, busy_flag, wel_flag;
    logic [15:0] prog_total;

    logic [2:0]  estate;
    logic [1:0]  owner;
    logic        eng_busy, eng_done, ph_go, just_done;
    logic [7:0]  d_opcode;
    logic [1:0]  d_kind;
    logic        d_addr_en, d_dir_rd, d_src_buf, d_crc, d_pre_wren;
    logic [15:0] d_len, e_sent;
    logic [23:0] d_addr;
    logic [7:0]  e_chunk, e_src_idx, e_addr_idx;
    logic        spi_start, spi_cs_hold;
    logic [7:0]  spi_len;

    logic [2:0]  pstate;
    logic [8:0]  p_total, p_off;
    logic [23:0] p_base;
    logic        pgm_busy;
    logic [8:0]  pp_chunk;              // bytes in the page program in flight
    logic        pgm_done, pgm_flush_done;
    // page-program request descriptor (combinational, selected by pstate)
    logic        pq_valid;
    logic [7:0]  pq_opcode;
    logic        pq_addr_en, pq_src_buf;
    logic [1:0]  pq_kind;
    logic [15:0] pq_len;
    logic [23:0] pq_addr;
    logic [7:0]  pq_src_off;

    logic        bq_valid;
    logic [23:0] bq_addr;
    logic [15:0] bq_len;

    logic [7:0]  page_buf [0:255];
    logic [8:0]  page_wr_ptr;
    logic [23:0] page_base;
    logic        wr_active, flush_pending, dw_pending;
    logic        dw_serviced, dr_serviced;
    logic        dr_is_data, dr_ready, dr_streaming, dr_pop;
    logic        dr_pending, ack_dr, dr_sel, dr_sel_q;
    logic        rd_stream_active;
    logic [7:0]  data_rd_reg;
    logic [15:0] wr_bytes_left;
    logic        ack_dw, ack_reg;

    logic [7:0]  rd_fifo [0:7];
    logic [2:0]  rd_wr_ptr, rd_rd_ptr;
    logic [3:0]  rd_used;

    logic [7:0]  id_bytes [0:2];
    logic        id_ok_reg;
    logic [2:0]  id_rx_idx;
    logic [7:0]  sr_reg;

    logic [15:0] crc_reg;
    logic        crc_ready;
    logic        crc_init, crc_en;
    logic [15:0] crc_val;

    logic        cpu_req_pend;
    logic [7:0]  cq_opcode;
    logic [1:0]  cq_kind;
    logic        cq_addr_en, cq_dir_rd, cq_pre_wren;
    logic [15:0] cq_len;
    logic [23:0] cq_addr;

    // ------------------------------------------------------- SPI + CRC core
    logic        spi_busy, spi_done, spi_tx_ready, spi_tx_taken;
    logic        spi_tx_valid, spi_rx_valid, spi_rx_ack;
    logic [7:0]  spi_tx_data, spi_rx_data;
    logic [15:0] spi_half_div;

    assign spi_half_div = {11'd0, ctrl_reg[3:0]} + 16'd1;

    sv16_spi_master u_spi (
        .clk(clk), .rst_n(rst_n),
        .start(spi_start), .len(spi_len), .mode(ctrl_reg[5:4]),
        .clk_div(spi_half_div), .cs_hold(spi_cs_hold),
        .busy(spi_busy), .done(spi_done),
        .tx_data(spi_tx_data), .tx_valid(spi_tx_valid), .tx_ready(spi_tx_ready),
        .tx_taken(spi_tx_taken),
        .rx_data(spi_rx_data), .rx_valid(spi_rx_valid), .rx_ack(spi_rx_ack),
        .sck(flash_sck), .mosi(flash_mosi), .miso(flash_miso), .cs_n(flash_cs_n)
    );

    sv16_crc16 u_crc (
        .clk(clk), .rst_n(rst_n),
        .crc_init(crc_init), .crc_en(crc_en), .crc_data(spi_rx_data),
        .crc_out(crc_val)
    );

    // -------------------------------------------------- Combinational decode
    logic        cpu_cmd_pulse;
    logic [3:0]  cpu_cmd;
    logic        dw_is_data, dw_ok_now, dw_drop;
    logic        payload_rx_byte, id_rx_byte, sr_rx_byte, fifo_pop;
    logic        px_valid_any;
    logic        busy_any;

    assign cpu_cmd_pulse = req && we && (addr == FLASH_CMD);
    assign cpu_cmd       = wdata[3:0];

    // One bus transaction moves exactly one byte. A master holds `req` until
    // it sees `ack`, so each data port access is serviced once per request
    // (see dw_serviced / dr_serviced below): without that arbitration a held
    // request would store or pop the same byte on every clock.
    assign dw_is_data = req && we && (addr == FLASH_DATA) && !dw_serviced;
    assign dw_ok_now  = wr_active && (wr_bytes_left != 16'd0) &&
                        (page_wr_ptr != 9'd256) && !pgm_busy;
    assign dw_drop    = !wr_active || (wr_bytes_left == 16'd0);

    assign busy_any = busy_flag || eng_busy || pgm_busy || cq_valid_any ||
                      pq_valid || bq_valid;

    assign pgm_done = eng_done && (owner == OWN_PGM);

    // completed a payload transfer (drives the RX routing decisions)
    assign payload_rx_byte = spi_rx_valid && spi_rx_ack && (estate == E_PAYLOAD);
    assign id_rx_byte      = payload_rx_byte && (owner == OWN_CPU) && (d_kind == KIND_ID);
    assign sr_rx_byte      = payload_rx_byte && (d_kind == KIND_SR);
    // A data read is serviced the moment a byte is available.  While a read
    // stream is in flight and its FIFO is still empty (the SPI transfer has not
    // produced a byte yet) the read is parked in dr_pending and the bus
    // acknowledge is withheld: the CPU's memory state simply waits, instead of
    // sampling stale data.  Without that wait state the first byte handed back
    // to firmware was the leftover in data_rd_reg, which shifted every streamed
    // read - and every CRC computed from it - by one byte.
    assign dr_is_data      = req && !we && (addr == FLASH_DATA) && !dr_serviced;
    assign dr_ready        = (rd_used != 4'd0);
    // A sticky flag that says "a streaming read is in flight".  It is raised
    // when the read is commanded and lowered only once the controller is
    // quiescent and its FIFO is empty, i.e. when no further byte can arrive.
    // A data read that arrives meanwhile has to wait for its byte instead of
    // sampling whatever happens to be in the output register.
    assign dr_streaming    = rd_stream_active;
    assign dr_pop          = ((dr_is_data && !dr_serviced) || dr_pending) && dr_ready;
    assign fifo_pop        = dr_pop;

    // occupancy taken from the FIFO owner block
    logic fifo_full;
    assign fifo_full = (rd_used == 4'd8);

    // Only DATA reads are buffered for the CPU; ID, status and CRC reads are
    // consumed immediately by their own logic (a CRC stream must never stall
    // on FIFO occupancy).
    logic fifo_push;
    assign fifo_push = payload_rx_byte && (owner == OWN_CPU) &&
                       (d_kind == KIND_DATA);

    // ------------------------------------------------------- Bus acknowledge
    // (BLK A) ack_reg / ack_dw owners
    //
    // The CPU issues a single-cycle request pulse and then waits for the
    // acknowledge, so the acknowledge source has to be remembered too: using
    // the live dw_is_data would drop back to the register acknowledge one cycle
    // later -- exactly when the data-port acknowledge arrives -- and a store to
    // FLASH_DATA would never complete (the CPU would sit in its memory state
    // forever, which is what real firmware hit the moment it programmed a byte).
    logic dw_sel, dw_sel_q;
    assign dw_sel = dw_is_data || dw_pending;
    assign dr_sel = dr_is_data || dr_pending;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            dw_sel_q <= 1'b0;
            dr_sel_q <= 1'b0;
        end else begin
            dw_sel_q <= dw_sel;
            dr_sel_q <= dr_sel;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) ack_reg <= 1'b0;
        // Register accesses only: FLASH_DATA is answered exclusively by the
        // data port, otherwise a second cycle of a held data request would
        // pick up a register acknowledge with stale read data.
        else        ack_reg <= req && (addr != FLASH_DATA);
    end

    always_comb begin
        if      (dw_sel_q) ack = ack_dw;
        else if (dr_sel_q) ack = ack_dr;
        else               ack = ack_reg;
    end

    // ------------------------------------ BLK B: data/page-buffer write path
    // Owns: page_buf, page_wr_ptr, page_base, wr_active, wr_bytes_left,
    //       flush_pending, dw_pending, ack_dw

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            page_wr_ptr    <= 9'd0;
            page_base      <= 24'd0;
            wr_active      <= 1'b0;
            wr_bytes_left  <= 16'd0;
            flush_pending  <= 1'b0;
            dw_pending     <= 1'b0;
            dw_serviced    <= 1'b0;
            ack_dw         <= 1'b0;
        end else begin
            ack_dw <= 1'b0;

            // ---- start a write session ----
            if (cpu_cmd_pulse && (cpu_cmd == FCMD_WRITE_START) && !busy_any) begin
                wr_active     <= 1'b1;
                wr_bytes_left <= len_reg;
                page_wr_ptr   <= 9'd0;
                page_base     <= addr_reg;
                flush_pending <= 1'b0;
            end

            // ---- explicit flush request ----
            if (cpu_cmd_pulse && (cpu_cmd == FCMD_FLUSH) && !busy_any) begin
                if (page_wr_ptr != 9'd0) flush_pending <= 1'b1;
            end

            // ---- byte buffering (with bus wait states) ----
            // A byte that cannot be buffered yet (the page buffer is full while
            // a program is running) is remembered in dw_pending and
            // acknowledged later, when the page sequencer has made room: that
            // is the wait state the CPU's memory state waits for.  The CPU
            // holds wdata stable while it waits, so the byte is captured when
            // it is finally accepted.
            if (!req) dw_serviced <= 1'b0;

            if (dw_is_data && !dw_pending && dw_ok_now) begin
                page_buf[page_wr_ptr[7:0]] <= wdata[7:0];
                page_wr_ptr   <= page_wr_ptr + 9'd1;
                wr_bytes_left <= wr_bytes_left - 16'd1;
                ack_dw        <= 1'b1;
                dw_serviced   <= 1'b1;
            end else if (dw_is_data && !dw_pending) begin
                if (dw_drop) begin
                    ack_dw      <= 1'b1;   // discarded; ERR is set by BLK H
                    dw_serviced <= 1'b1;
                end else begin
                    dw_pending  <= 1'b1;   // wait for room in the page buffer
                    dw_serviced <= 1'b1;
                end
            end else if (dw_pending && dw_ok_now) begin
                page_buf[page_wr_ptr[7:0]] <= wdata[7:0];
                page_wr_ptr   <= page_wr_ptr + 9'd1;
                wr_bytes_left <= wr_bytes_left - 16'd1;
                ack_dw        <= 1'b1;
                dw_pending    <= 1'b0;
            end else if (dw_pending && dw_drop) begin
                ack_dw     <= 1'b1;        // discarded; ERR is set by BLK H
                dw_pending <= 1'b0;
            end

            // ---- the whole buffer has been programmed into the flash ----
            if (pgm_flush_done) begin
                page_base     <= p_base + {15'd0, p_total};
                page_wr_ptr   <= 9'd0;
                flush_pending <= 1'b0;
                if (wr_active && (wr_bytes_left == 16'd0)) wr_active <= 1'b0;
            end
        end
    end

    // ------------------------------------- BLK C: page program sequencer
    // Owns: pstate, p_total, p_off, p_base, pp_chunk, pgm_busy, prog_total
    //
    // A flush programs `p_total` bytes sitting in the page buffer. The buffer
    // can span a 256-byte flash page boundary, so the sequence is split into
    // page-safe chunks (never crossing a page) with WREN + PP per chunk and a
    // status poll before each one.
    logic [8:0] pp_room;
    logic       flush_cond, sr_wip;

    assign pp_room = 9'd256 - {1'b0, (p_base[7:0] + p_off[7:0])};

    // bytes available in the buffer for this flush pass
    logic [8:0] pp_avail;
    assign pp_avail = p_total - p_off;

    assign flush_cond = !pgm_busy && (page_wr_ptr != 9'd0) &&
                        ((page_wr_ptr == 9'd256) ||
                         flush_pending ||
                         (wr_active && (wr_bytes_left == 16'd0)));

    assign sr_wip = sr_reg[0];

    // descriptor for whichever step the sequencer is in
    always_comb begin
        case (pstate)
            P_POLL: begin
                pq_valid   = 1'b1;
                pq_kind    = KIND_SR;
                pq_opcode  = SPIF_RDSR;
                pq_addr_en = 1'b0;
                pq_src_buf = 1'b0;
                pq_len     = 16'd1;
                pq_addr    = 24'd0;
                pq_src_off = 8'd0;
            end
            P_WREN: begin
                pq_valid   = 1'b1;
                pq_kind    = KIND_DATA;
                pq_opcode  = SPIF_WREN;
                pq_addr_en = 1'b0;
                pq_src_buf = 1'b0;
                pq_len     = 16'd0;
                pq_addr    = 24'd0;
                pq_src_off = 8'd0;
            end
            P_PP: begin
                pq_valid   = 1'b1;
                pq_kind    = KIND_DATA;
                pq_opcode  = SPIF_PP;
                pq_addr_en = 1'b1;
                pq_src_buf = 1'b1;
                pq_len     = {7'd0, pp_chunk};
                pq_addr    = p_base + {15'd0, p_off};
                pq_src_off = p_off[7:0];
            end
            default: begin
                pq_valid   = 1'b0;
                pq_kind    = KIND_DATA;
                pq_opcode  = 8'h00;
                pq_addr_en = 1'b0;
                pq_src_buf = 1'b0;
                pq_len     = 16'd0;
                pq_addr    = 24'd0;
                pq_src_off = 8'd0;
            end
        endcase
    end

    // bytes of this flush pass that fit in the current flash page
    always_comb begin
        pp_chunk = (pp_avail < pp_room) ? pp_avail : pp_room;
        if (pp_chunk == 9'd0) pp_chunk = 9'd1;
    end

    assign pgm_flush_done = pgm_done && (pstate == P_PP_W) &&
                            ((p_off + pp_chunk) >= p_total);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pstate    <= P_IDLE;
            p_total   <= 9'd0;
            p_off     <= 9'd0;
            p_base    <= 24'd0;
            pgm_busy  <= 1'b0;
            prog_total<= 16'd0;
        end else begin
            if (pgm_done) prog_total <= prog_total + {7'd0, pp_chunk};

            case (pstate)
                P_IDLE: begin
                    if (flush_cond) begin
                        p_total  <= page_wr_ptr;
                        p_base   <= page_base;
                        p_off    <= 9'd0;
                        pgm_busy <= 1'b1;
                        pstate   <= P_POLL;
                    end
                end

                P_POLL:   pstate <= P_POLL_W;

                P_POLL_W: begin
                    if (pgm_done) pstate <= sr_wip ? P_POLL : P_WREN;
                end

                P_WREN:   pstate <= P_WREN_W;

                P_WREN_W: begin
                    if (pgm_done) pstate <= P_PP;
                end

                P_PP:     pstate <= P_PP_W;

                P_PP_W: begin
                    if (pgm_done) begin
                        if ((p_off + pp_chunk) >= p_total) begin
                            pgm_busy <= 1'b0;
                            pstate   <= P_UPDATE;
                        end else begin
                            p_off  <= p_off + pp_chunk;
                            pstate <= P_POLL;
                        end
                    end
                end

                P_UPDATE: begin
                    // tell the buffer owner that the flush finished
                    pgm_busy <= 1'b0;
                    pstate   <= P_IDLE;
                end

                default: pstate <= P_IDLE;
            endcase
        end
    end

    // ------------------------------------------------- BLK D: SPI sequencer
    // Owns: estate, owner, eng_busy, eng_done, descriptor, counters, CS/start
    logic [15:0] payload_remaining;
    logic [7:0]  chunk_calc;
    logic [7:0]  last_addr_byte;

    assign payload_remaining = d_len - e_sent;

    always_comb begin
        chunk_calc = (payload_remaining > {8'd0, CHUNK_MAX}) ? CHUNK_MAX
                                                             : payload_remaining[7:0];
        if (chunk_calc == 8'd0) chunk_calc = 8'd1;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            estate      <= E_IDLE;
            owner       <= OWN_NONE;
            eng_busy    <= 1'b0;
            eng_done    <= 1'b0;
            just_done   <= 1'b0;
            ph_go       <= 1'b0;
            d_opcode    <= 8'h00;
            d_kind      <= KIND_DATA;
            d_addr_en   <= 1'b0;
            d_dir_rd    <= 1'b0;
            d_src_buf   <= 1'b0;
            d_crc       <= 1'b0;
            d_pre_wren  <= 1'b0;
            d_len       <= 16'd0;
            d_addr      <= 24'd0;
            e_sent      <= 16'd0;
            e_chunk     <= 8'd0;
            e_src_idx   <= 8'd0;
            e_addr_idx  <= 8'd0;
            spi_start   <= 1'b0;
            spi_len     <= 8'd1;
            spi_cs_hold <= 1'b0;
        end else begin
            eng_done  <= 1'b0;
            spi_start <= 1'b0;
            just_done <= 1'b0;

            // descriptor index counters advance with the shifted bytes
            if (spi_tx_taken) begin
                if (estate == E_ADDR)         e_addr_idx <= e_addr_idx + 8'd1;
                else if (estate == E_PAYLOAD) e_src_idx  <= e_src_idx + 8'd1;
            end

            case (estate)
                E_IDLE: begin
                    ph_go <= 1'b0;
                    // `just_done` keeps the engine quiet for one cycle after a
                    // transfer so the completed requester can lower its valid
                    // flag before a new descriptor is latched.
                    if (!eng_busy && !just_done) begin
                        // priority: boot stream > page program > CPU
                        if (bq_valid) begin
                            d_opcode  <= SPIF_READ;
                            d_addr_en <= 1'b1;
                            d_dir_rd  <= 1'b1;
                            d_src_buf <= 1'b0;
                            d_crc     <= 1'b0;
                            d_kind    <= KIND_DATA;
                            d_pre_wren<= 1'b0;
                            d_len     <= bq_len;
                            d_addr    <= bq_addr;
                            owner     <= OWN_BOOT;
                            eng_busy  <= 1'b1;
                            e_sent    <= 16'd0;
                            e_addr_idx<= 8'd0;
                            estate    <= E_OPCODE;
                        end else if (pq_valid) begin
                            d_opcode  <= pq_opcode;
                            d_addr_en <= pq_addr_en;
                            d_dir_rd  <= 1'b0;
                            d_src_buf <= pq_src_buf;
                            d_crc     <= 1'b0;
                            d_kind    <= pq_kind;
                            d_pre_wren<= 1'b0;
                            d_len     <= pq_len;
                            d_addr    <= pq_addr;
                            e_src_idx <= pq_src_off;
                            owner     <= OWN_PGM;
                            eng_busy  <= 1'b1;
                            e_sent    <= 16'd0;
                            e_addr_idx<= 8'd0;
                            estate    <= E_OPCODE;
                        end else if (cpu_req_pend) begin
                            d_opcode  <= cq_opcode;
                            d_addr_en <= cq_addr_en;
                            d_dir_rd  <= cq_dir_rd;
                            d_src_buf <= 1'b0;
                            d_crc     <= (cq_kind == KIND_CRC);
                            d_kind    <= cq_kind;
                            d_pre_wren<= cq_pre_wren;
                            d_len     <= cq_len;
                            d_addr    <= cq_addr;
                            owner     <= OWN_CPU;
                            eng_busy  <= 1'b1;
                            e_sent    <= 16'd0;
                            e_addr_idx<= 8'd0;
                            estate    <= cq_pre_wren ? E_WREN : E_OPCODE;
                        end
                    end
                end

                E_WREN: begin
                    if (!ph_go) begin
                        if (!spi_busy && !spi_start) begin
                            spi_len     <= 8'd1;
                            spi_cs_hold <= 1'b0;
                            spi_start   <= 1'b1;
                            ph_go       <= 1'b1;
                        end
                    end else if (spi_done) begin
                        ph_go  <= 1'b0;
                        estate <= E_OPCODE;
                    end
                end

                E_OPCODE: begin
                    if (!ph_go) begin
                        if (!spi_busy && !spi_start) begin
                            spi_len     <= 8'd1;
                            spi_cs_hold <= (d_addr_en || (d_len != 16'd0));
                            spi_start   <= 1'b1;
                            ph_go       <= 1'b1;
                        end
                    end else if (spi_done) begin
                        ph_go <= 1'b0;
                        if (d_addr_en)           estate <= E_ADDR;
                        else if (d_len != 16'd0) estate <= E_PAYLOAD;
                        else                     estate <= E_FINISH;
                    end
                end

                E_ADDR: begin
                    if (!ph_go) begin
                        if (!spi_busy && !spi_start) begin
                            spi_len     <= 8'd3;
                            spi_cs_hold <= (d_len != 16'd0);
                            spi_start   <= 1'b1;
                            ph_go       <= 1'b1;
                        end
                    end else if (spi_done) begin
                        ph_go  <= 1'b0;
                        estate <= (d_len != 16'd0) ? E_PAYLOAD : E_FINISH;
                    end
                end

                E_PAYLOAD: begin
                    if (!ph_go) begin
                        if (!spi_busy && !spi_start) begin
                            e_chunk     <= chunk_calc;
                            spi_len     <= chunk_calc;
                            spi_cs_hold <= ((e_sent + {8'd0, chunk_calc}) < d_len);
                            spi_start   <= 1'b1;
                            ph_go       <= 1'b1;
                        end
                    end else if (spi_done) begin
                        ph_go  <= 1'b0;
                        e_sent <= e_sent + {8'd0, e_chunk};
                        if ((e_sent + {8'd0, e_chunk}) >= d_len) estate <= E_FINISH;
                    end
                end

                E_FINISH: begin
                    if (!spi_busy && !spi_rx_valid) begin
                        eng_busy  <= 1'b0;
                        eng_done  <= 1'b1;
                        just_done <= 1'b1;
                        estate    <= E_IDLE;
                    end
                end

                default: estate <= E_IDLE;
            endcase
        end
    end

    assign last_addr_byte = (e_addr_idx == 8'd0) ? d_addr[23:16] :
                            (e_addr_idx == 8'd1) ? d_addr[15:8]  :
                                                   d_addr[7:0];

    always_comb begin
        spi_tx_valid = 1'b0;
        spi_tx_data  = 8'hFF;
        case (estate)
            E_WREN:    begin spi_tx_valid = 1'b1; spi_tx_data = SPIF_WREN; end
            E_OPCODE:  begin spi_tx_valid = 1'b1; spi_tx_data = d_opcode; end
            E_ADDR:    begin spi_tx_valid = 1'b1; spi_tx_data = last_addr_byte; end
            E_PAYLOAD: begin
                spi_tx_valid = 1'b1;
                spi_tx_data  = d_src_buf ? page_buf[e_src_idx] : 8'hFF;
            end
            default: ;
        endcase
    end

    // ------------------------------------------------- BLK E: RX byte FIFO
    // Owns: rd_fifo, rd_wr_ptr, rd_rd_ptr, rd_used
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rd_wr_ptr   <= 3'd0;
            rd_rd_ptr   <= 3'd0;
            rd_used     <= 4'd0;
            dr_serviced <= 1'b0;
            dr_pending        <= 1'b0;
            ack_dr            <= 1'b0;
            rd_stream_active  <= 1'b0;
            data_rd_reg       <= 8'h00;
        end else begin
            if (!req) dr_serviced <= 1'b0;
            ack_dr <= 1'b0;            // the acknowledge is a one-cycle pulse

            // ---- data reads, with bus wait states ----
            // Taking a byte out of the FIFO latches it into the output
            // register; the acknowledge is registered on the same edge, so both
            // become valid together in the next cycle - the cycle a master sees
            // as valid (acknowledge high, rdata valid).
            if (dr_pop) begin
                ack_dr     <= 1'b1;
                dr_pending <= 1'b0;
            end else if (dr_is_data && !dr_pending && !dr_ready) begin
                if (dr_streaming) begin
                    dr_pending  <= 1'b1;   // wait for the next SPI byte
                    dr_serviced <= 1'b1;
                end else begin
                    ack_dr      <= 1'b1;   // no stream: report the last byte
                    dr_serviced <= 1'b1;
                end
            end

            // ---- streaming-read bookkeeping ----
            if (cpu_cmd_pulse && (cpu_cmd == FCMD_READ_START)) rd_stream_active <= 1'b1;
            else if (rd_stream_active && !cpu_req_pend && !eng_busy &&
                     !fifo_push && (rd_used == 4'd0)) rd_stream_active <= 1'b0;

            if (fifo_push && !fifo_full) begin
                rd_fifo[rd_wr_ptr] <= spi_rx_data;
                rd_wr_ptr <= rd_wr_ptr + 3'd1;
            end
            if (fifo_pop) begin
                // latch the byte so it stays stable for the whole bus access
                data_rd_reg <= rd_fifo[rd_rd_ptr];
                rd_rd_ptr   <= rd_rd_ptr + 3'd1;
                dr_serviced <= 1'b1;
            end

            case ({fifo_push && !fifo_full, fifo_pop})
                2'b10:   rd_used <= rd_used + 4'd1;
                2'b01:   rd_used <= rd_used - 4'd1;
                default: ;
            endcase
        end
    end

    // ------------------------------------------- BLK F: RDID / RDSR capture
    // Owns: id_bytes, id_ok_reg, id_rx_idx, sr_reg
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            id_bytes[0] <= 8'h00;
            id_bytes[1] <= 8'h00;
            id_bytes[2] <= 8'h00;
            id_ok_reg   <= 1'b0;
            id_rx_idx   <= 3'd0;
            sr_reg      <= 8'h00;
        end else begin
            if (cpu_cmd_pulse && (cpu_cmd == FCMD_READ_ID)) begin
                id_ok_reg <= 1'b0;
                id_rx_idx <= 3'd0;
            end

            if (id_rx_byte) begin
                case (id_rx_idx)
                    3'd0:    id_bytes[0] <= spi_rx_data;
                    3'd1:    id_bytes[1] <= spi_rx_data;
                    3'd2:    id_bytes[2] <= spi_rx_data;
                    default: ;
                endcase
                if (id_rx_idx == 3'd2) id_ok_reg <= 1'b1;
                id_rx_idx <= id_rx_idx + 3'd1;
            end

            if (sr_rx_byte) sr_reg <= spi_rx_data;
        end
    end

    // ---------------------------------------------------- BLK G: CRC result
    // Owns: crc_reg, crc_ready
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            crc_reg   <= 16'hFFFF;
            crc_ready <= 1'b0;
        end else begin
            if (crc_init) crc_ready <= 1'b0;
            if (eng_done && (owner == OWN_CPU) && (d_kind == KIND_CRC)) begin
                crc_reg   <= crc_val;
                crc_ready <= 1'b1;
            end
        end
    end

    always_comb begin
        crc_init = cpu_cmd_pulse && (cpu_cmd == FCMD_CRC_START) && !busy_any;
        crc_en   = payload_rx_byte && (owner == OWN_CPU) && (d_kind == KIND_CRC);
    end

    // ------------------------------------------------------ BLK H: control
    // Owns: ctrl_reg, addr_reg, len_reg, err_flag, busy_flag, wel_flag, cq_*
    logic cq_valid_any;
    assign cq_valid_any = cpu_req_pend;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ctrl_reg     <= 16'h0001;      // SCLK divider -> 6.25 MHz
            addr_reg     <= 24'd0;
            len_reg      <= 16'd0;
            err_flag     <= 1'b0;
            busy_flag    <= 1'b0;
            wel_flag     <= 1'b0;          // unknown until WREN or RDSR
            cpu_req_pend <= 1'b0;
            cq_opcode    <= 8'h00;
            cq_kind      <= KIND_DATA;
            cq_addr_en   <= 1'b0;
            cq_dir_rd    <= 1'b0;
            cq_pre_wren  <= 1'b0;
            cq_len       <= 16'd0;
            cq_addr      <= 24'd0;
        end else begin
            // plain configuration registers
            if (req && we) begin
                case (addr)
                    FLASH_ADDR_LO: addr_reg <= {addr_reg[23:16], wdata};
                    FLASH_ADDR_HI: addr_reg <= {wdata[7:0], addr_reg[15:0]};
                    FLASH_LEN:     len_reg  <= wdata;
                    FLASH_CTRL:    ctrl_reg <= wdata;
                    default: ;
                endcase
            end

            // rejected writes to FLASH_DATA outside a session set ERR
            if ((dw_is_data && !dw_pending && dw_drop) ||
                (dw_pending && dw_drop)) err_flag <= 1'b1;

            // a status-register read reports the real write-enable latch
            if (sr_rx_byte) wel_flag <= spi_rx_data[1];

            // command dispatch
            if (cpu_cmd_pulse) begin
                if (busy_any) begin
                    err_flag <= 1'b1;                 // controller busy
                end else begin
                    err_flag <= 1'b0;
                    case (cpu_cmd)
                        FCMD_NOP: ;
                        FCMD_READ_ID: begin
                            cpu_req_pend <= 1'b1;
                            cq_pre_wren  <= 1'b0;
                            cq_kind      <= KIND_ID;
                            cq_opcode    <= SPIF_RDID;
                            cq_addr_en   <= 1'b0;
                            cq_dir_rd    <= 1'b1;
                            cq_len       <= 16'd3;
                            cq_addr      <= 24'd0;
                        end
                        FCMD_READ_START: begin
                            cpu_req_pend <= 1'b1;
                            cq_pre_wren  <= 1'b0;
                            cq_kind      <= KIND_DATA;
                            cq_opcode    <= SPIF_READ;
                            cq_addr_en   <= 1'b1;
                            cq_dir_rd    <= 1'b1;
                            cq_len       <= len_reg;
                            cq_addr      <= addr_reg;
                        end
                        FCMD_CRC_START: begin
                            cpu_req_pend <= 1'b1;
                            cq_pre_wren  <= 1'b0;
                            cq_kind      <= KIND_CRC;
                            cq_opcode    <= SPIF_READ;
                            cq_addr_en   <= 1'b1;
                            cq_dir_rd    <= 1'b1;
                            cq_len       <= len_reg;
                            cq_addr      <= addr_reg;
                        end
                        FCMD_ERASE_SECT: begin
                            cpu_req_pend <= 1'b1;
                            cq_pre_wren  <= 1'b1;
                            cq_kind      <= KIND_DATA;
                            cq_opcode    <= SPIF_SE;
                            cq_addr_en   <= 1'b1;
                            cq_dir_rd    <= 1'b0;
                            cq_len       <= 16'd0;
                            cq_addr      <= addr_reg;
                        end
                        FCMD_ERASE_CHIP: begin
                            cpu_req_pend <= 1'b1;
                            cq_pre_wren  <= 1'b1;
                            cq_kind      <= KIND_DATA;
                            cq_opcode    <= SPIF_CE;
                            cq_addr_en   <= 1'b0;
                            cq_dir_rd    <= 1'b0;
                            cq_len       <= 16'd0;
                            cq_addr      <= 24'd0;
                        end
                        FCMD_READ_SR: begin
                            cpu_req_pend <= 1'b1;
                            cq_pre_wren  <= 1'b0;
                            cq_kind      <= KIND_SR;
                            cq_opcode    <= SPIF_RDSR;
                            cq_addr_en   <= 1'b0;
                            cq_dir_rd    <= 1'b1;
                            cq_len       <= 16'd1;
                            cq_addr      <= 24'd0;
                        end
                        FCMD_WR_ENABLE: begin
                            cpu_req_pend <= 1'b1;
                            cq_pre_wren  <= 1'b0;
                            cq_kind      <= KIND_DATA;
                            cq_opcode    <= SPIF_WREN;
                            cq_addr_en   <= 1'b0;
                            cq_dir_rd    <= 1'b0;
                            cq_len       <= 16'd0;
                            cq_addr      <= 24'd0;
                            wel_flag     <= 1'b1;
                        end
                        FCMD_WR_DISABLE: begin
                            cpu_req_pend <= 1'b1;
                            cq_pre_wren  <= 1'b0;
                            cq_kind      <= KIND_DATA;
                            cq_opcode    <= SPIF_WRDI;
                            cq_addr_en   <= 1'b0;
                            cq_dir_rd    <= 1'b0;
                            cq_len       <= 16'd0;
                            cq_addr      <= 24'd0;
                            wel_flag     <= 1'b0;
                        end
                        FCMD_RELEASE: begin
                            cpu_req_pend <= 1'b1;
                            cq_pre_wren  <= 1'b0;
                            cq_kind      <= KIND_DATA;
                            cq_opcode    <= SPIF_RELEASE;
                            cq_addr_en   <= 1'b0;
                            cq_dir_rd    <= 1'b0;
                            cq_len       <= 16'd0;
                            cq_addr      <= 24'd0;
                        end
                        FCMD_WRITE_START, FCMD_FLUSH: ;  // handled by BLK B
                        default: err_flag <= 1'b1;
                    endcase
                    if ((cpu_cmd == FCMD_WRITE_START) || (cpu_cmd == FCMD_FLUSH))
                        busy_flag <= 1'b0;
                    else if (cpu_cmd != FCMD_NOP)
                        busy_flag <= 1'b1;
                end
            end

            // request handshake with the engine
            if (eng_busy && (owner == OWN_CPU)) cpu_req_pend <= 1'b0;
            if (eng_done && (owner == OWN_CPU)) begin
                cpu_req_pend <= 1'b0;
                busy_flag    <= 1'b0;
            end
        end
    end

    // ------------------------------------- BLK I: boot stream request latch
    // Owns: bq_valid, bq_addr, bq_len
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            bq_valid <= 1'b0;
            bq_addr  <= 24'd0;
            bq_len   <= 16'd0;
        end else begin
            // A new request always survives the completion of the previous
            // one: the boot loader issues its next stream in the same cycle
            // the engine retires the current one, and a plain
            // "clear on eng_done" would swallow it.
            if (boot_abort && !eng_busy && !boot_start) bq_valid <= 1'b0;
            else if (eng_done && (owner == OWN_BOOT) && !boot_start) bq_valid <= 1'b0;
            if (boot_start) begin
                bq_valid <= 1'b1;
                bq_addr  <= boot_addr;
                bq_len   <= (boot_len == 16'd0) ? 16'd1 : boot_len;
            end
        end
    end

    // ------------------------------------------------------------ Read path
    always_comb begin
        rdata = 16'h0000;
        case (addr)
            FLASH_STAT:    rdata = {8'h00, sr_reg[0], crc_ready, pgm_busy,
                                    wel_flag, (rd_used != 4'd0), id_ok_reg,
                                    err_flag, busy_any};
            FLASH_ADDR_LO: rdata = addr_reg[15:0];
            FLASH_ADDR_HI: rdata = {8'h00, addr_reg[23:16]};
            FLASH_LEN:     rdata = len_reg;
            FLASH_DATA:    rdata = {8'h00, data_rd_reg};
            FLASH_ID:      rdata = {id_bytes[1], id_bytes[0]};
            FLASH_ID2:     rdata = {8'h00, id_bytes[2]};
            FLASH_CRC_LO:  rdata = {8'h00, crc_reg[7:0]};
            FLASH_CRC_HI:  rdata = {8'h00, crc_reg[15:8]};
            FLASH_CTRL:    rdata = ctrl_reg;
            FLASH_WRCNT:   rdata = {7'd0, page_wr_ptr};
            FLASH_SR:      rdata = {8'h00, sr_reg};
            FLASH_TOTAL:   rdata = prog_total;
            default:       rdata = 16'h0000;
        endcase
    end

    // ------------------------------------------------------------- Outputs
    assign boot_valid = (owner == OWN_BOOT) && spi_rx_valid && (estate == E_PAYLOAD);
    assign boot_data  = spi_rx_data;
    assign boot_busy  = bq_valid || ((owner == OWN_BOOT) && eng_busy);
    assign id_ok      = id_ok_reg;
    assign jedec_id   = {id_bytes[0], id_bytes[1], id_bytes[2]};  // 0xEF4018
    assign flash_irq  = eng_done && (owner == OWN_CPU);

    // Receive back-pressure: the boot port must accept, the CPU FIFO needs
    // room, page-program data is discarded (and never acknowledged early).
    always_comb begin
        spi_rx_ack = 1'b0;
        if (spi_rx_valid) begin
            if (estate != E_PAYLOAD) begin
                spi_rx_ack = 1'b1;               // opcode/address bytes
            end else begin
                case (owner)
                    OWN_BOOT: spi_rx_ack = boot_ack;
                    OWN_CPU:  spi_rx_ack = !fifo_full || (d_kind != KIND_DATA);
                    default:  spi_rx_ack = 1'b1;
                endcase
            end
        end
    end

endmodule : sv16_flash_ctrl
