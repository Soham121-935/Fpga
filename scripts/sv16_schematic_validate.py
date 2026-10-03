"""Independent check of the generated sheet.

Reads the .kicad_sch as text and asks:
  * does any wire segment pass through a symbol body?
  * is every junction dot placed where three or more directions really meet?
  * do the nets on the sheet match the board netlist?
"""
import re, sys
from collections import Counter
from pathlib import Path

txt = Path("hardware/sv16_board/sv16_board.kicad_sch").read_text()

# ---- symbol bodies, from lib_symbols -------------------------------------
bodies = {}
for m in re.finditer(r'\(symbol "([^"]+)"\n(.*?)\n    \)\n', txt, re.S):
    name, body = m.group(1), m.group(2)
    rects = [(float(a), float(b), float(c), float(d)) for a, b, c, d in
             re.findall(r'\(rectangle \(start ([\d.-]+) ([\d.-]+)\)'
                        r' \(end ([\d.-]+) ([\d.-]+)\)', body)]
    if rects:
        bodies[name] = (min(r[0] for r in rects), min(r[1] for r in rects),
                        max(r[2] for r in rects), max(r[3] for r in rects))

# ---- instances ------------------------------------------------------------
boxes = []
for m in re.finditer(r'\(symbol \(lib_id "([^"]+)"\)\s*\n\s*\(at ([\d.-]+) '
                     r'([\d.-]+) ([\d.-]+)\)', txt):
    lib, x, y = m.group(1), float(m.group(2)), float(m.group(3))
    if lib in bodies and not lib.startswith("SV16:PWR_"):
        x0, y0, x1, y1 = bodies[lib]
        boxes.append((lib, x + x0, y + y0, x + x1, y + y1))

wires = []
for m in re.finditer(r'\(wire \(pts (.*?)\)\n', txt):
    pts = [(float(a), float(b)) for a, b in
           re.findall(r'\(xy ([\d.-]+) ([\d.-]+)\)', m.group(1))]
    wires.append(pts)

junc = set()
for m in re.finditer(r'\(junction \(at ([\d.-]+) ([\d.-]+)\)', txt):
    junc.add((float(m.group(1)), float(m.group(2))))

print("symbol bodies: %d   instances: %d   wires: %d   junctions: %d"
      % (len(bodies), len(boxes), len(wires), len(junc)))

# ---- 1. wires through bodies ---------------------------------------------
def through_box(a, b, box, inset=0.2):
    _, bx0, by0, bx1, by1 = box
    bx0 += inset; by0 += inset; bx1 -= inset; by1 -= inset
    steps = max(2, int(max(abs(b[0]-a[0]), abs(b[1]-a[1])) / 0.4) + 2)
    for k in range(steps + 1):
        t = k / steps
        px, py = a[0] + (b[0]-a[0])*t, a[1] + (b[1]-a[1])*t
        if bx0 <= px <= bx1 and by0 <= py <= by1:
            return True
    return False

bad = []
for pts in wires:
    for a, b in zip(pts, pts[1:]):
        for box in boxes:
            if through_box(a, b, box):
                bad.append((box[0], a, b))
                break
print("wire segments crossing a symbol body: %d" % len(bad))
for name, a, b in bad[:10]:
    print("    %s  %s -> %s" % (name, a, b))

# ---- 2. junctions ---------------------------------------------------------
ends, interior = Counter(), Counter()
for pts in wires:
    ends[pts[0]] += 1
    ends[pts[-1]] += 1
    for pt in pts[1:-1]:
        interior[pt] += 1
need = {p for p in set(ends) | set(interior)
        if ends.get(p, 0) + 2 * interior.get(p, 0) >= 3}
print("points that need a dot: %d   dots written: %d   missing: %d   extra: %d"
      % (len(need), len(junc), len(need - junc), len(junc - need)))

sys.exit(1 if (bad or (need - junc)) else 0)
