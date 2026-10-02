// SV-16 Rev B — Watchdog timer (WDT), MMIO block 8 (0xF080)
//
// A windowed, key-protected watchdog whose timeout restarts the SoC through the
// startup sequencer (ADR-017).  It is the difference between "an application
// hung" and "an application restarted": with it enabled, a runaway program
// recovers by itself instead of waiting for someone to press reset.
//
// Register map (word offsets from 0xF080):
//   0x0 WDT_CTRL    RW    key-protected: [0] ENABLE  [1] LOCK  [2] WINDOW_EN
//                         [3] IRQ_EN  [6:4] PRESC          key in [15:8] = 0x5A
//   0x1 WDT_STAT    RO    [0] RUNNING [1] TIMEOUT [2] WINDOW_FAULT [3] LOCKED
//                         [4] IRQ_PENDING [5] BAD_KEY [6] WRITE_BLOCKED
//                         (all but RUNNING/LOCKED are write-1-to-clear)
//   0x2 WDT_PRESET  RW    reload value, in prescaled ticks (frozen by LOCK)
//   0x3 WDT_FEED    WO    write 0x5A5A to kick the counter
//   0x4 WDT_WINDOW  RW    minimum ticks before a feed is legal (frozen by LOCK)
//   0x5 WDT_MARGIN  RW    early-warning threshold from expiry (frozen by LOCK)
//
// Protection model: CTRL is keyed (key 0x5A in [15:8]) because it holds the
// bits that could disarm the watchdog; FEED needs the magic word 0x5A5A.  The
// three value registers are plain 16-bit writes - a 16-bit period cannot share
// a word with an 8-bit key - and are instead protected by LOCK, which freezes
// them until the external reset pin is asserted.
//
// Behaviour:
//   * Disabled at reset.  Software enables it with a keyed write, which is the
//     one store an application should do before entering its main loop.
//   * Timeout period = (PRESET + 1) x 2^PRESC clocks.  At 12.5 MHz that spans
//     5.2 ms (PRESC=0) to 0.67 s (PRESC=7), so it can cover both "the control
//     loop stalled" and "the boot loader never finished".
//   * On timeout the counter reloads itself, a one-cycle `timeout` pulse is
//     sent to the startup sequencer, and STAT.TIMEOUT latches.  The reload
//     matters: after a watchdog restart the system needs a full period to get
//     through reset, image loading and init before it can feed again.
//   * MARGIN ticks before expiry the early-warning interrupt fires, so software
//     can save a breadcrumb (SYS_SCRATCH0/1 survive a restart) before the reset.
//   * LOCK, once set, freezes ENABLE/PRESC/PRESET/WINDOW/MARGIN until the
//     external reset pin is asserted: a wild pointer cannot disarm the watchdog
//     that is guarding it.  Feeds and the interrupt enable still work, of
//     course.
//   * WINDOW_EN turns on windowed feeding: a feed earlier than WINDOW ticks
//     after the last one is treated as a fault (a tight loop that feeds
//     constantly is exactly the failure mode a plain watchdog misses).  The
//     window is not enforced during the first period after ENABLE, so starting
//     the watchdog and feeding it in the next instruction is legal.
//   * The block is reset ONLY by the external hard reset (rst_n), never by the
//     SoC's own soft restart (cpu_rst_n).  An application cannot escape its
//     watchdog by hanging twice.
//
// Rev B: new module (ADR-017).

`timescale 1ns / 1ps

import sv16_pkg::*;

module sv16_wdt (
    input  logic        clk,
    input  logic        rst_n,      // hard reset only (external pin)

    // Bus
    input  logic [3:0]  addr,
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    input  logic        req,
    input  logic        we,
    output logic        ack,

    // Interrupts / reset request
    output logic        irq,        // early warning (IRQ_WDT)
    output logic        timeout     // one-cycle pulse: restart the SoC
);


    // --------------------------------------------------------------- state
    logic        enable, lock, window_en, irq_en;
    logic [2:0]  presc;
    logic [15:0] preset, window, margin;

    logic [15:0] counter;      // ticks left before expiry
    logic [15:0] elapsed;      // ticks since the last feed
    logic [13:0] presc_cnt;    // clock divider

    logic        st_timeout, st_winfault, st_irq, st_badkey, st_blocked;
    logic        first_period;   // window not enforced until the first feed
    logic        timeout_pulse;
    logic        tick;

    // ---------------------------------------------------------- prescaler
    logic [13:0] presc_reload;
    always_comb presc_reload = (14'd1 << presc) - 14'd1;   // 2^PRESC clocks per tick

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            presc_cnt <= 14'd0;
        end else if (presc_cnt == 14'd0) begin
            presc_cnt <= presc_reload;
        end else begin
            presc_cnt <= presc_cnt - 14'd1;
        end
    end

    assign tick = (presc_cnt == 14'd0);

    // --------------------------------------------------------- key handling
    logic ctrl_key_ok, feed_key_ok;
    assign ctrl_key_ok = (wdata[15:8] == WDT_KEY_BYTE);
    assign feed_key_ok = (wdata == WDT_KEY_FEED);

    // Period-defining registers a keyed write may not touch once LOCK is set
    logic locked_write;
    assign locked_write = lock && ((addr == WDT_PRESET) ||
                                   (addr == WDT_WINDOW) ||
                                   (addr == WDT_MARGIN));

    // ------------------------------------------------------------ main FSM
    logic feed_ok, feed_early, feed_bad;
    always_comb begin
        feed_ok    = 1'b0;
        feed_early = 1'b0;
        feed_bad   = 1'b0;
        if (enable && (addr == WDT_FEED) && we) begin
            if (!feed_key_ok)                                  feed_bad   = 1'b1;
            else if (window_en && !first_period && elapsed < window) feed_early = 1'b1;
            else                                                feed_ok    = 1'b1;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enable        <= 1'b0;
            lock          <= 1'b0;
            window_en     <= 1'b0;
            irq_en        <= 1'b0;
            presc         <= 3'd0;
            preset        <= 16'd0;
            window        <= 16'd0;
            margin        <= 16'd0;
            counter       <= 16'd0;
            elapsed       <= 16'd0;
            st_timeout    <= 1'b0;
            st_winfault   <= 1'b0;
            st_irq        <= 1'b0;
            st_badkey     <= 1'b0;
            st_blocked    <= 1'b0;
            first_period  <= 1'b0;
            timeout_pulse <= 1'b0;
        end else begin
            timeout_pulse <= 1'b0;      // default: one-cycle pulse

            // ---------------------------------------------- register writes
            if (req && we) begin
                case (addr)
                    WDT_CTRL: begin
                        if (!ctrl_key_ok) begin
                            st_badkey <= 1'b1;
                        end else if (lock) begin
                            // Locked: ENABLE, WINDOW_EN and PRESC are frozen.
                            // IRQ_EN stays writable (it cannot disarm the
                            // watchdog), and disabling/period changes are
                            // reported rather than silently dropped.
                            irq_en <= wdata[WDT_CTRL_IRQ_BIT];
                            enable <= 1'b1;
                            if (!wdata[WDT_CTRL_ENABLE_BIT] ||
                                (wdata[WDT_CTRL_WINDOW_BIT] != window_en) ||
                                (wdata[WDT_CTRL_PRESC_HI:WDT_CTRL_PRESC_LO] != presc))
                                st_blocked <= 1'b1;
                        end else begin
                            enable    <= wdata[WDT_CTRL_ENABLE_BIT];
                            window_en <= wdata[WDT_CTRL_WINDOW_BIT];
                            irq_en    <= wdata[WDT_CTRL_IRQ_BIT];
                            presc     <= wdata[WDT_CTRL_PRESC_HI:WDT_CTRL_PRESC_LO];
                            if (wdata[WDT_CTRL_LOCK_BIT]) lock <= 1'b1;
                            if (!enable && wdata[WDT_CTRL_ENABLE_BIT]) begin
                                // starting: load the counter, clear history and
                                // suspend the window for one period
                                counter      <= preset;
                                elapsed      <= 16'd0;
                                first_period <= 1'b1;
                            end
                        end
                    end
                    WDT_PRESET: begin
                        if (locked_write) st_blocked <= 1'b1;
                        else              preset <= wdata;
                    end
                    WDT_WINDOW: begin
                        if (locked_write) st_blocked <= 1'b1;
                        else              window <= wdata;
                    end
                    WDT_MARGIN: begin
                        if (locked_write) st_blocked <= 1'b1;
                        else              margin <= wdata;
                    end
                    WDT_FEED: begin
                        st_badkey   <= st_badkey | feed_bad;
                        st_winfault <= st_winfault | feed_early;
                        // the reload itself happens in the priority block below
                    end
                    WDT_STAT: begin       // write 1 clears the sticky flags
                        if (wdata[WDT_STAT_TIMEOUT_BIT]) st_timeout  <= 1'b0;
                        if (wdata[WDT_STAT_WINFAULT_BIT]) st_winfault <= 1'b0;
                        if (wdata[WDT_STAT_IRQ_BIT])      st_irq      <= 1'b0;
                        if (wdata[WDT_STAT_BADKEY_BIT])   st_badkey   <= 1'b0;
                        if (wdata[WDT_STAT_BLOCKED_BIT])  st_blocked  <= 1'b0;
                    end
                    default: ;
                endcase
            end

            // ------------------------------------- counter: explicit priority
            // A feed, a window fault and a tick can all land in the same clock
            // (at PRESC = 0 every clock is a tick), so the order below is the
            // arbitration: a fault restarts, a feed reloads, a tick counts down.
            // Without this a feed would be silently swallowed by the decrement.
            if (feed_early) begin
                // a windowed feed that arrived too early is a fault: restart now
                st_timeout    <= 1'b1;
                counter       <= preset;
                elapsed       <= 16'd0;
                first_period  <= 1'b0;
                timeout_pulse <= 1'b1;
            end else if (feed_ok) begin
                counter       <= preset;
                elapsed       <= 16'd0;
                first_period  <= 1'b0;
            end else if (tick && enable) begin
                if (counter == 16'd0) begin
                    // expiry: latch, rearm for a full period, ask for a restart
                    st_timeout    <= 1'b1;
                    counter       <= preset;
                    elapsed       <= 16'd0;
                    timeout_pulse <= 1'b1;
                end else begin
                    counter <= counter - 16'd1;
                    elapsed <= elapsed + 16'd1;
                    if (irq_en && (counter <= margin)) st_irq <= 1'b1;
                end
            end
        end
    end

    assign irq     = st_irq & irq_en & enable;
    assign timeout = timeout_pulse;

    // --------------------------------------------------------------- readout
    always_comb begin
        rdata = 16'h0000;
        case (addr)
            WDT_CTRL:   rdata = {8'h00, 1'b0, presc, irq_en, window_en, lock, enable};
            WDT_STAT:   rdata = {9'h000, st_blocked, st_badkey, st_irq,
                                 lock, st_winfault, st_timeout, enable};
            WDT_PRESET: rdata = preset;
            WDT_WINDOW: rdata = window;
            WDT_MARGIN: rdata = margin;
            default:    rdata = 16'h0000;   // FEED is write-only
        endcase
    end

    // -------------------------------------------------------------- bus ack
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) ack <= 1'b0;
        else        ack <= req;
    end

endmodule : sv16_wdt
