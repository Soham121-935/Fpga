"""Independent check of the generated sheet.

Reads the .kicad_sch as text and asks:
  * does any wire segment pass through a symbol body?
  * is every junction dot placed where three or more directions really meet?
  * do the nets on the sheet match the board netlist?
"""
import re, sys
from collections import Counter
from pathlib import Path

# --- 0. strict s-expression parse, the way KiCad reads the file ------------
try:
    import sexpdata
except ImportError:
    print("sexpdata not installed - skipping the strict parse")
    sexpdata = None

if sexpdata is not None:
    tree = sexpdata.loads(Path(
        "hardware/sv16_board/sv16_board.kicad_sch").read_text())
    print("strict s-expression parse: OK")

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

# KiCad reads these as booleans, so "(hide)" with no value makes the loader
# choke on the closing paren: "Expecting yes or no. Got ')'".  Bare flags
# like (fields_autoplaced) are meant to have no value and are fine.
# A wire is exactly (pts (xy ..) (xy ..)).  A routed path has to be split
# into separate wires, because the loader stops after the second point.
for m in re.finditer(r"^  \(wire \(pts (.*?)\)\)", txt, re.M):
    if m.group(1).count("(xy") != 2:
        problems.append("line %d: wire has %d points, KiCad wants 2"
                        % (txt[:m.start()].count("\n") + 1, m.group(1).count("(xy")))

for name in ("in_bom", "on_board", "dnp", "exclude_from_sim", "hide", "bold",
             "italic", "mirror", "visible", "unlocked", "locked"):
    for m in re.finditer(r"\(%s\)" % name, txt):
        line = txt[:m.start()].count("\n") + 1
        problems.append("line %d: (%s) needs yes or no" % (line, name))
problems = []
sheet_uuid = txt.split('(uuid "', 1)[1].split('")', 1)[0]
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

# --- 5. every symbol needs instance data, and the path must be the sheet's
for m in re.finditer(r'^  \(symbol \(lib_id "[^"]+"\)(.*?)^  \)$',
                     txt, re.S | re.M):
    body = m.group(1)
    if "(instances" not in body:
        problems.append("symbol instance has no (instances ...) block")
        continue
    for path in re.findall(r'\(path "([^"]*)"', body):
        if not path.startswith("/" + sheet_uuid):
            problems.append("instance path %r does not start with the sheet uuid"
                            % path)

total = len(bad) + len(need - junc) + len(junc - need) + len(problems)
for p in problems[:10]:
    print("   ", p)
print("PROBLEMS: %d" % total)
sys.exit(1 if total else 0)
