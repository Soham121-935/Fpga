// =====================================================================
// SV-16 Rev B -- hardware boot loader (SPI flash -> RAM -> CPU release)
//
// The loader is the SoC's second bus master (after the CPU).  On reset
// the startup sequencer holds the CPU in reset and pulses `boot_start`;
// the loader then:
//
//   1. streams the 32-byte image header from SPI flash through
//      sv16_flash_ctrl and checks magic / header CRC16 / image length,
//   2. latches entry address, stack pointer and payload length,
//   3. streams the payload and writes it into RAM over the system bus,
//      accumulating a CRC16 while the bytes arrive,
//   4. compares the payload CRC with the value in the header.
//
// A verified image raises `boot_ok` and the startup sequencer releases
// the CPU at `boot_entry`.  A missing or corrupt image raises
// BOOT_STAT.FAIL and the CPU is left in reset so the serial monitor can
// recover the part over UART.
//
// Register map (MMIO block 0xA0, see docs/MEMORY_MAP.md):
//   0x0 BOOT_CTRL   RW/W1P [0] START [1] ABORT [2] VERIFY-ONLY [3] AUTO
//   0x1 BOOT_STAT   RO     [0] BUSY [1] OK [2] FAIL [3] CRC_OK [4] MAGIC_OK
//   0x2 BOOT_SRC_LO RW     flash byte address [15:0]
//   0x3 BOOT_SRC_HI RW     flash byte address [23:16]
//   0x4 BOOT_SRC_LEN RW    header size override (0 = 32 bytes)
//   0x5 BOOT_ENTRY  RO     entry word address
//   0x6 BOOT_STACK  RO     initial stack pointer
//   0x7 BOOT_WORDS  RO     payload length in words
//   0x8 BOOT_CRC_EXP RO    payload CRC from the header
//   0x9 BOOT_CRC_ACT RO    payload CRC computed by the hardware
//   0xA BOOT_ERR    RO/W1C [0] magic [1] header CRC [2] payload CRC
//                          [3] stream timeout [4] length [5] flash
//                          [6] header version
//   0xB BOOT_MAGIC  RO     magic bytes [1:0]
//   0xC BOOT_HDRVER RO     header version
//   0xD BOOT_NAME0  RO     image name chars [1:0]
//   0xE BOOT_NAME1  RO     image name chars [3:2]
//   0xF BOOT_NAME2  RO     image name chars [5:4]
//
// ADR-012: the boot loader is a bus master, not a CPU program, so an
// image is authenticated before a single instruction of it executes.
// =====================================================================
`default_nettype none
import sv16_pkg::*;

module sv16_boot (
    input  logic        clk,
    input  logic        rst_n,

    // Register interface (bus slave)
    input  logic [3:0]  addr,
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    input  logic        req,
    input  logic        we,
    output logic        ack,

    // RAM loader port (bus master)
    output logic        m_req,
    output logic        m_we,
    output logic [15:0] m_addr,
    output logic [15:0] m_wdata,
    input  logic        m_ack,
    input  logic [15:0] m_rdata,

    // Flash byte stream interface (sv16_flash_ctrl boot port)
    output logic        f_start,
    output logic [23:0] f_addr,
    output logic [15:0] f_len,
    input  logic        f_valid,
    input  logic [7:0]  f_data,
    output logic        f_ack,
    output logic        f_abort,
    input  logic        f_busy,

    // Startup sequencer interface
    input  logic        boot_start,     // pulse: run the load sequence
    output logic        boot_done,      // pulse: load sequence finished
    output logic        boot_ok,        // level: image verified and loaded
    output logic [15:0] boot_entry,     // entry word address
    output logic [15:0] boot_stack,     // initial stack pointer
    output logic        auto_boot,      // BOOT_CTRL.AUTO
    output logic        busy
);

    // ---------------------------------------------------------- FSM states
    localparam logic [2:0] B_IDLE  = 3'd0,   // waiting for a start pulse
                           B_HDR   = 3'd1,   // streaming the 32-byte header
                           B_CHK   = 3'd2,   // header verdict
                           B_PLD   = 3'd3,   // streaming + storing the payload
                           B_FIN   = 3'd4,   // drain, settle, CRC verdict
                           B_DONE  = 3'd5,   // image accepted
                           B_FAIL  = 3'd6;   // image rejected

    localparam logic [1:0] W_IDLE = 2'd0,
                           W_REQ  = 2'd1;    // bus write in flight

    // A stalled SPI stream (dead flash, missing clock) fails the load
    // instead of hanging the sequencer.  0xFFFF cycles ~ 2.6 ms @ 25 MHz.
    localparam logic [15:0] WATCHDOG_MAX = 16'hFFFF;
    localparam logic [15:0] DRAIN_MAX    = 16'hFFFF;

    // ---------------------------------------------------------- registers
    logic [2:0]  bstate;
    logic [1:0]  wstate;
    logic [4:0]  hdr_idx;
    logic [7:0]  hdr_buf [0:31];
    logic        hdr_done;
    logic        fail_flag;
    logic        phase;
    logic [7:0]  lo_byte;
    logic [15:0] pld_bytes_left;
    logic [15:0] word_idx;
    logic [15:0] timeout_cnt;
    logic        timeout_fired;
    logic [2:0]  settle_cnt;
    logic [15:0] drain_cnt;

    logic [23:0] launch_addr;
    logic [15:0] launch_len;
    logic        launcher;
    logic        crc_init_pulse, pld_crc_init;
    logic        hcrc_en, pcrc_en;
    logic [15:0] hcrc_val, pcrc_val;
    logic [15:0] hcrc_reg, pld_crc_reg;

    logic        auto_r, verify_only;
    logic [23:0] src_addr;
    logic [15:0] src_len_reg;

    logic [7:0]  stat_reg;
    logic [7:0]  err_reg;

    logic [15:0] entry_reg, stack_reg, words_reg;
    logic [15:0] crc_exp_reg, crc_act_reg, magic_reg, ver_reg;
    logic [7:0]  name_bytes [0:5];

    logic        m_req_r, m_we_r;
    logic [15:0] m_addr_r, m_wdata_r;

    logic        start_pulse, abort_pulse, start_req;

    // ------------------------------------------------- combinational views
    //
    // START is a latched request that clears itself once the attempt begins:
    // the bus holds a write until it is acknowledged (and re-presents it if the
    // interconnect has to defer it), so acting on the write directly would
    // start a fresh attempt on every re-presentation.  One write, one attempt.
    assign start_pulse = ((start_req && !busy) || (boot_start && !busy));
    assign abort_pulse = req && we && (addr == BOOT_CTRL) && wdata[1];

    assign busy = (bstate == B_HDR) || (bstate == B_CHK) ||
                  (bstate == B_PLD) || (bstate == B_FIN);

    assign auto_boot  = auto_r;
    assign boot_entry = entry_reg;
    assign boot_stack = stack_reg;

    // header field views (little endian, offsets from the image format in
    // sv16_pkg.sv)
    logic [15:0] hdr_ver, hdr_words, hdr_entry, hdr_sp, hdr_hcrc, hdr_pcrc;
    assign hdr_ver   = {hdr_buf[5],  hdr_buf[4]};
    assign hdr_words = {hdr_buf[7],  hdr_buf[6]};
    assign hdr_entry = {hdr_buf[17], hdr_buf[16]};
    assign hdr_sp    = {hdr_buf[19], hdr_buf[18]};
    assign hdr_hcrc  = {hdr_buf[21], hdr_buf[20]};
    assign hdr_pcrc  = {hdr_buf[23], hdr_buf[22]};

    logic magic_ok, hcrc_ok, ver_ok, len_ok;
    assign magic_ok = ({hdr_buf[3], hdr_buf[2], hdr_buf[1], hdr_buf[0]} ==
                       BOOT_MAGIC_VALUE[31:0]);
    assign hcrc_ok  = (hcrc_reg == hdr_hcrc);
    assign ver_ok   = (hdr_ver == BOOT_HDR_VERSION);
    assign len_ok   = (hdr_words != 16'd0) &&
                      ((hdr_entry + hdr_words) <= RAM_WORDS[15:0]);

    // ------------------------------------------------- stream back-pressure
    // The loader consumes one byte per handshake.  A payload byte is only
    // accepted once the previous word write has been acknowledged, which is
    // what stalls the SPI stream while the bus is busy.
    logic take_byte;
    assign take_byte = ((bstate == B_HDR) && !hdr_done) ||
                       ((bstate == B_PLD) && (wstate == W_IDLE)) ||
                       (bstate == B_FIN);

    assign f_ack    = f_valid && take_byte;
    assign f_start  = launcher;
    assign f_addr   = launch_addr;
    assign f_len    = launch_len;
    assign f_abort  = abort_pulse;
    assign m_req    = m_req_r;
    assign m_we     = m_we_r;
    assign m_addr   = m_addr_r;
    assign m_wdata  = m_wdata_r;

    assign hcrc_en  = f_ack && (bstate == B_HDR) && (hdr_idx < 5'd20);
    assign pcrc_en  = f_ack && (bstate == B_PLD);

    sv16_crc16 u_hcrc (
        .clk(clk), .rst_n(rst_n),
        .crc_init(crc_init_pulse), .crc_en(hcrc_en), .crc_data(f_data),
        .crc_out(hcrc_val)
    );

    sv16_crc16 u_pcrc (
        .clk(clk), .rst_n(rst_n),
        .crc_init(pld_crc_init), .crc_en(pcrc_en), .crc_data(f_data),
        .crc_out(pcrc_val)
    );

    // ------------------------------------------------------------- the FSM
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            bstate         <= B_IDLE;
            wstate         <= W_IDLE;
            hdr_idx        <= 5'd0;
            hdr_done       <= 1'b0;
            fail_flag      <= 1'b0;
            phase          <= 1'b0;
            lo_byte        <= 8'h00;
            pld_bytes_left <= 16'd0;
            word_idx       <= 16'd0;
            timeout_cnt    <= 16'd0;
            timeout_fired  <= 1'b0;
            settle_cnt     <= 3'd0;
            drain_cnt      <= 16'd0;
            launch_addr    <= 24'd0;
            launch_len     <= 16'd0;
            launcher       <= 1'b0;
            crc_init_pulse <= 1'b0;
            pld_crc_init   <= 1'b0;
            hcrc_reg       <= 16'hFFFF;
            pld_crc_reg    <= 16'hFFFF;
            auto_r         <= 1'b1;         // AUTO boot from flash
            verify_only    <= 1'b0;
            src_addr       <= 24'd0;
            src_len_reg    <= 16'd0;
            stat_reg       <= 8'h00;
            err_reg        <= 8'h00;
            start_req      <= 1'b0;
            entry_reg      <= 16'd0;
            stack_reg      <= BOOT_DEFAULT_SP;
            words_reg      <= 16'd0;
            crc_exp_reg    <= 16'hFFFF;
            crc_act_reg    <= 16'hFFFF;
            magic_reg      <= 16'h0000;
            ver_reg        <= 16'h0000;
            name_bytes[0]  <= 8'h00;
            name_bytes[1]  <= 8'h00;
            name_bytes[2]  <= 8'h00;
            name_bytes[3]  <= 8'h00;
            name_bytes[4]  <= 8'h00;
            name_bytes[5]  <= 8'h00;
            m_req_r        <= 1'b0;
            m_we_r         <= 1'b0;
            m_addr_r       <= 16'd0;
            m_wdata_r      <= 16'd0;
            boot_done      <= 1'b0;
            boot_ok        <= 1'b0;
        end else begin
            // ------------------------------------------------ pulse defaults
            launcher       <= 1'b0;
            crc_init_pulse <= 1'b0;
            pld_crc_init   <= 1'b0;
            boot_done      <= 1'b0;

            // ------------------------------------------------ CPU writes
            // START/ABORT are consumed here, before the register file below, so
            // that a store which sets and aborts at once aborts.
            if (start_pulse) start_req <= 1'b0;
            if (req && we && (addr == BOOT_CTRL) && wdata[0]) start_req <= 1'b1;
            if (req && we && (addr == BOOT_CTRL) && wdata[1]) start_req <= 1'b0;

            if (req && we) begin
                case (addr)
                    BOOT_CTRL:    begin auto_r      <= wdata[3];
                                        verify_only <= wdata[2]; end
                    BOOT_SRC_LO:  src_addr[15:0]  <= wdata;
                    BOOT_SRC_HI:  src_addr[23:16] <= wdata[7:0];
                    BOOT_SRC_LEN: src_len_reg     <= wdata;
                    BOOT_ERR:     err_reg         <= err_reg & ~wdata[7:0];
                    default: ;
                endcase
            end

            // ------------------------------------------------ watchdog
            if ((bstate == B_HDR) || (bstate == B_PLD)) begin
                if (f_valid) begin
                    timeout_cnt <= 16'd0;
                end else if (timeout_cnt == WATCHDOG_MAX) begin
                    timeout_fired <= 1'b1;
                end else begin
                    timeout_cnt <= timeout_cnt + 16'd1;
                end
            end else begin
                timeout_cnt   <= 16'd0;
                timeout_fired <= 1'b0;
            end

            // --------------------------------- header CRC byte-20 snapshot
            if (f_ack && (bstate == B_HDR) && (hdr_idx == 5'd20))
                hcrc_reg <= hcrc_val;

            // ------------------------------------------------ start / abort
            if (start_pulse) begin
                fail_flag      <= 1'b0;
                hdr_done       <= 1'b0;
                hdr_idx        <= 5'd0;
                phase          <= 1'b0;
                pld_bytes_left <= 16'd0;
                word_idx       <= 16'd0;
                settle_cnt     <= 3'd0;
                drain_cnt      <= 16'd0;
                timeout_cnt    <= 16'd0;
                timeout_fired  <= 1'b0;
                err_reg        <= 8'h00;
            start_req      <= 1'b0;
                stat_reg       <= 8'h00;
                boot_ok        <= 1'b0;
                crc_init_pulse <= 1'b1;
                pld_crc_init   <= 1'b1;
                launcher       <= 1'b1;
                launch_addr    <= src_addr;
                launch_len     <= (src_len_reg == 16'd0) ? 16'd32 : src_len_reg;
                bstate         <= B_HDR;
            end else if (abort_pulse && busy) begin
                // f_abort only drops a request that has not started, so the
                // drain path in B_FIN waits for whatever is already in flight
                fail_flag <= 1'b1;
                bstate    <= B_FIN;
            end else begin
                case (bstate)
                    // -------------------------------------------- IDLE
                    B_IDLE: ;

                    // ------------------------------------------ HEADER
                    B_HDR: begin
                        if (timeout_fired) begin
                            fail_flag <= 1'b1;
                            bstate    <= B_FIN;
                        end else if (f_ack) begin
                            hdr_buf[hdr_idx] <= f_data;
                            timeout_cnt      <= 16'd0;
                            if (hdr_idx == 5'd31) begin
                                hdr_done   <= 1'b1;
                                settle_cnt <= 3'd0;
                                drain_cnt  <= 16'd0;
                                bstate     <= B_CHK;
                            end else begin
                                hdr_idx <= hdr_idx + 5'd1;
                            end
                        end
                    end

                    // ------------------------------------ HEADER VERDICT
                    B_CHK: begin
                        // let the flash controller retire the header stream
                        // before handing it the payload request
                        if (settle_cnt != 3'd7) settle_cnt <= settle_cnt + 3'd1;
                        if ((settle_cnt >= 3'd2) && !f_busy) begin
                        if (magic_ok && hcrc_ok && ver_ok && len_ok) begin
                            entry_reg      <= hdr_entry;
                            stack_reg      <= (hdr_sp == 16'd0) ? BOOT_DEFAULT_SP
                                                                : hdr_sp;
                            words_reg      <= hdr_words;
                            crc_exp_reg    <= hdr_pcrc;
                            magic_reg      <= {hdr_buf[1], hdr_buf[0]};
                            ver_reg        <= hdr_ver;
                            name_bytes[0]  <= hdr_buf[8];
                            name_bytes[1]  <= hdr_buf[9];
                            name_bytes[2]  <= hdr_buf[10];
                            name_bytes[3]  <= hdr_buf[11];
                            name_bytes[4]  <= hdr_buf[12];
                            name_bytes[5]  <= hdr_buf[13];
                            stat_reg[BOOT_MAGIC_OK_BIT] <= 1'b1;
                            stat_reg[BOOT_CRC_OK_BIT]   <= 1'b0;
                            stat_reg[BOOT_FAIL_BIT]     <= 1'b0;
                            // Start the payload stream immediately: this is
                            // what turns load-over-SPI into a streaming
                            // transfer instead of a byte-at-a-time poke.
                            pld_crc_init   <= 1'b1;
                            launcher       <= 1'b1;
                            launch_addr    <= src_addr + 24'd32;
                            launch_len     <= {hdr_words[14:0], 1'b0};
                            pld_bytes_left <= {hdr_words[14:0], 1'b0};
                            word_idx       <= 16'd0;
                            phase          <= 1'b0;
                            settle_cnt     <= 3'd0;
                            bstate         <= B_PLD;
                        end else begin
                            fail_flag <= 1'b1;
                            stat_reg[BOOT_MAGIC_OK_BIT] <= magic_ok;
                            // first failure wins: a blank part reports
                            // "magic", not a pile of downstream symptoms
                            if (!magic_ok) begin
                                err_reg[BOOTERR_MAGIC_BIT] <= 1'b1;
                            end else if (!hcrc_ok) begin
                                err_reg[BOOTERR_HDRCRC_BIT] <= 1'b1;
                            end else if (!ver_ok) begin
                                err_reg[BOOTERR_VER_BIT] <= 1'b1;
                            end else begin
                                err_reg[BOOTERR_LENGTH_BIT] <= 1'b1;
                            end
                            settle_cnt <= 3'd0;
                            drain_cnt  <= 16'd0;
                            bstate     <= B_FIN;
                        end
                        end
                    end

                    // ------------------------------------------ PAYLOAD
                    B_PLD: begin
                        if (timeout_fired) begin
                            fail_flag <= 1'b1;
                            bstate    <= B_FIN;
                        end else if (f_ack) begin
                            timeout_cnt <= 16'd0;
                            if (phase == 1'b0) begin
                                lo_byte <= f_data;
                                phase   <= 1'b1;
                            end else begin
                                // low byte already latched: submit the word
                                m_wdata_r <= {f_data, lo_byte};
                                m_addr_r  <= entry_reg + word_idx;
                                m_req_r   <= 1'b1;
                                m_we_r    <= 1'b1;
                                wstate    <= W_REQ;
                                phase     <= 1'b0;
                            end
                            if (pld_bytes_left == 16'd1) begin
                                pld_bytes_left <= 16'd0;
                                settle_cnt     <= 3'd0;
                                drain_cnt      <= 16'd0;
                                bstate         <= B_FIN;
                            end else begin
                                pld_bytes_left <= pld_bytes_left - 16'd1;
                            end
                        end
                    end

                    // ------------------------------- DRAIN + CRC VERDICT
                    B_FIN: begin
                        if (settle_cnt != 3'd7) settle_cnt <= settle_cnt + 3'd1;
                        if (drain_cnt != DRAIN_MAX) drain_cnt <= drain_cnt + 16'd1;
                        // the CRC engine output lags the last byte by one
                        // cycle, so snapshot it after a settle cycle
                        if (settle_cnt == 3'd1) pld_crc_reg <= pcrc_val;
                        if ((settle_cnt >= 3'd2) && !f_busy && !f_valid &&
                            (wstate == W_IDLE)) begin
                            crc_act_reg <= pld_crc_reg;
                            boot_done   <= 1'b1;
                            if (fail_flag) begin
                                stat_reg[BOOT_OK_BIT]   <= 1'b0;
                                stat_reg[BOOT_FAIL_BIT] <= 1'b1;
                                boot_ok                 <= 1'b0;
                                bstate                  <= B_FAIL;
                            end else if (pld_crc_reg == crc_exp_reg) begin
                                stat_reg[BOOT_OK_BIT]     <= 1'b1;
                                stat_reg[BOOT_FAIL_BIT]   <= 1'b0;
                                stat_reg[BOOT_CRC_OK_BIT] <= 1'b1;
                                // verify-only loads the image but does not
                                // hand the CPU over to it
                                boot_ok <= !verify_only;
                                bstate  <= B_DONE;
                            end else begin
                                err_reg[BOOTERR_PLDRC_BIT] <= 1'b1;
                                stat_reg[BOOT_OK_BIT]      <= 1'b0;
                                stat_reg[BOOT_FAIL_BIT]    <= 1'b1;
                                stat_reg[BOOT_CRC_OK_BIT]  <= 1'b0;
                                boot_ok                    <= 1'b0;
                                bstate                     <= B_FAIL;
                            end
                        end else if (drain_cnt == DRAIN_MAX) begin
                            // a stream that never drains must not hang the
                            // sequencer (and with it the whole SoC)
                            err_reg[BOOTERR_TIMEOUT_BIT] <= 1'b1;
                            stat_reg[BOOT_FAIL_BIT]      <= 1'b1;
                            stat_reg[BOOT_OK_BIT]        <= 1'b0;
                            boot_ok                      <= 1'b0;
                            boot_done                    <= 1'b1;
                            bstate                       <= B_FAIL;
                        end
                    end

                    // ------------------------------------------- RESULTS
                    // B_DONE holds boot_ok until the next start pulse
                    B_DONE: ;
                    B_FAIL: boot_ok <= 1'b0;

                    default: bstate <= B_IDLE;
                endcase
            end

            // -------------------------------------------- bus write FSM
            case (wstate)
                W_IDLE: ;
                W_REQ: begin
                    if (m_ack) begin
                        m_req_r  <= 1'b0;
                        m_we_r   <= 1'b0;
                        word_idx <= word_idx + 16'd1;
                        wstate   <= W_IDLE;
                    end
                end
                default: wstate <= W_IDLE;
            endcase
        end
    end

    // ------------------------------------------------------- read mux + ack
    always_comb begin
        rdata = 16'h0000;
        case (addr)
            BOOT_CTRL:    rdata = {12'h000, auto_r, verify_only, start_req, 1'b0};
            BOOT_STAT:    rdata = {11'h000, stat_reg[4:1], busy};
            BOOT_SRC_LO:  rdata = src_addr[15:0];
            BOOT_SRC_HI:  rdata = {8'h00, src_addr[23:16]};
            BOOT_SRC_LEN: rdata = src_len_reg;
            BOOT_ENTRY:   rdata = entry_reg;
            BOOT_STACK:   rdata = stack_reg;
            BOOT_WORDS:   rdata = words_reg;
            BOOT_CRC_EXP: rdata = crc_exp_reg;
            BOOT_CRC_ACT: rdata = crc_act_reg;
            BOOT_ERR:     rdata = {8'h00, err_reg};
            BOOT_MAGIC:   rdata = magic_reg;
            BOOT_HDRVER:  rdata = ver_reg;
            BOOT_NAME0:   rdata = {name_bytes[1], name_bytes[0]};
            BOOT_NAME1:   rdata = {name_bytes[3], name_bytes[2]};
            BOOT_NAME2:   rdata = {name_bytes[5], name_bytes[4]};
            default:      rdata = 16'h0000;
        endcase
    end

    // one wait state, matching every other MMIO slave on the bus
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) ack <= 1'b0;
        else        ack <= req;
    end

endmodule

`default_nettype wire
