// SV-16 Rev B — Optional PLL system clock (ECP5 EHXPLLL)
// Module: sv16_pll
//
// The board oscillator is 25 MHz and the SoC closes timing at 46.17 MHz, so the
// part has been shipping at 25 MHz with the oscillator wired straight into the
// fabric.  This module turns the unused headroom into a real clock option: an
// `EHXPLLL` hard macro that multiplies the reference up to a build-time
// frequency, which is what an MCU normally gives you.
//
//   make bitstream CLKSRC=pll PLLMHZ=37.5     # 50 % faster system clock
//
// The frequency arithmetic is the one the ECP5 actually implements, and the one
// nextpnr's timing analysis implements too:
//
//   fPFD = fREF / CLKI_DIV                       (must be 10..400 MHz)
//   fOUT = fPFD * CLKFB_DIV                      (feedback taken from CLKOP, so
//                                                 the CLKOP divider is inside the
//                                                 loop and cancels out)
//   fVCO = fOUT * CLKOP_DIV                      (must be 400..800 MHz)
//
// So CLKFB_DIV sets the frequency and CLKOP_DIV only positions the VCO inside
// its legal range — which is why the build script searches for the divider pair
// rather than assuming out = vco/CLKOP_DIV.  Getting this wrong is not subtle:
// the first version of this module used the "out = VCO / CLKOP_DIV" form and
// nextpnr derived a 16 GHz VCO and constrained the fabric to 800 MHz.
//
// Only frequencies that the 25 MHz reference can reach exactly are advertised
// by the Makefile — multiples of 25 MHz and of 12.5 MHz (37.5, 50, 62.5, 75...).
// The synthesis script reports the frequency it actually built, and refuses to
// silently build something else.  Note that 50 MHz is above the fabric's
// measured 46.17 MHz Fmax, so the useful setting on this part is 37.5 MHz.
//
// Feedback is internal: CLKINTFB drives CLKFB inside the primitive (this is the
// configuration the prjtrellis examples and the Lattice wizard generate for
// CLKOP feedback).  RST is the raw external reset and must NOT be gated by
// `locked`, or the PLL could never start; the rest of the SoC waits for `locked`
// through sv16_startup's clk_ready input.
//
// Rev B: new module (ADR-021).

`timescale 1ns / 1ps

module sv16_pll #(
    parameter int REF_MHZ   = 25,   // reference (board oscillator) frequency
    parameter int CLKI_DIV  = 1,    // pre-divider: fPFD = REF / CLKI_DIV
    parameter int CLKFB_DIV = 2,    // feedback divider: fOUT = fPFD * CLKFB_DIV
    parameter int CLKOP_DIV = 12    // VCO divider: fVCO = fOUT * CLKOP_DIV
) (
    input  logic clk_ref,
    input  logic rst,               // asynchronous, active high (raw reset)
    output logic clk_out,
    output logic locked
);

    // Output phase 0 degrees: this primitive counts the coarse phase in VCO
    // cycles and (CLKOP_DIV - 1) is the unshifted position.
    localparam int CLKOP_CPHASE = CLKOP_DIV - 1;

`ifdef VERILATOR
    // ------------------------------------------------------- simulation model
    // A free-running oscillator at fOUT = fREF / CLKI_DIV * CLKFB_DIV, with
    // edges placed by delay.  It cannot be derived from the reference clock's
    // own edges (37.5 MHz has 1.5 edges per 25 MHz cycle, and no clocked
    // process can create more edges than it is given — the first version of
    // this model tried, and produced 12.5 MHz).  Frequency-accurate; the lock
    // delay is a fixed 64 reference cycles rather than an analog model.
    localparam real HALF_NS = 1000.0 * CLKI_DIV / (2.0 * REF_MHZ * CLKFB_DIV);

    logic [31:0] lock_cnt;
    logic        lock_ff;

    // Generated clock: a square wave at fOUT, running while reset is released.
    initial begin : ckgen
        clk_out = 1'b0;
        forever begin
            if (rst) @(negedge rst);
            while (!rst) begin
                #(HALF_NS) clk_out = ~clk_out;
            end
            clk_out = 1'b0;          // held reset: the clock stops
        end
    end

    // LOCK: asserted 64 reference cycles after reset is released.
    initial lock_ff = 1'b0;

    always_ff @(posedge clk_ref or posedge rst) begin
        if (rst) begin
            lock_cnt <= 32'd0;
            lock_ff  <= 1'b0;
        end else if (lock_cnt < 32'd64) begin
            lock_cnt <= lock_cnt + 32'd1;
            lock_ff  <= 1'b0;
        end else begin
            lock_ff  <= 1'b1;
        end
    end

    assign locked = lock_ff;

`else
    // ------------------------------------------------------- ECP5 hard macro
    // The attributes are the loop-filter settings the Lattice wizard emits for
    // this reference range; prjtrellis reads them out of the netlist.
    (* FREQUENCY_PIN_CLKI = "25.0" *)
    (* ICP_CURRENT = "12" *) (* LPF_RESISTOR = "8" *)
    (* MFG_ENABLE_FILTEROPAMP = "1" *) (* MFG_GMCREF_SEL = "2" *)

    logic clk_fb;

    EHXPLLL #(
        .CLKI_DIV(CLKI_DIV),
        .CLKFB_DIV(CLKFB_DIV),
        .CLKOP_DIV(CLKOP_DIV),
        .CLKOP_CPHASE(CLKOP_CPHASE),
        .CLKOP_FPHASE(0),
        .CLKOP_ENABLE("ENABLED"),
        .CLKOS_ENABLE("DISABLED"),
        .CLKOS2_ENABLE("DISABLED"),
        .CLKOS3_ENABLE("DISABLED"),
        .FEEDBK_PATH("CLKOP"),
        .OUTDIVIDER_MUXA("DIVA"),
        .OUTDIVIDER_MUXB("DIVB"),
        .OUTDIVIDER_MUXC("DIVC"),
        .OUTDIVIDER_MUXD("DIVD"),
        .PLLRST_ENA("DISABLED"),
        .INTFB_WAKE("DISABLED"),
        .STDBY_ENABLE("DISABLED"),
        .DPHASE_SOURCE("DISABLED"),
        .REFIN_RESET("DISABLED"),
        .SYNC_ENABLE("DISABLED")
    ) u_pll (
        .CLKI      (clk_ref),
        .CLKFB     (clk_fb),
        .CLKINTFB  (clk_fb),
        .RST       (rst),
        .CLKOP     (clk_out),
        .CLKOS     (),
        .CLKOS2    (),
        .CLKOS3    (),
        .LOCK      (locked),
        .INTLOCK   (),
        .REFCLK    (),
        .PHASESEL1 (1'b0),
        .PHASESEL0 (1'b0),
        .PHASEDIR  (1'b0),
        .PHASESTEP (1'b0),
        .PHASELOADREG(1'b0),
        .STDBY     (1'b0),
        .PLLWAKESYNC(1'b0),
        .ENCLKOP   (1'b0),
        .ENCLKOS   (1'b0),
        .ENCLKOS2  (1'b0),
        .ENCLKOS3  (1'b0)
    );
`endif

endmodule
