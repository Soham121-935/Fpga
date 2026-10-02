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
// ADR-019 (A/B images): the loader does not just load the image at BOOT_SRC --
// it chooses between two slots (base 0 and base + 32 KB) using the 2-byte slot
// record in the reserved part of each image header (bytes 0x18/0x19), and it
// maintains that record itself:
//
//   L_PICK        read the 2-byte record at the head of one slot
//   L_RDEND       parse it: 0xA5 + {PENDING, GOOD, BAD, dead, none}
//   L_DEC         trial rule: a pending image getting its first boot is marked
//                 tried, a pending image that restarts is marked BAD
//   L_WR          program the record, then read it back
//   L_DONE        only a settled record hands the CPU over
//
// Confirmation (BOOT_CTRL[6]) writes GOOD over the running slot's record and
// then writes BAD over the *other* slot's record, so exactly one image is the
// live one: with two GOOD records the pick order would fall back to slot 0 and
// a confirmed update would silently revert at the next reset.
//
// The record is two bytes in the same flash page, but each byte is its own
// one-byte page program, so a power cut can leave {0xA5, 0xFF} -- which decodes
// as "no record", not as a state the loader would trust.  Every state the
// loader writes is a bit-subset of PENDING, because a page program cannot set a
// bit back to 1: PENDING(0x11) -> GOOD(0x10) -> ... and PENDING(0x11) ->
// BAD(0x01).  A verify-only
// load (the monitor's V/B path, which redirects BOOT_SRC) is never turned into
// a trial and its slots_ctl is ignored: only the automatic boot owns the
// records.  That is what makes a failed update recoverable with no host: a new
// image that hangs is restarted by the watchdog (ADR-017), the restart lands
// inside the trial period, its record becomes BAD, and the previous image boots
// again.
//
// A verified image raises `boot_ok` and the startup sequencer releases
// the CPU at `boot_entry`.  A missing or corrupt image raises
// BOOT_STAT.FAIL and the CPU is left in reset so the serial monitor can
// recover the part over UART.
//
// Register map (MMIO block 0xA0, see docs/MEMORY_MAP.md):
//   0x0 BOOT_CTRL   RW/W1P [0] START [1] ABORT [2] VERIFY-ONLY [3] AUTO
//                          [4] NOSLOT (ADR-019) [5] SLOT_CLR [6] SLOT_CNF
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
// ADR-019 adds no register offsets: BOOT_CTRL gains [4] NOSLOT, [5] SLOT_CLR,
// [6] SLOT_CNF and BOOT_STAT gains [5] SLOT, [6] SLOT_RETRY, [7] SLOT_TRIAL.
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

    // Slot-record interface (ADR-019, wired to sv16_flash_ctrl)
    output logic        slot_wr_req,    // pulse: program the record
    output logic [23:0] slot_wr_addr,
    output logic [7:0]  slot_wr_data,
    input  logic [1:0]  slot_wr_done,   // [0] accepted, [1] finished

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

    // ------------------------------------------------- ADR-019: slot states
    localparam logic [3:0] L_OFF   = 4'd0,   // not doing slot work (legacy path)
                           L_PICK  = 4'd1,   // launch a record read
                           L_READ  = 4'd2,   // collect the 2 record bytes
                           L_RDEND = 4'd3,   // parse + route the record
                           L_XFER  = 4'd4,   // launch the header stream of a slot
                           L_WAIT  = 4'd5,   // wait for the load verdict
                           L_DEC   = 4'd6,   // trial decision
                           L_WR    = 4'd7,   // program a record byte
                           L_RETRY = 4'd8,   // this slot failed: try the other
                           L_DONE  = 4'd9,   // record settled: boot
                           L_CDONE = 4'd10,  // confirmation finished
                           L_FAIL  = 4'd11,  // nothing bootable: monitor
                           L_SEL   = 4'd12;  // settle the slot classes

    // why a record is being read back
    localparam logic [1:0] RD_PICK  = 2'd0,
                           RD_VER   = 2'd1,
                           RD_CONF  = 2'd2;

    // Candidate class of a slot; the value doubles as the pick priority
    // (lower wins) and the fixed order settles ties, so slot 0 is the factory
    // slot.  TRIAL outranks GOOD because a trial that failed must be retired
    // before an old image is booted -- otherwise the stale record would linger.
    localparam logic [2:0] CLS_PENDING = 3'd0,   // installed, never booted
                           CLS_TRIAL   = 3'd1,   // booted, never confirmed
                           CLS_GOOD    = 3'd2,   // confirmed: the fallback image
                           CLS_PLAIN   = 3'd3,   // no record: boot it, no trial
                           CLS_BAD     = 3'd4;   // never picked

    // record byte encodings: one source of truth, in the package (ADR-019).
    // PENDING -> TRIED -> {GOOD | BAD} only ever clears bits, which is all a
    // flash page program can do: 0x1F -> 0x0F -> 0x07 / 0x08.
    localparam logic [7:0] REC_SYNC  = SLOT_REC_SYNC,
                           REC_PEND  = SLOT_REC_PENDING,
                           REC_TRIED = SLOT_REC_TRIED,
                           REC_GOOD  = SLOT_REC_GOOD,
                           REC_BAD   = SLOT_REC_BAD;

    localparam logic [23:0] SLOT_BASE0 = 24'h00_0000;
    localparam logic [23:0] REC0_ADDR  = SLOT_REC0;       // records live in the
    localparam logic [23:0] REC1_ADDR  = SLOT_REC1;       // image header (ADR-019)
    localparam logic [23:0] SLOT_BASE1 = BOOT_SLOT_STRIDE;

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
    logic [23:0] boot_base;         // image base of this attempt (BOOT_SRC or slot)
    logic [15:0] src_len_reg;

    logic [7:0]  stat_reg;
    logic [7:0]  err_reg;

    logic [15:0] entry_reg, stack_reg, words_reg;
    logic [15:0] crc_exp_reg, crc_act_reg, magic_reg, ver_reg;
    logic [7:0]  name_bytes [0:5];

    logic        m_req_r, m_we_r;
    logic [15:0] m_addr_r, m_wdata_r;

    logic        start_pulse, abort_pulse, start_req;

    // ------------------------------------------------- ADR-019 slot signals
    logic [3:0]  lstate;
    logic [1:0]  rd_purpose;
    logic        pick_idx;
    logic        launch_armed;
    logic [1:0]  rd_bytes;
    logic [7:0]  rec_b0, rec_b1;
    logic [2:0]  slot_cls [0:1];
    logic        sel_bad  [0:1];
    logic        sel_slot;
    logic        cur_slot;
    logic [2:0]  cur_cls;
    logic        pick_round;
    // NOTE: there is deliberately no "tried" state here.  The trial lives in
    // the flash record, so it survives the watchdog reset that triggers the
    // rollback (a flip-flop would be cleared by that very reset).
    logic        slot_active;      // this attempt went through the slot logic
    logic        slot_retry;       // a slot was abandoned during this attempt
    logic        slot_trial;       // the running image is on trial
    logic        conf_retire;      // the write in flight retires the other slot
    logic [7:0]  l_wr_data;
    logic [23:0] l_wr_addr;
    logic        l_wr_slot;
    logic        wr_started;
    logic        slot_begin;       // pulse from the main FSM: start the pick
    logic        slot_xfer_req;    // pulse: stream the chosen slot's header
    logic [23:0] slot_xfer_addr;
    logic [3:0]  l_settle;         // slot-logic settle counter (main FSM owns
                                   // settle_cnt for the legacy paths)
    logic        slot_launch_req;  // pulse: start a flash byte stream
    logic [23:0] slot_launch_addr;
    logic [15:0] slot_launch_len;
    logic        slot_settled;     // pulse: record work done, boot it
    logic        slot_aborted;     // pulse: record work failed, use the monitor
    logic        slot_err;         // pulse: latch BOOTERR_SLOT
    logic        slot_clear;       // pulse: forget cached slot state
    logic        slot_confirm;     // pulse: confirm the running image
    logic        slots_en_r;       // BOOT_SLOTS_CTL.ENABLE
    logic        slot_take;        // the slot logic consumes a streamed byte
    logic        slot_act_next;    // this attempt should use the slot logic

    assign slot_act_next = slots_en_r && boot_start && !verify_only;
    assign slot_take     = (lstate == L_READ) && (rd_bytes != 2'd2);

    // ------------------------------------------------- combinational views
    //
    // START is a latched request that clears itself once the attempt begins:
    // the bus holds a write until it is acknowledged (and re-presents it if the
    // interconnect has to defer it), so acting on the write directly would
    // start a fresh attempt on every re-presentation.  One write, one attempt.
    assign start_pulse = ((start_req && !busy) || (boot_start && !busy));
    assign abort_pulse = req && we && (addr == BOOT_CTRL) && wdata[1];

    assign busy = (bstate == B_HDR) || (bstate == B_CHK) ||
                  (bstate == B_PLD) || (bstate == B_FIN) ||
                  ((lstate != L_OFF) && (lstate != L_DONE) &&
                   (lstate != L_CDONE) && (lstate != L_FAIL));

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
                       slot_take ||
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
            boot_base      <= 24'd0;
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
            // ADR-019: the slot logic owns its own registers (see the slot
            // state machine below); the main FSM only owns the two signals it
            // writes: slot_active (this attempt goes through the slot logic)
            // and slots_en_r (the BOOT_SLOTS_CTL.ENABLE bit).
            slot_active    <= 1'b0;
            slot_begin     <= 1'b0;
            slots_en_r     <= 1'b1;    // A/B policy on by default
        end else begin
            // ------------------------------------------------ pulse defaults
            launcher       <= 1'b0;
            crc_init_pulse <= 1'b0;
            pld_crc_init   <= 1'b0;
            boot_done      <= 1'b0;
            slot_begin        <= 1'b0;

            // ------------------------------------------------ CPU writes
            // START/ABORT are consumed here, before the register file below, so
            // that a store which sets and aborts at once aborts.
            if (start_pulse) start_req <= 1'b0;
            if (req && we && (addr == BOOT_CTRL) && wdata[0]) start_req <= 1'b1;
            if (req && we && (addr == BOOT_CTRL) && wdata[1]) start_req <= 1'b0;

            // ADR-019 control pulses.  CONFIRM and CLEAR are write-only pulses;
            // they are the only way an application can affect the slot records,
            // and neither can make an unbootable part bootable or vice versa.
            slot_confirm <= req && we && (addr == BOOT_CTRL) &&
                            wdata[BOOT_CTRL_SLOTCNF_BIT];
            slot_clear   <= req && we && (addr == BOOT_CTRL) &&
                            wdata[BOOT_CTRL_SLOTCLR_BIT];

            // a slot-record stream, requested by the slot logic
            if (slot_launch_req) begin
                launcher    <= 1'b1;
                launch_addr <= slot_launch_addr;
                launch_len  <= slot_launch_len;
            end

            // the slot logic finished: hand the verdict to the sequencer
            if (slot_settled) begin
                boot_done                  <= 1'b1;
                boot_ok                    <= 1'b1;
                stat_reg[BOOT_OK_BIT]      <= 1'b1;
                stat_reg[BOOT_FAIL_BIT]    <= 1'b0;
                slot_active                <= 1'b0;   // attempt over
            end
            if (slot_aborted) begin
                boot_done               <= 1'b1;
                boot_ok                 <= 1'b0;
                stat_reg[BOOT_FAIL_BIT] <= 1'b1;
                stat_reg[BOOT_OK_BIT]   <= 1'b0;
                slot_active             <= 1'b0;      // attempt over
            end
            if (slot_err) err_reg[BOOTERR_SLOT_BIT] <= 1'b1;

            if (req && we) begin
                case (addr)
                    BOOT_CTRL:    begin
                        // ADR-019 bits 5 and 6 are write-only pulses (clear the
                        // cached slot state / confirm the trial).  A write that
                        // carries them is a control write only: it must not
                        // disarm AUTO or the A/B policy, or an application
                        // committing its own trial would stop the next reset
                        // from booting.
                        if (!(wdata[BOOT_CTRL_SLOTCLR_BIT] ||
                              wdata[BOOT_CTRL_SLOTCNF_BIT])) begin
                            auto_r      <= wdata[3];
                            verify_only <= wdata[2];
                            // bit 4 is active low ("1 = ignore the records"),
                            // so firmware that predates the slot policy keeps
                            // A/B enabled by writing 0 there
                            slots_en_r  <= !wdata[BOOT_CTRL_NOSLOT_BIT];
                        end
                    end
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
            if (start_pulse || slot_xfer_req) begin
                // ---- arm an attempt (a fresh start, or the slot logic handing
                // over the slot it chose)
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
                // BOOT_ERR accumulates across the slots tried inside one
                // attempt, so the operator sees *why* each slot failed; only a
                // fresh start clears it.
                if (start_pulse) err_reg <= 8'h00;
                start_req      <= 1'b0;
                stat_reg       <= 8'h00;
                boot_ok        <= 1'b0;
                boot_done      <= 1'b0;
                crc_init_pulse <= 1'b1;
                pld_crc_init   <= 1'b1;
                launcher       <= 1'b1;
                bstate         <= B_HDR;
                if (slot_xfer_req) begin
                    // the slot logic chose this slot: stream it.  boot_base is
                    // what the payload offset is measured from, so it has to
                    // follow the choice -- BOOT_SRC is not the image address
                    // when the slot policy picked the slot.
                    boot_base   <= slot_xfer_addr;
                    launch_addr <= slot_xfer_addr;
                    launch_len  <= 16'd32;
                end else begin
                    boot_base   <= src_addr;
                    launch_addr <= src_addr;
                    launch_len  <= (src_len_reg == 16'd0) ? 16'd32 : src_len_reg;
                    if (slot_act_next) begin
                        // ADR-019: an automatic boot with the slot policy
                        // enabled does not stream one fixed address -- it picks
                        // a slot from the records first, and the slot logic
                        // finishes the attempt (including marking a failed
                        // trial BAD and falling back to the other slot).
                        slot_begin   <= 1'b1;
                        slot_active  <= 1'b1;
                        bstate       <= B_IDLE;     // the slot logic drives it
                        launcher     <= 1'b0;       // ... which owns the stream
                    end else begin
                        slot_active  <= 1'b0;
                    end
                end
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
                            launch_addr    <= boot_base + 24'd32;
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
                                boot_done               <= !slot_active;
                                bstate                  <= B_FAIL;
                            end else if (pld_crc_reg == crc_exp_reg) begin
                                stat_reg[BOOT_OK_BIT]     <= 1'b1;
                                stat_reg[BOOT_FAIL_BIT]   <= 1'b0;
                                stat_reg[BOOT_CRC_OK_BIT] <= 1'b1;
                                // verify-only loads the image but does not
                                // hand the CPU over to it; a slot-managed load
                                // hands over only once its record is settled
                                boot_ok <= !verify_only && !slot_active;
                                boot_done <= !slot_active;
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
                            boot_done                    <= !slot_active;
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


    // ============================================ ADR-019: A/B slot machine
    //
    // This is the whole "two images, one of them on trial, fall back if the
    // trial fails" policy.  It owns every l_*/slot_*/rec_* register; the main
    // FSM only tells it when an attempt starts (slot_begin) and reacts to its
    // verdict (slot_settled / slot_aborted / slot_err).  No new bus master, no
    // new flash commands, no CPU involvement.
    //
    // Record layout: image header byte 0x18 (header word 0x0C), i.e. absolute
    // 0x000018 in slot A and 0x008018 in slot B -- inside the 32-byte header,
    // where it can never collide with the payload:
    //
    //   0x18  0xA5      sync byte                (written once)
    //   0x19  0x11      PENDING - on trial       (written by the packer)
    //         0x10      GOOD    - confirmed      (written by CONFIRM)
    //         0x01      BAD     - trial failed   (written by the loader)
    //         0x00      dead, every bit cleared (treated as BAD)
    //         0xFF      erased = no record      (treated as "boot untried")
    //
    // Each byte is its own one-byte page program, so a power cut can leave
    // {0xA5, 0xFF} or {0xA5, <old>}: neither is a state the loader trusts, and
    // the slot reads as "no trial" rather than as a wrongly promoted image.
    // State transitions only ever clear bits (see the table above), which is
    // what makes a re-program possible at all inside a page that also holds the
    // image header.  That is the torn-write story.
    assign slot_wr_req  = (lstate == L_WR) && !wr_started;
    assign slot_wr_addr = l_wr_addr;
    assign slot_wr_data = l_wr_data;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            lstate        <= L_OFF;
            pick_idx      <= 1'b0;
            rd_purpose    <= RD_PICK;
            launch_armed  <= 1'b0;
            rd_bytes      <= 2'd0;
            rec_b0        <= 8'h00;
            rec_b1        <= 8'h00;
            slot_cls[0]   <= CLS_PLAIN;
            slot_cls[1]   <= CLS_PLAIN;
            sel_bad[0]    <= 1'b0;
            sel_bad[1]    <= 1'b0;
            sel_slot      <= 1'b0;
            cur_slot      <= 1'b0;
            cur_cls       <= CLS_PLAIN;
            pick_round    <= 1'b0;
            slot_retry    <= 1'b0;
            slot_trial    <= 1'b0;
            conf_retire   <= 1'b0;
            l_wr_data     <= REC_GOOD;
            l_wr_addr     <= 24'd0;
            l_wr_slot     <= 1'b0;
            wr_started    <= 1'b0;
            slot_launch_req  <= 1'b0;
            slot_launch_addr <= 24'd0;
            slot_launch_len  <= 16'd0;
            slot_xfer_req    <= 1'b0;
            slot_xfer_addr   <= 24'd0;
            l_settle         <= 4'd0;
            slot_settled  <= 1'b0;
            slot_aborted  <= 1'b0;
            slot_err      <= 1'b0;
        end else begin
            slot_launch_req <= 1'b0;
            slot_xfer_req   <= 1'b0;
            slot_settled    <= 1'b0;
            slot_aborted    <= 1'b0;
            slot_err        <= 1'b0;

            // ------------------------------------------------ new attempt
            if (slot_begin) begin
                lstate       <= L_PICK;
                pick_idx     <= 1'b0;
                rd_purpose   <= RD_PICK;
                launch_armed <= 1'b0;
                rd_bytes     <= 2'd0;
                sel_bad[0]   <= 1'b0;
                sel_bad[1]   <= 1'b0;
                pick_round   <= 1'b0;
                slot_retry   <= 1'b0;
                slot_trial   <= 1'b0;
            end

            // --------------------------------- the application confirms it
            // CONFIRM moves PENDING or TRIAL to GOOD, and then retires the other
            // slot's image (a second, best-effort record write) so that the
            // freshly confirmed image always wins the next pick: two GOOD slots
            // would otherwise be settled by the fixed slot-0-first tie-break and
            // the update would silently revert.  CONFIRM is refused while an
            // attempt is in flight, and it cannot make a BAD slot bootable again
            // (that would defeat the rollback).
            if (slot_confirm &&
                ((lstate == L_OFF) || (lstate == L_DONE) ||
                 (lstate == L_CDONE) || (lstate == L_FAIL))) begin
                if ((cur_cls == CLS_PENDING) || (cur_cls == CLS_TRIAL)) begin
                    // PENDING -> GOOD and TRIAL -> GOOD are both bit-clearings
                    // of the record, so one page program does it
                    l_wr_slot   <= cur_slot;
                    l_wr_addr   <= (cur_slot == 1'b0) ? REC0_ADDR : REC1_ADDR;
                    l_wr_data   <= REC_GOOD;
                    rd_purpose  <= RD_CONF;
                    conf_retire <= 1'b0;
                    wr_started  <= 1'b0;
                    lstate      <= L_WR;
                end else begin
                    // already GOOD, or an image with no record: there is no
                    // trial to end, so nothing is written
                    slot_trial  <= 1'b0;
                end
            end

            // --------------------------------- the policy was cleared
            if (slot_clear) begin
                sel_bad[0]  <= 1'b0;
                sel_bad[1]  <= 1'b0;
                slot_retry  <= 1'b0;
                slot_trial  <= 1'b0;
            end

            case (lstate)
                L_OFF, L_DONE, L_CDONE, L_FAIL: ;

                // ------------------------------------ launch a record read
                L_PICK: begin
                    if (!launch_armed) begin
                        slot_launch_addr <= (pick_idx == 1'b0) ? REC0_ADDR : REC1_ADDR;
                        slot_launch_len  <= 16'd2;
                        slot_launch_req  <= 1'b1;
                        launch_armed     <= 1'b1;
                        rd_bytes         <= 2'd0;
                        l_settle         <= 4'd0;
                    end else begin
                        if (l_settle != 4'd15) l_settle <= l_settle + 4'd1;
                        // give the flash controller its settle cycles before
                        // the stream starts (the header path does the same)
                        if (l_settle >= 4'd4) lstate <= L_READ;
                    end
                end

                // ---------------------------------------- collect two bytes
                L_READ: begin
                    if (f_ack) begin
                        if (rd_bytes == 2'd0) begin
                            rec_b0   <= f_data;
                            rd_bytes <= 2'd1;
                        end else begin
                            rec_b1   <= f_data;
                            rd_bytes <= 2'd2;
                            lstate   <= L_RDEND;
                        end
                    end
                end

                // -------------------------------------- parse + route
                L_RDEND: begin
                    // classify the slot we just read (also used by readbacks)
                    // State decode.  Fail toward rollback: once the record has
                    // a sync byte, any byte that is not a state we wrote is a
                    // record that was interrupted mid-program (a torn write),
                    // and a torn record must never promote an image, so it
                    // counts as BAD.  0xFF is the exception -- that is the
                    // erased byte, i.e. sync written and state never programmed,
                    // which reads as "no record": an image with no record is
                    // booted untried, exactly as before ADR-019.
                    slot_cls[pick_idx] <= (rec_b0 != REC_SYNC)  ? CLS_PLAIN   :
                                          (rec_b1 == REC_PEND)  ? CLS_PENDING :
                                          (rec_b1 == REC_TRIED) ? CLS_TRIAL   :
                                          (rec_b1 == REC_GOOD)  ? CLS_GOOD    :
                                          (rec_b1 == REC_BAD)   ? CLS_BAD     :
                                          (rec_b1 == 8'hFF)     ? CLS_PLAIN   :
                                                                  CLS_BAD;
                    case (rd_purpose)
                        RD_PICK: begin
                            // A sync byte with a state byte that is neither a
                            // state we wrote nor the erased byte means the
                            // record was interrupted mid-program (or is not
                            // ours at all).  The classifier already refuses to
                            // boot it; report it so firmware can see why.
                            if ((rec_b0 == REC_SYNC) && (rec_b1 != REC_PEND) &&
                                (rec_b1 != REC_TRIED) && (rec_b1 != REC_GOOD) &&
                                (rec_b1 != REC_BAD) && (rec_b1 != 8'hFF))
                                slot_err <= 1'b1;
                            if (pick_idx == 1'b0) begin
                                pick_idx     <= 1'b1;
                                launch_armed <= 1'b0;
                                lstate       <= L_PICK;
                            end else begin
                                // both records are in: let slot_cls settle for
                                // a cycle before the pick samples it (it is
                                // written with non-blocking assignments)
                                lstate <= L_SEL;
                            end
                        end
                        RD_VER: begin
                            if (slot_rb_ok) begin
                                if (l_wr_data == REC_BAD) begin
                                    // the failed trial is marked: fall back to
                                    // the other slot in this same attempt, once
                                    sel_bad[l_wr_slot] <= 1'b1;
                                    if (pick_round == 1'b0) begin
                                        pick_round   <= 1'b1;
                                        slot_retry   <= 1'b1;
                                        pick_idx     <= 1'b0;
                                        launch_armed <= 1'b0;
                                        rd_purpose   <= RD_PICK;
                                        lstate       <= L_PICK;
                                    end else begin
                                        slot_aborted <= 1'b1;
                                        lstate       <= L_FAIL;
                                    end
                                end else begin
                                    // the TRIED marker is down, so however the
                                    // part leaves this boot, the record now
                                    // says the trial had started
                                    cur_cls      <= CLS_TRIAL;
                                    slot_trial   <= 1'b1;
                                    slot_settled <= 1'b1;
                                    lstate       <= L_DONE;
                                end
                            end else begin
                                // the record cannot be trusted.  For a trial
                                // marker that only costs rollback, so boot the
                                // verified image anyway; for a bad marker it
                                // would re-boot the bad image, so refuse.
                                slot_err <= 1'b1;
                                if (l_wr_data == REC_BAD) begin
                                    slot_aborted <= 1'b1;
                                    lstate       <= L_FAIL;
                                end else begin
                                    slot_settled <= 1'b1;
                                    lstate       <= L_DONE;
                                end
                            end
                        end
                        default: begin   // RD_CONF
                            if (!conf_retire) begin
                                if (!slot_rb_ok) begin
                                    // the record refused the promotion: leave
                                    // the trial in place and tell firmware
                                    slot_err <= 1'b1;
                                    lstate   <= L_CDONE;
                                end else begin
                                    // GOOD is down: retire the other image
                                    conf_retire <= 1'b1;
                                    l_wr_slot   <= !cur_slot;
                                    l_wr_addr   <= (cur_slot == 1'b1) ? REC0_ADDR
                                                                      : REC1_ADDR;
                                    l_wr_data   <= REC_BAD;
                                    wr_started  <= 1'b0;
                                    lstate      <= L_WR;
                                end
                            end else begin
                                // The retire write is best effort: an image with
                                // no record cannot take a sync byte, and such an
                                // image loses the pick to a GOOD record anyway.
                                conf_retire <= 1'b0;
                                cur_cls     <= CLS_GOOD;
                                slot_trial  <= 1'b0;
                                lstate      <= L_CDONE;
                            end
                        end
                    endcase
                end

                // -------------------------------- launch the chosen image
                L_XFER: begin
                    // The main FSM owns `bstate`, so the hand-over is a pulse
                    // plus the address; it also re-primes the header engine for
                    // this attempt (a re-pick after a failure is a second
                    // attempt inside the same boot).
                    slot_xfer_addr <= (sel_slot == 1'b0) ? SLOT_BASE0 : SLOT_BASE1;
                    slot_xfer_req  <= 1'b1;
                    lstate         <= L_WAIT;
                end

                // ------------------------------ wait for the load verdict
                L_WAIT: begin
                    if (bstate == B_DONE)      lstate <= L_DEC;
                    else if (bstate == B_FAIL) lstate <= L_RETRY;
                end

                // ------------------------------------------------ trial rule
                L_DEC: begin
                    if (cur_cls == CLS_TRIAL) begin
                        // This slot was booted and came back without a CONFIRM.
                        // Whatever caused the restart -- the watchdog (ADR-017),
                        // a pin, a power cut -- the image did not finish its
                        // trial, so retire it in flash and fall back.  This is
                        // the rollback, and it needs no state of its own: the
                        // record in flash is the state.
                        l_wr_slot  <= cur_slot;
                        l_wr_addr  <= (cur_slot == 1'b0) ? REC0_ADDR : REC1_ADDR;
                        l_wr_data  <= REC_BAD;
                        rd_purpose <= RD_VER;
                        wr_started <= 1'b0;
                        lstate     <= L_WR;
                    end else if (cur_cls == CLS_PENDING) begin
                        // First boot of a freshly installed image: put it on
                        // trial *in flash* before the CPU is released, so the
                        // trial survives any reset from here on.
                        l_wr_slot  <= cur_slot;
                        l_wr_addr  <= (cur_slot == 1'b0) ? REC0_ADDR : REC1_ADDR;
                        l_wr_data  <= REC_TRIED;
                        rd_purpose <= RD_VER;
                        wr_started <= 1'b0;
                        lstate     <= L_WR;
                    end else begin
                        // a confirmed image, or an image with no record at all:
                        // hand it the CPU
                        slot_settled <= 1'b1;
                        lstate       <= L_DONE;
                    end
                end

                // ---------------------------- decide which slot to boot
                L_SEL: begin
                    if (!cand0 && !cand1) begin
                        // nothing bootable: refuse rather than boot an image the
                        // records say is bad
                        slot_err     <= 1'b1;
                        slot_aborted <= 1'b1;
                        lstate       <= L_FAIL;
                    end else if (sel_cls == CLS_TRIAL) begin
                        // This slot has already had its boot and came back
                        // without a CONFIRM: retire it in flash right away.
                        // Loading it first would only put a failed image into
                        // RAM a cycle before the fallback replaces it.
                        slot_retry <= 1'b1;
                        l_wr_slot  <= sel_choice;
                        l_wr_addr  <= (sel_choice == 1'b0) ? REC0_ADDR : REC1_ADDR;
                        l_wr_data  <= REC_BAD;
                        rd_purpose <= RD_VER;
                        wr_started <= 1'b0;
                        lstate     <= L_WR;
                    end else begin
                        sel_slot   <= sel_choice;
                        cur_slot   <= sel_choice;
                        cur_cls    <= sel_cls;
                        // the app can see that it still owes a CONFIRM
                        slot_trial <= (sel_cls == CLS_PENDING) ||
                                      (sel_cls == CLS_TRIAL);
                        lstate     <= L_XFER;
                    end
                end

                // ------------------------------------ program a record byte
                L_WR: begin
                    if (!wr_started) begin
                        wr_started <= 1'b1;   // request held for the handshake
                    end else if (slot_wr_done[1]) begin
                        // sync + state went down as one 2-byte page program;
                        // read the record back before trusting the new state.
                        // rd_purpose says which verdict the read-back decides
                        // (RD_VER = trial/retire, RD_CONF = confirm), so it is
                        // set by whoever started the write.
                        pick_idx     <= l_wr_slot;
                        launch_armed <= 1'b0;
                        lstate       <= L_PICK;
                    end
                end

                // ---------------------------------- this slot failed to load
                L_RETRY: begin
                    sel_bad[sel_slot] <= 1'b1;
                    if (pick_round == 1'b0) begin
                        pick_round   <= 1'b1;
                        slot_retry   <= 1'b1;
                        pick_idx     <= 1'b0;
                        launch_armed <= 1'b0;
                        rd_purpose   <= RD_PICK;
                        lstate       <= L_PICK;
                    end else begin
                        // both slots have now failed to load: this is the
                        // "nothing bootable" verdict
                        slot_err     <= 1'b1;
                        slot_aborted <= 1'b1;
                        lstate       <= L_FAIL;
                    end
                end

                default: lstate <= L_OFF;
            endcase
        end
    end

    // -------------------------------------------------- slot combinational
    logic        cand0, cand1, sel_choice, slot_rb_ok;
    logic [2:0]  sel_cls;
    logic [2:0]  cls_eff [0:1];

    always_comb begin
        // a slot already abandoned in this attempt is out of the running
        cls_eff[0] = sel_bad[0] ? CLS_BAD : slot_cls[0];
        cls_eff[1] = sel_bad[1] ? CLS_BAD : slot_cls[1];
        cand0      = (cls_eff[0] != CLS_BAD);
        cand1      = (cls_eff[1] != CLS_BAD);
        // PENDING outranks GOOD outranks "no record"; the fixed order settles
        // ties, which makes slot 0 the factory slot
        if (cand0 && (!cand1 || (cls_eff[0] <= cls_eff[1]))) begin
            sel_choice = 1'b0;
            sel_cls    = cls_eff[0];
        end else begin
            sel_choice = 1'b1;
            sel_cls    = cls_eff[1];
        end
    end

    // Read-back verdict: the state byte must read back exactly as the state we
    // asked for.  On real flash a program can only clear bits, so this holds
    // only because every transition is a bit-subset of the state it came from
    // (0x1F -> 0x0F -> 0x07 / 0x08); if an encoding ever breaks that chain the
    // read-back fails and the loader refuses to boot the image.
    assign slot_rb_ok = (rec_b0 == REC_SYNC) && (rec_b1 == l_wr_data);

    // ------------------------------------------------------- read mux + ack
    always_comb begin
        rdata = 16'h0000;
        case (addr)
            BOOT_CTRL:    rdata = {9'h000, slot_trial, !slots_en_r,
                                   auto_r, verify_only, start_req, 1'b0};
            // ADR-019: [7] trial, [6] retry, [5] chosen slot
            BOOT_STAT:    rdata = {8'h00, slot_trial, slot_retry, sel_slot,
                                   stat_reg[4:1], busy};
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
