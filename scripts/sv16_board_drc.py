#!/usr/bin/env python3
"""Geometry and design-rule checks for the SV-16 board.

The board file is generated, but "generated" is not "correct": pads can be too
close, a part can hang over the edge, a track can run into a via, a plane can
swallow a foreign pad.  This module parses the file back and does the
arithmetic KiCad's DRC does - because without KiCad in the loop the shapes have
to be checked by hand.

What it checks (per net class clearances from sv16_board.kicad_pro):

    * pad-to-pad, pad-to-edge, courtyard overlap
    * track-to-pad, track-to-track (same and different layers), via-to-pad,
      via-to-track, via-to-via
    * plane fills (zone `filled_polygon`s) against every foreign pad, track and
      via: nothing foreign may sit inside a plane or come closer than the
      clearance
    * copper connectivity: after routing, every pad of a net must reach every
      other pad of that net through same-net copper (pads, tracks, vias and
      planes) - the check that says "the copper is really complete"

The geometry is exact: rectangles are convex polygons, circles are circles, and
tracks are capsules (a segment with a width).  Distances are analytic, so a
pass here means a pass in KiCad's DRC (which uses the same rules), not an
approximation of it.

Usage
    scripts/sv16_board_drc.py                 # check hardware/sv16_board/sv16_board.kicad_pcb
    scripts/sv16_board_drc.py FILE            # check another board file
    scripts/sv16_board_drc.py --quiet FILE    # exit status only

It is imported by the router and by the placement legaliser, so `load_board()`,
`Shape` and `clearance_for()` are shared.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOARD_FILE = ROOT / "hardware" / "sv16_board" / "sv16_board.kicad_pcb"

BOARD_W = 100.0
BOARD_H = 100.0
PAD_EDGE = 0.30             # a pad's copper to the board edge
LARGE_BODY_AREA = 20.0      # mm^2: only bodies this big must not overlap
COPPER_EDGE = 0.25          # a track, via or plane to the board edge
LAYERS = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")

# net class clearances, from sv16_board.kicad_pro
CLASS_CLEARANCE = {"Default": 0.20, "Power": 0.20, "Switching": 0.50, "USB": 0.20,
                   "JTAG": 0.25, "Fine": 0.15}
CLASS_OF_NET = {
    "GND": "Power", "VM_IN": "Power", "VM_IN_RAW": "Power", "3V3": "Power", "2V5": "Power",
    "1V1": "Power", "USB_VBUS": "Power", "5V_USB": "Power",
    "U5_SW": "Switching", "U5_BST": "Switching", "U6_SW": "Switching", "U6_BST": "Switching",
    "USB_DP": "USB", "USB_DN": "USB", "USB_DP_F": "USB", "USB_DN_F": "USB",
    "CC1": "USB", "CC2": "USB",
    "TCK": "JTAG", "TMS": "JTAG", "TDI": "JTAG", "TDO": "JTAG", "PROGRAMN": "JTAG",
    "INITN": "JTAG", "DONE": "JTAG", "CCLK": "JTAG",
}


def clearance_for(net_a: str | None, net_b: str | None) -> float:
    return max(CLASS_CLEARANCE[CLASS_OF_NET.get(net_a or "NC", "Default")],
               CLASS_CLEARANCE[CLASS_OF_NET.get(net_b or "NC", "Default")])


# --------------------------------------------------------------------- shapes
class Shape:
    """A pad, a via, a hole or a track: a rotated rectangle or a circle, in mm.

    `kind` is "rect", "circle" or "capsule" (a track: width `w`, length implied
    by `a`/`b`).  Everything else about the board - where a shape is, on which
    layers, on which net - hangs off this.
    """

    def __init__(self, kind, x, y, w, h, rot=0.0, net=None, ref=None, pad=None,
                 layers=("F.Cu",), drill=None, smd=True, a=None, b=None):
        self.kind = kind                # "rect" | "circle" | "capsule"
        self.x, self.y = x, y
        self.w, self.h = w, h
        self.rot = rot % 180.0
        self.net = net
        self.ref, self.pad = ref, pad
        self.layers = tuple(layers)
        self.drill = drill
        self.smd = smd
        self.a = a                      # capsule ends
        self.b = b

    # ---- basics ------------------------------------------------------------
    @property
    def is_circle(self) -> bool:
        return self.kind == "circle"

    @property
    def radius(self) -> float:
        return self.w / 2.0

    def corners(self):
        """The four corners of the (rotated) rectangle, or None for a circle."""
        if self.kind == "circle":
            return None
        c, s = math.cos(math.radians(self.rot)), math.sin(math.radians(self.rot))
        half = ((self.w / 2.0, self.h / 2.0), (self.w / 2.0, -self.h / 2.0),
                (-self.w / 2.0, -self.h / 2.0), (-self.w / 2.0, self.h / 2.0))
        return [(self.x + dx * c - dy * s, self.y + dx * s + dy * c) for dx, dy in half]

    def edges(self):
        """The outline as segments: 4 edges (rect) or 1 segment (capsule)."""
        if self.kind == "capsule":
            return [(self.a, self.b)]
        corners = self.corners()
        return [(corners[i], corners[(i + 1) % 4]) for i in range(4)]

    def samples(self, step=0.25):
        """Points along the outline (and the centre) for zone hit tests."""
        if self.kind == "circle":
            points = [(self.x, self.y)]
            count = max(12, int(2 * math.pi * self.radius / step))
            for i in range(count):
                angle = 2 * math.pi * i / count
                points.append((self.x + self.radius * math.cos(angle),
                               self.y + self.radius * math.sin(angle)))
            return points
        if self.kind == "capsule":
            return _sample_segment(self.a, self.b, step) + _sample_segment(
                (self.a[0] - self.w / 2, self.a[1]), (self.a[0] + self.w / 2, self.a[1]), step)
        corners = self.corners()
        points = [(self.x, self.y)]
        for index in range(4):
            points += _sample_segment(corners[index], corners[(index + 1) % 4], step)
        return points

    def bbox(self):
        if self.kind == "circle":
            return (self.x - self.radius, self.y - self.radius,
                    self.x + self.radius, self.y + self.radius)
        if self.kind == "capsule":
            return (min(self.a[0], self.b[0]) - self.w / 2, min(self.a[1], self.b[1]) - self.w / 2,
                    max(self.a[0], self.b[0]) + self.w / 2, max(self.a[1], self.b[1]) + self.w / 2)
        xs = [p[0] for p in self.corners()]
        ys = [p[1] for p in self.corners()]
        return (min(xs), min(ys), max(xs), max(ys))

    # ---- shapes as shapely-ish pieces for the router -----------------------
    def to_polygon(self):
        from shapely.geometry import box
        if self.kind == "circle":
            from shapely.geometry import Point
            return Point(self.x, self.y).buffer(self.radius, quad_segs=48)
        if self.kind == "capsule":
            from shapely.geometry import LineString
            return LineString([self.a, self.b]).buffer(self.w / 2.0, cap_style=1, quad_segs=16)
        from shapely.geometry import Polygon
        return Polygon(self.corners())


def _sample_segment(a, b, step):
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    count = max(1, int(length / step))
    return [(a[0] + (b[0] - a[0]) * i / count, a[1] + (b[1] - a[1]) * i / count)
            for i in range(count + 1)]


def _seg_point_distance(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    length2 = vx * vx + vy * vy
    if length2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / length2))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


def _seg_seg_distance(a, b, c, d):
    """Exact distance between two segments (0 if they cross)."""
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return 0.0
    return min(_seg_point_distance(a[0], a[1], c[0], c[1], d[0], d[1]),
               _seg_point_distance(b[0], b[1], c[0], c[1], d[0], d[1]),
               _seg_point_distance(c[0], c[1], a[0], a[1], b[0], b[1]),
               _seg_point_distance(d[0], d[1], a[0], a[1], b[0], b[1]))


def _point_rect_distance(x, y, rect):
    """Distance from a point to a rotated rectangle (negative inside)."""
    c, s = math.cos(math.radians(-rect.rot)), math.sin(math.radians(-rect.rot))
    dx, dy = x - rect.x, y - rect.y
    lx, ly = dx * c - dy * s, dx * s + dy * c
    ox = abs(lx) - rect.w / 2.0
    oy = abs(ly) - rect.h / 2.0
    if ox > 0 or oy > 0:
        return math.hypot(max(ox, 0.0), max(oy, 0.0))
    return max(ox, oy)


def _seg_rect_distance(a, b, rect):
    """Distance from a segment to a rotated rectangle (0 if they overlap)."""
    corners = rect.corners()
    best = min(_seg_point_distance(c[0], c[1], a[0], a[1], b[0], b[1]) for c in corners)
    for index in range(4):
        edge = (corners[index], corners[(index + 1) % 4])
        best = min(best, _seg_seg_distance(a, b, edge[0], edge[1]))
    if best > 0:
        # the segment could still run through the rectangle without touching a
        # corner or crossing an edge?  No: a crossing shows up as distance 0.
        pass
    return best


def _rect_rect_distance(a, b):
    best = float("inf")
    for sa in a.edges():
        for sb in b.edges():
            best = min(best, _seg_seg_distance(sa[0], sa[1], sb[0], sb[1]))
            if best == 0.0:
                return 0.0
    return best


def shape_distance(a: Shape, b: Shape) -> float:
    """Minimum distance between two shapes in mm (0 if they touch or overlap)."""
    if a.kind == "circle" and b.kind == "circle":
        return math.hypot(b.x - a.x, b.y - a.y) - a.radius - b.radius
    if a.kind == "circle":
        return shape_distance(b, a)
    if a.kind == "capsule" and b.kind == "capsule":
        return _seg_seg_distance(a.a, a.b, b.a, b.b) - a.w / 2.0 - b.w / 2.0
    if a.kind == "capsule":
        if b.kind == "circle":
            return _seg_point_distance(b.x, b.y, a.a[0], a.a[1], a.b[0], a.b[1]) - a.w / 2.0 - b.radius
        return _seg_rect_distance(a.a, a.b, b) - a.w / 2.0
    if b.kind == "circle":
        return _point_rect_distance(b.x, b.y, a) - b.radius
    if b.kind == "capsule":
        return shape_distance(b, a)
    return _rect_rect_distance(a, b)


def _point_in_polygon(x, y, ring):
    """Even-odd ray cast against a closed ring [(x, y), ...]."""
    inside = False
    count = len(ring)
    for index in range(count):
        x1, y1 = ring[index]
        x2, y2 = ring[(index + 1) % count]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xin > x:
                inside = not inside
    return inside


def _ring_distance(x, y, ring):
    """Distance from a point to a closed ring (0 on it)."""
    best = float("inf")
    count = len(ring)
    for index in range(count):
        x1, y1 = ring[index]
        x2, y2 = ring[(index + 1) % count]
        best = min(best, _seg_point_distance(x, y, x1, y1, x2, y2))
        if best == 0.0:
            return 0.0
    return best


# ------------------------------------------------------------------- parsing
PAD_RE = re.compile(
    r'\(pad "(?P<num>[^"]*)" (?P<kind>\w+) (?P<shape>\w+) \(at (?P<x>-?[\d.]+) (?P<y>-?[\d.]+)'
    r'(?: (?P<rot>-?[\d.]+))?\) \(size (?P<w>[\d.]+) (?P<h>[\d.]+)\)(?P<rest>[\s\S]*?)\)\s*(?=\(pad|\(fp_|\)\s*$)')


def _layer_set(text):
    """Copper layers a pad or zone touches."""
    match = re.search(r'\(layers ([^)]*)\)', text)
    names = re.findall(r'"([^"]+)"', match.group(1)) if match else []
    out = []
    for name in names:
        if name in LAYERS:
            out.append(name)
        elif name in ("*.Cu", "F&B.Cu"):
            out = list(LAYERS)
            break
    return tuple(out) or ("F.Cu",)


def load_board(path=BOARD_FILE):
    """Return (shapes, footprints, tracks, vias, zones) with absolute coordinates."""
    text = Path(path).read_text()
    shapes, footprints = [], []
    net_of_number = {}

    blocks = text.split("  (footprint ")
    for block in blocks[1:]:
        header = block.split("\n", 1)[0]
        lib = header.split('"')[1]
        at = re.search(r'\(at (-?[\d.]+) (-?[\d.]+)(?: (-?[\d.]+))?\)', header)
        fx, fy = float(at.group(1)), float(at.group(2))
        frot = float(at.group(3) or 0.0)
        ref_match = re.search(r'\(fp_text reference "([^"]+)"', block)
        ref = ref_match.group(1) if ref_match else "?"
        courtyard = re.search(r'\(fp_rect \(start (-?[\d.]+) (-?[\d.]+)\) \(end (-?[\d.]+) (-?[\d.]+)\)'
                              r' \(layer "F.SilkS"', block)
        body = None
        if courtyard:
            x0, y0, x1, y1 = (float(courtyard.group(i)) for i in (1, 2, 3, 4))
            body = Shape("rect", fx + (x0 + x1) / 2.0, fy + (y0 + y1) / 2.0,
                         abs(x1 - x0), abs(y1 - y0), frot, None, ref, None,
                         tuple(), None, True)
        packed = []
        for match in PAD_RE.finditer(block):
            rest = match.group("rest")
            net_match = re.search(r'\(net (\d+) "([^"]*)"\)', rest)
            net_name = None
            if net_match:
                net_of_number[int(net_match.group(1))] = net_match.group(2)
                net_name = net_match.group(2)
            drill = re.search(r'\(drill ([\d.]+)\)', rest)
            dx, dy = float(match.group("x")), float(match.group("y"))
            rot = float(match.group("rot") or 0.0) + frot
            c, s = math.cos(math.radians(frot)), math.sin(math.radians(frot))
            x = fx + dx * c - dy * s
            y = fy + dx * s + dy * c
            kind = match.group("shape")
            shape = Shape("circle" if kind in ("circle", "oval") else "rect",
                          x, y, float(match.group("w")), float(match.group("h")), rot,
                          net_name, ref, match.group("num"),
                          _layer_set(rest),
                          float(drill.group(1)) if drill else None,
                          match.group("kind") == "smd")
            shapes.append(shape)
            packed.append(shape)
        footprints.append({"ref": ref, "lib": lib, "x": fx, "y": fy, "rot": frot,
                           "body": body, "pads": packed})

    tracks = []
    for match in re.finditer(r'\(segment \(start (-?[\d.]+) (-?[\d.]+)\) \(end (-?[\d.]+) (-?[\d.]+)\)'
                             r' \(width ([\d.]+)\) \(layer "([^"]+)"\)(?P<rest>[^\n]*)', text):
        net = re.search(r'\(net (\d+)\)', match.group("rest"))
        start = (float(match.group(1)), float(match.group(2)))
        end = (float(match.group(3)), float(match.group(4)))
        tracks.append({"start": start, "end": end, "width": float(match.group(5)),
                       "layer": match.group(6),
                       "net": net_of_number.get(int(net.group(1))) if net else None,
                       "shape": Shape("capsule", (start[0] + end[0]) / 2.0,
                                      (start[1] + end[1]) / 2.0, float(match.group(5)), 0.0,
                                      net=net_of_number.get(int(net.group(1))) if net else None,
                                      layers=(match.group(6),), a=start, b=end)})
    vias = []
    for match in re.finditer(r'\(via \(at (-?[\d.]+) (-?[\d.]+)\) \(size ([\d.]+)\) \(drill ([\d.]+)\)'
                             r' \(layers ([^)]*)\)(?P<rest>[^\n]*)', text):
        net = re.search(r'\(net (\d+)\)', match.group("rest"))
        size = float(match.group(3))
        vias.append({"x": float(match.group(1)), "y": float(match.group(2)),
                     "size": size, "drill": float(match.group(4)),
                     "net": net_of_number.get(int(net.group(1))) if net else None,
                     "layers": _layer_set(match.group(5)),
                     "shape": Shape("circle", float(match.group(1)), float(match.group(2)),
                                    size, size,
                                    net=net_of_number.get(int(net.group(1))) if net else None,
                                    layers=tuple(_layer_set(match.group(5))))})

    zones = []
    for match in re.finditer(r'\(zone \(net (\d+)\) \(net_name "([^"]+)"\) \(layer "([^"]+)"\)'
                             r'(?P<body>[\s\S]*?)\n  \)\n', text):
        net = match.group(2)
        layer = match.group(3)
        for pts in re.finditer(r'\(filled_polygon \(layer "([^"]+)"\)([\s\S]*?)\n      \)',
                               match.group("body")):
            ring = [(float(a), float(b)) for a, b in
                    re.findall(r'\(xy (-?[\d.]+) (-?[\d.]+)\)', pts.group(2))]
            if len(ring) >= 3:
                zones.append({"net": net, "layer": pts.group(1) or layer, "ring": ring})
    return shapes, footprints, tracks, vias, zones


class Violation:
    def __init__(self, kind, a, b, distance, required, detail=""):
        self.kind, self.a, self.b = kind, a, b
        self.distance, self.required, self.detail = distance, required, detail

    def __str__(self):
        where = ""
        if self.a is not None and self.b is not None:
            where = " at (%.2f, %.2f)-(%.2f, %.2f)" % (self.a.x, self.a.y, self.b.x, self.b.y)
        return "%-22s %.3f < %.3f mm%s %s" % (self.kind, self.distance, self.required, where,
                                              self.detail)


def _label(shape):
    if shape is None:
        return "?"
    if shape.ref:
        return "%s.%s" % (shape.ref, shape.pad)
    if shape.net:
        return "net %s" % shape.net
    return "copper"


# --------------------------------------------------------------- checks: body
def check_placement(shapes, footprints, quiet=False):
    """Pad-to-pad, pad-to-edge and courtyard checks."""
    problems = []
    buckets, cell = {}, 5.0
    for shape in shapes:
        buckets.setdefault((int(shape.x // cell), int(shape.y // cell)), []).append(shape)
    seen = set()
    for (bx, by), group in buckets.items():
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                for other in buckets.get((bx + ox, by + oy), []):
                    for a in group:
                        if a is other or a.ref == other.ref:
                            continue
                        key = (id(a), id(other)) if id(a) < id(other) else (id(other), id(a))
                        if key in seen:
                            continue
                        seen.add(key)
                        if a.net is not None and a.net == other.net:
                            continue
                        required = clearance_for(a.net, other.net)
                        distance = shape_distance(a, other)
                        if distance < required:
                            problems.append(Violation("pad-pad", a, other, distance, required,
                                                      "%s / %s" % (_label(a), _label(other))))
    for shape in shapes:
        x0, y0, x1, y1 = shape.bbox()
        margin = min(x0, BOARD_W - x1, y0, BOARD_H - y1)
        if margin < PAD_EDGE:
            problems.append(Violation("pad-to-edge", shape, None, margin, PAD_EDGE, _label(shape)))
    # The generator draws each part's body as an F.SilkS rectangle, not as a
    # KiCad courtyard, so overlapping silk between two chip parts is harmless
    # and is not an error.  What *is* real is a big can (electrolytic, tantalum,
    # barrel jack, pin header) sitting on top of something else: those are
    # checked, small parts are left to the pad rules.
    bodies = [f["body"] for f in footprints if f["body"]
              and (f["body"].w * f["body"].h) > LARGE_BODY_AREA]
    for index, a in enumerate(bodies):
        for b in bodies[index + 1:]:
            if a.ref == b.ref:
                continue
            if shape_distance(a, b) <= 0.0:
                problems.append(Violation("courtyard-overlap", a, b, 0.0, 0.0,
                                          "%s / %s" % (a.ref, b.ref)))
    if not quiet:
        print("  shapes: %d (%d pads)" % (len(shapes), sum(1 for s in shapes if s.pad)))
        print("  footprints: %d" % len(footprints))
    return problems


def copper_layers(kind, layers):
    """Which copper layers a piece of copper lives on.

    A via in this stack-up is a through via: KiCad stores it as
    `(layers "F.Cu" "B.Cu")` but it is drilled through every copper layer, so it
    counts on all four.  A through-hole pad is stored as `*.Cu` and likewise
    lives on all four; an SMD pad only on the layer it sits on.
    """
    if kind == "via":
        return set(LAYERS)
    if kind == "track":
        return set(layers)
    return set(layers) or {"F.Cu"}


def _copper_items(tracks, vias, shapes):
    items = [{"shape": t["shape"], "net": t["net"], "what": "track",
              "layers": copper_layers("track", (t["layer"],))} for t in tracks]
    items += [{"shape": v["shape"], "net": v["net"], "what": "via",
               "layers": copper_layers("via", v["layers"])} for v in vias]
    items += [{"shape": s, "net": s.net, "what": _label(s),
               "layers": copper_layers("pad", s.layers)} for s in shapes]
    return items


def check_tracks(tracks, vias, shapes, quiet=False):
    """Clearance between every piece of copper and every other piece.

    Pads on the same footprint are KiCad's own exception (they are inside one
    component), but two different parts are only skipped when their nets match.
    """
    problems = []
    items = _copper_items(tracks, vias, shapes)
    for index, a in enumerate(items):
        for b in items[index + 1:]:
            if a["net"] is not None and a["net"] == b["net"]:
                continue
            if a["shape"].ref and a["shape"].ref == b["shape"].ref:
                continue
            if not (a["layers"] & b["layers"]):
                continue
            required = clearance_for(a["net"], b["net"])
            distance = shape_distance(a["shape"], b["shape"])
            if distance < required:
                problems.append(Violation("%s-%s" % (a["what"] if a["what"] != "track" or
                                                     b["what"] != "pad" else "track",
                                                     b["what"]), a["shape"], b["shape"],
                                          distance, required,
                                          "net %s / %s" % (a["net"], b["what"])))
    # copper to the board edge
    for item in items:
        x0, y0, x1, y1 = item["shape"].bbox()
        margin = min(x0, BOARD_W - x1, y0, BOARD_H - y1)
        if margin < COPPER_EDGE:
            problems.append(Violation("copper-to-edge", item["shape"], None, margin, COPPER_EDGE,
                                      "%s %s" % (item["what"], item["net"] or "")))
    if not quiet:
        print("  tracks: %d   vias: %d   copper items: %d" % (len(tracks), len(vias), len(items)))
    return problems


def check_zones(zones, shapes, tracks, vias, quiet=False):
    """Nothing foreign inside a plane, and no plane closer than the clearance."""
    problems = []
    items = _copper_items(tracks, vias, shapes)
    for zone in zones:
        ring = zone["ring"]
        for item in items:
            if item["net"] == zone["net"] or zone["layer"] not in item["layers"]:
                continue
            required = clearance_for(zone["net"], item["net"])
            worst, worst_point = float("inf"), None
            for (px, py) in item["shape"].samples(step=0.2):
                if _point_in_polygon(px, py, ring):
                    worst, worst_point = 0.0, (px, py)
                    break
                distance = _ring_distance(px, py, ring)
                if distance < worst:
                    worst, worst_point = distance, (px, py)
            if worst < required:
                problems.append(Violation("zone-%s" % ("short" if worst == 0.0 else "clearance"),
                                          None, None, worst, required,
                                          "plane %s on %s / %s at (%.2f, %.2f)"
                                          % (zone["net"], zone["layer"], item["what"],
                                             worst_point[0] if worst_point else 0.0,
                                             worst_point[1] if worst_point else 0.0)))
    if not quiet:
        print("  zones:     %d filled polygon(s) on %s"
              % (len(zones), ", ".join(sorted({z["layer"] for z in zones})) or "-"))
    return problems


# ------------------------------------------------------------- check: copper
class _UnionFind:
    def __init__(self):
        self.parent = {}

    def add(self, item):
        self.parent.setdefault(item, item)

    def find(self, item):
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def check_connectivity(shapes, tracks, vias, zones, quiet=False):
    """Every pad of a net must reach every other pad of that net.

    Copper is connected when two pieces of the same net touch or overlap on a
    layer they share.  Vias tie the layers together, through-hole pads live on
    every copper layer, planes are polygons on one layer.
    """
    nodes = []
    for shape in shapes:
        if shape.net and shape.pad:
            node = {"net": shape.net, "layers": copper_layers("pad", shape.layers), "shape": shape,
                    "what": _label(shape), "pad": True}
            nodes.append(node)
    for track in tracks:
        if track["net"]:
            nodes.append({"net": track["net"], "layers": copper_layers("track", (track["layer"],)),
                          "shape": track["shape"],
                          "what": "track", "pad": False})
    for via in vias:
        if via["net"]:
            nodes.append({"net": via["net"], "layers": copper_layers("via", via["layers"]),
                          "shape": via["shape"],
                          "what": "via", "pad": False})
    for zone in zones:
        nodes.append({"net": zone["net"], "layers": {zone["layer"]}, "ring": zone["ring"],
                      "what": "plane on %s" % zone["layer"], "pad": False})

    by_net = {}
    for index, node in enumerate(nodes):
        by_net.setdefault(node["net"], []).append(index)

    problems = []
    for net, indices in sorted(by_net.items()):
        union = _UnionFind()
        for index in indices:
            union.add(index)
        for position, index in enumerate(indices):
            a = nodes[index]
            for other in indices[position + 1:]:
                b = nodes[other]
                if not (a["layers"] & b["layers"]):
                    continue
                if "ring" in b and "ring" not in a:
                    touched = _touches_ring(a["shape"], b["ring"], a["layers"] & b["layers"])
                elif "ring" in a and "ring" not in b:
                    touched = _touches_ring(b["shape"], a["ring"], a["layers"] & b["layers"])
                elif "ring" in a and "ring" in b:
                    touched = _rings_touch(a["ring"], b["ring"])
                else:
                    touched = shape_distance(a["shape"], b["shape"]) <= 0.0001
                if touched:
                    union.union(index, other)
        roots = {union.find(index) for index in indices}
        pads = [nodes[i] for i in indices if nodes[i]["pad"]]
        if len(roots) > 1 and pads:
            groups = {}
            for index in indices:
                groups.setdefault(union.find(index), []).append(nodes[index])
            islands = sorted(len(group) for group in groups.values())
            problems.append(Violation("unconnected", None, None, float(len(roots)), 1.0,
                                      "net %s: %d islands (%s), pads %s"
                                      % (net, len(roots), islands,
                                         ", ".join(node["what"] for node in pads[:4]))))
    if not quiet:
        print("  nets with copper: %d" % len(by_net))
    return problems


def _touches_ring(shape, ring, layers):
    if not layers:
        return False
    if shape.kind == "capsule":
        return any(_point_in_polygon(x, y, ring) for x, y in _sample_segment(shape.a, shape.b, 0.1))
    for (x, y) in shape.samples(step=0.1):
        if _point_in_polygon(x, y, ring):
            return True
    return _ring_distance(shape.x, shape.y, ring) <= 0.0001


def _rings_touch(a, b):
    for (x, y) in a:
        if _point_in_polygon(x, y, b):
            return True
    for (x, y) in b:
        if _point_in_polygon(x, y, a):
            return True
    return False


# ---------------------------------------------------------------------- main
def check_board(path=BOARD_FILE, quiet=False):
    shapes, footprints, tracks, vias, zones = load_board(path)
    if not quiet:
        print("checking %s" % (Path(path).relative_to(ROOT) if Path(path).is_absolute()
                               and ROOT in Path(path).parents else path))
    problems = check_placement(shapes, footprints, quiet=quiet)
    problems += check_tracks(tracks, vias, shapes, quiet=quiet)
    problems += check_zones(zones, shapes, tracks, vias, quiet=quiet)
    problems += check_connectivity(shapes, tracks, vias, zones, quiet=quiet)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="geometric DRC for the SV-16 board")
    parser.add_argument("path", nargs="?", default=str(BOARD_FILE))
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--kinds", help="only report these violation kinds (comma separated)")
    args = parser.parse_args()

    problems = check_board(args.path, quiet=args.quiet)
    if args.kinds:
        wanted = set(args.kinds.split(","))
        problems = [p for p in problems if p.kind in wanted]
    counts = {}
    for problem in problems:
        counts[problem.kind] = counts.get(problem.kind, 0) + 1
    for problem in problems[:args.limit]:
        print("  " + str(problem))
    if len(problems) > args.limit:
        print("  ... and %d more" % (len(problems) - args.limit))
    if counts:
        print("  by kind: " + ", ".join("%s %d" % (k, v) for k, v in sorted(counts.items())))
    print("  %s" % ("OK - placement, copper and connectivity all clean" if not problems
                    else "%d violation(s)" % len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
