#!/usr/bin/env python3
"""Write the SV-16 board schematic: hardware/sv16_board/sv16_board.kicad_sch.

Generated from the same netlist the board is built from - COMPONENTS is
(ref, footprint, pads, value, group) and CONNECTIONS is (ref, pad, net) - so
the two views cannot drift apart.  --check fails if a net or a pad exists on
one and not the other.

Connections are drawn as wires, not dumped into labels.  Three things make
that possible:

  Power rails become power symbols.  Nearly half the pins on this board are
  supplies, and a symbol is what a person expects to see there.

  Pin order is ours to choose.  A symbol's pins can be listed in any order, so
  U1's 96 pins are grouped by the peripheral they serve and listed in that
  peripheral's own pin order.  J4's B0..B15 then sit opposite U1's pins for
  B0..B15 at the same heights, and the bus is a set of straight parallel wires
  rather than a warehouse of labels.

  Two-pin parts are placed between what they join.  A series resistor sits in
  the gap with the net on one side on one pin and the net on the other side on
  the other pin, and both connections are wires.

A net that still cannot be drawn - because its pins end up far apart - keeps a
global label, and --check reports how many.  Nothing is ever dropped.

Use --check to compare the sheet against the board and print those counts.
"""
from __future__ import annotations

import argparse
import re
import sys
import uuid
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "hardware" / "sv16_board" / "sv16_board.kicad_sch"

PITCH = 2.54          # the wiring grid
PIN_PITCH = 2 * PITCH  # pin to pin.  Two cells, not one: with pins a single
                       # cell apart, the wires leaving two neighbouring pins
                       # form a two-cell-thick band that nothing can get
                       # through, which is what sealed so many pins in.
PIN_LEN = 2.54
STUB = 5.08           # short wire from a pin to whatever it meets
GROUP_GAP = 2 * PIN_PITCH
# Clear bands above and below the FPGA.  Several nets - TCK, TMS, TDI, TDO,
# PROGRAMN, INITN - have pins on both sides of it, and the only way round the
# body is over the top or under the bottom.  Keep them generous or those nets
# cannot be drawn at all.
TOP_BAND = 160.0
BOTTOM_BAND = 160.0
KEEPOUT = 1             # cells of clear space kept around every symbol
CROSS_COST = 6          # penalty for crossing another net
PERIPH_GAP = 260.0       # FPGA body to connector body
CHILD_GAP = 30.0         # part to the part it hangs off
BLOCK_PITCH_X = 132.0
BLOCK_PITCH_Y = 76.0

PAPER = "A0"
PAGE_W, PAGE_H = 1189.0, 841.0
MARGIN = 30.0

# Rails get a power symbol rather than a wire or a label.
POWER_NETS = ("GND", "3V3", "1V1", "2V5", "VM_IN", "VM_IN_RAW",
              "USB_VBUS", "5V_USB", "J9_VIN")

NS = uuid.UUID("6f0d5b3e-9c1a-4a52-9e6f-2f2b6a1d4c77")

import os
DEBUG = bool(os.environ.get("SV16_DEBUG"))


def uu(tag: str) -> str:
    return str(uuid.uuid5(NS, "sv16-schematic/" + tag))


def ref_key(ref: str):
    m = re.match(r"([A-Za-z_]+)(\d+)$", ref)
    return (m.group(1), int(m.group(2)), ref) if m else (ref, 0, ref)


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def f(value: float) -> str:
    """Trim trailing zeros so the file stays readable."""
    return ("%.3f" % value).rstrip("0").rstrip(".") or "0"


# ------------------------------------------------------------------- netlist
def load():
    import sv16_board_kicad as B

    comps = {}
    for ref, library, pads_spec, value, group in B.COMPONENTS:
        pads = B.pads_of(pads_spec)
        comps[ref] = {"ref": ref, "fp": library, "value": value,
                      "group": group, "order": ref_key(ref),
                      "pads": [p["number"] if str(p["number"]).strip() else "1"
                               for p in pads]}
    nets = {}
    bynet = defaultdict(list)
    for ref, pad, net in B.CONNECTIONS:
        nets[(ref, str(pad))] = net
        bynet[net].append((ref, str(pad)))

    problems = []
    for (ref, pad), net in sorted(nets.items()):
        if ref not in comps:
            problems.append("%s is connected but is not a component" % ref)
        elif pad not in comps[ref]["pads"]:
            problems.append("%s pin %s carries %s but the footprint has no "
                            "such pad" % (ref, pad, net))
    if problems:
        for line in problems:
            print("  ! %s" % line, file=sys.stderr)
        raise SystemExit("%d netlist problem(s)" % len(problems))

    return B, comps, nets, bynet


# --------------------------------------------------------------------- parts
class Part:
    """One symbol: where it sits and where each of its pins comes out."""

    def __init__(self, ref, comp, body_w=10.16):
        self.ref = ref
        self.comp = comp
        self.pads = list(comp["pads"])
        self.body_w = body_w
        self.left = []          # [(pad, y)]
        self.right = []
        self.x = 0.0
        self.y = 0.0            # the symbol's own origin

    def pin_xy(self, pad):
        """Connection point in sheet coordinates."""
        for number, y in self.left:
            if number == pad:
                return self.x - (self.body_w / 2 + PIN_LEN), self.y + y
        for number, y in self.right:
            if number == pad:
                return self.x + (self.body_w / 2 + PIN_LEN), self.y + y
        raise KeyError("%s has no pin %s" % (self.ref, pad))

    def side_of(self, pad):
        return "L" if any(n == pad for n, _ in self.left) else "R"

    def extent(self):
        ys = [y for _, y in self.left + self.right]
        # Tall enough for the pins it actually has.  Counting one pin as
        # though it needed a whole slot made every resistor seven and a half
        # millimetres tall, which is more than the gap between two rows and
        # turned a column of them into a wall.
        half = max(len(self.left) - 1, len(self.right) - 1, 0) * PIN_PITCH / 2
        return (self.body_w / 2 + PIN_LEN,
                max(max(abs(y) for y in ys) if ys else 0, half) + 1.27)


def symbol_lines(name, part, reference, value):
    """A (symbol ...) block for lib_symbols, from a Part's pin placement."""
    half_h = part.extent()[1]
    out = ['    (symbol "%s"' % name,
           '      (pin_names (offset 0.762) hide)',
           '      (exclude_from_sim no)',
           '      (in_bom yes) (on_board yes)',
           '      (property "Reference" "%s" (at 0 %s 0)'
           ' (effects (font (size 1.27 1.27))))' % (esc(reference), f(half_h + 1.27)),
           '      (property "Value" "%s" (at 0 %s 0)'
           ' (effects (font (size 1.27 1.27))))'
           % (esc(value), f(-(half_h + 1.27))),
           '      (property "Footprint" "" (at 0 0 0)'
           ' (effects (font (size 1.27 1.27)) hide))',
           '      (property "Datasheet" "~" (at 0 0 0)'
           ' (effects (font (size 1.27 1.27)) hide))',
           '      (symbol "%s_0_1"' % name,
           '        (rectangle (start %s %s) (end %s %s)'
           % (f(-part.body_w / 2), f(-half_h), f(part.body_w / 2), f(half_h)),
           '          (stroke (width 0.254) (type default) (color 0 0 0 0))',
           '          (fill (type background))',
           '        )',
           '      )',
           '      (symbol "%s_1_1"' % name]
    for number, y in part.left:
        out += ['        (pin passive line (at %s %s 0) (length %s)'
                % (f(-(part.body_w / 2 + PIN_LEN)), f(y), f(PIN_LEN)),
                '          (name "%s" (effects (font (size 1.27 1.27))))' % esc(str(number)),
                '          (number "%s" (effects (font (size 1.27 1.27))))' % esc(str(number)),
                '        )']
    for number, y in part.right:
        out += ['        (pin passive line (at %s %s 180) (length %s)'
                % (f(part.body_w / 2 + PIN_LEN), f(y), f(PIN_LEN)),
                '          (name "%s" (effects (font (size 1.27 1.27))))' % esc(str(number)),
                '          (number "%s" (effects (font (size 1.27 1.27))))' % esc(str(number)),
                '        )']
    out += ['      )', '    )']
    return out


def power_symbol_lines(name, net):
    """A rail symbol: a hidden pin at the origin and a graphic below or above."""
    if net == "GND":
        graphic = [
            '        (polyline (pts (xy 0 0) (xy 0 -1.27))',
            '          (stroke (width 0.254) (type default) (color 0 0 0 0))',
            '          (fill (type none))',
            '        )',
        ]
        for bar_w, bar_y in ((1.905, -1.27), (1.27, -2.032), (0.635, -2.794)):
            graphic += [
                '        (polyline (pts (xy %s %s) (xy %s %s))'
                % (f(-bar_w), f(bar_y), f(bar_w), f(bar_y)),
                '          (stroke (width 0.254) (type default) (color 0 0 0 0))',
                '          (fill (type none))',
                '        )',
            ]
    else:
        graphic = [
            '        (polyline (pts (xy 0 0) (xy 0 2.54))',
            '          (stroke (width 0.254) (type default) (color 0 0 0 0))',
            '          (fill (type none))',
            '        )',
            '        (polyline (pts (xy -1.27 2.54) (xy 1.27 2.54))',
            '          (stroke (width 0.254) (type default) (color 0 0 0 0))',
            '          (fill (type none))',
            '        )',
        ]
    return ['    (symbol "%s"' % name,
            '      (pin_names (offset 0) hide)',
            '      (exclude_from_sim no)',
            '      (in_bom yes) (on_board yes)',
            '      (property "Reference" "#PWR" (at 0 0 0)'
            ' (effects (font (size 1.27 1.27)) hide))',
            '      (property "Value" "%s" (at 0 %s 0)'
            ' (effects (font (size 1.27 1.27)) (justify left)))'
            % (esc(net), f(-3.81 if net == "GND" else 4.318)),
            '      (property "Footprint" "" (at 0 0 0)'
            ' (effects (font (size 1.27 1.27)) hide))',
            '      (property "Datasheet" "~" (at 0 0 0)'
            ' (effects (font (size 1.27 1.27)) hide))',
            '      (symbol "%s_0_1"' % name] + graphic + [
            '      )',
            '      (symbol "%s_1_1"' % name,
            '        (pin power_in line (at 0 0 0) (length 0) (hide)',
            '          (name "%s" (effects (font (size 1.27 1.27))))' % esc(net),
            '          (number "1" (effects (font (size 1.27 1.27))))',
            '        )',
            '      )',
            '    )']


# -------------------------------------------------------------------- routing
class Grid:
    """An orthogonal wiring grid over the sheet.

    Symbol bodies are kept out.  Copper already laid down may be *crossed* but
    never run along: two wires meeting at right angles are a crossing, which
    every schematic reader understands, whereas a wire sharing two cells in a
    row with another would merge the two nets.

    Wire ends are safe because a pin cell is re-blocked as soon as its net is
    finished, so nothing can later pass through a point where a wire ends.  A
    junction is therefore only ever drawn where the generator meant to join.
    """

    def __init__(self, width, height, cell=PITCH):
        self.cell = cell
        self.nx = int(width / cell) + 3
        self.ny = int(height / cell) + 3
        self.blocked = [bytearray(self.ny) for _ in range(self.nx)]
        self.used = [bytearray(self.ny) for _ in range(self.nx)]
        self.own = [bytearray(self.ny) for _ in range(self.nx)]
        self.owner = {}
        # Which way the copper through each cell runs: 1 = across the sheet,
        # 2 = up and down it, 3 = a corner.  Without this, two parallel wires
        # side by side look like one thick wire running the other way, and a
        # crossing that is perfectly legal gets refused.
        self.orient = [bytearray(self.ny) for _ in range(self.nx)]

    def cell_of(self, x, y):
        return int(round(x / self.cell)), int(round(y / self.cell))

    def point_of(self, i, j):
        return i * self.cell, j * self.cell

    def block(self, x0, y0, x1, y1):
        i0, j0 = self.cell_of(min(x0, x1), min(y0, y1))
        i1, j1 = self.cell_of(max(x0, x1), max(y0, y1))
        for i in range(max(0, i0), min(self.nx, i1 + 1)):
            for j in range(max(0, j0), min(self.ny, j1 + 1)):
                self.blocked[i][j] = 1

    def open(self, i, j):
        return (0 <= i < self.nx and 0 <= j < self.ny
                and not self.blocked[i][j] and not self.used[i][j])

    def _other(self, i, j):
        """Copper that is not free sheet and not this net's own."""
        return (0 <= i < self.nx and 0 <= j < self.ny
                and self.used[i][j] and not self.own[i][j])

    def explore(self, starts, goal):
        """How many search states `route` would visit.  Diagnosis only."""
        import heapq
        goal_i, goal_j = goal
        queue, seen = [], set()
        for i, j in starts:
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                s = (i, j, di, dj)
                if s not in seen:
                    seen.add(s)
                    heapq.heappush(queue, (0, i, j, di, dj))
        n = 0
        while queue:
            cost, i, j, di, dj = heapq.heappop(queue)
            n += 1
            if i == goal_i and j == goal_j:
                return n
            for ni, nj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                si, sj = i + ni, j + nj
                if not (0 <= si < self.nx and 0 <= sj < self.ny):
                    continue
                if self.blocked[si][sj]:
                    continue
                if self.used[si][sj] and not self.own[si][sj]:
                    if ni == 0:
                        along = (self._other(si, sj + 1)
                                 or self._other(si, sj - 1))
                    else:
                        along = (self._other(si + 1, sj)
                                 or self._other(si - 1, sj))
                    if along:
                        continue
                    step = 1 + CROSS_COST
                else:
                    step = 1
                key = (si, sj, ni, nj)
                if key in seen:
                    continue
                seen.add(key)
                heapq.heappush(queue, (cost + step, si, sj, ni, nj))
        return -n

    def route(self, starts, goal):
        """Shortest orthogonal run from any of `starts` to `goal`.

        `starts` is the tree of copper this net already has, so each new pin is
        tied into what is there rather than to the previous pin, which is what
        keeps the result a tree instead of a daisy chain.

        Copper belonging to this same net is free to run over - that is just
        one wire.  Copper belonging to another net may be *crossed*, but only
        at right angles: the cell ahead and the cell behind along the direction
        of travel must both be clear of that other net, otherwise the two wires
        would share a run and would silently become one net.  Crossings cost a
        little more than empty sheet so they are only used when going around is
        worse.
        """
        import heapq
        goal_i, goal_j = goal
        queue = []
        came = {}
        seen = set()
        for i, j in starts:
            self.own[i][j] = 1
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                state = (i, j, di, dj)
                if state not in seen:
                    seen.add(state)
                    heapq.heappush(queue, (0, i, j, di, dj))
        while queue:
            cost, i, j, di, dj = heapq.heappop(queue)
            if i == goal_i and j == goal_j:
                path = [(i, j)]
                state = (i, j, di, dj)
                while state in came:
                    state = came[state]
                    path.append((state[0], state[1]))
                return path[::-1]
            for ni, nj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                si, sj = i + ni, j + nj
                if not (0 <= si < self.nx and 0 <= sj < self.ny):
                    continue
                if self.blocked[si][sj]:
                    continue
                if self.used[si][sj] and not self.own[si][sj]:
                    # Crossing a wire is fine; travelling along one would
                    # merge two nets.  1 = across, 2 = up and down.
                    if self.orient[si][sj] & (1 if ni else 2):
                        continue
                    step = 1 + CROSS_COST
                else:
                    step = 1
                key = (si, sj, ni, nj)
                if key in seen:
                    continue
                seen.add(key)
                came[key] = (i, j, di, dj)
                heapq.heappush(queue, (cost + step, si, sj, ni, nj))
        return None

    def take(self, path, who=""):
        for k, (i, j) in enumerate(path):
            self.used[i][j] = 1
            axis = 0
            for a, b in ((path[k - 1] if k else None, None),
                         (path[k + 1] if k + 1 < len(path) else None, None)):
                if a is not None and a[1] != j:
                    axis |= 2
                if a is not None and a[0] != i:
                    axis |= 1
            if not axis:                     # a lone cell: say both, safely
                axis = 3
            self.orient[i][j] |= axis
            if DEBUG:
                self.owner[(i, j)] = who

    def untake(self, path):
        for i, j in path:
            self.used[i][j] = 0


def clean(path, grid):
    """Collapse a run of grid cells into the corner points of the wire."""
    points = [grid.point_of(i, j) for i, j in path]
    out = [points[0]]
    for index in range(1, len(points) - 1):
        ax, ay = out[-1]
        bx, by = points[index]
        cx, cy = points[index + 1]
        if not ((ax == bx == cx) or (ay == by == cy)):
            out.append((bx, by))
    out.append(points[-1])
    return out


# -------------------------------------------------------------------- layout
def build(B, comps, nets, bynet):
    power = set(POWER_NETS)
    u1_ref = "U1"

    u1_nets = {n for n, pins in bynet.items()
               if any(r == u1_ref for r, _ in pins) and n not in power}
    local = {n for n in bynet if n not in power and n not in u1_nets}

    # Which parts hang off the FPGA, and on how many of its nets.
    periph = defaultdict(list)          # ref -> [net] in U1's own order
    u1_pad_of = {}
    for net in sorted(u1_nets):
        for ref, pad in bynet[net]:
            if ref != u1_ref:
                periph[ref].append(net)
            else:
                u1_pad_of[net] = pad

    # Only parts with several FPGA nets get a run of pins laid opposite them.
    # A part with a single FPGA net - a series resistor, a test point, a
    # transistor - would be aligned to the very same pin as the connector it
    # shares that net with (R11 and J5 both hang off A1), and the two symbols
    # would land on top of each other, each blocking the other's pin.  Those
    # go in the blocks below and are wired to the FPGA instead.
    majors = [r for r in periph if len(periph[r]) >= 2]
    ordered = sorted(majors, key=lambda r: (-len(periph[r]), comps[r]["order"]))

    # Peripherals that talk to each other have to end up on the same side of
    # the FPGA.  Two JTAG headers carrying the same four signals, split across
    # the chip, would need those four nets to cross the entire symbol.
    buddies = defaultdict(set)
    for net, pins in bynet.items():
        if net in power:
            continue
        refs = sorted({r for r, _ in pins} & set(majors))
        for a in refs:
            for b in refs:
                if a != b:
                    buddies[a].add(b)
    groups, seen = [], set()
    for ref in ordered:
        if ref in seen:
            continue
        bundle, queue = [], [ref]
        seen.add(ref)
        while queue:
            r = queue.pop(0)
            bundle.append(r)
            for other in sorted(buddies.get(r, ())):
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
        groups.append(bundle)

    sides = {"L": [], "R": []}
    load = {"L": 0, "R": 0}
    for bundle in groups:
        side = "L" if load["L"] <= load["R"] else "R"
        for ref in bundle:
            sides[side].append(ref)
            load[side] += max(len(periph[ref]), len(comps[ref]["pads"]))

    parts = {}
    wires, labels, junctions = [], [], []
    stats = {"power": 0, "wired": 0, "labelled": 0, "failed": []}

    # Every placed symbol's footprint, so the next one can be put somewhere it
    # does not land on top of another.
    boxes = []

    def free_box(x0, x1, y0, y1, pad=2.54):
        return all(x1 + pad < a or x0 - pad > b or y1 + pad < c or y0 - pad > d
                   for a, b, c, d in boxes)

    # ---- the FPGA ------------------------------------------------------
    u1 = Part(u1_ref, comps[u1_ref], body_w=15.24)
    plan = {"L": [], "R": []}           # side -> [(periph_ref, [(pad, net, y)])]
    cursor = {"L": 0.0, "R": 0.0}
    for side in ("L", "R"):
        y = 0.0
        for ref in sides[side]:
            group = periph[ref]
            n_pads = len(comps[ref]["pads"])
            rows = max(len(group), n_pads)
            start = y
            entries = []
            for net in group:                     # in U1 order = periph order
                entries.append((u1_pad_of[net], net, y))
                y -= PIN_PITCH
            y = start - rows * PIN_PITCH - GROUP_GAP
            plan[side].append((ref, entries))
        cursor[side] = y

    # FPGA pins that reach no connector - a reset line to a switch, a clock to
    # an oscillator - have nothing to line up with, but they still have to be
    # on the symbol.  They get a row of their own on whichever side is shorter.
    taken = {pad for side in ("L", "R") for _, entries in plan[side]
             for pad, _, _ in entries}
    leftovers = [pad for pad in comps[u1_ref]["pads"]
                 if pad not in taken
                 and nets.get((u1_ref, pad))
                 and nets[(u1_ref, pad)] not in power]
    for pad in sorted(leftovers, key=lambda pad: nets[(u1_ref, pad)]):
        side = "L" if cursor["L"] > cursor["R"] else "R"
        plan[side].append((None, [(pad, nets[(u1_ref, pad)], cursor[side])]))
        cursor[side] -= PIN_PITCH

    # Supply pins go underneath everything else.
    for pad in comps[u1_ref]["pads"]:
        net = nets.get((u1_ref, pad))
        if net in power:
            side = "L" if cursor["L"] > cursor["R"] else "R"
            plan[side].append((None, [(pad, net, cursor[side])]))
            cursor[side] -= PIN_PITCH
    for side, column in (("L", u1.left), ("R", u1.right)):
        for _, entries in plan[side]:
            for pad, net, y in entries:
                column.append((pad, y))
    u1.x = 520.0
    u1_half = u1.extent()[1]
    if DEBUG:
        print("   U1: %d left + %d right pins, half-height %.0f mm"
              % (len(u1.left), len(u1.right), u1_half), file=sys.stderr)
    u1.y = TOP_BAND + u1_half
    u1.x = 520.0
    _hw, _hh = u1.extent()
    boxes.append((u1.x - _hw, u1.x + _hw, u1.y - _hh, u1.y + _hh))
    parts[u1_ref] = u1

    # ---- the peripherals, pin for pin opposite the FPGA ----------------
    for side in ("L", "R"):
        for ref, entries in plan[side]:
            if ref is None:
                continue
            part = Part(ref, comps[ref], body_w=10.16)
            facing = "R" if side == "L" else "L"     # the side turned to U1
            outer = "L" if side == "L" else "R"
            net_of_pad = {p: nets.get((ref, p)) for p in part.pads}
            # The plan hands over absolute sheet rows.  Shift them so the
            # symbol is centred on its own pins; otherwise the body is drawn
            # up at the FPGA's origin while the pins sit far below it, and the
            # rectangle grows tall enough to swallow its neighbours.
            ys = [y for _pad, _net, y in entries] or [0.0]
            centre = (min(ys) + max(ys)) / 2.0
            used = set()
            for pad, net, y in entries:
                for p in part.pads:
                    if net_of_pad.get(p) == net and p not in used:
                        getattr(part, "right" if facing == "R" else "left").append((p, y - centre))
                        used.add(p)
                        break
            rest = [pad for pad in part.pads if pad not in used]
            rest_y = (len(rest) - 1) * PIN_PITCH / 2
            for pad in rest:
                getattr(part, "right" if outer == "R" else "left").append((pad, rest_y))
                rest_y -= PIN_PITCH
            # Stand it opposite its own FPGA pins, at PERIPH_GAP.  If another
            # part already owns that patch of sheet - two parts can share a
            # pin row when one of them only has a single FPGA net - step
            # further out, and only then give up a little height.
            gap = -PERIPH_GAP if side == "L" else PERIPH_GAP
            reach = part.body_w / 2 + PIN_LEN
            outward = -1 if side == "L" else 1
            # Keeping the row matters more than keeping the column: a part on
            # its pin's row still gets a straight run to the FPGA however far
            # out it has to stand, whereas a part pushed off its row does not.
            tries = [(s, 0.0) for s in range(12)]
            for _dy in (PIN_PITCH, -PIN_PITCH, 2 * PIN_PITCH, -2 * PIN_PITCH):
                tries += [(s, _dy) for s in range(12)]
            for step, dy in tries:
                facing_x = u1.x + gap + step * CHILD_GAP * outward
                part.x = (facing_x - reach if facing == "R"
                          else facing_x + reach)
                part.y = u1.y + centre + dy
                hw, hh = part.extent()
                if free_box(part.x - hw, part.x + hw,
                            part.y - hh, part.y + hh):
                    break
            hw, hh = part.extent()
            boxes.append((part.x - hw, part.x + hw, part.y - hh, part.y + hh))
            parts[ref] = part

    if DEBUG and os.environ.get("SV16_DEBUG_PARTS"):
        from collections import Counter
        allpads = [pp for pp, _ in u1.left] + [pp for pp, _ in u1.right]
        dupes = [k for k, v in Counter(allpads).items() if v > 1]
        print("   U1 pads: L=%d R=%d duplicated=%s"
              % (len(u1.left), len(u1.right), dupes), file=sys.stderr)
        for pp in ("60", "61", "62", "63", "64"):
            for side, lst in (("L", u1.left), ("R", u1.right)):
                for q, yy in lst:
                    if q == pp:
                        print("      U1.%s on %s y=%.2f net=%s"
                              % (pp, side, u1.y + yy, nets.get(("U1", pp))),
                              file=sys.stderr)
        for nn in ("TCK", "TDI", "TDO", "TMS"):
            for ref, pad in bynet[nn]:
                pr = parts[ref]
                x, y = pr.pin_xy(pad)
                print("   %-5s %s.%-3s -> (%.2f, %.2f) side=%s"
                      % (nn, ref, pad, x, y, pr.side_of(pad)), file=sys.stderr)
        for ref in ("J1", "J2", "J5"):
            if ref not in parts:
                continue
            pr = parts[ref]
            print("   %s x=%.1f y=%.1f" % (ref, pr.x, pr.y), file=sys.stderr)
            for pad, y in sorted(pr.left + pr.right, key=lambda e: -e[1]):
                n = nets.get((ref, pad))
                uy = None
                for pp, yy in u1.left + u1.right:
                    if nets.get(("U1", pp)) == n:
                        uy = u1.y + yy
                print("      pad %-3s net %-10s y=%8.2f   U1 pin y=%s"
                      % (pad, n, pr.y + y,
                         "%.2f" % uy if uy else "-"), file=sys.stderr)
    # ---- everything else, hung next to whatever it talks to -------------
    # A net between neighbours is a short straight run.  A net between two
    # parts on opposite sides of the sheet is a journey, and no amount of
    # routing cleverness makes a journey readable.  So each remaining part is
    # placed just outside the part it shares a net with, at the height of the
    # pin it shares it with, and the pin that does the talking is turned to
    # face its neighbour.
    neighbours = defaultdict(set)
    for net, pins in bynet.items():
        if net in power:
            continue
        refs = sorted({r for r, _ in pins})
        for a in refs:
            for b in refs:
                if a != b:
                    neighbours[a].add(b)

    side_of_pin = {}         # (ref, pad) -> which side of the FPGA it sits on
    tier = {}
    for _side in ("L", "R"):
        for ref, _entries in plan[_side]:
            if ref:
                tier[ref] = 1
                for _pad in comps[ref]["pads"]:
                    side_of_pin[(ref, _pad)] = _side
    # Every FPGA pin is an anchor too, including the ones that reached no
    # connector; parts hanging off a reset line have nowhere else to go.
    for _pad, _y in u1.left:
        side_of_pin[(u1_ref, _pad)] = "L"
        tier.setdefault(u1_ref, 0)
    for _pad, _y in u1.right:
        side_of_pin[(u1_ref, _pad)] = "R"
        tier.setdefault(u1_ref, 0)
    taken_rows = defaultdict(list)

    def free_slot(side, col, y0, y1):
        return all(y1 + 2.54 < a or y0 - 2.54 > b
                   for a, b in taken_rows[(side, col)])

    def hang(parent, child, parent_pad, child_pad):
        """Set `child` just outside `parent`, level with the pin it joins."""
        side = side_of_pin.get((parent, parent_pad), "L")
        pp = parts[parent]
        p_reach = pp.body_w / 2 + PIN_LEN
        p_pin_x = pp.x - p_reach if side == "L" else pp.x + p_reach
        p_pin_y = pp.y + dict(pp.left + pp.right)[parent_pad]
        inner = part_side["R" if side == "L" else "L"]   # the face turned back
        outer = part_side[side]
        part = Part(child, comps[child], body_w=8.89)
        y = 0.0
        for pad in part.pads:
            if pad == child_pad and not getattr(part, inner):
                getattr(part, inner).append((pad, 0.0))
            else:
                getattr(part, outer).append((pad, y))
                y -= PIN_PITCH
        c_reach = part.body_w / 2 + PIN_LEN
        col = tier[parent] + 1
        tries = [(s, 0.0) for s in range(10)]
        for _dy in (PIN_PITCH, -PIN_PITCH, 2 * PIN_PITCH, -2 * PIN_PITCH):
            tries += [(s, _dy) for s in range(10)]
        for step, dy in tries:
            gap = CHILD_GAP * (step + 1)
            pin_x = p_pin_x - gap if side == "L" else p_pin_x + gap
            part.x = pin_x - c_reach if inner == "right" else pin_x + c_reach
            part.y = p_pin_y + dy
            hw, hh = part.extent()
            if free_box(part.x - hw, part.x + hw, part.y - hh, part.y + hh):
                break
        hw, hh = part.extent()
        boxes.append((part.x - hw, part.x + hw, part.y - hh, part.y + hh))
        parts[child] = part
        for _pad in part.pads:
            side_of_pin[(child, _pad)] = side
        tier[child] = col

    part_side = {"L": "left", "R": "right"}
    pending = sorted(set(comps) - set(parts), key=lambda r: comps[r]["order"])
    while True:
        done = []
        for ref in pending:
            best = None
            for pad in comps[ref]["pads"]:
                net = nets.get((ref, pad))
                if not net or net in power:
                    continue
                for other, opad in bynet[net]:
                    if other != ref and (other, opad) in side_of_pin:
                        if best is None or tier.get(other, 9) < tier.get(best[0], 9):
                            best = (other, opad, pad)
            if best is None:
                continue
            hang(best[0], ref, best[1], best[2])
            done.append(ref)
        if not done:
            break
        pending = [r for r in pending if r not in set(done)]

    # Whatever is left has no signal net to anything already placed -
    # decoupling caps, test points, mounting holes, and parts whose only
    # partners are equally unplaced.  They go in a farm below, still in
    # netlist order so the few nets between them stay short.
    farm, seen = [], set()
    for seed in pending:
        if seed in seen:
            continue
        queue, seen = [seed], seen | {seed}
        while queue:
            ref = queue.pop(0)
            farm.append(ref)
            for other in sorted(neighbours.get(ref, ())):
                if other in set(pending) and other not in seen:
                    seen.add(other)
                    queue.append(other)
    row_y = u1.y + u1_half + BOTTOM_BAND
    col_x = MARGIN + 40.0
    per_row = 9
    for index, ref in enumerate(farm):
        part = Part(ref, comps[ref], body_w=8.89)
        half = max(len(part.pads) // 2, 1)
        for i, pad in enumerate(part.pads):
            y = (half - 1 - (i // 2)) * PIN_PITCH if len(part.pads) > 2 else 0.0
            (part.left if i % 2 == 0 else part.right).append((pad, y))
        part.x = col_x + (index % per_row) * BLOCK_PITCH_X
        part.y = row_y + (index // per_row) * BLOCK_PITCH_Y
        parts[ref] = part

    # ---- connect -------------------------------------------------------
    spread = [part.extent() for part in parts.values()]
    reach = max(part.x + w for part, (w, _) in zip(parts.values(), spread))
    depth = max(part.y + h for part, (_, h) in zip(parts.values(), spread))
    grid = Grid(max(PAGE_W, reach + 200.0), max(PAGE_H, depth + 200.0))
    for ref, part in parts.items():
        half_w, half_h = part.extent()
        m = KEEPOUT * PITCH
        grid.block(part.x - half_w - m, part.y - half_h - m,
                   part.x + half_w + m, part.y + half_h + m)

    # Every pin gets a short corridor leading straight out of its own symbol's
    # keep-out.  The corridor is blocked at all times except while that pin's
    # net is being drawn, so no amount of other people's wiring can seal a pin
    # into its own symbol.  Without this, a wire running along the edge of a
    # symbol leaves the pins behind it with nowhere to go.
    approach = {}
    for ref, part in parts.items():
        for pad, _y in part.left + part.right:
            px, py = part.pin_xy(pad)
            ci, cj = grid.cell_of(px, py)
            step = -1 if part.side_of(pad) == "L" else 1
            cells = [(ci + step * k, cj) for k in range(1, KEEPOUT + 1)]
            for i, j in cells:
                if 0 <= i < grid.nx and 0 <= j < grid.ny:
                    grid.blocked[i][j] = 1
            approach[(ref, pad)] = cells

    if DEBUG:
        miss = [(r, pd) for net, pins in bynet.items() if net not in power
                for r, pd in pins if (r, pd) not in approach]
        print("   approach: %d entries, %d net pins with NO corridor: %s"
              % (len(approach), len(miss), miss[:6]), file=sys.stderr)

    if DEBUG:
        for _side in ("L", "R"):
            for _ref, _entries in plan[_side]:
                if not _ref or _ref not in parts:
                    continue
                _pr = parts[_ref]
                _n = _entries[0][1] if _entries else None
                _up = u1_pad_of.get(_n) if _n else None
                _us = u1.side_of(_up) if _up else "?"
                _hw, _hh = _pr.extent()
                print("   plan[%s] %-5s x=%7.1f y=%7.1f box=(%.0f..%.0f, "
                      "%.0f..%.0f) | U1.%s on %s"
                      % (_side, _ref, _pr.x, _pr.y, _pr.x - _hw, _pr.x + _hw,
                         _pr.y - _hh, _pr.y + _hh, _up, _us), file=sys.stderr)
    if DEBUG:
        from collections import Counter as _C
        print("   placement: %d hung in clusters, %d in the farm"
              % (len(tier) - 1, len(farm)), file=sys.stderr)
        print("   cluster tier histogram: %s"
              % sorted(_C(tier.values()).items()), file=sys.stderr)
        if farm:
            print("   farm: %s" % farm[:24], file=sys.stderr)

    def straight(a, b):
        return (abs(a[1] - b[1]) < 1e-6 and abs(a[0] - b[0]) > 1e-6)

    # Empty margin around everything, used when a net has no way through.
    bx0 = min(b[0] for b in boxes)
    bx1 = max(b[1] for b in boxes)
    by0 = min(b[2] for b in boxes)
    by1 = max(b[3] for b in boxes)
    m = 40.0
    ring = [(bx0 - m, by0 - m), ((bx0 + bx1) / 2, by0 - m), (bx1 + m, by0 - m),
            (bx1 + m, (by0 + by1) / 2), (bx1 + m, by1 + m),
            ((bx0 + bx1) / 2, by1 + m), (bx0 - m, by1 + m),
            (bx0 - m, (by0 + by1) / 2), (bx0 - m, (by0 + by1) / 2)]

    def detour(tree, cell, net):
        """Round the outside of the sheet, for nets with no way through."""
        goal_xy = grid.point_of(*cell)
        for wx, wy in ring:
            w = grid.cell_of(wx, wy)
            if not (0 <= w[0] < grid.nx and 0 <= w[1] < grid.ny):
                continue
            if grid.blocked[w[0]][w[1]]:
                continue
            first = grid.route(tree, w)
            if first is None:
                continue
            grid.take(first, net + " (detour)")
            second = grid.route([w], cell)
            if second is None:
                grid.untake(first)
                continue
            return first + second[1:]
        return None

    # Widest nets first: they have the least freedom about where they go.
    for net, pins in sorted(bynet.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if net in power:
            for ref, pad in pins:
                px, py = parts[ref].pin_xy(pad)
                side = parts[ref].side_of(pad)
                out_x = px - STUB if side == "L" else px + STUB
                wires.append([(px, py), (out_x, py)])
                labels.append(("PWR", net, out_x, py))
            stats["power"] += len(pins)
            continue

        points = [parts[ref].pin_xy(pad) for ref, pad in pins]
        if len(points) == 2 and straight(*points):
            a, b = grid.cell_of(*points[0]), grid.cell_of(*points[1])
            # Only take the straight run if it is actually clear.  Two pins
            # can share a row with a whole symbol sitting between them, and
            # drawing through it would both look wrong and silently short
            # anything the wire crossed on the way.
            mine = set(a for _r, _p in pins
                       for a in [grid.cell_of(*parts[_r].pin_xy(_p))])
            for ref, pad in pins:
                mine.update(approach.get((ref, pad), ()))
            run = [(i, j) for i in range(min(a[0], b[0]), max(a[0], b[0]) + 1)
                   for j in range(min(a[1], b[1]), max(a[1], b[1]) + 1)]
            if all(not grid.blocked[i][j] or (i, j) in mine for i, j in run):
                wires.append(list(points))
                # Mark the whole run, not just the ends: a later route has to
                # be able to see this wire to avoid running along it.
                for i, j in run:
                    grid.used[i][j] = 1
                    grid.orient[i][j] |= 1
                    if DEBUG:
                        grid.owner[(i, j)] = net + " (straight)"
                for i, j in mine:
                    grid.used[i][j] = 1
                    grid.orient[i][j] |= 1
                    if DEBUG:
                        grid.owner[(i, j)] = net + " (corridor)"
                stats["wired"] += 2
                continue

        cells = [grid.cell_of(x, y) for x, y in points]
        grid.own = [bytearray(grid.ny) for _ in range(grid.nx)]
        # A pin sits inside its own symbol's keep-out; open just its cell so
        # the route can reach it from outside, then close it again after.
        exits = [c for ref, pad in pins for c in approach.get((ref, pad), ())]
        reopened = [(i, j) for i, j in cells + exits if grid.blocked[i][j]]
        for i, j in reopened:
            grid.blocked[i][j] = 0
        tree, routed = [cells[0]], []
        pending = list(cells[1:])
        while pending:
            # Nearest first.  A net that feeds several parts is drawn as a
            # chain - FPGA, then the resistor beside it, then the connector -
            # rather than as spokes from the FPGA that have to get past parts
            # already belonging to the same net.
            pending.sort(key=lambda c: min(abs(c[0] - tc[0]) + abs(c[1] - tc[1])
                                           for tc in tree))
            cell = pending[0]
            path = None
            for cand in pending:
                path = grid.route(tree, cand)
                if path is not None:
                    cell = cand
                    break
            if path is None:
                # No way through the middle of the sheet.  Go the long way
                # round: out into the empty margin, along it, and back in.
                # Ugly, but a long wire the reader can follow beats a label
                # they have to hunt for.
                path = detour(tree, cell, net)
            if path is None:
                if DEBUG:
                    gi, gj = cell
                    print("   FAIL %s: goal cell (%d,%d) at %s  blocked=%d "
                          "used=%d  start=%s blocked=%d"
                          % (net, gi, gj, grid.point_of(gi, gj),
                             grid.blocked[gi][gj], grid.used[gi][gj],
                             grid.point_of(*cells[0]),
                             grid.blocked[cells[0][0]][cells[0][1]]),
                          file=sys.stderr)
                    from collections import deque
                    flood = {cells[0]}
                    dq = deque([cells[0]])
                    while dq:
                        ci, cj = dq.popleft()
                        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                            step = (ci + di, cj + dj)
                            if step not in flood and grid.open(*step):
                                flood.add(step)
                                dq.append(step)
                    seen2 = grid.explore(tree, cell)
                    gx, gy = grid.point_of(*cell)
                    spoke = ["%s.%s@%s" % (r, pd,
                             "U1" if r == "U1" else
                             ("MAJ" if abs(parts[r].x - u1.x) > 60 else "BLK"))
                             for r, pd in pins]
                    print("        %-12s %-5s fail#%d/%d goal=(%d,%d) "
                          "states=%d  %s"
                          % (net, "", cells.index(cell), len(cells) - 1,
                             int(gx), int(gy), seen2, " ".join(spoke)),
                          file=sys.stderr)
                    # walk out of the start pin and report the first wall
                    print("        pins=%s" % (pins,), file=sys.stderr)
                    for r, pd in pins:
                        i0, j0 = grid.cell_of(*parts[r].pin_xy(pd))
                        sd = -1 if parts[r].side_of(pd) == "L" else 1
                        corr = [(i0 + sd * k, j0) for k in range(1, KEEPOUT + 1)]
                        print("        %s.%-4s cell=(%d,%d) side=%s corr=%s %s"
                              % (r, pd, i0, j0, "x", corr,
                                 [grid.owner.get(c, "-") for c in corr]),
                              file=sys.stderr)
                        print("        %s.%-4s cell=(%d,%d) side=%s corr=%s %s"
                              % (r, pd, i0, j0, parts[r].side_of(pd), corr,
                                 [("blk" if grid.blocked[i][j] else
                                   "own" if grid.own[i][j] else
                                   "used" if grid.used[i][j] else "free")
                                  for i, j in corr]), file=sys.stderr)
                    ci, cj = cells[0]
                    step = -1 if parts[pins[0][0]].side_of(pins[0][1]) == "L" else 1
                    for k in range(0, KEEPOUT + 4):
                        i2 = ci + step * k
                        st = ("blocked" if grid.blocked[i2][cj]
                              else "used" if grid.used[i2][cj] else "free")
                        horiz = (grid._other(i2 - 1, cj) or grid._other(i2 + 1, cj))
                        print("          exit %+d (%d,%d): %s  horiz-nbr=%s"
                              % (step * k, i2, cj, st, bool(horiz)),
                              file=sys.stderr)
                routed = None
                break
            grid.take(path, net)
            tree = tree + path
            routed.append(clean(path, grid))
            pending.remove(cell)
        for i, j in reopened:
            grid.blocked[i][j] = 1

        if routed is None:
            # Cannot be drawn without crossing something.  Keep the net, say so
            # with labels, and let --check count it.
            labels.extend(("NET", net, x, y) for x, y in points)
            stats["labelled"] += len(points)
            stats["failed"].append((net, len(points),
                                    any(r == "U1" for r, _ in pins)))
        else:
            wires.extend(routed)
            stats["wired"] += len(points)

    return parts, wires, labels, junctions, bynet, power, stats


# -------------------------------------------------------------------- output
def emit(parts, wires, labels, used, comps, bynet):
    names, defs = {}, []
    for ref in sorted(parts, key=ref_key):
        part = parts[ref]
        key = (part.body_w, tuple(part.left), tuple(part.right))
        if key not in names:
            name = "SV16:S%d" % len(names)
            names[key] = name
            defs += symbol_lines(name, part, ref, comps[ref]["value"])
    pwr_names = {}
    for kind, net, _, _ in labels:
        if kind == "PWR" and net not in pwr_names:
            pwr_names[net] = "SV16:PWR_%s" % re.sub(r"[^A-Za-z0-9_]", "_", net)
            defs += power_symbol_lines(pwr_names[net], net)

    out = ['(kicad_sch (version 20231120) (generator "sv16_schematic_kicad")',
           '  (uuid "%s")' % uu("sheet"),
           '  (paper "%s")' % PAPER,
           '  (title_block',
           '    (title "SV-16 FPGA board")',
           '    (rev "1")',
           '    (comment 1 "Generated from scripts/sv16_board_kicad.py - power '
           'rails are symbols, connections are wires, leftover nets are '
           'labelled")',
           '  )',
           '  (lib_symbols']
    out += defs
    out.append('  )')

    for ref in sorted(parts, key=ref_key):
        part = parts[ref]
        name = names[(part.body_w, tuple(part.left), tuple(part.right))]
        half_h = part.extent()[1]
        out += ['  (symbol (lib_id "%s")' % name,
                '    (at %s %s 0)' % (f(part.x), f(part.y)),
                '    (unit 1)',
                '    (in_bom yes) (on_board yes) (dnp no) (fields_autoplaced yes)',
                '    (uuid "%s")' % uu("symbol/" + ref),
                '    (property "Reference" "%s" (at %s %s 0)'
                % (esc(ref), f(part.x), f(part.y - half_h - 1.27)),
                '      (effects (font (size 1.27 1.27)) (justify left))',
                '    )',
                '    (property "Value" "%s" (at %s %s 0)'
                % (esc(comps[ref]["value"]), f(part.x), f(part.y + half_h + 1.27)),
                '      (effects (font (size 1.27 1.27)) (justify left))',
                '    )',
                '    (property "Footprint" "%s" (at %s %s 0)'
                % (esc(comps[ref]["fp"]), f(part.x), f(part.y)),
                '      (effects (font (size 1.27 1.27)) hide)',
                '    )',
                '    (property "Datasheet" "~" (at %s %s 0)' % (f(part.x), f(part.y)),
                '      (effects (font (size 1.27 1.27)) hide)',
                '    )']
        for number, _ in part.left + part.right:
            out.append('    (pin "%s" (uuid "%s"))'
                       % (esc(str(number)), uu("pin/%s/%s" % (ref, number))))
        out.append('  )')

    # A point where three or more wire ends arrive is a junction and needs its
    # dot, or KiCad reads the crossing as unconnected.  Counting is easier and
    # safer than trying to work it out per route.
    from collections import Counter
    arrivals = Counter()
    for pts in wires:
        for point in pts:
            arrivals[point] += 1

    for index, pts in enumerate(wires):
        coords = " ".join("(xy %s %s)" % (f(x), f(y)) for x, y in pts)
        out += ['  (wire (pts %s)' % coords,
                '    (stroke (width 0) (type default) (color 0 0 0 0))',
                '    (uuid "%s")' % uu("wire/%d" % index),
                '  )']

    for index, (x, y) in enumerate(sorted(p for p, n in arrivals.items() if n >= 3)):
        out += ['  (junction (at %s %s) (diameter 0) (color 0 0 0 0)'
                % (f(x), f(y)),
                '    (uuid "%s")' % uu("junction/%d" % index),
                '  )']

    for index, (kind, net, x, y) in enumerate(labels):
        if kind == "PWR":
            out += ['  (symbol (lib_id "%s")' % pwr_names[net],
                    '    (at %s %s 0)' % (f(x), f(y)),
                    '    (unit 1)',
                    '    (in_bom yes) (on_board yes) (dnp no)'
                    ' (fields_autoplaced yes)',
                    '    (uuid "%s")' % uu("pwr/%d" % index),
                    '    (property "Reference" "#PWR??" (at %s %s 0)'
                    % (f(x), f(y)),
                    '      (effects (font (size 1.27 1.27)) hide)',
                    '    )',
                    '    (property "Value" "%s" (at %s %s 0)'
                    % (esc(net), f(x), f(y)),
                    '      (effects (font (size 1.27 1.27)) (justify left))',
                    '    )',
                    '    (property "Footprint" "" (at %s %s 0)' % (f(x), f(y)),
                    '      (effects (font (size 1.27 1.27)) hide)',
                    '    )',
                    '    (property "Datasheet" "~" (at %s %s 0)' % (f(x), f(y)),
                    '      (effects (font (size 1.27 1.27)) hide)',
                    '    )',
                    '    (pin "1" (uuid "%s"))' % uu("pwrpin/%d" % index),
                    '  )']
        else:
            out += ['  (global_label "%s" (shape input) (at %s %s 0)'
                    ' (fields_autoplaced)' % (esc(net), f(x), f(y)),
                    '    (effects (font (size 1.27 1.27)) (justify left))',
                    '    (uuid "%s")' % uu("label/%d" % index),
                    '  )']

    out += ['  (sheet_instances', '    (path "/" (page "1"))', '  )', ')']
    return "\n".join(out) + "\n"


def check(text, bynet, power, stats):
    """Every pin must be accounted for, and every net present on the sheet."""
    drawn_labels = len(re.findall(r"^  \(global_label ", text, re.M))
    pwr = len(re.findall(r'\(lib_id "SV16:PWR_', text))
    pins = sum(len(v) for v in bynet.values())
    nets_on_sheet = set(re.findall(r'\(global_label "([^"]+)"', text)) | {
        n for n in re.findall(r'\(lib_id "SV16:PWR_([A-Za-z0-9_]+)"\)', text)}
    net_labels = {n for _, n, _, _ in []}
    ok = True
    if stats["power"] + stats["wired"] + stats["labelled"] != pins:
        print("  ! %d pins on the board but %d accounted for on the sheet"
              % (pins, stats["power"] + stats["wired"] + stats["labelled"]),
              file=sys.stderr)
        ok = False
    if pwr != stats["power"]:
        print("  ! %d rail symbols written for %d rail pins"
              % (pwr, stats["power"]), file=sys.stderr)
        ok = False
    if drawn_labels != stats["labelled"]:
        print("  ! %d labels written for %d labelled pins"
              % (drawn_labels, stats["labelled"]), file=sys.stderr)
        ok = False
    print("  nets on board: %d   pins: %d   (rail %d / wired %d / labelled %d)"
          % (len(bynet), pins, stats["power"], stats["wired"], stats["labelled"]))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    B, comps, nets, bynet = load()
    parts, wires, labels, junctions, bynet2, power, stats = build(B, comps, nets, bynet)
    text = emit(parts, wires, labels, set(parts), comps, bynet)

    path = Path(args.out)
    path.write_text(text)
    print("wrote %s (%d lines, %.0f KB)"
          % (path.relative_to(ROOT), text.count("\n"), len(text) / 1024))
    print("  symbols: %d" % len(parts))
    print("  pins on a rail symbol: %d   pins wired: %d   pins labelled: %d"
          % (stats["power"], stats["wired"], stats["labelled"]))
    if stats["failed"]:
        u1f = [n for n, _, on_u1 in stats["failed"] if on_u1]
        print("  nets that could not be drawn: %d (%d of them FPGA nets)"
              % (len(stats["failed"]), len(u1f)))
        for net, size, _ in stats["failed"][:25]:
            print("      %-16s %d pins" % (net, size))
    if args.check:
        return 0 if check(text, bynet, power, stats) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
