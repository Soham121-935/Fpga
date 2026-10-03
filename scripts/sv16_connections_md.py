#!/usr/bin/env python3
"""SV-16 — emit the board netlist as a plain markdown table.

The netlist lives in scripts/sv16_board_kicad.py and is the single source of
truth for what connects to what; this script only reshapes it into one row per
net so it can be printed.  Nothing is invented here: if a connection is not in
CONNECTIONS, it does not appear.

    scripts/sv16_connections_md.py                 # -> CONNECTIONS.md
    scripts/sv16_connections_md.py --out foo.md
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sv16_board_kicad as B  # noqa: E402


def ref_key(ref):
    """Sort C2 before C10, and group by prefix before number."""
    m = re.match(r"([A-Za-z_]+)(\d+)$", ref)
    return (m.group(1), int(m.group(2)), ref) if m else (ref, 0, ref)


def pad_key(pad):
    """Sort pin "10" after "9", and keep named pads (A, K, VBUS) last."""
    return (0, int(pad), "") if pad.isdigit() else (1, 0, pad)


def net_key(net):
    """Power rails first, then signals, each alphabetically."""
    return (0 if net in getattr(B, "POWER_NETS", ()) else 1, net)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=None, help="markdown output (default CONNECTIONS.md)")
    args = ap.parse_args()
    dst = Path(args.out) if args.out else ROOT / "CONNECTIONS.md"

    nets = {}
    for ref, pad, net in B.CONNECTIONS:
        nets.setdefault(net, []).append((ref, pad))

    lines = ["# SV-16 — Connections", ""]
    lines.append("| Net | Pins | Connections |")
    lines.append("| --- | ---: | --- |")
    for net in sorted(nets, key=net_key):
        pins = sorted(nets[net], key=lambda rp: (ref_key(rp[0]), pad_key(rp[1])))
        joined = " ".join("%s.%s" % (ref, pad) for ref, pad in pins)
        lines.append("| `%s` | %d | %s |" % (net, len(pins), joined))

    text = "\n".join(lines) + "\n"
    dst.write_text(text)

    total = sum(len(v) for v in nets.values())
    print("wrote %s (%d nets, %d connections)" % (dst, len(nets), total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
