#!/usr/bin/env python3
"""Copper plan for the SV-16 board: power pours, escape vias, stitching, thermals.

`sv16_board_kicad.py` writes footprints, pads and nets.  This module decides the
*copper* that can be worked out without a human at the mouse:

  * **power pours on `In2.Cu`** — 3V3 everywhere (the rail almost every part
    needs), with higher-priority patches for 1V1 and 2V5 where their regulators
    and bulk capacitors live.  KiCad resolves the overlap by zone priority, so
    the pour polygons are allowed to overlap and DRC stays clean.
  * **escape vias** — for every surface-mount pad that can legally drop into a
    pour of its own net straight away (GND into the In1 plane, 3V3 into the In2
    pour, 1V1/2V5 into their patches), with a 0.2 mm stub track from the pad.
    This is the tedious half of the TQFP-144 fan-out and the "via first at the
    pad" rule from PCB_COMPONENTS.md section 7, done for the pads where it is
    unambiguous.
  * **thermal vias** in the MP1584's exposed pad.
  * **stitching vias** on a coarse grid wherever nothing else is.

Everything is checked before it is emitted: a pad that lies inside a pour of a
*different* net is never given a via (that would be a short), vias are placed
with the 0.2 mm clearance the fab rules ask for, and the planner reports what it
skipped and why.  `sv16_pcb_copper.py --report` prints that plan without
touching the board file.

Geometry note: a pad's position on the board is

    global = origin + rotate(local, footprint_rotation)

with the rotation applied clockwise in KiCad's screen coordinates (y grows
downwards).  :func:`rotate` implements exactly that, and every pad in the
generated board is a rectangle or a circle, which is all the clearance test
needs.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- fab rules (PCB_COMPONENTS.md section 7 / the KiCad project's constraints)
CLEARANCE = 0.20          # mm, copper-to-copper minimum the board is designed to
EDGE_CLEARANCE = 0.60     # mm, via edge to board edge
ESCAPE_VIA_DIA = 0.45     # mm  (the third via size the tutorial adds)
ESCAPE_VIA_DRILL = 0.20
STITCH_VIA_DIA = 0.60
STITCH_VIA_DRILL = 0.30
STUB_WIDTH = 0.20

# --- pours on In2.Cu, as polygons of (x, y) points, with a priority.
#
# The layout rule this encodes: a surface-mount pad can drop straight into the
# inner layer **only where the copper underneath already belongs to its own
# net**.  3V3 is the rail almost every part on the board needs, so it is the
# whole layer; 1V1 and 2V5 are carved out of it where their own regulators,
# bulk capacitors and decoupling live.
#
#   3V3  priority 0  the whole board
#   2V5  priority 2  the LP5907 group and the band above U1 where C8-C11 sit
#   1V1  priority 3  the MP1584 group, plus the strip down the left of U1 that
#                    feeds C2-C7 and U1 pins 20/29
#
# KiCad fills the higher-priority zone first and cuts the lower one back, so
# the polygons may overlap and DRC stays clean.  Pads that end up over a pour
# of the *wrong* net are reported by the planner (see `--report`) instead of
# being given a via that would short two rails together.
POURS: list[tuple[str, int, list[list[tuple[float, float]]]]] = [
    ("3V3", 0, [[(3.0, 3.0), (97.0, 3.0), (97.0, 97.0), (3.0, 97.0)]]),
    ("2V5", 2, [[(32.5, 26.0), (44.5, 26.0), (44.5, 34.5), (32.5, 34.5)],
                [(36.0, 35.0), (56.0, 35.0), (56.0, 39.4), (36.0, 39.4)]]),
    ("1V1", 3, [[(18.0, 14.0), (35.5, 14.0), (35.5, 36.0), (38.0, 36.0),
                 (38.0, 64.0), (32.0, 64.0), (32.0, 36.0), (18.0, 36.0)]]),
]

# --- nets that may use a plane
# GND has a solid plane on In1.Cu and a pour on B.Cu, so a GND via is legal
# anywhere; the three rails may only via where their own In2 pour is.
PLANE_NETS = ("GND", "3V3", "1V1", "2V5")
SOLID_NETS = ("GND",)


def rotate(lx: float, ly: float, degrees: float) -> tuple[float, float]:
    """KiCad's footprint rotation, in file coordinates (y grows downwards)."""
    t = math.radians(degrees)
    c, s = math.cos(t), math.sin(t)
    return (lx * c + ly * s, -lx * s + ly * c)


class Pad:
    __slots__ = ("ref", "num", "net", "x", "y", "w", "h", "rot", "shape",
                 "kind", "lx", "ly")

    def __init__(self, ref, num, net, x, y, w, h, rot, shape, kind, lx, ly):
        self.ref, self.num, self.net = ref, num, net
        self.x, self.y, self.w, self.h = x, y, w, h
        self.rot, self.shape, self.kind = rot, shape, kind
        self.lx, self.ly = lx, ly

    @property
    def is_smd(self) -> bool:
        return self.kind == "smd"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Pad(%s.%s %s @ %.2f,%.2f)" % (self.ref, self.num, self.net,
                                              self.x, self.y)


def collect_pads(placed, nets_by_ref) -> list[Pad]:
    """placed: iterable of (ref, pads, origin_x, origin_y, rotation)."""
    pads: list[Pad] = []
    for ref, pad_list, origin_x, origin_y, rot in placed:
        nets = nets_by_ref.get(ref, {})
        for pad in pad_list:
            dx, dy = rotate(pad["x"], pad["y"], rot)
            pads.append(Pad(ref, str(pad["number"]), nets.get(str(pad["number"])),
                            origin_x + dx, origin_y + dy, pad["w"], pad["h"], rot,
                            pad["shape"], pad["kind"], pad["x"], pad["y"]))
    return pads


def rect_distance(px: float, py: float, pad: Pad) -> float:
    """Distance from a point to a pad's copper (0 inside the pad)."""
    hw, hh = pad.w / 2.0, pad.h / 2.0
    dx = max(abs(px - pad.x) - hw, 0.0)
    dy = max(abs(py - pad.y) - hh, 0.0)
    return math.hypot(dx, dy)


def inside_pour(x: float, y: float, polygons) -> bool:
    for polygon in polygons:
        if point_in_polygon(x, y, polygon):
            return True
    return False


def hit_polygon(x: float, y: float, polygons) -> bool:
    return inside_pour(x, y, polygons)


def point_in_polygon(x: float, y: float, polygon) -> bool:
    """Ray casting; the polygons here are simple and axis-aligned."""
    inside = False
    count = len(polygon)
    for index in range(count):
        x0, y0 = polygon[index]
        x1, y1 = polygon[(index + 1) % count]
        if (y0 > y) != (y1 > y):
            x_cross = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < x_cross:
                inside = not inside
    return inside


def winning_pour_at(x: float, y: float):
    """The pour that actually owns this point: the highest priority covering it."""
    best = None
    for pour_net, priority, polygons in POURS:
        if inside_pour(x, y, polygons):
            if best is None or priority > best[1]:
                best = (pour_net, priority)
    return best


def pour_of_net_at(x: float, y: float, net: str) -> bool:
    if net in SOLID_NETS:
        return True                       # In1.Cu plane + B.Cu pour
    winner = winning_pour_at(x, y)
    return winner is not None and winner[0] == net


def foreign_pour_at(x: float, y: float, net: str):
    """The pour that owns this point when it is not this net's own."""
    if net in SOLID_NETS:
        return None                       # nothing can be swallowed by GND
    winner = winning_pour_at(x, y)
    if winner is None or winner[0] == net:
        return None
    return winner


class Copper:
    """The plan: zones, vias and stub tracks, plus the reasons things were skipped."""

    def __init__(self):
        self.vias: list[dict] = []
        self.segments: list[dict] = []
        self.notes: list[str] = []
        self.skipped: list[str] = []

    # -- geometry helpers -------------------------------------------------
    def _clear_of(self, x: float, y: float, net: str, radius: float,
                  pads: list[Pad]) -> bool:
        """True when a circle at (x, y) keeps CLEARANCE from every other net."""
        for pad in pads:
            if pad.net is None or pad.net == net:
                continue
            if rect_distance(x, y, pad) < radius + CLEARANCE:
                return False
        for via in self.vias:
            if via["net"] == net:
                continue
            if math.hypot(via["x"] - x, via["y"] - y) < 2 * radius + CLEARANCE:
                return False
        return True

    def _stub_clear(self, pad: Pad, x: float, y: float, net: str,
                    pads: list[Pad]) -> bool:
        """True when the 0.2 mm stub from pad to (x, y) clears other pads."""
        steps = max(int(math.hypot(x - pad.x, y - pad.y) / 0.05), 2)
        for index in range(steps + 1):
            t = index / steps
            px = pad.x + (x - pad.x) * t
            py = pad.y + (y - pad.y) * t
            for other in pads:
                if other is pad or other.net is None or other.net == net:
                    continue
                if rect_distance(px, py, other) < STUB_WIDTH / 2.0 + CLEARANCE:
                    return False
        return True

    def add_via(self, x: float, y: float, net: str, number: int, *,
                diameter: float = ESCAPE_VIA_DIA, drill: float = ESCAPE_VIA_DRILL,
                connect_pad: Pad | None = None) -> bool:
        self.vias.append({"x": round(x, 3), "y": round(y, 3), "net": net,
                          "number": number, "dia": diameter, "drill": drill})
        if connect_pad is not None:
            self.segments.append({"start": (round(connect_pad.x, 3), round(connect_pad.y, 3)),
                                  "end": (round(x, 3), round(y, 3)),
                                  "width": STUB_WIDTH, "net": net, "layer": "F.Cu"})
        return True


def pad_touches_pour(pad: Pad, net: str) -> bool:
    """True when the pad's own copper overlaps the In2 pour of its net."""
    if net in SOLID_NETS:
        return False                      # GND is on In1/B.Cu: it needs a via
    points = [(pad.x, pad.y)]
    for sx in (-0.5, 0.5):
        for sy in (-0.5, 0.5):
            points.append((pad.x + sx * pad.w, pad.y + sy * pad.h))
    for px, py in points:
        if pour_of_net_at(px, py, net):
            return True
    return False


def plan_escapes(copper: Copper, pads: list[Pad], origins: dict[str, tuple[float, float]],
                 net_number, board_w: float, board_h: float) -> None:
    """One escape via per surface-mount pad that can legally drop into its pour."""
    for pad in sorted(pads, key=lambda p: (p.ref, p.num)):
        if not pad.is_smd or pad.net is None:
            continue
        if pad.net not in PLANE_NETS:
            continue
        # An SMD pad is on F.Cu; the pour is on In2.Cu (or In1.Cu for GND), so it
        # only ever connects through a via - there is no "already touching"
        # shortcut.  Through-hole pads are the exception and are skipped above.

        # escape directions: away from the part's own centre first (along the pad
        # axis for a two-pad chip part, radially outwards for U1), then the two
        # perpendicular directions - a pad whose pour lies to the side still gets
        # its via without the router having to do it by hand.
        ox, oy = origins.get(pad.ref, (pad.x, pad.y))
        dx, dy = pad.x - ox, pad.y - oy
        length = math.hypot(dx, dy)
        if length < 0.05:                       # a centre pad: handled as a thermal
            continue
        dx, dy = dx / length, dy / length
        # snap to the dominant axis: a QFP escape leaves the pad straight out,
        # and an axis-aligned stub keeps its 0.25 mm to the neighbouring pad
        if abs(dx) >= abs(dy):
            dx, dy = (1.0 if dx > 0 else -1.0), 0.0
        else:
            dx, dy = 0.0, (1.0 if dy > 0 else -1.0)
        directions = [(dx, dy), (-dy, dx), (dy, -dx)]

        placed = False
        for ux, uy in directions:
            # the pad's own half-size along this direction, so the via lands
            # clear of the pad's copper as well as of its neighbours
            if abs(ux) > abs(uy):
                half = pad.w / 2.0 * abs(ux) + pad.h / 2.0 * abs(uy)
            else:
                half = pad.h / 2.0 * abs(uy) + pad.w / 2.0 * abs(ux)
            for extra in (0.42, 0.62, 0.82, 1.05, 1.30, 1.60, 2.00, 2.50, 3.00, 3.60):
                distance = half + extra + ESCAPE_VIA_DIA / 2.0
                x, y = pad.x + ux * distance, pad.y + uy * distance
                if not (EDGE_CLEARANCE + ESCAPE_VIA_DIA / 2.0 < x < board_w - EDGE_CLEARANCE - ESCAPE_VIA_DIA / 2.0
                        and EDGE_CLEARANCE + ESCAPE_VIA_DIA / 2.0 < y < board_h - EDGE_CLEARANCE - ESCAPE_VIA_DIA / 2.0):
                    continue
                if not pour_of_net_at(x, y, pad.net):
                    continue                    # the via must land in its own pour
                if not copper._clear_of(x, y, pad.net, ESCAPE_VIA_DIA / 2.0, pads):
                    continue
                if not copper._stub_clear(pad, x, y, pad.net, pads):
                    continue
                if any(math.hypot(v["x"] - x, v["y"] - y) < ESCAPE_VIA_DIA + CLEARANCE
                       for v in copper.vias):
                    continue
                copper.add_via(x, y, pad.net, net_number(pad.net), connect_pad=pad)
                placed = True
                break
            if placed:
                break
        if not placed:
            if foreign := foreign_pour_at(pad.x, pad.y, pad.net):
                copper.skipped.append(
                    "%s.%s (%s) escapes into the %s pour - route it out by hand, do not via here"
                    % (pad.ref, pad.num, pad.net, foreign[0]))
            else:
                copper.skipped.append(
                    "%s.%s (%s) has no room for an escape via - route it to the %s pour"
                    % (pad.ref, pad.num, pad.net, pad.net))


def plan_thermal(copper: Copper, pads: list[Pad], ref: str, net: str, net_number) -> None:
    """Four vias inside an exposed pad (the MP1584's GND pad)."""
    for pad in pads:
        if pad.ref != ref or pad.num != "9" or pad.net != net:
            continue
        offsets = [(-pad.w / 2 + 0.55, -pad.h / 2 + 0.55), (pad.w / 2 - 0.55, -pad.h / 2 + 0.55),
                   (-pad.w / 2 + 0.55, pad.h / 2 - 0.55), (pad.w / 2 - 0.55, pad.h / 2 - 0.55)]
        for ox, oy in offsets:
            x, y = pad.x + ox, pad.y + oy
            if not copper._clear_of(x, y, net, ESCAPE_VIA_DIA / 2.0, pads):
                continue
            copper.add_via(x, y, net, net_number(net), connect_pad=pad)
        copper.notes.append("%s: exposed pad stitched with vias to the GND plane" % ref)


def plan_stitching(copper: Copper, pads: list[Pad], net_number, board_w: float,
                   board_h: float, *, rings=(2.5, 7.0), spacing: float = 5.0,
                   skip: list[tuple[float, float, float, float]] = ()) -> None:
    """GND stitching around the board edge, where nothing else is in the way.

    Deliberately a *ring* and not a grid: the interior belongs to the router,
    and KICAD_TUTORIAL.md asks for stitching "along the board edge and either
    side of the USB pair" rather than a field of vias under the signals.
    """
    radius = STITCH_VIA_DIA / 2.0
    candidates: list[tuple[float, float]] = []
    for offset in rings:
        steps = max(int((board_w - 2 * offset) / spacing), 1)
        for index in range(steps + 1):
            x = offset + index * (board_w - 2 * offset) / steps
            candidates.append((x, offset))
            candidates.append((x, board_h - offset))
        steps = max(int((board_h - 2 * offset) / spacing), 1)
        for index in range(steps + 1):
            y = offset + index * (board_h - 2 * offset) / steps
            candidates.append((offset, y))
            candidates.append((board_w - offset, y))

    count = 0
    for x, y in candidates:
        if any(r[0] - 1.0 <= x <= r[2] + 1.0 and r[1] - 1.0 <= y <= r[3] + 1.0
               for r in skip):
            continue
        if not copper._clear_of(x, y, "GND", radius, pads):
            continue
        if any(math.hypot(v["x"] - x, v["y"] - y) < STITCH_VIA_DIA + CLEARANCE
               for v in copper.vias):
            continue
        copper.add_via(x, y, "GND", net_number("GND"),
                       diameter=STITCH_VIA_DIA, drill=STITCH_VIA_DRILL)
        count += 1
    copper.notes.append("%d GND stitching vias (rings at %s mm, %.1f mm apart)"
                        % (count, "/".join("%.1f" % r for r in rings), spacing))


def build(placed, nets_by_ref, origins, net_number, board_w: float, board_h: float,
          *, stitching: bool = True, escapes: bool = True) -> Copper:
    pads = collect_pads(placed, nets_by_ref)
    copper = Copper()
    if escapes:
        plan_escapes(copper, pads, origins, net_number, board_w, board_h)
        plan_thermal(copper, pads, "U6", "GND", net_number)
    if stitching:
        # keep the stitching out of the FPGA pad ring: that area belongs to the
        # fan-out, and the escape vias are already there
        plan_stitching(copper, pads, net_number, board_w, board_h,
                       skip=[(37.0, 37.0, 67.0, 67.0)])
    return copper


def rect_gap(first: Pad, second: Pad) -> float:
    """Edge-to-edge distance between two pads (negative = the pads overlap)."""
    dx = abs(first.x - second.x) - (first.w + second.w) / 2.0
    dy = abs(first.y - second.y) - (first.h + second.h) / 2.0
    if dx <= 0 and dy <= 0:
        return max(dx, dy)                    # overlapping rectangles
    return math.hypot(max(dx, 0.0), max(dy, 0.0))


def verify_pads(placed, nets_by_ref) -> int:
    """A pad-to-pad DRC: two pads of different nets may not touch or be too close.

    This catches placement collisions that are invisible in a footprint list -
    two parts whose pads overlap are a short before the board is even routed.
    """
    pads = collect_pads(placed, nets_by_ref)
    problems = 0
    for index, first in enumerate(pads):
        if first.net is None:
            continue
        for second in pads[index + 1:]:
            if second.net is None or second.net == first.net:
                continue
            if first.ref == second.ref:
                continue
            gap = rect_gap(first, second)
            if gap < CLEARANCE - 1e-6:
                print("  FAIL: %s.%s (%s) and %s.%s (%s) are %.3f mm apart%s"
                      % (first.ref, first.num, first.net, second.ref, second.num,
                         second.net, gap, " - OVERLAP" if gap < 0 else ""))
                problems += 1
    return problems


def verify(copper: Copper, placed, nets_by_ref) -> int:
    """A tiny DRC: no two different nets closer than CLEARANCE, nothing off-board."""
    pads = collect_pads(placed, nets_by_ref)
    problems = verify_pads(placed, nets_by_ref)
    for via in copper.vias:
        net = via["net"]
        for pad in pads:
            if pad.net is None or pad.net == net:
                continue
            gap = rect_distance(via["x"], via["y"], pad) - via["dia"] / 2.0
            if gap < CLEARANCE - 1e-6:
                print("  FAIL: via %s at (%.2f, %.2f) is %.3f mm from %s.%s (%s)"
                      % (net, via["x"], via["y"], gap, pad.ref, pad.num, pad.net))
                problems += 1
    for index, first in enumerate(copper.vias):
        for second in copper.vias[index + 1:]:
            if first["net"] == second["net"]:
                continue
            gap = math.hypot(first["x"] - second["x"], first["y"] - second["y"]) \
                - first["dia"] / 2.0 - second["dia"] / 2.0
            if gap < CLEARANCE - 1e-6:
                print("  FAIL: vias %s(%.2f,%.2f) and %s(%.2f,%.2f) are %.3f mm apart"
                      % (first["net"], first["x"], first["y"], second["net"],
                         second["x"], second["y"], gap))
                problems += 1
    for segment in copper.segments:
        net = segment["net"]
        x0, y0 = segment["start"]
        x1, y1 = segment["end"]
        steps = max(int(math.hypot(x1 - x0, y1 - y0) / 0.05), 2)
        for index in range(steps + 1):
            t = index / steps
            px, py = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            for pad in pads:
                if pad.net is None or pad.net == net:
                    continue
                if math.hypot(px - pad.x, py - pad.y) < 0.02:
                    continue                     # the pad this stub starts from
                if rect_distance(px, py, pad) < CLEARANCE - 1e-6:
                    print("  FAIL: %s stub crosses %s.%s (%s)"
                          % (net, pad.ref, pad.num, pad.net))
                    problems += 1
                    break
    for via in copper.vias:
        if not (0 < via["x"] < 100 and 0 < via["y"] < 100):
            print("  FAIL: via %s off the board" % via["net"])
            problems += 1
    return problems


def report(copper: Copper, pads: list[Pad]) -> None:
    """Print the plan: what got copper, and what the router still has to do."""
    by_net: dict[str, int] = {}
    for via in copper.vias:
        by_net[via["net"]] = by_net.get(via["net"], 0) + 1
    print("  vias:       %d (%s)" % (len(copper.vias),
                                     ", ".join("%s %d" % kv for kv in sorted(by_net.items()))))
    print("  stub tracks:%d" % len(copper.segments))
    for note in copper.notes:
        print("  note:       %s" % note)

    skipped_rails = [s for s in copper.skipped if "pour - route it out" in s]
    if skipped_rails:
        print("  RAIL DELIVERY (route these pads to their pour by hand):")
        for line in skipped_rails:
            print("    - %s" % line)


def main() -> int:
    """Print the plan the board generator will use (no files are touched)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", action="store_true",
                        help="also list every pad the router still has to connect")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "scripts"))
    import sv16_board_kicad as board       # noqa: E402  (the data lives there)

    copper = board.copper_plan()           # built from effective_placement()
    placed = [(ref, board.pads_of(builder), *board.effective_placement()[ref])
              for ref, library, builder, value, group in board.COMPONENTS
              if ref in board.effective_placement()]
    nets_by_ref: dict = {}
    for ref, pad, net in board.CONNECTIONS:
        nets_by_ref.setdefault(ref, {})[pad] = net

    by_net: dict[str, int] = {}
    for via in copper.vias:
        by_net[via["net"]] = by_net.get(via["net"], 0) + 1
    print("copper plan for %d footprints:" % len(placed))
    print("  vias:       %d (%s)" % (len(copper.vias),
                                     ", ".join("%s %d" % kv for kv in sorted(by_net.items()))))
    print("  stub tracks:%d" % len(copper.segments))
    print("  zones:      %d (2 GND + %d rail pours on In2.Cu)"
          % (2 + len(POURS), len(POURS)))
    for note in copper.notes:
        print("  note:       %s" % note)
    problems = verify(copper, placed, nets_by_ref)
    if args.report:
        report(copper, collect_pads(placed, nets_by_ref))
    print("  %s" % ("DRC-lite OK" if problems == 0 else "%d FAILURES" % problems))
    return problems


if __name__ == "__main__":
    sys.exit(main())
