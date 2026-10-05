#!/usr/bin/env python3
"""SV-16 — draw a routing checkpoint to a PNG, one colour per copper layer.

KiCad is not installed here, so this is the only way to look at the board.
It draws the board outline, the footprints, and every track in
routing_state.json coloured by the layer it sits on, with vias on top.

    python3 scripts/sv16_route_render.py
    python3 scripts/sv16_route_render.py --out board.png --scale 9

Needs Pillow.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sv16_board_drc import BOARD_FILE, BOARD_W, BOARD_H      # noqa: E402
from sv16_route import CHECKPOINT                            # noqa: E402

LAYER_COLOUR = {"F.Cu": (210, 45, 45), "In1.Cu": (45, 155, 75),
                "In2.Cu": (215, 155, 40), "B.Cu": (55, 95, 225)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--board", default=str(BOARD_FILE))
    ap.add_argument("--checkpoint", default=str(CHECKPOINT))
    ap.add_argument("--out", default="hardware/sv16_board/routing_preview.png")
    ap.add_argument("--scale", type=float, default=7.0, help="pixels per mm")
    ap.add_argument("--layers", default="F.Cu,In1.Cu,In2.Cu,B.Cu")
    args = ap.parse_args()

    from PIL import Image, ImageDraw
    show = set(args.layers.split(","))

    text = Path(args.board).read_text()
    blocks = []
    i = 0
    while True:
        j = text.find("(footprint ", i)
        if j < 0:
            break
        depth = 0
        k = j
        while k < len(text):
            if text[k] == '(':
                depth += 1
            elif text[k] == ')':
                depth -= 1
                if depth == 0:
                    break
            k += 1
        blocks.append(text[j:k + 1])
        i = k

    w_px, h_px = int(BOARD_W * args.scale), int(BOARD_H * args.scale)
    img = Image.new("RGB", (w_px, h_px), (18, 20, 24))
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, 0, w_px - 1, h_px - 1], outline=(120, 120, 130), width=2)

    def px(x, y):
        return (x * args.scale, (BOARD_H - y) * args.scale)

    # footprints: pads first, then the body outline
    for blk in blocks:
        at = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?', blk)
        if not at:
            continue
        ox, oy = float(at.group(1)), float(at.group(2))
        rot = math.radians(float(at.group(3) or 0))
        for p in re.finditer(
                r'\(pad "([^"]*)"[^\n]*?\(at ([-\d.]+) ([-\d.]+)'
                r'[^\n]*?\(size ([-\d.]+) ([-\d.]+)', blk):
            dx, dy = float(p.group(2)), float(p.group(3))
            pw, ph = float(p.group(4)), float(p.group(5))
            cx = ox + dx * math.cos(rot) - dy * math.sin(rot)
            cy = oy + dx * math.sin(rot) + dy * math.cos(rot)
            x0, y0 = px(cx - pw / 2, cy + ph / 2)
            x1, y1 = px(cx + pw / 2, cy - ph / 2)
            dr.rectangle([x0, y0, x1, y1], fill=(145, 145, 155))
        pts = []
        for m in re.finditer(r'\(fp_line \(start ([-\d.]+) ([-\d.]+)\) '
                             r'\(end ([-\d.]+) ([-\d.]+)\)', blk):
            for ux, uy in ((float(m.group(1)), float(m.group(2))),
                           (float(m.group(3)), float(m.group(4)))):
                X = ox + ux * math.cos(rot) - uy * math.sin(rot)
                Y = oy + ux * math.sin(rot) + uy * math.cos(rot)
                pts.append(px(X, Y))
        if len(pts) > 2:
            dr.polygon(pts, outline=(85, 85, 95))

    # the copper
    data = json.loads(Path(args.checkpoint).read_text())
    for a, b, width, layer, net in data["tracks"]:
        if layer not in show:
            continue
        colour = LAYER_COLOUR.get(layer, (160, 160, 160))
        dr.line([px(a[0], a[1]), px(b[0], b[1])],
                fill=colour, width=max(1, int(width * args.scale * 0.7)))
    for x, y, size, drill, net in data["vias"]:
        r = max(1, int(size * args.scale * 0.35))
        cx, cy = px(x, y)
        dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(225, 225, 235))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print("wrote %s (%dx%d) - %d tracks, %d vias"
          % (out, w_px, h_px, len(data["tracks"]), len(data["vias"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
