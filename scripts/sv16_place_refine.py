#!/usr/bin/env python3
"""SV-16 — shorten the placement after it has been made legal.

sv16_place.py makes the placement *legal*: nothing overlaps, nothing hangs off
the board, U1 keeps its escape ring.  It does not make it *short*.  It parks
every movable part at the free spot nearest to where the hand-drawn floorplan
put it, so a USB-UART sitting in the wrong corner stays in the wrong corner
and its nets run the length of the board.  On the SV-16 that cost ~40 mm of
half-perimeter wirelength on an average net, with two-pin nets spanning 90 mm
of a 122 mm board.

This pass keeps the legality and chases the length.  It repeatedly tries to
move each movable part somewhere better and accepts the move only if the
total HPWL drops:

  * "somewhere better" is mostly the centroid of the pins it connects to,
    which is where a part wants to be if its wires were rubber bands, plus
    a ring of offsets around where it is now;
  * legality is decided on grown boxes, the same test sv16_place.py uses to
    pack: disjoint grown boxes guarantee the copper is clear, so a move that
    passes here cannot create a violation;
  * only the nets touching the moving part are re-measured, so a round is
    cheap enough to run a few dozen of them.

    python3 scripts/sv16_place_refine.py                    # report only
    python3 scripts/sv16_place_refine.py --rounds 40 --apply

Then regenerate and check:
    python3 scripts/sv16_board_kicad.py && python3 scripts/sv16_board_drc.py

Needs shapely and numpy.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sv16_place as P                      # noqa: E402  (Part, Grid, load_board, scan)

ROOT = Path(__file__).resolve().parent.parent

# How far a part may jump in one candidate move, mm.
STEP = 1.0
RING = (1.0, 2.5, 6.0, 12.0)


def pad_centres(part):
    """[(pad_name, cx, cy)] in board coordinates, cached off the part origin."""
    cx0, cy0 = part.origin
    out = []
    for pad in part.pads:
        c = pad["poly"].centroid
        out.append((pad["pad"], c.x - cx0, c.y - cy0))
    return out


def build_nets(parts, connections):
    """net -> [(Part, offset_x, offset_y)] for everything that has a net."""
    index = {}
    for ref, part in parts.items():
        for name, ox, oy in pad_centres(part):
            index[(ref, str(name))] = (part, ox, oy)
    nets = defaultdict(list)
    missing = 0
    for ref, pad, net in connections:
        hit = index.get((ref, str(pad)))
        if hit is None:
            missing += 1
            continue
        nets[net].append(hit)
    return nets, missing


def hpwl_of(pins, skip=None, override=None):
    """Half-perimeter of one net, in mm.

    override is (part, ox, oy) -> (x, y) for a part being trial-moved.
    """
    xs, ys = [], []
    for part, ox, oy in pins:
        if skip is not None and part is skip:
            continue
        px, py = part.origin
        if override is not None and part is override[0]:
            px, py = override[1], override[2]
        xs.append(px + ox)
        ys.append(py + oy)
    if len(xs) < 2:
        return 0.0
    return (max(xs) - min(xs)) + (max(ys) - min(ys))


def total_hpwl(nets):
    return sum(hpwl_of(pins) for pins in nets.values())


def boxes_of(parts):
    return {ref: part.grown_box() for ref, part in parts.items()}


def legal(boxes, ref, box, board_w, board_h, margin):
    """True if `box` for `ref` clears every other grown box and the edge."""
    x0, y0, x1, y1 = box
    if x0 < margin or y0 < margin or x1 > board_w - margin or y1 > board_h - margin:
        return False
    for other, ob in boxes.items():
        if other == ref:
            continue
        if x0 < ob[2] and ob[0] < x1 and y0 < ob[3] and ob[1] < y1:
            return False
    return True


def refine(parts, nets, rounds, seed=1, verbose=True):
    rng = random.Random(seed)
    movable = [p for p in parts.values() if p.movable]
    boxes = boxes_of(parts)
    touched = defaultdict(list)          # part -> nets it appears in
    for net, pins in nets.items():
        for part, _, _ in pins:
            touched[part.ref].append(net)

    bw, bh = P.BOARD_W, P.BOARD_H
    margin = P.EDGE_MARGIN
    best_total = total_hpwl(nets)
    if verbose:
        print("  starting HPWL: %.0f mm" % best_total)

    for rnd in range(rounds):
        moved = 0
        gained = 0.0
        rng.shuffle(movable)
        for part in movable:
            here = part.origin
            my_nets = touched.get(part.ref, [])
            if not my_nets:
                continue
            before = sum(hpwl_of(nets[n]) for n in my_nets)

            # where the wires want this part: centroid of the pins it joins
            px, py, n = 0.0, 0.0, 0
            own = set()
            for net in my_nets:
                for other, ox, oy in nets[net]:
                    if other is part:
                        continue
                    px += other.origin[0] + ox
                    py += other.origin[1] + oy
                    n += 1
            cands = [here]
            if n:
                cands.append((px / n, py / n))
            for d in RING:
                for dx, dy in ((d, 0), (-d, 0), (0, d), (0, -d),
                               (d, d), (-d, d), (d, -d), (-d, -d)):
                    cands.append((here[0] + dx, here[1] + dy))
            rng.shuffle(cands)

            best_xy, best_gain = None, 1e-9
            for cx, cy in cands:
                if best_xy is None and (cx, cy) == here:
                    continue
                part.move_to(cx, cy)
                box = part.grown_box()
                if not legal(boxes, part.ref, box, bw, bh, margin):
                    continue
                after = sum(hpwl_of(nets[net], override=(part, cx, cy))
                            for net in my_nets)
                gain = before - after
                if gain > best_gain:
                    best_gain, best_xy = gain, (cx, cy)
            part.move_to(*here)

            if best_xy is not None:
                part.move_to(*best_xy)
                boxes[part.ref] = part.grown_box()
                moved += 1
                gained += best_gain
        best_total -= gained
        if verbose:
            print("    round %2d: %3d parts moved, %.0f mm saved -> %.0f mm"
                  % (rnd + 1, moved, gained, best_total))
        if gained < 1.0:
            break
    return best_total


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--board", default=str(P.BOARD_FILE))
    ap.add_argument("--rounds", type=int, default=24)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--apply", action="store_true",
                    help="write the shorter placement into the generator")
    args = ap.parse_args()

    load = P.load_board(args.board)
    parts = {foot["ref"]: P.Part(foot) for foot in load[1]}

    # start from the legal packing, not from the raw file
    grid = P.Grid()
    P.pack(parts, grid)
    P.snap(parts)

    sys.path.insert(0, str(ROOT / "scripts"))
    import sv16_board_kicad as B
    nets, missing = build_nets(parts, B.CONNECTIONS)
    if missing:
        print("  ! %d connections reference a pad that is not on the board" % missing)

    print("refining %d movable parts over %d nets"
          % (sum(1 for p in parts.values() if p.movable), len(nets)))
    before = total_hpwl(nets)
    refine(parts, nets, args.rounds, seed=args.seed)
    after = total_hpwl(nets)
    print("  HPWL %.0f -> %.0f mm (%.0f%% shorter)"
          % (before, after, 100.0 * (before - after) / before if before else 0.0))

    problems = P.scan(parts)
    print("  violations after refining (exact geometry): %d" % len(problems))
    for hit in problems[:10]:
        print("    %s / %s  %.3f < %.3f (%s)" % hit)

    if problems:
        print("  NOT writing: refining must not break legality")
        return 1
    if args.apply:
        n = P.write_back(parts)
        print("  wrote %d placements back into scripts/sv16_board_kicad.py" % n)
    else:
        print("  (dry run - pass --apply to keep this)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
