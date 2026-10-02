#!/usr/bin/env python3
"""Write the SV-16 board schematic: hardware/sv16_board/sv16_board.kicad_sch.

The board in sv16_board_kicad.py already carries the whole design as a netlist:
COMPONENTS is (ref, footprint, pads, value, group) and CONNECTIONS is
(ref, pad, net).  That is exactly the information a schematic holds, so the
schematic is generated from it rather than drawn a second time by hand.  One
source, two views: change a connection in the board generator and both files
move together, and a net that exists on the board but not on the sheet (or the
other way about) is a hard error instead of a surprise at assembly.

How it reads: every pin carries a global label naming its net.  Labels are how
KiCad nets a schematic anyway - two pins with the same label are one net - so
the sheet is electrically identical to the board even though no wires are drawn
between symbols.  A program can place 141 symbols tidily; it cannot draw the
600-odd wires a person would want to read, and fake tidiness would be worse
than honest labels.

Symbols are generated to fit each part's own pad list, so the USB-C connector
shows A1..B12 and S1..S4 rather than being flattened into 1..20.

Use --check to compare the sheet against the board netlist and stop on any
difference.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "hardware" / "sv16_board" / "sv16_board.kicad_sch"

# --- sheet geometry, all in millimetres, all on the KiCad 2.54 mm symbol grid
PIN_LEN = 2.54          # how far a pin reaches from its connection point
STUB = 5.08             # wire from the pin out to where its label sits
LABEL_W = 20.0          # room kept beside a symbol for label text
PITCH = 2.54            # pin to pin
GAP = 6.0               # between cells
MARGIN = 25.0

PAPER = "A0"
PAGE_W, PAGE_H = 1189.0, 841.0

# Nets are drawn in this order of importance so the eye can find them.
GROUP_ORDER = ["fpga", "power", "usb", "flash", "jtag", "leds",
               "expansion", "passives", "test", "mech"]

# Stable identifiers: the same netlist always produces the same file, so the
# schematic can be diffed between commits.
NS = uuid.UUID("6f0d5b3e-9c1a-4a52-9e6f-2f2b6a1d4c77")


def uu(tag: str) -> str:
    return str(uuid.uuid5(NS, "sv16-schematic/" + tag))


def ref_key(ref: str):
    """Sort R2 before R10."""
    m = re.match(r"([A-Za-z_]+)(\d+)$", ref)
    return (m.group(1), int(m.group(2)), ref) if m else (ref, 0, ref)


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


# ------------------------------------------------------------------- netlist
def load():
    import sv16_board_kicad as B

    comps = {}
    for ref, library, pads_spec, value, group in B.COMPONENTS:
        pads = B.pads_of(pads_spec)
        comps[ref] = {
            "ref": ref, "fp": library, "value": value, "group": group,
            "pads": [p["number"] for p in pads],
        }

    nets = {}                       # (ref, pad) -> net
    for ref, pad, net in B.CONNECTIONS:
        nets[(ref, str(pad))] = net

    # A connection to a pad the footprint does not have would silently vanish
    # from the board; that is worth failing loudly for.
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
        raise SystemExit("%d netlist problem(s) between board and sheet"
                         % len(problems))
    return B, comps, nets


# -------------------------------------------------------------------- symbols
class Shape:
    """How one component's pins are laid out on the sheet."""

    def __init__(self, pads):
        self.pads = list(pads)
        n = len(self.pads)
        half = (n + 1) // 2
        self.left = self.pads[:half]
        self.right = self.pads[half:]
        rows = max(len(self.left), len(self.right), 1)
        self.body_w = 5.08 if n <= 2 else 10.16
        self.body_h = max(rows * PITCH + PITCH, 5.08)
        self.cell_w = self.body_w + 2 * (PIN_LEN + STUB + LABEL_W)
        self.cell_h = self.body_h + 14.0

    def pins(self):
        """(number, x, y, angle) in symbol coordinates."""
        out = []
        top = (len(self.left) - 1) * PITCH / 2.0
        for index, number in enumerate(self.left):
            out.append((number, -(self.body_w / 2 + PIN_LEN),
                        top - index * PITCH, 0))
        top = (len(self.right) - 1) * PITCH / 2.0
        for index, number in enumerate(self.right):
            out.append((number, self.body_w / 2 + PIN_LEN,
                        top - index * PITCH, 180))
        return out

    def key(self):
        return (len(self.pads), tuple(self.pads))


def symbol_def(name: str, shape: Shape) -> list:
    """One (symbol ...) entry for lib_symbols."""
    lines = [
        '    (symbol "%s"' % name,
        '      (pin_names (offset 0.762) hide)',
        '      (exclude_from_sim no)',
        '      (in_bom yes) (on_board yes)',
        '      (property "Reference" "U" (at 0 %.3f 0)'
        ' (effects (font (size 1.27 1.27)) hide))'
        % (shape.body_h / 2 + 1.27),
        '      (property "Value" "" (at 0 %.3f 0)'
        ' (effects (font (size 1.27 1.27)) hide))'
        % -(shape.body_h / 2 + 1.27),
        '      (property "Footprint" "" (at 0 0 0)'
        ' (effects (font (size 1.27 1.27)) hide))',
        '      (property "Datasheet" "~" (at 0 0 0)'
        ' (effects (font (size 1.27 1.27)) hide))',
        '      (symbol "%s_0_1"' % name,
        '        (rectangle (start %.3f %.3f) (end %.3f %.3f)'
        % (-shape.body_w / 2, -shape.body_h / 2,
           shape.body_w / 2, shape.body_h / 2),
        '          (stroke (width 0.254) (type default) (color 0 0 0 0))',
        '          (fill (type background))',
        '        )',
        '      )',
        '      (symbol "%s_1_1"' % name,
    ]
    for number, x, y, angle in shape.pins():
        lines += [
            '        (pin passive line (at %.3f %.3f %d) (length %.3f)'
            % (x, y, angle, PIN_LEN),
            '          (name "%s" (effects (font (size 1.27 1.27))))'
            % esc(str(number)),
            '          (number "%s" (effects (font (size 1.27 1.27))))'
            % esc(str(number)),
            '        )',
        ]
    lines += ['      )', '    )']
    return lines


# -------------------------------------------------------------------- layout
def place(order, shapes):
    """Shelf-pack left to right, wrapping at the page edge."""
    spots, x, y, row_h = [], MARGIN, MARGIN, 0.0
    for ref in order:
        shape = shapes[ref]
        if x > MARGIN and x + shape.cell_w > PAGE_W - MARGIN:
            x, y, row_h = MARGIN, y + row_h + GAP, 0.0
        spots.append((ref, x, y))
        x += shape.cell_w + GAP
        row_h = max(row_h, shape.cell_h)
    return spots


# -------------------------------------------------------------------- output
def build(B, comps, nets) -> str:
    # Parts with nothing connected are mechanical (mounting holes, fiducials)
    # and have no business on a sheet; a mounting hole's single pad is not even
    # numbered.
    used = sorted((ref for ref in comps if any(r == ref for (r, _) in nets)),
                  key=lambda r: (GROUP_ORDER.index(comps[r]["group"])
                                 if comps[r]["group"] in GROUP_ORDER else 99,
                                 ref_key(r)))
    skipped = sorted(set(comps) - set(used))

    shapes = {ref: Shape(comps[ref]["pads"]) for ref in used}

    # One symbol definition per distinct pin list: every 0603 resistor shares
    # one, the USB-C connector gets its own with A1..S4.
    names, defs = {}, []
    for ref in used:
        key = shapes[ref].key()
        if key not in names:
            name = "SV16:P%d_%d" % (len(shapes[ref].pads), len(names))
            names[key] = name
            defs += symbol_def(name, shapes[ref])

    out = [
        '(kicad_sch (version 20231120) (generator "sv16_schematic_kicad")',
        '  (uuid "%s")' % uu("sheet"),
        '  (paper "%s")' % PAPER,
        '  (title_block',
        '    (title "SV-16 FPGA board")',
        '    (date "%s")' % B.__dict__.get("BUILD_DATE", ""),
        '    (rev "1")',
        '    (comment 1 "Generated from scripts/sv16_board_kicad.py - every '
        'pin carries its net as a global label")',
        '  )',
        '  (lib_symbols',
    ]
    out += defs
    out.append('  )')

    wires, labels = [], []
    for ref, x, y in place(used, shapes):
        shape = shapes[ref]
        comp = comps[ref]
        name = names[shape.key()]
        cx = x + LABEL_W + STUB + PIN_LEN + shape.body_w / 2
        cy = y + 7.0 + shape.body_h / 2

        out += [
            '  (symbol (lib_id "%s")' % name,
            '    (at %.3f %.3f 0)' % (cx, cy),
            '    (unit 1)',
            '    (in_bom yes) (on_board yes) (dnp no) (fields_autoplaced yes)',
            '    (uuid "%s")' % uu("symbol/" + ref),
            '    (property "Reference" "%s" (at %.3f %.3f 0)'
            % (esc(ref), cx, cy - shape.body_h / 2 - 1.27),
            '      (effects (font (size 1.27 1.27)) (justify left))',
            '    )',
            '    (property "Value" "%s" (at %.3f %.3f 0)'
            % (esc(comp["value"]), cx, cy + shape.body_h / 2 + 1.27),
            '      (effects (font (size 1.27 1.27)) (justify left))',
            '    )',
            '    (property "Footprint" "%s" (at %.3f %.3f 0)'
            % (esc(comp["fp"]), cx, cy),
            '      (effects (font (size 1.27 1.27)) hide)',
            '    )',
            '    (property "Datasheet" "~" (at %.3f %.3f 0)' % (cx, cy),
            '      (effects (font (size 1.27 1.27)) hide)',
            '    )',
        ]
        for number, _, _, _ in shape.pins():
            out.append('    (pin "%s" (uuid "%s"))'
                       % (esc(str(number)), uu("pin/%s/%s" % (ref, number))))
        out.append('  )')

        for number, px, py, angle in shape.pins():
            net = nets.get((ref, str(number)))
            if not net:
                continue
            # The stub leaves the pin in the direction the pin body points in,
            # so it always runs away from the symbol rather than through it.
            sx, sy = cx + px, cy + py
            step = -STUB if angle == 0 else STUB
            ex, ey = sx + step, sy
            wires += [
                '  (wire (pts (xy %.3f %.3f) (xy %.3f %.3f))'
                % (sx, sy, ex, ey),
                '    (stroke (width 0) (type default) (color 0 0 0 0))',
                '    (uuid "%s")' % uu("wire/%s/%s" % (ref, number)),
                '  )',
            ]
            labels += [
                '  (global_label "%s" (shape input) (at %.3f %.3f %d) '
                '(fields_autoplaced)' % (esc(net), ex, ey, angle),
                '    (effects (font (size 1.27 1.27)) (justify %s))'
                % ("right" if angle == 180 else "left"),
                '    (uuid "%s")' % uu("label/%s/%s" % (ref, number)),
                '    (property "Intersheet References" "${INTERSHEET_REFS}"'
                ' (at %.3f %.3f 0)' % (ex, ey),
                '      (effects (font (size 1.27 1.27)) hide)',
                '      (uuid "%s")' % uu("iref/%s/%s" % (ref, number)),
                '    )',
                '  )',
            ]

    out += wires
    out += labels
    out += ['  (sheet_instances', '    (path "/" (page "1"))', '  )', ')']
    return "\n".join(out) + "\n", used, skipped


def check(B, comps, nets, text, used):
    """The sheet must describe exactly the nets the board does."""
    board = {}
    for ref, pad, net in B.CONNECTIONS:
        board.setdefault(net, set()).add((ref, str(pad)))

    drawn = {}
    labelled = 0
    for match in re.finditer(r'^\s+\(global_label "((?:[^"\\]|\\.)*)"',
                             text, re.M):
        drawn.setdefault(match.group(1).replace('\\"', '"'), 0)
        drawn[match.group(1).replace('\\"', '"')] += 1
        labelled += 1

    problems = []
    for net, pins in board.items():
        if net not in drawn:
            problems.append("net %s is on the board but not on the sheet" % net)
    for net in drawn:
        if net not in board:
            problems.append("net %s is on the sheet but not on the board" % net)

    # Every pad that carries a net on the board must carry a label here, or a
    # connection has gone missing between the two views.
    board_pins = sum(len(v) for v in board.values())
    if board_pins != labelled:
        problems.append("%d pads carry a net on the board but %d are labelled "
                        "on the sheet" % (board_pins, labelled))

    for line in problems:
        print("  ! %s" % line, file=sys.stderr)
    print("  nets on board: %d   nets on sheet: %d" % (len(board), len(drawn)))
    print("  pads carrying a net: %d   labelled pins: %d"
          % (board_pins, labelled))
    return not problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--check", action="store_true",
                    help="cross-check the sheet against the board netlist")
    args = ap.parse_args()

    B, comps, nets = load()
    text, used, skipped = build(B, comps, nets)

    path = Path(args.out)
    path.write_text(text)

    # Nothing is much use off the edge of the sheet.
    xs = [float(m) for m in re.findall(r'\(at ([\d.]+) [\d.]+ 0\)\n    \(unit 1\)',
                                       text)]
    ys = [float(m) for m in re.findall(r'\(at [\d.]+ ([\d.]+) 0\)\n    \(unit 1\)',
                                       text)]
    over = sum(1 for x, y in zip(xs, ys) if x > PAGE_W or y > PAGE_H)

    print("wrote %s (%d lines, %.0f KB)"
          % (path.relative_to(ROOT), text.count("\n"), len(text) / 1024))
    print("  symbols: %d   skipped as mechanical: %s"
          % (len(used), ", ".join(skipped) if skipped else "none"))
    if xs:
        print("  sheet %s %.0f x %.0f mm, content to x %.0f y %.0f, "
              "%d off the page"
              % (PAPER, PAGE_W, PAGE_H, max(xs), max(ys), over))
    if args.check:
        return 0 if check(B, comps, nets, text, used) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
