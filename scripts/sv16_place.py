#!/usr/bin/env python3
"""Legalise the SV-16 placement: no overlaps, no clearance violations.

The floorplan in `sv16_board_kicad.py` was drawn by hand on a 100 x 100 mm
sheet and parts collide - the first clearance check found 150 pad-to-pad
violations, some at 0.000 mm (which is a short, not a "tight" layout).  Routing
a board whose placement is illegal produces copper that cannot be built, so the
placement is fixed first, against exactly the rules the DRC script checks:

  * pad-to-pad clearance for the two nets' classes (sv16_board_drc.clearance_for)
  * pads at least 0.30 mm inside the board outline
  * no big body (pin header, electrolytic, barrel jack, USB socket ...) sitting
    on top of another part
  * around U1, the 0.5 mm pitch TQFP-144, a 2.4 mm "escape ring": every pin
    needs room for the dogbone stub + via that gets it off the pad row

How it works: parts that must not move are pinned (the FPGA, the mounting
holes, the fiducials, every connector, the switches, the test points).  The
rest are placed one at a time, biggest first, at the free spot nearest to where
the designer drew them; "free" is decided on a 0.25 mm occupancy grid where
each part is stamped as its pad bounding box grown by the worst clearance it
needs.  Disjoint grown boxes mean the real copper is clear with margin, so the
result is legal by construction - and then it is re-checked with the real
geometry (and with the DRC script on the board file) rather than trusted.

    .venv/bin/python scripts/sv16_place.py             # pack, report, write nothing
    .venv/bin/python scripts/sv16_place.py --apply      # write into the generator

Needs `shapely` and `numpy`: KiCad is not installed in this container, so the
geometry has to be done here.  See scripts/README-routing.md.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

import numpy as np
from shapely.ops import nearest_points, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sv16_board_drc import (BOARD_FILE, BOARD_H, BOARD_W, LARGE_BODY_AREA,  # noqa: E402
                            clearance_for, load_board)

ROOT = Path(__file__).resolve().parent.parent
GENERATOR = ROOT / "scripts" / "sv16_board_kicad.py"

PINNED = {
    "U1",                                    # the FPGA is the datum for everything
    "H1", "H2", "H3", "H4",                  # mounting holes: mechanical
    "FID1", "FID2", "FID3", "FID4",          # fiducials: mechanical
    "J1", "J2", "J3", "J4", "J5", "J6", "J7", "J8", "J9", "J10",   # connectors
    "SW1", "SW2",                            # switches: where a finger goes
    "TP1", "TP2", "TP3", "TP4", "TP5", "TP6",  # test points: probe access
}
U1_ESCAPE_RING = 2.4       # mm of clear copper around U1's pad rows
EDGE_MARGIN = 0.35         # pads must be inside this (the DRC wants 0.30)
BODY_GAP = 0.60            # a big body is drawn 0.6 mm outside its pads
SAFETY = 0.05              # headroom
CELL = 0.25                # occupancy grid, mm


class Part:
    """One footprint: its pads (shapely), its body box, its placement."""

    def __init__(self, foot):
        self.ref = foot["ref"]
        self.pads = []
        for pad in foot["pads"]:
            key = pad.net if pad.net else ""
            self.pads.append({"net": pad.net, "pad": pad.pad, "poly": pad.to_polygon(),
                              "key": key if key else "%s.%s" % (pad.ref, pad.pad),
                              "same_net": bool(key)})
        self.body = foot["body"].to_polygon() if foot["body"] is not None else None
        self.body_area = self.body.area if self.body is not None else 0.0
        self.movable = foot["ref"] not in PINNED
        self.x, self.y, self.rot = foot["x"], foot["y"], foot["rot"]
        self.home = (self.x, self.y)
        self.origin = (self.x, self.y)
        self.size = 0.0

    # ---- geometry ----------------------------------------------------------
    def groups(self):
        """[(key, polygon, is_a_net)] - clearance is a question of the two nets."""
        out, singles = {}, []
        for pad in self.pads:
            if pad["same_net"]:
                out.setdefault(pad["key"], []).append(pad["poly"])
            else:
                singles.append((pad["key"], pad["poly"], False))
        return [(key, unary_union(polys), True) for key, polys in out.items()] + singles

    def pad_box(self):
        xs0 = min(p["poly"].bounds[0] for p in self.pads)
        ys0 = min(p["poly"].bounds[1] for p in self.pads)
        xs1 = max(p["poly"].bounds[2] for p in self.pads)
        ys1 = max(p["poly"].bounds[3] for p in self.pads)
        return [xs0, ys0, xs1, ys1]

    def inflation(self):
        """How far the pad box has to be grown for a guaranteed-clear pack.

        Copper: half the worst clearance in the design, so two grown boxes that
        do not touch leave the copper clear.  Big bodies: the body outline is
        0.6 mm outside the pad box, so grow by that instead.  U1: the escape
        ring, because every other part has to stay out of it.
        """
        grow = 0.5 / 2.0 + SAFETY / 2.0
        if self.ref == "U1":
            return max(grow, U1_ESCAPE_RING)
        if self.body_area > LARGE_BODY_AREA:
            return max(grow, BODY_GAP + SAFETY)
        return grow

    def grown_box(self):
        x0, y0, x1, y1 = self.pad_box()
        grow = self.inflation()
        return [x0 - grow, y0 - grow, x1 + grow, y1 + grow]

    def move_to(self, x, y):
        from shapely.affinity import translate
        dx, dy = x - self.origin[0], y - self.origin[1]
        if dx or dy:
            for pad in self.pads:
                pad["poly"] = translate(pad["poly"], dx, dy)
            if self.body is not None:
                self.body = translate(self.body, dx, dy)
            self.origin = (x, y)
        self.x, self.y = x, y


# ------------------------------------------------------------------- packing
class Grid:
    """A 0.25 mm occupancy map of the board with a summed-area table."""

    def __init__(self):
        self.cols = int(round(BOARD_W / CELL))
        self.rows = int(round(BOARD_H / CELL))
        self.occupied = np.zeros((self.rows, self.cols), dtype=np.int8)
        self.parts = []

    def _cell_range(self, box):
        x0 = max(0, int(math.floor(box[0] / CELL)))
        y0 = max(0, int(math.floor(box[1] / CELL)))
        x1 = min(self.cols, int(math.ceil(box[2] / CELL)))
        y1 = min(self.rows, int(math.ceil(box[3] / CELL)))
        return x0, y0, x1, y1

    def stamp(self, box, value=1):
        x0, y0, x1, y1 = self._cell_range(box)
        if x1 > x0 and y1 > y0:
            self.occupied[y0:y1, x0:x1] = value

    def table(self):
        """Summed-area table of the occupancy map (int32: an int8 cumsum wraps)."""
        padded = np.pad(self.occupied.astype(np.int32), ((1, 0), (1, 0)), constant_values=0)
        return padded.cumsum(0).cumsum(1)

    def free_placements(self, width, height, table):
        """Where a width x height box can go: a boolean map the size of the board."""
        cols, rows = self.cols, self.rows
        w = max(1, int(math.ceil(width / CELL)))
        h = max(1, int(math.ceil(height / CELL)))
        if w >= cols or h >= rows:
            return None
        windows = (table[h:, w:] - table[:-h, w:] - table[h:, :-w] + table[:-h, :-w])
        free = windows == 0
        padded = np.zeros((rows, cols), dtype=bool)
        padded[:rows - h + 1, :cols - w + 1] = free
        return padded


def pack(parts, grid):
    """Place the movable parts, biggest first, at the nearest free spot."""
    order = sorted([p for p in parts.values() if p.movable],
                   key=lambda p: -(p.pad_box()[2] - p.pad_box()[0]) *
                   (p.pad_box()[3] - p.pad_box()[1]))
    for part in parts.values():
        if not part.movable:
            grid.stamp(part.grown_box())
            grid.parts.append(part)
    # the outline itself: nothing may sit within EDGE_MARGIN of the edge
    grid.occupied[:int(math.ceil(EDGE_MARGIN / CELL)), :] = 1
    grid.occupied[-int(math.ceil(EDGE_MARGIN / CELL)):, :] = 1
    grid.occupied[:, :int(math.ceil(EDGE_MARGIN / CELL))] = 1
    grid.occupied[:, -int(math.ceil(EDGE_MARGIN / CELL)):] = 1

    moved = []
    for part in order:
        table = grid.table()
        x0, y0, x1, y1 = part.grown_box()
        width, height = x1 - x0, y1 - y0
        free = grid.free_placements(width, height, table)
        if free is None:
            print("  ! %s is bigger than the board" % part.ref)
            continue
        index = np.argwhere(free)
        if len(index) == 0:
            print("  ! no room at all for %s" % part.ref)
            continue
        # A free cell is the *bottom-left corner of the grown box*; turn that
        # into the part's own reference point (the footprint origin).
        corner_x = index[:, 1] * CELL
        corner_y = index[:, 0] * CELL
        grow = part.inflation()
        offset_x = part.pad_box()[0] - part.x        # pads are not centred on the origin
        offset_y = part.pad_box()[1] - part.y
        origin_x = corner_x - offset_x + grow
        origin_y = corner_y - offset_y + grow
        distance = (origin_x - part.home[0]) ** 2 + (origin_y - part.home[1]) ** 2
        # prefer the nearest legal spot, then the one that moved least
        best = int(np.argmin(distance))
        new_x = float(origin_x[best])
        new_y = float(origin_y[best])
        if abs(new_x - part.x) > 1e-9 or abs(new_y - part.y) > 1e-9:
            moved.append((math.hypot(new_x - part.home[0], new_y - part.home[1]), part.ref))
        part.move_to(new_x, new_y)
        grid.stamp(part.grown_box())
        grid.parts.append(part)
    return moved


# ------------------------------------------------------- exact verification
def scan(parts):
    """Every violation of the current placement, with exact geometry."""
    problems = []
    items = list(parts.values())
    for index, pa in enumerate(items):
        for pb in items[index + 1:]:
            for key_a, poly_a, net_a in pa.groups():
                for key_b, poly_b, net_b in pb.groups():
                    if net_a and net_b and key_a == key_b:
                        continue                      # same net: no clearance needed
                    required = clearance_for(key_a if net_a else None,
                                             key_b if net_b else None)
                    if pa.ref == "U1" or pb.ref == "U1":
                        required = max(required, U1_ESCAPE_RING)
                    required += SAFETY
                    distance = poly_a.distance(poly_b)
                    if distance < required:
                        problems.append((pa.ref, pb.ref, distance, required,
                                         "%s / %s" % (key_a, key_b)))
            if pa.body is not None and pb.body is not None \
                    and max(pa.body_area, pb.body_area) > LARGE_BODY_AREA:
                if pa.body.distance(pb.body) <= 0.02:
                    problems.append((pa.ref, pb.ref, pa.body.distance(pb.body), 0.02, "bodies"))
    return problems


def snap(parts, grid=0.01):
    for part in parts.values():
        if part.movable:
            part.move_to(round(part.x / grid) * grid, round(part.y / grid) * grid)


def write_back(parts) -> int:
    text = GENERATOR.read_text()
    changed = 0
    for ref, part in sorted(parts.items()):
        pattern = re.compile(r'("%s": \()(-?[\d.]+), (-?[\d.]+), (-?[\d.]+)(\))' % re.escape(ref))

        def swap(match, part=part):
            nonlocal changed
            new_x, new_y = "%.2f" % part.x, "%.2f" % part.y
            if match.group(2) == new_x and match.group(3) == new_y:
                return match.group(0)
            changed += 1
            return match.group(1) + new_x + ", " + new_y + ", " + match.group(4) + match.group(5)
        text = pattern.sub(swap, text)
    if changed:
        GENERATOR.write_text(text)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the result into the generator")
    parser.add_argument("--board", default=str(BOARD_FILE))
    args = parser.parse_args()

    load = load_board(args.board)
    parts = {foot["ref"]: Part(foot) for foot in load[1]}
    print("legalising %d footprints (%d movable, %d pinned)"
          % (len(parts), sum(1 for p in parts.values() if p.movable),
             sum(1 for p in parts.values() if not p.movable)))

    grid = Grid()
    moved = pack(parts, grid)
    snap(parts)
    problems = scan(parts)
    print("  parts that moved: %d (max %.2f mm%s)"
          % (len(moved), moved[0][0] if moved else 0.0,
             ", e.g. " + ", ".join(r for _, r in moved[:5]) if moved else ""))
    print("  violations after packing (exact geometry): %d" % len(problems))
    for hit in problems[:12]:
        print("    %s / %s  %.3f < %.3f (%s)" % hit)

    if args.apply and not problems:
        count = write_back(parts)
        print("  wrote %d placements back into scripts/sv16_board_kicad.py" % count)
        print("\nregenerate and re-check with:")
        print("  python3 scripts/sv16_board_kicad.py && python3 scripts/sv16_board_drc.py")
    elif args.apply:
        print("  NOT writing while violations remain")
    else:
        print("  (dry run - nothing written; pass --apply to keep this placement)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
