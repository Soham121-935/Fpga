# Cart reconciliation — what you bought vs what the board assumes

Source: `digikey_1.png` (DigiKey India), `india_passives_1.png`, `india_passives_2.png` (Indian site,
"packs of 20"). Read again on **1 Oct 2026**. Nothing here is guessed: every row is a line on a
screenshot.

## 1. The headline: your cart is the **revision-1.0 power tree**, not the India-sourced revision 1.1

| Board ref | `BOARD.md` rev 1.1 says | **You bought** | Consequence |
| :--- | :--- | :--- | :--- |
| U5 (3V3) | LM2596S-3.3 (TO-263-5, 150 kHz, non-synchronous, needs D10 + big bulk) | **AP62300TWU-7** — synchronous buck, 4.2–18 V in, 3 A, TSOT-26 | electrically *better*: no catch diode, small inductor, no 470 µF input bulk. Board must use the AP62300 land pattern and an AP62300-appropriate inductor |
| U6 (1V1) | MP1584EN | **MP1584EN** ✔ | matches |
| U7 (2V5) | AMS1117-2.5 (SOT-223, 1 A) | **LP5907MFX-2.5** — LDO, 250 mA, SOT-23-5, **has an EN pin** | 16 mA load is fine. Because it has EN, the sequencing can be done with an RC on EN instead of the Q3 P-FET load switch |
| Q2, Q4 | BC817/BC807 | **MMBT3904 / MMBT3906** (SOT-23) | electrically equivalent, same SOT-23 pinout — no footprint change |
| D10, D11 | SS34 catch diodes | **SS34 ×2** ✔ (but see above: the AP62300 needs no catch diode) | the two SS34 become the D8/D9 input ORing pair, or spares |
| C23 (470 µF) | **35 V** minimum (12 V input, derating) | **470 µF / 16 V**, D8 × L10.5 mm | ⚠ **16 V on a 12 V rail is only 1.33× derating.** Use the 25 V or 35 V part, or cap VM_IN at 12 V and accept it. Your call — flagging it, not blocking |
| C24 (220 µF) | 16 V electrolytic | **220 µF hybrid** D8 × L10.5 mm ✔ | matches, and hybrid polymer is better for ripple |
| C22 (22 µF) | 5 × 5 mm | **22 µF / 63 V**, D6.3 × L5.4 mm | bigger can than the doc — footprint updated |
| C21 (100 µF, 1V1 bulk) | 100 µF / 10 V electrolytic | **100 µF / 25 V tantalum, D case** (+ a 100 µF/16 V D5×5.8 reel) | tantalum is the better choice for a 1 V rail — but **tantalum needs the polarity respected and a low-impedance source**; keep it |

## 2. Package changes the board file must carry

| Ref | Board file had | You bought | New footprint |
| :--- | :--- | :--- | :--- |
| R38 (12.4 k) | 0603 | **0402** (Yageo RC0402FR-0712K4L, 30 pcs) | `R_0402_1005Metric` ⚠ 0402 is what you have — I will use it, but it is finger-hard to hand-solder; a 0603 12.4 k is ₹2 if you prefer |
| R39 (33 k) | 0603 | **1206** (Yageo 33 k, 1/4 W) | `R_1206_3216Metric` |
| R9–R12 (100 Ω) | 0603 | **1206** (1 %) | `R_1206_3216Metric` |
| R31, R33, R34 (1 k) | 0603 | **1206** (1/4 W) | `R_1206_3216Metric` |
| R42 (1 M) | 0603 | **1206** | `R_1206_3216Metric` |
| R2, R3, R4 (4.7 k) | 0603 | **0805** | `R_0805_2012Metric` |
| R27–R30 (470 Ω) | 0603 | **0805** | `R_0805_2012Metric` |
| R36, R37 (5.1 k) | 0603 | **0805** | `R_0805_2012Metric` — and 5.1 k confirms **USB-C** |
| R40, R41, R43 (100 k) | 0603 | **0603** (0.1 %) ✔ | unchanged |
| C31, C32 (470 nF) | 0603 | **0603, Kemet X7R 50 V** ✔ | unchanged (C32 may become 1 µF if we use the LP5907 EN delay — see §4) |
| C1–C20, C26–C29, C33 (100 nF) | 0603 | **0603, Kemet X7R 50 V ×40** ✔ | unchanged |
| L1, L2 | 8×8 mm / 6×6 mm | **CD54 33 µH ×2 and CD54 10 µH ×2** | ~5.8 × 5.2 mm body: footprint set to the 6 mm class, verify against the part drawing |

## 2b. Second batch (1 Oct, after the first reconciliation)

| Board ref | Board document says | **You have** | Consequence |
| :--- | :--- | :--- | :--- |
| **U1** | LFE5U-12F-6TG144C | **LFE5U-12F-6TG144C** ✔ confirmed unchanged | no change to the pin map, the LPF or the bitstream flow |
| U4 | CH340C (internal clock) | **CH340G** (SOP-16) | needs a **12 MHz crystal (Y2) + 2 × 22 pF (C36/C37)** — the G has no internal clock. Board file, `BOARD.md` §3.1/§7.4 and `PCB_COMPONENTS.md` §4.4 updated. Pin 13 is DTR#; keep it for auto-reconfigure |
| Y1 | 25 MHz **active** XO, 3.3 V, 4-pin | **25 MHz HC49/US "crystal oscillator"** | ⚠ **HC49/US is a 2-pin PASSIVE crystal**, and the ECP5 has no on-chip crystal driver. It cannot drive `clk_25m` — the board would configure but have no clock, no console and no boot. **Check the pin count: 4 pins = active (fine), 2 pins = passive (this one)** |

**Two ways forward on Y1 (pick one):**

1. **Buy an active 25 MHz 3.3 V XO** (4-pin, 3.2×2.5 or 5×7 mm) — ₹110 at digikey.in, or the 7050/5032
   type on Amazon.in/eBay.in. The board file already has the footprint; nothing else changes. **Recommended.**
2. **Keep the HC49/US crystal and add a Pierce oscillator**: 74LVC1G04 unbuffered inverter (SOT-23-5),
   1 MΩ feedback resistor, the crystal, and 2 × 22 pF load caps (match the crystal's CL). Works at
   25 MHz, but it is three extra parts, a sensitive layout, and a bring-up risk on a board you have one
   weekend to finish.

Either way: **order a 12 MHz crystal for the CH340G** (₹15–25) unless you also swap U4 for a CH340C
(₹45, pin-compatible, and then Y2/C36/C37 are not fitted at all).

## 3. What is **not** on these three screenshots

Not a problem — but the board cannot be ordered without them:

| Missing | Note |
| :--- | :--- |
| **U1 LFE5U-12F-6TG144C** | the FPGA itself, and a spare |
| **Y1 25 MHz oscillator** | must be an *active* 3.3 V XO (3.2 × 2.5 mm or 5 × 7 mm) |
| **U4 CH340C** | USB–UART bridge |
| **J8 USB-C receptacle** | 16-pin, or micro-USB (then R36/R37 are not fitted) |
| Headers J1–J7, J10, JP1, switches SW1/SW2, barrel jack J9, test points | `BOARD.md` §3.2 |
| **Q3 AO3401** | only needed if we keep the P-FET load switch; with the LP5907's EN pin we can drop it |
| 2N7002 ✔ (bought, 7 pcs), USBLC6-2SC6 ✔ (3 pcs), SN74LVC1T45 ✔ (1 pc) | bought |
| 10 Ω 0805 ×40 | not used by this design — spares |

## 4. The one decision this creates

Your cart forces a choice about the **2V5 sequencing**, because the LP5907 has an EN pin:

* **Option A (recommended, fewer parts):** feed the LP5907 from **3V3** and delay it with an RC on its EN
  pin (R 100 k from 3V3 + C 1 µF to GND ⇒ crosses the ~1.2 V EN threshold at ≈45 ms, after the 1V1 rail).
  Delete **Q3, R42, R43, C32** and the SS34 catch diode story. Simpler, cheaper, and the parts you bought
  cover it.
* **Option B:** keep the Q3 load switch from VM_IN exactly as `BOARD.md` §7.1 now says — needs an AO3401
  you have not bought, and re-computing C32 for a 3V3 source (the VM_IN numbers do not transfer).

Either way the **board file, `PCB_COMPONENTS.md` §2–§3 and `BOARD.md` §4/§7.1 need one revision** to match
what is on your bench. That revision is written once, after you answer §4 and tell me whether U1, Y1, U4
and the connectors are already on order.

## 5. Status after the board file was rebuilt (revision 1.2)

Everything below is now **in** `hardware/sv16_board/sv16_board.kicad_pcb` (141 footprints, 596 pads,
472 on 133 nets, two ground zones, project file with net classes):

| From the cart | What the board file now has |
| :--- | :--- |
| U5 AP62300TWU-7 | TSOT-26 footprint, pins 1 GND / 2 SW / 3 VIN / 4 FB / 5 EN / 6 BST, C38 bootstrap, R46/R47 feedback (33 k / 10 k ⇒ 3.28 V), R48/R49 enable divider (EN is a **6 V** pin), C39 input + C40/C41 output ceramics. **D10 deleted** — no catch diode on a synchronous buck |
| U7 LP5907MFX-2.5 | SOT-23-5 (1 IN, 2 GND, 3 EN, 4 NC, 5 OUT) fed from 3V3, R43/C32 on EN ⇒ ≈21 ms. **Q3 and R42 deleted**; C42 10 µF low-ESR ceramic added because the part is only stable into one |
| U4 CH340G | SOIC-16 with the G pin numbers, Y2 12 MHz HC49/US through-hole + C36/C37 22 pF |
| Q2/Q4 MMBT3904/3906 | same SOT-23 pads, value strings updated |
| Package changes (§2) | R38 0402; the 1206 and 0805 groups; C21 tantalum D-case; C22 6.3×5.4; C23/C24 8×10.5; L1/L2 CD54 |
| SS34 ×2 needed | D8, D9 (input ORing) and D11 (MP1584 catch) are fitted; the fourth is a spare |

**Still to buy before the board will regulate** (₹100–200 total):

1. **10 kΩ 1 % resistor** — R47, the AP62300 feedback bottom leg.
2. **Ceramics**: 10 µF (C39, AP62300 input), 2 × 22 µF (C40/C41, 3V3 output), 10 µF (C42, LP5907
   output), plus the 10 µF ×2 the design already assumed for C25/C30.
3. **An active 25 MHz 3.3 V XO** for Y1 (4-pin — the HC49/US part is not it), unless you build the
   Pierce oscillator instead.

And one decision that is yours: the **470 µF input bulk is a 16 V part on a 12 V rail** (1.33×
derating, where 35 V was specified). Fine on a bench supply that never exceeds 12 V.
