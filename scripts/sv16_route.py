#!/usr/bin/env python3
"""Route the SV-16 board: 4 layers, no KiCad in the loop.

There is no autorouter in this container (no KiCad, no Java, no Freerouting), so
the copper is generated here and then checked with `sv16_board_drc.py`, which
does the same arithmetic KiCad's DRC does.  The stack-up the router builds is
the classic four-layer one:

    F.Cu    signals (and the U1 fan-out)
    In1.Cu  solid GND plane
    In2.Cu  3V3 plane with carved channels for the other rails
    B.Cu    signals + a GND pour

What it does, in order:

 1. fan-out U1 (144 pins on 0.5 mm pitch): every pin gets a 0.12 mm stub to a
    0.30/0.15 via, staggered 0.7 mm / 1.25 mm from the pad row.  Two pins
    0.5 mm apart cannot both be escaped any other way, which is why the LQFP
    land pattern uses 0.25 mm pads (0.25 mm gap) and the FPGA's nets use the
    0.20 mm clearance rule;
 2. a via next to every SMD pad of a plane net (GND, 3V3, 1V1, 2V5, VM_IN,
    VM_IN_RAW, USB_VBUS) so the pad reaches its plane;
 3. the rails that are not the planes (1V1, 2V5, VM_IN, VM_IN_RAW, USB_VBUS)
    get wide spines on In2, routed shortest-first with the same maze router;
 4. every signal net is routed on F.Cu/B.Cu with A* on a 0.1 mm grid (octile
    moves, a via costs 2.5 mm of track, a bend 0.1 mm), shortest nets first so
    the local wires never fight the buses;
 5. the planes are filled: 3V3 covers what is left of In2, GND covers In1 and
    the bottom, and every foreign pad, track and via is cut out with its net
    class clearance (holes are fractured out the way KiCad does it);
 6. the copper is written to `hardware/sv16_board/routing.kicad_pcb.txt`, which
    `sv16_board_kicad.py` splices into the board file.

    .venv/bin/python scripts/sv16_route.py            # route and write the snippet
    .venv/bin/python scripts/sv16_route.py --dry-run  # just report

Needs `shapely` and `numpy`.  Geometry is board millimetres, KiCad's Y-down
axis, board origin at the top-left corner.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sv16_board_drc import (BOARD_FILE, BOARD_H, BOARD_W, CLASS_OF_NET,  # noqa: E402
                            clearance_for, load_board)

ROOT = Path(__file__).resolve().parent.parent
SNIPPET = ROOT / "hardware" / "sv16_board" / "routing.kicad_pcb.txt"

CELL = 0.1                      # mm, router grid
LAYERS = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")
SIGNAL_LAYERS = ("F.Cu", "B.Cu")
GND_PLANE = "In1.Cu"
PWR_PLANE = "In2.Cu"
VIA_COST = 25                   # cells of track a via is worth (2.5 mm)
BEND_COST = 1.0                 # cells of turn penalty so routes look like routes
SLACK = CELL * 0.71             # a diagonal step must not cut a corner

WIDTH = {"Default": 0.20, "Power": 0.50, "Switching": 0.50, "USB": 0.20,
         "JTAG": 0.25, "Fine": 0.15}
SPINE_WIDTH = {"1V1": 2.00, "2V5": 1.20, "VM_IN": 1.50, "VM_IN_RAW": 1.50,
               "USB_VBUS": 0.80}
PLANE_NETS = ("GND", "3V3", "1V1", "2V5", "VM_IN", "VM_IN_RAW", "USB_VBUS")

FANOUT_VIA = (0.30, 0.15)
FANOUT_STUB = 0.12
FANOUT_R = (0.70, 1.25)
ESCAPE_VIA = (0.45, 0.25)
ROUTE_VIA = (0.60, 0.30)
EDGE = 0.30
U1_RING = Polygon([(38.1, 38.1), (65.9, 38.1), (65.9, 65.9), (38.1, 65.9)])


# ----------------------------------------------------------------- board model
class Item:
    """A piece of copper: a pad, a via or a track."""

    def __init__(self, kind, geom, net, layers, width=0.0, ref=None, pad=None, smd=True):
        self.kind, self.geom, self.net = kind, geom, net
        self.layers = tuple(layers)
        self.width = width
        self.ref, self.pad = ref, pad
        self.smd = smd
        self.via = None                       # escape via, when one was placed

    def on(self, layer):
        return layer in self.layers


class Board:
    def __init__(self, path=BOARD_FILE):
        shapes, footprints, tracks, vias, zones = load_board(path)
        self.footprints = footprints
        self.items = []
        self.pads_by_net = defaultdict(list)
        self.u1_pads = []
        for shape in shapes:
            item = Item("pad", shape.to_polygon(), shape.net, shape.layers, 0.0,
                        shape.ref, shape.pad, shape.smd)
            self.items.append(item)
            if shape.net:
                self.pads_by_net[shape.net].append(item)
            if shape.ref == "U1":
                self.u1_pads.append((shape, item))
        self.u1_pads.sort(key=lambda pair: int(pair[0].pad))
        self.nets = sorted(self.pads_by_net)
        self.new_tracks, self.new_vias = [], []
        self.notes = []

    # ---- helpers -----------------------------------------------------------
    def class_of(self, net):
        return CLASS_OF_NET.get(net or "NC", "Default")

    def width_of(self, net):
        return WIDTH[self.class_of(net)]

    def clearance(self, net_a, net_b):
        return clearance_for(net_a, net_b)

    def add_track(self, a, b, width, layer, net):
        geom = LineString([a, b]).buffer(width / 2.0, cap_style=1, quad_segs=8)
        item = Item("track", geom, net, (layer,), width)
        self.items.append(item)
        self.new_tracks.append((a, b, width, layer, net))
        return item

    def add_via(self, x, y, size, drill, net):
        geom = Point(x, y).buffer(size / 2.0, quad_segs=24)
        item = Item("via", geom, net, LAYERS, size)
        self.items.append(item)
        self.new_vias.append((x, y, size, drill, net))
        return item

    @staticmethod
    def center(item):
        return item.geom.centroid.x, item.geom.centroid.y


# ------------------------------------------------------------------- raster
class Layer:
    """A boolean occupancy window on one copper layer."""

    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.nx = int(math.ceil((x1 - x0) / CELL)) + 1
        self.ny = int(math.ceil((y1 - y0) / CELL)) + 1
        self.data = np.zeros((self.ny, self.nx), dtype=np.uint8)

    def center(self, ix, iy):
        return (self.x0 + (ix + 0.5) * CELL, self.y0 + (iy + 0.5) * CELL)

    def paint(self, geom, extra, value=1):
        if geom.is_empty:
            return
        x0, y0, x1, y1 = geom.bounds
        if x1 + extra < self.x0 or x0 - extra > self.x1:
            return
        if y1 + extra < self.y0 or y0 - extra > self.y1:
            return
        grown = geom.buffer(extra, quad_segs=8) if extra else geom
        gx0, gy0, gx1, gy1 = grown.bounds
        i0 = max(0, int(math.floor((gx0 - self.x0) / CELL)))
        i1 = min(self.nx, int(math.ceil((gx1 - self.x0) / CELL)) + 1)
        j0 = max(0, int(math.floor((gy0 - self.y0) / CELL)))
        j1 = min(self.ny, int(math.ceil((gy1 - self.y0) / CELL)) + 1)
        if i1 <= i0 or j1 <= j0:
            return
        from shapely import contains_xy
        xs = self.x0 + (np.arange(i0, i1) + 0.5) * CELL
        ys = self.y0 + (np.arange(j0, j1) + 0.5) * CELL
        grid_x, grid_y = np.meshgrid(xs, ys)
        hit = contains_xy(grown, grid_x, grid_y)
        view = self.data[j0:j1, i0:i1]
        if value > 0:
            view[hit] = 1
        else:
            view[hit] = 0

    def blocked(self):
        return self.data != 0


def window_for(points, margin):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (max(0.0, min(xs) - margin), max(0.0, min(ys) - margin),
            min(BOARD_W, max(xs) + margin), min(BOARD_H, max(ys) + margin))


def track_mask(board, net, width, bounds, layers=SIGNAL_LAYERS):
    """Where a track of `net` may run: clear of every foreign piece of copper."""
    win = {name: Layer(*bounds) for name in layers}
    for item in board.items:
        if item.net == net:
            continue
        extra = width / 2.0 + SLACK + board.clearance(net, item.net)
        for name in layers:
            if item.on(name):
                win[name].paint(item.geom, extra)
    return win


def via_mask(board, net, size, bounds):
    """Where a via of `net` may go: clear on every layer it drills through."""
    win = Layer(*bounds)
    for item in board.items:
        if item.net == net:
            continue
        win.paint(item.geom, size / 2.0 + SLACK + board.clearance(net, item.net))
    return win


def free_for(board, net, width, bounds, layers=SIGNAL_LAYERS):
    """Masks for routing `net`, with its own copper carved back out."""
    win = track_mask(board, net, width, bounds, layers)
    for item in board.items:
        if item.net != net:
            continue
        for name in layers:
            if item.on(name):
                win[name].paint(item.geom, 0.0, value=0)
    return win


# --------------------------------------------------------------------- A*
NEIGHBOURS = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
              (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142))


def astar(windows, via_ok, starts, goals, via_cost=VIA_COST, bend_cost=BEND_COST):
    """A* from any start cell to any goal cell; returns a cell path or None."""
    names = list(windows)
    free = {name: (windows[name].data == 0) for name in names}
    goal_set = set(goals)
    goal_xy = [windows[name].center(ix, iy) for name, ix, iy in goals]
    nx, ny = windows[names[0]].nx, windows[names[0]].ny

    def h(name, ix, iy):
        cx, cy = windows[name].center(ix, iy)
        return min(math.hypot(cx - gx, cy - gy) for gx, gy in goal_xy) / CELL

    heap, came, best = [], {}, {}
    for start in starts:
        best[start] = 0.0
        heapq.heappush(heap, (h(*start), 0.0, start))
    seen = set()
    while heap:
        _, cost, node = heapq.heappop(heap)
        if node in seen:
            continue
        seen.add(node)
        if node in goal_set:
            path, cur = [], node
            while cur is not None:
                path.append(cur)
                cur = came.get(cur)
            return list(reversed(path))
        name, ix, iy = node
        grid = free[name]
        head = came.get(node)
        for dx, dy, step in NEIGHBOURS:
            jx, jy = ix + dx, iy + dy
            if jx < 0 or jy < 0 or jx >= nx or jy >= ny or not grid[jy, jx]:
                continue
            if dx and dy and (not grid[iy, jx] or not grid[jy, ix]):
                continue
            bend = bend_cost if (head is not None and
                                 (ix - head[1], iy - head[2]) != (dx, dy)) else 0.0
            new_cost = cost + step + bend
            key = (name, jx, jy)
            if new_cost < best.get(key, 1e30):
                best[key] = new_cost
                came[key] = node
                heapq.heappush(heap, (new_cost + h(name, jx, jy), new_cost, key))
        if via_ok is not None and via_ok[iy, ix]:
            for other in names:
                if other == name:
                    continue
                key = (other, ix, iy)
                new_cost = cost + via_cost
                if new_cost < best.get(key, 1e30):
                    best[key] = new_cost
                    came[key] = node
                    heapq.heappush(heap, (new_cost + h(other, ix, iy), new_cost, key))
    return None


def cell_of(win, x, y):
    return (int((x - win.x0) / CELL), int((y - win.y0) / CELL))


def cells_touching(win, geom, radius=1):
    x0, y0, x1, y1 = geom.bounds
    i0 = max(0, int((x0 - win.x0) / CELL) - radius)
    i1 = min(win.nx - 1, int((x1 - win.x0) / CELL) + radius)
    j0 = max(0, int((y0 - win.y0) / CELL) - radius)
    j1 = min(win.ny - 1, int((y1 - win.y0) / CELL) + radius)
    return [(ix, iy) for ix in range(i0, i1 + 1) for iy in range(j0, j1 + 1)]


def emit(board, path, windows, width, net, via_size, via_drill, snap_first=None,
         snap_last=None):
    """Cell path -> tracks and vias."""
    points = [(name,) + windows[name].center(ix, iy) for name, ix, iy in path]
    if snap_first:
        points[0] = (points[0][0], snap_first[0], snap_first[1])
    if snap_last:
        points[-1] = (points[-1][0], snap_last[0], snap_last[1])
    vertex = [points[0]]
    for point in points[1:]:
        if point[0] == vertex[-1][0] and len(vertex) >= 2:
            (x0, y0), (x1, y1) = vertex[-2][1:], vertex[-1][1:]
            if abs((x1 - x0) * (point[2] - y1) - (y1 - y0) * (point[1] - x1)) < 1e-6:
                vertex[-1] = point
                continue
        if point[0] != vertex[-1][0]:
            board.add_via(vertex[-1][1], vertex[-1][2], via_size, via_drill, net)
            vertex.append(point)
        else:
            vertex.append(point)
    for index in range(len(vertex) - 1):
        a, b = vertex[index], vertex[index + 1]
        if a[0] != b[0] or (abs(a[1] - b[1]) < 1e-9 and abs(a[2] - b[2]) < 1e-9):
            continue
        board.add_track((a[1], a[2]), (b[1], b[2]), width, a[0], net)


def clash(board, geom, radius, net, exclude=None):
    grown = geom.buffer(radius, quad_segs=8)
    for item in board.items:
        if item is exclude or item.net == net:
            continue
        if item.geom.intersects(grown):
            return True
    return False


def in_ring(x, y):
    return U1_RING.contains(Point(x, y))


# ------------------------------------------------------------------ fan-out
def normals_for(shape, cx, cy):
    if abs(cx - 52.0) > abs(cy - 52.0):
        return (1.0, 0.0) if cx > 52.0 else (-1.0, 0.0), shape.w / 2.0
    return (0.0, 1.0) if cy > 52.0 else (0.0, -1.0), shape.h / 2.0


def side_of(cx, cy):
    if abs(cx - 52.0) > abs(cy - 52.0):
        return "E" if cx > 52.0 else "W"
    return "S" if cy > 52.0 else "N"


def fanout_u1(board, verbose=True):
    sides = defaultdict(list)
    for shape, item in board.u1_pads:
        cx, cy = Board.center(item)
        sides[side_of(cx, cy)].append((shape, item, cx, cy))
    made = skipped = 0
    for side, pads in sides.items():
        for index, (shape, item, cx, cy) in enumerate(pads):
            if item.net is None:
                skipped += 1
                continue
            (nx, ny), half = normals_for(shape, cx, cy)
            radius = half + FANOUT_R[index % 2]
            vx, vy = cx + nx * radius, cy + ny * radius
            if not (EDGE < vx < BOARD_W - EDGE and EDGE < vy < BOARD_H - EDGE):
                board.notes.append("fan-out off board: U1.%s" % item.pad)
                continue
            board.add_track((cx, cy), (vx, vy), FANOUT_STUB, "F.Cu", item.net)
            via = board.add_via(vx, vy, FANOUT_VIA[0], FANOUT_VIA[1], item.net)
            item.via = (vx, vy)
            made += 1
    if verbose:
        print("  U1 fan-out: %d pins escaped, %d pins have no net"
              % (made, skipped))


def escape_plane_pads(board, verbose=True):
    made, missed = 0, 0
    for net in PLANE_NETS:
        for item in board.pads_by_net.get(net, []):
            if not item.smd or item.via:
                continue
            cx, cy = Board.center(item)
            x0, y0, x1, y1 = item.geom.bounds
            along = (0.0, 1.0) if (y1 - y0) >= (x1 - x0) else (1.0, 0.0)
            spot = None
            for distance in (0.55, 0.75, 1.0, 1.3, 1.7):
                for sign in (1, -1):
                    vx = cx + along[0] * distance * sign
                    vy = cy + along[1] * distance * sign
                    if not (EDGE < vx < BOARD_W - EDGE and EDGE < vy < BOARD_H - EDGE):
                        continue
                    if in_ring(vx, vy):
                        continue
                    if clash(board, Point(vx, vy), ESCAPE_VIA[0] / 2.0, net):
                        continue
                    spot = (vx, vy)
                    break
                if spot:
                    break
            if not spot:
                missed += 1
                board.notes.append("no escape via for %s.%s (%s)" % (item.ref, item.pad, net))
                continue
            board.add_track((cx, cy), spot, min(0.30, board.width_of(net)), "F.Cu", net)
            board.add_via(spot[0], spot[1], ESCAPE_VIA[0], ESCAPE_VIA[1], net)
            item.via = spot
            made += 1
    if verbose:
        print("  plane-net escapes: %d vias (%d missed)" % (made, missed))


# ------------------------------------------------------------------ routing
def entry_points(board, net):
    """Where the net's copper can be entered: pads, and the vias it owns."""
    nodes = []
    for item in board.pads_by_net.get(net, []):
        nodes.append({"item": item, "xy": Board.center(item), "layers": item.layers,
                      "geom": item.geom, "kind": "pad"})
    for x, y, size, drill, vnet in board.new_vias:
        if vnet != net:
            continue
        nodes.append({"item": None, "xy": (x, y), "layers": LAYERS, "kind": "via",
                      "geom": Point(x, y).buffer(size / 2.0, quad_segs=8)})
    for track in board.new_tracks:
        pass
    return nodes


def net_span(nodes):
    xs = [n["xy"][0] for n in nodes]
    ys = [n["xy"][1] for n in nodes]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def connect(board, net, target, width, to_node, via_size, via_drill,
            layers=SIGNAL_LAYERS, margin=None):
    """Route one connection: from the already-routed copper to `to_node`.

    The window is kept as tight as the connection allows - an A* over a
    board-sized window explores a million cells and takes minutes, and almost
    every connection here needs a window a fraction of that.  If the tight
    window fails, the caller asks again with a bigger one.
    """
    near = min(target, key=lambda n: math.hypot(n["xy"][0] - to_node["xy"][0],
                                                n["xy"][1] - to_node["xy"][1]))
    span = math.hypot(near["xy"][0] - to_node["xy"][0], near["xy"][1] - to_node["xy"][1])
    if margin is None:
        margin = min(12.0, max(3.0, 0.5 * span))
    bounds = window_for([near["xy"], to_node["xy"]], margin)
    windows = free_for(board, net, width, bounds, layers)
    vmask = via_mask(board, net, via_size, bounds)
    starts, goals = [], []
    for node in target:
        for layer in layers:
            if layer in node["layers"]:
                starts += [(layer, ix, iy)
                           for ix, iy in cells_touching(windows[layer], node["geom"], 1)]
    for layer in layers:
        if layer in to_node["layers"]:
            goals += [(layer, ix, iy)
                      for ix, iy in cells_touching(windows[layer], to_node["geom"], 1)]
    if not starts or not goals:
        return False, "no start or goal cell"
    via_ok = (vmask.data == 0) if len(layers) > 1 else None
    path = astar(windows, via_ok, starts, goals)
    if path is None:
        return False, "no path in a %.0f mm window" % margin
    emit(board, path, windows, width, net, via_size, via_drill,
         snap_first=near["xy"], snap_last=to_node["xy"])
    return True, ""


def route_net(board, net, verbose=False):
    """Join every entry point of a net to the copper already routed for it."""
    nodes = entry_points(board, net)
    if len(nodes) < 2:
        return True
    width = board.width_of(net)
    joined = [nodes[0]]
    ok = True
    remaining = nodes[1:]
    while remaining:
        # always grow from the closest unconnected point: short paths, and the
        # maze router never has to cross the whole board
        best = min(((min(math.hypot(n["xy"][0] - r["xy"][0], n["xy"][1] - r["xy"][1])
                         for n in joined), index) for index, r in enumerate(remaining)))
        node = remaining.pop(best[1])
        good, why = False, ""
        for margin in (None, 6.0, 12.0, 20.0):
            good, why = connect(board, net, joined, width, node,
                                ROUTE_VIA[0], ROUTE_VIA[1], margin=margin)
            if good:
                break
        if not good:
            where = ("%s.%s" % (node["item"].ref, node["item"].pad)) if node["item"] else "via"
            board.notes.append("unrouted %s -> %s (%s)" % (net, where, why))
            ok = False
        joined.append(node)
        if verbose:
            print("      %s -> %s: %s" % (net, node["xy"], "ok" if good else why))
    return ok


def route_spines(board, verbose=True):
    """The rails that are not planes: wide copper on In2, shortest first."""
    spines = sorted(SPINE_WIDTH.items(), key=lambda kv: kv[1])
    for net in ("2V5", "1V1", "USB_VBUS", "VM_IN_RAW", "VM_IN"):
        if net not in SPINE_WIDTH:
            continue
        nodes = [n for n in entry_points(board, net)
                 if n["kind"] == "via" or "In2.Cu" in n["layers"]]
        if len(nodes) < 2:
            continue
        width = SPINE_WIDTH[net]
        joined = [nodes[0]]
        for node in nodes[1:]:
            good, why = connect(board, net, joined, width, node,
                                ROUTE_VIA[0], ROUTE_VIA[1], layers=("In2.Cu",), margin=20.0)
            if not good:
                board.notes.append("spine %s -> %s unrouted (%s)" % (net, node["xy"], why))
            joined.append(node)
        if verbose:
            print("  spine %-10s %.2f mm wide, %d nodes" % (net, width, len(nodes)))


def signal_nets(board):
    out = []
    for net in board.nets:
        if net in PLANE_NETS:
            continue
        nodes = entry_points(board, net)
        if len(nodes) >= 2:
            out.append((net_span(nodes), net))
    out.sort()
    return [net for _, net in out]


# ------------------------------------------------------------------- planes
def closest_pair(outer, hole, cell_budget=2_000_000):
    """Index of the closest pair of vertices between two rings.

    The outline grows by every hole's vertices - on a real plane that is tens
    of thousands of points against hundreds per hole, so the comparison is done
    in row blocks: the full matrix would be hundreds of megabytes and the
    out-of-memory killer takes the process down.
    """
    outer_xy = np.asarray(outer, dtype=float)
    hole_xy = np.asarray(hole, dtype=float)
    step = max(1, int(cell_budget // max(1, len(hole_xy))))
    best_distance, best_oi, best_hi = float("inf"), 0, 0
    for start in range(0, len(outer_xy), step):
        block = outer_xy[start:start + step]
        delta = block[:, None, :] - hole_xy[None, :, :]
        distance = (delta * delta).sum(axis=2)
        flat = int(distance.argmin())
        row, column = divmod(flat, distance.shape[1])
        if distance[row, column] < best_distance:
            best_distance = float(distance[row, column])
            best_oi, best_hi = start + int(row), int(column)
    return best_oi, best_hi


def fracture(poly):
    """One hole-free ring for a polygon with holes (KiCad's own keyhole trick).

    Each hole is joined to the outline by a zero-width slit.  Finding the
    closest pair of vertices is done with numpy: the outline grows by every
    hole's vertices, so a Python double loop over it is quadratic and takes
    ten minutes on a plane with a few hundred holes.
    """
    outer = list(poly.exterior.coords)
    for ring in poly.interiors:
        hole = list(ring.coords)
        oi, hi = closest_pair(outer, hole)
        slit = outer[oi]
        loop = hole[hi:] + hole[1:hi + 1]
        outer = outer[:oi + 1] + [slit] + loop + [slit] + outer[oi:]
    return outer


def rings_of(geom):
    out = []
    for poly in getattr(geom, "geoms", [geom]):
        if poly.is_empty:
            continue
        if isinstance(poly, Polygon):
            ring = fracture(poly)
            if len(ring) >= 4:
                out.append(ring)
    return out


def plane_fill(board, layer, net, verbose=False):
    """Copper for a plane: the board minus every foreign piece of copper.

    The keep-outs are unioned first and subtracted in one go.  Subtracting them
    one at a time rebuilds the plane after every hole, which is quadratic and
    takes tens of minutes on a board with 1,500 pads.
    """
    area = box(EDGE, EDGE, BOARD_W - EDGE, BOARD_H - EDGE)
    holes = []
    for item in board.items:
        if item.net == net or not item.on(layer):
            continue
        holes.append(item.geom.buffer(board.clearance(net, item.net) + 0.05,
                                      quad_segs=8))
    if holes:
        area = area.difference(unary_union(holes))
    # 0.01 mm is a tenth of the routing grid: it throws away the rounded corners
    # the clearance buffers add, which cuts the vertex count by several times and
    # is far below anything the fab can resolve
    rings = rings_of(area.simplify(0.01))
    if verbose:
        print("  plane %-4s on %-6s: %d ring(s), %d vertices"
              % (net, layer, len(rings), sum(len(r) for r in rings)))
    return rings


def build_planes(board, verbose=True):
    return [("GND", GND_PLANE, plane_fill(board, GND_PLANE, "GND", verbose)),
            ("3V3", PWR_PLANE, plane_fill(board, PWR_PLANE, "3V3", verbose)),
            ("GND", "B.Cu", plane_fill(board, "B.Cu", "GND", verbose))]



# ------------------------------------------------------------------ checkpoint
CHECKPOINT = ROOT / "hardware" / "sv16_board" / "routing_state.json"


def save_state(board, path=CHECKPOINT):
    """Dump the copper routed so far, so a long run can be resumed."""
    data = {"tracks": [[list(a), list(b), w, layer, net]
                       for a, b, w, layer, net in board.new_tracks],
            "vias": [[x, y, size, drill, net] for x, y, size, drill, net in board.new_vias]}
    path.write_text(json.dumps(data))
    return len(data["tracks"])


def load_state(board, path=CHECKPOINT):
    """Put a saved checkpoint back on the board."""
    if not path.exists():
        return 0
    data = json.loads(path.read_text())
    for a, b, w, layer, net in data["tracks"]:
        board.add_track(tuple(a), tuple(b), w, layer, net)
    for x, y, size, drill, net in data["vias"]:
        board.add_via(x, y, size, drill, net)
    return len(data["tracks"])


def rip_net(board, net):
    """Take a net's copper back off so it can be routed again."""
    board.new_tracks = [t for t in board.new_tracks if t[4] != net]
    board.new_vias = [v for v in board.new_vias if v[4] != net]
    board.notes = [n for n in board.notes if not n.startswith("unrouted %s " % net)]


# --------------------------------------------------------------------- output
def net_numbers(board):
    text = BOARD_FILE.read_text()
    table = {}
    for match in re.finditer(r'\(net (\d+) "([^"]+)"\)', text):
        table.setdefault(match.group(2), int(match.group(1)))
    for match in re.finditer(r'\(add_net (\d+) "([^"]+)"\)', text):
        table.setdefault(match.group(2), int(match.group(1)))
    return table


def write_snippet(board, zones, path):
    numbers = net_numbers(board)
    lines = []
    for a, b, width, layer, net in board.new_tracks:
        lines.append('  (segment (start %.3f %.3f) (end %.3f %.3f) (width %.2f) (layer "%s") '
                     "(net %d))" % (a[0], a[1], b[0], b[1], width, layer, numbers.get(net, 0)))
    for x, y, size, drill, net in board.new_vias:
        lines.append('  (via (at %.3f %.3f) (size %.2f) (drill %.2f) (layers "F.Cu" "B.Cu") '
                     "(net %d))" % (x, y, size, drill, numbers.get(net, 0)))
    for index, (net, layer, rings) in enumerate(zones):
        lines.append('  (zone (net %d) (net_name "%s") (layer "%s")'
                     " (uuid 5f16b0aa-0000-4000-8000-%012d)"
                     % (numbers.get(net, 0), net, layer, index))
        lines.append("    (hatch edge 0.5) (connect_pads (clearance 0.3)) (min_thickness 0.25)")
        lines.append("    (fill yes (thermal_gap 0.3) (thermal_bridge_width 0.3))")
        lines.append("    (polygon (pts (xy %.2f %.2f) (xy %.2f %.2f) (xy %.2f %.2f) (xy %.2f %.2f)))"
                     % (EDGE, EDGE, BOARD_W - EDGE, EDGE, BOARD_W - EDGE, BOARD_H - EDGE,
                        EDGE, BOARD_H - EDGE))
        for ring in rings:
            lines.append('    (filled_polygon (layer "%s")' % layer)
            lines.append("      (pts")
            chunk = []
            for (x, y) in ring:
                chunk.append("(xy %.3f %.3f)" % (x, y))
                if len(chunk) == 6:
                    lines.append("        " + " ".join(chunk))
                    chunk = []
            if chunk:
                lines.append("        " + " ".join(chunk))
            lines.append("      )")
            lines.append("    )")
        lines.append("  )")
    path.write_text("\n".join(lines) + "\n")
    return len(lines)


# ----------------------------------------------------------------------- main
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", default="all",
                        choices=("fanout", "spines", "signals", "planes", "all"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--board", default=str(BOARD_FILE))
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--resume", action="store_true",
                        help="reload the copper saved in routing_state.json")
    parser.add_argument("--repair", type=int, default=2,
                        help="rip-up-and-reroute rounds for nets that failed")
    args = parser.parse_args()

    start = time.time()
    board = Board(args.board)
    print("routing %s: %d nets, %d pads"
          % (Path(args.board).name, len(board.nets),
             sum(len(v) for v in board.pads_by_net.values())))

    if args.stage in ("fanout", "all", "spines", "signals", "planes"):
        fanout_u1(board)
        escape_plane_pads(board)

    nets = signal_nets(board)
    print("  signal nets: %d (shortest %.1f mm, longest %.1f mm)"
          % (len(nets), net_span(entry_points(board, nets[0])),
             net_span(entry_points(board, nets[-1]))))

    routed = failed = 0
    if args.stage in ("spines", "signals", "all"):
        if args.resume:
            n = load_state(board)
            print("  resumed %d tracks from %s" % (n, CHECKPOINT.name))
        else:
            route_spines(board)
            save_state(board)
    if args.stage in ("signals", "all"):
        for index, net in enumerate(nets, 1):
            if args.resume:
                continue
            if route_net(board, net, args.verbose):
                routed += 1
            else:
                failed += 1
            if index % 10 == 0 or index == len(nets):
                save_state(board)
                print("    %d/%d nets, %d tracks, %d vias, %d unrouted, %.0f s"
                      % (index, len(nets), len(board.new_tracks), len(board.new_vias),
                         len([n for n in board.notes if n.startswith("unrouted")]),
                         time.time() - start), flush=True)

    # Repair: nets that failed on the first pass get another go with the other
    # nets' copper lifted out of the way.  Two rounds is enough to clear all
    # but the genuinely boxed-in ones.
    for round_number in range(1, args.repair + 1):
        broken = sorted({note.split()[1] for note in board.notes
                         if note.startswith("unrouted")})
        if not broken:
            break
        print("  repair pass %d: %d net(s)" % (round_number, len(broken)), flush=True)
        still_broken = []
        for net in broken:
            rip_net(board, net)
            ok = route_net(board, net, args.verbose)
            if not ok:
                still_broken.append(net)
        failed = len(still_broken)
        routed = len(nets) - failed
        print("    after repair %d: %d routed, %d failed" % (round_number, routed, failed),
              flush=True)
        save_state(board)

    print("  routed: %d   failed: %d   tracks: %d   vias: %d"
          % (routed, failed, len(board.new_tracks), len(board.new_vias)))

    zones = build_planes(board) if args.stage in ("planes", "all") else []
    if board.notes:
        print("  notes (%d):" % len(board.notes))
        for note in board.notes[:20]:
            print("    - %s" % note)
    if not args.dry_run:
        count = write_snippet(board, zones, SNIPPET)
        print("  wrote %s (%d lines)" % (SNIPPET.relative_to(ROOT), count))
    print("  %.1f s" % (time.time() - start))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
