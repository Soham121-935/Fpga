#!/usr/bin/env python3
"""Generate PCB_CONNECTIONS.md: the SV-16 board's connections, written and drawn.

`PCB_COMPONENTS.md` is the specification (what each part is, why the values are
what they are).  This document is the *wiring*: one page per block, every pad of
every part and what it connects to, in the order you actually build the board.

Everything in the tables is generated from the same data the board file is
generated from - `sv16_board_kicad.py` (the netlist) and `sv16_pcb_copper.py`
(the copper plan) - so a connection in this document is a connection the board
file has.  The prose sections (how to read it, the checklists, the bring-up
numbers) are part of this generator for the same reason: no second copy to drift.

Usage
    scripts/sv16_pcb_connections.py            # write PCB_CONNECTIONS.md
    scripts/sv16_pcb_connections.py --check    # exit 1 if the file is stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sv16_board_kicad as board      # noqa: E402
import sv16_pcb_copper as copper      # noqa: E402

DOC = ROOT / "PCB_CONNECTIONS.md"

POWER = ("GND", "3V3", "2V5", "1V1", "VM_IN", "VM_IN_RAW", "USB_VBUS", "5V_USB")

# what each net is for, in one line - the "easy reading" part
NET_PURPOSE = {
    "GND": "the ground plane (In1.Cu) - every GND pad gets its own via",
    "3V3": "main rail, AP62300 + L1; the whole In2.Cu pour",
    "2V5": "FPGA VCCAUX, LP5907 from 3V3, RC-delayed on EN",
    "1V1": "FPGA core, MP1584 + L2; patch pour on In2.Cu",
    "VM_IN": "7-12 V after the ferrite, feeds U5 and U6",
    "VM_IN_RAW": "barrel / USB ORing node before FB1",
    "USB_VBUS": "5 V from the USB-C connector",
    "5V_USB": "VBUS only - J3/J4 pins 17/18/20, do not power the board here",
    "CCLK": "FPGA configuration clock (pin 54), R8 pull-up, R9 to U2",
    "U2_CLK": "U2 clock after the 100 ohm damping resistor",
    "MOSI": "FPGA configuration data out (pin 47)", "U2_DI": "U2 data in",
    "MISO": "FPGA configuration data in (pin 46)", "U2_DO": "U2 data out",
    "CSSPIN": "FPGA configuration chip select (pin 49)", "U2_CS": "U2 chip select",
    "U2_WP": "U2 write protect (pulled high)", "U2_HOLD": "U2 hold (pulled high)",
    "PROGRAMN": "configuration trigger, active low", "INITN": "SRAM clear / config error",
    "DONE": "configuration complete, high when running",
    "CFG_0": "mode strap, low", "CFG_1": "mode strap, high (Master SPI)", "CFG_2": "mode strap, low",
    "TCK": "JTAG clock", "TMS": "JTAG mode select", "TDI": "JTAG data in", "TDO": "JTAG data out",
    "ext_rst_n": "reset button and RC, active low",
    "Q1_G": "Q1 gate (DTR auto-reconfigure)", "Q1_D": "Q1 drain on PROGRAMN",
    "DTR": "CH340G DTR# output", "DTR_F": "DTR after the JP1 jumper",
    "Q2_B": "Q2 base", "Q2_C": "Q2 collector", "DONE_LED": "D1 anode",
    "Q4_B": "Q4 base", "Q4_C": "Q4 collector", "INITN_LED": "D6 cathode side",
    "clk_25m": "the 25 MHz clock into U1 pin 133",
    "uart_rx": "into the SoC (FPGA pin 73), idles high",
    "uart_tx": "out of the SoC (FPGA pin 74)",
    "U4_TXD": "CH340G transmit out", "U4_RXD": "CH340G receive in",
    "flash_sck": "application flash clock", "flash_cs_n": "application flash select",
    "flash_mosi": "application flash data out", "flash_miso": "application flash data in",
    "U3_WP": "U3 write protect (pulled high)", "U3_HOLD": "U3 hold (pulled high)",
    "USB_DP": "USB D+ at the connector", "USB_DN": "USB D- at the connector",
    "USB_DP_F": "USB D+ after the ESD device", "USB_DN_F": "USB D- after the ESD device",
    "CC1": "USB-C CC1, 5.1 k to GND", "CC2": "USB-C CC2, 5.1 k to GND",
    "U4_DTR": "CH340G DTR# pin 13", "U4_V3": "CH340G V3 pin, tied to 3V3",
    "Y2_XI": "12 MHz crystal, XI side", "Y2_XO": "12 MHz crystal, XO side",
    "U5_SW": "AP62300 switch node", "U5_BST": "AP62300 bootstrap",
    "U5_FB": "AP62300 feedback node", "U5_EN": "AP62300 enable (6 V pin)",
    "U6_SW": "MP1584 switch node", "U6_BST": "MP1584 bootstrap",
    "U6_EN": "MP1584 enable RC", "U6_FREQ": "MP1584 frequency set (900 kHz)",
    "FB_1V1": "1V1 feedback node", "U7_EN": "LP5907 enable RC", "U6_COMP": "MP1584 loop compensation",
    "U8_DP": "USBLC6 D+ (unused duplicate)", "U8_DN": "USBLC6 D- (unused duplicate)",
    "pwm_out": "motor PWM, 16 mA drive (pin 88)",
    "motor_dir1": "motor direction 1 (pin 89)", "motor_dir2": "motor direction 2 (pin 102)",
    "motor_fault_n": "motor fault input, pulled up (pin 103)",
    "spi0_sck": "SPI0 clock to EXP-A", "spi0_cs_n": "SPI0 chip select to EXP-A",
    "spi0_mosi": "SPI0 data out to EXP-A", "spi0_miso": "SPI0 data in to EXP-A",
    "J9_VIN": "barrel jack positive pin", "J10_TX": "console header TX side",
    "J10_RX": "console header RX side", "D7_A": "3V3-present LED anode",
    "D1_A": "D1 anode", "D6_K": "D6 cathode",
}

# which build step each block belongs to, for the "build it in this order" table
BLOCK_ORDER = [
    ("Power tree", ["U5", "U6", "U7", "L1", "L2", "D8", "D9", "D11", "FB1", "C23", "C24",
                    "C21", "C22", "C25", "C30", "C38", "C39", "C40", "C41", "C42",
                    "R38", "R39", "R40", "R41", "R43", "R45", "R46", "R47", "R48", "R49",
                    "C31", "C32", "C33", "C35", "J9"]),
    ("Clock, reset and status", ["Y1", "C26", "SW1", "SW2", "R1", "C1", "Q1", "Q2", "Q4",
                                 "R25", "R26", "R31", "R32", "R33", "R34", "R44",
                                 "D1", "D6", "D7", "JP1"]),
    ("Configuration flash", ["U2", "C28", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12",
                             "R13", "R14", "R15"]),
    ("Application flash", ["U3", "C29", "R16", "R17", "R18"]),
    ("USB and console", ["J8", "U8", "U4", "Y2", "C27", "C34", "C36", "C37", "R21", "R22",
                         "R23", "R24", "R36", "R37", "J10"]),
    ("Motor and expansion", ["J3", "J4", "J5", "J6", "J7", "R19", "R27", "R28", "R29", "R30",
                             "D2", "D3", "D4", "D5"]),
    ("JTAG", ["J1", "J2"]),
    ("The FPGA, its decoupling and the test points",
     ["U1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12", "C13",
      "C14", "C15", "C16", "C17", "C18", "C19", "C20", "TP1", "TP2", "TP3", "TP4", "TP5",
      "TP6", "H1", "H2", "H3", "H4", "FID1", "FID2", "FID3", "FID4"]),
]

# one line per part about *how* to place it (BOARD.md 11 / PCB_COMPONENTS.md 7)
PLACEMENT_NOTE = {
    "U1": "0.5 mm pitch: 0.2 mm fan-out tracks, 0.45/0.2 mm vias; fit it LAST, after the rails measure right",
    "U2": "within 15 mm of U1 pins 54/46/47/49; R9-R12 at the FPGA end",
    "U3": "ordinary SPI device on user I/O - nowhere near as critical as U2",
    "U4": "next to J8; keep XI/XO short and symmetrical, away from the switchers",
    "U5": "C38 across BST(6)-SW(2) right at the pins; feedback tap at C40/C41, not at the far end",
    "U6": "exposed pad soldered with its thermal vias; D11 loop as short as possible",
    "U7": "C42 must be low-ESR ceramic and close to OUT",
    "U8": "at the connector, not at the chip - it protects U4",
    "Y1": "within 10 mm of U1 pin 133, ground pour underneath, no via in the trace",
    "Y2": "short, symmetrical XI/XO traces; load caps to the same ground",
    "L1": "the AP62300 switch node: keep the loop tight",
    "L2": "the MP1584 switch node: keep the loop tight",
    "J8": "flush with the board edge, CC resistors within 10 mm",
    "J9": "opening clear of the edge; keep the motor return away from it",
    "R9": "100 ohm damping, at the FPGA end", "R10": "100 ohm damping, at the FPGA end",
    "R11": "100 ohm damping, at the FPGA end", "R12": "100 ohm damping, at the FPGA end",
    "C23": "input bulk, close to U5 VIN",
    "C24": "3V3 output bulk, at the L1 side of the rail",
    "C21": "1V1 bulk, tantalum - check the polarity bar",
}

# what is still missing from the cart (cart/RECONCILED.md section 5)
# footprints that depend on the exact part in your hand - confirm before ordering
FOOTPRINT_WARN = {
    "U6": "the MP1584 SOIC-8E exposed-pad size varies by vendor (`EP2.41x3.3mm` here)",
    "U4": "CH340G SOP-16 150 mil - confirm the pin numbers against the WCH datasheet",
    "J8": "USB-C 16-pin receptacle: this is the HRO TYPE-C-31-M-12 land pattern; a different part needs its own footprint (micro-USB drops R36/R37)",
    "J9": "5.5/2.1 mm barrel jack: confirm against the part you buy",
    "Y1": "3.2 x 2.5 mm 4-pad oscillator; a 5 x 7 mm part uses `Oscillator_SMD_Abracon_ASV-4Pin_7.0x5.1mm`",
    "Y2": "HC49/US through-hole (4.88 mm lead spacing); an SMD 3225 crystal needs its own footprint",
    "L1": "CD54 5.8 x 5.2 mm class; check the pad spacing on your part drawing",
    "L2": "CD54 5.8 x 5.2 mm class; check the pad spacing on your part drawing",
    "C21": "Kemet-D (EIA 7343-31) tantalum; polarity bar",
    "C22": "D6.3 x L5.4 mm electrolytic can",
    "C23": "D8 x L10.5 mm electrolytic can",
    "C24": "D8 x L10.5 mm electrolytic can",
}

STILL_TO_BUY = [
    ("R47", "10 kohm 1 %", "AP62300 feedback bottom leg - the rail will not regulate without it"),
    ("C39", "10 uF X5R 25 V", "AP62300 input ceramic"),
    ("C40, C41", "22 uF X5R 25 V", "AP62300 output ceramics"),
    ("C42", "10 uF low-ESR X5R", "LP5907 output - it is only stable into a low-ESR capacitor"),
    ("C25, C30", "10 uF", "3V3 local bulk and the LP5907 input"),
    ("Y1", "active 25 MHz 3.3 V XO, 4-pin", "the HC49/US crystal in the cart cannot clock the FPGA"),
    ("Y2", "12 MHz crystal + 22 pF x2", "only if U4 is the CH340G; the C variant needs neither"),
]


def nets_by_ref() -> dict:
    out: dict = {}
    for ref, pad, net in board.CONNECTIONS:
        out.setdefault(ref, {})[str(pad)] = net
    return out


def peers_by_net() -> dict:
    out: dict = {}
    for ref, pad, net in board.CONNECTIONS:
        out.setdefault(net, []).append("%s.%s" % (ref, pad))
    return out


def sorted_refs(refs) -> list:
    def key(ref):
        stem = ref.rstrip("0123456789")
        number = "".join(ch for ch in ref if ch.isdigit())
        return (stem, int(number) if number else 0)
    return sorted(refs, key=key)


def peers_line(net: str, peers: dict, exclude: str) -> str:
    """The other pads on this net, collapsed when the net is a big one."""
    members = [member for member in peers.get(net, []) if member != exclude]
    if net in POWER:
        rails = {"GND": "the GND plane", "3V3": "the 3V3 pour", "2V5": "the 2V5 patch",
                 "1V1": "the 1V1 patch", "VM_IN": "VM_IN copper",
                 "VM_IN_RAW": "the ORing node", "USB_VBUS": "J8 VBUS",
                 "5V_USB": "J3/J4 5 V pins"}
        return "%s (%d pads)" % (rails.get(net, net), len(members))
    if len(members) > 6:
        return "%s ... (%d pads)" % (", ".join(members[:5]), len(members))
    return ", ".join(members)


def component_tables() -> list:
    """[(block title, [markdown lines])] - one entry per part, in build order."""
    nets = nets_by_ref()
    peers = peers_by_net()
    placement = board.effective_placement()
    seen = set()
    out = []
    for title, refs in BLOCK_ORDER:
        for ref in refs:
            if ref in seen:
                continue
            entry = next((c for c in board.COMPONENTS if c[0] == ref), None)
            if entry is None or ref not in placement:
                continue
            seen.add(ref)
            _, library, builder, value, group = entry
            x, y, rot = placement[ref]
            dnp = " **(not fitted)**" if ref in board.DNP_REFS else ""
            rows = ["#### %s — %s  (at %.1f, %.1f mm%s)%s\n"
                    % (ref, value or library.split(":")[-1], x, y,
                       "" if not rot else ", rotated %d deg" % rot, dnp)]
            if ref in PLACEMENT_NOTE:
                rows.append("_%s_\n" % PLACEMENT_NOTE[ref])
            pads = nets.get(ref, {})
            rows.append("| pad | net | also connected to |")
            rows.append("| :--- | :--- | :--- |")
            for pad in sorted(pads, key=lambda p: (len(p), p)):
                net = pads[pad]
                rows.append("| %s | `%s` | %s |"
                            % (pad, net, peers_line(net, peers, "%s.%s" % (ref, pad))))
            unassigned = [str(pad["number"]) for pad in board.pads_of(builder)
                          if pad["number"] and str(pad["number"]) not in pads]
            if unassigned:
                rows.append("")
                rows.append("_No net (leave unconnected): %s_" % ", ".join(unassigned))
            rows.append("")
            out.append((title, rows))
    return out


def net_table() -> list:
    peers = peers_by_net()
    lines = []
    for net in board.NET_ORDER:
        members = peers.get(net, [])
        if not members:
            continue
        lines.append("| `%s` | %d | %s |" % (net, len(members),
                                            NET_PURPOSE.get(net, "")))
    return lines


def fpga_pin_rows() -> list:
    """U1's constrained pins with their TQFP number, signal and board net."""
    import re
    lpf = (ROOT / "constraints" / "ecp5_144tqfp.lpf").read_text()
    rows = []
    nets = nets_by_ref().get("U1", {})
    for match in re.finditer(r'LOCATE\s+COMP\s+"([^"]+)"\s+SITE\s+"([^"]+)"', lpf):
        signal, site = match.group(1), match.group(2)
        number = site.lstrip("P")
        net = nets.get(str(int(number)), "")
        peers = [m for m in peers_by_net().get(net, []) if m != "U1.%s" % number]
        rows.append((int(number), signal, net, ", ".join(peers) if peers else "-"))
    return sorted(rows)


HEADER = """# PCB connections — SV-16 Rev B

**What this file is.** The wiring of the SV-16 board, written out one part at a
time and drawn, so that building the schematic or routing the board is a matter
of copying rather than working things out. `PCB_COMPONENTS.md` says *what* each
part is; this says *what connects to what*, in the order you build it.

**Where it comes from.** Every table below is generated (by
`scripts/sv16_pcb_connections.py`) from the same data the KiCad board file is
generated from — `scripts/sv16_board_kicad.py` for the netlist and
`scripts/sv16_pcb_copper.py` for the copper plan. If a row here says `U1.54 ->
R9 -> U2.6`, then the board file has that connection. Nothing in this document
was typed from memory, and `make lint` fails if it drifts.

**The pictures** (in `hardware/sv16_board/`, regenerate with `make pcb-bitmap`):

| File | What it shows |
| :--- | :--- |
| `pcb_top_view.png` | the board from above: every footprint, pad, silkscreen label, the In2 rail pours and all {vias} vias |
| `pcb_bottom_view.png` | the same board flipped: through-hole pads and the B.Cu ground pour |
| `pcb_net_map.png` | the ratsnest coloured by function, with a legend — read this before you route |
| `pcb_power_map.png` | the power tree and the In2.Cu pour map, plus the pads the router still owes a trace |
| `pcb_connection_sheets.png` | the six connection sheets at the end of this file, drawn |
| `placement_preview.png` | the floorplan and the ratsnest, regenerated by the board generator |

**Two rules for reading it.**

1. **Rows marked ⚠** must be confirmed against the datasheet of the part in your
   hand (the MP1584's exposed pad, the USB-C and barrel-jack footprints, the
   crystal and inductor bodies). Everything else is standard-package or was
   reconciled against the cart in `hardware/cart/RECONCILED.md`.
2. **Net names are the LPF signal names** (`clk_25m`, `flash_cs_n`,
   `gpio_a[0]`…), so any net here can be traced to a line in
   `constraints/ecp5_144tqfp.lpf` and to a row in `board/TQFP144_PINOUT.md`.
   Power nets are `VM_IN` / `3V3` / `2V5` / `1V1` / `GND`.

---

## 1. Read this first — the five things that decide whether the board works

| # | Thing | The rule | Where |
| :-: | :--- | :--- | :--- |
| 1 | **The FPGA's rails** | 1V1 on pins 20/29/38/66/83/130, 2V5 on 17/53/96/132, 3V3 on 9/16/36/43/70/86/100/122/137. Getting one of these wrong is the classic dead-board bug | §4 |
| 2 | **The Master-SPI pads are also GPIOA pins** | `gpio_a[1]/[2]/[4]/[6]` share pins 46/47/49/51 with the configuration flash. Keep them **inputs** in firmware; R9–R12 (100 Ω) bound any contention | §4, §6 |
| 3 | **`EN` of the AP62300 is a 6 V pin** | never tie it to VM_IN — the R48/R49 divider is what protects it | §6 |
| 4 | **Y1 must be an active oscillator** | the ECP5 has no crystal driver; a 2-pin HC49/US part leaves the board with no clock, no console, no boot | §6 |
| 5 | **USB is a differential pair** | J8 → U8 → U4, no vias, gap 0.2 mm, length skew under 0.5 mm, CC resistors 5.1 k to GND | §4, §8 |

---

## 2. Every net on the board

{net_count} nets carry {pad_count} pads. This is the whole list, with what each
one is for; the pad-level detail is in §3.

| net | pads | what it is |
| :--- | :-: | :--- |
{net_rows}

---

## 3. Connection list, part by part

Read a row as: *this pad, this net, and the other pads on that net*. Power nets
are collapsed (`the GND plane (118 pads)`) because they are the plane, not a
wire — §7 says how each rail reaches its pads.

"""

SHEETS = """
---

## 8. The connection sheets, drawn

The same thing as §3–§7 but as pictures — `hardware/sv16_board/pcb_connection_sheets.png`
holds all six at full size. If you are drawing the schematic, these are the
sheets to copy.

### Sheet 1 — power into the FPGA

```
  J9 7-12 V --+-- D8 SS34 --+-- FB1 --+-- VM_IN --+-- U5 AP62300 -- L1 10uH -- 3V3
              |             |         |           |                              |
  J8 VBUS ----+-- D9 SS34 --+         C23 470u  +-- U6 MP1584EN -- L2 10uH -- 1V1
                                      C39 10u              |                     |
                                                           +-- D11 SS34 (catch)  C21 100u
  U7 LP5907-2.5:  3V3 -- IN ;  EN <-- R43 100k -- 3V3 ,  C32 470n -> GND  (~21 ms)
                  OUT -- 2V5 -- C42 10u + C22 22u

  U1 supplies:   1V1 -> pins 20 29 38 66 83 130   + C2-C7   100n each
                 2V5 -> pins 17 53 96 132         + C8-C11  100n each
                 3V3 -> pins  9 16 36 43 70 86 100 122 137  + C12-C20 100n each
                 GND -> pins  8 15 21 32 42 65 75 85 87 101 123 129 131 138
                 NC  -> pins 109, 144
```

### Sheet 2 — configuration, JTAG, reset, status

```
  U1.57 PROGRAMN --+-- R2 4.7k -- 3V3        U1.63 TCK -- J1.8 -- J2.5
                   +-- SW2 -- GND             U1.64 TMS -- J1.6 -- J2.2
                   +-- J1.4                   U1.61 TDI -- J1.3 -- J2.3
                   +-- Q1 drain               U1.60 TDO -- J1.2 -- J2.4
                       Q1 source -- GND       J1.7 / J2.6 / J2.10 -- GND
                       Q1 gate -- R25 4.7k -- JP1 -- U4 DTR#
                       Q1 gate -- R26 10k -- GND

  U1.55 INITN --+-- R3 4.7k -- 3V3     U1.56 DONE --+-- R4 4.7k -- 3V3
                +-- J1.10                            +-- J1.9
                +-- R31 1k -- Q4 base                +-- R32 10k -- Q2 base
                    Q4 (PNP) emitter -- 3V3              Q2 (NPN) emitter -- GND
                    Q4 collector -- D6 -- R34 1k -- GND   Q2 collector -- D1 -- R33 1k -- 3V3

  mode straps:  CFG_0 (62) -- R6 1k -- GND   CFG_1 (59) -- R5 4.7k -- 3V3   CFG_2 (58) -- R7 1k -- GND
  reset:        ext_rst_n (134) -- SW1 -- GND ,  R1 10k -- 3V3 ,  C1 100n -- GND
```

### Sheet 3 — the two flashes

```
  U2 configuration flash (Master SPI, driven by the configuration logic)
    U1.54 CCLK -- R9 100R --> U2.6 CLK        U1.54 -- R8 1k -- 3V3
    U1.47 MOSI -- R10 100R -> U2.5 DI         U2.1 /CS  -- R13 10k -- 3V3
    U1.46 MISO -- R11 100R -> U2.2 DO         U2.3 /WP  -- R14 10k -- 3V3
    U1.49 CSSPIN - R12 100R -> U2.1 /CS       U2.7 /HOLD-- R15 10k -- 3V3
                                              U2.8 VCC = 3V3 + C28 100n ; U2.4 GND

  U3 application flash (driven by the soft core, sv16_flash_ctrl at 0xF0A0)
    U1.110 flash_sck  -------------> U3.6 CLK      U3.1 /CS -- R16 10k -- 3V3
    U1.111 flash_cs_n -------------> U3.1 /CS      U3.3 /WP -- R17 10k -- 3V3
    U1.112 flash_mosi -------------> U3.5 DI       U3.7 /HOLD- R18 10k -- 3V3
    U1.113 flash_miso <------------ U3.2 DO        U3.8 VCC = 3V3 + C29 100n
```

### Sheet 4 — clock, reset, console

```
  Y1 25.000 MHz ACTIVE XO          U4 CH340G (SOP-16)                 J8 USB-C
    1 EN  -- 3V3                     2 TXD -- R21 0R -- U1.73            A4 B4 A9 B9 -- VBUS
    2 GND -- GND                     3 RXD -- R23 0R -- U1.74            A6/B6 D+ -- U8 -- D+/D- U4.5
    3 OUT -- U1.133 clk_25m          4 V3  -- 3V3 + C34 100n             A7/B7 D- -- U8 -- D-/D+ U4.6
    4 VCC -- 3V3 + C26 100n          7 XI / 8 XO -- Y2 12 MHz + C36/C37    A5 CC1 -- R36 5.1k -- GND
                                     13 DTR# -- JP1 -- R25 -- Q1 gate     B5 CC2 -- R37 5.1k -- GND
  SW1/R1/C1 on U1.134                16 VCC -- 3V3 + C27 100n             S1-S4 -- GND
                                     5 UD+ / 6 UD- -- U8

  J10 console alternative: fit R22/R24 and REMOVE R21/R23.
```

### Sheet 5 — expansion and motor

```
  J3 EXP-A 2x10    1 3V3   2 GND   3-10 A8..A15   11 spi0_cs_n  12 spi0_sck
                   13 spi0_mosi  14 spi0_miso  15,16 GND  17,18 5V(VBUS)  19,20 GND
  J4 EXP-B 2x10    1 3V3   2 GND   3-18 B0..B15   19 GND  20 5V(VBUS)
  J5 EXP-C 1x10    1-8 A0..A7      9 GND  10 3V3   (pins 2/3/5/7 also reach U2: INPUTS ONLY)
  J6 MOTOR 1x6     1 VM_IN  2 GND  3 pwm_out  4 motor_dir1  5 motor_dir2  6 motor_fault_n
  J7 SPARE 2x25    footprint only, not fitted (46 spare I/O + 4 GND)
  LEDs             led[0..3] (39 40 41 44) -- R27-R30 470R -- D2-D5 -- 3V3   (active low)
```

### Sheet 6 — build order and first power-up

```
  1  power section only: U5 U6 U7 L1 L2 D8 D9 D11 FB1 C23 C24 C39 C40 C41 J9
  2  bench supply 12 V, current limit 200 mA, through J9
  3  TP1 = 3.28 V    TP3 = 1.10 V    TP2 = 2.50 V (≈21 ms after 3V3)   TP4 = 0 V
  4  wrong rail? -> R46/R47 (3V3) · R38/R39 (1V1) · R43/C32 (2V5) · U5 EN ≈3 V, never 12 V
  5  fit the rest, U1 (FPGA) last
  6  power again, re-measure all four test points
  7  USB: the CH340G must appear as a serial port
  8  configure over J1 (openFPGALoader), then write the config flash
  9  DONE (TP5) high, monitor answers '?' at 115200 8-N-1
 10  DONE never rises -> scope clk_25m at Y1 pin 3, then check PROGRAMN, CCLK, U2
```
"""


def build_document() -> str:
    peers = peers_by_net()
    nets = nets_by_ref()
    plan = board.copper_plan()
    placement = board.effective_placement()
    pad_count = sum(len(v) for v in nets.values())
    real_nets = [net for net in board.NET_ORDER if peers.get(net)]

    parts = []
    current = None
    for title, rows in component_tables():
        if title != current:
            parts.append("### %s\n" % title)
            current = title
        parts.extend(rows)

    body = [HEADER.format(
        vias=len(plan.vias), net_count=len(real_nets), pad_count=pad_count,
        net_rows="\n".join(net_table()))]

    body.append("### Build order\n")
    body.append("| # | block | parts |")
    body.append("| :-: | :--- | :--- |")
    for index, (title, refs) in enumerate(BLOCK_ORDER, start=1):
        present = [ref for ref in refs if ref in placement]
        body.append("| %d | %s | %s |" % (index, title, " · ".join(present)))
    body.append("")
    body.extend(parts)

    # ---- section 4: the FPGA
    body.append("---\n")
    body.append("## 4. The FPGA — U1, LFE5U-12F-6TG144C\n")
    body.append("52 of the 98 I/O pins are used. Pin numbers are the TQFP-144 "
                "physical pins; the signal names are the LPF names, so each row "
                "can be traced to `constraints/ecp5_144tqfp.lpf`.\n")
    body.append("| TQFP pin | signal | board net | connects to |")
    body.append("| :-: | :--- | :--- | :--- |")
    for number, signal, net, others in fpga_pin_rows():
        body.append("| %d | `%s` | `%s` | %s |" % (number, signal, net or "?", others))
    body.append("")
    body.append("Supplies and ground (the rows that matter most):\n")
    body.append("| pins | rail | decoupling |")
    body.append("| :--- | :--- | :--- |")
    body.append("| 20, 29, 38, 66, 83, 130 | 1V1 | C2–C7, 100 nF each |")
    body.append("| 17, 53, 96, 132 | 2V5 | C8–C11, 100 nF each |")
    body.append("| 9, 16, 36, 43, 70, 86, 100, 122, 137 | 3V3 | C12–C20, 100 nF each |")
    body.append("| 8, 15, 21, 32, 42, 65, 75, 85, 87, 101, 123, 129, 131, 138 | GND | one via each into the In1 plane |")
    body.append("| 109, 144 | — | not connected |")
    body.append("")

    # ---- section 5: connectors
    body.append("---\n")
    body.append("## 5. Connector pinouts\n")
    for ref, library, builder, value, group in board.COMPONENTS:
        if ref not in placement or group not in ("expansion", "jtag", "usb", "power"):
            continue
        if not ref.startswith("J"):
            continue
        pads = nets.get(ref, {})
        if not pads:
            continue
        body.append("**%s — %s** (%s)%s\n" % (ref, value or "", library.split(":")[-1],
                                              " **(not fitted)**" if ref in board.DNP_REFS else ""))
        if ref in FOOTPRINT_WARN:
            body.append("⚠ **Confirm the footprint**: %s\n" % FOOTPRINT_WARN[ref])
        entries = sorted(pads.items(), key=lambda kv: (len(kv[0]), kv[0]))
        body.append("| pin | net | | pin | net |")
        body.append("| :-: | :--- | :--- | :-: | :--- |")
        half = (len(entries) + 1) // 2
        for index in range(half):
            left = entries[index]
            right = entries[index + half] if index + half < len(entries) else ("", "")
            body.append("| %s | `%s` | | %s | `%s` |"
                        % (left[0], left[1], right[0], right[1] if right[0] else ""))
        body.append("")

    # ---- section 6: power tree
    body.append("---\n")
    body.append(POWER_SECTION.format(vias=len(plan.vias)))

    # ---- section 7: what the copper plan already did
    by_net: dict = {}
    for via in plan.vias:
        by_net[via["net"]] = by_net.get(via["net"], 0) + 1
    manual = [line for line in plan.skipped if "route it out by hand" in line]
    body.append("---\n")
    body.append("## 7. Rail delivery — what is already copper, and what the router owes\n")
    body.append("The board file ships with the rail pours on `In2.Cu` and with the "
                "vias below already placed, each one wrapped in a 0.2 mm stub track "
                "from its pad (that is how an SMD pad reaches an inner layer).\n")
    body.append("| net | copper |")
    body.append("| :--- | :--- |")
    body.append("| `3V3` | whole-layer pour on In2.Cu, priority 0 |")
    body.append("| `2V5` | patch pour: LP5907 group + the C8–C11 band above U1 |")
    body.append("| `1V1` | patch pour: MP1584 group + the strip down the left of U1 (C2–C7) |")
    body.append("| `GND` | solid plane on In1.Cu + pour on B.Cu |")
    body.append("")
    body.append("Vias already placed: %s. Of those, %d are GND stitching round "
                "the board edge, and the rest are escape vias on pads that sit over "
                "their own rail's pour.\n"
                % (", ".join("`%s` %d" % kv for kv in sorted(by_net.items())),
                   sum(1 for v in plan.vias if v["dia"] > 0.5)))
    if manual:
        body.append("**These pads are over a different rail's pour, so a via would "
                    "short two rails.** Route each one with a 0.25 mm track to its "
                    "own patch (or move it in the placement and regenerate):\n")
        for line in manual:
            body.append("* %s" % line)
        body.append("")
    body.append("Everything else is a normal ratsnest connection: run `make pcb` "
                "then open the board, press **B** to fill the zones, and route.\n")

    body.append(SHEETS)

    body.append(BEFORE_ROUTING)
    body.append(BRING_UP)
    body.append(STILL_TO_BUY_SECTION)

    body.append("---\n")
    body.append("## 12. Regenerating this file\n")
    body.append("```sh\n"
                "make pcb            # board file + bitmaps + BOM/CPL + this document\n"
                "make pcb-check      # parse the board back: nets, pads, DRC-lite, placement\n"
                "python3 scripts/sv16_pcb_connections.py --check   # is this document stale?\n"
                "```\n")
    body.append("_Revision 1.0 — generated from commit data in "
                "`scripts/sv16_board_kicad.py` (netlist), "
                "`scripts/sv16_pcb_copper.py` (copper plan) and "
                "`constraints/ecp5_144tqfp.lpf` (pin map)._\n")
    return "\n".join(body) + "\n"


POWER_SECTION = """## 6. Power tree and sequencing

```
  J9 7-12 V ----+-- D8 SS34 --+-- FB1 600R --+-- VM_IN ---- U5 AP62300 -- L1 10uH --+-- 3V3
                |             |              |                                        |
  J8 VBUS ------+-- D9 SS34 --+              +-- VM_IN ---- U6 MP1584 -- L2 10uH --+-- 1V1
                                                                                    |
                                              VM_IN -- R48 100k -- U5.EN -- R49 33k -- GND
                                              VM_IN -- R41 100k -- U6.EN -- C31 470n -- GND
                                              3V3   -- R43 100k -- U7.EN -- C32 470n -- GND
                                              3V3   ---------------- U7.IN   (LP5907-2.5) -- OUT = 2V5
```

| Rail | Source | Set by | Rises | Bulk |
| :--- | :--- | :--- | :--- | :--- |
| **3V3** | U5 AP62300 (sync buck, 750 kHz) | R46 33k / R47 10k on FB → **3.28 V** | first, from VM_IN | C24 220 µF + C40/C41 22 µF + C25 10 µF |
| **1V1** | U6 MP1584 (buck, 900 kHz via R40) | R38 12.4k / R39 33k on FB → **1.10 V** | ≈13 ms after VM_IN | C21 100 µF (tantalum) + 100 nF |
| **2V5** | U7 LP5907 from 3V3 | RC on EN: R43 100k + C32 470n → **≈21 ms** | ≈21 ms after 3V3 | C42 10 µF (low-ESR, mandatory) + C22 22 µF |

Two things that break this board if they are wrong, both from `PCB_COMPONENTS.md` §10:

* **U5 pin 5 (`EN`) is a 6 V pin** — it is driven by the R48/R49 divider (3.0 V at
  12 V in), never by VM_IN directly.
* **U6 pin 3 (`COMP`)** needs its RC network (R45 / C35, already placed as
  components) — the MP1584 is not stable without it.

Current plan (`BOARD.md` §4.2): 3V3 ≈ 600 mA, 1V1 ≈ 150 mA, 2V5 ≈ 50 mA. Copper:
0.8 mm for the rails, 1.5 mm for VM_IN, pours for everything local. {vias} vias
are already placed, including one on every GND pad that could take one.
"""

BEFORE_ROUTING = """
---

## 9. Before you route — the twelve checks

| # | Check | Why |
| :-: | :--- | :--- |
| 1 | Open the **project** (`sv16_board.kicad_pro`), not the bare board | it carries the five net classes and their widths |
| 2 | **Tools → Update Footprints from Library** | the board ships with generated pads: correct numbers, positions and nets, approximate sizes |
| 3 | 141 footprints, 121 nets, 472 pads with a net, 291 vias, 163 stubs | the sanity check; `Inspect → Net Inspector` |
| 4 | Y1 within 10 mm of U1 pin 133 | a long clock trace picks up the switchers |
| 5 | U2 within 15 mm of U1 pins 54/46/47/49, with R9–R12 at the FPGA end | this is the configuration path the FPGA needs at power-on |
| 6 | The switchers (U5, U6, L1, L2, C38–C41) away from Y1, U2 and U4 | that is where the EMI comes from |
| 7 | U8 between J8 and U4, J8 flush with the edge, R36/R37 within 10 mm of J8 | the ESD device protects the chip only if it is on the connector side |
| 8 | **B** — fill all zones — then look for islands on In1.Cu | an unfilled plane is not a plane; islands are DRC warnings worth fixing |
| 9 | Check the three In2 pours do not leave a rail pad stranded | §7 lists the pads that are over the wrong pour |
| 10 | DRC with *refill zones* ticked; fix copper errors, ignore silkscreen ones for now | every copper error is a spinner or a short |
| 11 | Add a third via size **0.45 / 0.2 mm** for the QFP fan-out | the default 0.8/0.4 via will not fit between 0.5 mm pads |
| 12 | Route in this order: power → switcher loops → QFP fan-out → USB pair → clocks → the rest | it is the order that keeps the inner layers free for the pours |

Two numbers to keep in front of you while routing: **0.2 mm** track and
clearance for the FPGA fan-out, and **0.8 mm** for anything carrying a rail.
"""

BRING_UP = """
---

## 10. Bring-up: measure, in this order

| Step | Do | Expected |
| :-: | :--- | :--- |
| 1 | Fit **only** the power section and J9 | U5, U6, U7, L1, L2, D8, D9, D11, FB1, C23, C24, C39–C42 |
| 2 | Bench supply at 12 V, **200 mA** limit | a few tens of mA — if the limit trips, find the short before reapplying |
| 3 | TP1 | **3.28 V** (R46/R47) |
| 4 | TP3 | **1.10 V** (R38/R39, R45/C35) |
| 5 | TP2 | **2.50 V**, appearing ≈21 ms after 3V3 (R43/C32) |
| 6 | TP4 | 0 V |
| 7 | Fit the rest, U1 last | flashes before the FPGA, headers and connectors any time |
| 8 | Power again, re-measure TP1–TP3 | a sagging 3V3 with U1 fitted = a short under the QFP or a missing decoupling cap |
| 9 | Plug in USB | the CH340G appears as a serial port (`dmesg`, or Device Manager with the WCH driver) |
| 10 | Configure over J1 (`make prog`), then `make prog-flash` | DONE (TP5) goes high when the FPGA is configured |
| 11 | Open the console at 115200 8-N-1, send `?` | the monitor prints its help |
| 12 | If DONE never rises | scope `clk_25m` at Y1 pin 3 → then PROGRAMN (57), CCLK (54) and U2 |
"""

STILL_TO_BUY_SECTION = """
---

## 11. Still to buy (the parts the documents say are missing from the cart)

| Ref | What | Why the board does not work without it |
| :--- | :--- | :--- |
""" + "\n".join("| %s | %s | %s |" % row for row in STILL_TO_BUY) + """

And one decision that is yours: the **470 µF input bulk (C23) in the cart is a
16 V part on a 12 V rail** — 1.33× derating where 35 V was specified. Fine on a
bench supply that never exceeds 12 V; use 25–35 V if you can still change it.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if PCB_CONNECTIONS.md is stale")
    args = parser.parse_args()

    text = build_document()
    if args.check:
        if not DOC.exists() or DOC.read_text() != text:
            print("FAIL: %s is stale - run make pcb-connections" % DOC.name)
            return 1
        print("%s is current (%d lines)" % (DOC.name, text.count("\n")))
        return 0
    DOC.write_text(text)
    print("wrote %s (%d lines, %.0f KB)"
          % (DOC.name, text.count("\n"), len(text) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
