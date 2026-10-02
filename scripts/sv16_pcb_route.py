#!/usr/bin/env python3
"""Route the SV-16 board: a maze router for every signal net.

The board generator (`sv16_board_kicad.py`) places the parts and the copper
plan (`sv16_pcb_copper.py`) drops the rail pours, the escape vias and the
stitching.  What is left is the signal routing, and that is this file.

How it works
------------

* **Grid.** The board is rasterised at 0.1 mm.  Cell centres sit at
  `(i + 0.5) * 0.1 mm`, which puts every 0.05 mm multiple on a cell centre - the
  TQFP-144's 0.5 mm pad pitch included - so a fan-out track leaves a pad
  exactly along the pad's centre line.

* **Masks, as big integers.**  Per layer the grid keeps the *net id* of each
  cell and one halo mask per track width ("some copper is within
  `clearance + width/2` of this cell"), plus a via halo.  A track of net *n*
  may only use a cell whose halo is clear: the halo is the union over *all*
  copper, because copper of the same net is a track just the same, and the
  0.2 mm rule has to hold against the neighbour's pad, not just against its
  centre.  The masks are combined with big-integer arithmetic
  (`int.from_bytes` + `&`/`|`), so a net's passable map costs about a
  millisecond rather than a Python loop over a million cells.

* **Escape corridors.**  A strict halo leaves a pad surrounded by its
  neighbours' halos with no passable cell at all - exactly the QFP fan-out.
  `escape_cells()` walks out of every pad in the four axis directions, checks
  each step against the *real* geometry of every nearby item, and opens the
  cells it verified.  That is the only way a cell is ever opened, so the
  router never trusts the raster where the raster is too coarse.

* **A\\* over (layer, x, y)**, four-way moves, vias priced at 1.6 mm so the
  router only changes layer when it has to.  Two signal layers are used
  (`F.Cu`, `B.Cu`); `In1.Cu` stays a solid ground plane and `In2.Cu` stays the
  rail pours, which is what the stack-up promises.  A via may drop where the
  via halo is clear, or inside the net's own copper when the real geometry
  says it is 0.2 mm clear of everything foreign.

* **Per net**: the pads, tracks and vias already on that net are grouped into
  components (touching copper is one component; a via or a through-hole pad
  inside the net's own pour - or anywhere, for the ground plane - joins that
  pour's island, which is what makes the plane part of the net), then the
  components are joined cheapest-first with A\\*.  Nets whose pour does not
  cover their pads get pour-entry cells as extra targets, so a rail is
  finished by dropping a via into its own pour.

* **Then it checks itself.**  `verify()` is a geometric DRC over every item on
  the board (pads, planned stubs and vias, new tracks, new vias): different
  nets closer than 0.2 mm, or copper off the board.  `connectivity()` is a
  union-find over the same geometry and reports any net whose pads are not all
  joined.  The result goes to `hardware/sv16_board/routing.json`, which the
  board generator reads; a routing that fails either check is still written,
  but `make pcb-check` then fails, so it cannot be shipped by accident.

Usage
    scripts/sv16_pcb_route.py                 # route everything, write routing.json
    scripts/sv16_pcb_route.py --report        # print the routing report
    scripts/sv16_pcb_route.py --nets CCLK,TCK # route only these nets (debugging)
    scripts/sv16_pcb_route.py --no-write      # dry run
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sv16_board_kicad as board      # noqa: E402
import sv16_pcb_copper as copper      # noqa: E402

OUT = ROOT / "hardware" / "sv16_board"
ROUTING_FILE = OUT / "routing.json"

# ------------------------------------------------------------------ constants
G = 0.1                      # mm per cell
W = int(round(board.BOARD_W / G))
H = int(round(board.BOARD_H / G))
N = W * H

CLEARANCE = 0.15             # mm, the rule this router keeps.  0.15 mm is
                              # JLCPCB's standard 4-layer clearance and it
                              # is what lets a 0.5 mm QFP ring fan out at
                              # all: two 0.2 mm tracks fit between two
                              # neighbouring pads, and at 0.20 mm they do not
CLEARANCE_TOLERANCE = 0.005   # mm the DRC forgives, and so must the probes: a
                              # cell at 0.1993 mm is inside the rule's rounding,
                              # and rejecting it throws away routes the finished
                              # board is allowed to have
VIA_DIA = 0.45
VIA_DRILL = 0.20
STEP_COST = 10               # A* cost of one 0.1 mm step (and the unit of the heuristic)
VIA_COST = 16                # 1.6 mm - makes the router prefer a detour to a via pair
EDGE_MARGIN = 0.30           # mm of copper-free border at the board edge
HALO_MARGIN = 0.0            # mm of slack on top of clearance + half the track.
                             # Zero on purpose: the mask must be *sound* (a cell
                             # it frees really takes the track), and every
                             # hundredth of a millimetre here is a ring of cells
                             # the router may not use.

DEFAULT_WIDTH = 0.20
NET_WIDTH = {
    "VM_IN": 0.80, "VM_IN_RAW": 0.80,
    # the USB-C VBUS pads are 0.3 mm wide on a 0.5 mm pitch, with 0.2 mm to
    # their neighbours: 0.25 mm is the widest track that can leave them, and
    # four parallel pads (A4/A9/B4/B9) carry the current between them
    "USB_VBUS": 0.25,
    "3V3": 0.50, "1V1": 0.50, "2V5": 0.50, "5V_USB": 0.50,
    "U6_SW": 0.50, "U6_BST": 0.50,
}

F_CU, B_CU = 0, 1
LAYER_NAMES = {F_CU: "F.Cu", B_CU: "B.Cu"}
OTHER_LAYER = {F_CU: B_CU, B_CU: F_CU}

EXPLORE_LIMIT = 400_000      # A* expansions before a connection is given up
FANOUT_REACH = 2.5           # mm a pad's escape track may look for free space
POUR_ENTRY_SAMPLE = 10       # cells between pour entry points (1 mm)


def track_width(net: str) -> float:
    return NET_WIDTH.get(net, DEFAULT_WIDTH)


def halo_radius(width: float) -> float:
    """How far from foreign copper a track's *centre line* must stay.

    The mask marks a cell when it is nearer than this to some copper, so a
    track that only uses unmarked cells keeps `clearance` to everything: the
    track is a capsule of radius width/2 and the distance along its centre
    line is a convex function, so its minimum is at a cell centre.
    """
    return round(CLEARANCE + width / 2.0 + HALO_MARGIN, 3)


HALO_RADII = sorted({halo_radius(width) for width in set(NET_WIDTH.values()) | {DEFAULT_WIDTH}})
HALO_VIA_RADIUS = round(CLEARANCE + VIA_DIA / 2.0 + HALO_MARGIN, 3)


_EDGE_CACHE: dict[float, int] = {}


def _edge_int(width: float) -> int:
    """Big integer mask of the cells a track of this width may not occupy.

    Track *copper* has to stay EDGE_MARGIN from the board outline, so the
    centre line has to stay EDGE_MARGIN + width/2 away - a via even more.
    """
    margin = EDGE_MARGIN + width / 2.0
    if margin in _EDGE_CACHE:
        return _EDGE_CACHE[margin]
    mask = bytearray(N)
    for iy in range(H):
        y = cell_center(iy)
        row = iy * W
        if y < margin or y > board.BOARD_H - margin:
            mask[row:row + W] = b"\x01" * W
            continue
        for ix in range(W):
            x = cell_center(ix)
            if x < margin or x > board.BOARD_W - margin:
                mask[row + ix] = 1
    value = int.from_bytes(bytes(mask), "big")
    _EDGE_CACHE[margin] = value
    return value


def halo_key(width: float) -> str:
    """The mask to use for a track of this width."""
    for radius in HALO_RADII:
        if radius >= halo_radius(width) - 1e-9:
            return radius
    return HALO_RADII[-1]


# ------------------------------------------------------------------ geometry
class Item:
    """One piece of copper: a rectangle, a circle or a track (a capsule).

    A KiCad track has round ends, so a track is modelled as a *capsule* - the
    segment between its two endpoints, inflated by half its width.  That
    matters: the distance from a capsule to a neighbour is the distance from
    its centre line minus the radius, while a rectangle would grow a corner
    that the copper does not have, and the DRC would report shorts that are
    not there (and, worse, the router would avoid room it could use).
    """

    __slots__ = ("ref", "pad", "net", "layers", "kind", "cx", "cy", "w", "h",
                 "r", "source", "cells", "x0", "y0", "x1", "y1")

    def __init__(self, net, layers, kind, cx, cy, w=0.0, h=0.0, r=0.0,
                 ref="", pad="", source="pad", ends=None):
        self.net, self.layers = net, layers
        self.kind, self.cx, self.cy = kind, cx, cy
        self.w, self.h, self.r = w, h, r
        self.ref, self.pad, self.source = ref, pad, source
        self.cells: dict[int, list[int]] = {}
        if ends is None:
            self.x0, self.y0, self.x1, self.y1 = cx, cy, cx, cy
        else:
            (self.x0, self.y0), (self.x1, self.y1) = ends

    def label(self) -> str:
        return "%s.%s" % (self.ref, self.pad) if self.ref else "%s@%.2f,%.2f" % (
            self.source, self.cx, self.cy)

    # -- geometry ---------------------------------------------------------
    @staticmethod
    def _segment_distance(x: float, y: float, x0: float, y0: float,
                          x1: float, y1: float) -> float:
        """Distance from a point to a segment."""
        dx, dy = x1 - x0, y1 - y0
        length2 = dx * dx + dy * dy
        if length2 <= 1e-12:
            return math.hypot(x - x0, y - y0)
        t = ((x - x0) * dx + (y - y0) * dy) / length2
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        return math.hypot(x - (x0 + t * dx), y - (y0 + t * dy))

    @staticmethod
    def _segment_rect_distance(x0, y0, x1, y1, rx0, ry0, rx1, ry1) -> float:
        """Distance between a segment and an axis-aligned rectangle."""
        if (min(x0, x1) <= rx1 and max(x0, x1) >= rx0
                and min(y0, y1) <= ry1 and max(y0, y1) >= ry0):
            if ((rx0 <= x0 <= rx1 and ry0 <= y0 <= ry1)
                    or (rx0 <= x1 <= rx1 and ry0 <= y1 <= ry1)):
                return 0.0
            for edge in (((rx0, ry0), (rx1, ry0)), ((rx1, ry0), (rx1, ry1)),
                         ((rx1, ry1), (rx0, ry1)), ((rx0, ry1), (rx0, ry0))):
                if Item._segments_cross((x0, y0), (x1, y1), edge[0], edge[1]):
                    return 0.0
        best = min(Item._point_rect_distance(x0, y0, rx0, ry0, rx1, ry1),
                   Item._point_rect_distance(x1, y1, rx0, ry0, rx1, ry1))
        for corner in ((rx0, ry0), (rx1, ry0), (rx1, ry1), (rx0, ry1)):
            best = min(best, Item._segment_distance(corner[0], corner[1], x0, y0, x1, y1))
        return best

    @staticmethod
    def _segments_cross(a0, a1, b0, b1) -> bool:
        def side(p, q, r):
            return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        d1, d2 = side(b0, b1, a0), side(b0, b1, a1)
        d3, d4 = side(a0, a1, b0), side(a0, a1, b1)
        return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))

    @staticmethod
    def _point_rect_distance(x, y, x0, y0, x1, y1) -> float:
        dx = max(x0 - x, 0.0, x - x1)
        dy = max(y0 - y, 0.0, y - y1)
        return math.hypot(dx, dy)

    def dist2(self, x: float, y: float) -> float:
        """Squared distance from a point to this item's copper (0 inside)."""
        if self.kind == "capsule":
            d = self._segment_distance(x, y, self.x0, self.y0, self.x1, self.y1) - self.r
            return d * d if d > 0 else 0.0
        if self.kind == "circle":
            d = math.hypot(x - self.cx, y - self.cy) - self.r
            return d * d if d > 0 else 0.0
        dx = abs(x - self.cx) - self.w / 2.0
        dy = abs(y - self.cy) - self.h / 2.0
        dx = dx if dx > 0 else 0.0
        dy = dy if dy > 0 else 0.0
        return dx * dx + dy * dy

    def bbox(self, margin: float = 0.0):
        if self.kind == "circle":
            half_w = half_h = self.r + margin
            return (self.cx - half_w, self.cy - half_h, self.cx + half_w, self.cy + half_h)
        x0, y0, x1, y1 = self.x0 - self.r, self.y0 - self.r, self.x1 + self.r, self.y1 + self.r
        if self.kind == "rect":
            x0, y0 = self.cx - self.w / 2.0, self.cy - self.h / 2.0
            x1, y1 = self.cx + self.w / 2.0, self.cy + self.h / 2.0
        return (min(x0, x1) - margin, min(y0, y1) - margin,
                max(x0, x1) + margin, max(y0, y1) + margin)

    def edge_distance(self, other: "Item") -> float:
        """Edge-to-edge distance to another item (negative when they overlap)."""
        if self.kind == "capsule":
            if other.kind == "capsule":
                return (self._segments_distance(other) - self.r - other.r)
            if other.kind == "circle":
                return (self._segment_distance(other.cx, other.cy, self.x0, self.y0,
                                               self.x1, self.y1) - self.r - other.r)
            ox0, oy0, ox1, oy1 = other.bbox(0.0)
            return (self._segment_rect_distance(self.x0, self.y0, self.x1, self.y1,
                                                ox0, oy0, ox1, oy1) - self.r)
        if other.kind == "capsule":
            return other.edge_distance(self)
        if self.kind == "circle" and other.kind == "circle":
            return math.hypot(self.cx - other.cx, self.cy - other.cy) - self.r - other.r
        if self.kind == "circle" or other.kind == "circle":
            circle, rect = (self, other) if self.kind == "circle" else (other, self)
            dx = max(abs(circle.cx - rect.cx) - rect.w / 2.0, 0.0)
            dy = max(abs(circle.cy - rect.cy) - rect.h / 2.0, 0.0)
            return math.hypot(dx, dy) - circle.r
        dx = abs(self.cx - other.cx) - (self.w + other.w) / 2.0
        dy = abs(self.cy - other.cy) - (self.h + other.h) / 2.0
        if dx <= 0 and dy <= 0:
            return max(dx, dy)
        return math.hypot(max(dx, 0.0), max(dy, 0.0))

    def _segments_distance(self, other: "Item") -> float:
        if self._segments_cross((self.x0, self.y0), (self.x1, self.y1),
                                (other.x0, other.y0), (other.x1, other.y1)):
            return 0.0
        best = min(self._segment_distance(other.x0, other.y0, self.x0, self.y0, self.x1, self.y1),
                   self._segment_distance(other.x1, other.y1, self.x0, self.y0, self.x1, self.y1),
                   self._segment_distance(self.x0, self.y0, other.x0, other.y0, other.x1, other.y1),
                   self._segment_distance(self.x1, self.y1, other.x0, other.y0, other.x1, other.y1))
        return best


def cell_of(x: float) -> int:
    i = int(x / G)
    return 0 if i < 0 else (W - 1 if i >= W else i)


def cell_center(i: int) -> float:
    return (i + 0.5) * G


def cell_index(x: float, y: float) -> int:
    return cell_of(y) * W + cell_of(x)


def index_xy(index: int):
    return index % W, index // W


def index_center(index: int):
    x, y = index_xy(index)
    return cell_center(x), cell_center(y)


# ------------------------------------------------------------------- the grid
class Grid:
    """`netid` and the halo masks per layer, plus the cell list of every item."""

    #: net id 1 is the shared "copper with no net" (spare header pins, unused
    #: package pins): never routed, always foreign, so tracks keep clear of it
    NO_NET = 1

    def __init__(self):
        self.netid = [bytearray(N), bytearray(N)]
        self.halo = {radius: [bytearray(N), bytearray(N)] for radius in HALO_RADII}
        self.halo_via = [bytearray(N), bytearray(N)]
        self.items: list[Item] = []
        self.net_index: dict[str, int] = {"(no net)": self.NO_NET}
        self.net_names: list[str] = ["(no net)"]
        self._halo_int = {radius: [0, 0] for radius in HALO_RADII}
        self._halo_via_int = [0, 0]
        self._own_halo_cache: dict[tuple[int, float, int], int] = {}
        self.dirty = True

    # -- net numbering ----------------------------------------------------
    def net_id(self, net: str | None) -> int:
        if not net:
            return self.NO_NET
        if net not in self.net_index:
            self.net_index[net] = len(self.net_names) + 1
            self.net_names.append(net)
        return self.net_index[net]

    def net_name(self, index: int) -> str:
        return self.net_names[index - 1] if 1 <= index <= len(self.net_names) else ""

    # -- rasterising ------------------------------------------------------
    def add(self, item: Item):
        self.items.append(item)
        self._stamp(item)
        for key in [key for key in self._own_halo_cache if key[0] == item.net]:
            del self._own_halo_cache[key]
        self.dirty = True

    def own_halo_int(self, net: int, radius: float, layer: int) -> int:
        """The halo mask this net's *own* copper contributes.

        `_stamp` writes the halos of every item into one shared mask, so a
        net's own copper blocks it exactly like a foreign one does.  That is
        wrong and it used to lock every escaped pad inside its own fan-out
        stub's halo.  Subtracting the net's own share gives the foreign mask:
        (A | O) & ~O == A & ~O, a subset of A, so the mask stays sound.
        """
        key = (net, radius, layer)
        cached = self._own_halo_cache.get(key)
        if cached is not None:
            return cached
        mask = bytearray(N)
        limit = (radius + 1e-9) ** 2
        for item in self.items:
            if item.net != net or layer not in item.layers:
                continue
            x0, y0, x1, y1 = item.bbox(radius)
            for iy in range(max(0, cell_of(y0) - 1), min(H - 1, cell_of(y1) + 1) + 1):
                cy = cell_center(iy)
                base = iy * W
                for ix in range(max(0, cell_of(x0) - 1), min(W - 1, cell_of(x1) + 1) + 1):
                    if item.dist2(cell_center(ix), cy) < limit:
                        mask[base + ix] = 1
        value = int.from_bytes(bytes(mask), "big")
        self._own_halo_cache[key] = value
        return value

    def _stamp(self, item: Item):
        """Write the item's copper, its track halos and its via halo."""
        net = item.net
        radii = [(radius, (radius + 1e-9) ** 2) for radius in HALO_RADII]
        via2 = (HALO_VIA_RADIUS + 1e-9) ** 2
        x0, y0, x1, y1 = item.bbox(max([HALO_VIA_RADIUS] + HALO_RADII))
        # one cell of slack all round: cell_of(int(x/G)) rounds the wrong way
        # for an edge that lands exactly on a cell boundary (0.1 is not exact
        # in binary), and a halo that stops one cell short of an item's end is
        # a hole for a track or a via to slip through
        ix0, ix1 = max(0, cell_of(x0) - 1), min(W - 1, cell_of(x1) + 1)
        iy0, iy1 = max(0, cell_of(y0) - 1), min(H - 1, cell_of(y1) + 1)
        for layer in item.layers:
            netid = self.netid[layer]
            halo_via = self.halo_via[layer]
            halos = [(limit, self.halo[radius][layer]) for radius, limit in radii]
            for iy in range(iy0, iy1 + 1):
                cy = cell_center(iy)
                base = iy * W
                for ix in range(ix0, ix1 + 1):
                    d2 = item.dist2(cell_center(ix), cy)
                    index = base + ix
                    if d2 == 0.0:
                        netid[index] = net
                        halo_via[index] = 1
                        for _limit, mask in halos:
                            mask[index] = 1
                        continue
                    if d2 < via2:
                        halo_via[index] = 1
                    for limit, mask in halos:
                        if d2 < limit:
                            mask[index] = 1

    def seal(self):
        """Freeze the base masks into big integers (fast per-net combination)."""
        self._halo_int = {radius: [int.from_bytes(bytes(self.halo[radius][layer]), "big")
                                   for layer in (F_CU, B_CU)]
                          for radius in HALO_RADII}
        self._halo_via_int = [int.from_bytes(bytes(self.halo_via[layer]), "big")
                              for layer in (F_CU, B_CU)]
        self.dirty = False

    def refresh(self):
        """Re-seal after new copper was added."""
        self.seal()

    # -- masks ------------------------------------------------------------
    def blocked(self, width: float, net: int = 0) -> list[bytearray]:
        """Per layer: bytearray, 1 where a track of this width may not go.

        `net` is the net the track belongs to: its own copper does not block it.
        """
        radius = halo_key(width)
        edge = _edge_int(width)
        out = []
        for layer in (F_CU, B_CU):
            mask = self._halo_int[radius][layer] | edge
            out.append(bytearray(mask.to_bytes(N, "big")))
        return out

    def blocked_with_own(self, width: float, net: int) -> list[bytearray]:
        """Like `blocked`, but the net's own halo does not block it.

        A track may touch its own copper, so the cells around a net's own pads
        and tracks are fair game - and that is exactly where a pad trapped
        inside its own stub's halo needs to go.  The mask alone would be
        unsound there (a cell near both our copper and a rival's would be
        opened), so the A* re-checks every move into one of these cells; here
        we only have to make them *candidates*.
        """
        radius = halo_key(width)
        edge = _edge_int(width)
        out = []
        for layer in (F_CU, B_CU):
            mask = self._halo_int[radius][layer] | edge
            mask &= ~self.own_halo_int(net, radius, layer)
            out.append(bytearray(mask.to_bytes(N, "big")))
        return out

    def via_blocked(self, net: int = 0) -> bytearray:
        """1 where a via may not go: nearer than 0.45 mm to *any* copper."""
        mask = (self._halo_via_int[F_CU] | self._halo_via_int[B_CU]
                | _edge_int(VIA_DIA))
        return bytearray(mask.to_bytes(N, "big"))

    def net_at(self, layer: int, index: int) -> int:
        return self.netid[layer][index]

    def cells_of(self, item: Item, layer: int) -> list[int]:
        """Cell indices whose centres are inside this item on this layer."""
        if layer in item.cells:
            return item.cells[layer]
        if layer not in item.layers:
            item.cells[layer] = []
            return []
        x0, y0, x1, y1 = item.bbox(0.0)
        out = []
        for iy in range(cell_of(y0), cell_of(y1) + 1):
            cy = cell_center(iy)
            base = iy * W
            for ix in range(cell_of(x0), cell_of(x1) + 1):
                if item.dist2(cell_center(ix), cy) == 0.0:
                    out.append(base + ix)
        item.cells[layer] = out
        return out


# --------------------------------------------------------------- escape cells
class Neighbourhood:
    """Spatial hash of items, so a clearance test only looks nearby."""

    def __init__(self, grid: Grid, cell: float = 2.0):
        self.cell = cell
        self.buckets: dict[tuple[int, int], list[Item]] = {}
        self.grid = grid

    def add(self, item: Item):
        x0, y0, x1, y1 = item.bbox(CLEARANCE + 1.0)
        for gy in range(int(y0 / self.cell), int(y1 / self.cell) + 1):
            for gx in range(int(x0 / self.cell), int(x1 / self.cell) + 1):
                self.buckets.setdefault((gx, gy), []).append(item)

    def near(self, x0, y0, x1, y1) -> list[Item]:
        seen = {}
        for gy in range(int(y0 / self.cell), int(y1 / self.cell) + 1):
            for gx in range(int(x0 / self.cell), int(x1 / self.cell) + 1):
                for item in self.buckets.get((gx, gy), ()):
                    seen[id(item)] = item
        return list(seen.values())


def segment_clear(probe: Item, layer: int, net: int,
                  neighbourhood: Neighbourhood, clearance: float = CLEARANCE) -> bool:
    """Is this probe track item clear of every foreign item on its layer?"""
    lo_x, lo_y, hi_x, hi_y = probe.bbox(clearance + 0.1)
    for other in neighbourhood.near(lo_x, lo_y, hi_x, hi_y):
        if other.net == net or layer not in other.layers:
            continue
        if probe.edge_distance(other) < clearance - CLEARANCE_TOLERANCE:
            return False
    return True


def escape_cells(grid: Grid, item: Item, layer: int, blocked: bytearray, net: int,
                 neighbourhood: Neighbourhood, width: float, reach: float = 1.8,
                 budget: int = 4000, want_path: bool = False):
    """Cells around a pad that a track of this net may legally use.

    The raster is deliberately strict, so a pad can end up with no passable
    cell at all - the QFP fan-out, where every neighbour's halo covers the
    gap.  This walks out of the pad cell by cell and checks every *move*
    against the real geometry of the nearby items, so the corridor it returns
    is legal whatever the raster says.  It is a small BFS rather than four
    straight rays because the fan-out has to step around the escape vias.
    """
    if layer not in item.layers:
        return []
    x0, y0, x1, y1 = item.bbox(reach)
    ix0, ix1 = max(0, cell_of(x0) - 1), min(W - 1, cell_of(x1) + 1)
    iy0, iy1 = max(0, cell_of(y0) - 1), min(H - 1, cell_of(y1) + 1)
    start = grid.cells_of(item, layer)
    if not start:
        return []
    seen = set(start)
    came: dict[int, int] = {}
    queue = list(start)
    open_cells = []
    free = []
    while queue and budget > 0:
        index = queue.pop()
        budget -= 1
        ix, iy = index_xy(index)
        px, py = index_center(index)
        for nx, ny in ((ix + 1, iy), (ix - 1, iy), (ix, iy + 1), (ix, iy - 1)):
            if not (ix0 <= nx <= ix1 and iy0 <= ny <= iy1):
                continue
            nindex = ny * W + nx
            if nindex in seen:
                continue
            qx, qy = index_center(nindex)
            probe = Item(net, (layer,), "capsule", (px + qx) / 2.0, (py + qy) / 2.0,
                         r=width / 2.0, ends=((px, py), (qx, qy)))
            if not segment_clear(probe, layer, net, neighbourhood):
                continue
            seen.add(nindex)
            came[nindex] = index
            open_cells.append(nindex)
            if blocked[nindex]:
                queue.append(nindex)
            else:
                free.append(nindex)            # already free: the way out
    if want_path:
        return open_cells, free, came
    return open_cells


def via_clear(grid: Grid, x: float, y: float, net: int,
              neighbourhood: Neighbourhood) -> bool:
    """May a via of this net sit here?  Real geometry, not the raster."""
    reach = EDGE_MARGIN + VIA_DIA / 2.0
    if not (reach < x < board.BOARD_W - reach and reach < y < board.BOARD_H - reach):
        return False
    probe = Item(net, (F_CU, B_CU), "circle", x, y, r=VIA_DIA / 2.0)
    lo_x, lo_y, hi_x, hi_y = probe.bbox(CLEARANCE + 0.1)
    for other in neighbourhood.near(lo_x, lo_y, hi_x, hi_y):
        if other.net == net:
            continue
        if probe.edge_distance(other) < CLEARANCE - CLEARANCE_TOLERANCE:
            return False
    return True


# ------------------------------------------------------------------ the router
def debug_pocket(grid: Grid, neighbourhood: Neighbourhood, blocked, sources, targets,
                 net_id: int, width: float, first: str, second: str) -> None:
    """Why did this search die?  Flood the reachable set and name the walls."""
    seen = set(sources)
    queue = list(sources)
    while queue:
        nxt = []
        for node in queue:
            layer, index = divmod(node, N)
            ix, iy = index_xy(index)
            for nx, ny in ((ix + 1, iy), (ix - 1, iy), (ix, iy + 1), (ix, iy - 1)):
                if not (0 <= nx < W and 0 <= ny < H):
                    continue
                nindex = ny * W + nx
                if blocked[layer][nindex]:
                    continue
                nnode = layer * N + nindex
                if nnode in seen:
                    continue
                seen.add(nnode)
                nxt.append(nnode)
        queue = nxt
    radius = halo_radius(width)
    wall: dict[str, int] = {}
    free = [(layer, index) for layer, index in
            (divmod(node, N) for node in seen) if grid.net_at(layer, index) == net_id]
    for layer, index in free:
        ix, iy = index_xy(index)
        for nx, ny in ((ix + 1, iy), (ix - 1, iy), (ix, iy + 1), (ix, iy - 1)):
            if not (0 <= nx < W and 0 <= ny < H):
                continue
            nindex = ny * W + nx
            if not blocked[layer][nindex]:
                continue
            cx, cy = index_center(nindex)
            for other in neighbourhood.near(cx - 0.5, cy - 0.5, cx + 0.5, cy + 0.5):
                if other.net == net_id or layer not in other.layers:
                    continue
                if other.dist2(cx, cy) <= radius * radius + 1e-9:
                    wall[other.label()] = wall.get(other.label(), 0) + 1
    print("    DEBUG %s -> %s: reachable %d, on-net cells %d, targets %d"
          % (first, second, len(seen), len(free), len(seen & targets)))
    for label, count in sorted(wall.items(), key=lambda kv: -kv[1])[:8]:
        print("      walled by %-18s %d cells" % (label, count))


def astar(grid: Grid, net_id: int, neighbourhood: Neighbourhood,
          blocked: list[bytearray], via_blocked: bytearray,
          sources: set[int], targets: set[int],
          target_boxes: list[tuple[int, int, int, int]], width: float,
          base_blocked: list[bytearray] | None = None,
          explore_limit: int = EXPLORE_LIMIT, stats: list | None = None):
    """A* over (layer, x, y).  Returns the node path [(layer, index), ...]."""
    if not sources or not targets:
        return None

    def heuristic(node: int) -> float:
        _layer, index = divmod(node, N)
        x, y = index_xy(index)
        best = 1e18
        for x0, y0, x1, y1 in target_boxes:
            dx = x0 - x if x < x0 else (x - x1 if x > x1 else 0)
            dy = y0 - y if y < y0 else (y - y1 if y > y1 else 0)
            d = dx + dy
            if d < best:
                best = d
        # in the same units as the move cost (10 per cell): without this the
        # search degenerates into Dijkstra and explores the whole board
        return STEP_COST * best

    VERIFY_MOVES = True           # re-check a move the raster called blocked

# A cell the mask blocks can still be used: the escape corridor opened it,
    # or it is a pad we are allowed to land on.  But the corridor was verified
    # for *one* way in, and the search may arrive from a different side - so
    # every such move is checked against the real geometry here, once.
    checked: dict[tuple[int, int], bool] = {}

    def move_clear(layer: int, index: int, direction: int) -> bool:
        key = (layer, index * 4 + direction)
        verdict = checked.get(key)
        if verdict is None:
            px, py = index_center(index)
            qx, qy = px - (STEP_X[direction] * G), py - (STEP_Y[direction] * G)
            probe = Item(net_id, (layer,), "capsule", (px + qx) / 2.0,
                         (py + qy) / 2.0, r=width / 2.0, ends=((qx, qy), (px, py)))
            verdict = segment_clear(probe, layer, net_id, neighbourhood)
            checked[key] = verdict
        return verdict

    heap = []
    g: dict[int, int] = {}
    came: dict[int, int] = {}
    for node in sources:
        if node in g:
            continue
        g[node] = 0
        heapq.heappush(heap, (heuristic(node), 0, node))
    if not heap:
        return None

    expanded = 0
    limit_hit = False
    rejected = [0, 0]
    while heap:
        _f, cost, node = heapq.heappop(heap)
        if cost > g.get(node, 1 << 30):
            continue
        if node in targets:
            path = [node]
            while node in came:
                node = came[node]
                path.append(node)
            path.reverse()
            return path
        expanded += 1
        if expanded > explore_limit:
            limit_hit = True
            break
        layer, index = divmod(node, N)
        x, y = index_xy(index)
        moves = []
        for direction, (dx, dy) in enumerate(STEP_DIRECTIONS):
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H:
                moves.append((layer, ny * W + nx, STEP_COST, direction))
        if not via_blocked[index]:
            moves.append((OTHER_LAYER[layer], index, VIA_COST, -1))
        elif (grid.net_at(layer, index) == net_id
              and via_clear(grid, *index_center(index), net_id, neighbourhood)):
            # inside our own copper: a via is allowed when the real geometry
            # says it keeps the 0.2 mm rule against everything foreign
            moves.append((OTHER_LAYER[layer], index, VIA_COST, -1))
        for nlayer, nindex, step, direction in moves:
            nnode = nlayer * N + nindex
            if blocked[nlayer][nindex] and nnode not in targets:
                rejected[0] += 1
                continue
            if (VERIFY_MOVES and direction >= 0 and base_blocked is not None
                    and base_blocked[nlayer][nindex]
                    and not move_clear(nlayer, nindex, direction)):
                rejected[1] += 1
                continue
            ncost = cost + step
            if ncost < g.get(nnode, 1 << 30):
                g[nnode] = ncost
                came[nnode] = node
                heapq.heappush(heap, (ncost + heuristic(nnode), ncost, nnode))
    if stats is not None:
        stats.append({"expanded": expanded, "limit_hit": limit_hit,
                      "frontier": len(heap), "mask_reject": rejected[0],
                      "verify_reject": rejected[1]})
    return None


STEP_DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1))
STEP_X = (1, -1, 0, 0)
STEP_Y = (0, 0, 1, -1)


def path_to_copper(path: list[int], width: float):
    """Turn a cell path into axis-aligned segments plus the vias it needs."""
    segments, vias = [], []
    runs: list[list] = []                       # [layer, [cell, ...]]
    for node in path:
        layer, index = divmod(node, N)
        if runs and runs[-1][0] == layer:
            runs[-1][1].append(index)
        else:
            runs.append([layer, [index]])
    for layer, indices in runs:
        points = [index_center(i) for i in indices]
        start = previous = points[0]
        direction = None
        for point in points[1:]:
            step = (round(point[0] - previous[0], 3), round(point[1] - previous[1], 3))
            if step == (0.0, 0.0):
                continue
            if direction is None:
                direction = step
            elif step != direction:
                segments.append((start, previous, layer))
                start, direction = previous, step
            previous = point
        segments.append((start, previous, layer))
    for kindex in range(1, len(runs)):
        index = runs[kindex - 1][1][-1]
        x, y = index_center(index)
        vias.append((x, y))
    return segments, vias


class Router:
    def __init__(self, grid: Grid, neighbourhood: Neighbourhood):
        self.grid = grid
        self.neighbourhood = neighbourhood
        self.new_segments: list[dict] = []
        self.new_vias: list[dict] = []
        self.failures: list[str] = []
        self.log: list[str] = []
        self.violations: list[str] = []      # copper that failed its own check

    # -- adding copper ----------------------------------------------------
    def add_segment(self, p0, p1, layer: int, net_name: str, width: float):
        if p0 == p1:
            return
        item = Item(self.grid.net_id(net_name), (layer,), "capsule",
                    (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0, r=width / 2.0,
                    ref="", pad="", source="track", ends=(p0, p1))
        if not segment_clear(item, layer, item.net, self.neighbourhood):
            other = min(((o.edge_distance(item), o)
                         for o in self.neighbourhood.near(*item.bbox(0.6))
                         if o.net != item.net), key=lambda pair: pair[0],
                        default=(0.0, None))[1]
            self.violations.append("track %s %.2f,%.2f->%.2f,%.2f (%s) id=%d vs %s (%s)"
                                   % (net_name, p0[0], p0[1], p1[0], p1[1],
                                      LAYER_NAMES[layer], len(self.new_segments),
                                      other.label() if other else "?",
                                      self.grid.net_name(other.net) if other else "?"))
            if os.environ.get("SV16_DEBUG"):
                brute = []
                for candidate in self.grid.items:
                    if candidate.net == item.net or layer not in candidate.layers:
                        continue
                    brute.append((candidate.edge_distance(item), candidate.label(),
                                  self.grid.net_name(candidate.net),
                                  item.edge_distance(candidate), candidate))
                brute.sort(key=lambda row: row[0])
                print("    DEBUG %s %.2f,%.2f->%.2f,%.2f (%s) seg#%d: %d foreign items on this layer"
                      % (net_name, p0[0], p0[1], p1[0], p1[1], LAYER_NAMES[layer],
                         len(self.new_segments), len(brute)))
                for row in brute[:3]:
                    seq = ""
                    if row[4].source == "track":
                        for i, record in enumerate(self.new_segments):
                            if (abs(record["start"][0] - row[4].x0) < 1e-9
                                    and abs(record["start"][1] - row[4].y0) < 1e-9):
                                seq = " (that one is segment #%d)" % i
                                break
                    print("      other-first %.4f | self-first %.4f | %s (%s)%s"
                          % (row[0], row[3], row[1], row[2], seq))
        self.grid.add(item)
        self.neighbourhood.add(item)
        self.new_segments.append({"start": [round(p0[0], 3), round(p0[1], 3)],
                                  "end": [round(p1[0], 3), round(p1[1], 3)],
                                  "width": width, "layer": LAYER_NAMES[layer],
                                  "net": net_name})

    def add_via(self, x: float, y: float, net_name: str):
        item = Item(self.grid.net_id(net_name), (F_CU, B_CU), "circle", x, y,
                    r=VIA_DIA / 2.0, source="via")
        if not via_clear(self.grid, x, y, item.net, self.neighbourhood):
            other = min(((o.edge_distance(item), o)
                         for o in self.neighbourhood.near(*item.bbox(0.6))
                         if o.net != item.net), key=lambda pair: pair[0],
                        default=(0.0, None))[1]
            self.violations.append("via %s %.3f,%.3f id=%d vs %s (%s)"
                                   % (net_name, x, y, len(self.new_vias),
                                      other.label() if other else "?",
                                      self.grid.net_name(other.net) if other else "?"))
        self.grid.add(item)
        self.neighbourhood.add(item)
        self.new_vias.append({"x": round(x, 3), "y": round(y, 3),
                              "size": VIA_DIA, "drill": VIA_DRILL,
                              "net": net_name})

    # -- routing one net --------------------------------------------------
    def route_net(self, net: str, pads: list[Item], existing: list[Item],
                  pour_cells: dict[int, str] | None = None) -> bool:
        width = track_width(net)
        net_id = self.grid.net_id(net)
        components = self.components(pads, existing, net)
        if len(components) <= 1:
            return True

        ok = True
        while len(components) > 1:
            best = None
            for i in range(len(components)):
                for j in range(i + 1, len(components)):
                    d = self._bbox_gap(components[i], components[j])
                    if best is None or d < best[0]:
                        best = (d, i, j)
            _d, i, j = best
            first, second = components[i], components[j]
            if self.connect(first, second, net, net_id, width, pour_cells):
                components[i] = first + second
                del components[j]
            else:
                self.failures.append("%s: could not join %s to %s"
                                     % (net, self._describe(second),
                                        self._describe(first)))
                ok = False
                components[i] = first + second
                del components[j]
        return ok

    @staticmethod
    def _describe(component) -> str:
        labels = sorted({item.label() for item in component if item.ref})
        return ",".join(labels) if labels else (component[0].label() if component else "?")

    @staticmethod
    def _bbox_gap(first, second) -> float:
        def box(items):
            boxes = [item.bbox(0.0) for item in items]
            return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                    max(b[2] for b in boxes), max(b[3] for b in boxes))
        a, b = box(first), box(second)
        dx = max(a[0] - b[2], b[0] - a[2], 0.0)
        dy = max(a[1] - b[3], b[1] - a[3], 0.0)
        return math.hypot(dx, dy)

    def components(self, pads, existing, net):
        """Group the net's copper into touching components (pours included)."""
        items = list(pads) + list(existing)
        parent = list(range(len(items)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for a in range(len(items)):
            for b in range(a + 1, len(items)):
                if items[a].edge_distance(items[b]) <= 0.0:
                    union(a, b)
        # a via or a through-hole pad inside a pour of its own net joins that
        # pour island: the ground plane joins all of them, a rail pour only
        # joins the vias that stand in it
        islands: dict[str, int] = {}
        for index, item in enumerate(items):
            island = self.pour_island(item, net)
            if island is None:
                continue
            if island not in islands:
                islands[island] = index
            else:
                union(index, islands[island])
        groups: dict[int, list[Item]] = {}
        for index, item in enumerate(items):
            groups.setdefault(find(index), []).append(item)
        return list(groups.values())

    @staticmethod
    def pour_island(item: Item, net: str):
        """The pour island this item stands in, if it can reach one."""
        if not (item.kind == "circle" or len(item.layers) > 1):
            return None                    # only a via or a through-hole pad
        return pour_island_at(item.cx, item.cy, net)

    # -- one connection ---------------------------------------------------
    def connect(self, first, second, net, net_id, width, pour_cells=None) -> bool:
        for reach, own in ((1.8, False), (3.5, False), (6.0, False), (6.0, True)):
            if self._connect(first, second, net, net_id, width, pour_cells, reach, own):
                return True
        return False

    def _connect(self, first, second, net, net_id, width, pour_cells, reach,
                 own_halo=False) -> bool:
        blocked = self.grid.blocked(width)
        base_blocked = [bytearray(mask) for mask in blocked]
        if own_halo:
            # the last try: open the net's own halo as *candidates* and let the
            # per-move geometry check decide
            blocked = self.grid.blocked_with_own(width, net_id)
        via_blocked = self.grid.via_blocked()

        sources = set()
        for item in first:
            for layer in (F_CU, B_CU):
                for index in self.grid.cells_of(item, layer):
                    sources.add(layer * N + index)
        targets = set()
        boxes = []
        for item in second:
            for layer in (F_CU, B_CU):
                for index in self.grid.cells_of(item, layer):
                    targets.add(layer * N + index)
        if not sources or not targets:
            return False

        # the net's pour is a valid destination: drop a via into it.  Only the
        # entry points nearest this connection are offered, which keeps the A*
        # heuristic tight and the search small.
        entry_nodes: dict[int, int] = {}
        if pour_cells:
            cx = sum(item.cx for item in first + second) / len(first + second)
            cy = sum(item.cy for item in first + second) / len(first + second)
            nearest = sorted(pour_cells, key=lambda index: (
                (index_xy(index)[0] - int(cx / G)) ** 2 + (index_xy(index)[1] - int(cy / G)) ** 2
            ))[:40]
            for index in nearest:
                for layer in (F_CU, B_CU):
                    if not via_blocked[index]:
                        node = layer * N + index
                        targets.add(node)
                        entry_nodes[node] = index

        for item in second:
            for box in (item.bbox(0.0),):
                boxes.append((int(box[0] / G), int(box[1] / G),
                              int(box[2] / G), int(box[3] / G)))
        for node, index in entry_nodes.items():
            x, y = index_xy(index)
            boxes.append((x, y, x, y))

        # the strict raster can leave a pad with no free cell at all: open a
        # verified corridor out of every pad of this connection
        for item in first + second:
            for layer in (F_CU, B_CU):
                if layer not in item.layers:
                    continue
                for index in escape_cells(self.grid, item, layer, blocked[layer],
                                          net_id, self.neighbourhood, width, reach=reach):
                    blocked[layer][index] = 0

        stats: list = []
        path = astar(self.grid, net_id, self.neighbourhood, blocked, via_blocked,
                     sources, targets, boxes, width, base_blocked, stats=stats)
        if path is None:
            self.log.append("%s: no path from %s to %s (%s)"
                            % (net, self._describe(first), self._describe(second),
                               stats[0] if stats else "?"))
            if os.environ.get("SV16_DEBUG") == net:
                debug_pocket(self.grid, self.neighbourhood, blocked, sources,
                             targets, net_id, width, self._describe(first),
                             self._describe(second))
            return False
        segments, vias = path_to_copper(path, width)
        last = path[-1]
        if last in entry_nodes and self.grid.net_at(*divmod(last, N)) != net_id:
            x, y = index_center(entry_nodes[last])
            vias.append((x, y))
        # The real geometry has the last word.  The raster, the escape
        # corridors and the heuristics are all approximations of "may a track
        # go here"; this is not.  A path that fails is thrown away whole - no
        # half-laid connection - and the next rung of the ladder gets its turn.
        for (p0, p1, layer) in segments:
            probe = Item(net_id, (layer,), "capsule",
                         (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0,
                         r=width / 2.0, ends=(p0, p1))
            if not segment_clear(probe, layer, net_id, self.neighbourhood):
                self.log.append("%s: no clean path from %s to %s (track %.2f,%.2f->%.2f,%.2f)"
                                % (net, self._describe(first), self._describe(second),
                                   p0[0], p0[1], p1[0], p1[1]))
                return False
        for (x, y) in vias:
            if not via_clear(self.grid, x, y, net_id, self.neighbourhood):
                self.log.append("%s: no clean path from %s to %s (via %.2f,%.2f)"
                                % (net, self._describe(first), self._describe(second), x, y))
                return False
        for (p0, p1, layer) in segments:
            self.add_segment(p0, p1, layer, net, width)
        for (x, y) in vias:
            self.add_via(x, y, net)
        self.grid.refresh()
        return True


# ------------------------------------------------------- the pours as islands
_SOLID_ISLAND = "plane"


def pour_island_at(x: float, y: float, net: str):
    """Which pour island of `net` covers this point (None if none does).

    The ground plane is marked as one island: In1.Cu is solid and the B.Cu
    pour is joined to it by the stitching vias, so every GND via reaches it.
    A rail pour is only reached where that rail's polygon actually is, and the
    polygons are separate islands - two rectangles of the same net that do not
    touch are two pieces of copper, and the router has to join them.
    """
    if net in copper.SOLID_NETS:
        return _SOLID_ISLAND
    winner = copper.winning_pour_at(x, y)
    if winner is None or winner[0] != net:
        return None
    for pour_net, priority, polygons in copper.POURS:
        if pour_net != net or priority != winner[1]:
            continue
        for index, polygon in enumerate(polygons):
            if copper.point_in_polygon(x, y, polygon):
                return "%s#%d" % (net, index)
    return None


RAIL_POUR_NETS = tuple({pour[0] for pour in copper.POURS} - set(copper.SOLID_NETS))
_POUR_ENTRY_CACHE: dict[str, dict[int, str]] = {}


def pour_entry_cells(net: str) -> dict[int, str]:
    """Cells inside this net's pours that may take an entry via."""
    if net not in RAIL_POUR_NETS:
        return {}
    if net in _POUR_ENTRY_CACHE:
        return _POUR_ENTRY_CACHE[net]
    out = {}
    for iy in range(0, H, POUR_ENTRY_SAMPLE):
        y = cell_center(iy)
        for ix in range(0, W, POUR_ENTRY_SAMPLE):
            x = cell_center(ix)
            island = pour_island_at(x, y, net)
            if island is not None:
                out[iy * W + ix] = island
    _POUR_ENTRY_CACHE[net] = out
    return out


# ------------------------------------------------------- build the base grid
def build(verbose: bool = True):
    """The board as a grid: pads (from the placement) and the planned copper."""
    grid = Grid()
    neighbourhood = Neighbourhood(grid)
    placement = board.effective_placement()
    nets_by_ref: dict = {}
    for ref, pad, net in board.CONNECTIONS:
        nets_by_ref.setdefault(ref, {})[str(pad)] = net

    pad_items: dict[str, list[Item]] = {}
    for ref, library, builder, value, group in board.COMPONENTS:
        if ref not in placement:
            continue
        x0, y0, rot = placement[ref]
        for pad in board.pads_of(builder):
            number = str(pad["number"])
            dx, dy = board.rotate_point(pad["x"], pad["y"], rot)
            w, h = pad["w"], pad["h"]
            if int(round(rot)) % 180 == 90:
                w, h = h, w
            net = nets_by_ref.get(ref, {}).get(number)
            if pad["kind"] == "np_thru_hole":
                continue                     # no copper
            if pad["kind"] == "thru_hole":
                item = Item(grid.net_id(net), (F_CU, B_CU), "circle",
                            x0 + dx, y0 + dy, r=max(w, h) / 2.0,
                            ref=ref, pad=number, source="pad")
            elif number == "":
                continue
            else:
                item = Item(grid.net_id(net), (F_CU,), "rect",
                            x0 + dx, y0 + dy, w, h, ref=ref, pad=number,
                            source="pad")
            grid.add(item)
            neighbourhood.add(item)
            pad_items.setdefault(ref, []).append(item)

    # the copper plan: stubs and vias that are already in the board file
    plan = board.copper_plan()
    for segment in plan.segments:
        (x0, y0), (x1, y1) = segment["start"], segment["end"]
        layer = F_CU if segment["layer"] == "F.Cu" else B_CU
        item = Item(grid.net_id(segment["net"]), (layer,), "capsule",
                    (x0 + x1) / 2.0, (y0 + y1) / 2.0, r=segment["width"] / 2.0,
                    source="stub", ends=((x0, y0), (x1, y1)))
        grid.add(item)
        neighbourhood.add(item)
    for via in plan.vias:
        item = Item(grid.net_id(via["net"]), (F_CU, B_CU), "circle",
                    via["x"], via["y"], r=via["dia"] / 2.0, source="planned-via")
        grid.add(item)
        neighbourhood.add(item)

    grid.seal()
    if verbose:
        print("grid: %d x %d cells at %.1f mm, %d items (%d pads, %d planned vias)"
              % (W, H, G, len(grid.items), sum(len(v) for v in pad_items.values()),
                 len(plan.vias)))
    return grid, neighbourhood, pad_items


def net_pads(grid: Grid, pad_items, net: str) -> list[Item]:
    wanted = grid.net_id(net)
    return [item for items in pad_items.values() for item in items
            if item.net == wanted]


def routing_order(grid: Grid, pad_items) -> list[str]:
    """Critical and short nets first, long hauls last."""
    nets: dict[str, list[Item]] = {}
    for ref, items in pad_items.items():
        for item in items:
            if item.net != Grid.NO_NET:
                nets.setdefault(grid.net_name(item.net), []).append(item)
    critical = {"clk_25m", "CCLK", "MISO", "MOSI", "CSSPIN", "U2_CLK", "U2_DI",
                "U2_DO", "U2_CS", "flash_sck", "USB_DP", "USB_DN", "USB_DP_F",
                "USB_DN_F"}
    power = {"VM_IN_RAW", "VM_IN", "USB_VBUS", "5V_USB", "3V3", "1V1", "2V5", "GND"}
    fpga = {item.net for items in [nets[net] for net in nets] for item in items
            if item.ref == "U1"}

    def tier(net):
        # The 0.5 mm QFP ring is the scarce resource on this board: a net that
        # has to thread it gets the ring while it is still empty, because the
        # ring closes up faster than anything else on the board.  The pours
        # carry the power nets, so those go last; the critical signals (USB,
        # the clocks, the console) come next.
        if net in power:
            return 3
        if nets[net][0].net in fpga:
            return 0
        if net in critical:
            return 1
        return 2

    def key(net):
        items = nets[net]
        xs = [i.cx for i in items]
        ys = [i.cy for i in items]
        size = (max(xs) - min(xs)) + (max(ys) - min(ys))
        return (tier(net), round(size, 1), net)
    return sorted(nets, key=key)


def _pad_has_copper(router: "Router", item: Item) -> bool:
    """True when something else on this net already touches the pad."""
    for other in router.neighbourhood.near(*item.bbox(1.5)):
        if other is not item and other.net == item.net and other.edge_distance(item) <= 0.0:
            return True
    return False


def _escape_stub(router: "Router", grid: Grid, item: Item, net: str, width: float,
                 origin: tuple[float, float], reach: float = FANOUT_REACH):
    """The shortest legal straight run from a pad into free space, if any.

    Away from the part's own centre first (the way a fan-out leaves a package),
    then the two perpendicular directions.  A straight run is tried before
    anything clever: it is what a person would draw, and it keeps the stub out
    of the way of the rest of the board.
    """
    net_id = grid.net_id(net)
    blocked = grid.blocked(width)
    dx, dy = item.cx - origin[0], item.cy - origin[1]
    length = math.hypot(dx, dy)
    if length < 0.05:
        dx, dy = 0.0, -1.0
    else:
        dx, dy = dx / length, dy / length
    if abs(dx) >= abs(dy):
        dx, dy = (1.0 if dx > 0 else -1.0), 0.0
    else:
        dx, dy = 0.0, (1.0 if dy > 0 else -1.0)
    best = None
    block_cells = 0
    for layer in (F_CU, B_CU):
        if layer not in item.layers:
            continue
        mask = blocked[layer]
        for ux, uy in ((dx, dy), (-dy, dx), (dy, -dx)):
            previous = (item.cx, item.cy)
            for step in range(1, int(reach / G) + 1):
                px = item.cx + ux * step * G
                py = item.cy + uy * step * G
                if not (EDGE_MARGIN < px < board.BOARD_W - EDGE_MARGIN
                        and EDGE_MARGIN < py < board.BOARD_H - EDGE_MARGIN):
                    break
                probe = Item(net_id, (layer,), "capsule",
                             (previous[0] + px) / 2.0, (previous[1] + py) / 2.0,
                             r=width / 2.0, ends=(previous, (px, py)))
                if not segment_clear(probe, layer, net_id, router.neighbourhood):
                    break
                previous = (px, py)
                index = cell_index(px, py)
                if not mask[index]:
                    # free space: keep going while it stays clear, so the stub
                    # ends deep enough that the net's later route has room
                    distance = step * G
                    if best is None or distance > best[0] + 1e-9:
                        best = (distance, layer, [(item.cx, item.cy), (px, py)])
                block_cells = max(block_cells, step)
    if best is not None:
        return best[1], best[2]
    # nothing straight out: fall back to the verified corridor, simplified
    for layer in (F_CU, B_CU):
        if layer not in item.layers:
            continue
        mask = grid.blocked(width)[layer]
        cells, free, came = escape_cells(grid, item, layer, mask, net_id,
                                         router.neighbourhood, width,
                                         reach=reach, want_path=True)
        if not free:
            continue
        shallow = min(free, key=lambda index: len(_walk(came, index)))
        path = _walk(came, shallow)
        points = [index_center(index) for index in path]
        return layer, _simplify(points, layer, net_id, router.neighbourhood, width)
    return None


def _simplify(points, layer, net, neighbourhood, width):
    """Join a cell path into the longest straight runs that stay legal."""
    out = [points[0]]
    start = 0
    while start + 1 < len(points):
        end = start + 1
        for candidate in range(start + 2, len(points)):
            probe = Item(net, (layer,), "capsule",
                         (points[start][0] + points[candidate][0]) / 2.0,
                         (points[start][1] + points[candidate][1]) / 2.0,
                         r=width / 2.0, ends=(points[start], points[candidate]))
            if segment_clear(probe, layer, net, neighbourhood):
                end = candidate
            else:
                break
        out.append(points[end])
        start = end
    return out


#: Parts whose pads escape *towards* the centre of the part.  The FPGA's pad
#: ring is 0.5 mm pitch: a via needs 0.65 mm and a track 0.3 mm of clear space,
#: so a single row of vias outside the ring cannot stagger and the escape dies
#: there.  Inside the package is 18 mm of empty laminate, where the escapes have
#: room to fan out and the vias can be spread.
INWARD_REFS = ("U1",)
INWARD_REACH = 4.0


def fan_out(router: "Router", grid: Grid, pad_items, verbose=True) -> int:
    """Give every pad its own escape track, before the nets are routed.

    The mask blocks a pad's own cells (they are inside copper, and copper is
    copper), so every net leaves its pad through a corridor the router verifies
    against the real geometry.  Doing that in one pass at the start - while the
    board is still empty and every corridor is open - is what lets a 0.5 mm QFP
    fan out at all; done net by net, the later nets find the ring full of their
    neighbours' copper.  A pad that already carries copper (the copper plan's
    escape via) is left alone.
    """
    placement = board.effective_placement()
    laid = 0
    through = 0
    placed: list[tuple[float, float]] = []      # fan-out vias already down
    for ref in sorted(pad_items):
        centre = placement.get(ref, (0.0, 0.0))[:2]
        for item in pad_items[ref]:
            if item.net == Grid.NO_NET:
                continue
            net = grid.net_name(item.net)
            if _pad_has_copper(router, item):
                continue
            width = track_width(net)
            if ref in INWARD_REFS:
                # Every pad of the QFP ring goes *into* the package: the
                # laminate inside is empty, and at 0.15 mm the geometry works
                # out - neighbouring vias 0.5 mm apart in the row are pulled
                # apart by depth (each pad's depth is staggered by a third of
                # a millimetre), so the tracks to the deeper ones thread past
                # the shallower ones with room to spare.  Outward escapes are
                # only a fallback: two neighbours' stubs are 0.3 mm apart and
                # no track fits between them, so an outward ring fills up and
                # seals itself.
                ordinal = _ring_ordinal(item, centre)
                if _via_escape(router, grid, item, net, centre, placed,
                               channel=RING_VIA_CHANNEL,
                               stagger=RING_VIA_STAGGER * (ordinal % 3)):
                    laid += 1
                    through += 1
                    continue
            stub = _escape_stub(router, grid, item, net, width, centre,
                                reach=INWARD_REACH if ref in INWARD_REFS else FANOUT_REACH)
            if stub is None:
                continue
            layer, points = stub
            for a, b in zip(points, points[1:]):
                router.add_segment(a, b, layer, net, width)
            laid += 1
            grid.refresh()
            # A pad at 0.5 mm pitch can only leave the ring on one layer: the
            # stubs of its neighbours seal the free space beside it, and F.Cu
            # ends in a pocket.  So the escape track gets a via - the other
            # layer is empty, and for a plane or pour net that via *is* the
            # connection.  Two rules keep the vias from sealing the layer they
            # are meant to open: a passable channel needs 1.05 mm between two
            # vias (0.45 of via, 0.3 either side for the track), and the via
            # wants to sit as deep on the stub as the space allows.
            tip = _deep_via_spot(router, grid, item.net, points, placed)
            if tip is not None:
                router.add_via(tip[0], tip[1], net)
                placed.append(tip)
                through += 1
                grid.refresh()
    if verbose:
        print("fan-out: %d escape tracks laid, %d of them via to B.Cu" % (laid, through))
    return laid


def _ring_ordinal(item: Item, centre: tuple[float, float]) -> int:
    """Which pad of its row this is, counted round the package.

    A 0.5 mm pad ring has room for one escape lane per *two* pads: two tracks
    need 0.8 mm of centre-to-centre spacing, and two vias need 0.7 mm.  So the
    ring is fanned out by parity - every second pad takes a via into the
    package, the pad between keeps its lane clear for the first one to reach
    the rest of the board through.  This is that parity.
    """
    dx, dy = item.cx - centre[0], item.cy - centre[1]
    along = dy if abs(dx) >= abs(dy) else dx
    return int(round(along / 0.5))


def _via_escape(router: "Router", grid: Grid, item: Item, net: str,
                centre: tuple[float, float], ring_vias: list,
                channel: float | None = None, stagger: float = 0.0) -> bool:
    """Take a pad inward to a via under the package, when a legal one fits.

    A 0.5 mm pad ring cannot hold a via: 0.45 mm of via plus 0.2 mm of
    clearance needs 0.65 mm, and the neighbouring pads are 0.5 mm away.  The
    laminate *inside* the package, on the other hand, is empty - no copper at
    all - so that is where the ring vias.  The search walks a small fan of
    positions inside, nearest first, and lays the stairs to the first one that
    passes the real geometry.  The vias stagger themselves: every via already
    placed is copper, and via_clear() keeps the next one clear of it.
    """
    net_id = grid.net_id(net)
    width = track_width(net)
    channel = VIA_CHANNEL if channel is None else channel
    depths = tuple(round(depth + stagger, 3) for depth in RING_DEPTHS)
    ux, uy = centre[0] - item.cx, centre[1] - item.cy
    length = math.hypot(ux, uy)
    if length < 0.05:
        return False
    ux, uy = ux / length, uy / length
    sx, sy = -uy, ux                        # along the pad row, both ways
    for depth in depths:
        for offset in (0.0, 0.5, -0.5, 1.0, -1.0, 1.5, -1.5, 2.0, -2.0):
            x = item.cx + ux * depth + sx * offset
            y = item.cy + uy * depth + sy * offset
            if not via_clear(grid, x, y, net_id, router.neighbourhood):
                continue
            if not all(math.hypot(x - ox, y - oy) >= channel
                       for ox, oy in ring_vias):
                continue
            for path in (((item.cx, item.cy), (x, item.cy), (x, y)),
                         ((item.cx, item.cy), (item.cx, y), (x, y))):
                probes = [Item(net_id, (F_CU,), "capsule",
                               (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, r=width / 2.0,
                               ends=(a, b)) for a, b in zip(path, path[1:])]
                if not all(segment_clear(probe, F_CU, net_id, router.neighbourhood)
                           for probe in probes):
                    continue
                for a, b in zip(path, path[1:]):
                    router.add_segment(a, b, F_CU, net, width)
                router.add_via(x, y, net)
                ring_vias.append((x, y))
                grid.refresh()
                return True
    return False


VIA_CHANNEL = 1.05            # mm between two vias that a track must pass
RING_VIA_CHANNEL = 0.70       # ...but a ring via only has to keep the rule:
                              # its neighbours are endpoints, not crossings
RING_VIA_STAGGER = 0.5        # mm of depth between neighbouring ring vias, so
                              # a straight stub never lands next to a via
RING_DEPTHS = (1.2, 1.7, 2.2, 2.7, 3.2, 3.8, 4.4)


def _deep_via_spot(router: "Router", grid: Grid, net: int, points,
                   placed) -> tuple[float, float] | None:
    """The deepest point on this escape track that can take a via.

    Walking in from the tip keeps the via as deep as the geometry allows.  A
    candidate is rejected when it is nearer than VIA_CHANNEL to a via this pass
    already placed: two vias 0.65 mm apart are legal but no track can pass
    between them, so a row of them would wall off the layer instead of opening
    it.
    """
    for start, end in reversed(list(zip(points, points[1:]))):
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        steps = max(1, int(length / G))
        for step in range(steps, -1, -1):
            t = step / float(steps)
            x = start[0] + (end[0] - start[0]) * t
            y = start[1] + (end[1] - start[1]) * t
            index = cell_index(x, y)
            cx, cy = index_center(index)
            if not via_clear(grid, cx, cy, net, router.neighbourhood):
                continue
            if not all(math.hypot(cx - ox, cy - oy) >= VIA_CHANNEL
                       for ox, oy in placed):
                continue
            return (cx, cy)
    return None


def _via_on_stub(router: "Router", grid: Grid, net: int, points) -> bool:
    """Drop a via somewhere on this escape track - the deepest legal spot.

    The via is what actually connects: for a plane or a rail pour the via
    reaches the zone, and for everything else it opens the far side of the
    board.  Walking in from the tip keeps the via as deep as the geometry
    allows, which is where there is room for it.
    """
    for start, end in reversed(list(zip(points, points[1:]))):
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        steps = max(1, int(length / G))
        for step in range(steps, -1, -1):
            t = step / float(steps)
            x = start[0] + (end[0] - start[0]) * t
            y = start[1] + (end[1] - start[1]) * t
            index = cell_index(x, y)
            cx, cy = index_center(index)
            if via_clear(grid, cx, cy, net, router.neighbourhood):
                router.add_via(cx, cy, grid.net_name(net))
                return True
    return False


def _walk(came: dict, index: int) -> list[int]:
    """The cell path from a pad to `index`, as recorded by the escape BFS."""
    path = [index]
    while index in came:
        index = came[index]
        path.append(index)
    path.reverse()
    return path


# ---------------------------------------------------------------- verification
def verify(grid: Grid, verbose=True) -> list[str]:
    """Geometric DRC: different nets closer than 0.2 mm, copper off the board."""
    problems: list[str] = []
    # every piece of copper counts, the router's own tracks included: a track
    # lying across a foreign pad is exactly the failure a DRC has to catch
    items = list(grid.items)
    cell = 2.0
    buckets: dict[tuple[int, int], list[Item]] = {}
    for item in items:
        x0, y0, x1, y1 = item.bbox(0.0)
        for gy in range(int(y0 / cell), int(y1 / cell) + 1):
            for gx in range(int(x0 / cell), int(x1 / cell) + 1):
                buckets.setdefault((gx, gy), []).append(item)
    checked = set()
    for bucket in buckets.values():
        if len(bucket) < 2:
            continue
        for i, first in enumerate(bucket):
            for second in bucket[i + 1:]:
                key = (id(first), id(second))
                if key in checked:
                    continue
                checked.add(key)
                if first.net == second.net:
                    continue
                if not (set(first.layers) & set(second.layers)):
                    continue
                gap = first.edge_distance(second)
                if gap < CLEARANCE - 0.005:
                    problems.append("%s (%s) and %s (%s) are %.3f mm apart"
                                    % (first.label(), grid.net_name(first.net),
                                       second.label(), grid.net_name(second.net), gap))
    for item in items:
        x0, y0, x1, y1 = item.bbox(0.0)
        if item.source != "pad":
            if (x0 < EDGE_MARGIN - 0.05 or y0 < EDGE_MARGIN - 0.05
                    or x1 > board.BOARD_W - EDGE_MARGIN + 0.05
                    or y1 > board.BOARD_H - EDGE_MARGIN + 0.05):
                problems.append("%s extends outside the %.2f mm edge margin"
                                % (item.label(), EDGE_MARGIN))
    if verbose:
        print("  DRC: %d items, %d clearance problems" % (len(items), len(problems)))
    return problems


def connectivity(grid: Grid, pad_items, verbose=True) -> list[str]:
    """Union-find over the final copper: every net's pads must be one piece."""
    items = [item for item in grid.items if item.net != Grid.NO_NET]
    parent = list(range(len(items)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    buckets: dict[tuple[int, int], list[int]] = {}
    for index, item in enumerate(items):
        x0, y0, x1, y1 = item.bbox(CLEARANCE + 1.0)
        for gy in range(int(y0 / 2.0), int(y1 / 2.0) + 1):
            for gx in range(int(x0 / 2.0), int(x1 / 2.0) + 1):
                buckets.setdefault((gx, gy), []).append(index)
    for bucket in buckets.values():
        for i, first in enumerate(bucket):
            for second in bucket[i + 1:]:
                a, b = items[first], items[second]
                if a.net != b.net:
                    continue
                if not (set(a.layers) & set(b.layers)):
                    continue
                if a.edge_distance(b) <= 0.0:
                    union(first, second)
    islands: dict[tuple[str, str], int] = {}
    for index, item in enumerate(items):
        net = grid.net_name(item.net)
        island = Router.pour_island(item, net)
        if island is None:
            continue
        key = (net, island)
        if key not in islands:
            islands[key] = index
        else:
            union(index, islands[key])

    problems = []
    by_net: dict[int, list[int]] = {}
    for index, item in enumerate(items):
        if item.source == "pad":
            by_net.setdefault(item.net, []).append(index)
    for net, indices in sorted(by_net.items(), key=lambda kv: grid.net_name(kv[0])):
        roots = {find(index) for index in indices}
        if len(roots) > 1:
            pads = [items[index].label() for index in indices]
            problems.append("%s: %d pads in %d pieces (%s)"
                            % (grid.net_name(net), len(indices), len(roots),
                               ", ".join(sorted(pads)[:6]) + ("..." if len(pads) > 6 else "")))
    if verbose:
        print("  connectivity: %d nets with pads, %d nets in more than one piece"
              % (len(by_net), len(problems)))
    return problems


def check(quiet: bool = False) -> int:
    """Re-run the DRC and the connectivity check on the routing on disk.

    This is the acceptance test for `make pcb-check`: it takes `routing.json`,
    puts its copper back on the board and asks the same two questions the
    router asked while routing - is anything too close, and is every net one
    piece - plus whether the file still belongs to this board at all.
    """
    if not ROUTING_FILE.exists():
        # Nothing to verify yet.  Not an error: `make route` writes this file,
        # and until it does the board is the unrouted base - which the other
        # checks cover.  Silence would hide the fact, though, so say it.
        if not quiet:
            print("no %s yet: run `make route` to lay the signal copper"
                  % ROUTING_FILE.relative_to(ROOT))
        return 0
    data = json.loads(ROUTING_FILE.read_text())
    grid, neighbourhood, pad_items = build(verbose=not quiet)
    router = Router(grid, neighbourhood)
    for via in data.get("vias", []):
        router.add_via(via["x"], via["y"], via["net"])
    for segment in data.get("segments", []):
        layer = F_CU if segment["layer"] == "F.Cu" else B_CU
        router.add_segment(tuple(segment["start"]), tuple(segment["end"]), layer,
                           segment["net"], segment["width"])
    grid.refresh()

    digest = data.get("board_digest", "")
    stale = digest and digest != board.board_digest()
    print("routing.json: %d segments, %d vias (%s)"
          % (len(data.get("segments", [])), len(data.get("vias", [])),
             "laid on this board" if not stale else "STALE: re-run make route"))
    problems = verify(grid, verbose=not quiet)
    for line in problems[:20]:
        print("  DRC: " + line)
    unconnected = connectivity(grid, pad_items, verbose=not quiet)
    for line in unconnected[:20]:
        print("  UNCONNECTED: " + line)
    failures = data.get("stats", {}).get("failures", [])
    if stale:
        print("  FAIL: routing.json is stale (digest %s, board %s)"
              % (digest, board.board_digest()))
    if failures:
        print("  note: the router reported %d connections it could not make" % len(failures))
        for line in failures[:10]:
            print("    " + line)
    if problems or unconnected or stale:
        print("ROUTING FAILED: %d clearance problems, %d nets in pieces%s"
              % (len(problems), len(unconnected), ", stale file" if stale else ""))
        return 1
    print("ROUTING OK: no clearance problems, every net is one piece")
    return 0


# ------------------------------------------------------------------------ main
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--nets", default="", help="comma-separated subset")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.check:
        return check(quiet=args.quiet)

    if args.report:
        if not ROUTING_FILE.exists():
            print("no routing yet: run scripts/sv16_pcb_route.py first")
            return 1
        data = json.loads(ROUTING_FILE.read_text())
        print("routing.json: %d segments, %d vias" % (len(data["segments"]), len(data["vias"])))
        for key, value in sorted(data.get("stats", {}).items()):
            print("  %-14s %s" % (key, value))
        return 0

    started = time.time()
    grid, neighbourhood, pad_items = build(verbose=not args.quiet)
    router = Router(grid, neighbourhood)

    order = routing_order(grid, pad_items)
    if args.nets:
        wanted = {name.strip() for name in args.nets.split(",")}
        order = [net for net in order if net in wanted]
    else:
        fan_out(router, grid, pad_items, verbose=not args.quiet)

    print("routing %d nets" % len(order))
    for net in order:
        pads = net_pads(grid, pad_items, net)
        if not pads:
            continue
        existing = [item for item in grid.items
                    if item.net == grid.net_id(net) and item.source != "pad"]
        entries = pour_entry_cells(net)
        before = len(router.new_segments) + len(router.new_vias)
        router.route_net(net, pads, existing, entries)
        after = len(router.new_segments) + len(router.new_vias)
        if after > before and not args.quiet:
            print("  %-14s %2d pads, %d new items" % (net, len(pads), after - before))

    print("routed %d segments, %d vias in %.1f s"
          % (len(router.new_segments), len(router.new_vias), time.time() - started))
    if router.violations:
        print("SELF-CHECK (%d): copper that was laid where it should not fit"
              % len(router.violations))
        for line in router.violations[:12]:
            print("  " + line)
    if router.failures:
        print("FAILURES (%d):" % len(router.failures))
        for line in router.failures:
            print("  " + line)
        if not args.quiet:
            for line in router.log:
                print("  why: " + line)

    problems = verify(grid, verbose=not args.quiet)
    for line in problems[:20]:
        print("  DRC: " + line)
    unconnected = connectivity(grid, pad_items, verbose=not args.quiet)
    for line in unconnected[:20]:
        print("  UNCONNECTED: " + line)

    result = {
        "generator": "sv16_pcb_route.py",
        "board_digest": board.board_digest(),
        "grid_mm": G,
        "clearance_mm": CLEARANCE,
        "via_diameter_mm": VIA_DIA,
        "segments": router.new_segments,
        "vias": router.new_vias,
        "stats": {
            "nets": len(order),
            "segments": len(router.new_segments),
            "vias": len(router.new_vias),
            "failures": router.failures,
            "drc_problems": problems,
            "unconnected": unconnected,
            "seconds": round(time.time() - started, 1),
        },
    }
    if not args.no_write and not args.nets:
        ROUTING_FILE.write_text(json.dumps(result, indent=1) + "\n")
        print("wrote %s" % ROUTING_FILE.relative_to(ROOT))
    return 1 if (problems or unconnected or router.failures) else 0


if __name__ == "__main__":
    sys.exit(main())
