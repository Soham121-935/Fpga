#!/usr/bin/env python3
"""Generate a KiCad board file (.kicad_pcb) for the SV-16 microcontroller.

This is a *starting point* for layout, not a finished board.  It contains:

  * the 100 x 100 mm, 4-layer board outline on Edge.Cuts, four mounting holes
    and four fiducials
  * every component from PCB_COMPONENTS.md, placed in functional groups with a
    sane floorplan (power top-left, FPGA centre, flashes right, USB bottom-right,
    JTAG and expansion bottom-left)
  * the **complete netlist**: each pad is assigned to the net the documents
    specify, so KiCad draws the ratsnest and you can route without inventing
    connections
  * net classes (Default, Power, USB, JTAG, Switching) with the widths from
    PCB_COMPONENTS.md section 7

Footprint names are the standard KiCad library identifiers ("Resistor_SMD:R_0603_1608Metric"),
so after opening the board you can run *Update Footprints from Library* to replace
the embedded approximations with the official ones while keeping every placement
and every net.  That is the intended workflow: this file gives you the topology
and the netlist; KiCad's library gives you the exact pads.

Usage
    scripts/sv16_board_kicad.py              # write the board + preview + README
    scripts/sv16_board_kicad.py --check      # re-read the board and report it

The generator is deliberately stdlib-only: it emits KiCad's s-expression format
directly and then parses its own output back (balanced parentheses, footprint and
pad counts, net coverage) so a typo cannot silently produce a broken board.
"""

from __future__ import annotations

import argparse
import re
import sys
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "hardware" / "sv16_board"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sv16_pcb_copper  # noqa: E402  (the copper plan: pours, vias, stitching)
BOARD_FILE = OUT / "sv16_board.kicad_pcb"

BOARD_W, BOARD_H = 100.0, 100.0
MARGIN = 3.0

# --------------------------------------------------------------------------- nets
POWER_NETS = ["GND", "VM_IN", "3V3", "2V5", "1V1"]
# ordered so the net numbers are stable between runs
NET_ORDER = [
    "GND", "VM_IN_RAW", "VM_IN", "3V3", "2V5", "1V1", "5V_USB",
    # FPGA configuration / JTAG
    "CCLK", "U2_CLK", "MOSI", "U2_DI", "MISO", "U2_DO", "CSSPIN", "U2_CS",
    "U2_WP", "U2_HOLD", "PROGRAMN", "INITN", "DONE", "CFG_0", "CFG_1", "CFG_2",
    "TCK", "TMS", "TDI", "TDO", "ext_rst_n", "Q1_G", "Q1_D", "DTR", "DTR_F",
    "Q2_B", "Q2_C", "DONE_LED", "Q4_B", "Q4_C", "INITN_LED",
    # clock, console, application flash
    "clk_25m", "uart_rx", "uart_tx", "U4_TXD", "U4_RXD",
    "flash_sck", "flash_cs_n", "flash_mosi", "flash_miso", "U3_WP", "U3_HOLD",
    "USB_VBUS", "USB_DP", "USB_DN", "USB_DP_F", "USB_DN_F", "CC1", "CC2",
    # USB bridge strapping
    "U4_DTR", "U4_V3", "Y2_XI", "Y2_XO",
    # power tree internals
    "U5_SW", "U5_BST", "U5_FB", "U5_EN", "U6_SW", "U6_BST", "U6_EN", "U6_FREQ", "FB_1V1", "U7_EN",
    "U8_DP", "U8_DN",
    # motor / expansion
    "pwm_out", "motor_dir1", "motor_dir2", "motor_fault_n",
    "spi0_sck", "spi0_cs_n", "spi0_mosi", "spi0_miso",
    "led[0]", "led[1]", "led[2]", "led[3]",
    "A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7",
    "A8", "A9", "A10", "A11", "A12", "A13", "A14", "A15",
    "B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7",
    "B8", "B9", "B10", "B11", "B12", "B13", "B14", "B15",
    "TP_3V3", "TP_2V5", "TP_1V1", "TP_GND", "TP_DONE", "TP_INITN",
    "D7_A", "D1_A", "D6_K", "J9_VIN", "J10_TX", "J10_RX", "U6_COMP",
    "led[0]_k", "led[1]_k", "led[2]_k", "led[3]_k",
]

# ------------------------------------------------------------------ connections
# (reference, pad, net).  This is PCB_COMPONENTS.md section 4, as data.
CONNECTIONS: list[tuple[str, str, str]] = []


def connect(ref: str, pad: str, net: str) -> None:
    CONNECTIONS.append((ref, str(pad), net))


# --- U1, the FPGA (pin numbers are the datasheet's)
for pin in (20, 29, 38, 66, 83, 130):
    connect("U1", pin, "1V1")
for pin in (17, 53, 96, 132):
    connect("U1", pin, "2V5")
for pin in (9, 16, 36, 43, 70, 86, 100, 122, 137):
    connect("U1", pin, "3V3")
for pin in (8, 15, 21, 32, 42, 65, 75, 85, 87, 101, 123, 129, 131, 138):
    connect("U1", pin, "GND")
# configuration
connect("U1", 54, "CCLK");    connect("U1", 46, "MISO")
connect("U1", 47, "MOSI");    connect("U1", 49, "CSSPIN")
connect("U1", 57, "PROGRAMN"); connect("U1", 55, "INITN"); connect("U1", 56, "DONE")
connect("U1", 62, "CFG_0");   connect("U1", 59, "CFG_1");   connect("U1", 58, "CFG_2")
connect("U1", 63, "TCK");     connect("U1", 64, "TMS")
connect("U1", 61, "TDI");     connect("U1", 60, "TDO")
# clock, reset, console
connect("U1", 133, "clk_25m"); connect("U1", 134, "ext_rst_n")
connect("U1", 73, "uart_rx");  connect("U1", 74, "uart_tx")
# application flash
connect("U1", 110, "flash_sck"); connect("U1", 111, "flash_cs_n")
connect("U1", 112, "flash_mosi"); connect("U1", 113, "flash_miso")
# SPI0 expansion
connect("U1", 114, "spi0_sck"); connect("U1", 115, "spi0_cs_n")
connect("U1", 116, "spi0_mosi"); connect("U1", 117, "spi0_miso")
# LEDs (active low), GPIOA, GPIOB, motor
for index, pin in enumerate((39, 40, 41, 44)):
    connect("U1", pin, "led[%d]" % index)
for index in range(8):
    connect("U1", 45 + index, "A%d" % index)
for index in range(8):
    connect("U1", (97, 98, 99, 104, 105, 106, 107, 108)[index], "A%d" % (index + 8))
for index, pin in enumerate((135, 136, 139, 140, 141, 142, 143, 128,
                             124, 125, 126, 127, 1, 2, 3, 4)):
    connect("U1", pin, "B%d" % index)
connect("U1", 88, "pwm_out");       connect("U1", 89, "motor_dir1")
connect("U1", 102, "motor_dir2");   connect("U1", 103, "motor_fault_n")
# spare pins 109/144 are not connected

# --- U2, configuration flash (W25Q64JVSSIQ, SOIC-8)
connect("U2", 1, "U2_CS");  connect("U2", 2, "U2_DO"); connect("U2", 3, "U2_WP")
connect("U2", 4, "GND");    connect("U2", 5, "U2_DI"); connect("U2", 6, "U2_CLK")
connect("U2", 7, "U2_HOLD"); connect("U2", 8, "3V3")
# --- U3, application flash
connect("U3", 1, "flash_cs_n"); connect("U3", 2, "flash_miso")
connect("U3", 3, "U3_WP");      connect("U3", 4, "GND")
connect("U3", 5, "flash_mosi"); connect("U3", 6, "flash_sck")
connect("U3", 7, "U3_HOLD");    connect("U3", 8, "3V3")
# --- U4, CH340C USB-UART (pin numbers to be confirmed against the WCH datasheet)
# CH340G (SOP-16): 1 GND, 2 TXD, 3 RXD, 4 V3, 5 UD+, 6 UD-, 7 XI, 8 XO, 13 DTR#, 16 VCC
connect("U4", 1, "GND");      connect("U4", 2, "U4_TXD"); connect("U4", 3, "U4_RXD")
connect("U4", 4, "U4_V3");    connect("U4", 5, "USB_DP_F"); connect("U4", 6, "USB_DN_F")
connect("U4", 7, "Y2_XI");    connect("U4", 8, "Y2_XO")
connect("U4", 13, "U4_DTR");  connect("U4", 16, "3V3")
# --- U5, AP62300TWU-7 synchronous buck (TSOT-26: 1 GND, 2 SW, 3 VIN, 4 FB, 5 EN, 6 BST)
connect("U5", 1, "GND");     connect("U5", 2, "U5_SW")
connect("U5", 3, "VM_IN");   connect("U5", 4, "U5_FB")
connect("U5", 5, "U5_EN");   connect("U5", 6, "U5_BST")
# --- U6, MP1584EN (SOIC-8E)
connect("U6", 1, "U6_SW");   connect("U6", 2, "U6_EN"); connect("U6", 3, "U6_COMP")
connect("U6", 4, "FB_1V1");  connect("U6", 5, "GND");   connect("U6", 6, "U6_FREQ")
connect("U6", 7, "VM_IN");   connect("U6", 8, "U6_BST");  connect("U6", 9, "GND")
# --- U7, LP5907MFX-2.5 (SOT-23-5: 1 IN, 2 GND, 3 EN, 4 NC, 5 OUT)
connect("U7", 1, "3V3"); connect("U7", 2, "GND"); connect("U7", 3, "U7_EN"); connect("U7", 5, "2V5")
# --- U8, USBLC6-2SC6
connect("U8", 1, "USB_DP");  connect("U8", 2, "GND");  connect("U8", 3, "USB_DN")
connect("U8", 4, "USB_DN_F"); connect("U8", 5, "USB_VBUS"); connect("U8", 6, "USB_DP_F")
# --- Y1, 25 MHz oscillator
connect("Y1", 1, "3V3"); connect("Y1", 2, "GND"); connect("Y1", 3, "clk_25m"); connect("Y1", 4, "3V3")
# --- drivers
connect("Q1", 1, "Q1_G"); connect("Q1", 2, "GND"); connect("Q1", 3, "PROGRAMN")
connect("Q2", 1, "Q2_B"); connect("Q2", 2, "GND"); connect("Q2", 3, "Q2_C")
connect("Q4", 1, "Q4_B"); connect("Q4", 2, "3V3"); connect("Q4", 3, "Q4_C")
# --- LEDs and their resistors (D1 DONE, D2-5 GPIO, D6 INITN, D7 power)
connect("D1", 1, "Q2_C"); connect("D1", 2, "D1_A")   # cathode to the driver, anode to R33
for index in range(4):
    connect("D%d" % (index + 2), 1, "led[%d]_k" % index)
    connect("D%d" % (index + 2), 2, "3V3")
connect("D6", 1, "D6_K"); connect("D6", 2, "Q4_C")
connect("D7", 1, "GND");  connect("D7", 2, "D7_A")
# --- diodes in the power path
connect("D8", 1, "VM_IN_RAW"); connect("D8", 2, "J9_VIN")
connect("D9", 1, "VM_IN_RAW"); connect("D9", 2, "USB_VBUS")
connect("D11", 1, "U6_SW");  connect("D11", 2, "GND")
# --- inductors and ferrite
connect("L1", 1, "U5_SW");  connect("L1", 2, "3V3")
connect("L2", 1, "U6_SW");  connect("L2", 2, "1V1")
connect("FB1", 1, "VM_IN_RAW"); connect("FB1", 2, "VM_IN")
# --- resistors
connect("R1", 1, "ext_rst_n"); connect("R1", 2, "3V3")
connect("R2", 1, "PROGRAMN");  connect("R2", 2, "3V3")
connect("R3", 1, "INITN");     connect("R3", 2, "3V3")
connect("R4", 1, "DONE");      connect("R4", 2, "3V3")
connect("R5", 1, "CFG_1"); connect("R5", 2, "3V3")
connect("R6", 1, "CFG_0"); connect("R6", 2, "GND")
connect("R7", 1, "CFG_2"); connect("R7", 2, "GND")
connect("R8", 1, "CCLK"); connect("R8", 2, "3V3")
connect("R9", 1, "CCLK");     connect("R9", 2, "U2_CLK")
connect("R10", 1, "MOSI");    connect("R10", 2, "U2_DI")
connect("R11", 1, "MISO");    connect("R11", 2, "U2_DO")
connect("R12", 1, "CSSPIN");  connect("R12", 2, "U2_CS")
connect("R13", 1, "U2_CS");   connect("R13", 2, "3V3")
connect("R14", 1, "U2_WP");   connect("R14", 2, "3V3")
connect("R15", 1, "U2_HOLD"); connect("R15", 2, "3V3")
connect("R16", 1, "flash_cs_n"); connect("R16", 2, "3V3")
connect("R17", 1, "U3_WP");      connect("R17", 2, "3V3")
connect("R18", 1, "U3_HOLD");    connect("R18", 2, "3V3")
connect("R19", 1, "motor_fault_n"); connect("R19", 2, "3V3")
connect("R21", 1, "U4_TXD");  connect("R21", 2, "uart_rx")
connect("R22", 1, "uart_rx"); connect("R22", 2, "J10_RX")
connect("R23", 1, "U4_RXD");  connect("R23", 2, "uart_tx")
connect("R24", 1, "uart_tx"); connect("R24", 2, "J10_TX")
connect("R25", 1, "DTR_F");   connect("R25", 2, "Q1_G")
connect("R26", 1, "Q1_G");    connect("R26", 2, "GND")
for index in range(4):
    connect("R%d" % (27 + index), 1, "led[%d]" % index)
    connect("R%d" % (27 + index), 2, "led[%d]_k" % index)
connect("R31", 1, "INITN"); connect("R31", 2, "Q4_B")
connect("R32", 1, "DONE");  connect("R32", 2, "Q2_B")
connect("R33", 1, "3V3");   connect("R33", 2, "D1_A")
connect("R34", 1, "D6_K");  connect("R34", 2, "GND")
connect("R36", 1, "CC1"); connect("R36", 2, "GND")
connect("R37", 1, "CC2"); connect("R37", 2, "GND")
connect("R38", 1, "1V1");    connect("R38", 2, "FB_1V1")
connect("R39", 1, "FB_1V1"); connect("R39", 2, "GND")
connect("R40", 1, "U6_FREQ"); connect("R40", 2, "GND")
connect("R41", 1, "VM_IN");  connect("R41", 2, "U6_EN")
# AP62300 feedback and enable dividers (datasheet table for a 0.763 V reference)
connect("R46", 1, "3V3");   connect("R46", 2, "U5_FB")     # 33k top
connect("R47", 1, "U5_FB"); connect("R47", 2, "GND")       # 10k bottom -> 3.28 V
connect("R48", 1, "VM_IN");  connect("R48", 2, "U5_EN")    # 100k top (EN is a 6 V pin)
connect("R49", 1, "U5_EN");  connect("R49", 2, "GND")      # 33k bottom -> 3.0 V at 12 V in
# AP62300 support parts
connect("C38", 1, "U5_BST"); connect("C38", 2, "U5_SW")    # 100 nF bootstrap
connect("C39", 1, "VM_IN");  connect("C39", 2, "GND")      # 10 uF input ceramic
connect("C40", 1, "3V3");    connect("C40", 2, "GND")      # 22 uF output ceramic
connect("C41", 1, "3V3");    connect("C41", 2, "GND")      # 22 uF output ceramic
# 2V5 sequencing without the P-FET: 100k/470nF on the LP5907 EN pin, ~21 ms
connect("R43", 1, "3V3");    connect("R43", 2, "U7_EN")
connect("C42", 1, "2V5");    connect("C42", 2, "GND")      # LP5907 needs a low-ESR output cap
connect("R44", 1, "3V3");    connect("R44", 2, "D7_A")
# MP1584 loop compensation (values from the datasheet typical application - open
# item OQ-B10); added as components so their pads exist to place and route
connect("R45", 1, "U6_COMP"); connect("R45", 2, "GND")
connect("C35", 1, "U6_COMP"); connect("C35", 2, "GND")
# --- capacitors
connect("C1", 1, "ext_rst_n"); connect("C1", 2, "GND")
for index in range(6):
    connect("C%d" % (2 + index), 1, "1V1"); connect("C%d" % (2 + index), 2, "GND")
for index in range(4):
    connect("C%d" % (8 + index), 1, "2V5"); connect("C%d" % (8 + index), 2, "GND")
for index in range(9):
    connect("C%d" % (12 + index), 1, "3V3"); connect("C%d" % (12 + index), 2, "GND")
connect("C21", 1, "1V1"); connect("C21", 2, "GND")
connect("C22", 1, "2V5"); connect("C22", 2, "GND")
connect("C23", 1, "VM_IN"); connect("C23", 2, "GND")
connect("C24", 1, "3V3"); connect("C24", 2, "GND")
connect("C25", 1, "3V3"); connect("C25", 2, "GND")
connect("C26", 1, "3V3"); connect("C26", 2, "GND")
connect("C27", 1, "3V3"); connect("C27", 2, "GND")
connect("C28", 1, "3V3"); connect("C28", 2, "GND")
connect("C29", 1, "3V3"); connect("C29", 2, "GND")
connect("C30", 1, "3V3"); connect("C30", 2, "GND")
connect("C31", 1, "U6_EN");  connect("C31", 2, "GND")
connect("C32", 1, "U7_EN"); connect("C32", 2, "GND")
connect("C33", 1, "U6_BST"); connect("C33", 2, "U6_SW")
connect("C34", 1, "U4_V3");  connect("C34", 2, "GND")      # CH340G V3 decoupling
# CH340G clock: 12 MHz crystal on XI/XO with 22 pF load caps
connect("Y2", 1, "Y2_XI");   connect("Y2", 2, "Y2_XO")
connect("C36", 1, "Y2_XI");  connect("C36", 2, "GND")
connect("C37", 1, "Y2_XO");  connect("C37", 2, "GND")
# --- connectors and switches
connect("J1", 1, "3V3");  connect("J1", 2, "TDO"); connect("J1", 3, "TDI")
connect("J1", 4, "PROGRAMN"); connect("J1", 6, "TMS"); connect("J1", 7, "GND")
connect("J1", 8, "TCK");  connect("J1", 9, "DONE"); connect("J1", 10, "INITN")
connect("J2", 1, "3V3"); connect("J2", 2, "TMS"); connect("J2", 3, "TDI")
connect("J2", 4, "TDO"); connect("J2", 5, "TCK"); connect("J2", 6, "GND"); connect("J2", 10, "GND")
for pad, net in ((1, "3V3"), (2, "GND"), (3, "A8"), (4, "A9"), (5, "A10"), (6, "A11"),
                 (7, "A12"), (8, "A13"), (9, "A14"), (10, "A15"),
                 (11, "spi0_cs_n"), (12, "spi0_sck"), (13, "spi0_mosi"), (14, "spi0_miso"),
                 (15, "GND"), (16, "GND"), (17, "5V_USB"), (18, "5V_USB"), (19, "GND"), (20, "GND")):
    connect("J3", pad, net)
for pad, net in ((1, "3V3"), (2, "GND"), (19, "GND"), (20, "5V_USB")):
    connect("J4", pad, net)
for index in range(16):
    connect("J4", 3 + index, "B%d" % index)
for pad, net in ((1, "A0"), (2, "A1"), (3, "A2"), (4, "A3"), (5, "A4"), (6, "A5"),
                 (7, "A6"), (8, "A7"), (9, "GND"), (10, "3V3")):
    connect("J5", pad, net)
for pad, net in ((1, "VM_IN"), (2, "GND"), (3, "pwm_out"), (4, "motor_dir1"),
                 (5, "motor_dir2"), (6, "motor_fault_n")):
    connect("J6", pad, net)
connect("J8", "A1", "GND");  connect("J8", "B1", "GND")
connect("J8", "A12", "GND"); connect("J8", "B12", "GND")
connect("J8", "A4", "USB_VBUS"); connect("J8", "B4", "USB_VBUS")
connect("J8", "A9", "USB_VBUS"); connect("J8", "B9", "USB_VBUS")
connect("J8", "A5", "CC1");  connect("J8", "B5", "CC2")
connect("J8", "A6", "USB_DP"); connect("J8", "B6", "USB_DP")
connect("J8", "A7", "USB_DN"); connect("J8", "B7", "USB_DN")
for shield in ("S1", "S2", "S3", "S4"):
    connect("J8", shield, "GND")
connect("J9", 1, "J9_VIN"); connect("J9", 2, "GND")
connect("J10", 1, "3V3"); connect("J10", 2, "J10_TX"); connect("J10", 3, "J10_RX"); connect("J10", 4, "GND")
connect("SW1", 1, "ext_rst_n"); connect("SW1", 2, "GND")
connect("SW2", 1, "PROGRAMN");  connect("SW2", 2, "GND")
connect("JP1", 1, "U4_DTR"); connect("JP1", 2, "DTR_F")
connect("TP1", 1, "TP_3V3"); connect("TP2", 1, "TP_2V5"); connect("TP3", 1, "TP_1V1")
connect("TP4", 1, "TP_GND"); connect("TP5", 1, "TP_DONE"); connect("TP6", 1, "TP_INITN")
# test points tie back to the rails they measure (same net, so KiCad shows them connected)
CONNECTIONS = [(ref, pad, "3V3" if net == "TP_3V3" else
                        "2V5" if net == "TP_2V5" else
                        "1V1" if net == "TP_1V1" else
                        "GND" if net == "TP_GND" else
                        "DONE" if net == "TP_DONE" else
                        "INITN" if net == "TP_INITN" else net)
               for ref, pad, net in CONNECTIONS]

# Nets that no pad ended up on (the test-point aliases, the second USBLC6
# channel that this design does not use) are dropped rather than declared: an
# empty net in the file is a phantom in KiCad's Net Inspector.
_USED = {net for _, _, net in CONNECTIONS}
NET_ORDER = [net for net in NET_ORDER if net in _USED]

# ------------------------------------------------------------------- footprints
# Each builder returns (kiwi_library_id, pads).  A pad is a dict; "shape" is
# either a rectangle (w, h in mm) or a circle (d).
SMD_LAYERS = '"F.Cu" "F.Paste" "F.Mask"'


def rect(number, x, y, w, h, net=None, layers=SMD_LAYERS, kind="smd"):
    return {"number": str(number), "x": x, "y": y, "w": w, "h": h,
            "shape": "rect", "layers": layers, "net": net, "kind": kind}


def circle(number, x, y, d, net=None, layers=SMD_LAYERS, kind="smd", drill=None):
    return {"number": str(number), "x": x, "y": y, "w": d, "h": d,
            "shape": "circle", "layers": layers, "net": net, "kind": kind, "drill": drill}


def chip(pitch: float, pad_w: float, pad_h: float):
    """Two-pad chip footprint (0603, 0805)."""
    return lambda: ("", [rect(1, -pitch / 2, 0, pad_w, pad_h), rect(2, pitch / 2, 0, pad_w, pad_h)])


def soic(count: int, pitch: float, row: float, pad_w: float, pad_h: float, ep=None):
    def build():
        pads = []
        per_side = count // 2
        for index in range(per_side):                 # left column, top to bottom
            y = (per_side - 1) * pitch / 2 - index * pitch
            pads.append(rect(index + 1, -row / 2, y, pad_w, pad_h))
        for index in range(per_side):                 # right column, bottom to top
            y = -(per_side - 1) * pitch / 2 + index * pitch
            pads.append(rect(per_side + index + 1, row / 2, y, pad_w, pad_h))
        if ep:
            w, h = ep
            pads.append({"number": str(count + 1), "x": 0.0, "y": 0.0, "w": w, "h": h,
                         "shape": "rect", "layers": SMD_LAYERS, "net": None, "kind": "smd"})
        return pads
    return build


def sot23():
    return lambda: ("", [rect(1, -0.95, 0.95, 0.9, 0.8), rect(2, 0.95, 0.95, 0.9, 0.8),
                         rect(3, 0.0, -0.95, 0.9, 0.8)])


def sot23_6():
    return lambda: ("", [rect(1, -0.95, 0.95, 0.6, 1.1), rect(2, 0.0, 1.1, 0.6, 1.1),
                         rect(3, 0.95, 0.95, 0.6, 1.1), rect(4, 0.95, -0.95, 0.6, 1.1),
                         rect(5, 0.0, -1.1, 0.6, 1.1), rect(6, -0.95, -0.95, 0.6, 1.1)])


def to263_5():
    return lambda: ("", [rect(1, -3.4, 3.0, 1.0, 2.0), rect(2, -1.7, 3.0, 1.0, 2.0),
                         rect(3, 0.0, 2.2, 4.0, 5.0), rect(4, 1.7, 3.0, 1.0, 2.0),
                         rect(5, 3.4, 3.0, 1.0, 2.0)])


def sot223():
    return lambda: ("", [rect(1, -2.3, 3.0, 1.15, 2.0), rect(2, 0.0, 2.0, 3.6, 4.0),
                         rect(3, 2.3, 3.0, 1.15, 2.0)])


def sma():
    return lambda: ("", [rect(1, -2.0, 0, 1.6, 2.0), rect(2, 2.0, 0, 1.6, 2.0)])


def qfp144():
    """LQFP-144, 0.5 mm pitch, 0.30 x 1.50 mm pads, JEDEC numbering."""
    def build():
        pads = []
        row = 10.75
        span = (36 - 1) * 0.5 / 2.0                   # 8.75
        for index in range(36):
            pads.append(rect(index + 1, -row, span - index * 0.5, 1.5, 0.3))
        for index in range(36):
            pads.append(rect(37 + index, -span + index * 0.5, -row, 0.3, 1.5))
        for index in range(36):
            pads.append(rect(73 + index, row, -span + index * 0.5, 1.5, 0.3))
        for index in range(36):
            pads.append(rect(109 + index, span - index * 0.5, row, 0.3, 1.5))
        return pads
    return build


def osc3225():
    return lambda: ("", [rect(1, -1.0, 0.8, 1.2, 1.0), rect(2, -1.0, -0.8, 1.2, 1.0),
                         rect(3, 1.0, -0.8, 1.2, 1.0), rect(4, 1.0, 0.8, 1.2, 1.0)])


def crystal_hc49():
    """HC49/US through-hole crystal, 4.88 mm lead spacing, matches KiCad
    `Crystal:Crystal_HC49-4H_Vertical` (pads 1.5 mm, 0.8 mm drill)."""
    return lambda: ("", [circle(1, -2.44, 0.0, 1.5, kind="thru_hole",
                               layers='"*.Cu" "*.Mask"', drill=0.8),
                         circle(2, 2.44, 0.0, 1.5, kind="thru_hole",
                               layers='"*.Cu" "*.Mask"', drill=0.8)])


def sot23_5():
    """SOT-23-5 (LP5907): pins 1-3 on one side, 4-5 on the other."""
    return lambda: ("", [rect(1, -0.95, 0.95, 0.9, 0.8), rect(2, 0.0, 1.1, 0.6, 1.1),
                         rect(3, 0.95, 0.95, 0.9, 0.8), rect(4, 0.95, -0.95, 0.9, 0.8),
                         rect(5, -0.95, -0.95, 0.9, 0.8)])


def eia_7343_31():
    """Kemet-D (EIA 7343-31) tantalum: pads at +/-3.1125 mm, 2.075 x 2.55 mm."""
    return lambda: ("", [rect(1, -3.1125, 0.0, 2.075, 2.55),
                         rect(2, 3.1125, 0.0, 2.075, 2.55)])


def usb_c_16():
    """USB-C receptacle, 16 pads: 12 signal (0.5 mm pitch) + 4 shell."""
    def build():
        pads = []
        names = ["A1", "A4", "A5", "A6", "A7", "A8", "A9", "A12",
                 "B1", "B4", "B5", "B6", "B7", "B8", "B9", "B12"]
        for index, name in enumerate(names):
            x = -(len(names) - 1) * 0.5 / 2.0 + index * 0.5
            pads.append(rect(name, x, 3.2, 0.3, 1.2))
        for index, name in enumerate(("S1", "S2", "S3", "S4")):
            x = -3.0 + index * 2.0
            pads.append(rect(name, x, -3.6, 1.2, 2.4))
        return pads
    return build


def pin_header(rows: int, cols: int, pitch: float = 2.54):
    """Through-hole header.  The pad shrinks with the pitch: 1.7 mm at 2.54 mm,
    1.5 mm at 2.00 mm, 0.85 mm at 1.27 mm - a 1.7 mm pad on a 1.27 mm pitch
    would touch its neighbour and cannot be made."""
    pad = min(1.7, round(pitch * 0.67, 2))
    drill = min(1.0, round(pad * 0.6, 2))

    def build():
        pads = []
        number = 1
        for row in range(rows):
            for col in range(cols):
                y = (cols - 1) * pitch / 2 - col * pitch
                x = -(rows - 1) * pitch / 2 + row * pitch if rows > 1 else 0.0
                pads.append(circle(number, x, y, pad, kind="thru_hole",
                                   layers='"*.Cu" "*.Mask"', drill=drill))
                number += 1
        return pads
    return build


def tact_switch():
    return lambda: ("", [circle(1, -3.25, 2.25, 1.8, kind="thru_hole", layers='"*.Cu" "*.Mask"', drill=1.1),
                         circle(2, 3.25, 2.25, 1.8, kind="thru_hole", layers='"*.Cu" "*.Mask"', drill=1.1),
                         circle(3, -3.25, -2.25, 1.8, kind="thru_hole", layers='"*.Cu" "*.Mask"', drill=1.1),
                         circle(4, 3.25, -2.25, 1.8, kind="thru_hole", layers='"*.Cu" "*.Mask"', drill=1.1)])


def barrel_jack():
    return lambda: ("", [circle(1, 0.0, 3.0, 2.4, kind="thru_hole", layers='"*.Cu" "*.Mask"', drill=1.3),
                         circle(2, -4.5, -3.0, 2.4, kind="thru_hole", layers='"*.Cu" "*.Mask"', drill=1.3),
                         circle(3, 4.5, -3.0, 2.4, kind="thru_hole", layers='"*.Cu" "*.Mask"', drill=1.3)])


def test_point():
    return lambda: ("", [circle(1, 0.0, 0.0, 1.0)])


def mounting_hole():
    return lambda: ("", [circle("", 0.0, 0.0, 3.2, kind="np_thru_hole",
                                layers='"*.Cu" "*.Mask"', drill=3.2)])


def fiducial():
    return lambda: ("", [circle(1, 0.0, 0.0, 1.0)])


# ------------------------------------------------------- component definitions
# (ref, KiCad library id, footprint builder, value, group)
COMPONENTS: list[tuple] = [
    ("U1", "Package_QFP:LQFP-144_20x20mm_P0.5mm", qfp144(), "LFE5U-12F-6TG144C", "fpga"),
    ("U2", "Package_SO:SOIC-8_5.23x5.23mm_P1.27mm", soic(8, 1.27, 5.4, 2.0, 0.6), "W25Q64JVSSIQ", "flash"),
    ("U3", "Package_SO:SOIC-8_5.23x5.23mm_P1.27mm", soic(8, 1.27, 5.4, 2.0, 0.6), "W25Q64JVSSIQ", "flash"),
    ("U4", "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm", soic(16, 1.27, 6.0, 2.0, 0.6), "CH340G", "usb"),
    ("U5", "Package_TO_SOT_SMD:SOT-23-6", sot23_6(), "AP62300TWU-7", "power"),
    ("U6", "Package_SO:SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.3mm",
     soic(8, 1.27, 5.4, 2.0, 0.6, ep=(2.41, 3.3)), "MP1584EN", "power"),
    ("U7", "Package_TO_SOT_SMD:SOT-23-5", sot23_5(), "LP5907MFX-2.5", "power"),
    ("U8", "Package_TO_SOT_SMD:SOT-23-6", sot23_6(), "USBLC6-2SC6", "usb"),
    ("Y1", "Oscillator:Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm", osc3225(),
     "25 MHz ACTIVE XO (4-pin)", "fpga"),
    ("Y2", "Crystal:Crystal_HC49-4H_Vertical", crystal_hc49(),
     "12 MHz (CH340G clock)", "usb"),
    ("Q1", "Package_TO_SOT_SMD:SOT-23", sot23(), "2N7002", "jtag"),
    ("Q2", "Package_TO_SOT_SMD:SOT-23", sot23(), "BC817", "jtag"),
    ("Q4", "Package_TO_SOT_SMD:SOT-23", sot23(), "BC807", "jtag"),
    ("D8", "Diode_SMD:D_SMA", sma(), "SS34", "power"),
    ("D9", "Diode_SMD:D_SMA", sma(), "SS34", "power"),
    ("D11", "Diode_SMD:D_SMA", sma(), "SS34", "power"),
    ("L1", "Inductor_SMD:L_Sunlord_MWSA0518_5.4x5.2mm", chip(5.0, 3.4, 2.6), "10 uH", "power"),
    ("L2", "Inductor_SMD:L_Sunlord_MWSA0518_5.4x5.2mm", chip(5.0, 3.4, 2.6), "10 uH", "power"),
    ("FB1", "Inductor_SMD:L_0603_1608Metric", chip(1.575, 0.9, 0.95), "600R @100MHz", "power"),
]

for index, value in enumerate(["D1", "D2", "D3", "D4", "D5", "D6", "D7"]):
    COMPONENTS.append((value, "LED_SMD:LED_0603_1608Metric", chip(1.575, 0.9, 0.95),
                       "LED green" if index < 5 else "LED red", "leds"))

# package per reference, from the cart (hardware/cart/RECONCILED.md section 2)
R_PACKAGE = {
    "R38": ("Resistor_SMD:R_0402_1005Metric", (1.0, 0.6, 0.7)),
    "R9": ("Resistor_SMD:R_1206_3216Metric", (2.9, 1.15, 1.8)),
    "R10": ("Resistor_SMD:R_1206_3216Metric", (2.9, 1.15, 1.8)),
    "R11": ("Resistor_SMD:R_1206_3216Metric", (2.9, 1.15, 1.8)),
    "R12": ("Resistor_SMD:R_1206_3216Metric", (2.9, 1.15, 1.8)),
    "R31": ("Resistor_SMD:R_1206_3216Metric", (2.9, 1.15, 1.8)),
    "R33": ("Resistor_SMD:R_1206_3216Metric", (2.9, 1.15, 1.8)),
    "R34": ("Resistor_SMD:R_1206_3216Metric", (2.9, 1.15, 1.8)),
    "R39": ("Resistor_SMD:R_1206_3216Metric", (2.9, 1.15, 1.8)),
    "R46": ("Resistor_SMD:R_1206_3216Metric", (2.9, 1.15, 1.8)),
    "R47": ("Resistor_SMD:R_1206_3216Metric", (2.9, 1.15, 1.8)),
    "R49": ("Resistor_SMD:R_1206_3216Metric", (2.9, 1.15, 1.8)),
    "R2": ("Resistor_SMD:R_0805_2012Metric", (1.9, 1.0, 1.4)),
    "R3": ("Resistor_SMD:R_0805_2012Metric", (1.9, 1.0, 1.4)),
    "R4": ("Resistor_SMD:R_0805_2012Metric", (1.9, 1.0, 1.4)),
    "R27": ("Resistor_SMD:R_0805_2012Metric", (1.9, 1.0, 1.4)),
    "R28": ("Resistor_SMD:R_0805_2012Metric", (1.9, 1.0, 1.4)),
    "R29": ("Resistor_SMD:R_0805_2012Metric", (1.9, 1.0, 1.4)),
    "R30": ("Resistor_SMD:R_0805_2012Metric", (1.9, 1.0, 1.4)),
    "R36": ("Resistor_SMD:R_0805_2012Metric", (1.9, 1.0, 1.4)),
    "R37": ("Resistor_SMD:R_0805_2012Metric", (1.9, 1.0, 1.4)),
}
R_VALUES = {"R38": "12.4k", "R39": "33k", "R40": "100k", "R41": "100k", "R43": "100k",
            "R45": "10k", "R46": "33k", "R47": "10k", "R48": "100k", "R49": "33k",
            "R36": "5.1k", "R37": "5.1k"}
for index in range(49):          # R1..R49 (R42 not fitted - see the power tree)
    ref = "R%d" % (index + 1)
    if ref == "R42":             # deleted with Q3: the LP5907 EN pin does the delay
        continue
    library, geometry = R_PACKAGE.get(ref, ("Resistor_SMD:R_0603_1608Metric", (1.575, 0.9, 0.95)))
    COMPONENTS.append((ref, library, chip(*geometry), R_VALUES.get(ref, ""), "passives"))
# electrolytics and ceramics, sized to the parts in the cart
C_SPECIAL = {
    "C21": ("Capacitor_Tantalum_SMD:CP_EIA-7343-31_Kemet-D", eia_7343_31, "100uF 25V tant"),
    "C22": ("Capacitor_SMD:CP_Elec_6.3x5.4", lambda: chip(5.9, 1.8, 2.6), "22uF 63V"),
    "C23": ("Capacitor_SMD:CP_Elec_8x10.5", lambda: chip(7.6, 2.0, 3.0), "470uF 25V"),
    "C24": ("Capacitor_SMD:CP_Elec_8x10.5", lambda: chip(7.6, 2.0, 3.0), "220uF 16V"),
    "C38": ("Capacitor_SMD:C_0603_1608Metric", lambda: chip(1.575, 0.9, 0.95), "100nF"),
    "C39": ("Capacitor_SMD:C_0805_2012Metric", lambda: chip(1.9, 1.0, 1.4), "10uF"),
    "C40": ("Capacitor_SMD:C_1206_3216Metric", lambda: chip(2.9, 1.15, 1.8), "22uF"),
    "C41": ("Capacitor_SMD:C_1206_3216Metric", lambda: chip(2.9, 1.15, 1.8), "22uF"),
    "C42": ("Capacitor_SMD:C_0805_2012Metric", lambda: chip(1.9, 1.0, 1.4), "10uF"),
}
for index in range(42):          # C1..C42
    ref = "C%d" % (index + 1)
    if ref in C_SPECIAL:
        library, builder, value = C_SPECIAL[ref]
        COMPONENTS.append((ref, library, builder(), value, "passives"))
    elif ref in ("C25", "C30", "C32"):
        COMPONENTS.append((ref, "Capacitor_SMD:C_0805_2012Metric", chip(1.9, 1.0, 1.4),
                           {"C25": "10uF", "C30": "10uF", "C32": "470nF"}[ref], "passives"))
    else:
        COMPONENTS.append((ref, "Capacitor_SMD:C_0603_1608Metric", chip(1.575, 0.9, 0.95),
                           "100nF" if ref not in ("C31",) else "470nF", "passives"))

COMPONENTS += [
    ("J1", "Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical", pin_header(1, 10), "JTAG", "jtag"),
    ("J2", "Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical", pin_header(2, 5, 1.27), "JTAG-1.27", "jtag"),
    ("J3", "Connector_PinHeader_2.54mm:PinHeader_2x10_P2.54mm_Vertical", pin_header(2, 10), "EXP-A", "expansion"),
    ("J4", "Connector_PinHeader_2.54mm:PinHeader_2x10_P2.54mm_Vertical", pin_header(2, 10), "EXP-B", "expansion"),
    ("J5", "Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical", pin_header(1, 10), "EXP-C", "expansion"),
    ("J6", "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical", pin_header(1, 6), "MOTOR", "expansion"),
    ("J7", "Connector_PinHeader_2.54mm:PinHeader_2x25_P2.54mm_Vertical", pin_header(2, 25), "SPARE (not fitted)", "expansion"),
    ("J8", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", usb_c_16(), "USB-C", "usb"),
    ("J9", "Connector_BarrelJack:BarrelJack_CUI_PJ-102AH_Horizontal", barrel_jack(), "7-12 V", "power"),
    ("J10", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", pin_header(1, 4), "CONSOLE", "expansion"),
    ("SW1", "Button_Switch_THT:SW_PUSH_6mm", tact_switch(), "RESET", "jtag"),
    ("SW2", "Button_Switch_THT:SW_PUSH_6mm", tact_switch(), "RECONFIG", "jtag"),
    ("JP1", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", pin_header(1, 2), "DTR ENABLE", "jtag"),
    ("TP1", "TestPoint:TestPoint_Pad_D1.0mm", test_point(), "3V3", "test"),
    ("TP2", "TestPoint:TestPoint_Pad_D1.0mm", test_point(), "2V5", "test"),
    ("TP3", "TestPoint:TestPoint_Pad_D1.0mm", test_point(), "1V1", "test"),
    ("TP4", "TestPoint:TestPoint_Pad_D1.0mm", test_point(), "GND", "test"),
    ("TP5", "TestPoint:TestPoint_Pad_D1.0mm", test_point(), "DONE", "test"),
    ("TP6", "TestPoint:TestPoint_Pad_D1.0mm", test_point(), "INITN", "test"),
    ("H1", "MountingHole:MountingHole_3.2mm_M3", mounting_hole(), "", "mech"),
    ("H2", "MountingHole:MountingHole_3.2mm_M3", mounting_hole(), "", "mech"),
    ("H3", "MountingHole:MountingHole_3.2mm_M3", mounting_hole(), "", "mech"),
    ("H4", "MountingHole:MountingHole_3.2mm_M3", mounting_hole(), "", "mech"),
    ("FID1", "Fiducial:Fiducial_1mm_Mask2mm", fiducial(), "", "mech"),
    ("FID2", "Fiducial:Fiducial_1mm_Mask2mm", fiducial(), "", "mech"),
    ("FID3", "Fiducial:Fiducial_1mm_Mask2mm", fiducial(), "", "mech"),
    ("FID4", "Fiducial:Fiducial_1mm_Mask2mm", fiducial(), "", "mech"),
]

# ----------------------------------------------------------------- placement
# (ref, x, y, rotation degrees).  Board origin is the top-left corner; KiCad's Y
# axis points down, so this table reads like the board seen from above.
PLACEMENT: dict[str, tuple[float, float, float]] = {
    # power section - top left, away from the FPGA and the motor connector
    "J9": (10, 10, 0), "D8": (16, 8, 90), "D9": (16, 12, 90), "FB1": (22, 10, 0),
    "C23": (28, 8, 0), "U5": (34, 11, 0), "L1": (42, 8, 0),
    "C38": (37, 11, 0), "R46": (37, 14, 0), "R47": (34, 14, 0),
    "R48": (27, 14, 0), "R49": (30, 17, 0), "C39": (30, 12, 0),
    "C40": (46, 11, 0), "C41": (46, 14, 0),
    "C24": (44, 19, 0), "C25": (44, 16, 0), "C21": (30, 24, 0), "C22": (40, 30, 0),
    "C42": (43, 33, 0),
    "U6": (26, 22, 0), "L2": (32, 19, 0), "D11": (32, 27, 90), "C33": (22, 19, 0),
    "R38": (21, 24, 0), "R39": (21, 26, 0), "R40": (21, 28, 0),
    "R41": (25, 30, 0), "C31": (28, 30, 0), "FID3": (8, 36, 0),
    "R45": (23, 22, 0), "C35": (23, 20, 0),
    "R43": (32, 37, 0), "C32": (35, 34, 0),
    "U7": (38, 34, 0), "C30": (60, 19, 0), "TP1": (46, 6, 0), "TP2": (41.5, 27, 0), "TP3": (22, 32, 0),
    # FPGA and its decoupling
    "U1": (52, 52, 0),
    "C2": (34, 46, 0), "C3": (34, 49, 0), "C4": (34, 52, 0), "C5": (34, 55, 0),
    "C6": (34, 58, 0), "C7": (37, 61, 90),
    "C8": (45, 37.5, 0), "C9": (48, 37.5, 0), "C10": (51, 37.5, 0), "C11": (54, 37.5, 0),
    "C12": (67, 46, 0), "C13": (67, 49, 0), "C14": (67, 52, 0), "C15": (67, 55, 0),
    "C16": (67, 58, 0), "C17": (64, 61, 90), "C18": (61, 61, 90), "C19": (58, 61, 90),
    "C20": (43, 61, 90),
    "Y1": (48, 32, 0), "C26": (52, 34, 0), "R9": (44, 73, 0), "R10": (47, 73, 0),
    "R11": (50, 73, 0), "R12": (53, 73, 0), "R8": (41, 73, 0),
    "U2": (60, 34, 0), "C28": (64, 36, 0), "R13": (56, 30, 0), "R14": (58, 30, 0), "R15": (60, 30, 0),
    "U3": (78, 52, 0), "C29": (78, 57, 0), "R16": (74, 46, 0), "R17": (74, 49, 0), "R18": (74, 55, 0),
    # USB and console - bottom right
    "J8": (90, 88, 0), "U8": (83, 88, 0), "U4": (74, 84, 0), "C27": (70, 88, 0),
    "C34": (70, 84, 0),
    # the two USB-C CC pull-downs sit under the connector: the strip between
    # J7's last pad row and J8's shell pads is 1.85 mm and an 0805 needs 1.9 mm
    "R36": (86, 93.5, 0), "R37": (89, 93.5, 0),
    "Y2": (70, 92, 0), "C36": (67, 92, 0), "C37": (73, 92, 0),
    "R21": (70, 79, 0), "R23": (73, 79, 0), "R22": (66, 76, 0), "R24": (69, 76, 0),
    "J10": (62, 88, 0),
    # configuration, reset and status - left
    "J7": (93, 50, 0), "J1": (16, 78, 0), "J2": (10, 88, 0),
    "SW1": (10, 62, 0), "SW2": (20, 62, 0), "R1": (6, 66, 0), "C1": (9, 66, 0),
    "R2": (24, 62, 0), "R3": (24, 66, 0), "R4": (24, 70, 0),
    "R5": (30, 70, 0), "R6": (33, 70, 0), "R7": (36, 70, 0),
    "Q1": (10, 70, 0), "R25": (13, 70, 0), "R26": (10, 73, 0), "JP1": (6, 70, 0) if False else (6, 70, 0),
    "Q2": (26, 80, 0), "R32": (23, 80, 0), "D1": (29, 80, 0), "R33": (32, 80, 0),
    "Q4": (6, 80, 0), "R31": (9, 80, 0), "D6": (12, 80, 0), "R34": (15, 80, 0),
    "D7": (36, 74, 0), "R44": (39, 74, 0), "FID1": (8, 20, 0), "FID2": (92, 14, 0),
    "FID4": (92.5, 93.75, 0),        # moved off the USB-C shell pads (J8)
    # LEDs and expansion - bottom
    "D2": (40, 88, 0), "D3": (43, 88, 0), "D4": (46, 88, 0), "D5": (49, 88, 0),
    "R27": (40, 85, 0), "R28": (43, 85, 0), "R29": (46, 85, 0), "R30": (49, 85, 0),
    "J5": (18, 86.5, 0), "J3": (52, 86.5, 0), "J4": (24, 86.5, 0),
    "J6": (86, 70, 0), "R19": (82, 73, 0),
    "H1": (4, 4, 0), "H2": (96, 4, 0), "H3": (4, 96, 0), "H4": (96, 96, 0),
    "TP4": (55, 6, 0), "TP5": (46, 74, 0), "TP6": (49, 74, 0),
}

# board-level silk labels: (text, x, y, size)
LABELS = [
    ("POWER", 30, 4.5, 2.0), ("FPGA - ECP5 LFE5U-12F", 52, 24, 2.0),
    ("USB + CONSOLE", 78, 94, 2.0), ("JTAG", 16, 84, 2.0),
    ("EXPANSION", 38, 91.0, 2.0), ("MOTOR", 86, 66, 2.0),
    ("CONFIG FLASH", 60, 30, 1.6), ("APP FLASH", 78, 62, 1.6),
    ("FIT U1 LAST - MEASURE RAILS FIRST", 52, 45, 1.6),
]


# ------------------------------------------------------------------- emit file
def pads_of(builder) -> list:
    """Footprint builders return either a pad list or (library_id, pad list)."""
    result = builder()
    return result[1] if isinstance(result, tuple) else result


# ---------------------------------------------------- placement repair pass
# The PLACEMENT table above is the *intent*: which part goes in which cluster.
# Hand-typing 141 coordinates leaves a few parts whose pads overlap a neighbour
# (a short before the board is even routed), so the generator runs a small
# deterministic relaxation over the movable passives before it emits anything:
# a part is nudged along the axis of least overlap until it clears its
# neighbour, and never further than MOVE_LEASH from where the table put it.
#
# Everything downstream - the board file, the preview, the bitmaps, the BOM and
# the CPL - reads effective_placement(), so there is exactly one floorplan.
# Parts that are placed on the board file but deliberately not fitted
# (BOARD.md section 3, PCB_COMPONENTS.md section 8).  Marking them in the file
# keeps the assembly drawing, the BOM and the CPL honest.
DNP_REFS = {"D6", "J7"}
DNP_NOTES = {
    "D6": "INITN indicator - DNP by default",
    "J7": "spare-I/O header - footprint only, not fitted",
}

# The copper plan is built once and shared by the board, the bitmaps and the
# documents (sv16_pcb_copper.build).
_COPPER = None


def copper_plan():
    global _COPPER
    if _COPPER is None:
        placement = effective_placement()
        placed = [(ref, pads_of(builder), *placement[ref])
                  for ref, library, builder, value, group in COMPONENTS
                  if ref in placement]
        nets_by_ref: dict = {}
        for ref, pad, net in CONNECTIONS:
            nets_by_ref.setdefault(ref, {})[pad] = net
        origins = {ref: (x, y) for ref, (x, y, rot) in placement.items()}
        _COPPER = sv16_pcb_copper.build(
            placed, nets_by_ref, origins,
            lambda net: NET_ORDER.index(net) + 1, BOARD_W, BOARD_H)
    return _COPPER


ROUTING_FILE = OUT / "routing.json"


def board_digest() -> str:
    """A short fingerprint of everything the router has to lay copper against.

    The routed tracks are only meaningful for the placement and the copper plan
    they were laid on, so `routing.json` carries this digest and both the board
    generator and the router's `--check` refuse a stale file.
    """
    import hashlib
    h = hashlib.sha256()
    for ref, (x, y, rot) in sorted(effective_placement().items()):
        h.update(("P|%s|%.2f|%.2f|%g\n" % (ref, x, y, rot)).encode())
    for ref, library, builder, value, group in COMPONENTS:
        for pad in pads_of(builder):
            h.update(("D|%s|%s|%.3f|%.3f|%.3f|%.3f|%s|%s\n"
                      % (ref, pad["number"], pad["x"], pad["y"], pad["w"],
                         pad["h"], pad["shape"], pad.get("kind", "smd"))).encode())
    plan = copper_plan()
    for via in plan.vias:
        h.update(("V|%s|%.3f|%.3f|%.3f\n" % (via["net"], via["x"], via["y"], via["dia"])).encode())
    for segment in plan.segments:
        h.update(("S|%s|%s|%.3f|%.3f|%.3f|%.3f|%.2f\n"
                  % (segment["net"], segment["layer"], segment["start"][0],
                     segment["start"][1], segment["end"][0], segment["end"][1],
                     segment["width"])).encode())
    return h.hexdigest()[:16]


_ROUTED = None


def routed_copper():
    """The signal routing (`routing.json`): (segments, vias, digest, stale)."""
    global _ROUTED
    if _ROUTED is None:
        if ROUTING_FILE.exists():
            import json
            data = json.loads(ROUTING_FILE.read_text())
            digest = data.get("board_digest", "")
            _ROUTED = (data.get("segments", []), data.get("vias", []), digest,
                       bool(digest) and digest != board_digest())
        else:
            _ROUTED = ([], [], "", False)
    return _ROUTED


MOVE_LEASH = 9.0            # mm a part may travel from its table position
BOX_MARGIN = 0.55           # mm of courtyard around a footprint's pads
BOX_GAP = 0.30              # mm the boxes must keep apart (= pad clearance + slack)

# Parts that define the floorplan and must not move at all.
FIXED_REFS = {
    "U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8", "Y1", "Y2",
    "J1", "J2", "J3", "J4", "J5", "J6", "J7", "J8", "J9", "J10",
    "SW1", "SW2", "JP1", "H1", "H2", "H3", "H4",
    "FID1", "FID2", "FID3", "FID4",
}


def rotate_point(x: float, y: float, degrees: float):
    """KiCad's footprint rotation, in file coordinates (y grows downwards)."""
    t = math.radians(degrees)
    c, s = math.cos(t), math.sin(t)
    return (x * c + y * s, -x * s + y * c)


def pad_extent(pads: list, x: float, y: float, rot: float):
    """Bounding box of a footprint's pads, in board coordinates."""
    xs, ys = [], []
    for pad in pads:
        for sx in (-0.5, 0.5):
            for sy in (-0.5, 0.5):
                dx, dy = rotate_point(pad["x"] + sx * pad["w"], pad["y"] + sy * pad["h"], rot)
                xs.append(x + dx)
                ys.append(y + dy)
    return (min(xs), min(ys), max(xs), max(ys))


def _boxes(placement: dict) -> dict:
    out = {}
    for ref, library, builder, value, group in COMPONENTS:
        if ref not in placement:
            continue
        x, y, rot = placement[ref]
        x0, y0, x1, y1 = pad_extent(pads_of(builder), x, y, rot)
        out[ref] = [x0 - BOX_MARGIN, y0 - BOX_MARGIN, x1 + BOX_MARGIN, y1 + BOX_MARGIN]
    return out


def _overlaps(first, second) -> bool:
    return (first[0] < second[2] + BOX_GAP and second[0] < first[2] + BOX_GAP
            and first[1] < second[3] + BOX_GAP and second[1] < first[3] + BOX_GAP)


PAD_CLEARANCE = 0.25        # mm that pads of different parts must keep apart


def _pad_shape(entry):
    """(x, y, w, h, is_circle) of a pad entry."""
    return (entry[3], entry[4], entry[5], entry[6], entry[7] == "circle")


def _shape_gap(first, second) -> float:
    """Edge-to-edge gap between two (x, y, w, h, circle) shapes."""
    ax, ay, aw, ah, acircle = first
    bx, by, bw, bh, bcircle = second
    if acircle and bcircle:
        return math.hypot(ax - bx, ay - by) - (aw + bw) / 2.0
    if acircle or bcircle:
        x, y, r, other = (ax, ay, aw / 2.0, second) if acircle else (bx, by, bw / 2.0, first)
        ox, oy, ow, oh, _ = other
        dx = max(abs(x - ox) - ow / 2.0, 0.0)
        dy = max(abs(y - oy) - oh / 2.0, 0.0)
        return math.hypot(dx, dy) - r
    dx = abs(ax - bx) - (aw + bw) / 2.0
    dy = abs(ay - by) - (ah + bh) / 2.0
    if dx <= 0 and dy <= 0:
        return max(dx, dy)
    return math.hypot(max(dx, 0.0), max(dy, 0.0))


def pad_entries(placement: dict) -> list:
    """Every pad on the board: (ref, number, net, x, y, w, h, kind)."""
    nets_by_ref: dict = {}
    for ref, pad, net in CONNECTIONS:
        nets_by_ref.setdefault(ref, {})[str(pad)] = net
    entries = []
    for ref, library, builder, value, group in COMPONENTS:
        if ref not in placement:
            continue
        x, y, rot = placement[ref]
        for pad in pads_of(builder):
            number = str(pad["number"])
            if not number:
                continue                       # mounting holes: no copper
            dx, dy = rotate_point(pad["x"], pad["y"], rot)
            w, h = pad["w"], pad["h"]
            if round(rot) % 180 == 90:
                w, h = h, w
            entries.append((ref, number, nets_by_ref.get(ref, {}).get(number),
                            x + dx, y + dy, w, h, pad["shape"]))
    return entries


def _pad_buckets(entries: list, cell: float = 4.0) -> dict:
    buckets: dict = {}
    for entry in entries:
        x, y, w, h = entry[3:7]
        for gy in range(int((y - h) / cell), int((y + h) / cell) + 1):
            for gx in range(int((x - w) / cell), int((x + w) / cell) + 1):
                buckets.setdefault((gx, gy), []).append(entry)
    return buckets


def _worst_pad_conflict(entries: list):
    """The closest pair of pads that belong to different parts and nets."""
    buckets = _pad_buckets(entries)
    worst = None
    for bucket in buckets.values():
        for index, first in enumerate(bucket):
            for second in bucket[index + 1:]:
                if first[0] == second[0] or first[2] == second[2]:
                    continue
                gap = _shape_gap(_pad_shape(first), _pad_shape(second))
                if worst is None or gap < worst[0]:
                    worst = (gap, first, second)
    return worst


def effective_placement() -> dict:
    """PLACEMENT with the pad overlaps resolved (deterministic; cached)."""
    global _EFFECTIVE
    if _EFFECTIVE is not None:
        return _EFFECTIVE

    moved = {ref: [x, y, rot] for ref, (x, y, rot) in PLACEMENT.items()}
    movable = {ref: ref not in FIXED_REFS for ref in PLACEMENT}

    for _pass in range(400):
        boxes = _boxes({ref: tuple(value) for ref, value in moved.items()})
        clashed = False
        for index, first in enumerate(sorted(boxes)):
            for second in sorted(boxes)[index + 1:]:
                a, b = boxes[first], boxes[second]
                if not _overlaps(a, b):
                    continue
                move_a, move_b = movable[first], movable[second]
                if not move_a and not move_b:
                    continue                  # two anchors: reported, not moved
                overlap_x = min(a[2], b[2]) - max(a[0], b[0])
                overlap_y = min(a[3], b[3]) - max(a[1], b[1])
                share = 0.5 if (move_a and move_b) else 1.0
                if overlap_x < overlap_y:
                    step = overlap_x + BOX_GAP / 2 + 0.05
                    direction = 1.0 if (a[0] + a[2]) > (b[0] + b[2]) else -1.0
                    delta = (direction * step, 0.0)
                else:
                    step = overlap_y + BOX_GAP / 2 + 0.05
                    direction = 1.0 if (a[1] + a[3]) > (b[1] + b[3]) else -1.0
                    delta = (0.0, direction * step)
                # clamp inside the leash around the table position
                for ref, sign in ((first, 1.0), (second, -1.0)):
                    if not (movable[ref] if sign > 0 else movable[second]):
                        continue
                    if sign > 0 and not move_a:
                        continue
                    if sign < 0 and not move_b:
                        continue
                    ox, oy, rot = PLACEMENT[ref]
                    new_x = moved[ref][0] + sign * delta[0] * share
                    new_y = moved[ref][1] + sign * delta[1] * share
                    moved[ref][0] = max(ox - MOVE_LEASH, min(ox + MOVE_LEASH, new_x))
                    moved[ref][1] = max(oy - MOVE_LEASH, min(oy + MOVE_LEASH, new_y))
                clashed = True
        if not clashed:
            break

    # Second pass: the body boxes can be clear while individual pads still
    # touch (a fiducial next to a USB shell, a resistor slid under a header).
    # Parts that are not anchors are nudged to the best spot within 3 mm.
    for _pass in range(40):
        entries = pad_entries({ref: tuple(value) for ref, value in moved.items()})
        worst = _worst_pad_conflict(entries)
        if worst is None or worst[0] >= PAD_CLEARANCE - 1e-9:
            break
        gap, first, second = worst
        if not movable[first[0]] and not movable[second[0]]:
            break                              # two anchors: reported, not moved
        ref = first[0] if movable[first[0]] else second[0]
        x, y, rot = moved[ref]
        others = [entry for entry in entries if entry[0] != ref]
        buckets = _pad_buckets(others)
        best = None
        for dx in [i * 0.25 for i in range(-52, 53)]:
            for dy in [i * 0.25 for i in range(-52, 53)]:
                if abs(dx) + abs(dy) > 6.0:
                    continue
                cx, cy = x + dx, y + dy
                ox, oy, _rot = PLACEMENT[ref]
                if abs(cx - ox) > MOVE_LEASH or abs(cy - oy) > MOVE_LEASH:
                    continue
                if not (2.0 < cx < BOARD_W - 2.0 and 2.0 < cy < BOARD_H - 2.0):
                    continue
                mine = [_pad_shape(entry) for entry in entries if entry[0] == ref]
                for shape in mine:
                    shape = (shape[0] + dx, shape[1] + dy, shape[2], shape[3], shape[4])
                    worst_here = 1e9
                    for entry in others:
                        worst_here = min(worst_here, _shape_gap(shape, _pad_shape(entry)))
                    clear = worst_here >= PAD_CLEARANCE + 0.05
                    # prefer the *nearest* legal spot: a part may only wander as
                    # far as it must, which keeps the floorplan readable
                    key = ((abs(dx) + abs(dy)) if clear else (100.0 - worst_here))
                    if not clear:
                        key += 1000.0
                    if best is None or key < best[0] - 1e-9:
                        best = (key, worst_here, dx, dy)
        if best is None or best[1] <= gap + 1e-9:
            break                              # nothing better: report it instead
        moved[ref][0] = round(x + best[2], 2)
        moved[ref][1] = round(y + best[3], 2)

    _EFFECTIVE = {ref: (round(x, 2), round(y, 2), rot)
                  for ref, (x, y, rot) in moved.items()}
    return _EFFECTIVE


_EFFECTIVE: dict | None = None


def placement_conflicts(placement: dict | None = None) -> list:
    """Pad-level clearance problems that survive the repair pass, worst first.

    Pads of different parts (and of different nets) must keep PAD_CLEARANCE
    apart - that is 0.05 mm more than the copper clearance the router uses, so
    a placement that passes here always leaves the router its room.
    """
    placement = placement or effective_placement()
    entries = pad_entries(placement)
    buckets = _pad_buckets(entries)
    conflicts = []
    seen = set()
    for bucket in buckets.values():
        for index, first in enumerate(bucket):
            for second in bucket[index + 1:]:
                if first[0] == second[0] or first[2] == second[2]:
                    continue
                key = (first[0], first[1], second[0], second[1])
                if key in seen:
                    continue
                seen.add(key)
                gap = _shape_gap(_pad_shape(first), _pad_shape(second))
                if gap < PAD_CLEARANCE - 1e-9:
                    conflicts.append("%s.%s (%s) / %s.%s (%s): %.3f mm"
                                     % (first[0], first[1], first[2] or "no net",
                                        second[0], second[1], second[2] or "no net", gap))
    return sorted(conflicts)


def net_number(net: str) -> int:
    return NET_ORDER.index(net) + 1


def pad_sexp(pad: dict, indent: str) -> str:
    layers = pad["layers"]
    net = pad.get("net")
    net_text = ""
    if net:
        net_text = " (net %d %s)" % (net_number(net), '"%s"' % net)
    if pad["kind"] == "np_thru_hole":
        return ("%s(pad \"\" np_thru_hole circle (at %.3f %.3f) (size %.3f %.3f) (drill %.3f) "
                "(layers %s)%s)" % (indent, pad["x"], pad["y"], pad["w"], pad["h"], pad["drill"],
                                    layers, net_text))
    if pad["kind"] == "thru_hole":
        return ("%s(pad \"%s\" thru_hole circle (at %.3f %.3f) (size %.3f %.3f) (drill %.3f) "
                "(layers %s)%s)" % (indent, pad["number"], pad["x"], pad["y"], pad["w"], pad["h"],
                                    pad["drill"], layers, net_text))
    if pad["shape"] == "circle":
        return ("%s(pad \"%s\" smd circle (at %.3f %.3f) (size %.3f %.3f) (layers %s)%s)"
                % (indent, pad["number"], pad["x"], pad["y"], pad["w"], pad["h"], layers, net_text))
    return ("%s(pad \"%s\" smd rect (at %.3f %.3f) (size %.3f %.3f) (layers %s)%s)"
            % (indent, pad["number"], pad["x"], pad["y"], pad["w"], pad["h"], layers, net_text))


def build_board() -> str:
    nets_in_use = {net for _, _, net in CONNECTIONS}
    unknown = nets_in_use - set(NET_ORDER)
    if unknown:
        raise SystemExit("nets used but not declared: %s" % sorted(unknown))

    lines = [
        "(kicad_pcb (version 20221018) (generator sv16_board_kicad.py)",
        "",
        "  (general",
        "    (thickness 1.6)",
        "  )",
        "  (paper \"A3\")",
        "  (title_block",
        "    (title \"SV-16 microcontroller - ECP5 LFE5U-12F-6TG144C\")",
        "    (date \"%s\")" % __import__("datetime").date.today().isoformat(),
        "    (rev \"1.3\")",
        "    (company \"SV-16 project\")",
        "    (comment 1 \"100 x 100 mm, 4 layers: signal / GND / PWR / signal\")",
        "    (comment 2 \"Generated by scripts/sv16_board_kicad.py - run make kicad-board to refresh\")",
        "  )",
        "  (layers",
        "    (0 \"F.Cu\" signal)",
        "    (1 \"In1.Cu\" power)",
        "    (2 \"In2.Cu\" power)",
        "    (31 \"B.Cu\" signal)",
        "    (34 \"B.Paste\" user)",
        "    (35 \"F.Paste\" user)",
        "    (36 \"B.SilkS\" user \"B.Silkscreen\")",
        "    (37 \"F.SilkS\" user \"F.Silkscreen\")",
        "    (38 \"B.Mask\" user)",
        "    (39 \"F.Mask\" user)",
        "    (44 \"Edge.Cuts\" user)",
        "    (48 \"B.Fab\" user)",
        "    (49 \"F.Fab\" user)",
        "  )",
        "  (setup",
        "    (pad_to_mask_clearance 0.05)",
        "    (grid_origin 0 0)",
        "  )",
    ]
    for index, net in enumerate(NET_ORDER):
        lines.append("  (net %d \"%s\")" % (index + 1, net))
    lines.append("")

    # net classes
    classes = [
        ("Default", "0.25", "0.2", ["\"*\""]),
        ("Power", "0.8", "0.25", ["\"GND\"", "\"VM_IN\"", "\"VM_IN_RAW\"", "\"3V3\"", "\"2V5\"", "\"1V1\"", "\"USB_VBUS\"", "\"5V_USB\""]),
        ("Switching", "0.8", "0.5", ["\"U5_SW\"", "\"U5_BST\"", "\"U6_SW\"", "\"U6_BST\""]),
        ("USB", "0.25", "0.2", ["\"USB_DP\"", "\"USB_DN\"", "\"USB_DP_F\"", "\"USB_DN_F\"", "\"CC1\"", "\"CC2\""]),
        ("JTAG", "0.25", "0.25", ["\"TCK\"", "\"TMS\"", "\"TDI\"", "\"TDO\"", "\"PROGRAMN\"", "\"INITN\"", "\"DONE\"", "\"CCLK\""]),
    ]
    for name, width, clearance, members in classes:
        lines.append("  (net_class \"%s\" \"\" (clearance %.2f) (trace_width %s) (via_dia 0.8) "
                     "(via_drill 0.4) (uvia_dia 0.3) (uvia_drill 0.1)" % (name, float(clearance), width))
        for member in members:
            lines.append("    (add_net %s)" % member)
        lines.append("  )")
    lines.append("")

    # board outline
    for x1, y1, x2, y2 in ((0, 0, BOARD_W, 0), (BOARD_W, 0, BOARD_W, BOARD_H),
                           (BOARD_W, BOARD_H, 0, BOARD_H), (0, BOARD_H, 0, 0)):
        lines.append("  (gr_line (start %.2f %.2f) (end %.2f %.2f) (layer \"Edge.Cuts\") "
                     "(width 0.1))" % (x1, y1, x2, y2))
    for ref, note in sorted(DNP_NOTES.items()):
        if ref in effective_placement():
            x, y, rot = effective_placement()[ref]
            lines.append("  (gr_text \"DNP - %s\" (at %.2f %.2f) (layer \"F.SilkS\") "
                         "(effects (font (size 1.0 1.0) (thickness 0.15))))"
                         % (ref, x, y + 2.4))
    for text, x, y, size in LABELS:
        lines.append("  (gr_text \"%s\" (at %.2f %.2f) (layer \"F.SilkS\") "
                     "(effects (font (size %.1f %.1f) (thickness 0.2))))" % (text, x, y, size, size))
    lines.append("")

    # ground planes.  The stack-up (BOARD.md section 14) is
    # signal / solid GND / solid PWR / signal, so the plane goes on In1.Cu and
    # the bottom signal layer gets a pour as well.  KiCad fills them on the
    # first "Fill All Zones" (B) - the polygons below are the outlines only.
    gnd = NET_ORDER.index("GND") + 1
    zone_id = 0
    for layer, inset in (("In1.Cu", 0.25), ("B.Cu", 0.5)):
        zone_id += 1
        x0, y0, x1, y1 = inset, inset, BOARD_W - inset, BOARD_H - inset
        lines.append("  (zone (net %d) (net_name \"GND\") (layer \"%s\") " % (gnd, layer))
        lines.append("    (uuid 5f16b0a%d-0000-4000-8000-00000000000%d) (hatch edge 0.5)" % (zone_id, zone_id))
        lines.append("    (connect_pads (clearance 0.5))")
        lines.append("    (min_thickness 0.25) (filled_areas_thickness no)")
        lines.append("    (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))")
        lines.append("    (polygon")
        lines.append("      (pts")
        lines.append("        (xy %.2f %.2f) (xy %.2f %.2f) (xy %.2f %.2f) (xy %.2f %.2f)"
                     % (x0, y0, x1, y0, x1, y1, x0, y1))
        lines.append("      )")
        lines.append("    )")
        lines.append("  )")

    # the rail pours on In2.Cu, from sv16_pcb_copper.py.  KiCad resolves the
    # overlaps by priority, so the polygons may intersect and DRC stays clean.
    for net, priority, polygons in sv16_pcb_copper.POURS:
        zone_id += 1
        lines.append("  (zone (net %d) (net_name \"%s\") (layer \"In2.Cu\") "
                     % (net_number(net), net))
        lines.append("    (uuid 5f16b0b%d-0000-4000-8000-00000000000%d) (hatch edge 0.5)"
                     % (zone_id, zone_id))
        if priority:
            lines.append("    (priority %d)" % priority)
        lines.append("    (connect_pads (clearance 0.3))")
        lines.append("    (min_thickness 0.25) (filled_areas_thickness no)")
        lines.append("    (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))")
        lines.append("    (polygon")
        lines.append("      (pts")
        for polygon in polygons:
            for index in range(0, len(polygon), 4):
                chunk = polygon[index:index + 4]
                lines.append("        " + " ".join("(xy %.2f %.2f)" % (x, y) for x, y in chunk))
        lines.append("      )")
        lines.append("    )")
        lines.append("  )")
    lines.append("")

    # escape vias, stubs and stitching, from the same module.  These are the
    # "via first at the pad" part of the fan-out; every one of them was checked
    # against every other pad before it was written.
    copper = copper_plan()
    for via in copper.vias:
        lines.append("  (via (at %.3f %.3f) (size %.2f) (drill %.2f) (layers \"F.Cu\" \"B.Cu\") "
                     "(net %d) (uuid 5f16b0c0-0000-4000-8000-%012d))"
                     % (via["x"], via["y"], via["dia"], via["drill"],
                        net_number(via["net"]), len(lines)))
    for index, segment in enumerate(copper.segments):
        lines.append("  (segment (start %.3f %.3f) (end %.3f %.3f) (width %.2f) "
                     "(layer \"%s\") (net %d) (uuid 5f16b0d0-0000-4000-8000-%012d))"
                     % (segment["start"][0], segment["start"][1], segment["end"][0],
                        segment["end"][1], segment["width"], segment["layer"],
                        net_number(segment["net"]), index))

    # and the signal routing: every track and via the maze router laid, with a
    # different uuid prefix so the two sets stay tellable apart
    routed_segments, routed_vias, _digest, _stale = routed_copper()
    for index, via in enumerate(routed_vias):
        lines.append("  (via (at %.3f %.3f) (size %.2f) (drill %.2f) (layers \"F.Cu\" \"B.Cu\") "
                     "(net %d) (uuid 5f16b0e0-0000-4000-8000-%012d))"
                     % (via["x"], via["y"], via["size"], via["drill"],
                        net_number(via["net"]), index))
    for index, segment in enumerate(routed_segments):
        lines.append("  (segment (start %.3f %.3f) (end %.3f %.3f) (width %.2f) "
                     "(layer \"%s\") (net %d) (uuid 5f16b0f0-0000-4000-8000-%012d))"
                     % (segment["start"][0], segment["start"][1], segment["end"][0],
                        segment["end"][1], segment["width"], segment["layer"],
                        net_number(segment["net"]), index))
    lines.append("")

    # connections grouped by reference
    by_ref: dict[str, dict[str, str]] = {}
    for ref, pad, net in CONNECTIONS:
        by_ref.setdefault(ref, {})[pad] = net

    placement = effective_placement()
    placed = set()
    for ref, library, builder, value, group in COMPONENTS:
        if ref not in placement:
            continue
        placed.add(ref)
        x, y, rot = placement[ref]
        pads = pads_of(builder)
        attr = "through_hole" if any(pad["kind"] in ("thru_hole", "np_thru_hole")
                                     for pad in pads) else "smd"
        if ref in DNP_REFS:
            # KiCad 7's "do not populate" and BOM/CPL exclusions, so the fab and
            # the pick-and-place file agree with BOARD.md section 3
            attr += " dnp exclude_from_pos_files exclude_from_bom"
        lines.append("  (footprint \"%s\" (layer \"F.Cu\") (at %.2f %.2f %d) (attr %s)"
                     % (library, x, y, int(rot), attr))
        lines.append("    (fp_text reference \"%s\" (at 0 -1.6) (layer \"F.SilkS\") "
                     "(effects (font (size 0.8 0.8) (thickness 0.15))))" % ref)
        lines.append("    (fp_text value \"%s\" (at 0 1.6) (layer \"F.Fab\") "
                     "(effects (font (size 0.8 0.8) (thickness 0.15))))" % (value or ref))
        if pads:
            xs = [p["x"] for p in pads]
            ys = [p["y"] for p in pads]
            x0, x1 = min(xs) - 0.6, max(xs) + 0.6
            y0, y1 = min(ys) - 0.6, max(ys) + 0.6
            if (x1 - x0) > 0.9 and (y1 - y0) > 0.9:
                for layer, width in (("F.SilkS", 0.12), ("F.Fab", 0.1)):
                    lines.append("    (fp_rect (start %.2f %.2f) (end %.2f %.2f) (layer \"%s\") "
                                 "(stroke (width %.2f) (type solid)) (fill none))"
                                 % (x0, y0, x1, y1, layer, width))
        nets = by_ref.get(ref, {})
        for pad in pads:
            pad = dict(pad)
            if pad["number"]:
                pad["net"] = nets.get(pad["number"])
            lines.append(pad_sexp(pad, "    "))
        lines.append("  )")
    lines.append(")")

    missing = set(PLACEMENT) - placed
    if missing:
        raise SystemExit("placement without a component definition: %s" % sorted(missing))
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ validation
def check(text: str) -> int:
    problems = 0
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                print("FAIL: unbalanced ')' at offset %d" % index)
                return 1
    if depth != 0:
        print("FAIL: %d unclosed parentheses" % depth)
        problems += 1

    footprints = re.findall(r'\(footprint "([^"]+)"', text)
    pads = re.findall(r"\(pad ", text)
    nets = re.findall(r'^  \(net (\d+) "([^"]*)"\)', text, re.M)
    with_net = re.findall(r"\(pad \"[^\"]*\"[^\n]*?\(net \d+ \"[^\"]+\"\)", text)
    print("  footprints: %d" % len(footprints))
    print("  pads:       %d (%d with a net)" % (len(pads), len(with_net)))
    print("  nets:       %d declared" % len(nets))

    names = [name for _, name in nets]
    net_dupes = {name for name in names if names.count(name) > 1}
    if net_dupes:
        print("  FAIL: duplicate net declarations: %s" % sorted(net_dupes))
        problems += 1
    zones = re.findall(r'\(zone \(net \d+\) \(net_name "([^"]+)"\) \(layer "([^"]+)"\)', text)
    if zones:
        print("  zones:      %s" % ", ".join("%s on %s" % (name, layer) for name, layer in zones))

    refs = re.findall(r'\(fp_text reference "([^"]+)"', text)
    duplicates = {ref for ref in refs if refs.count(ref) > 1}
    if duplicates:
        print("  FAIL: duplicate references: %s" % sorted(duplicates))
        problems += 1

    # every connection must land on a pad that exists
    pads_by_ref: dict[str, set[str]] = {}
    for block in re.finditer(r'\(footprint "[^"]+"[^\n]*\n(.*?)\n  \)', text, re.S):
        body = block.group(1)
        ref_match = re.search(r'\(fp_text reference "([^"]+)"', body)
        if not ref_match:
            continue
        numbers = set(re.findall(r'\(pad "([^"]*)"', body))
        pads_by_ref[ref_match.group(1)] = numbers
    for ref, pad, net in CONNECTIONS:
        if ref not in pads_by_ref:
            print("  FAIL: %s has no footprint" % ref)
            problems += 1
        elif pad not in pads_by_ref[ref]:
            print("  FAIL: %s has no pad %s (net %s)" % (ref, pad, net))
            problems += 1

    # the copper the generator planned must still be verifiable from the file
    vias = re.findall(r'^  \(via \(at ([\d.]+) ([\d.]+)\) \(size ([\d.]+)\) \(drill ([\d.]+)\)',
                      text, re.M)
    segments = re.findall(r'^  \(segment ', text, re.M)
    inner_zones = re.findall(r'\(zone \(net \d+\) \(net_name "(3V3|2V5|1V1)"\) \(layer "In2.Cu"\)', text)
    routed_segments, routed_vias, digest, stale = routed_copper()
    copper = copper_plan()
    print("  vias:       %d (%d planned + %d routed)"
          % (len(vias), len(copper.vias), len(routed_vias)))
    print("  segments:   %d (%d stubs + %d routed)"
          % (len(segments), len(copper.segments), len(routed_segments)))
    if not inner_zones:
        print("  note: no rail pours on In2.Cu")
    if len(vias) != len(copper.vias) + len(routed_vias) \
            or len(segments) != len(copper.segments) + len(routed_segments):
        print("  FAIL: the copper in the file does not match the plan "
              "(%d/%d vias, %d/%d segments)"
              % (len(vias), len(copper.vias) + len(routed_vias), len(segments),
                 len(copper.segments) + len(routed_segments)))
        problems += 1
    if stale:
        print("  FAIL: routing.json was laid on a different board (digest %s, now %s)"
              % (digest, board_digest()))
        problems += 1
    for routed_via in routed_vias:
        if not (0 < routed_via["x"] < BOARD_W and 0 < routed_via["y"] < BOARD_H):
            print("  FAIL: routed via %s off the board" % routed_via["net"])
            problems += 1
    placed = [(ref, pads_of(builder), *effective_placement()[ref])
              for ref, library, builder, value, group in COMPONENTS
              if ref in effective_placement()]
    nets_by_ref: dict = {}
    for ref, pad, net in CONNECTIONS:
        nets_by_ref.setdefault(ref, {})[pad] = net
    problems += sv16_pcb_copper.verify(copper, placed, nets_by_ref)
    for conflict in placement_conflicts():
        print("  FAIL: placement conflict %s" % conflict)
        problems += 1

    # summary of nets with the fewest connections - a quick sanity look
    counts: dict[str, int] = {}
    for _, _, net in CONNECTIONS:
        counts[net] = counts.get(net, 0) + 1
    singles = sorted(net for net, count in counts.items() if count < 2)
    if singles:
        print("  note: nets with a single connection (check these): %s" % singles)
    print("  %s" % ("OK" if problems == 0 else "FAILED"))
    return problems


PROJECT_FILE = OUT / "sv16_board.kicad_pro"

PROJECT_NETCLASSES = [
    ("Default", 0.20, 0.25, 0.80, 0.40),
    ("Power", 0.25, 0.80, 1.00, 0.50),
    ("Switching", 0.50, 0.80, 1.00, 0.50),
    ("USB", 0.20, 0.25, 0.80, 0.40),
    ("JTAG", 0.25, 0.25, 0.80, 0.40),
]


def write_project() -> None:
    """A minimal KiCad 7 project file: net classes with the widths the router
    should start from (PCB_COMPONENTS.md section 7), USB as a 90 ohm pair."""
    import json

    classes = []
    for name, clearance, width, via_dia, via_drill in PROJECT_NETCLASSES:
        classes.append({
            "bus_width": 12,
            "clearance": clearance,
            "diff_pair_gap": 0.2,
            "diff_pair_via_gap": 0.25,
            "diff_pair_width": 0.2,
            "line_style": 0,
            "microvia_diameter": 0.3,
            "microvia_drill": 0.1,
            "name": name,
            "pcb_color": "rgba(0, 0, 0, 0.000)",
            "priority": 0,
            "schematic_color": "rgba(0, 0, 0, 0.000)",
            "track_width": width,
            "via_diameter": via_dia,
            "via_drill": via_drill,
            "wire_width": 6,
        })
    project = {
        "board": {
            "design_settings": {
                "defaults": {"board_outline_line_width": 0.1, "silk_line_width": 0.12,
                             "copper_line_width": 0.2},
                "diff_pair_dimensions": [],
                "drc_exclusions": [],
                "rules": {"min_clearance": 0.2, "min_track_width": 0.2,
                          "min_through_hole_diameter": 0.3, "min_via_diameter": 0.5,
                          "min_via_annular_width": 0.13},
                "track_widths": [0.2, 0.25, 0.5, 0.8, 1.0],
                "via_dimensions": [{"diameter": 0.8, "drill": 0.4},
                                   {"diameter": 1.0, "drill": 0.5}],
            },
            "layer_presets": [],
            "viewports": [],
        },
        "boards": [],
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": "sv16_board.kicad_pro", "version": 1},
        "net_settings": {"classes": classes, "meta": {"version": 3}, "net_colors": None},
        "pcbnew": {"last_paths": {}, "page_layout_descr_file": ""},
        "schematic": {"annotate_start_num": 0, "drawing": {}, "legacy_lib_dir": "",
                      "legacy_lib_list": [], "meta": {"version": 1},
                      "page_layout_descr_file": "", "spice_external_command": "spice \"%I\"",
                      "subpart_first_id": 65, "subpart_id_separator": 0},
        "sheets": [],
        "text_variables": {},
    }
    PROJECT_FILE.write_text(json.dumps(project, indent=2) + "\n")
    print("wrote %s" % PROJECT_FILE.relative_to(ROOT))


def draw_preview() -> None:
    """Placement + ratsnest preview so the floorplan can be judged at a glance.

    Optional: needs Pillow.  The board file itself has no third-party dependency.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("note: Pillow not installed - skipping the preview PNG "
              "(python3 -m pip install pillow)")
        return

    scale = 9
    size = int(BOARD_W * scale)
    image = Image.new("RGB", (size, size), "#0e1116")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, size - 1, size - 1], outline="#4b5563", width=2)

    placement = effective_placement()
    pads: dict[str, list[tuple[float, float, str]]] = {}
    for ref, library, builder, value, group in COMPONENTS:
        if ref not in placement:
            continue
        x, y, rot = placement[ref]
        nets = {pad: net for r, pad, net in CONNECTIONS if r == ref}
        entries = []
        for pad in pads_of(builder):
            entries.append((x + pad["x"], y + pad["y"], nets.get(pad["number"])))
        pads[ref] = entries

    # ratsnest: same net, straight line
    for net in NET_ORDER:
        points = [(px, py) for ref in pads for px, py, pnet in pads[ref] if pnet == net]
        for first, second in zip(points, points[1:]):
            colour = "#3b82f6" if net == "GND" else "#f59e0b" if net in POWER_NETS else "#6b7280"
            draw.line([first[0] * scale, first[1] * scale,
                       second[0] * scale, second[1] * scale], fill=colour, width=1)

    colours = {"fpga": "#22c55e", "power": "#ef4444", "flash": "#a855f7", "usb": "#06b6d4",
               "jtag": "#eab308", "expansion": "#f472b6", "leds": "#84cc16",
               "passives": "#9ca3af", "test": "#e5e7eb", "mech": "#374151"}
    for ref, library, builder, value, group in COMPONENTS:
        if ref not in placement:
            continue
        cx, cy = placement[ref][0] * scale, placement[ref][1] * scale
        half = 40 if group == "fpga" else 12
        draw.rectangle([cx - half, cy - half, cx + half, cy + half],
                       outline=colours.get(group, "#9ca3af"), width=2)
        if group in ("fpga", "power", "usb", "jtag", "flash"):
            draw.text((cx - half, cy - half - 10), ref, fill=colours.get(group, "#fff"))
    image.save(OUT / "placement_preview.png")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only verify the file on disk")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    if not args.check:
        text = build_board()
        BOARD_FILE.write_text(text)
        print("wrote %s (%d lines, %.0f KB)" % (BOARD_FILE.relative_to(ROOT),
                                                text.count("\n"), len(text) / 1024.0))
        write_project()
        draw_preview()
        copper = copper_plan()
        print("  copper plan: %d vias, %d stub tracks, %d zones"
              % (len(copper.vias), len(copper.segments),
                 2 + len(sv16_pcb_copper.POURS)))
        for note in copper.notes:
            print("  note: %s" % note)
        moved = [ref for ref in PLACEMENT
                 if (PLACEMENT[ref][0], PLACEMENT[ref][1]) !=
                 effective_placement()[ref][:2]]
        if moved:
            print("  placement repair moved %d part(s): %s"
                  % (len(moved), " ".join(sorted(moved))))
        for conflict in placement_conflicts():
            print("  PLACEMENT CONFLICT: %s" % conflict)
    else:
        text = BOARD_FILE.read_text()
        print("checking %s" % BOARD_FILE.relative_to(ROOT))
    return check(text)


if __name__ == "__main__":
    sys.exit(main())
