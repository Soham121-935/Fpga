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
