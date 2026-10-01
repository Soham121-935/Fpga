# SV-16 microcontroller — PCB design blueprint

**Status: design specification for review — no board has been built or ordered.** Nothing in this
document has been validated on hardware; every number is either taken from a cited document (Lattice
datasheet / technical note / BSDL model) or measured from this repository's own build artifacts. Items
that still need bench or vendor verification are collected in §13.2.

**What it is:** a complete component list, electrical specification and connection diagram for turning
the SV-16 soft-core that lives in this repository into a **stand-alone MCU-class board** built around a
single Lattice **LFE5U-12F-6TG144C** (ECP5, 144-lead TQFP, speed grade 6, commercial temperature).

**Sourcing note (revision 1.1):** the component list was originally written for US/EU distributors. It
has been re-sourced for India: every part below is available from a domestic vendor, with the electrical
equivalent spelled out where the original choice had to be replaced. §3.6 is the change list.

**It is not:** a copy of an evaluation kit, and not a general-purpose FPGA dev board. The board exists to
run the firmware in `firmware/` — boot from non-volatile memory, talk on a serial console, be
reprogrammed in the field, and drive a small motor — which is exactly what the SoC in `rtl/` implements.

| | |
| :--- | :--- |
| Device | LFE5U-12F-6TG144C — ECP5, 12,144 LUT4, 32 × sysMEM (72 KB), 28 multipliers, 2 PLL, 144-TQFP |
| Fit of the current SoC | 9,191 LUT4 (75.7 %), 4,772 FF (39.3 %), 18/32 DP16KD (56.2 %), 1/2 EHXPLLL, 52/98 I/O |
| Bitstream | 292,752 B compressed (`build/pll/sv16_top.bit`), 45.45 MHz max core clock |
| I/O banks used | 0, 1, 2, 3, 7, 8 — all LVCMOS33 (3.3 V), 52 signals constrained, 46 spare I/O |
| Storage | 2 × 3.3 V SPI NOR: one for the FPGA bitstream, one for SV-16 firmware images |
| Console / update | USB-C → CH340C → 115200 8N1 UART → ROM monitor (erase / upload / verify / boot) |
| Debug / config | 1×10 0.1" and 2×5 0.05" JTAG headers; TCK ≤ 25 MHz (BSDL `TAP_SCAN_CLOCK`) |
| Power in | 7–12 V DC barrel (recommended) or USB-C 5 V; 3.3 V / 2.5 V / 1.1 V rails generated on board |
| Sourcing | **every part is orderable from an Indian vendor** (Robu, Zbotic, QuartzComponents, Sunrom, Hubtronics, Sharvie, KTRON, iFutureTech, DNA Tech) except the FPGA and the oscillator, which come from digikey.in / mouser.in / element14 India — see §3 |

## 0.1 Where the numbers come from

| Fact | Source |
| :--- | :--- |
| Pin numbers, banks, pad names, the 98 user-I/O pins | `board/ecp5_tqfp144.json`, cross-built from the prjtrellis device database for **LFE5U-12F TQFP144** (98 user-I/O pin numbers + banks) and the Lattice BSDL model **FPGA-MD-02097** (`LFE5U_25F_XXTG144`, pad names, the 7 dedicated sysCONFIG pins, the 4 TAP pins, every VCC/VCCAUX/VCCIO/VSS pin) |
| Which pin carries which design signal | `constraints/ecp5_144tqfp.lpf` — the same file the bitstream is built with |
| Rail voltages, tolerances, ramp rates, POR trip points, LVCMOS33 range | `ECP5 and ECP5-5G.pdf` in this repository — **FPGA-DS-02012-3.4**, Tables 3.1–3.5, 3.8, 3.11, §4.3.2 |
| Configuration strapping, pull-ups, MCLK, `PERSISTENT` | Lattice **TN1260** (ECP5 sysCONFIG) and **TN-02039** (sysCONFIG usage guide); pull-up values from the ECP5 hardware checklist **TN-02038-2.0** Table 6.2 |
| JTAG header pinout | Lattice ECP5 Versa EB98/EB103 Appendix A (1×10 header) and the Digilent/FT2232H 2×5 0.05" standard |
| Pinout of every constrained signal on the board | `board/TQFP144_PINOUT.md` (generated) |

**Printables.** This document exists twice: `BOARD.md` (the source of truth, with the generated netlist
appendix in `board/TQFP144_PINOUT.md`) and **`BOARD.pdf`** — the same content typeset for printing, with
the ASCII diagrams kept in a monospaced face. Rebuild the PDF with `make board-pdf`
(`python3 -m pip install markdown xhtml2pdf` once; nothing else in the build needs those packages).

**Drift control.** `board/TQFP144_PINOUT.md` is generated from the two files above and is verified in
`make lint`:

```sh
scripts/sv16_board_pins.py            # regenerate the pin/net table
scripts/sv16_board_pins.py --check    # fail if the checked-in table is stale
scripts/sv16_board_pins.py --summary  # bank/usage summary only
```

If somebody moves a signal in `constraints/ecp5_144tqfp.lpf`, `--check` fails until the board document
is regenerated, so the schematic and the bitstream cannot silently disagree.

---

## 1. Board-level block diagram

```
                   +7..12 V barrel (J9)        USB-C (J8: VBUS + D+/D-)
                          |                          |
                     [D8 SS34]                  [D9 SS34]   CC1/CC2 = 5.1k Rd
                          +------------+-------------+
                                       |  VM_IN (4.6 ... 12 V)
                    +------------------+------------------+
                    |                                     |
            +-------+--------+                    +-------+--------+
            | U5 LM2596S-3.3 |                    | U6 MP1584EN    |  EN delayed ~13 ms (R41/C31)
            | 3.3 V / 3 A    |                    | 1.1 V / 3 A    |  R38/R39 set 1.099 V
            | + D10 catch    |                    | + D11 catch    |
            +-------+--------+                    +-------+--------+
                    |                                     |            (C21 100u, C2-C7 100n)
                  3V3  (C23 470u in, C24 220u, C25 10u)  1V1  ────►  U1 VCC (6 pins)
                    |
            +-------+--------+   Q3 AO3401 load switch, gate delay ~54 ms (R42/R43/C32)
            | U7 AMS1117-2.5 |◄─────────────────────────────────────
            | 2.5 V / 1 A    |
            +-------+--------+
                    |            (C22 22u, C8-C11 100n)
                   2V5  ────►  U1 VCCAUX (4 pins)

                   3V3  ────►  U1 VCCIO0/1/2/3/6/7/8 (9 pins) + Y1 oscillator + both flashes
                    |                + CH340C + LEDs
                    |
   =================|=================================================================
                    |
                  +-+-----------------------------------------------------------------+
                  |   VCC (6)      VCCAUX (4)      VCCIO0/1/2/3/6/7/8 (9)       |
                  |                     U1  LFE5U-12F-6TG144C                  |
                  |        bank 8 = VCCIO8 = configuration + JTAG supply        |
                  +--+--------------+---------------+---------------+-----------+
                     |              |               |               |
        Master SPI   |              | user SPI      | UART          | GPIOA/B, PWM
   (dedicated pads)  |      (bank 1 pads 110-113)   | (bank 3)      | (banks 0/1/2/7/8)
        +------------+--+        +--+----------+    |               |
        | U2 W25Q64JV   |        | U3 W25Q64JV |    |               |
        | FPGA bitstream|        | SV-16 slots |    |               |
        +---------------+        +-------------+    |               |
                                                    |               |
        J1 1x10 JTAG ---- TCK/TMS/TDI/TDO ------+   |               |
        J2 2x5  JTAG (parallel)                 |   |               |
        SW1 reset -> ext_rst_n (pin 134)        |   |               |
        SW2 PROGRAMN (pin 57)                    |   |               |
        D1 DONE, D6 INITN, D2-D5 user LED (GPIOA[3:0])               |
                                                 |   |               |
                                     U4 CH340C --+---+  J10 UART hdr |
                                     (USB console)                  |
                                                                    |
      J5 EXP-C (GPIOA[7:0])  J3 EXP-A (SPI0 + GPIOA[15:8])  J4 EXP-B (GPIOB[15:0])
      J6 motor (PWM, DIR1, DIR2, FAULTn, VM)     J7 spare-I/O breakout (46 pins, not fitted)
   ===================================================================================
```

The soft-core sees this board through its memory map: GPIOA/GPIOB at `0xF010`/`0xF070`, PWM+quadrature
motor block at `0xF030`, SPI0 at `0xF050`, UART0 at `0xF000`, watchdog at `0xF080`, SPI flash controller
at `0xF0A0` (`docs/MEMORY_MAP.md`, `docs/PERIPHERALS.md`). Every board signal below maps to one of those
registers — the board adds nothing the SoC cannot already drive.

## 2. Decisions that shaped the board (and why)

1. **One I/O rail: 3.3 V everywhere.** The existing LPF constrains all 52 signals to `LVCMOS33`, which
   needs VCCIO 3.135–3.465 V (datasheet Table 3.11). Rather than split banks across rails (which would
   force LPF and bitstream changes), all six used banks sit on 3V3. The flash, the USB bridge and the
   25 MHz oscillator are all 3.3 V parts, so no level shifting is needed anywhere.
2. **Power-up order is enforced by two RC-delayed enables, not by hope.** In Master SPI mode the datasheet
   requires VCCIO8 to be above the flash's input-high threshold before VCC *or* VCCAUX reach their POR
   trip points, otherwise PROGRAMN/INITN must be held low until VCCIO8 is valid (§3.5 of FPGA-DS-02012-3.4).
   The India-available regulators (LM2596, MP1584) do **not** accept a 3.3 V input, so VCC can no longer
   be *derived* from VCCIO8 as in revision 1.0. Instead their enable pins are used: the 1.1 V buck gets an
   RC on `EN` (≈6 ms at 12 V, ≈13 ms at 5 V) and the 2.5 V LDO is fed through a P-MOSFET load switch
   whose gate RC (R42/R43/C32) delays it by ≈54 ms from 12 V.
   3V3 = VCCIO8 therefore reaches the flash threshold ≈0.3 ms after power-up, long before either other
   rail moves. §4.3 has the numbers, the bench check is bring-up step 3 in §10.
3. **Two SPI flashes, not one.** The FPGA's configuration port is not memory-mapped: the MSPI pads
   (CCLK = pin 54, MOSI = pin 47, MISO = pin 46, CSSPIN = pin 49) belong to the configuration logic
   while `PERSISTENT` is set, and the soft-core cannot read or write the bitstream flash through them.
   The SV-16 firmware store must therefore be a *separate* device on ordinary user I/O (bank 1,
   pins 110–113), which is what `sv16_flash_ctrl` and the bootloader already expect. Consequences and
   the pin-sharing rule are spelled out in §6.4 — this is the single most important thing to understand
   about this board.
4. **25 MHz single-ended oscillator, PLL on-chip.** The design is built for `clk_25m` on pin 133 and the
   PLL recipe CLKI 2 / CLKFB 3 / CLKOP 16 → 37.5 MHz core (VCO 600 MHz), giving 45.45 MHz of margin. A
   3.2 × 2.5 mm 4-pin CMOS XO is cheaper and more robust than a crystal on the FPGA's oscillator pad,
   and it also supports the `CLKSRC=osc` build (25 MHz, no PLL) unchanged.
5. **USB-UART instead of a second USB device controller.** The console/update path is the same UART the
   ROM monitor already speaks: a CH340C makes it a single USB-C cable. The optional DTR→PROGRAMN
   transistor lets a host script reconfigure the FPGA, but it is jumper-disableable because DTR polarity
   differs between host tools.
6. **JTAG is the primary configuration and recovery path.** A 1×10 0.1" header (Versa-compatible) and a
   2×5 0.05" header (FT2232H/HS2-compatible) are wired in parallel, so both a cheap FT232H adapter and a
   Digilent-style probe work. JTAG always works even when the configuration flash is blank or corrupt —
   that is the brick-recovery path.
7. **Motor interface on the pins the SoC already drives.** `pwm_out` (pin 88, 16 mA), `motor_dir1/2`
   (GPIOA[4]/[5] mirrored to pins 89/102) and `motor_fault_n` (pin 103, pulled up) go to a keyed 1×6
   header with the motor supply passed through, so an external driver board (or a future on-board driver,
   §14 V3) plugs straight in. No new logic.
8. **Every spare pin is brought out.** 46 of the 98 I/O pins are unused by the current design; they go to
   a 2×25 footprint `J7` (not fitted by default) with interleaved grounds so the board can grow without a
   respin.

---

## 3. Bill of materials — India-sourced edition

Everything below is orderable from an Indian vendor that ships domestically: no US/EU freight, no customs
paperwork on your side. Where revision 1.0 picked a part that only exists on the global distributors'
shelves, it has been replaced by an electrical equivalent that is in stock in India — and because two
regulators changed, the power tree, the sequencing scheme and the schematic sheet in §4 and §7.1 changed
with them. §3.6 is the change list.

**Sourcing tiers**

| Tier | Vendors | Order from here |
| :--- | :--- | :--- |
| **1 — Indian component shops** (₹ pricing, 2–5 day delivery, no customs) | Robu.in · Zbotic.in · QuartzComponents.in · Sunrom.com · Hubtronics.in (the old rareComponents) · Sharvie Electronics · KTRON India · iFutureTech · Robocraze · DNA Tech · ElectronicsComp | passives, connectors, LEDs, MOSFETs, both SPI flashes, CH340C, USBLC6, LM2596S-3.3, MP1584EN, AMS1117-2.5, modules |
| **2 — Indian storefronts of the global distributors** (INR pricing, domestic delivery, they handle customs) | digikey.in · mouser.in · in.element14.com · in.rs-online.com | **U1 (the FPGA)** and the 25 MHz oscillator — the two parts no hobby shop stocks; also anything tier 1 has run out of |
| **3 — marketplaces** (AliExpress, IndiaMART, eBay.in, third-party Amazon.in) | use with care | last resort for passives and modules. **Never buy the FPGA here** — relabelled, refurbished and out-of-spec ECP5 parts are a known problem, and a fake costs you a board and a fortnight |

Prices are indicative, single unit, GST included, from a September 2026 stock check — verify before
ordering. Passives are **0603** (stock standard in India and hand-solderable; revision 1.0's 0402 was
chosen for density and is a bad idea when you are soldering it yourself). Electrolytics are now required
(the two bucks are non-synchronous and the LM2596 needs real bulk capacitance).

### 3.1 Active devices

| Ref | Part number | Specification | Package | Qty | Where (indicative ₹) |
| :--- | :--- | :--- | :--- | :-: | :--- |
| U1 | **LFE5U-12F-6TG144C** | ECP5 FPGA, 12,144 LUT4, 72 KB sysMEM, 28 mult, 2 PLL, VCC 1.1 V, VCCAUX 2.5 V, speed 6, commercial 0–85 °C Tj | TQFP-144 20×20 mm, 0.5 mm | 1 | **digikey.in ≈ ₹1,650** incl. GST (in stock Sept 2026) · mouser.in · in.element14.com. No substitute exists — §3.4 |
| U2 | **W25Q64JVSSIQ** | 64 Mbit (8 MB) SPI NOR, 2.7–3.6 V, standard SPI + dual/quad | SOIC-8 208 mil | 1 | Sharvie Electronics ₹75 · Hubtronics ₹117 · KTRON · Robu sells a W25Q64 breakout module for ₹77 (§3.5) |
| U3 | **W25Q64JVSSIQ** | same device — SV-16 firmware slots. `W25Q32JVSSIQ` (4 MB) or `W25Q16JV` is already enough: the images are 32 KB per slot | SOIC-8 208 mil | 1 | as U2 |
| U4 | **CH340G** | USB 2.0 full-speed ↔ UART, 3.3 V, V3 to 3V3 at 3.3 V operation. **Needs an external 12 MHz crystal (Y2) + 2 × 22 pF (C36/C37, 33 pF if the crystal is a 20 pF-load type)** — the G version has no internal clock; the CH340C is the pin-compatible part that does not need them | SOP-16 150 mil | 1 | iFutureTech · Hubtronics · Robu. Pairs with Y2 below |
| U5 | **LM2596S-3.3** *(was AP63203)* | buck, 4.5–30 V in, **3.3 V fixed**, 3 A, 150 kHz, non-synchronous → **needs D10** | TO-263-5 | 1 | Robu ₹51 (XBLW) / ₹61 (Slkor) — listed in stock |
| U6 | **MP1584EN-LF-Z** *(was TPS62823)* | buck, 4.5–28 V in, adjustable 0.8–20 V, 3 A, up to 1.5 MHz, non-synchronous → **needs D11 and R38/R39** | SOIC-8E | 1 | Hubtronics ₹47 (361 in stock) · Sunrom · others |
| U7 | **AMS1117-2.5** *(was LP5907)* | LDO, 2.5 V, 1 A, needs ≥10 µF on the output | SOT-223 | 1 | Robu / QuartzComponents ₹12–20 |
| Y1 | **YIC OSC25M-3.3I/S3-25T** *(was ASEMB)* | **25.000 MHz XO**, 3.3 V CMOS, ±25 ppm, enable/disable | 3.2×2.5 mm SMD-4 | 1 | **digikey.in ₹111** · any 25 MHz **3.3 V active** oscillator in 7050/5032 (Amazon.in / eBay.in sell the 5×7 mm 4-pin type) works |
| Y2 | **12 MHz quartz crystal** (CH340G only) | **12 MHz exactly** — the chip accepts 11.98–12.02 MHz, so the 25 MHz part cannot be substituted. CL 12–20 pF, 2-pin **passive crystal** — the CH340G's internal inverter oscillates it. HC49/US through-hole or 3225 SMD both work | HC49/US or SMD-2 | 1 | Robu / Zbotic ₹15–25. **Skipped entirely if U4 is a CH340C** |
| D1–D5 | LED 0603, green | DONE indicator + four user LEDs (GPIOA[3:0], active low) | 0603 | 5 | Robu / Zbotic ₹1–2 each |
| D6, D7 | LED 0603, red | INITN indicator (DNP by default) + 3V3 power LED | 0603 | 2 | as above |
| D8, D9 | **SS34** | Schottky 40 V / 3 A — barrel and USB input ORing | SMA | 2 | Robu ₹3 |
| D10 | **SS34** | catch diode for the 3V3 LM2596 | SMA | 1 | as above |
| D11 | **SS34** | catch diode for the 1V1 MP1584 | SMA | 1 | as above |
| Q1 | **2N7002** | N-MOSFET, PROGRAMN pull-down from DTR (optional auto-reconfigure) | SOT-23 | 1 | Robu / QuartzComponents ₹5 |
| Q2, Q4 | **BC817 (NPN) / BC807 (PNP)** *(was MMBT3904/3906)* | indicator drivers for DONE and INITN — identical function, the part Indian shops actually stock | SOT-23 | 2 | Zbotic / Robu ₹2 each |
| Q3 | **AO3401** | P-MOSFET load switch that delays the 2.5 V LDO (sequencing, §4.3) | SOT-23 | 1 | Robu / Zbotic ₹8 |
| U8 | **USBLC6-2SC6** | USB D+/D− ESD protection, 2 channels + VBUS | SOT-23-6 | 1 | Sunrom ₹30 · DNA Tech ₹32 |
| — | SN74LVC1T45 *(optional)* | level shifter, only if a 5 V UART adapter is used on J10 | SOT-23-6 | 0 | Robu / QuartzComponents if needed |

### 3.2 Connectors, switches, protection

| Ref | Item | Specification | Qty | Where / notes |
| :--- | :--- | :--- | :-: | :--- |
| J1 | 1×10 header, 2.54 mm | JTAG / configuration, Versa pinout (§8) | 1 | Robu ₹10 — the header that definitely exists in India |
| J2 | 2×5 box header, **1.27 mm** | Digilent / FT2232H-style adapter | 1 | 1.27 mm box headers are patchy in India: if you cannot find one, **leave J2 unpopulated** and use J1 with a 2.54 mm ribbon; or fit a 2×5 2.54 mm header and use an adapter cable |
| J3, J4 | 2×10 headers, 2.54 mm | EXP-A (SPI0 + GPIOA[15:8]) and EXP-B (GPIOB[15:0]) | 2 | Robu ₹15 each |
| J5 | 1×10 header, 2.54 mm | EXP-C: GPIOA[7:0] | 1 | pins 2/3/5/7 share nets with the config flash — §6.4 |
| J6 | 1×6 keyed header, 2.54 mm | motor: VM, GND, PWM, DIR1, DIR2, FAULTn | 1 | Robu ₹15 |
| J7 | 2×25 header, 2.54 mm | spare-I/O breakout (46 signals + 4 GND) | 1 | footprint only, **not fitted** |
| J8 | **USB-C receptacle 16-pin** — or micro-USB B | power + console. With micro-USB, omit R36/R37 | 1 | Robu / Zbotic ₹25 (USB-C) or ₹10 (micro-USB, easier to hand-solder) |
| J9 | DC barrel jack 5.5 / 2.1 mm | centre positive, 7–12 V | 1 | Robu ₹20 |
| J10 | 1×4 header, 2.54 mm | 3V3, UART_TX, UART_RX, GND (console without the CH340C) | 1 | Robu ₹5 |
| SW1, SW2 | 6×6 mm tactile switches | reset → `ext_rst_n`; reconfigure → PROGRAMN | 2 | Robu ₹5 each |
| JP1 | 2-pin header + shunt | disables Q1 (DTR auto-reconfigure) | 1 | Robu ₹5 |
| TP1–TP6 | 1 mm pads or test loops | 3V3, 2V5, 1V1, GND, DONE, INITN | 6 | — |
| — | 0603 resistor + capacitor assortment kit | avoids buying 100 individual reels | 1 | Robu ₹500–800 — worth it once, and it covers every passive on this board |

### 3.3 Passives

| Ref | Value | Package | Qty | Purpose |
| :--- | :--- | :--- | :-: | :--- |
| R1 | 10 kΩ | 0603 | 1 | `ext_rst_n` pull-up (the pin has an internal pull-up; this is for noise and SW1) |
| R2 | 4.7 kΩ | 0603 | 1 | PROGRAMN pull-up to 3V3 (TN-02038 Table 6.2) |
| R3, R4 | 4.7 kΩ | 0603 | 2 | INITN and DONE pull-ups to 3V3 |
| R5, R6, R7 | 4.7 kΩ / 1 kΩ / 1 kΩ | 0603 | 3 | mode straps: CFG1 = 1 (4.7 k to 3V3), CFG0 = 0, CFG2 = 0 (1 k to GND) |
| R8 | 1 kΩ | 0603 | 1 | MCLK/CCLK pull-up to 3V3 |
| R9–R12 | 100 Ω | 0603 | 4 | series resistors in the four Master-SPI nets — damping, and they bound any contention with GPIOA[1]/[2]/[4]/[6] (§6.4) |
| R13–R15 | 10 kΩ | 0603 | 3 | config flash (U2) `/CS`, `/WP`, `/HOLD` pull-ups to 3V3 |
| R16–R19 | 10 kΩ | 0603 | 4 | application flash (U3) `/CS`, `/WP`, `/HOLD` pull-ups; `motor_fault_n` pull-up |
| R21–R24 | 0 Ω | 0603 | 4 | UART routing: R21/R23 = CH340C, R22/R24 = J10 (populate one pair only) |
| R25, R26 | 4.7 kΩ / 10 kΩ | 0603 | 2 | Q1 gate series resistor and gate pull-down |
| R27–R30 | 470 Ω | 0603 | 4 | user LED series resistors |
| R31–R34 | 1 kΩ | 0603 | 4 | indicator drives: R31 = Q4 base, R32 = Q2 base, R33/R34 = series for D1/D6 |
| R36, R37 | 5.1 kΩ | 0603 | 2 | USB-C CC1/CC2 Rd (omit with micro-USB) |
| **R38** | **12.4 kΩ (E96)** | 0603 | 1 | **1V1 feedback divider, top**: 0.8 × (1 + 12.4/33) = **1.1006 V** (was 37.4 kΩ with a 100 kΩ bottom — see R39) |
| **R39** | **33 kΩ** | 0603 | 1 | **1V1 feedback divider, bottom** — measure this rail before fitting U1 (§10 step 2). **Corrected from 100 kΩ:** the MP1584 datasheet keeps the *lower* divider resistor **below 40 kΩ**, because the FB pin's ≈20 µA bias current would otherwise push the output outside the FPGA's 1.045–1.155 V window |
| **R40** | 100 kΩ | 0603 | 1 | MP1584 `FREQ` resistor → **900 kHz** (datasheet: R = 180000/f^1.1 with R in kΩ and f in kHz; its own table gives 100 kΩ = 900 kHz) |
| **R41** | 100 kΩ | 0603 | 1 | MP1584 `EN` series resistor (with C31 = the ≈13 ms sequencing delay) |
| **R42** | **1 MΩ** | 0603 | 1 | Q3 gate **to GND** — this is what turns the load switch *on* (with C32 = the 2V5 delay). Revised from 47 kΩ: see R43 |
| C1 | 100 nF | 0603 | 1 | `ext_rst_n` RC (with R1) |
| C2–C7 | 100 nF | 0603 | 6 | 1V1 decoupling, one per VCC pin (20, 29, 38, 66, 83, 130) |
| C8–C11 | 100 nF | 0603 | 4 | 2V5 decoupling, one per VCCAUX pin (17, 53, 96, 132) |
| C12–C20 | 100 nF | 0603 | 9 | 3V3 decoupling, one per VCCIO pin (9, 16, 36, 43, 70, 86, 100, 122, 137) |
| C21 | 100 µF / 10 V electrolytic + 100 nF | 6.3×5.4 mm / 0603 | 1+1 | 1V1 bulk (MP1584 is non-synchronous — needs real bulk) |
| C22 | 22 µF / 10 V electrolytic + 100 nF | 5×5 mm / 0603 | 1+1 | 2V5 bulk |
| C23 | **470 µF / 35 V electrolytic** + 100 nF | 10×10 mm / 0603 | 1+1 | LM2596 input bulk (datasheet value for a 5–12 V input) |
| C24 | **220 µF / 16 V electrolytic** + 100 nF | 8×7 mm / 0603 | 1+1 | LM2596 output bulk for the 3V3 rail |
| C25 | 10 µF | 0805 | 1 | 3V3 bulk near banks 0/1/6/7 |
| C26 | 100 nF | 0603 | 1 | Y1 oscillator decoupling |
| C27 | 100 nF | 0603 | 1 | CH340C decoupling |
| C28, C29 | 100 nF | 0603 | 2 | flash decoupling (one per device) |
| **C30** | 10 µF in + 10 µF out | 0805 | 2 | AMS1117 input/output — it wants ≥10 µF, and ceramics can make it ring; bench check (OQ-B10) |
| **C31** | 470 nF | 0603 | 1 | MP1584 `EN` delay capacitor (≈13 ms with R41) |
| **C32** | **4.7 µF** | 0805 | 1 | Q3 gate→**source** delay capacitor: τ = (R42∥R43)·C32 = 91 kΩ × 4.7 µF ≈ 428 ms, crossing the AO3401 threshold at ≈54 ms from 12 V |
| C33 | 100 nF | 0603 | 1 | MP1584 bootstrap (`BST`) capacitor |
| C36, C37 | 22 pF | 0603 | 2 | CH340G crystal load capacitors (XI and XO to GND). **Match to the crystal:** 22 pF for a CL = 12 pF crystal, 33 pF for the common CL = 20 pF HC49/US type (WCH quotes both values across datasheet revisions). **Omit with a CH340C** |
| **R43** | **100 kΩ** | 0603 | 1 | Q3 gate→source clamp: with R42 it holds Vgs at −VM_IN·1M/1.1M ≈ **−10.9 V** at 12 V, inside the AO3401's ±12 V rating (without it the gate would sit at GND and Vgs = −12 V, right on the absolute maximum) |
| L1 | **33 µH / 3 A** shielded | 8×8 mm | 1 | LM2596 3V3 inductor (datasheet value) |
| L2 | **10 µH / 3 A** shielded | 6×6 mm | 1 | MP1584 1V1 inductor |
| FB1 | ferrite bead 600 Ω @ 100 MHz | 0603 | 1 | VM_IN filtering ahead of the regulators |

**Cost band (India, one board):** U1 ≈ ₹1,650 is three quarters of the total; everything else together is
roughly **₹700–1,100** from tier-1 vendors. The module-first build of §3.5 trades about ₹200 for a much
easier assembly.

### 3.4 Sourcing the FPGA (the one part you cannot substitute)

* The design *is* an ECP5 design: `rtl/sv16_pll.sv` instantiates `EHXPLLL`, the boot ROM is initialised
  ECP5 block RAM, `constraints/ecp5_144tqfp.lpf` is a TQFP-144 pin map, and the bitstream comes out of
  `nextpnr-ecp5`. No other vendor's part fits, and no other ECP5 package fits either.
* **Buy it from an Indian storefront of a global distributor:** digikey.in, mouser.in or
  in.element14.com. They quote in ₹, ship domestically, and clear customs themselves. Lead time is
  40+ weeks when the part is not stocked, so **check availability before you commit to the PCB** — this
  is open item OQ-B13.
* **Acceptable substitutions** (same package, pin-compatible, same or better silicon):
  * **LFE5U-12F-7TG144C** — speed grade 7 instead of 6 (pin-identical, and often the part you can
    actually find). **Verified on this tree:** `make bitstream CLKSRC=osc FPGA_SPEED=7 BUILD=build/spd7`
    completes end to end — 9,407 LUT4 (77.5 %), 18/32 sysMEM, **49.53 MHz Fmax** at the 25 MHz
    constraint (the speed-6 build measures 44.70 MHz in the same configuration), and the resource guard
    accepts the `LFE5U-12F-7TQFP144` part string. Program it with `make prog FPGA_PART=LFE5U-12F`.
  * **LFE5U-12F-6TG144I** — industrial temperature grade. Drop-in, usually a little dearer.
  * **Do not** substitute another density (25F/45F) or package (BG256/BG381): the pin map, the PLL
    reference input and the whole LPF would have to be redone.
* **Want ECP5 silicon in your hands before the PCB exists?** A **Colorlight 5A-75B / 5A-75E** LED
  controller (₹1,500–3,000 via Amazon.in / IndiaMART / AliExpress) contains an **LFE5U-25F-6BG381C** and
  its JTAG header is publicly reverse-engineered (`q3k/chubby75`). It is *not* this board — different
  package, different pinout, needs its own LPF — but it is a cheap way to run the SV-16 SoC and this
  toolchain on real silicon while the PCB is being designed.

### 3.5 Module-first option (recommended for a first build in India)

Hand-soldering a 0.5 mm-pitch TQFP-144 is the hardest part of this board; the second hardest is getting
the two switchers right. If you want the first board to work on the first try, replace the power and
console sections with ready-made modules on 4-pin headers — the FPGA section and every net name
(3V3 / 2V5 / 1V1 / VM_IN, `uart_tx` / `uart_rx`) stay exactly the same:

| Instead of | Fit | ₹ | Why it is easier |
| :--- | :--- | :-: | :--- |
| U5 + L1 + D10 + C23 + C24 (3V3) | an **LM2596 buck module** (Robu ₹43–50) with its output set to 3.3 V | 45 | no inductor/diode/feedback to get wrong; the pot sets the voltage |
| U6 + L2 + D11 + R38/R39/R40/C31 + C21 (1V1) | a **Mini360 / MP1584 module** (Robu ₹105), output trimmed to **1.10 V, measured with a meter** | 105 | same reason; the divider risk disappears |
| U7 + Q3 + C30/C32 (2V5) | a second small buck module set to 2.5 V, or an AMS1117-2.5 breakout | 50–105 | |
| U4 + U8 + J8 (USB-UART) | a **CH340C + USB-C serial breakout** (Robu ₹149) — 4-pin header, cross TX/RX | 149 | no SOP-16, no USB routing, no ESD array |
| J2 + J1 (JTAG) | keep J1 (2.54 mm) — modules cannot replace this | 10 | |

Two caveats: modules make the §4.3 power-up order less deterministic (many MP1584 modules expose an `EN`
pad, so you can still add the RC delay — otherwise keep the PROGRAMN-hold fallback), and they are bulky:
reserve ~35 × 45 mm for the module area and mount them on headers rather than soldering them down, so you
can swap one out.

### 3.6 What changed from revision 1.0, and why each replacement is equivalent

| Rev 1.0 part | Now | Why it is an equivalent (not just "something similar") |
| :--- | :--- | :--- |
| U5 AP63203 (synch. buck, TSOT-26) | **LM2596S-3.3** (TO-263-5) | Same job: 3.3 V rail ≥ 2 A from a 5–12 V input. Slower (150 kHz vs 1.1 MHz) and non-synchronous, so it needs an external Schottky (D10) and much more bulk capacitance (C23/C24) — but 3 A rated and it is on the shelf in India for ₹51. Neutral for the FPGA: the rail is 3.3 V either way |
| U6 TPS62823 (synch. buck, 2.4–5.5 V in) | **MP1584EN** (SOIC-8E) | Same job: 1.1 V core rail, 3 A. Difference: the MP1584 needs **≥4.5 V input**, so it runs from VM_IN instead of from 3V3 — that is what forces the explicit sequencing in §4.3. 0.8 V reference (vs the TPS62823's lower one) sets 1.1 V with a divider, still inside the FPGA's 1.045–1.155 V window with 5 % margin |
| U7 LP5907-2.5 (LDO, SOT-23-5) | **AMS1117-2.5** (SOT-223) | Same job: 2.5 V for VCCAUX at 16 mA. Bigger, noisier and it needs ≥10 µF output — irrelevant for a 16 mA load of reference input buffers |
| Y1 ASEMB-25.000 (XO, 3.2×2.5) | **YIC OSC25M-3.3I/S3-25T** | Same job: 25.000 MHz, 3.3 V CMOS, ±25 ppm (better than the ±50 ppm the ±2 % UART tolerance needs). Any 25 MHz 3.3 V **active** oscillator in 5×7 mm works |
| R38–R42, C30–C33, D10, D11, Q3 | new | Sequencing and the passives the two new bucks require |
| passives 0402 | **0603** | Same values, hand-solderable; 0402 stays only if you shrink the board |
| "no electrolytics anywhere" | 470 µF + 220 µF + 100 µF + 22 µF electrolytics | Consequence of the two non-synchronous bucks |
| `L1 4.7 µH`, `L2 2.2 µH` | **33 µH** (LM2596) and **10 µH** (MP1584) | Inductor values are set by the switcher, not the load |

## 4. Power architecture

### 4.1 Rail generation

```
  J9 barrel 7-12 V ─[D8 SS34]─+                       J8 USB-C 5 V ─[D9 SS34]─+
                              |                                            |
                              +──────── VM_IN (4.6 ... 12 V) ──────────────+
                                            |         |         |
                                         [FB1]      C23 470u    |
                                            |      (electro)    |
                                  +---------+---------+         |
                                  |   U5 LM2596S-3.3  |--L1 33uH
                                  |   3.3 V / 3 A     |  D10 SS34 (catch)
                                  +---------+---------+
                                            |
                            3V3 ── C24 220u(electro) + C25 10u + 9 x 100n ─────────────+
                                            |                                          |
      ┌── directly to VCCIO0/1/2/3/6/7/8 ────┘                                          |
      |  (VCCIO8 = pin 43, the config port, is the first rail to become valid)          |
      |                                                                                 |
      |   ┌── U6 MP1584EN ── L2 10uH ── D11 SS34 (catch) ── 1V1 (C21 100u + 6 x 100n) ──┤
      +───┤    EN ◄── R41 100k (VM_IN) + C31 470n (GND)     ← ≈13 ms delay              |
      |   └── FB ◄── R38 37.4k (OUT) + R39 100k (GND) = 1.099 V                         |
      |                                                                                 |
      |   ┌── Q3 AO3401 (P-FET load switch) ── U7 AMS1117-2.5 ── 2V5 (C22 22u + 4 x 100n)
      +───┤    gate: R42 1M to GND, C32 4.7u to source, R43 100k clamp  ← ≈54 ms delay  |
          └── (C30 10u in / 10u out)                                                    |
                                                                                        |
   VCC (1.1 V)    = pins 20, 29, 38, 66, 83, 130  ◄─────────────────────────────────────┘
   VCCAUX (2.5 V) = pins 17, 53, 96, 132
   VCCIO0/1/2/3/6/7/8 (3.3 V) = pins 137, 122, 100, 70, 86, 16, 36, 9, 43
   VCCIO8 (pin 43) also powers the configuration port and the JTAG TAP.
```

### 4.2 Rails and current budget

| Rail | Pins (count) | Nominal | Allowed range (datasheet) | Consumers | Static budget |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1V1** (VCC) | 20, 29, 38, 66, 83, 130 (6) | 1.10 V — **set by R38/R39** | 1.045–1.155 V (Table 3.2); abs max 1.32 V (Table 3.1) | FPGA core | 77 mA typical (Table 3.8, TJ = 85 °C) + switching current; U6 rated 3 A |
| **2V5** (VCCAUX) | 17, 53, 96, 132 (4) | 2.50 V | 2.375–2.625 V; abs max 2.75 V | differential/referenced input buffers | 16 mA typical (Table 3.8) + 5 mA LDO quiescent; U7 rated 1 A |
| **3V3** (VCCIO + I/O) | 9, 16, 36, 43, 70, 86, 100, 122, 137 (9) | 3.30 V | 3.135–3.465 V for LVCMOS33 (Table 3.11); abs max 3.63 V | 6 banks + 2 flashes + oscillator + LEDs + CH340C + the 2V5 LDO's 5 mA | 6 × 0.5 mA typical (Table 3.8) + loads + U7 quiescent; U5 rated 3 A |
| VM_IN | J9 / J8 | 7–12 V (barrel, recommended) or 5 V (USB) | U5 input 4.5–30 V, U6 input 4.5–28 V — see the USB note below | U5, U6, the 5 V pins of J3/J4, J6 motor passthrough | external supply ≥ 1 A |

**USB-C power is at the input-voltage edge.** 5 V USB minus the SS34 drop (~0.4 V) leaves ≈ 4.6 V at
VM_IN, and both bucks want ≥ 4.5 V. That works for bench use at light load, but the margin disappears as
soon as the motor header is loaded — **use the barrel jack at 7–12 V for anything real**, or replace D9
with a P-MOSFET ideal-diode. Open item OQ-B12.

**Timing margin is not the same thing as power margin.** The static numbers above are from the datasheet;
this repository has **no** dynamic power estimate for the SoC (the open toolchain has no power analyser,
and `nextpnr` emits none). The regulators are therefore specified with a large margin, and
"measure the real 1V1 current during bring-up" is an explicit bring-up step (§10) and an open item
(§13.2 OQ-B1). Nothing on the board draws more than 3 A on any rail even in the worst case, and the
1V1 buck is current-limited, so an over-estimate cannot damage the device.

### 4.3 Power-up order, POR and the rules the board must not break

| Rule | Requirement | How this board satisfies it |
| :--- | :--- | :--- |
| Recommended levels | VCC 1.045–1.155 V, VCCAUX 2.375–2.625 V, VCCIO 1.14–3.465 V | fixed-value regulators: 1.10 V / 2.50 V / 3.30 V |
| Ramp rate | all supplies 0.01–10 V/ms; VCCAUX ≤ 30 mV/µs | LM2596 soft-start ≈ 1 V/ms; MP1584 ≈ 0.5 V/ms; AMS1117 ≈ 0.1 V/ms — all inside the window (verify on the bench, §10 step 3) |
| POR release | only when VCC, VCCAUX **and VCCIO8** are all above their trip points (0.90–1.00 V, 2.00–2.20 V, 0.95–1.06 V) | all three rails are generated and all three are monitored by the device itself; no board-side reset generator is needed |
| Master-SPI order (§3.5) | ramp VCCIO8 above the flash `VIH` (0.7 × 3.3 V ≈ **2.31 V**) **before** VCC or VCCAUX reach their POR trip (0.90–1.00 V and 2.00–2.20 V), or hold PROGRAMN/INITN low until VCCIO8 is valid | **explicitly sequenced** — see the timeline below. Because the India-sourced bucks need ≥4.5 V input, VCC and VCCAUX are no longer derived from 3V3, so the order is created with two RC networks instead of by construction |
| Fallback if the bench disagrees | the datasheet's second option | drive PROGRAMN low from the host (J1.4 / the CH340C DTR path through Q1) and release it after 3V3 is up; this is a firmware/host action, not a board change |
| VCCIO8 ramp-down | the device has **no ramp-down detection** on VCCIO8; a brown-out that only drops VCCIO8 while VCC stays valid can leave the part in an undefined state | the 3V3 rail is the master: if the supply collapses, VCC collapses with it (all rails come from the same VM_IN), so the device sees a clean power cycle. Do not add a separate 3V3-only cutoff switch |
| Sequencing on power-down | no requirement | bulk capacitance is sized so all three rails fall together; the 3V3 rail has the largest load (C23/C24/C25) and therefore falls last, which is what the datasheet wants |
| JTAG `VREF` | the 1×10 Versa-style header has no VREF pin, the 2×5 header does | J1.1 and J2.1 both sit on 3V3; adapters that measure VREF will read 3.3 V, and adapters that *level-shift* from VREF will drive 3.3 V logic correctly |

**Power-up timeline (typ, 12 V input).** `t = 0` is VM_IN applied.

| Time | Event | Consequence |
| ---: | :--- | :--- |
| ≈0.3 ms | 3V3 (U5, LM2596 soft-start) crosses 2.31 V | VCCIO8 is now above the config flash's `VIH` — the ordering requirement is met with two orders of magnitude of margin |
| ≈13 ms | U6 starts (EN released by R41/C31; threshold ≈1.2 V at 5 V in: t = −RC·ln(1 − 1.2/Vin), RC = 47 ms) | VCC begins to rise after VCCIO8 is fully valid |
| ≈14 ms | 1V1 crosses 0.90 V | VCC POR trip, comfortably after VCCIO8 |
| ≈54 ms | Q3 turns on (gate falls with τ = (R42∥R43)·C32 ≈ 428 ms, crossing the −1.3 V threshold) → 2V5 rises | VCCAUX POR trip, last of the three |
| ≈60 ms | POR releases (VCC, VCCAUX and VCCIO8 all above trip) | the device starts configuration from U2 |

### 4.4 Decoupling

| Rail | Bulk | Per-pin ceramic | Placement rule |
| :--- | :--- | :--- | :--- |
| 1V1 | C21 100 µF electrolytic | C2–C7 100 nF (6, one per VCC pin) | 100 nF within 3 mm of each pin, via to the ground plane directly beside the pad |
| 2V5 | C22 22 µF electrolytic | C8–C11 100 nF (4, one per VCCAUX pin) | same |
| 3V3 | C23 470 µF (input) + C24 220 µF (output) electrolytic + C25 10 µF ceramic | C12–C20 100 nF (9, one per VCCIO pin) | same; the 100 nF on VCCIO8 (pin 43) is the most important one on the board — it also decouples the configuration port |
| Input | — | 100 nF per regulator pin + FB1 | at the input diodes |

The electrolytics are the price of using two non-synchronous bucks; keep them close to their regulator
rather than near the FPGA, and keep the switching loops small (§11).

---

## 5. Clocking

```
   Y1 (25.000 MHz CMOS XO, 3.3 V)  ── CLK25 ──►  U1 pin 133  clk_25m
        |  power: 3V3 + C26 100 nF
        |  output enable (pin 1): tied to 3V3 (always on)
```

| Item | Value | Source |
| :--- | :--- | :--- |
| Frequency | 25.000 MHz | `constraints/ecp5_144tqfp.lpf` (`clk_25m`), `docs/RESET_AND_CLOCK.md` |
| Stability | ±25 ppm (the India-available YIC part) — far better than needed: the console runs 115200 8N1 (≈ ±2 % tolerance) and the tests are cycle-based | this design |
| Sourcing | **it must be an active oscillator, not a crystal.** ECP5 has no on-chip oscillator and the design expects a driven `clk_25m`, so a ₹39 passive 25 MHz crystal (the "YSX321SL" type that Indian shops list) will **not** work. Buy the YIC part from digikey.in (₹111) or any 25 MHz 3.3 V active oscillator in 5×7 mm / 3.2×2.5 mm from Amazon.in / eBay.in / Sunrom | |
| PLL configuration | CLKI_DIV 2, CLKFB_DIV 3, CLKOP_DIV 16 → CLKOP = 37.5 MHz, VCO = 600 MHz (inside the 400–800 MHz range) | `rtl/sv16_pll.sv`, `docs/ARCHITECTURE_DECISIONS.md` ADR-024 |
| Achieved timing | 45.45 MHz Fmax at the 37.5 MHz constraint (`build/pll/sv16_nextpnr.log`), 44.70 MHz in the `CLKSRC=osc` 25 MHz build | `docs/SYNTHESIS_AND_DEPLOYMENT.md` |
| Second clock | none. No DDR, no SERDES (the ECP5 144-TQFP offering has **0 SerDes channels**), no second oscillator input — the design has a single clock domain plus the hardened blocks | datasheet Table 1.1 / §4.3.2 |
| JTAG clock | TCK ≤ 25 MHz (`TAP_SCAN_CLOCK of TCK is (25.0e6, BOTH)` in the BSDL model) | FPGA-MD-02097 |
| Configuration clock | 25 MHz pin 54 output in Master SPI; the device starts at ≈ 2.4 MHz and may step up per the bitstream's `MCCLK_FREQ`. A 293 KB compressed image therefore takes ≈ 1 s to load | TN-02039 §6.1, estimate |

---

## 6. FPGA pin map and the board nets

`board/TQFP144_PINOUT.md` is the complete, generated 144-pin table (device pad, bank, rail, design
signal, drive strength, pull mode and board destination). This section is the human-readable summary.

### 6.1 Signals used by the current design (52 of 98 I/O pins)

| Function | Bank | Pins (TQFP144) | Drive / pull (from the LPF) | Board destination |
| :--- | :-: | :--- | :--- | :--- |
| 25 MHz clock | 0 | 133 | 4 mA | Y1.3 |
| Reset button input | 0 | 134 | 4 mA / pull-up | SW1 + R1 + C1 |
| Console UART | 3 | 73 (rx), 74 (tx) | 4 mA | CH340C (U4) / J10 |
| Application flash (bank-1 SPI) | 1 | 110 sck, 111 cs_n, 112 mosi, 113 miso | 8/8/8/4 mA | U3 (application flash) |
| SPI0 expansion | 1 | 114 sck, 115 cs_n, 116 mosi, 117 miso | 8/8/8/4 mA | J3 (EXP-A) |
| Status LEDs (mirror of GPIOA[3:0]) | 8 | 39, 40, 41, 44 | 8 mA | D2–D5 + R27–R30 |
| GPIOA[0:7] | 8 | 45–52 | 8 mA | J5 EXP-C + config-flash nets for [1],[2],[4],[6] (§6.4) |
| GPIOA[8:15] | 2 | 97, 98, 99, 104, 105, 106, 107, 108 | 8 mA | J3 EXP-A |
| GPIOB[0:7] | 0 | 135, 136, 139, 140, 141, 142, 143, 128 | 8 mA | J4 EXP-B |
| GPIOB[8:11] | 1 | 124, 125, 126, 127 | 8 mA | J4 EXP-B |
| GPIOB[12:15] | 7 | 1, 2, 3, 4 | 8 mA | J4 EXP-B |
| PWM / motor | 2 | 88 pwm (16 mA), 89 dir1, 102 dir2, 103 fault_n (pull-up) | see left | J6 motor header |

LEDs are not independent software GPIO: `rtl/sv16_top.sv` does `assign led = ~gpio_a_out[3:0]`, so the
LED pins always mirror GPIOA[3:0] and light when the bit is **0** (active low). GPIOA[3:0] are also on
J5 pins 4/5/6/7 — the header copy and the LED copy are separate FPGA pins, so a lever on J5 does not
have to disturb the LED indication, but both reflect the same register bit.

### 6.2 Spare I/O (46 pins)

| Bank | Free pins | Where brought |
| :-: | :--- | :--- |
| 1 | 118, 119, 120, 121 | J7 |
| 2 | 90, 91, 92, 93, 94, 95 | J7 |
| 3 | 67, 68, 69, 71, 72, 76, 77, 78, 79, 80, 81, 82, 84 | J7 |
| 6 | 18, 19, 22, 23, 24, 25, 26, 27, 28, 30, 31, 33, 34, 35, 37 | J7 |
| 7 | 5, 6, 7, 10, 11, 12, 13, 14 | J7 |

Banks 6 and 7 are unused by the current bitstream, so adding a peripheral to them costs nothing in
LUTs today. Two notes for whoever uses them: bank 3 pin 79 (`PR35B`, VREF1_3), bank 6 pin 19
(`PL35B`, VREF1_6) and bank 7 pin 11 (`PL14C`, VREF1_7) are `VREF` inputs, and bank 2 pin 88 is the
16 mA PWM output — do not stack heavy loads on it (it is already the motor PWM).

### 6.3 Active-low and direction conventions

| Signal | Direction | Idle / reset state | Consequence |
| :--- | :--- | :--- | :--- |
| `ext_rst_n` | input | high (pull-up), press = low | SW1 resets the SoC; the startup FSM then runs the boot sequence |
| `led[3:0]` | output | LEDs off (GPIOA[3:0] = 1 after reset) | active low |
| `flash_cs_n`, `spi0_cs_n` | output | high = deselected | active low |
| `motor_fault_n` | input | pulled up = "no fault" | active low; the motor block at `0xF030` reports it (`docs/PERIPHERALS.md`) |
| `uart_rx` | input | pulled up; must **not** be held low at power-up | the startup FSM forces the monitor after 4096 clocks of a held-low RX (`RX_HOLD_CYCLES`) — deliberate, and the reason the CH340C's TXD idles high |
| all GPIO | bidirectional | `dir_reg` = 0 on reset ⇒ inputs (high-Z) | this is what makes §6.4 safe in software |

### 6.4 The one hard constraint on this board: the Master-SPI pads are also GPIOA pins

The design constrains `gpio_a[0:7]` to bank-8 pins 45–52. Four of those pads are the device's Master-SPI
configuration port:

| TQFP pin | Pad | sysCONFIG role | Design signal | Board net |
| :-: | :--- | :--- | :--- | :--- |
| 46 | `PB11A` | `D1/MISO` — **input from the config flash** | `gpio_a[1]` | J5.2 **and** U2.2 (flash DO) via R11 100 Ω |
| 47 | `PB11B` | `D0/MOSI` — **output to the config flash** | `gpio_a[2]` | J5.3 **and** U2.5 (flash DI) via R10 100 Ω |
| 49 | `PB15A` | `HOLDN/DI/BUSY/CSSPIN` — **flash chip select** | `gpio_a[4]` | J5.5 **and** U2.1 (/CS) via R12 100 Ω |
| 51 | `PB15B` | `DOUT/CSON` — unused in a single-FPGA chain | `gpio_a[6]` | J5.7 only (no flash connection) |
| 39, 40, 41, 44, 45, 48, 50, 52 | `PB6A`, `PB4A`, `PB6B`, `PB4B`, `PB9A`, `PB13A`, `PB13B`, `PB18A` | parallel / slave-SPI pads, **not** claimed by Master SPI | `led[0:3]`, `gpio_a[0]`, `[3]`, `[5]`, `[7]` | headers / LEDs, free |

Why this is nevertheless safe, and what must be true for it to stay safe:

1. During configuration the configuration logic drives pins 54, 47, 46 and 49 and the fabric is held in
   reset, so the user I/O on those pads cannot fight it.
2. After configuration, the pads are released to the fabric **because the design does not set the
   `PERSISTENT` attribute** on the spi port. This is what "recovering the configuration port pins for use
   as general purpose I/O" means in TN-02039 §4.6.10. Keeping it that way is deliberate.
3. The **board uses a separate flash for firmware** (U3 on bank-1 pins 110–113). The bitstream flash (U2)
   is only touched by the configuration logic and by JTAG, never by the soft-core.
4. The four shared nets carry 100 Ω series resistors (R9–R12). If firmware ever drives `gpio_a[1]`,
   `[2]`, `[4]` or `[6]` as an output while U2 is driving DO, the series resistor bounds the current
   instead of letting two drivers fight. Software must still treat those four bits as **inputs**
   (they are inputs after reset, and nothing in the ROM monitor or the bootloader ever changes that).
5. Consequence for a user: J5 pins 2, 3, 5 and 7 are *not* free general-purpose pins on this board —
   they are the configuration flash's DO, DI, /CS and the unused DOUT line. Use a spare pin from §6.2 if
   you need a clean signal, or apply variant V1 (§14) which remaps those four GPIO bits.

Everything else about the pin map is uncomplicated: no pin used by the design is shared with the JTAG
TAP, and no pin used by the design is one of the dedicated sysCONFIG pins (PROGRAMN 57, INITN 55,
DONE 56, CCLK 54, CFG_0 62, CFG_1 59, CFG_2 58, TCK 63, TMS 64, TDI 61, TDO 60).

---

## 7. Connection circuit diagram

Sheets 1–5 below are the connection diagram. Net labels are the LPF signal names, so any net can be
traced back to a line in `constraints/ecp5_144tqfp.lpf` and to a row of `board/TQFP144_PINOUT.md`.
Pin numbers for U1 are TQFP-144 physical pins; pin numbers for the flashes are SOIC-8 as defined by the
W25Q datasheet; the CH340C is drawn by pin *name* (the vendor's SOP-16 numbering applies).

### 7.1 Sheet 1 — FPGA supply and ground

```
       1V1 rail (U6 MP1584EN)            2V5 rail (U7 AMS1117-2.5)        3V3 rail (U5 LM2596S-3.3)
       from VM_IN, EN delayed 6-13 ms   from Q3 load switch, 54 ms       from VM_IN, valid first
           |                               |                               |
   +---+---+---+---+---+---+       +---+---+---+---+               +---+---+---+---+---+---+---+---+---+
   |20 |29 |38 |66 |83 |130|       |17 |53 |96 |132|               | 9 |16 |36 |43 |70 |86 |100|122|137|
   |VCC|VCC|VCC|VCC|VCC|VCC|       |AUX|AUX|AUX|AUX|               |IO7|IO6|IO6|IO8|IO3|IO3|IO2|IO1|IO0|
   +-+-+---+---+---+---+---+       +-+-+---+---+---+               +-+-+---+---+---+---+---+---+---+---+
     | |   |   |   |   |             | |   |   |                     | |   |   |   |   |   |   |   |
    C2 C3  C4  C5  C6  C7           C8 C9 C10 C11                  C12 C13 ...                 ...   C20
   100n  (all to GND)              100n (all to GND)               100n (all to GND)
   + C21 100u (electro)            + C22 22u (electro)             + C24 220u + C25 10u

   U5 (3V3):  VM_IN → [C23 470u electro + 100n] → IN ; OUT → L1 33uH → 3V3 ; D10 SS34 from OUT to GND(anode)
              OUT → C24 220u → 3V3 ; ON/OFF pin → GND (always enabled) ; GND → plane
              FB (pin 4) → 3V3 : the fixed-output version senses its own output here, so this pin
              is NOT left floating (the TI datasheet's force-on/force-off tests are written as
              "feedback pin removed from output")
   U6 (1V1):  VM_IN → [100n] → IN ; EN ← VM_IN via R41 100k with C31 470n to GND (13 ms at 5 V in,
              ~6 ms at 12 V in: EN rising threshold 1.5 V, falling 1.2 V, tau = 47 ms)
              SW → L2 10uH → 1V1 ; D11 SS34 catch to GND ; BST → C33 100n → SW
              FB ← R38 12.4k from 1V1, R39 33k to GND (= 1.1006 V) ; C21 100u on the 1V1 rail
              FREQ → R40 100k → GND (= 900 kHz) ; GND (pin 5) and the exposed pad → plane
              COMP (pin 3): needs an RC compensation network to GND — values from the MP1584
              datasheet's typical application for 1.1 V out at 900 kHz (open item OQ-B10)
   Q3/U7 (2V5): VM_IN → Q3 AO3401 (S) → (D) → U7 AMS1117-2.5 IN → OUT = 2V5 → C22 22u
              (the AMS1117 needs >= 3.8 V in for a 2.5 V out, so this section runs from VM_IN,
              not from 3V3)
              Q3 gate: R42 1M to GND + C32 4.7uF to source + R43 100k source-to-gate (Vgs clamp);
              the gate starts at source potential (off) and falls with tau = 91k x 4.7uF = 428 ms,
              reaching the threshold at ≈54 ms from 12 V
              U7: C30 10u in, 10u out ; GND → plane

   Ground:  8 (VSSIO7)  15 (VSSIO6)  21 (VSS)  32 (VSSIO6)  42 (VSSIO8)  65 (VSS)  75 (VSSIO3)
            85 (VSS)  87 (VSSIO3)  101 (VSSIO2)  123 (VSSIO1)  129 (VSSIO0)  131 (VSS)  138 (VSSIO0)
            -> every pin to the GND plane with its own via.  Pins 109 and 144 are NC.
```

### 7.2 Sheet 2 — Configuration mode, JTAG, reset and status

```
  U1.57 PROGRAMN --+--[R2 4.7k]-- 3V3
                   +-- SW2 --- GND                       (press = reconfigure)
                   +-- J1.4  (header PROGRAMn)
                   +-- Q1 drain ; Q1 source -- GND ; Q1 gate --[R25 4.7k]-- JP1 -- U4 DTR#
                                                                 Q1 gate --[R26 10k]-- GND
                   (auto-reconfigure from the host, disable by removing JP1)

  U1.55 INITN  -----+--[R3 4.7k]-- 3V3
                    +-- J1.10 (header INITn)
                    +--[R31 1k]-- Q4 base             Q4 = BC807 (PNP, optional indicator)
                        emitter -- 3V3 ; collector -- D6 --[R34 1k]-- GND
                        (D6 red lights when INITN is low = SRAM clear / config error)

  U1.56 DONE   -----+--[R4 4.7k]-- 3V3
                    +-- J1.9  (header DONE)
                    +--[R32 10k]-- Q2 base            Q2 = BC817 (NPN)
                        Q2 emitter -- GND ; Q2 collector -- D1 --[R33 1k]-- 3V3
                        (D1 green lights when DONE is high = configured / in user mode)

  Mode straps (Master SPI, CFG[2:0] = 010, latched on the rising edge of INITN):
        U1.62 CFG_0 --[R6 1k]-- GND
        U1.59 CFG_1 --[R5 4.7k]-- 3V3
        U1.58 CFG_2 --[R7 1k]-- GND

  JTAG TAP (dedicated pins, VCCIO8 domain):
        U1.63 TCK -- J1.8  -- J2.5
        U1.64 TMS -- J1.6  -- J2.2        J1: 1=3V3(PWR) 2=TDO 3=TDI 4=PROGRAMn 5=NC
        U1.61 TDI -- J1.3  -- J2.3            6=TMS 7=GND 8=TCK 9=DONE 10=INITn
        U1.60 TDO -- J1.2  -- J2.4        J2: 1=3V3(VREF) 2=TMS 3=TDI 4=TDO 5=TCK
                                              6=GND 7..9=NC 10=GND
  JTAG works with a blank or corrupt configuration flash -> this is the recovery path.
```

### 7.3 Sheet 3 — The two SPI flashes

```
  U2 = W25Q64JVSSIQ — FPGA bitstream flash (Master SPI, driven by the configuration logic)
  ---------------------------------------------------------------------------------------
   U1.54  CCLK  --[R9 100R]-------> U2.6 CLK          ; U1.54 --[R8 1k]-- 3V3
   U1.47  PB11B (MOSI pad) --[R10 100R]--> U2.5 DI    ; also J5.3 as gpio_a[2]  *
   U1.46  PB11A (MISO pad) --[R11 100R]--> U2.2 DO    ; also J5.2 as gpio_a[1]  *
   U1.49  CSSPIN pad       --[R12 100R]--> U2.1 /CS   ; also J5.5 as gpio_a[4]  *
                                            U2.1 --[R13 10k]-- 3V3  (deselect when idle)
                                            U2.3 /WP --[R14 10k]-- 3V3
                                            U2.7 /HOLD --[R15 10k]-- 3V3   (IO2/IO3 not used: no quad on TQFP144)
                                            U2.8 VCC = 3V3 + C28 100n ; U2.4 GND
   * the 100R series resistors bound any contention between the pads and the flash; firmware keeps
     gpio_a[1]/[2]/[4]/[6] as inputs (see §6.4)

  U3 = W25Q64JVSSIQ — SV-16 application flash (firmware slots, driven by the soft-core)
  ---------------------------------------------------------------------------------------
   U1.110 flash_sck  ----------------------> U3.6 CLK
   U1.111 flash_cs_n ----------------------> U3.1 /CS   ; U3.1 --[R16 10k]-- 3V3
   U1.112 flash_mosi ----------------------> U3.5 DI
   U1.113 flash_miso <---------------------- U3.2 DO
                                            U3.3 /WP --[R17 10k]-- 3V3
                                            U3.7 /HOLD --[R18 10k]-- 3V3
                                            U3.8 VCC = 3V3 + C29 100n ; U3.4 GND

  Why two devices: the configuration port is not memory-mapped, so the soft-core cannot reach U2.
  U3 is an ordinary SPI device on user I/O, which is what sv16_flash_ctrl (MMIO 0xF0A0) drives and what
  the bootloader reads firmware images from. See §6.4 for the full argument.
```

### 7.4 Sheet 4 — Clock, reset and console

```
  Y1 25.000 MHz ACTIVE XO (3.3 V)      U4 CH340G (SOP-16, 3.3 V, pin numbers below)
  -------------------------------      --------------------------------------------------------
   Y1.3 OUT ----> U1.133 clk_25m        U4.16 VCC -- 3V3 + C27 100n
   Y1.1 EN  -- 3V3                      U4.4  V3  -- 3V3 + 100n **
   Y1.4 VCC -- 3V3 + C26 100n           U4.1  GND -- GND
   Y1.2 GND -- GND                      U4.5  UD+ <--> J8 D+  (via USBLC6 D+ channel)
                                        U4.6  UD- <--> J8 D-  (via USBLC6 D- channel)
   ** a passive crystal (HC49/US, 2 pins) CANNOT drive this net. The ECP5 has no on-chip crystal
      oscillator, so Y1 must be a 4-pin ACTIVE oscillator with its own VCC. See OQ-B14.

  CH340G clock (only for the G version; a CH340C has this inside and needs none of it)
  -----------------------------------------------------------------------------------
   U4.7 XI --+-- Y2 12 MHz --+-- U4.8 XO
   (or, instead of Y2/C36/C37: an active 12 MHz oscillator into XI, XO left open)
             |                |
          C36 22pF         C37 22pF
             |                |
            GND              GND
   (keep XI/XO short and symmetrical; do not route them near the USB pair or the switchers)

   U4.2  TXD --[R21 0R]-- U1.73 uart_rx   (idles high)
   U4.3  RXD --[R23 0R]-- U1.74 uart_tx
   U4.13 DTR# -- JP1 -- Q1 gate (optional auto-reconfigure, §7.2)
   U4.15 R232 -- NC (internal pull-down; leave open)
   U4.9 CTS# / 10 DSR# / 11 RI# / 12 DCD# / 14 RTS# -- NC

  SW1 reset
  ----------------
   U1.134 ext_rst_n --+-- SW1 -- GND
                      +--[R1 10k]-- 3V3
                      +-- C1 100n -- GND
   U1.134 has PULLMODE=UP in the LPF; R1/C1 are for noise immunity and contact bounce,
   not for correct reset behaviour.

  J10 alternative console (populate R22/R24 instead of R21/R23)
  ------------------------------------------------------------
   J10.1 3V3 | J10.2 UART_TX(F) --[R24 0R]-- U1.74 | J10.3 UART_RX(F) --[R22 0R]-- U1.73 | J10.4 GND
   ** 3.3 V-only board: a 5 V USB-UART adapter must not be used unless a level shifter is fitted
      (BOM "optional" row) or the adapter's I/O is 3.3 V tolerant.
```

### 7.5 Sheet 5 — LEDs, expansion and motor

```
  Status LEDs (mirror of GPIOA[3:0], active low -- see §6.1)
  ---------------------------------------------------------
   U1.39 led[0] --[R27 470R]-- D2 -- 3V3       (D2 on when GPIOA[0] = 0)
   U1.40 led[1] --[R28 470R]-- D3 -- 3V3
   U1.41 led[2] --[R29 470R]-- D4 -- 3V3
   U1.44 led[3] --[R30 470R]-- D5 -- 3V3

  Expansion headers (every signal is 3.3 V LVCMOS, 8 mA drive as constrained in the LPF)
  --------------------------------------------------------------------------------------
   J5 EXP-C   : 1 A0   2 A1*  3 A2*  4 A3   5 A4*  6 A5   7 A6*  8 A7   9 GND  10 3V3
   J3 EXP-A   : 1 3V3  2 GND  3 A8   4 A9   5 A10  6 A11  7 A12  8 A13  9 A14  10 A15
                11 spi0_cs_n  12 spi0_sck  13 spi0_mosi  14 spi0_miso
                15 GND 16 GND 17 5V 18 5V 19 GND 20 GND
   J4 EXP-B   : 1 3V3  2 GND  3 B0   4 B1   5 B2   6 B3   7 B4   8 B5   9 B6   10 B7
                11 B8  12 B9   13 B10 14 B11 15 B12 16 B13 17 B14 18 B15 19 GND 20 5V
   J7 spare   : 2x25, 46 spare I/O (bank 1 : 118-121, bank 2 : 90-95, bank 3 : 67,68,69,71,72,
                76-82,84, bank 6 : 18,19,22-28,30,31,33-35,37, bank 7 : 5-7,10-14) + 4 GND.
                Footprint only, not fitted.
   * A1/A2/A4/A6 are the shared configuration-flash nets of §6.4; A3/A5/A7 are free.
   The 5 V pins are USB VBUS only (the 3V3 rail comes from VM_IN, §4.1).

  Motor connector (keyed 1x6)
  ---------------------------
   J6.1 VM  <-- VM_IN through the keyed header (fused on the driver board, not on this board)
   J6.2 GND -- GND
   J6.3 PWM <--------- U1.88  pwm_out      (16 mA drive, PWM block at MMIO 0xF030)
   J6.4 DIR1 <--------- U1.89  motor_dir1  (mirror of GPIOA[4])
   J6.5 DIR2 <--------- U1.102 motor_dir2  (mirror of GPIOA[5])
   J6.6 FAULTn -------> U1.103 motor_fault_n  (input, PULLMODE=UP + R19 10k pull-up to 3V3)
```

---

## 8. Connector pinouts and how to use them

| Connector | Type | Pinout | Use |
| :--- | :--- | :--- | :--- |
| J1 | 1×10, 2.54 mm | 1 3V3 · 2 TDO · 3 TDI · 4 PROGRAMn · 5 NC · 6 TMS · 7 GND · 8 TCK · 9 DONE · 10 INITn | Versa-style programming header, works with `openFPGALoader` and any FT232H/FT2232H adapter |
| J2 | 2×5, 1.27 mm keyed | 1 3V3 (VREF) · 2 TMS · 3 TDI · 4 TDO · 5 TCK · 6 GND · 7–9 NC · 10 GND | Digilent/HS2-style probes; wired in parallel with J1 — use one at a time |
| J3 | 2×10, 2.54 mm | see §7.5 | SPI0 + GPIOA[15:8]; SPI0 is the SoC's second SPI (`0xF050`), ideal for an SD card or radio module |
| J4 | 2×10, 2.54 mm | see §7.5 | all 16 GPIOB pins (`0xF070`) |
| J5 | 1×10, 2.54 mm | see §7.5 | GPIOA[7:0]; pins 2/3/5/7 share the configuration flash (§6.4) |
| J6 | 1×6 keyed | see §7.5 | motor driver interface |
| J7 | 2×25, 2.54 mm | 46 spare I/O + 4 GND | expansion only; not fitted |
| J8 | USB-C receptacle | VBUS, D+, D−, GND, CC1/CC2 = 5.1 kΩ Rd | power + console on one cable |
| J9 | 5.5/2.1 mm barrel | centre positive, **7–12 V** (5 V USB works only at light load — OQ-B12) | bench supply, powers the motor connector too |
| J10 | 1×4, 2.54 mm | 3V3 · UART_TX(F) · UART_RX(F) · GND | console without fitting the CH340C (fit R22/R24, remove R21/R23) |

Wiring notes that prevent the two most common support cases:

* **A 5 V USB-UART adapter on J10 will damage the FPGA pins** (they are LVCMOS33 with no 5 V tolerance
  documented for this configuration). Use 3.3 V levels, or fit the optional level shifter.
* **Two JTAG adapters on J1 and J2 at the same time** will fight. Populate one connector if you are
  unsure; they are on the same four nets.
* The **console is the only update path in the field**: bitstreams go through JTAG (or through U2), while
  firmware images go through the UART into U3. That asymmetry is inherent to soft-core + configuration
  flash and is worth putting on the silkscreen.

---

## 9. What lives in which memory, and how each part gets programmed

| Storage | Device | Content | Written by | Survives power cycle |
| :--- | :--- | :--- | :--- | :-: |
| Configuration SRAM (inside U1) | — | the FPGA bitstream | configuration logic from U2, or JTAG directly | no |
| **U2** bitstream flash | W25Q64JV | `build/pll/sv16_top.bit` (293 KB) at offset 0 | `openFPGALoader -f` through the FPGA's MSPI port, or a bench SPI programmer (SOIC-8 clip) | yes |
| **U3** application flash | W25Q64JV (W25Q40-class is enough, see below) | firmware images: slot A at `0x000000`, slot B at `0x008000`, 32 KB each, 32-byte header, slot record at bytes `0x18`/`0x19` | the SV-16 ROM monitor over the UART (`make upload`, `make upload-slot`), or an external SPI programmer | yes |
| Boot ROM | hardened in the FPGA (initialised BRAM, `.ORG 0xE000`) | the ROM monitor (790 lines of SV-16 assembly) | bitstream build (`make rom`) | n/a (part of U2) |
| SRAM | FPGA block RAM | 32 KB at `0x0000-0x3FFF` — applications at run time, loader while booting | boot loader / firmware | no |

`docs/BOOT_AND_PROGRAMMING.md` documents the image format, the A/B slot policy (PENDING → TRIED → GOOD
or BAD), and the monitor's command set; this board only supplies the two physical flash devices it
assumes. The typical application flash in that document is a **512 KB W25Q40-class part**, so U3 can be
downsized to `W25Q40CLSNIQ` (or `W25Q16JV`) without changing a line of firmware — the design only needs
the standard SPI-NOR command set (`0x03/0x0B` read, `0x02/0x06/0x05/0x20/0xD8` program/erase/status)
that the whole W25Q family shares. U2 must be at least as large as the bitstream: 1 MB is comfortable,
8 MB is what the BOM lists because the part is the same and cheaper in volume.

### 9.1 Programming flows on this board

```sh
# 1. Volatile configuration (fastest loop while developing the FPGA side)
make bitstream                 # -> build/sv16_top.bit  (J1/J2 + any FT232H/FT2232H adapter)
make prog CABLE=ft232          # openFPGALoader --fpga-part LFE5U-12F build/sv16_top.bit

# 2. Persistent bitstream (survives power cycles, loads from U2 in ~1 s at the default MCLK)
make prog-flash CABLE=ft232    # openFPGALoader -f: writes U2 through the FPGA's MSPI port

# 3. Firmware: single-image upload through the monitor (no rollback)
make upload PORT=/dev/ttyUSB0  IMG=build/fw/app_img.hex

# 4. Firmware: A/B field update (recommended -- a bad image cannot brick the board)
make slot-image SLOT=1 && make upload-slot SLOT=1 PORT=/dev/ttyUSB0
make mon-boot                  # boot the PENDING slot; loader marks it TRIED
make commit                    # once the new image behaves: record GOOD, retire the other slot
```

The JTAG headers stay useful even with a blank U2: `openFPGALoader --detect` should identify the device
(the ECP5 12F IDCODE is device specific — record what your part reports; the 25F model in the BSDL
FPGA-MD-02097 reads `0x41111043`), then flow 1 or 2 recovers the board.

## 10. Bring-up and acceptance test plan

| # | Step | Pass criterion | Tool |
| :-: | :--- | :--- | :--- |
| 1 | Resistance check before power | > 100 Ω from each rail (TP1/TP2/TP3) to GND; no short between rails | DMM |
| 2 | Power up on the barrel jack (7–12 V) with **U1 not fitted yet** | TP1 = 3.135–3.465 V, TP2 = 2.375–2.625 V, TP3 = 1.045–1.155 V — the 1V1 rail is now set by the R38/R39 divider, so **verify and trim it here**, before the FPGA is on the board and can be damaged by an out-of-range core rail | DMM |
| 2b | With all three rails in spec, fit U1 (and only then, the flashes) | — | — |
| 3 | Ramp order (scope, two channels) | 3V3 rises first and passes 2.31 V before either of the other rails moves at all; 1V1 starts ≈13 ms later, 2V5 ≈50 ms later; no rail slower than 0.01 V/ms; VCCAUX slew ≤ 30 mV/µs | scope, 20 ms/div |
| 4 | JTAG detection | `openFPGALoader --detect` returns the ECP5 IDCODE, no cable/chain errors | J1/J2 + adapter |
| 5 | Volatile configuration | DONE (TP5) goes high, D1 lights, INITN stays high | `make prog` |
| 6 | Console | 115200 8N1 shows the monitor banner; `?` lists commands | `make mon-term PORT=/dev/ttyUSB0` |
| 7 | Reset and reset cause | SW1 restarts the monitor; `SYS_RSTCAUSE` (0xF003) reports the expected source | monitor |
| 8 | LEDs | an application that toggles GPIOA[3:0] blinks D2–D5 in the same pattern (active low) | any `firmware/apps/` build |
| 9 | Application flash | monitor reads the JEDEC ID of U3; `make upload` writes and `V` verifies | monitor |
| 10 | A/B update | `make upload-slot SLOT=1` + `make mon-boot` + `make commit`, then power-cycle and confirm the new image runs from slot B | host scripts |
| 11 | Rollback | upload a deliberately broken image to the free slot, boot it, reset — the loader must fall back to the other slot and set `BOOT_ERR[7]` | host scripts |
| 12 | Motor | scope on J6.3 shows the PWM waveform with the duty written to `0xF030`; J6.4/J6.5 follow GPIOA[4]/[5]; pulling J6.6 low sets the fault bit | scope + `firmware/apps/motor_test.s` |
| 13 | Current measurement | record 1V1/2V5/3V3 current at 37.5 MHz with the monitor idle and with an application running (this closes OQ-B1) | bench supply |
| 14 | Long-run soak | 24 h with the monitor running and the motor app cycling: no watchdog resets beyond those expected, no configuration re-entry | host log |

## 11. Layout and EMC guidance

| Topic | Guidance |
| :--- | :--- |
| Stack-up | 4 layers, 1.6 mm: signal / solid GND / solid PWR (3V3, 1V1, 2V5 pours) / signal. A 2-layer board is possible but the 0.5 mm-pitch TQFP fan-out and the three rails make it unpleasant; not recommended |
| Fan-out | 0.25 mm traces, 0.2 mm vias; TQFP-144 escape on all four sides. Ground pins 8/15/21/32/42/65/75/85/87/101/123/129/131/138 each get their own via to the GND plane |
| Decoupling | the 100 nF of C2–C20 within 3 mm of its pin, on the same side as the FPGA, with the via first at the pad; bulk (C21–C25) near the regulator outputs |
| Regulators | keep the two switchers' inductors (L1 33 µH, L2 10 µH), their catch diodes and the input loops tight — these are 150 kHz and ~500 kHz hard-switched nodes; keep L2 and D11 away from the configuration flash and the 25 MHz oscillator; put U5/U6/U7 and their electrolytics on the opposite edge of the board from J6 |
| Motor return | J6 GND must have its own path to the input bulk capacitor; do not route motor current through the FPGA ground area. FB1 and the 3V3 bulk capacitor are the barrier |
| Oscillator | Y1 within 10 mm of pin 133, no via in the trace, ground pour under the part, keep the switching nodes > 5 mm away |
| Config flash | U2 within 15 mm of pins 46/47/49/54; the 100 Ω series resistors at the FPGA end (they are there to bound contention, §6.4) |
| USB | D+/D− as a 90 Ω differential pair, ESD device at the connector, CC1/CC2 5.1 kΩ within 10 mm of J8 |
| JTAG | short TCK stub, no stubs beyond the two headers (TCK is the fastest signal at ≤ 25 MHz but the slowest is the cable); keep the TDO trace ≤ 50 mm |
| Test points | TP1–TP6 on the top side, labelled with the net names used in this document |
| Thermal | TQFP-144 has no exposed pad; use a copper pour on all four sides under the part, thermal vias under the body. Expected dissipation is well under 1 W (77 mA × 1.1 V core static plus switching), so no heatsink and no airflow requirement |
| Options/silkscreen | mark DNP parts (D6, J7, level shifter) and J5 pins 2/3/5/7 ("CFG FLASH — inputs only") |

## 12. What this board turns the design into

| MCU property | Where it comes from |
| :--- | :--- |
| Persistent program storage | U3 + `sv16_flash_ctrl` (MMIO `0xF0A0`) + the bootloader reading A/B slots |
| Field reprogramming that cannot brick the board | A/B slots with PENDING/TRIED/GOOD records (ADR-019) + the monitor's upload/verify + JTAG as the last resort |
| Console / host interface | CH340C + UART0 at 115200 8N1, the same protocol `scripts/sv16_mon.py` speaks |
| Deterministic start-up | POR → configuration → startup FSM → 32768-cycle boot delay → boot attempt → monitor fallback (holding the RX line low for 4096 cycles forces the monitor, which is the escape hatch after a bad image) |
| Reset control with cause reporting | SW1 on `ext_rst_n` + `SYS_RSTCAUSE` at `0xF003` |
| Autonomous safety | watchdog at `0xF080` (`docs/PERIPHERALS.md`) |
| Digital I/O with a real expansion story | 46 spare I/O on J7, 32 GPIO on J3/J4/J5 (2 ports × 16 bits at `0xF010`/`0xF070`), SPI0 at `0xF050` |
| Motor/actuator control | PWM at `0xF030` (DD-16 mA output on pin 88) with direction pins and a fault input |
| Debug | ROM monitor over UART today; the roadmap item S3 (UART GDB stub → `JTAGG` bridge, `REPORT.md` §8.2) uses this same JTAG header |

## 13. Verification status and open items

### 13.1 Verified (with the artefact that proves it)

| Item | Evidence |
| :--- | :--- |
| Pin numbers, pads, banks of all 52 constrained signals | `board/TQFP144_PINOUT.md`, generated from the prjtrellis device database for LFE5U-12F and the Lattice BSDL PIN_MAP; `scripts/sv16_board_pins.py --check` fails on drift |
| Device pin budget (98 I/O, 11 dedicated, 6 VCC, 4 VCCAUX, 9 VCCIO, 14 GND, 2 NC = 144) | `board/ecp5_tqfp144.json` `summary`, validated by the script against both sources |
| Rail limits, ramp rates, POR trips, LVCMOS33 range | FPGA-DS-02012-3.4 Tables 3.1/3.2/3.3/3.4/3.5/3.11 (the PDF is in this repository) |
| Static supply currents | FPGA-DS-02012-3.4 Table 3.8 |
| Configuration mode and pull-up values | TN1260 / TN-02039 (CFG[2:0] = 010) + TN-02038-2.0 Table 6.2 (4.7 kΩ PROGRAMN/INITN, 1 kΩ MCLK, 4.7–10 kΩ CSSPIN) |
| JTAG header pinout and TAP | ECP5 Versa EB98/EB103 Appendix A; BSDL `TAP_SCAN_*` attributes and `BOUNDARY_LENGTH` 409 |
| Fit of the design in the device | `build/pll/sv16_nextpnr.log`: 9,191 LUT4, 4,772 FF, 18 DP16KD, 1 EHXPLLL, 45.45 MHz |

### 13.2 Open items (must be closed before or during layout)

| ID | Item | Why it is open | Closing action |
| :--- | :--- | :--- | :--- |
| OQ-B1 | Dynamic current on 1V1/2V5/3V3 | the open-source flow has no power analyser; only datasheet *static* numbers exist | measure on the first board (§10 step 13); the regulators are oversized on purpose |
| OQ-B2 | Regulator passives (L1 33 µH, L2 10 µH, the electrolytic values, the feedback divider) | taken from the vendors' typical application circuits rather than re-derived here; see also OQ-B10 for the values the two new bucks add | run the vendors' reference designs at layout time, and measure the rails at bring-up step 2 |
| OQ-B3 | Configuration time from U2 at the default MCLK | TN-02039 gives the mechanism but the bitstream's `MCCLK_FREQ` setting is not inspected by the open flow | measure `INITN`→`DONE` with a scope on the first board |
| OQ-B4 | CH340C 3.3 V connection details (V3 pin, decoupling, DTR polarity) | pin numbers and the 3.3 V configuration must come from the WCH datasheet, which is not in this repository | download and check the WCH datasheet before schematic capture |
| OQ-B5 | USB-C sink compliance (Rd values, no-PD behaviour) | standard practice, no USB-IF testing | bench-test with several hosts/cables |
| OQ-B6 | J2 (2×5 0.05") pin map versus the actual probe in use | conventions differ slightly between Digilent/FT2232H clones | check against the chosen adapter's cable |
| OQ-B7 | EMC / ESD pre-compliance (motor transients, USB) | no test house, no hardware | add the layout measures of §11 and re-assess when hardware exists |
| OQ-B8 | Mechanical outline, mounting, connector placement, enclosure | not fixed yet | decide with the mechanical drawing at PCB start |
| OQ-B9 | J5 pin sharing with the configuration flash (§6.4) | acceptable as documented, but it is a usability wart | either keep the firmware rule or apply variant V1 (§14) |
| OQ-B10 | Regulator passives taken from vendor typical applications: the MP1584 `COMP` network and `FREQ` resistor (R40), the AMS1117 output capacitor type (ceramic vs tantalum), and the exact `EN` threshold that sets the 13 ms delay (the delay scales as −RC·ln(1 − Vth/Vin)) | the values here are correct in form but not re-derived from each datasheet | check the MP1584/AMS1117 application circuits before layout; measure the delayed rails at bring-up step 3 |
| OQ-B11 | Assembly of a 0.5 mm-pitch TQFP-144 plus 0603 passives without a reflow oven | this is the practical risk of the whole build, and it decides whether the first board works | order a stencil with the PCB, use solder paste + hot-air (₹2,500–4,000 stations are on Robu/Zbotic), drag-solder the TQFP with flux, or pay an Indian assembly service; practice on a ₹100 QFP breakout first |
| OQ-B12 | USB-C (5 V) input voltage margin: 5 V − SS34 drop ≈ 4.6 V against a 4.5 V regulator minimum | the barrel jack is fine; USB is marginal under load | use 7–12 V on J9 for anything real, or replace D9 with a P-MOSFET ideal diode (drop ≈ 50 mV) |
| OQ-B13 | Actual FPGA stock at digikey.in / mouser.in / element14 India. Checked 27 Sep 2026: digikey.com listed **372 pieces live** and a **40-week standard lead time** — i.e. single pieces ship now, a back-order takes most of a year | the board is pointless without U1, and stock moves fast at this volume | check availability and price **before** ordering PCBs, and buy a spare; a speed-7 or industrial-grade part is an acceptable substitute (§3.4) |
| OQ-B14 | Is Y1 an **active** oscillator? A 25 MHz HC49/US part is a 2-pin passive crystal and cannot drive `clk_25m` (the ECP5 has no on-chip crystal driver). Check the pin count before layout: 4 pins = active (works), 2 pins = passive (does not) | the board would configure but have no clock — no console, no boot | buy a 3.3 V active 25 MHz XO (3.2×2.5 or 5×7 mm), or build a Pierce oscillator around the crystal with an unbuffered inverter (e.g. 74LVC1G04 + 1 MΩ + 2 × 22 pF) — see PCB_COMPONENTS.md §10 |

## 14. Variants and the next revision

| Variant | Change | Benefit | Cost |
| :--- | :--- | :--- | :--- |
| **V1 — decouple J5 from the config flash** | move `gpio_a[1]`, `[2]`, `[4]`, `[6]` in `constraints/ecp5_144tqfp.lpf` from bank 8 (pins 46/47/49/51) to four of the free bank-2 pins (90–95), then regenerate `board/TQFP144_PINOUT.md` | J5 becomes 10 fully usable GPIO; the config flash no longer needs series resistors or a firmware rule; closes OQ-B9 | one LPF edit, a bitstream rebuild, doc regeneration. Constraint changes touch the pin map docs and §6.4 only |
| **V2 — single-cable USB** | replace the CH340C with an FT2232H (channel A = JTAG, channel B = UART) | one cable does configuration *and* console; no JTAG adapter needed | +USD 4–6, QFN-56 handling, two interfaces to document |
| **V3 — on-board motor driver** | populate U9 = DRV8871/TB6612 on the J6 nets, with current sense into a spare ADC-less comparator pin | turn-key actuator board | needs a driver design + thermal review |
| **V4 — mixed I/O rails** | split one bank to 1.8 V (e.g. for an SD card in bank 3) | expands the peripheral set | LPF `IOSTANDARD` change, an extra regulator, and the level-shift question returns |
| **V5 — USB-C PD / PoE input** | PD sink controller requesting 9–12 V, or 802.3af front end | no barrel jack | BOM + certification work |

The order I would do them: **V1 first** (it is cheap and removes the only awkward constraint in this
document), then V2 when the JTAG cable becomes the bottleneck, then V3 when a real motor is on the bench.

## 15. Appendix A — electrical quick reference (LFE5U-12F, from FPGA-DS-02012-3.4)

| Parameter | Value | Table |
| :--- | :--- | :--- |
| VCC recommended / absolute max | 1.045–1.155 V / −0.5…1.32 V | 3.1, 3.2 |
| VCCAUX recommended / absolute max | 2.375–2.625 V / −0.5…2.75 V | 3.1, 3.2 |
| VCCIO recommended / absolute max | 1.14–3.465 V / −0.5…3.63 V | 3.1, 3.2 |
| LVCMOS33 VCCIO window | 3.135–3.465 V | 3.11 |
| Supply ramp | 0.01–10 V/ms, monotonic; VCCAUX ≤ 30 mV/µs | 3.3 |
| POR trip (VCC / VCCAUX / VCCIO8) | 0.90–1.00 V / 2.00–2.20 V / 0.95–1.06 V; no VCCIO8 ramp-down detection | 3.4 |
| POR release condition | VCC **and** VCCAUX **and** VCCIO8 above trip | 3.5 |
| Static current, LFE5U-12F (TJ 85 °C, outputs tri-stated) | ICC 77 mA · ICCAUX 16 mA · ICCIO 0.5 mA/bank | 3.8 |
| Master SPI timing | fMCLK ±20 %, duty 40–60 %; PROGRAMN low ≥ 110 ns (≤ 50 ns is rejected); tINITL ≤ 55 µs; tVMC ≤ 5 µs; tCZ ≤ 300 ns | p85–87 |
| JTAG TCK | ≤ 25 MHz (BSDL `TAP_SCAN_CLOCK`) | FPGA-MD-02097 |
| Junction temperature | 0–85 °C (commercial `C` grade) | 3.2 |

## 16. Appendix B — files this document depends on

| File | Role |
| :--- | :--- |
| `board/ecp5_tqfp144.json` | device pin database (built from the prjtrellis database + Lattice BSDL) |
| `board/TQFP144_PINOUT.md` | generated 144-pin net table — the netlist appendix of this document |
| `scripts/sv16_board_pins.py` | regenerates the table, checks it for drift, prints the bank summary |
| `constraints/ecp5_144tqfp.lpf` | the single source of truth for signal → pin (and for drive strength / pull mode) |
| `docs/BOARD_AND_BRINGUP.md` | bench notes, harness wiring and bring-up history for the *simulation* and *previous* hardware effort — read alongside §10 |
| `docs/SYNTHESIS_AND_DEPLOYMENT.md` | build, timing, utilisation and existing pin-map narrative |
| `docs/BOOT_AND_PROGRAMMING.md` | image format, slot policy, monitor protocol, host tools |
| `docs/MEMORY_MAP.md`, `docs/PERIPHERALS.md` | MMIO map and register reference for every signal that reaches a connector |
| `docs/MCU_READINESS.md` | what is still missing for a production-grade MCU (the board does not change that list) |
| `REPORT.md` | status of the whole project, including the software-only roadmap §8.2 |
| `ECP5 and ECP5-5G.pdf` | Lattice FPGA-DS-02012-3.4 — every rail, timing and pin-count number above |

_Revision 1.1 — **India-sourcing edition** (September 2026). The bill of materials was re-sourced so
that every part is orderable from an Indian vendor: the two regulators became LM2596S-3.3 and MP1584EN,
the LDO became AMS1117-2.5, the oscillator became the digikey.in YIC part, and the passives moved to
0603. Because the new bucks need ≥4.5 V input, the power-up order is now created by two RC-delayed
enables instead of by deriving VCC/VCCAUX from 3V3 — §4.3 has the timeline, §3.6 the full change list,
and §3.5 a module-first build for a first board. Prices checked against Indian vendor listings in
September 2026._

_Revision 1.0 — first issue, written against `constraints/ecp5_144tqfp.lpf` and the bitstream in
`build/pll/sv16_top.bit`. No board exists yet; this document is the specification to build one._
