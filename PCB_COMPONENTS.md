# SV-16 microcontroller board — PCB component specifications for KiCad

**What this is:** the component list, the specifications and the pin-level connections needed to draw the
SV-16 microcontroller board in KiCad and order it. Every part here is the one finalised in `BOARD.md`
revision 1.1 (the India-sourced edition) — same parts, same values, plus the mechanical and electrical
detail a schematic and layout need.

**Sources of truth, in order:**

| Document | What it fixes |
| :--- | :--- |
| `constraints/ecp5_144tqfp.lpf` | the FPGA pin map — the §5 table in this document is generated from it, not copied |
| `BOARD.md` §3 | the finalised BOM (India-sourced) and prices |
| `BOARD.md` §4, §7 | the power tree and the five connection-diagram sheets |
| `BOARD.md` §6 | which FPGA pin is on which board net |
| `BOARD.md` §11 | layout and EMC rules, restated as KiCad rules in §7 here |
| `docs/SYNTHESIS_AND_DEPLOYMENT.md` | how the bitstream that matches this pin map is built |

**Two reading rules before you start drawing:**

1. **Rows marked ⚠ must be confirmed against the part's datasheet before you commit the schematic.**
   They are values where the board document gives the intent but the datasheet gives the number —
   regulator compensation, the feedback divider, footprint sizes that depend on what you buy. §10 lists
   them in one place.
2. **Footprint names are KiCad 7/8 standard-library names.** The library prefix (`Package_QFP:` and so on)
   is the library nickname in KiCad's Footprint Library table. Where a dimension depends on the exact
   part you buy (electrolytics, inductors, USB-C, oscillator, module headers), the row says so.

---

## 1. Setting up the KiCad project

| Step | Setting |
| :--- | :--- |
| KiCad version | 7.0 or later (8.x recommended: the net-class and DRC-rule syntax in §7 assumes 7+) |
| Project name | `sv16_board` — one project, one schematic, **five sheets** matching `BOARD.md` §7.1–§7.5 |
| Sheet names | 1 power · 2 configuration/JTAG/reset · 3 SPI flashes · 4 clock/reset/console · 5 LEDs/expansion/motor |
| Board size | 100 × 100 mm (five boards for ~₹3,000 at JLCPCB); mounting holes 4 × M3 at the corners, 3 mm from the edges |
| Stack-up | 4 layers, 1.6 mm: **signal / solid GND / solid PWR / signal**. The inner layers carry the 3V3, 1V1 and 2V5 pours and nothing else |
| Copper | 1 oz outer, 1 oz inner |
| Min track/clearance | 0.2 mm / 0.2 mm (the fab's cheap rules); the FPGA fan-out uses 0.25 mm signal traces and 0.2/0.4 mm vias |
| Sheet size | A3 per sheet (this design has 10 connectors and a 144-pin part; A4 gets cramped) |
| Net naming | **use the LPF signal names** (`clk_25m`, `uart_rx`, `flash_cs_n`, `gpio_a[0]` …) so a net in KiCad can be traced to a line in `constraints/ecp5_144tqfp.lpf` and to a row in §5. Power nets: `VM_IN`, `3V3`, `2V5`, `1V1`, `GND` |
| Symbol libraries | `Device` (R, C, L, D, Q, ferrite bead), `Connector_Generic`, `Connector`, `Power_Protection` (USBLC6), `Regulator_Linear` (AMS1117), `Regulator_Switching` (LM2596S-3.3), `Memory_Flash` (W25Q64JVSSIQ), `Interface_USB`/`Interface_UART` — **for the CH340C, check the symbol's pin numbers against the WCH datasheet** (see §4.7); for the ECP5, `Lattice` library or draw a 144-pin symbol from `board/TQFP144_PINOUT.md` |
| Net classes | §7 defines five: `Default`, `Power`, `Switching`, `USB`, `JTAG` |

---

## 2. KiCad footprint map

| Ref | Part | KiCad footprint (library:name) | Notes |
| :--- | :--- | :--- | :--- |
| U1 | LFE5U-12F-6TG144C | `Package_QFP:LQFP-144_20x20mm_P0.5mm` | 0.5 mm pitch, no exposed pad. Verify the courtyard against the datasheet's 22 × 22 mm body |
| U2, U3 | W25Q64JVSSIQ | `Package_SO:SOIC-8_5.23x5.23mm_P1.27mm` | 208 mil body |
| U4 | CH340C | `Package_SO:SOIC-16_3.9x9.9mm_P1.27mm` | 150 mil body. Confirm the SOP-16 body width from the WCH datasheet before routing |
| U5 | LM2596S-3.3 | `Package_TO_SOT_SMD:TO-263-5_TabPin3` | tab = pin 3 (GND); the tab is the heatsink, pour copper under it |
| U6 | MP1584EN-LF-Z | `Package_SO:SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.3mm` ⚠ | exposed pad = GND. **Check the pad size against the MP1584 datasheet** — some SOIC-8E parts use a 2.4 × 3.3 mm pad, others 3.3 × 2.4 mm |
| U7 | AMS1117-2.5 | `Package_TO_SOT_SMD:SOT-223-3_TabPin2` | tab = pin 2 (VOUT) |
| U8 | USBLC6-2SC6 | `Package_TO_SOT_SMD:SOT-23-6` | |
| Y1 | YIC OSC25M-3.3I/S3-25T (or any 3.2 × 2.5 mm 4-pad XO) | `Oscillator:Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm` | if you buy the 5 × 7 mm type instead, use `Oscillator_SMD_Abracon_ASV-4Pin_7.0x5.1mm` |
| Q1, Q2, Q3, Q4 | 2N7002 / BC817 / AO3401 / BC807 | `Package_TO_SOT_SMD:SOT-23` | pin 1 = gate/base on all four |
| D1–D7 | LED 0603 | `LED_SMD:LED_0603_1608Metric` | cathode on the marked end — orientation matters (§4.9) |
| D8–D11 | SS34 (SMA) | `Diode_SMD:D_SMA` | pin 1 = cathode (band) |
| R1–R42 | 0603 resistors | `Resistor_SMD:R_0603_1608Metric` | 1 %, 0.1 W |
| C1–C20, C26–C29, C31–C33 + the 100 nF companions | 0603 ceramic | `Capacitor_SMD:C_0603_1608Metric` | X7R, 16 V or 25 V |
| C25, C30 | 0805 ceramic | `Capacitor_SMD:C_0805_2012Metric` | 10 µF: 25 V X7R (a 10 µF/16 V 0805 is fine on 3V3, marginal on VM_IN) |
| C21 | 100 µF / 10 V electrolytic | `Capacitor_SMD:CP_Elec_6.3x5.4` ⚠ | verify against the can you buy; 6.3 × 5.4 mm is the common 100 µF/10 V size |
| C22 | 22 µF / 10 V electrolytic | `Capacitor_SMD:CP_Elec_5x5.4` ⚠ | |
| C23 | 470 µF / 35 V electrolytic | `Capacitor_SMD:CP_Elec_10x10.2` ⚠ | 10 mm can; **35 V minimum**, this sits on VM_IN |
| C24 | 220 µF / 16 V electrolytic | `Capacitor_SMD:CP_Elec_8x6.9` ⚠ | |
| L1 | 33 µH / 3 A shielded | `Inductor_SMD:L_Bourns_SRR1260` or generic 8 × 8 mm ⚠ | pick from the inductor you buy; keep the footprint's pad spacing |
| L2 | 10 µH / 3 A shielded | generic 6 × 6 mm shielded ⚠ | same |
| FB1 | ferrite bead 0603 | `Inductor_SMD:L_0603_1608Metric` | 600 Ω @ 100 MHz, ≥ 500 mA |
| SW1, SW2 | 6 × 6 mm tactile | `Button_Switch_THT:SW_PUSH_6mm` | through-hole for strength; fits the 6 × 6 mm body |
| J1, J5, J6, J10 | 1×10 / 1×6 / 1×4 headers | `Connector_PinHeader_2.54mm:PinHeader_1xNN_P2.54mm_Vertical` | J6 is keyed — add the keying notch or use a shrouded header |
| J3, J4 | 2×10 headers | `Connector_PinHeader_2.54mm:PinHeader_2x10_P2.54mm_Vertical` | |
| J7 | 2×25 header | `Connector_PinHeader_2.54mm:PinHeader_2x25_P2.54mm_Vertical` | footprint only, **not fitted** |
| J2 | 2×5 box header, 1.27 mm | `Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical` | if the connector is unavailable in India, leave J2 unpopulated and use J1 |
| J8 | USB-C receptacle 16-pin | `Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12` ⚠ | the ubiquitous 16-pin HRO part; if you buy a different receptacle, take the footprint from its datasheet. Micro-USB alternative: `Connector_USB:USB_Micro-B_Molex-105017-0001` (omit R36/R37) |
| J9 | 5.5/2.1 mm barrel jack | `Connector_BarrelJack:BarrelJack_CUI_PJ-102A_Horizontal` ⚠ | centre positive |
| JP1 | 2-pin header + shunt | `Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical` | |
| TP1–TP6 | 1 mm test pads | `TestPoint:TestPoint_Pad_D1.0mm` | nets: 3V3, 2V5, 1V1, GND, DONE, INITN |

---

## 3. Component specifications

### 3.1 Active devices

| Ref | Part | Electrical specification | Package | Qty | Price (India) |
| :--- | :--- | :--- | :--- | :-: | :--- |
| U1 | **LFE5U-12F-6TG144C** | ECP5 FPGA: 12,144 LUT4, 72 KB sysMEM, 28 × 18-bit multipliers, 2 PLLs. VCC 1.045–1.155 V, VCCAUX 2.375–2.625 V, VCCIO 3.3 V. 98 I/O on this package, 52 used. Speed grade 6, 0–85 °C Tj | TQFP-144 20 × 20 mm, 0.5 mm pitch | 1 | digikey.in ≈ ₹1,650 — **no substitute exists**; see `BOARD.md` §3.4 for the speed-7 / industrial-grade alternatives |
| U2 | W25Q64JVSSIQ | 64 Mbit (8 MB) SPI NOR, 2.7–3.6 V, 104 MHz, standard + dual/quad SPI. Holds the **bitstream** | SOIC-8, 208 mil | 1 | Sharvie ₹75 · Hubtronics ₹117 |
| U3 | W25Q64JVSSIQ | identical part; holds **firmware images** (slot A at 0x000000, slot B at 0x008000 — 32 KB each). A W25Q32/W25Q16 is already enough | SOIC-8, 208 mil | 1 | as U2 |
| U4 | CH340C | USB 2.0 full-speed ↔ UART bridge, 3.3 V, internal oscillator (no crystal), up to 2 Mbps, needs only 4 external capacitors | SOP-16, 150 mil | 1 | iFutureTech ₹45 · Hubtronics ₹47 |
| U5 | LM2596S-3.3 | buck, **3.3 V fixed**, VIN 4.5–40 V, 3 A, 150 kHz, non-synchronous, ON/OFF < 1.3 V = on | TO-263-5 (tab = GND) | 1 | Robu ₹51 (XBLW) / ₹61 (Slkor) |
| U6 | MP1584EN-LF-Z | buck, adjustable 0.8–20 V, VIN 4.5–28 V, 3 A, 100 kHz–1.5 MHz, 0.8 V reference, non-synchronous, EN threshold 1.2 V falling / 1.5 V rising, 1.5 µA internal EN pull-up | SOIC-8E (EP = GND) | 1 | Hubtronics ₹47 · Sunrom |
| U7 | AMS1117-2.5 | LDO, 2.5 V fixed, 1 A, dropout ≈ 1.3 V, requires ≥ 10 µF at the output for stability | SOT-223 (tab = VOUT) | 1 | Robu / QuartzComponents ₹12–20 |
| U8 | USBLC6-2SC6 | USB ESD protection: 2 data-line channels + VBUS clamp, 6 V standoff, < 1 nF line capacitance | SOT-23-6 | 1 | Sunrom ₹30 · DNA Tech ₹32 |
| Y1 | YIC OSC25M-3.3I/S3-25T | 25.000 MHz XO, 3.3 V CMOS, ±25 ppm (UART tolerance needs ±2 %), enable pin, 15 pF drive | 3.2 × 2.5 mm 4-pad | 1 | digikey.in ₹111 · 5 × 7 mm equivalents on Amazon.in/eBay.in |
| Q1 | 2N7002 | N-MOSFET 60 V / 115 mA, Vgs(th) 2.5 V max — pulls PROGRAMN low from the host's DTR | SOT-23 | 1 | Robu ₹5 |
| Q2 | BC817 | NPN 45 V / 500 mA — drives the DONE LED | SOT-23 | 1 | ₹2 |
| Q3 | AO3401 | P-MOSFET −30 V / −4 A, Rds(on) 60 mΩ — load switch that delays the 2.5 V LDO | SOT-23 | 1 | ₹8 |
| Q4 | BC807 | PNP 45 V / 500 mA — drives the INITN LED | SOT-23 | 1 | ₹2 |
| D1–D5 | LED green 0603 | Vf ≈ 2.0 V @ 5 mA, 20 mA max | 0603 | 5 | ₹1–2 |
| D6, D7 | LED red 0603 | Vf ≈ 1.9 V; D6 is **DNP by default** | 0603 | 2 | ₹1–2 |
| D8, D9 | SS34 | Schottky 40 V / 3 A, Vf ≈ 0.5 V — input ORing between the barrel jack and USB | SMA | 2 | ₹3 |
| D10 | SS34 | catch diode for the 3V3 LM2596 (obligatory, non-synchronous) | SMA | 1 | ₹3 |
| D11 | SS34 | catch diode for the 1V1 MP1584 | SMA | 1 | ₹3 |
| — | SN74LVC1T45 (optional) | level shifter for a 5 V adapter on J10 | SOT-23-6 | 0 | only if needed |

### 3.2 Resistors (all 0603, 1 %, 0.1 W unless noted)

| Ref | Value | Connects | Purpose |
| :--- | :--- | :--- | :--- |
| R1 | 10 kΩ | `ext_rst_n` → 3V3 | reset pull-up (the pin also has PULLMODE=UP in the LPF) |
| R2 | 4.7 kΩ | PROGRAMN → 3V3 | configuration pull-up (TN-02038 Table 6.2) |
| R3, R4 | 4.7 kΩ | INITN → 3V3, DONE → 3V3 | status pull-ups |
| R5 | 4.7 kΩ | CFG_1 (pin 59) → 3V3 | Master-SPI mode strap, CFG[2:0] = **010** |
| R6, R7 | 1 kΩ | CFG_0 (62) → GND, CFG_2 (58) → GND | mode straps |
| R8 | 1 kΩ | CCLK (54) → 3V3 | MCLK pull-up |
| R9–R12 | 100 Ω | the four Master-SPI nets, at the FPGA end | damping; bounds contention with GPIOA[1]/[2]/[4]/[6] |
| R13–R15 | 10 kΩ | U2 `/CS`, `/WP`, `/HOLD` → 3V3 | flash deselect/idle |
| R16–R18 | 10 kΩ | U3 `/CS`, `/WP`, `/HOLD` → 3V3 | flash deselect/idle |
| R19 | 10 kΩ | `motor_fault_n` → 3V3 | motor fault pull-up |
| R21, R23 | 0 Ω | CH340C TXD → `uart_rx`, RXD → `uart_tx` | UART routing option A |
| R22, R24 | 0 Ω | J10 → `uart_rx` / `uart_tx` | UART routing option B — populate **one pair only** |
| R25 | 4.7 kΩ | Q1 gate series | gate damping |
| R26 | 10 kΩ | Q1 gate → GND | keeps PROGRAMN released when DTR floats |
| R27–R30 | 470 Ω | `led[0..3]` → D2–D5 → 3V3 | ~4 mA per LED |
| R31 | 1 kΩ | INITN → Q4 base | Q4 drive |
| R32 | 10 kΩ | DONE → Q2 base | Q2 drive |
| R33 | 1 kΩ | Q2 collector → D1 → 3V3 | D1 current limit |
| R34 | 1 kΩ | Q4 collector → D6 → GND | D6 current limit |
| R36, R37 | 5.1 kΩ | USB-C CC1, CC2 → GND | Rd for a UFP power sink (omit with micro-USB) |
| R38 | **12.4 kΩ** (E96) | 1V1 → U6 FB | feedback divider top — **see §10 correction 2** |
| R39 | **33 kΩ** | U6 FB → GND | feedback divider bottom — must stay **below 40 kΩ** (§10 correction 2) |
| R40 | 100 kΩ | U6 FREQ → GND | switching frequency: the MP1584 datasheet's table gives **900 kHz at 100 kΩ** (formula R = 180000 / f^1.1, R in kΩ, f in kHz) |
| R41 | 100 kΩ | VM_IN → U6 EN, with C31 to GND | sequencing delay, τ = 47 ms |
| R42 | **1 MΩ** | Q3 gate → **GND** | turns Q3 on; with C32 this is the 2V5 delay (§10 correction 4) |
| **R43** | **100 kΩ** | Q3 gate → Q3 source | Vgs clamp: −10.9 V at VM_IN = 12 V, inside the ±12 V rating (§10 correction 4) |

### 3.3 Capacitors

| Ref | Value | Package | Purpose |
| :--- | :--- | :--- | :--- |
| C1 | 100 nF | 0603 | reset RC with R1 (noise and bounce, not timing) |
| C2–C7 | 100 nF ×6 | 0603 | VCC decoupling, one per pin: **20, 29, 38, 66, 83, 130** |
| C8–C11 | 100 nF ×4 | 0603 | VCCAUX decoupling: pins **17, 53, 96, 132** |
| C12–C20 | 100 nF ×9 | 0603 | VCCIO decoupling: pins **9, 16, 36, 43, 70, 86, 100, 122, 137** |
| C21 | 100 µF / 10 V electrolytic + 100 nF | 6.3 × 5.4 + 0603 | 1V1 bulk |
| C22 | 22 µF / 10 V electrolytic + 100 nF | 5 × 5 + 0603 | 2V5 bulk |
| C23 | 470 µF / **35 V** electrolytic + 100 nF | 10 × 10 + 0603 | LM2596 input bulk (datasheet value for this input range) |
| C24 | 220 µF / 16 V electrolytic + 100 nF | 8 × 6.9 + 0603 | LM2596 output bulk on 3V3 |
| C25 | 10 µF | 0805 | 3V3 bulk near banks 0/1/6/7 |
| C26 | 100 nF | 0603 | Y1 decoupling |
| C27 | 100 nF | 0603 | CH340C decoupling (plus the 100 nF on V3) |
| C28, C29 | 100 nF | 0603 | U2, U3 decoupling |
| C30 | 10 µF in + 10 µF out | 0805 ×2 | AMS1117 input/output — it needs ≥ 10 µF; bench-check for ringing (OQ-B10) |
| C31 | 470 nF | 0603 | U6 EN delay with R41 (47 ms time constant) |
| C32 | **4.7 µF** | 0805 | Q3 gate→**source** delay with R42/R43: τ = 91 kΩ × 4.7 µF ≈ 428 ms → ≈54 ms to threshold at 12 V |
| C33 | 100 nF | 0603 | U6 bootstrap, `BST` → `SW` |

### 3.4 Inductors and filtering

| Ref | Value | Specification | Package | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| L1 | 33 µH | ≥ 3 A saturation, shielded, low DCR | 8 × 8 mm | LM2596 3V3 inductor (datasheet value for 3.3 V fixed) |
| L2 | 10 µH | ≥ 3 A saturation, shielded | 6 × 6 mm | MP1584 1V1 inductor |
| FB1 | 600 Ω @ 100 MHz | ≥ 500 mA, 0603 | 0603 | VM_IN filtering ahead of the regulators |

### 3.5 Connectors, switches and test points

| Ref | Item | Pinout (by pin number) | Notes |
| :--- | :--- | :--- | :--- |
| J1 | 1×10 header, 2.54 mm | 1 3V3 · 2 TDO · 3 TDI · 4 PROGRAMn · 5 NC · 6 TMS · 7 GND · 8 TCK · 9 DONE · 10 INITn | Versa-style; works with `openFPGALoader` and FT232H/FT2232H adapters |
| J2 | 2×5 box header, 1.27 mm | 1 3V3 · 2 TMS · 3 TDI · 4 TDO · 5 TCK · 6 GND · 7–9 NC · 10 GND | wired in parallel with J1 — use one at a time |
| J3 | 2×10, 2.54 mm | 1 3V3 · 2 GND · 3 A8 · 4 A9 · 5 A10 · 6 A11 · 7 A12 · 8 A13 · 9 A14 · 10 A15 · 11 `spi0_cs_n` · 12 `spi0_sck` · 13 `spi0_mosi` · 14 `spi0_miso` · 15,16 GND · 17,18 5V · 19 GND · 20 GND | EXP-A: SPI0 + GPIOA[15:8]. The 5 V pins are USB VBUS only |
| J4 | 2×10, 2.54 mm | 1 3V3 · 2 GND · 3–18 B0–B15 · 19 GND · 20 5V | EXP-B: all 16 GPIOB |
| J5 | 1×10, 2.54 mm | 1 A0 · 2 A1 · 3 A2 · 4 A3 · 5 A4 · 6 A5 · 7 A6 · 8 A7 · 9 GND · 10 3V3 | EXP-C. **Pins 2/3/5/7 are also the configuration-flash nets — inputs only** (`BOARD.md` §6.4) |
| J6 | 1×6 keyed | 1 VM (VM_IN) · 2 GND · 3 `pwm_out` · 4 `motor_dir1` · 5 `motor_dir2` · 6 `motor_fault_n` | motor driver interface; the fuse lives on the driver board |
| J7 | 2×25, 2.54 mm | 46 spare I/O + 4 GND | footprint only, **not fitted** |
| J8 | USB-C receptacle 16 pin | VBUS, GND, D+, D−, CC1, CC2 (Rd = 5.1 kΩ) | power + console on one cable |
| J9 | 5.5/2.1 mm barrel | centre positive, **7–12 V** | bench supply; see `BOARD.md` OQ-B12 for the 5 V USB-load caveat |
| J10 | 1×4 header | 1 3V3 · 2 `uart_tx` · 3 `uart_rx` · 4 GND | console without the CH340C (fit R22/R24, remove R21/R23) |
| SW1 | 6 × 6 mm tactile | `ext_rst_n` → GND | reset |
| SW2 | 6 × 6 mm tactile | PROGRAMN → GND | reconfigure from flash |
| JP1 | 2-pin + shunt | in series with U4 DTR# → Q1 gate | remove to disable auto-reconfigure |
| TP1–TP6 | 1 mm pads | 3V3, 2V5, 1V1, GND, DONE, INITN | top side, labelled with these net names |

---

## 4. Pin-level connections

Everything in this section comes from the five connection sheets in `BOARD.md` §7. Pin *names* are what
matter; where a part's pin **numbers** depend on the vendor's drawing, the row says "confirm".

### 4.1 U1 — the FPGA (power, configuration and JTAG)

| U1 pin | Net / connection |
| ---: | :--- |
| 20, 29, 38, 66, 83, 130 | `1V1` (+ C2–C7, 100 nF each) |
| 17, 53, 96, 132 | `2V5` (+ C8–C11, 100 nF each) |
| 9, 16, 36, 43, 70, 86, 100, 122, 137 | `3V3` (+ C12–C20, 100 nF each) |
| 8, 15, 21, 32, 42, 65, 75, 85, 87, 101, 123, 129, 131, 138 | `GND` — each with its own via to the ground plane |
| 109, 144 | not connected |
| 54 | `CCLK` → R9 100 Ω → U2.6, and R8 1 kΩ → 3V3 |
| 46 | Master-SPI `D1/MISO` pad → R11 100 Ω → U2.2 (`DO`); also `gpio_a[1]` on J5.2 |
| 47 | Master-SPI `D0/MOSI` pad → R10 100 Ω → U2.5 (`DI`); also `gpio_a[2]` on J5.3 |
| 49 | `CSSPIN` pad → R12 100 Ω → U2.1 (`/CS`); also `gpio_a[4]` on J5.5 |
| 51 | Master-SPI `DOUT/CSON` pad — unused by the design; also `gpio_a[6]` on J5.7 |
| 57 | PROGRAMN → R2 4.7 kΩ → 3V3; SW2 → GND; J1.4; Q1 drain |
| 55 | INITN → R3 4.7 kΩ → 3V3; J1.10; R31 1 kΩ → Q4 base |
| 56 | DONE → R4 4.7 kΩ → 3V3; J1.9; R32 10 kΩ → Q2 base |
| 62, 59, 58 | CFG_0 → R6 1 kΩ → GND · CFG_1 → R5 4.7 kΩ → 3V3 · CFG_2 → R7 1 kΩ → GND |
| 63, 64, 61, 60 | TCK, TMS, TDI, TDO → J1.8/6/3/2 and J2.5/2/3/4 |
| 133 | `clk_25m` ← Y1.3 (25 MHz oscillator output) |
| 134 | `ext_rst_n` → SW1, R1 10 kΩ → 3V3, C1 100 nF → GND |
| 73, 74 | `uart_rx`, `uart_tx` → U4 or J10 (through R21–R24) |
| 110, 111, 112, 113 | `flash_sck`, `flash_cs_n`, `flash_mosi`, `flash_miso` → U3.6, U3.1, U3.5, U3.2 |
| 114–117 | `spi0_sck`, `spi0_cs_n`, `spi0_mosi`, `spi0_miso` → J3.12/11/13/14 |
| 39, 40, 41, 44 | `led[0..3]` → R27–R30 470 Ω → D2–D5 → 3V3 (active low) |
| 45–52 | `gpio_a[0..7]` → J5.1–J5.8 (pins 2/3/5/7 also reach the config flash) |
| 97–99, 104–108 | `gpio_a[8..15]` → J3.3–J3.10 |
| 135, 136, 139–143, 128, 124–127, 1–4 | `gpio_b[0..15]` → J4.3–J4.18 |
| 88, 89, 102, 103 | `pwm_out`, `motor_dir1`, `motor_dir2`, `motor_fault_n` → J6.3–J6.6 |

The complete 144-pin table, including the 46 unassigned I/O pins and every pad name, is
`board/TQFP144_PINOUT.md` (generated by `scripts/sv16_board_pins.py`). §5 below is the subset the design
actually constrains, generated from the LPF.

### 4.2 U2 — configuration flash (write-protected, driven by the FPGA)

| U2 pin | Net |
| ---: | :--- |
| 1 `/CS` | R12 100 Ω → U1.49, and R13 10 kΩ → 3V3 |
| 2 `DO` | R11 100 Ω → U1.46 |
| 3 `/WP` | R14 10 kΩ → 3V3 |
| 4 `GND` | GND |
| 5 `DI` | R10 100 Ω → U1.47 |
| 6 `CLK` | R9 100 Ω → U1.54 |
| 7 `/HOLD` | R15 10 kΩ → 3V3 (IO2/IO3 unused: no quad SPI on TQFP-144) |
| 8 `VCC` | 3V3 + C28 100 nF |

### 4.3 U3 — application flash (firmware, driven by the soft-core)

| U3 pin | Net |
| ---: | :--- |
| 1 `/CS` | U1.111 `flash_cs_n`, and R16 10 kΩ → 3V3 |
| 2 `DO` | U1.113 `flash_miso` |
| 3 `/WP` | R17 10 kΩ → 3V3 |
| 4 `GND` | GND |
| 5 `DI` | U1.112 `flash_mosi` |
| 6 `CLK` | U1.110 `flash_sck` |
| 7 `/HOLD` | R18 10 kΩ → 3V3 |
| 8 `VCC` | 3V3 + C29 100 nF |

### 4.4 U4 — CH340C USB–UART bridge ⚠ (confirm pin numbers against the WCH datasheet)

| U4 pin (name) | Net |
| :--- | :--- |
| `VCC`, `V3` | 3V3, each with 100 nF (V3 also to 3V3 in this 3.3 V-only design) |
| `GND` | GND |
| `UD+` | J8 D+ through the U8 channel (D+ side), with the 90 Ω differential pair |
| `UD−` | J8 D− through the U8 channel (D− side) |
| `TXD` | R21 0 Ω → U1.73 `uart_rx` (idles high) |
| `RXD` | R23 0 Ω → U1.74 `uart_tx` |
| `DTR#` | JP1 → Q1 gate (auto-reconfigure; remove JP1 to disable) |
| `RTS#` | not connected |

### 4.5 U5 — LM2596S-3.3 (3V3 rail, from VM_IN)

| U5 pin | Name | Connection |
| ---: | :--- | :--- |
| 1 | `VIN` | `VM_IN` after FB1, with C23 470 µF and 100 nF to GND |
| 2 | `OUT` | switch node: L1 33 µH → `3V3`; D10 cathode here (anode → GND) |
| 3 | `GND` (tab) | GND — copper pour under the tab |
| 4 | `FB` | **`3V3`** — the fixed 3.3 V version senses its own output here (TI SNVS124: the FB pin is "removed from output" only in the force-on/force-off test procedures) |
| 5 | `ON/OFF` | GND (always enabled; < 1.3 V = on) |

Output side: C24 220 µF + 100 nF on `3V3`.

### 4.6 U6 — MP1584EN (1V1 rail, from VM_IN)

| U6 pin | Name | Connection |
| ---: | :--- | :--- |
| 1 | `SW` | L2 10 µH → `1V1`; D11 cathode here (anode → GND); C33 100 nF to `BST` |
| 2 | `EN` | `VM_IN` → R41 100 kΩ → EN, C31 470 nF EN → GND (τ = 47 ms; crosses the 1.5 V rising threshold in ≈6 ms from 12 V, ≈13 ms from 5 V) |
| 3 | `COMP` | ⚠ **not yet specified** — the part needs an RC compensation network to GND (datasheet typical application, values depend on Vout and fsw). Add it before layout: §10 correction 3 |
| 4 | `FB` | divider from `1V1`: R38 top, R39 bottom — see §10 correction 2 for the recommended values |
| 5 | `GND` | GND (exposed pad to the ground plane, vias) |
| 6 | `FREQ` | R40 100 kΩ → GND ⇒ **900 kHz** |
| 7 | `VIN` | `VM_IN` with 100 nF |
| 8 | `BST` | C33 100 nF → `SW` |

Output side: C21 100 µF + 100 nF on `1V1`. **Measure this rail before fitting U1** (`BOARD.md` §10
step 2).

### 4.7 U7 and Q3 — the delayed 2V5 rail

| Device | Pin | Connection |
| :--- | :--- | :--- |
| Q3 (AO3401) | S | `VM_IN` (the AMS1117 needs ≥ 3.8 V in for 2.5 V out, so this section cannot run from 3V3) |
| | G | R42 1 MΩ → GND, C32 4.7 µF → S (source), **R43 100 kΩ** → S as the Vgs clamp |
| | D | U7 `VIN` |
| U7 (AMS1117-2.5) | 1 `GND` | GND |
| | 2 `VOUT` (tab) | `2V5` + C22 22 µF + 100 nF |
| | 3 `VIN` | Q3 drain + C30 10 µF to GND |

### 4.8 U8 — USB ESD protection ⚠ (confirm pin numbers against the ST datasheet)

| U8 pin | Connection |
| :--- | :--- |
| 1 `I/O1` | J8 `D+` (connector side) |
| 2 `GND` | GND |
| 3 `I/O2` | J8 `D−` |
| 4 `I/O2'` | U4 `UD−` (protected side) |
| 5 `VBUS` | J8 `VBUS` |
| 6 `I/O1'` | U4 `UD+` |

Place U8 at the connector; the D+/D− pair runs from J8 through U8 to U4 as a 90 Ω differential pair.
CC1/CC2 → R36/R37 5.1 kΩ → GND, within 10 mm of J8.

### 4.9 Status and user LEDs (all active low)

| Net | Chain |
| :--- | :--- |
| `led[0]` (U1.39) | R27 470 Ω → D2 → `3V3` |
| `led[1]` (U1.40) | R28 470 Ω → D3 → `3V3` |
| `led[2]` (U1.41) | R29 470 Ω → D4 → `3V3` |
| `led[3]` (U1.44) | R30 470 Ω → D5 → `3V3` |
| DONE (U1.56) | R32 10 kΩ → Q2 base; Q2 emitter → GND; Q2 collector → D1 → R33 1 kΩ → `3V3` (D1 lights when DONE is high) |
| INITN (U1.55) | R31 1 kΩ → Q4 base; Q4 emitter → `3V3`; Q4 collector → D6 → R34 1 kΩ → GND (D6 lights when INITN is low; **D6 is DNP by default**) |
| 3V3 present | D7 + its series resistor from `3V3` to GND |

---

## 5. FPGA pin table — generated from the constraint file

The table below is generated by `scripts/sv16_pcb_doc.py` directly from
`constraints/ecp5_144tqfp.lpf`, so it cannot drift from the bitstream's pin map. `make lint` fails if it
is stale.

<!-- BEGIN U1-PIN-TABLE (generated by scripts/sv16_pcb_doc.py from constraints/ecp5_144tqfp.lpf) -->

| TQFP pin | Bank | Port (LPF name) | IO type | Drive | Pull | Board net |
| ---: | :-: | :--- | :--- | ---: | :--- | :--- |
| 1 | 7 | `gpio_b[12]` | LVCMOS33 | 8 mA | NONE | J4.15 (EXP-B) |
| 2 | 7 | `gpio_b[13]` | LVCMOS33 | 8 mA | NONE | J4.16 (EXP-B) |
| 3 | 7 | `gpio_b[14]` | LVCMOS33 | 8 mA | NONE | J4.17 (EXP-B) |
| 4 | 7 | `gpio_b[15]` | LVCMOS33 | 8 mA | NONE | J4.18 (EXP-B) |
| 39 | 8 | `led[0]` | LVCMOS33 | 8 mA | NONE | D2 + R27 (status LED, active low) |
| 40 | 8 | `led[1]` | LVCMOS33 | 8 mA | NONE | D3 + R28 (status LED, active low) |
| 41 | 8 | `led[2]` | LVCMOS33 | 8 mA | NONE | D4 + R29 (status LED, active low) |
| 44 | 8 | `led[3]` | LVCMOS33 | 8 mA | NONE | D5 + R30 (status LED, active low) |
| 45 | 8 | `gpio_a[0]` | LVCMOS33 | 8 mA | NONE | J5.1 (EXP-C) |
| 46 | 8 | `gpio_a[1]` | LVCMOS33 | 8 mA | NONE | J5.2 (EXP-C) + U2 config-flash net (BOARD.md 6.4) |
| 47 | 8 | `gpio_a[2]` | LVCMOS33 | 8 mA | NONE | J5.3 (EXP-C) + U2 config-flash net (BOARD.md 6.4) |
| 48 | 8 | `gpio_a[3]` | LVCMOS33 | 8 mA | NONE | J5.4 (EXP-C) |
| 49 | 8 | `gpio_a[4]` | LVCMOS33 | 8 mA | NONE | J5.5 (EXP-C) + U2 config-flash net (BOARD.md 6.4) |
| 50 | 8 | `gpio_a[5]` | LVCMOS33 | 8 mA | NONE | J5.6 (EXP-C) |
| 51 | 8 | `gpio_a[6]` | LVCMOS33 | 8 mA | NONE | J5.7 (EXP-C) + U2 config-flash net (BOARD.md 6.4) |
| 52 | 8 | `gpio_a[7]` | LVCMOS33 | 8 mA | NONE | J5.8 (EXP-C) |
| 73 | 3 | `uart_rx` | LVCMOS33 | 4 mA | UP | U4 TXD via R21 (or J10.3 via R22) |
| 74 | 3 | `uart_tx` | LVCMOS33 | 4 mA | NONE | U4 RXD via R23 (or J10.2 via R24) |
| 88 | 2 | `pwm_out` | LVCMOS33 | 16 mA | NONE | J6.3 (motor PWM) |
| 89 | 2 | `motor_dir1` | LVCMOS33 | 8 mA | NONE | J6.4 (motor DIR1) |
| 97 | 2 | `gpio_a[8]` | LVCMOS33 | 8 mA | NONE | J3.3 (EXP-A) |
| 98 | 2 | `gpio_a[9]` | LVCMOS33 | 8 mA | NONE | J3.4 (EXP-A) |
| 99 | 2 | `gpio_a[10]` | LVCMOS33 | 8 mA | NONE | J3.5 (EXP-A) |
| 102 | 2 | `motor_dir2` | LVCMOS33 | 8 mA | NONE | J6.5 (motor DIR2) |
| 103 | 2 | `motor_fault_n` | LVCMOS33 | 4 mA | UP | J6.6 (motor FAULTn) + R19 pull-up |
| 104 | 2 | `gpio_a[11]` | LVCMOS33 | 8 mA | NONE | J3.6 (EXP-A) |
| 105 | 2 | `gpio_a[12]` | LVCMOS33 | 8 mA | NONE | J3.7 (EXP-A) |
| 106 | 2 | `gpio_a[13]` | LVCMOS33 | 8 mA | NONE | J3.8 (EXP-A) |
| 107 | 2 | `gpio_a[14]` | LVCMOS33 | 8 mA | NONE | J3.9 (EXP-A) |
| 108 | 2 | `gpio_a[15]` | LVCMOS33 | 8 mA | NONE | J3.10 (EXP-A) |
| 110 | 1 | `flash_sck` | LVCMOS33 | 8 mA | NONE | U3.6 CLK (application flash) |
| 111 | 1 | `flash_cs_n` | LVCMOS33 | 8 mA | NONE | U3.1 /CS |
| 112 | 1 | `flash_mosi` | LVCMOS33 | 8 mA | NONE | U3.5 DI |
| 113 | 1 | `flash_miso` | LVCMOS33 | 4 mA | UP | U3.2 DO |
| 114 | 1 | `spi0_sck` | LVCMOS33 | 8 mA | NONE | J3.12 (EXP-A) |
| 115 | 1 | `spi0_cs_n` | LVCMOS33 | 8 mA | NONE | J3.11 (EXP-A) |
| 116 | 1 | `spi0_mosi` | LVCMOS33 | 8 mA | NONE | J3.13 (EXP-A) |
| 117 | 1 | `spi0_miso` | LVCMOS33 | 4 mA | UP | J3.14 (EXP-A) |
| 124 | 1 | `gpio_b[8]` | LVCMOS33 | 8 mA | NONE | J4.11 (EXP-B) |
| 125 | 1 | `gpio_b[9]` | LVCMOS33 | 8 mA | NONE | J4.12 (EXP-B) |
| 126 | 1 | `gpio_b[10]` | LVCMOS33 | 8 mA | NONE | J4.13 (EXP-B) |
| 127 | 1 | `gpio_b[11]` | LVCMOS33 | 8 mA | NONE | J4.14 (EXP-B) |
| 128 | 0 | `gpio_b[7]` | LVCMOS33 | 8 mA | NONE | J4.10 (EXP-B) |
| 133 | 0 | `clk_25m` | LVCMOS33 | 4 mA | NONE | Y1.3 (25 MHz oscillator output) |
| 134 | 0 | `ext_rst_n` | LVCMOS33 | 4 mA | UP | SW1 + R1 + C1 (reset button) |
| 135 | 0 | `gpio_b[0]` | LVCMOS33 | 8 mA | NONE | J4.3 (EXP-B) |
| 136 | 0 | `gpio_b[1]` | LVCMOS33 | 8 mA | NONE | J4.4 (EXP-B) |
| 139 | 0 | `gpio_b[2]` | LVCMOS33 | 8 mA | NONE | J4.5 (EXP-B) |
| 140 | 0 | `gpio_b[3]` | LVCMOS33 | 8 mA | NONE | J4.6 (EXP-B) |
| 141 | 0 | `gpio_b[4]` | LVCMOS33 | 8 mA | NONE | J4.7 (EXP-B) |
| 142 | 0 | `gpio_b[5]` | LVCMOS33 | 8 mA | NONE | J4.8 (EXP-B) |
| 143 | 0 | `gpio_b[6]` | LVCMOS33 | 8 mA | NONE | J4.9 (EXP-B) |

_52 constrained ports. Bank numbers come from `board/ecp5_tqfp144.json`; every bank on this board is 3V3 (VCCIO8 = 3V3 for the configuration and JTAG domains)._

<!-- END U1-PIN-TABLE -->

The remaining 46 I/O pins are unassigned spares (bank 1: 118–121; bank 2: 90–95; bank 3: 67–69, 71, 72,
76–82, 84; bank 6: 18, 19, 22–28, 30, 31, 33–35, 37; bank 7: 5–7, 10–14) — they go to J7 and nothing
else. `board/TQFP144_PINOUT.md` lists all 144 pins with pad names and banks.

---

## 6. Net classes for the schematic

| Net class | Nets | Why it exists |
| :--- | :--- | :--- |
| `Power` | `VM_IN`, `3V3`, `1V1`, `2V5` | wide traces, the pours, and the regulator loops |
| `Switching` | `U5.OUT`/`L1` node, `U6.SW`, `BST` | short, fat, away from the oscillator and flash; this is where EMI comes from |
| `USB` | `USB_D+`, `USB_D−` | 90 Ω differential pair, ESD device at the connector |
| `JTAG` | `TCK`, `TMS`, `TDI`, `TDO`, `PROGRAMN`, `INITN`, `DONE`, `CCLK` | short stubs, series resistors at the FPGA end |
| `Default` | everything else | 0.25 mm signal |

**Net names to use:** the LPF signal names for FPGA pins (`clk_25m`, `ext_rst_n`, `uart_rx`, `uart_tx`,
`flash_sck`, `flash_cs_n`, `flash_mosi`, `flash_miso`, `spi0_sck`, `spi0_cs_n`, `spi0_mosi`, `spi0_miso`,
`led[0..3]`, `gpio_a[0..15]`, `gpio_b[0..15]`, `pwm_out`, `motor_dir1`, `motor_dir2`, `motor_fault_n`) and
`VM_IN` / `3V3` / `2V5` / `1V1` / `GND` for power. Nothing else — a net that exists only in KiCad cannot
be checked against the design.

---

## 7. Layout rules as KiCad DRC settings

| Rule | Setting in KiCad |
| :--- | :--- |
| Track width, signal | 0.25 mm (`Default` net class) |
| Track width, power | 0.8 mm for `3V3`, `1V1`, `2V5`; 1.5 mm for `VM_IN` — or use the PWR plane for the three rails |
| Track width, switching nodes | 0.8 mm, as short as possible: U5.OUT→L1, U6.SW→L2, and the catch-diode loops |
| Differential pair | `USB_D+`/`USB_D−`: 90 Ω, 0.2 mm gap, equal length within 0.5 mm |
| Vias | 0.2 mm drill / 0.4 mm pad (0.3/0.6 for power) |
| Clearance | 0.2 mm minimum; 0.5 mm between `Switching` nets and everything in the `JTAG`/flash group |
| FPGA decoupling | C2–C20 within 3 mm of the matching pin, on the same side, via first at the pad |
| FPGA ground | every GND pin gets its own via to the inner GND plane; thermal vias under the body |
| Oscillator | Y1 within 10 mm of pin 133, no via in the trace, ground pour under it, ≥ 5 mm from switching nodes |
| Config flash | U2 within 15 mm of pins 46/47/49/54; R9–R12 at the FPGA end |
| Motor return | J6 GND returns to the C23 area on its own path — never through the FPGA ground |
| Keep-out | no copper pour under the USB-C shell's shield pads or under the barrel jack body |
| Test points | TP1–TP6 on the top side, with their net names in silkscreen |
| Silkscreen | name the headers (J1 JTAG, J3 EXP-A, J4 EXP-B, J5 EXP-C, J6 MOTOR, J10 CONSOLE), the rails at TP1–TP3, "5V only" at J3/J4 pins 17/18, and "CFG FLASH - INPUTS ONLY" at J5 pins 2/3/5/7 |

---

## 8. Assembly notes

| Step | Note |
| :--- | :--- |
| Order of fitting | passives → connectors → regulators → **U1 last** (after the rails are measured, `BOARD.md` §10 step 2) |
| QFP-144 | stencil + paste + hot air; inspect at 10× before power. Do not try to drag-solder 0.5 mm pitch without flux |
| TO-263 (U5) | solder the tab down and pour copper into it — that tab is the only heatsink |
| SOIC-8E (U6) | the exposed pad must be soldered (vias to the ground plane); a part soldered on its pins only will overheat |
| Polarity | D1–D7 cathode = the marked end; D8–D11 band = cathode (pin 1); electrolytics have a polarity stripe |
| DNP list (by default) | D6 (INITN LED), J7 (spare-I/O header), the optional level shifter — mark them on the silkscreen so a reviewer does not think they are missing |
| Note for KiCad | put the DNP parts in the schematic as normal but unticked in the "Exclude from board/BOM" fields, so the BOM the fab sees matches `BOARD.md` §3 |

---

## 9. Ordering list and cost

| Group | What to order | ₹ (single board) |
| :--- | :--- | ---: |
| FPGA | 2 × LFE5U-12F-6TG144C (digikey.in / mouser.in) — one spare | 3,300 |
| Tier-1 actives | LM2596S-3.3, MP1584EN, AMS1117-2.5, CH340C, 2 × W25Q64JVSSIQ, USBLC6-2SC6, 2N7002, BC817, BC807, AO3401 | 350 |
| Oscillator | YIC OSC25M-3.3I/S3-25T | 111 |
| Passives | 0603 resistor + capacitor assortment kit (covers every R and C on this board), plus 33 µH, 10 µH, ferrite bead, 4 electrolytics, 4 × SS34 | 750 |
| LEDs | 5 green + 2 red 0603 | 12 |
| Connectors | J1–J10, SW1/SW2, JP1, shunts | 130 |
| PCB | 5 × 4-layer 100 × 100 mm + stencil | 3,000 |
| **Total** | (excluding the spare FPGA and tools) | **≈ ₹4,350** |

A complete order list with the vendors and the module-first alternative is `BOARD.md` §3.2–§3.5.

---

## 10. Accuracy notes — what is fixed, and the four things to correct before layout

**Fixed and traceable:** every component here is the part finalised in `BOARD.md` §3, the FPGA pin map is
generated from `constraints/ecp5_144tqfp.lpf`, and the connections come from the five sheets in
`BOARD.md` §7. The transistor and diode pin conventions, the flash pinouts and the oscillator pinout are
standard for those packages.

**Four corrections found while writing this document — apply them to the schematic (all four are now
also recorded in `BOARD.md`):**

1. **`U5` pin 4 (`FB`) must be connected to `3V3`.** The earlier sheet shows only VIN, OUT, GND and
   ON/OFF. For the fixed 3.3 V version the feedback pin senses the output; the TI datasheet's own
   force-on/force-off test procedures are written as "feedback pin removed from output", which only makes
   sense if it is normally connected to it. Leaving it floating is not a valid configuration.
2. **`U6` feedback divider: 100 kΩ at the bottom is too high for this part.** The MP1584 datasheet says
   the FB bias current (≈20 µA) is why the *lower* divider resistor should stay **below 40 kΩ**. With
   R39 = 100 kΩ the divider current is only ≈11 µA, so the bias current shifts the output well above the
   intended 1.10 V — on a rail whose window is 1.045–1.155 V (±5 %), that is not a margin you can spend.
   Recommended divider: **R39 = 33 kΩ, R38 = 12.4 kΩ (E96)** ⇒ 0.8 × (1 + 12.4/33) = **1.1006 V**, divider
   current 24 µA, both resistors inside the datasheet's guidance. (`BOARD.md` §3.3, OQ-B10.)
3. **`U6` `COMP` pin needs an RC network.** The MP1584 requires loop compensation on COMP (an RC to
   GND); the board sheets do not show it. Take the values from the datasheet's typical application for
   your output voltage and switching frequency, add them to sheet 1, and re-check the loop on the bench
   during bring-up. Without it the regulator will be marginally stable at best.
4. **The 2V5 load switch was drawn the wrong way round, and its gate drive exceeded the FET's rating.**
   As originally written (R42 gate→source, C32 gate→GND) the gate sits at source potential through the
   discharged cap at t = 0, so **Q3 is on immediately and turns off later** — the opposite of a delayed
   turn-on. Corrected topology: **R42 1 MΩ gate→GND** (this is what turns the switch on), **C32 4.7 µF
   gate→source** (the delay: τ = (R42∥R43)·C32 ≈ 428 ms, reaching the −1.3 V threshold at ≈54 ms from
   12 V), and a new **R43 100 kΩ gate→source** to clamp the gate drive. Without R43 the gate settles at
   GND and Vgs = −VM_IN = −12 V at the maximum input, right on the AO3401's absolute maximum. Also
   corrected on the same sheet: this section runs from **VM_IN**, not 3V3 — an AMS1117-2.5 needs at least
   ≈3.8 V of input for a 2.5 V output, so a 3V3 source could never regulate.

**Rows marked ⚠ need your datasheet, not mine:** the MP1584 exposed-pad size, the electrolytic can sizes,
the inductor footprints, the USB-C receptacle and barrel-jack footprints (they vary by the exact part you
buy), and the CH340C and USBLC6 pin *numbers* — the connections above are by pin name, which is what the
datasheet will confirm.

**What this document cannot tell you:** whether your schematic or layout is correct. That is what the
review step in `TEAM_PLAN.md` §13.1 (P1 + P4 review before the PCB order on day 10) is for, and what
`BOARD.md` §10's bring-up sequence is for.

---

_Revision 1.0 — written against commit `6011293`, from `BOARD.md` revision 1.1 (India-sourced BOM) and
`constraints/ecp5_144tqfp.lpf`. Rebuild: `make pcb-doc` (regenerates §5 and re-renders this PDF)._
