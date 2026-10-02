#!/usr/bin/env python3
"""Check a nextpnr-ecp5 report against the datasheet's resource budget.

Why this exists
---------------
prjtrellis models the LFE5U-12F with the LFE5U-25F's die: the two devices have
byte-identical `tilegrid.json` / `iodb.json` / `globals.json` in the database and
identical frame geometry (7,562 frames x 592 bits, max_row 50, max_col 72) -- only
the `idcode` differs (0x21111043 vs 0x41111043).  They are one die sold in two
bins.  Consequently nextpnr's utilisation denominators are the *die's* resources
(24,288 LUT4 slots, 56 sysMEM blocks), and nextpnr will happily place a
25F-sized design into a bitstream carrying the 12F idcode.

The budget that matters is the one Lattice guarantees for the part in the BOM.
From the ECP5/ECP5-5G Family Data Sheet (FPGA-DS-02012), Table 1.1:

    LFE5U-12: 12k LUTs, 32 x 18 kb sysMEM blocks (576 kb, i.e. 72 KB),
              97 kb distributed RAM, 28 x 18x18 multipliers, 2 PLLs / 2 DLLs,
              144 TQFP package: 98 I/O

(The 25F -- 24k LUTs, 56 blocks, 1,008 kb -- is what nextpnr's denominators
describe, and what this repository's documentation used to quote by mistake.)

Usage
-----
    scripts/sv16_check_budget.py build/sv16_nextpnr.log LFE5U-12F-6TQFP144 [--warn-only]

Exit status: 0 if inside budget, 2 if over budget (or 0 with --warn-only).
"""

from __future__ import annotations

import re
import sys

# Datasheet FPGA-DS-02012 Table 1.1, plus the TQFP-144 bonded I/O count.
# nextpnr's resource name -> (datasheet limit, what it is)
BUDGET: dict[str, tuple[int, str]] = {
    "TRELLIS_COMB": (12_144, "LUT4 (12k LUTs, datasheet)"),
    "TRELLIS_FF": (12_144, "flip-flops (2 per slice)"),
    "DP16KD": (32, "18 kb sysMEM blocks (576 kb)"),
    "MULT18X18D": (28, "18x18 multipliers"),
    "EHXPLLL": (2, "PLLs"),
    "TRELLIS_IO": (98, "I/O buffers bonded on TQFP-144"),
}

# "Info: \t        TRELLIS_COMB:    9407/  24288    38%"
LINE = re.compile(
    r"(?P<res>[A-Z][A-Z0-9_]*):\s+(?P<used>\d+)/\s+(?P<total>\d+)\s+(?P<pct>\d+)%"
)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__.strip().splitlines()[-6], file=sys.stderr)
        print("usage: sv16_check_budget.py <nextpnr.log> <part> [--warn-only]", file=sys.stderr)
        return 2

    log_path, part = argv[1], argv[2]
    warn_only = "--warn-only" in argv[3:]

    try:
        log = open(log_path, encoding="utf-8", errors="replace").read()
    except OSError as exc:
        print(f"[sv16] budget: cannot read {log_path}: {exc}", file=sys.stderr)
        return 2

    used: dict[str, int] = {}
    tool_total: dict[str, int] = {}
    for line in log.splitlines():
        m = LINE.search(line)
        if m and m.group("res") in BUDGET:
            used[m.group("res")] = int(m.group("used"))
            tool_total[m.group("res")] = int(m.group("total"))

    if not used:
        print(f"[sv16] budget: no utilisation table found in {log_path}", file=sys.stderr)
        return 2

    print(f"[sv16] resource budget for {part} (datasheet FPGA-DS-02012):")
    over: list[str] = []
    for res, (limit, label) in BUDGET.items():
        if res not in used:
            continue
        u = used[res]
        pct = 100.0 * u / limit
        flag = ""
        if u > limit:
            flag = "  <-- OVER BUDGET"
            over.append(f"{label.split('(')[0].strip()}: {u} used, {limit} guaranteed")
        elif pct >= 90:
            flag = "  <-- little headroom"
        print(f"[sv16]   {label:38s} {u:6d} / {limit:6d}  {pct:5.1f}%{flag}")

    if over:
        print(
            f"[sv16] this design exceeds what the datasheet guarantees for {part}:",
            file=sys.stderr,
        )
        for o in over:
            print(f"[sv16]   {o}", file=sys.stderr)
        print(
            "[sv16] nextpnr's denominators are the shared 12F/25F die, so a design this "
            "size would only be valid on a 25F (LFE5U-25F). See ADR-025.",
            file=sys.stderr,
        )
        if warn_only:
            print("[sv16] (--warn-only: continuing anyway)", file=sys.stderr)
            return 0
        return 2

    print(f"[sv16] all resources fit {part}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
