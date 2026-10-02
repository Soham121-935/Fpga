#!/usr/bin/env python3
"""Generate a KiCad board file (.kicad_pcb) for the SV-16 microcontroller.

This is a *starting point* for layout, not a finished board.  It contains:

  * the 122 x 122 mm, 4-layer board outline on Edge.Cuts, four mounting holes
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTING_FILE = ROOT / "hardware" / "sv16_board" / "routing.kicad_pcb.txt"
NO_ROUTING = False
OUT = ROOT / "hardware" / "sv16_board"
BOARD_FILE = OUT / "sv16_board.kicad_pcb"

BOARD_W, BOARD_H = 122.0, 122.0
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
    """LQFP-144, 0.5 mm pitch, 0.25 x 1.50 mm pads, JEDEC numbering.

    0.25 mm is the JEDEC land pattern for this package (the leads are 0.17-0.27 mm
    wide) and it leaves a 0.25 mm gap between pads, which is what makes the
    0.5 mm pitch fan-out - one 0.30 mm via per pin, staggered - possible.
    """
    def build():
        pads = []
        row = 10.75
        span = (36 - 1) * 0.5 / 2.0                   # 8.75
        for index in range(36):
            pads.append(rect(index + 1, -row, span - index * 0.5, 1.5, 0.25))
        for index in range(36):
            pads.append(rect(37 + index, -span + index * 0.5, -row, 0.25, 1.5))
        for index in range(36):
            pads.append(rect(73 + index, row, -span + index * 0.5, 1.5, 0.25))
        for index in range(36):
            pads.append(rect(109 + index, span - index * 0.5, row, 0.25, 1.5))
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
    def build():
        pads = []
        number = 1
        for row in range(rows):
            for col in range(cols):
                y = (cols - 1) * pitch / 2 - col * pitch
                x = -(rows - 1) * pitch / 2 + row * pitch if rows > 1 else 0.0
                pads.append(circle(number, x, y, 1.7, kind="thru_hole",
                                   layers='"*.Cu" "*.Mask"', drill=1.0))
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
     soic(8, 1.27, 5.4, 2.0, 0.6, ep=(3.3, 2.41)), "MP1584EN", "power"),
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
    "J9": (24.10, 24.10, 0), "D8": (34.62, 22.17, 90), "D9": (31.87, 26.18, 90), "FB1": (35.61, 26.10, 0),
    "C23": (42.18, 23.12, 0), "U5": (48.88, 25.78, 0), "L1": (54.58, 22.17, 0),
    "C38": (52.11, 25.10, 0), "R46": (52.90, 28.02, 0), "R47": (51.90, 32.02, 0),
    "R48": (41.11, 20.60, 0), "R49": (44.15, 26.28, 0), "C39": (40.07, 27.32, 0),
    "C40": (60.15, 25.02, 0), "C41": (60.15, 30.02, 0),
    "C24": (49.17, 35.12, 0), "C25": (58.08, 27.82, 0), "C21": (50.52, 38.65, 0), "C22": (51.98, 41.92, 0),
    "C42": (54.58, 44.57, 0),
    "U6": (39.70, 38.70, 0), "L2": (45.07, 30.18, 0), "D11": (45.38, 43.42, 90), "C33": (36.11, 31.60, 0),
    "R38": (34.18, 41.98, 0), "R39": (32.90, 38.02, 0), "R40": (33.61, 40.60, 0),
    "R41": (38.61, 44.10, 0), "C31": (42.11, 44.10, 0), "FID3": (22.10, 50.10, 0),
    "R45": (37.11, 35.10, 0), "C35": (37.11, 33.60, 0),
    "R43": (46.11, 51.10, 0), "C32": (48.58, 48.08, 0),
    "U7": (52.53, 47.98, 0), "C30": (55.08, 51.08, 0), "TP1": (60.10, 20.10, 0), "TP2": (63.10, 20.10, 0), "TP3": (66.10, 20.10, 0),
    # FPGA and its decoupling
    "U1": (66.10, 66.10, 0),
    "C2": (48.11, 60.10, 0), "C3": (48.11, 72.10, 0), "C4": (48.11, 70.60, 0), "C5": (48.11, 69.10, 0),
    "C6": (48.11, 67.60, 0), "C7": (51.10, 75.11, 90),
    "C8": (58.61, 47.10, 0), "C9": (62.61, 48.10, 0), "C10": (66.11, 47.10, 0), "C11": (69.11, 45.60, 0),
    "C12": (81.61, 60.10, 0), "C13": (81.61, 63.10, 0), "C14": (81.61, 66.10, 0), "C15": (81.61, 69.10, 0),
    "C16": (81.61, 72.10, 0), "C17": (82.35, 75.11, 90), "C18": (80.85, 78.36, 90), "C19": (80.85, 75.11, 90),
    "C20": (51.35, 71.86, 90),
    "Y1": (62.48, 45.18, 0), "C26": (58.61, 44.10, 0), "R9": (58.15, 83.53, 0), "R10": (56.65, 86.03, 0),
    "R11": (60.65, 90.28, 0), "R12": (68.15, 85.78, 0), "R8": (55.11, 88.60, 0),
    "U2": (75.20, 48.20, 0), "C28": (81.11, 51.35, 0), "R13": (69.61, 44.10, 0), "R14": (72.61, 42.60, 0), "R15": (74.11, 44.35, 0),
    "U3": (93.20, 66.70, 0), "C29": (92.11, 71.10, 0), "R16": (88.11, 60.10, 0), "R17": (88.11, 62.60, 0), "R18": (87.11, 69.10, 0),
    # USB and console - bottom right
    "J8": (104.10, 102.10, 0), "U8": (97.12, 102.02, 0), "U4": (88.00, 108.00, 0), "C27": (81.61, 103.35, 0),
    "C34": (84.11, 98.10, 0), "R36": (102.08, 95.58, 0), "R37": (105.08, 107.58, 0),
    "Y2": (84.06, 101.38, 0), "C36": (80.61, 99.60, 0), "C37": (89.11, 101.85, 0),
    "R21": (84.11, 93.10, 0), "R23": (87.36, 93.10, 0), "R22": (80.11, 90.10, 0), "R24": (83.36, 90.10, 0),
    "J10": (76.10, 102.10, 0),
    # configuration, reset and status - left
    "J7": (17.10, 66.10, 0), "J1": (30.10, 92.10, 0), "J2": (32.90, 86.10, 0),
    "SW1": (24.10, 76.10, 0), "SW2": (34.10, 76.10, 0), "R1": (21.61, 69.85, 0), "C1": (23.11, 71.35, 0),
    "R2": (38.07, 84.08, 0), "R3": (38.07, 82.08, 0), "R4": (40.82, 80.08, 0),
    "R5": (43.61, 84.10, 0), "R6": (47.11, 84.10, 0), "R7": (50.61, 84.10, 0),
    "Q1": (23.02, 83.98, 0), "R25": (24.86, 86.60, 0), "R26": (21.61, 87.10, 0), "JP1": (25.98, 82.49, 0) if False else (19.84, 72.30, 0),
    "Q2": (44.77, 92.48, 0), "R32": (35.36, 94.10, 0), "D1": (44.61, 97.60, 0), "R33": (46.65, 95.53, 0),
    "Q4": (21.78, 93.98, 0), "R31": (22.40, 97.03, 0), "D6": (24.86, 89.10, 0), "R34": (24.15, 91.03, 0),
    "D7": (50.11, 88.10, 0), "R44": (52.61, 86.60, 0), "FID1": (22.10, 34.10, 0), "FID2": (106.10, 34.10, 0),
    "FID4": (106.10, 84.10, 0),
    # LEDs and expansion - bottom
    "D2": (50.11, 103.60, 0), "D3": (53.61, 103.60, 0), "D4": (57.11, 103.60, 0), "D5": (60.61, 103.60, 0),
    "R27": (50.08, 100.58, 0), "R28": (53.58, 100.58, 0), "R29": (57.08, 100.58, 0), "R30": (60.58, 100.58, 0),
    "J5": (28.10, 98.10, 0), "J3": (66.10, 100.10, 0), "J4": (40.10, 100.10, 0),
    "J6": (100.10, 84.10, 0), "R19": (96.11, 87.10, 0),
    "H1": (18.10, 18.10, 0), "H2": (110.10, 18.10, 0), "H3": (18.10, 110.10, 0), "H4": (110.10, 110.10, 0),
    "TP4": (69.10, 20.10, 0), "TP5": (60.10, 88.10, 0), "TP6": (63.10, 88.10, 0),
}

# board-level silk labels: (text, x, y, size)
LABELS = [
    ("POWER", 44.10, 18.60, 2.0), ("FPGA - ECP5 LFE5U-12F", 66.10, 38.10, 2.0),
    ("USB + CONSOLE", 92.10, 108.10, 2.0), ("JTAG", 30.10, 98.10, 2.0),
    ("EXPANSION", 52.10, 105.10, 2.0), ("MOTOR", 100.10, 80.10, 2.0),
    ("CONFIG FLASH", 74.10, 44.10, 1.6), ("APP FLASH", 92.10, 76.10, 1.6),
    ("FIT U1 LAST - MEASURE RAILS FIRST", 66.10, 59.10, 1.6),
]


# ------------------------------------------------------------------- emit file
def pads_of(builder) -> list:
    """Footprint builders return either a pad list or (library_id, pad list)."""
    result = builder()
    return result[1] if isinstance(result, tuple) else result


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


def finish(lines, placed=None) -> str:
    """Close the board file and check that placement and components agree."""
    lines.append(")")
    placed = set(PLACEMENT) if placed is None else placed
    missing = set(PLACEMENT) - placed
    if missing:
        raise SystemExit("placement without a component definition: %s" % sorted(missing))
    return "\n".join(lines) + "\n"


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
    for text, x, y, size in LABELS:
        lines.append("  (gr_text \"%s\" (at %.2f %.2f) (layer \"F.SilkS\") "
                     "(effects (font (size %.1f %.1f) (thickness 0.2))))" % (text, x, y, size, size))
    lines.append("")

    # Routing.  `sv16_route.py` writes the copper (tracks, vias and the filled
    # planes) to routing.kicad_pcb.txt.  When that file is present it is spliced
    # in at the end of the board and the empty zone outlines below are skipped,
    # because the router emits its own filled zones.  Without it the board is
    # the unrouted base: components, netlist and placement, zones declared but
    # not filled - which is what `--no-routing` and a fresh clone give you.
    have_routing = ROUTING_FILE.exists() and not NO_ROUTING

    # ground planes.  The stack-up (BOARD.md section 14) is
    # signal / solid GND / solid PWR / signal, so the plane goes on In1.Cu and
    # the bottom signal layer gets a pour as well.  KiCad fills them on the
    # first "Fill All Zones" (B) - the polygons below are the outlines only.
    gnd = NET_ORDER.index("GND") + 1
    zone_id = 0
    for layer, inset in ((("In1.Cu", 0.25), ("B.Cu", 0.5)) if not have_routing else ()):
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
    lines.append("")

    # connections grouped by reference
    by_ref: dict[str, dict[str, str]] = {}
    for ref, pad, net in CONNECTIONS:
        by_ref.setdefault(ref, {})[pad] = net

    placed = set()
    for ref, library, builder, value, group in COMPONENTS:
        if ref not in PLACEMENT:
            continue
        placed.add(ref)
        x, y, rot = PLACEMENT[ref]
        pads = pads_of(builder)
        attr = "through_hole" if any(pad["kind"] in ("thru_hole", "np_thru_hole")
                                     for pad in pads) else "smd"
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
    if have_routing:
        lines.extend(ROUTING_FILE.read_text().rstrip("\n").split("\n"))
        lines.append("")

    return finish(lines, placed)


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

# These are the rules the board is actually routed to (scripts/sv16_route.py):
# clearance, track width, via diameter, via drill.
PROJECT_NETCLASSES = [
    ("Default", 0.20, 0.20, 0.60, 0.30),
    ("Power", 0.20, 0.50, 0.60, 0.30),
    ("Switching", 0.50, 0.50, 0.60, 0.30),
    ("USB", 0.20, 0.20, 0.60, 0.30),
    ("JTAG", 0.25, 0.25, 0.60, 0.30),
    ("Fine", 0.15, 0.15, 0.30, 0.15),      # the U1 0.5 mm fan-out vias
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
                "rules": {"min_clearance": 0.15, "min_track_width": 0.12,
                          "min_through_hole_diameter": 0.15, "min_via_diameter": 0.30,
                          "min_via_annular_width": 0.05},
                "track_widths": [0.12, 0.15, 0.2, 0.25, 0.5, 0.8, 1.0],
                "via_dimensions": [{"diameter": 0.30, "drill": 0.15},
                                   {"diameter": 0.45, "drill": 0.25},
                                   {"diameter": 0.60, "drill": 0.30}],
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

    by_ref = {ref: (x, y, rot) for ref, x, y, rot in
              ((ref,) + PLACEMENT[ref] for ref in PLACEMENT)}
    pads: dict[str, list[tuple[float, float, str]]] = {}
    for ref, library, builder, value, group in COMPONENTS:
        if ref not in PLACEMENT:
            continue
        x, y, rot = PLACEMENT[ref]
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
        if ref not in PLACEMENT:
            continue
        cx, cy = PLACEMENT[ref][0] * scale, PLACEMENT[ref][1] * scale
        half = 40 if group == "fpga" else 12
        draw.rectangle([cx - half, cy - half, cx + half, cy + half],
                       outline=colours.get(group, "#9ca3af"), width=2)
        if group in ("fpga", "power", "usb", "jtag", "flash"):
            draw.text((cx - half, cy - half - 10), ref, fill=colours.get(group, "#fff"))
    image.save(OUT / "placement_preview.png")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only verify the file on disk")
    parser.add_argument("--no-routing", action="store_true",
                        help="ignore routing.kicad_pcb.txt and emit the unrouted base")
    args = parser.parse_args()
    global NO_ROUTING
    NO_ROUTING = args.no_routing

    OUT.mkdir(parents=True, exist_ok=True)
    if not args.check:
        text = build_board()
        BOARD_FILE.write_text(text)
        print("wrote %s (%d lines, %.0f KB)" % (BOARD_FILE.relative_to(ROOT),
                                                text.count("\n"), len(text) / 1024.0))
        write_project()
        draw_preview()
    else:
        text = BOARD_FILE.read_text()
        print("checking %s" % BOARD_FILE.relative_to(ROOT))
    return check(text)


if __name__ == "__main__":
    sys.exit(main())
