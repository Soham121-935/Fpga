#!/usr/bin/env python3
"""SV-16 — turn a routing checkpoint into a board file you can open.

sv16_route.py only writes its snippet at the very end of a run, and a full
run is long enough that a background process can be lost part way.  The
copper is not lost with it: every net is checkpointed into
routing_state.json as it is routed.  This script takes that checkpoint,
rebuilds the pours and planes that go with it, and writes the snippet, so a
half-finished route is still a board file KiCad can open.

    python3 scripts/sv16_route_splice.py
    python3 scripts/sv16_board_kicad.py

The result is a partial route: whatever was checkpointed is on the board,
whatever was not is left with copper on its pads and nothing joining it.
Run sv16_route.py --resume to carry on and re-splice when it finishes.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sv16_route as R                      # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--board", default=str(R.BOARD_FILE))
    parser.add_argument("--no-planes", action="store_true",
                        help="skip the GND plane pours (faster, for a look at tracks)")
    args = parser.parse_args()

    if not R.CHECKPOINT.exists():
        print("no checkpoint at %s - nothing to splice" % R.CHECKPOINT)
        return 1

    start = time.time()
    board = R.Board(args.board)
    print("splicing %s" % R.CHECKPOINT.name)
    loaded = R.load_state(board)
    print("  %d tracks, %d vias, %d finished net(s)"
          % (loaded, len(board.new_vias), len(board.done_nets)))

    pours = R.build_pours(board, verbose=False)
    zones = pours + ([] if args.no_planes else R.build_planes(board))

    count = R.write_snippet(board, zones, R.SNIPPET)
    print("  wrote %s (%d lines)" % (R.SNIPPET.relative_to(R.ROOT), count))

    broken = sorted(net for net in board.nets if len(R.net_pieces(board, net)) > 1)
    print("  nets still in more than one piece: %d" % len(broken))
    for net in broken[:25]:
        print("    - %s" % net)
    if len(broken) > 25:
        print("    ... and %d more" % (len(broken) - 25))
    print("  %.1f s" % (time.time() - start))
    print("\nrebuild the board file with:  python3 scripts/sv16_board_kicad.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
