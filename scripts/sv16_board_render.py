#!/usr/bin/env python3
"""SV-16 — draw a board file to a PNG so the layout can actually be looked at.

KiCad is not installed here, so the only way to judge whether a placement or
a route "looks good" is to draw it.  Renders the board outline, courtyard,
pads, tracks (one colour per copper layer), vias, zones and reference text.

    scripts/sv16_board_render.py                          # -> build/board.png
    scripts/sv16_board_render.py --board X.kicad_pcb --out y.png
    scripts/sv16_board_render.py --layers F.Cu,B.Cu       # only some layers
    scripts/sv16_board_render.py --scale 8                # pixels per mm

Needs Pillow (python3 -m pip install pillow).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.stderr.write("Pillow is not installed - python3 -m pip install pillow\n")
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BOARD = ROOT / "hardware" / "sv16_board" / "sv16_board.kicad_pcb"

# One colour per copper layer, so a route can be read at a glance.
LAYER_COLOUR = {
    "F.Cu":  (200,  40,  40),
    "B.Cu":  ( 40, 110, 210),
    "In1.Cu": ( 90, 170,  90),
    "In2.Cu": (210, 150,  40),
}
PAD_COLOUR   = (215, 185,  70)
VIA_COLOUR   = (235, 235, 235)
BODY_COLOUR  = ( 95, 105, 120)
EDGE_COLOUR  = (250, 250, 250)
SILK_COLOUR  = (190, 200, 215)
ZONE_ALPHA   = 0.16


def num(text, i=0):
    """Read the i-th float out of an s-expression fragment."""
    return float(re.findall(r"-?\d+\.?\d*", text)[i])


def split_blocks(text, header):
    """Yield balanced (header ...) blocks."""
    out, i = [], 0
    while True:
        j = text.find(header, i)
        if j < 0:
            break
        depth, k = 0, j
        while k < len(text):
            if text[k] == "(":
                depth += 1
            elif text[k] == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        out.append(text[j:k + 1])
        i = k
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--board", default=str(DEFAULT_BOARD))
    ap.add_argument("--out", default=None)
    ap.add_argument("--layers", default="F.Cu,In1.Cu,In2.Cu,B.Cu",
                    help="copper layers to draw, comma separated")
    ap.add_argument("--scale", type=float, default=7.0, help="pixels per mm")
    ap.add_argument("--no-refs", action="store_true")
    args = ap.parse_args()

    board = Path(args.board)
    if not board.exists():
        sys.stderr.write("no such board: %s\n" % board)
        return 2
    text = board.read_text(errors="replace")
    want = [s.strip() for s in args.layers.split(",") if s.strip()]
    out = Path(args.out) if args.out else ROOT / "build" / "board.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    # --- board extents from Edge.Cuts ---
    xs, ys = [0.0, 100.0], [0.0, 100.0]
    pts = []
    for m in re.finditer(r'\(gr_(?:line|rect) \(start ([-\d.]+) ([-\d.]+)\)(?: \(end ([-\d.]+) ([-\d.]+)\))?[^)]*\n?\s*\(layer "Edge\.Cuts"\)', text):
        pts.append((float(m.group(1)), float(m.group(2))))
        if m.group(3):
            pts.append((float(m.group(3)), float(m.group(4))))
    if not pts:  # fall back to footprint extent
        for m in re.finditer(r'\(footprint [^\n]*\(at ([-\d.]+) ([-\d.]+)', text):
            pts.append((float(m.group(1)), float(m.group(2))))
    if pts:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]

    pad = 3.0
    x0, x1 = min(xs) - pad, max(xs) + pad
    y0, y1 = min(ys) - pad, max(ys) + pad
    s = args.scale
    W, H = int((x1 - x0) * s), int((y1 - y0) * s)
    img = Image.new("RGB", (max(W, 64), max(H, 64)), (24, 26, 30))
    d = ImageDraw.Draw(img, "RGBA")

    def P(x, y):
        return ((x - x0) * s, (y - y0) * s)

    # --- zones (fills) first, so copper sits on top ---
    for z in split_blocks(text, "(zone "):
        layer = re.search(r'\(layer "([^"]+)"', z)
        if not layer or layer.group(1) not in want:
            continue
        net = re.search(r'\(net_name "([^"]+)"', z)
        tint = {"GND": (60, 130, 70), "3V3": (170, 70, 60),
                "1V1": (70, 90, 170), "2V5": (150, 120, 50)}.get(
                    net.group(1) if net else "", (110, 110, 120))
        fill = z.find("(filled_polygon")
        if fill < 0:
            continue
        poly = re.search(r'\(filled_polygon\s*\n\s*\(layer "([^"]+)"\)\s*\n\s*\(pts\s*(.*?)\)\s*\n\s*\)',
                         z[fill:], re.S)
        if not poly:
            continue
        xy = re.findall(r'\(xy ([-\d.]+) ([-\d.]+)\)', poly.group(2))
        if len(xy) >= 3:
            d.polygon([P(float(a), float(b)) for a, b in xy],
                      fill=tint + (int(255 * ZONE_ALPHA),))

    # --- tracks ---
    ntrack = 0
    for seg in split_blocks(text, "(segment "):
        layer = re.search(r'\(layer "([^"]+)"', seg)
        if not layer or layer.group(1) not in want:
            continue
        w = re.search(r'\(width ([\d.]+)\)', seg)
        width = float(w.group(1)) if w else 0.2
        m = re.search(r'\(start ([-\d.]+) ([-\d.]+)\) \(end ([-\d.]+) ([-\d.]+)\)', seg)
        if not m:
            continue
        a = (float(m.group(1)), float(m.group(2)))
        b = (float(m.group(3)), float(m.group(4)))
        col = LAYER_COLOUR.get(layer.group(1), (170, 170, 170))
        d.line([P(*a), P(*b)], fill=col, width=max(1, int(width * s)))
        ntrack += 1

    # --- vias ---
    nvia = 0
    for m in re.finditer(r'\(via(?: blind)? \(at ([-\d.]+) ([-\d.]+)\) \(size ([\d.]+)\)', text):
        x, y, sz = float(m.group(1)), float(m.group(2)), float(m.group(3))
        r = max(1.0, sz * s / 2)
        d.ellipse([P(x, y)[0] - r, P(x, y)[1] - r, P(x, y)[0] + r, P(x, y)[1] + r],
                  fill=VIA_COLOUR)
        nvia += 1

    # --- footprints: body, pads, reference ---
    nfp = 0
    for fp in split_blocks(text, "(footprint "):
        at = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', fp)
        if not at:
            continue
        ox, oy = float(at.group(1)), float(at.group(2))
        nfp += 1
        # body from the fabrication outline
        bx0 = by0 = 1e9
        bx1 = by1 = -1e9
        for m in re.finditer(r'\((?:fp_line|fp_rect) \(start ([-\d.]+) ([-\d.]+)\) \(end ([-\d.]+) ([-\d.]+)\)', fp):
            for px, py in ((float(m.group(1)), float(m.group(2))),
                           (float(m.group(3)), float(m.group(4)))):
                bx0, bx1 = min(bx0, px), max(bx1, px)
                by0, by1 = min(by0, py), max(by1, py)
        if bx1 > bx0:
            d.rectangle([P(ox + bx0, oy + by0), P(ox + bx1, oy + by1)],
                        outline=BODY_COLOUR, width=1)
        # pads
        for m in re.finditer(r'\(pad "[^"]+" [^)]+\(at ([-\d.]+) ([-\d.]+)(?: [-\d.]+)?\)[^)]*\(size ([\d.]+) ([\d.]+)\)', fp):
            px, py = ox + float(m.group(1)), oy + float(m.group(2))
            pw, ph = float(m.group(3)), float(m.group(4))
            d.rectangle([P(px - pw / 2, py - ph / 2), P(px + pw / 2, py + ph / 2)],
                        fill=PAD_COLOUR)
        if not args.no_refs:
            ref = re.search(r'\(fp_text reference "([^"]+)"', fp)
            if ref and bx1 > bx0:
                d.text(P(ox + bx0, oy + by0 - 1.6), ref.group(1), fill=SILK_COLOUR)

    # --- board edge, drawn last so it is never hidden ---
    for m in re.finditer(r'\(gr_line \(start ([-\d.]+) ([-\d.]+)\) \(end ([-\d.]+) ([-\d.]+)\)[^)]*\(layer "Edge\.Cuts"\)', text):
        d.line([P(float(m.group(1)), float(m.group(2))),
                P(float(m.group(3)), float(m.group(4)))],
               fill=EDGE_COLOUR, width=2)

    img.save(out)
    print("wrote %s (%dx%d, %.0f px/mm)" % (out, img.width, img.height, s))
    print("  %d footprints, %d tracks, %d vias" % (nfp, ntrack, nvia))
    return 0


if __name__ == "__main__":
    sys.exit(main())
