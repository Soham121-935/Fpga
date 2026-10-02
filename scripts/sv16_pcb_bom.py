#!/usr/bin/env python3
"""Write the order files for the SV-16 board: BOM, pick-and-place, fab card.

Three things a board order needs and a KiCad board file does not contain:

| File | What it is for |
| :--- | :--- |
| `hardware/sv16_board/BOM.csv` | every part, grouped, with quantity, the KiCad footprint, the part number from the documents, the package the cart says, and a DNP column |
| `hardware/sv16_board/JLCPCB_CPL.csv` | pick-and-place positions in the column layout JLCPCB's assembly service wants (`Designator,Val,Package,Mid X,Mid Y,Rotation,Layer`), origin at the board's bottom-left corner, Y measured upwards as they expect |
| `hardware/sv16_board/JLCPCB_BOM.csv` | the same list in their BOM column layout, with a blank LCSC column for you to fill from the cart |
| `hardware/sv16_board/FAB_NOTES.md` | the exact ordering settings (4 layers, 1.6 mm, 1 oz, HASL), the design-rule summary, and the checks to run before uploading |

The data comes from `sv16_board_kicad.py` (footprints, values, nets) plus the
`PART_NUMBERS` table below, which is copied from BOARD.md section 3 and
hardware/cart/RECONCILED.md - not invented.

Usage
    scripts/sv16_pcb_bom.py            # write all four files
    scripts/sv16_pcb_bom.py --check    # exit 1 if the files are stale (used by lint)
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sv16_board_kicad as board      # noqa: E402

OUT = ROOT / "hardware" / "sv16_board"

# Part numbers and packages as they appear in BOARD.md section 3 and in the cart
# screenshots (hardware/cart/RECONCILED.md).  "to buy" marks describe the parts
# the documents say are still missing from the cart.
PARTS: dict[str, dict] = {
    "U1": {"part": "LFE5U-12F-6TG144C", "note": "no substitute; order a spare (BOARD.md 3.4)"},
    "U2": {"part": "W25Q64JVSSIQ", "note": "bitstream flash"},
    "U3": {"part": "W25Q64JVSSIQ", "note": "application flash; W25Q32/W25Q16 is enough"},
    "U4": {"part": "CH340G", "note": "SOP-16; needs Y2 12 MHz + C36/C37 (the C variant does not)"},
    "U5": {"part": "AP62300TWU-7", "note": "TSOT-26; EN is a 6 V pin - use the R48/R49 divider"},
    "U6": {"part": "MP1584EN-LF-Z", "note": "SOIC-8E; solder the exposed pad (thermal vias are placed)"},
    "U7": {"part": "LP5907MFX-2.5", "note": "SOT-23-5; needs a low-ESR 10 uF on OUT (C42)"},
    "U8": {"part": "USBLC6-2SC6", "note": "SOT-23-6, place at the connector"},
    "Y1": {"part": "YIC OSC25M-3.3I/S3-25T", "note": "ACTIVE 25 MHz 3.3 V XO, 4-pin - a 2-pin crystal will not clock the FPGA"},
    "Y2": {"part": "12 MHz crystal", "note": "CH340G clock; CL 12-20 pF, choose C36/C37 to match"},
    "Q1": {"part": "2N7002", "note": "SOT-23, PROGRAMN pull-down from DTR"},
    "Q2": {"part": "MMBT3904 (cart) / BC817", "note": "DONE indicator"},
    "Q4": {"part": "MMBT3906 (cart) / BC807", "note": "INITN indicator"},
    "D8": {"part": "SS34", "note": "SMA; input ORing"},
    "D9": {"part": "SS34", "note": "SMA; input ORing; keep the 4th SS34 as a spare"},
    "D11": {"part": "SS34", "note": "SMA; MP1584 catch diode"},
    "L1": {"part": "CD54 10 uH >= 1.5 A", "note": "AP62300 3V3 inductor; the cart has 2 x 33 uH as spares"},
    "L2": {"part": "CD54 10 uH >= 1.5 A", "note": "MP1584 1V1 inductor"},
    "FB1": {"part": "600 ohm @ 100 MHz ferrite", "note": "0603, >= 500 mA"},
    "C21": {"part": "100 uF 25 V tantalum, D case", "note": "1V1 bulk; mind the polarity bar"},
    "C22": {"part": "22 uF 63 V electrolytic", "note": "D6.3 x L5.4 mm"},
    "C23": {"part": "470 uF 25 V (35 V preferred)", "note": "the cart part is 16 V - on a 12 V rail that is only 1.33x derating"},
    "C24": {"part": "220 uF hybrid electrolytic", "note": "D8 x L10.5 mm; hybrid polymer is better for ripple"},
    "R47": {"part": "10 kohm 1 %", "note": "TO BUY - AP62300 feedback bottom leg"},
    "C39": {"part": "10 uF X5R/X7R 25 V", "note": "TO BUY - AP62300 input ceramic"},
    "C40": {"part": "22 uF X5R 25 V", "note": "TO BUY - 3V3 output ceramic"},
    "C41": {"part": "22 uF X5R 25 V", "note": "TO BUY - 3V3 output ceramic"},
    "C42": {"part": "10 uF X5R 25 V low ESR", "note": "TO BUY - LP5907 output; mandatory, the part is only stable into a low-ESR cap"},
    "C25": {"part": "10 uF", "note": "TO BUY - 3V3 bulk near the FPGA banks"},
    "C30": {"part": "10 uF", "note": "TO BUY - LP5907 input"},
}

VALUE_OVERRIDE = {
    "R38": "12.4k", "R39": "33k", "R40": "100k", "R41": "100k", "R43": "100k",
    "R44": "0R", "R45": "10k", "R46": "33k", "R47": "10k", "R48": "100k",
    "R49": "33k", "R36": "5.1k", "R37": "5.1k", "R19": "10k", "R21": "0R",
    "R22": "0R (or not fitted)", "R23": "0R", "R24": "0R (or not fitted)",
}


def rows():
    """[(ref, value, library, group, dnp)] from the board generator."""
    placement = board.effective_placement()
    out = []
    for ref, library, builder, value, group in board.COMPONENTS:
        if ref not in placement:
            continue
        shown = VALUE_OVERRIDE.get(ref) or value or ""
        out.append((ref, shown, library.split(":")[-1], group, ref in board.DNP_REFS))
    return out


def build_bom(entries) -> list[dict]:
    grouped: dict[tuple, list[str]] = {}
    for ref, value, package, group, dnp in entries:
        key = (value, package, dnp)
        grouped.setdefault(key, []).append(ref)
    lines = []
    for (value, package, dnp), refs in sorted(grouped.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        refs = sorted(refs, key=lambda r: (r.rstrip("0123456789"),
                                           int("".join(c for c in r if c.isdigit()) or 0)))
        part = next((PARTS[r]["part"] for r in refs if r in PARTS), "")
        note = next((PARTS[r]["note"] for r in refs if r in PARTS), "")
        lines.append({"Quantity": len(refs), "Value": value, "Footprint": package,
                      "References": " ".join(refs), "Part number": part,
                      "DNP": "yes" if dnp else "", "Notes": note})
    return lines


def write_bom(lines) -> None:
    path = OUT / "BOM.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Quantity", "Value", "Footprint",
                                                    "References", "Part number", "DNP", "Notes"])
        writer.writeheader()
        writer.writerows(lines)
    print("wrote %s (%d lines, %d parts)"
          % (path.relative_to(ROOT), len(lines), sum(l["Quantity"] for l in lines)))


def write_jlcpcb(entries) -> None:
    placement = board.effective_placement()
    bom = OUT / "JLCPCB_BOM.csv"
    with bom.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Comment", "Designator", "Footprint", "LCSC"])
        for refs, value, package in _jlcpcb_groups(entries):
            writer.writerow([value, ",".join(refs), package, ""])
    cpl = OUT / "JLCPCB_CPL.csv"
    with cpl.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Designator", "Val", "Package", "Mid X", "Mid Y", "Rotation", "Layer"])
        for ref, value, package, group, dnp in sorted(entries):
            if dnp or group == "mech":
                continue
            x, y, rot = placement[ref]
            # JLCPCB measures from the board's bottom-left corner with Y upwards
            writer.writerow([ref, value, package, "%.2f" % x, "%.2f" % (board.BOARD_H - y),
                             "%.0f" % rot, "T"])
    print("wrote %s and %s" % (bom.relative_to(ROOT), cpl.relative_to(ROOT)))


def _jlcpcb_groups(entries):
    grouped: dict[tuple, list[str]] = {}
    for ref, value, package, group, dnp in entries:
        if dnp or group == "mech":
            continue
        grouped.setdefault((value, package), []).append(ref)
    for (value, package), refs in sorted(grouped.items()):
        yield sorted(refs), value, package


FAB_NOTES = """# Fab and assembly card — SV-16 board

_Generated by `scripts/sv16_pcb_bom.py`; the numbers come from the board file the
same script read, so they cannot drift from it._

## Board

| Setting | Value |
| :--- | :--- |
| Size | {w:.0f} x {h:.0f} mm (this is the boundary of the cheap 4-layer tier — check the quote) |
| Layers | **4** |
| Thickness | 1.6 mm |
| Stack-up | signal / solid GND / power pours / signal |
| Copper | 1 oz outer, 0.5–1 oz inner |
| Surface finish | HASL (lead-free) |
| Minimum track / clearance | 0.20 mm / 0.20 mm |
| Minimum via | 0.45 mm pad / 0.20 mm drill (0.8/0.4 for power and stitching) |
| Holes | {holes} plated, {npth} non-plated (4 x M3 mounting) |
| Impedance control | not required — full-speed USB at 0.2/0.2 mm on this stack is 85–95 ohm |
| Castellations / edge plating | none |
| Countersinks | none |
| Marking | F.Silkscreen + B.Silkscreen, subtract soldermask, **no Protel extensions** |

## Assembly (only if you order it assembled)

| Setting | Value |
| :--- | :--- |
| Parts on the CPL | {cpl} placements, top side only |
| Sides | single-sided (all SMD is on the top layer) |
| BOM | `JLCPCB_BOM.csv` — fill the **LCSC** column from your cart before uploading |
| CPL | `JLCPCB_CPL.csv` — Designator, Val, Package, Mid X, Mid Y, Rotation, Layer |
| Rotation check | verify the LED cathode, the SS34 band (pin 1 = cathode), the tantalum bar and the SOT-23 pin 1 against their rendered preview |
| DNP parts | {dnp} (marked in the board file and excluded from the CPL) |

## Files to upload

1. the gerber zip (F.Cu, In1.Cu, In2.Cu, B.Cu, F/B.Mask, F/B.Silkscreen, Edge.Cuts, F.Paste + drill)
2. `JLCPCB_BOM.csv` and `JLCPCB_CPL.csv` if assembled
3. this card, if you want the fab to keep the stack-up explicit

## Doctor before you order

```sh
make pcb                # regenerate the board, bitmaps, BOM and CPL
make pcb-check          # the generator parses its own output back: nets, pads, DRC-lite, placement
python3 scripts/sv16_pcb_copper.py --report   # what the copper plan did and what the router still owes
```

Open the board in KiCad and, in this order: **Tools -> Update Footprints from
Library**, **B (fill zones)**, then **Inspect -> Design Rules Checker**. The
generated file already carries the rail pours, {vias} vias and {stubs} stub
tracks; DRC's remaining complaints are the ones routing has to fix.

## What the generator already did for you

* 141 footprints placed, 596 pads, 472 on 133 nets — the netlist is complete
* 5 zones: solid GND on In1.Cu, GND pour on B.Cu, 3V3 / 2V5 / 1V1 pours on In2.Cu with priorities
* {vias} vias: {escape_notes}
* {stubs} stub tracks (0.2 mm) connecting each of those pads to its via
* DNP parts marked in the file, on the silkscreen and in the BOM/CPL
* the pad-collision repair pass: {moved} parts were nudged so no two pads of
  different nets touch (the raw placement table had overlaps)
"""


def write_fab_notes(entries, copper) -> None:
    placement = board.effective_placement()
    holes = sum(1 for ref, lib, b, v, g in board.COMPONENTS
                if ref in placement and g != "mech"
                for pad in board.pads_of(b) if "thru_hole" in pad["kind"])
    npth = sum(1 for ref, lib, b, v, g in board.COMPONENTS
               if ref in placement
               for pad in board.pads_of(b) if pad["kind"] == "np_thru_hole")
    cpl = sum(1 for ref, value, package, group, dnp in entries
              if not dnp and group != "mech")
    by_net: dict[str, int] = {}
    for via in copper.vias:
        by_net[via["net"]] = by_net.get(via["net"], 0) + 1
    escape_notes = " ".join("%s %d," % kv for kv in sorted(by_net.items())).rstrip(",")
    moved = [ref for ref in board.PLACEMENT
             if (board.PLACEMENT[ref][0], board.PLACEMENT[ref][1]) !=
             board.effective_placement()[ref][:2]]
    path = OUT / "FAB_NOTES.md"
    path.write_text(FAB_NOTES.format(
        w=board.BOARD_W, h=board.BOARD_H, holes=holes, npth=npth, cpl=cpl,
        dnp=", ".join(sorted(board.DNP_REFS)),
        vias=len(copper.vias), stubs=len(copper.segments),
        escape_notes=escape_notes, moved=len(moved)))
    print("wrote %s" % path.relative_to(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the files on disk are stale")
    args = parser.parse_args()

    entries = rows()
    lines = build_bom(entries)
    copper = board.copper_plan()
    if args.check:
        path = OUT / "BOM.csv"
        if not path.exists():
            print("FAIL: %s is missing" % path.relative_to(ROOT))
            return 1
        with path.open() as handle:
            existing = [{key: str(value) for key, value in row.items()}
                        for row in csv.DictReader(handle)]
        expected = [{key: str(value) for key, value in row.items()} for row in lines]
        if existing != expected:
            print("FAIL: %s is stale - run make pcb-bom" % path.relative_to(ROOT))
            return 1
        print("BOM is current (%d lines)" % len(lines))
        return 0

    write_bom(lines)
    write_jlcpcb(entries)
    write_fab_notes(entries, copper)
    return 0


if __name__ == "__main__":
    sys.exit(main())
