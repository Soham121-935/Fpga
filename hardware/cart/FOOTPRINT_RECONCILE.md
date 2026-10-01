# Footprint reconciliation checklist

Work down this list **before routing**. Each row is a place where the board file's footprint must match
the part in your hand, not the part in the design document. Tick a row only after you have the datasheet
or the part open next to you.

| # | Ref | Footprint in `sv16_board.kicad_pcb` | Check against | Done |
| :-: | :--- | :--- | :--- | :-: |
| 1 | U1 | `Package_QFP:LQFP-144_20x20mm_P0.5mm` | Lattice datasheet body 20×20 mm, 0.5 mm pitch — update from the KiCad library | ☐ |
| 2 | U2, U3 | `Package_SO:SOIC-8_5.23x5.23mm_P1.27mm` | the flash you bought (208 mil) | ☐ |
| 3 | U4 | `Package_SO:SOIC-16_3.9x9.9mm_P1.27mm` | **CH340G**: XI=7, XO=8, DTR#=13, V3=4 (`PCB_COMPONENTS.md` §4.4) | ☐ |
| 3b | Y2 | `Crystal:Crystal_HC49-4H_Vertical` | the **12 MHz** crystal you buy for the CH340G (2-pin). Skipped with a CH340C | ☐ |
| 3c | Y1 | `Oscillator:..._ASE-4Pin_3.2x2.5mm` | **active 4-pin** XO. Your HC49/US part will not fit this footprint (see §2b of RECONCILED.md) | ☐ |
| 4 | U5 | `Package_TO_SOT_SMD:TO-263-5_TabPin3` | tab is pin 3 (GND) on your part | ☐ |
| 5 | U6 | `Package_SO:SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.3mm` | exposed-pad size from the MP1584 datasheet | ☐ |
| 6 | U7 | `Package_TO_SOT_SMD:SOT-223-3_TabPin2` | tab is pin 2 (VOUT) | ☐ |
| 7 | U8 | `Package_TO_SOT_SMD:SOT-23-6` | USBLC6 pinout (`PCB_COMPONENTS.md` §4.8) | ☐ |
| 8 | Y1 | `Oscillator:Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm` | your oscillator's actual body (3.2×2.5 or 5×7 mm) | ☐ |
| 9 | L1, L2 | `L_Bourns_SRR1260` (8×8), `L_Sunlord_SWPA6045S` (6×6) | your inductors' body and pad spacing | ☐ |
| 10 | C21–C24 | `CP_Elec_6.3x5.4` / `5x5.4` / `10x10.2` / `8x6.9` | your electrolytic cans (diameter × height) | ☐ |
| 11 | J8 | `Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12` | your receptacle; micro-USB ⇒ different footprint, omit R36/R37 | ☐ |
| 12 | J9 | `Connector_BarrelJack:BarrelJack_CUI_PJ-102AH_Horizontal` | your jack's pin spacing | ☐ |
| 13 | J1–J7, J10, JP1 | `Connector_PinHeader_2.54mm:…` | 2.54 mm headers as listed; J2 is 1.27 mm if fitted | ☐ |
| 14 | SW1, SW2 | `Button_Switch_THT:SW_PUSH_6mm` | your tact switches (6×6 mm, 4 pins) | ☐ |
| 15 | Q1–Q4 | `Package_TO_SOT_SMD:SOT-23` | pin 1 = gate/base on all four | ☐ |
| 16 | D1–D7 | `LED_SMD:LED_0603_1608Metric` | cathode mark direction on the reel | ☐ |
| 17 | D8–D11 | `Diode_SMD:D_SMA` | pin 1 = cathode (band) | ☐ |
| 18 | H1–H4 | `MountingHole:MountingHole_3.2mm_M3` | decided hole size | ☐ |
| 19 | — | **update all footprints from the library** | KiCad: Tools → Update Footprints from Library (keeps placement and nets) | ☐ |
