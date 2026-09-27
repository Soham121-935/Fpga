#!/usr/bin/env python3
"""SV-16 — PCB netlist generator / checker.

Cross-references three things that must never disagree:

  1. board/ecp5_tqfp144.json  — the LFE5U-12F-6TG144C device pin database
                                (98 user I/O + 11 dedicated sysCONFIG/TAP + power),
  2. constraints/ecp5_144tqfp.lpf — the pin constraints the bitstream is built with,
  3. BOARD.md §6/§7 — the board net names and connector pinouts this script prints.

Output: board/TQFP144_PINOUT.md (generated, checked in, verified by --check).

Usage:
    scripts/sv16_board_pins.py            # regenerate board/TQFP144_PINOUT.md
    scripts/sv16_board_pins.py --check    # exit 1 if the checked-in file is stale
    scripts/sv16_board_pins.py --summary  # only print the bank/config summary

Exit codes: 0 ok, 1 stale/ inconsistent, 2 usage error.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEVICE = ROOT / "board" / "ecp5_tqfp144.json"
LPF = ROOT / "constraints" / "ecp5_144tqfp.lpf"
OUT = ROOT / "board" / "TQFP144_PINOUT.md"

# Board rail per I/O bank.  Every bank in this design is LVCMOS33, so all six
# bank supply pins sit on the 3V3 rail (datasheet Table 3.11: 3.135-3.465 V).
BANK_RAIL = {0: "3V3", 1: "3V3", 2: "3V3", 3: "3V3", 6: "3V3", 7: "3V3", 8: "3V3"}

# ---------------------------------------------------------------- device side
# sysCONFIG role of the bank-8 dual-purpose pads (TN1260 Table 4 / TN-02039 §4.4).
# "claimed" = pad belongs to the configuration port while CFG[2:0] = 010 (Master SPI),
# i.e. it must not be trusted as a clean user I/O on a board that also uses MSPI.
CONFIG_PADS = {
    39: ("D5/IO5", False), 40: ("D7/IO7", False), 41: ("D4/IO4", False),
    44: ("D6/IO6", False), 45: ("D3/IO3", False), 46: ("D1/MISO", True),
    47: ("D0/MOSI", True), 48: ("CSN/SN", False), 49: ("HOLDN/DI/BUSY/CSSPIN", True),
    50: ("CS1N", False), 51: ("DOUT/CSON", True), 52: ("WRITEN", False),
}

# ---------------------------------------------------------------- board side
# FPGA signal name -> board net / destination.  Kept here so the generated table
# and BOARD.md §6/§7 cannot drift apart.
BOARD_NETS = {
    "clk_25m": "Y1.3 25 MHz XO output",
    "ext_rst_n": "SW1 reset button (to GND) + R1 10k pull-up + C1 100n",
    "uart_rx": "U1 TXD via R21 0R / J5.3 via R22 0R",
    "uart_tx": "U1 RXD via R23 0R / J5.2 via R24 0R",
    "flash_sck": "U6.6 application flash SCK",
    "flash_cs_n": "U6.1 application flash /CS",
    "flash_mosi": "U6.5 application flash DI",
    "flash_miso": "U6.2 application flash DO",
    "spi0_sck": "J2.12 SPI0 expansion",
    "spi0_cs_n": "J2.11 SPI0 expansion",
    "spi0_mosi": "J2.13 SPI0 expansion",
    "spi0_miso": "J2.14 SPI0 expansion",
    "pwm_out": "J6.3 motor connector",
    "motor_dir1": "J6.4 motor connector",
    "motor_dir2": "J6.5 motor connector",
    "motor_fault_n": "J6.6 motor connector",
}
BOARD_NET_REGEX = [
    (re.compile(r"^led\[(\d+)\]$"), lambda m: "D%d LED (active low) + R%d 470R" % (2 + int(m.group(1)), 31 + int(m.group(1)))),
    (re.compile(r"^gpio_a\[(\d+)\]$"), lambda m: "J4.%d EXP-C header" % (1 + int(m.group(1))) if int(m.group(1)) < 8
                                               else "J2.%d EXP-A header" % (3 + int(m.group(1)) - 8)),
    (re.compile(r"^gpio_b\[(\d+)\]$"), lambda m: "J3.%d EXP-B header" % (3 + int(m.group(1))) if int(m.group(1)) < 16
                                               else "J3.%d EXP-B header" % (3 + int(m.group(1)))),
]
CONFIG_NET = {
    "CCLK": "U5.6 config flash CLK (R7 100R series, R8 1k pull-up to VCCIO8)",
    "INITN": "J1.10 + R9 4.7k pull-up to VCCIO8 + D6 red LED via R15 1k",
    "DONE": "J1.9 + R10 4.7k pull-up to VCCIO8 + D1 green LED via R32 1k",
    "PROGRAMN": "J1.4 + R11 4.7k pull-up to VCCIO8 + SW2 + Q1 (DTR auto-program, JP1 to disable)",
    "CFG_0": "R12 1k to GND (CFGMDN0 = 0)",
    "CFG_1": "R13 4.7k to VCCIO8 (CFGMDN1 = 1)",
    "CFG_2": "R14 1k to GND (CFGMDN2 = 0)",
    "TCK": "J1.8 (TCK)",
    "TMS": "J1.6 (TMS)",
    "TDI": "J1.3 (TDI)",
    "TDO": "J1.2 (TDO)",
}
RAIL_NET = {
    "vcc": "1V1 core rail (U3 switcher) — 4x 100n + 10u",
    "vccaux": "2V5 rail (U4 LDO) — 100n + 4u7",
    "vccio": "3V3 rail — 100n per pin",
    "gnd": "GND plane",
    "nc": "do not connect",
}


def load_device():
    doc = json.loads(DEVICE.read_text())
    return doc, {int(k): v for k, v in doc["pins"].items()}


def load_lpf():
    """Return {pin_number: (signal, drive_ma, pullmode)} for every LOCATE in the LPF."""
    text = LPF.read_text()
    blocks = re.findall(
        r'LOCATE\s+COMP\s+"([^"]+)"\s+SITE\s+"(\d+)"\s*;\s*\nIOBUF\s+PORT\s+"[^"]+"\s+([^;]+);',
        text, re.S)
    out = {}
    for name, pin, attrs in blocks:
        drive = re.search(r"DRIVE=(\d+)", attrs)
        pull = re.search(r"PULLMODE=(\w+)", attrs)
        out[int(pin)] = (name, drive.group(1) if drive else "4", pull.group(1) if pull else "-")
    return out


def board_net(signal):
    if signal in BOARD_NETS:
        return BOARD_NETS[signal]
    for rx, fn in BOARD_NET_REGEX:
        m = rx.match(signal)
        if m:
            return fn(m)
    return "spare I/O — route to J7 breakout"


def device_net(pin, info):
    kind = info["kind"]
    if kind == "io":
        return ""
    if kind in ("config", "jtag"):
        return CONFIG_NET.get(info["pad"], "")
    return RAIL_NET.get(kind, "")


def build_report(device, pins, lpf):
    used = sorted(lpf)
    lines = []
    add = lines.append

    add("# LFE5U-12F-6TG144C — complete TQFP-144 pin / net table")
    add("")
    add("> **Generated by `scripts/sv16_board_pins.py` — do not edit by hand.**")
    add("> Device data: `board/ecp5_tqfp144.json`; design signals: `constraints/ecp5_144tqfp.lpf`;")
    add("> board destinations: `BOARD.md` §5–§7.  Part: **%s** (%s)." % (device["part"], device["package"]))
    add("")

    # ---- bank summary ------------------------------------------------
    bank_io = {}
    for pin, info in pins.items():
        if info["kind"] == "io":
            bank_io.setdefault(info["bank"], []).append(pin)
    add("## 1. I/O bank summary")
    add("")
    add("| Bank | VCCIO rail | I/O pins | Used by this design | Free |")
    add("| ---: | :--- | ---: | ---: | ---: |")
    for bank in sorted(bank_io):
        allp = bank_io[bank]
        usep = [p for p in allp if p in lpf]
        add("| %d | %s (pin %s) | %d | %d | %d |" % (
            bank, BANK_RAIL[bank],
            ", ".join(str(p) for p in sorted(pins) if pins[p].get("kind") == "vccio" and pins[p]["bank"] == bank),
            len(allp), len(usep), len(allp) - len(usep)))
    add("")
    total_io = device["summary"]["user_io"]
    add("Total: %d user I/O, %d used by the design, %d free." % (total_io, len(used), total_io - len(used)))
    add("")

    # ---- warning list ------------------------------------------------
    claimed = [p for p in used if p in CONFIG_PADS and CONFIG_PADS[p][1]]
    add("## 2. Configuration-pad interactions (CFG[2:0] = 010, Master SPI)")
    add("")
    add("| Pin | Pad | sysCONFIG role | LPF signal | Consequence on the board |")
    add("| ---: | :--- | :--- | :--- | :--- |")
    for p in sorted(used):
        if p in CONFIG_PADS:
            role, is_claimed = CONFIG_PADS[p]
            add("| %d | %s | %s%s | `%s` | %s |" % (
                p, pins[p]["pad"], role, " **(Master SPI pad)**" if is_claimed else "",
                lpf[p][0],
                "shares the net with the config flash — see BOARD.md §6.4" if is_claimed
                else "parallel/slave-mode pad only, free in this configuration"))
    add("")
    add("Pins sharing a net with the configuration flash: %s." % (
        ", ".join(str(p) for p in claimed) if claimed else "none"))
    add("")

    # ---- full table --------------------------------------------------
    add("## 3. Complete pin table (1-144)")
    add("")
    add("| Pin | Pad | Kind | Bank / rail | Design signal | Drive / pull | Board net |")
    add("| ---: | :--- | :--- | :--- | :--- | :--- | :--- |")
    for n in range(1, 145):
        info = pins[n]
        kind = info["kind"]
        if kind == "io":
            where = "bank %d (%s)" % (info["bank"], BANK_RAIL[info["bank"]])
        elif kind in ("config", "jtag"):
            where = "config" if kind == "config" else "JTAG"
        else:
            where = RAIL_NET[kind].split(" —")[0]
        if n in lpf:
            sig, drive, pull = lpf[n]
            sig_cell = "`%s`" % sig
            drv_cell = "%s mA" % drive + ("" if pull == "-" else " / %s" % pull)
            net = board_net(sig)
        else:
            sig_cell = "—"
            drv_cell = "—"
            if kind == "io":
                net = "spare I/O — route to J7 breakout"
                if n in CONFIG_PADS:
                    net += " (sysCONFIG pad: %s)" % CONFIG_PADS[n][0]
            else:
                net = device_net(n, info)
        add("| %d | %s | %s | %s | %s | %s | %s |" % (n, info["pad"], kind, where, sig_cell, drv_cell, net))
    add("")
    add("_Pad names and the dedicated sysCONFIG/TAP pins are from Lattice BSDL FPGA-MD-02097")
    add("(LFE5U_25F_XXTG144); the LFE5U-12F/25F/45F 144-TQFP pinout is identical (FPGA-DS-02012-3.4")
    add("Table 1.1 lists 98 user I/O on 144 TQFP for each density).  The 98 user-I/O pin numbers and")
    add("their banks are taken from the prjtrellis database for LFE5U-12F and agree with the BSDL._")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify the checked-in table is current")
    ap.add_argument("--summary", action="store_true", help="print only the summary")
    args = ap.parse_args()

    device, pins = load_device()
    lpf = load_lpf()

    problems = []
    for n in sorted(lpf):
        if n not in pins:
            problems.append("LPF pin %d is outside 1-144" % n)
        elif pins[n]["kind"] != "io":
            problems.append("LPF pin %d is not a user I/O pin (kind=%s)" % (n, pins[n]["kind"]))
    if not lpf:
        problems.append("no LOCATE COMP statements found in %s" % LPF)
    if problems:
        for p in problems:
            print("ERROR: %s" % p)
        return 1

    claimed = sorted(p for p in lpf if p in CONFIG_PADS and CONFIG_PADS[p][1])
    if not args.summary:
        text = build_report(device, pins, lpf)
        if args.check:
            old = OUT.read_text() if OUT.exists() else ""
            if old != text:
                print("ERROR: %s is out of date — run scripts/sv16_board_pins.py" % OUT.relative_to(ROOT))
                return 1
            print("%s is up to date (%d pins, %d constrained)" % (OUT.relative_to(ROOT), len(pins), len(lpf)))
        else:
            OUT.write_text(text)
            print("wrote %s (%d pins, %d constrained)" % (OUT.relative_to(ROOT), len(pins), len(lpf)))

    if not args.check:
        bank_io = {}
        for pin, info in pins.items():
            if info["kind"] == "io":
                bank_io.setdefault(info["bank"], []).append(pin)
        print("device: %s  %s" % (device["part"], device["package"]))
        print("user I/O %d (used %d, free %d)" % (
            device["summary"]["user_io"], len(lpf), device["summary"]["user_io"] - len(lpf)))
        for bank in sorted(bank_io):
            allp = bank_io[bank]
            usep = [p for p in allp if p in lpf]
            print("  bank %d (%s): %2d I/O, %2d used, %2d free" %
                  (bank, BANK_RAIL[bank], len(allp), len(usep), len(allp) - len(usep)))
    print("shared with the Master-SPI config port: %s -> %s (BOARD.md §6.4)" % (
        claimed, ", ".join(lpf[p][0] for p in claimed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
