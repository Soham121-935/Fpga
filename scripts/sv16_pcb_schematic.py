#!/usr/bin/env python3
"""Generate `sv16_board.kicad_sch` - the SV-16 schematic, from the board netlist.

There is one source of truth for this project's wiring, and it is
`scripts/sv16_board_kicad.py`: the same `COMPONENTS` / `CONNECTIONS` tables that
place the footprints and net the pads of `sv16_board.kicad_pcb` also produce
this schematic.  A net in the board file and a net here cannot disagree, because
neither is typed twice - and `--check` (run by `make lint` and `make pcb-check`)
fails if this file and that netlist ever drift apart.

How the drawing is made

  * every part becomes one symbol, drawn as a rectangle with its pins in
    numeric order (the QFP-144 splits its 144 pins evenly left and right, in
    reading order);
  * every pin gets a 2.54 mm wire stub with a **label carrying the net name** -
    in KiCad, two labels with the same name are the same net, so the whole
    board is wired by name.  That is deliberate: a generated point-to-point
    ratsnest drawing of 475 connections would be unreadable, while a labelled
    schematic is exactly what the fabricator and the reader need;
  * a pad with no net gets a **no-connect** marker instead of a stub, which is
    what keeps ERC quiet;
  * parts are grouped into the same ten blocks the connections document uses
    (power, FPGA, flash, USB, JTAG, expansion, LEDs, test, passives,
    mechanical), each with a frame and a heading.

Pin types are `passive` throughout, which is honest for a generated drawing:
nothing here knows whether a given pin is an input or an output, and a made-up
pin type is worse than none - it invents ERC errors that are not real.

Usage
    scripts/sv16_pcb_schematic.py              # write the schematic + preview
    scripts/sv16_pcb_schematic.py --check      # exit 1 if the file is stale
    scripts/sv16_pcb_schematic.py --quiet      # no chatter
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sv16_board_kicad as board      # noqa: E402

OUT = ROOT / "hardware" / "sv16_board"
SCH = OUT / "sv16_board.kicad_sch"
PREVIEW = OUT / "schematic_preview.png"
LPF = ROOT / "constraints" / "ecp5_144tqfp.lpf"

# ---- page and grid ---------------------------------------------------------
PAGE_W, PAGE_H = 841.0, 1189.0        # A0, in mm
MARGIN = 20.0
CELL_W, CELL_H = 52.0, 36.0           # the grid a part sits on
PIN_PITCH = 2.54
PIN_LEN = 2.54
STUB = 2.54                           # wire from the pin to its label
BODY_W = 15.24
LABEL_SIZE = 1.27

NAMESPACE = uuid.UUID("5f16b0a0-0000-4000-8000-000000000000")

#: the drawing order - the same ten blocks as PCB_CONNECTIONS.md
BAND_ORDER = ("power", "fpga", "flash", "usb", "jtag", "expansion",
              "leds", "test", "passives", "mech")

BAND_TITLE = {
    "power": "1. Power in and the three rails",
    "fpga": "2. The FPGA (U1) and its clock",
    "flash": "3. Configuration flash (U2) and application flash (U3)",
    "usb": "4. USB: connector, ESD and the bridge",
    "jtag": "5. JTAG, configuration and reset",
    "expansion": "6. Expansion and motor headers",
    "leds": "7. Status LEDs and their drivers",
    "test": "8. Test points",
    "passives": "9. Resistors, capacitors, inductors, diodes, transistors",
    "mech": "10. Mechanical: mounting holes and fiducials",
}

#: parts drawn large even by their pin count (the FPGA is the whole point)
BIG_PARTS = {"U1"}

#: up to this many pins a part is drawn as one vertical column, so its net
#: labels stack down one side instead of colliding in the middle
SINGLE_COLUMN_PINS = 6

POWER_NETS = ("GND", "3V3", "2V5", "1V1", "VM_IN", "VM_IN_RAW", "USB_VBUS", "5V_USB")


def q(text: str) -> str:
    """A KiCad quoted string."""
    return '"%s"' % str(text).replace("\\", "\\\\").replace('"', '\\"')


def uid(key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, "sv16/" + key))


def pad_sort_key(number: str):
    """Numeric pads first, in numeric order; then lettered ones (A1, B2, S1...)."""
    match = re.match(r"^([A-Za-z]*)(\d+)$", str(number))
    if match:
        prefix, digits = match.group(1), int(match.group(2))
        return (0 if prefix == "" else 1, prefix, digits, str(number))
    return (2, str(number), 0, str(number))


def lpf_pin_names() -> dict[str, str]:
    """Pin number -> port name, from the place-and-route constraints.

    The FPGA symbol uses these as pin names, so pin 133 reads `clk_25m` in the
    schematic exactly as it does in the LPF and in the board's pin table.
    """
    out: dict[str, str] = {}
    if not LPF.exists():
        return out
    for line in LPF.read_text().splitlines():
        match = re.match(r'\s*LOCATE\s+COMP\s+"([^"]+)"\s+SITE\s+"(\d+)"', line)
        if match:
            out[match.group(2)] = match.group(1)
    return out


# --------------------------------------------------------------------------- data
class Part:
    """One component, with the pins it actually has and the net each one is on."""

    __slots__ = ("ref", "library", "value", "group", "pins", "dnp", "body_w",
                 "body_h", "x", "y")

    def __init__(self, ref, library, value, group, pins, dnp):
        self.ref, self.library, self.value, self.group = ref, library, value, group
        self.pins = pins                    # [(number, net or None), ...]
        self.dnp = dnp
        self.x = self.y = 0.0
        if len(pins) <= SINGLE_COLUMN_PINS:
            rows = max(2, len(pins))
        else:
            rows = (len(pins) + 1) // 2
        self.body_w = BODY_W
        self.body_h = rows * PIN_PITCH + PIN_PITCH

    @property
    def cell_w(self) -> float:
        return self.body_w + 2 * (PIN_LEN + STUB + 14.0)

    @property
    def cell_h(self) -> float:
        return max(CELL_H, self.body_h + 12.0)

    def pin_positions(self):
        """(number, net, connection point, side) for every pin, top to bottom."""
        return [(number, net, (self.x + gx, self.y + gy), side)
                for number, net, (gx, gy), side in pin_geometry(self)]


def collect() -> list[Part]:
    nets = {(ref, str(pad)): net for ref, pad, net in board.CONNECTIONS}
    parts = []
    for ref, library, builder, value, group in board.COMPONENTS:
        pins = []
        for pad in board.pads_of(builder):
            number = str(pad.get("number", ""))
            if not number:
                continue                    # a pad with no number is not a pin
            pins.append((number, nets.get((ref, number))))
        pins.sort(key=lambda pair: pad_sort_key(pair[0]))
        parts.append(Part(ref, library, value, group, pins,
                          ref in board.DNP_REFS))
    parts.sort(key=lambda part: (BAND_ORDER.index(part.group)
                                 if part.group in BAND_ORDER else len(BAND_ORDER),
                                 part.ref))
    return parts


def layout(parts) -> float:
    """Lay the parts out band by band; return the page height actually used."""
    y = MARGIN + 16.0
    for band in BAND_ORDER:
        members = [part for part in parts if part.group == band]
        if not members:
            continue
        x = MARGIN
        y += 12.0                            # the band heading
        top = y
        row_h = 0.0
        for part in members:
            if part.ref in BIG_PARTS:
                if x > MARGIN:               # the FPGA gets its own row
                    x = MARGIN
                    y += row_h + 6.0
                    row_h = 0.0
                part.x = x + part.body_w / 2.0 + PIN_LEN
                part.y = y + part.body_h / 2.0
                x = MARGIN + part.cell_w
                row_h = max(row_h, part.cell_h)
                continue
            if x + part.cell_w > PAGE_W - MARGIN and x > MARGIN:
                x = MARGIN
                y += row_h + 6.0
                row_h = 0.0
            part.x = x + part.body_w / 2.0 + PIN_LEN
            part.y = y + part.body_h / 2.0
            x += part.cell_w
            row_h = max(row_h, part.cell_h)
        y += row_h + 18.0
    return y


# ------------------------------------------------------------------- the writer
def symbol_name(part: Part, taken: dict) -> str:
    """A stable library name for this part's shape (footprint + pin set)."""
    base = part.library.split(":")[-1] or part.group
    base = re.sub(r"[^A-Za-z0-9_.+-]", "_", base)
    key = (base, tuple(number for number, _net in part.pins))
    if key in taken:
        return taken[key]
    name = "SV16:%s" % base
    index = 2
    while name in taken.values():
        name = "SV16:%s_%d" % (base, index)
        index += 1
    taken[key] = name
    return name


def lib_symbol(name: str, part: Part) -> str:
    """The library half of a symbol: body, pins, default properties."""
    short = name.split(":")[1]
    lines = ['    (symbol %s (pin_names (offset 0.254) hide) (in_bom yes)'
             ' (on_board yes)' % q(name)]
    half = part.body_h / 2.0
    prefix = re.match(r"^[A-Za-z]+", part.ref)
    lines.append('      (property "Reference" %s (at 0 %.2f 0)'
                 ' (effects (font (size %.2f %.2f))))'
                 % (q(prefix.group(0) if prefix else "U"), half + 1.27,
                    LABEL_SIZE, LABEL_SIZE))
    lines.append('      (property "Value" %s (at 0 %.2f 0)'
                 ' (effects (font (size %.2f %.2f))))'
                 % (q(part.value or short), -half - 1.27, LABEL_SIZE, LABEL_SIZE))
    lines.append('      (property "Footprint" %s (at 0 0 0)'
                 ' (effects (font (size %.2f %.2f)) hide))'
                 % (q(part.library), LABEL_SIZE, LABEL_SIZE))
    lines.append('      (property "Datasheet" "" (at 0 0 0)'
                 ' (effects (font (size %.2f %.2f)) hide))'
                 % (LABEL_SIZE, LABEL_SIZE))
    lines.append('      (symbol %s' % q(short + "_0_1"))
    lines.append('        (rectangle (start %.2f %.2f) (end %.2f %.2f)'
                 ' (stroke (width 0.254) (type default)) (fill (type background)))'
                 % (-part.body_w / 2.0, half, part.body_w / 2.0, -half))
    lines.append('      )')
    lines.append('      (symbol %s' % q(short + "_1_1"))
    for number, point, side, name_text in _pins_with_geometry(part):
        lines.append('        (pin passive line (at %.2f %.2f %d) (length %.2f)'
                     % (point[0], point[1], 0 if side < 0 else 180, PIN_LEN))
        lines.append('          (name %s (effects (font (size %.2f %.2f))))'
                     % (q(name_text), LABEL_SIZE, LABEL_SIZE))
        lines.append('          (number %s (effects (font (size %.2f %.2f))))'
                     % (q(number), LABEL_SIZE, LABEL_SIZE))
        lines.append('        )')
    lines.append('      )')
    lines.append('    )')
    return "\n".join(lines)


def pin_geometry(part: Part):
    """[(number, net, (x, y), side)] in symbol coordinates, origin at the centre.

    Small parts are drawn as a single vertical column - a resistor or a
    capacitor with two pins at the same height would put its two net labels on
    top of each other.  Anything wider than six pins is split into two columns,
    first half down the left, second half down the right, which is how a QFP or
    a flash chip reads on paper.
    """
    count = len(part.pins)
    out = []
    if count <= SINGLE_COLUMN_PINS:
        for row, (number, net) in enumerate(part.pins):
            y = ((count - 1) / 2.0 - row) * PIN_PITCH
            out.append((number, net, (-(part.body_w / 2.0 + PIN_LEN), -y), -1))
        return out
    half = (count + 1) // 2
    for index, (number, net) in enumerate(part.pins):
        if index < half:
            row, side, rows = index, -1, half
        else:
            row, side, rows = index - half, 1, count - half
        y = ((rows - 1) / 2.0 - row) * PIN_PITCH
        x = side * (part.body_w / 2.0 + PIN_LEN)
        out.append((number, net, (x, -y), side))
    return out


def _pins_with_geometry(part: Part):
    """(number, point, side, name) in *symbol* coordinates (origin at 0, 0)."""
    names = lpf_pin_names() if part.ref == "U1" else {}
    return [(number, point, side, names.get(number, "~"))
            for number, _net, point, side in pin_geometry(part)]


def emit(parts, names, libs) -> str:
    taken: dict = {}
    lines: list[str] = []
    root = uid("root")
    lines.append("(kicad_sch (version 20230121) (generator sv16_pcb_schematic.py)")
    lines.append("")
    lines.append("  (uuid %s)" % q(root))
    lines.append("")
    lines.append('  (paper "A0")')
    lines.append("")
    lines.append("  (title_block")
    lines.append('    (title "SV-16 Rev B - ECP5 FPGA motor controller")')
    lines.append('    (rev "1.3")')
    lines.append('    (comment 1 "Generated from scripts/sv16_board_kicad.py - do not hand-edit.")')
    lines.append('    (comment 2 "%d parts, %d nets. Nets are carried by labels -'
                 ' the same name is the same net.")'
                 % (len(parts), len(board.NET_ORDER)))
    lines.append('    (comment 3 "Pin types are passive on purpose: this drawing knows'
                 ' what connects, not which way the signal goes.")')
    lines.append("  )")
    lines.append("")

    # ---- library ---------------------------------------------------------
    lines.append("  (lib_symbols")
    for name, part in libs:
        lines.append(lib_symbol(name, part))
    lines.append("  )")
    lines.append("")

    # ---- band frames and headings ---------------------------------------
    for band in BAND_ORDER:
        members = [part for part in parts if part.group == band]
        if not members:
            continue
        x0 = min(part.x - part.cell_w / 2.0 for part in members) - 4.0
        x1 = max(part.x + part.cell_w / 2.0 for part in members) + 4.0
        y0 = min(part.y - part.body_h / 2.0 for part in members) - 14.0
        y1 = max(part.y + part.body_h / 2.0 for part in members) + 8.0
        x0 = max(MARGIN - 8.0, x0)
        x1 = min(PAGE_W - MARGIN + 8.0, x1)
        lines.append("  (polyline (pts (xy %.2f %.2f) (xy %.2f %.2f) (xy %.2f %.2f)"
                     " (xy %.2f %.2f) (xy %.2f %.2f))" % (x0, y0, x1, y0, x1, y1, x0, y1, x0, y0))
        lines.append("    (stroke (width 0.254) (type default))")
        lines.append("    (uuid %s)" % q(uid("frame/" + band)))
        lines.append("  )")
        lines.append('  (text %s (at %.2f %.2f 0)' % (q(BAND_TITLE[band]), x0 + 2.0, y0 - 1.5))
        lines.append("    (effects (font (size 2.5 2.5) (thickness 0.5) bold) (justify left bottom))")
        lines.append("    (uuid %s)" % q(uid("heading/" + band)))
        lines.append("  )")
    lines.append("")

    # ---- notes -----------------------------------------------------------
    note = ("SV-16 Rev B schematic, generated from the same netlist as the PCB. "
            "Every pin has a stub and a net label; equal labels are the same net. "
            "Pads with no connection carry a no-connect cross.")
    lines.append("  (text %s (at %.2f %.2f 0)" % (q(note), MARGIN, MARGIN - 6.0))
    lines.append("    (effects (font (size 3 3)) (justify left bottom))")
    lines.append("    (uuid %s)" % q(uid("note/header")))
    lines.append("  )")
    lines.append("")

    # ---- wires, labels, no-connects --------------------------------------
    wires, labels, noconnects = [], [], []
    for part in parts:
        for number, net, point, side in part.pin_positions():
            px, py = point
            if net:
                far = (px - STUB, py) if side < 0 else (px + STUB, py)
                wires.append((px, py, far[0], far[1], part.ref, number))
                labels.append((net, far, side, part.ref, number))
            else:
                noconnects.append((px, py, part.ref, number))

    for (px, py, ref, number) in noconnects:
        lines.append("  (no_connect (at %.2f %.2f) (uuid %s))"
                     % (px, py, q(uid("nc/%s/%s" % (ref, number)))))
    lines.append("")
    for (x0, y0, x1, y1, ref, number) in wires:
        lines.append("  (wire (pts (xy %.2f %.2f) (xy %.2f %.2f))"
                     % (x0, y0, x1, y1))
        lines.append("    (stroke (width 0) (type solid)) (uuid %s)"
                     % q(uid("wire/%s/%s" % (ref, number))))
        lines.append("  )")
    lines.append("")
    for (net, (lx, ly), side, ref, number) in labels:
        if side < 0:
            lines.append('  (label %s (at %.2f %.2f 180) (fields_autoplaced)'
                         % (q(net), lx, ly))
            lines.append("    (effects (font (size %.2f %.2f)) (justify right bottom))"
                         % (LABEL_SIZE, LABEL_SIZE))
        else:
            lines.append('  (label %s (at %.2f %.2f 0) (fields_autoplaced)'
                         % (q(net), lx, ly))
            lines.append("    (effects (font (size %.2f %.2f)) (justify left bottom))"
                         % (LABEL_SIZE, LABEL_SIZE))
        lines.append("    (uuid %s)" % q(uid("label/%s/%s" % (ref, number))))
        lines.append("  )")
    lines.append("")

    # ---- the parts -------------------------------------------------------
    for part in parts:
        lines.append("  (symbol (lib_id %s) (at %.2f %.2f 0) (unit 1)"
                     % (q(names[part.ref]), part.x, part.y))
        lines.append("    (in_bom yes) (on_board yes) (dnp %s)"
                     % ("yes" if part.dnp else "no"))
        lines.append("    (uuid %s)" % q(uid("symbol/" + part.ref)))
        top = part.y - part.body_h / 2.0
        right = part.x + part.body_w / 2.0
        value = (part.value or "") + ("  (DNP)" if part.dnp else "")
        lines.append('    (property "Reference" %s (at %.2f %.2f 0)'
                     ' (effects (font (size %.2f %.2f)) (justify left)))'
                     % (q(part.ref), right + 1.0, top - 1.0, LABEL_SIZE, LABEL_SIZE))
        lines.append('    (property "Value" %s (at %.2f %.2f 0)'
                     ' (effects (font (size %.2f %.2f)) (justify left)))'
                     % (q(value), right + 1.0, top + 1.5, LABEL_SIZE, LABEL_SIZE))
        lines.append('    (property "Footprint" %s (at %.2f %.2f 0)'
                     ' (effects (font (size %.2f %.2f)) hide))'
                     % (q(part.library), part.x, part.y, LABEL_SIZE, LABEL_SIZE))
        lines.append('    (property "Datasheet" "" (at %.2f %.2f 0)'
                     ' (effects (font (size %.2f %.2f)) hide))'
                     % (part.x, part.y, LABEL_SIZE, LABEL_SIZE))
        for number, _net, _point, _side in part.pin_positions():
            lines.append("    (pin %s (uuid %s))"
                         % (q(number), q(uid("pin/%s/%s" % (part.ref, number)))))
        lines.append("    (instances")
        lines.append('      (project "sv16_board"')
        lines.append("        (path %s (reference %s) (unit 1))"
                     % (q("/" + root), q(part.ref)))
        lines.append("      )")
        lines.append("    )")
        lines.append("  )")
    lines.append("")

    lines.append('  (sheet_instances (path "/" (page "1")))')
    lines.append(")")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ read it back
def parse_sexpr(text: str):
    """A tiny S-expression reader - enough to prove the file is well formed."""
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()"]+', text)
    stack: list[list] = [[]]
    for token in tokens:
        if token == "(":
            stack.append([])
        elif token == ")":
            if len(stack) < 2:
                raise ValueError("unbalanced: too many ')'")
            node = stack.pop()
            stack[-1].append(node)
        else:
            stack[-1].append(token)
    if len(stack) != 1:
        raise ValueError("unbalanced: %d '(' left open" % (len(stack) - 1))
    return stack[0]


#: every element a schematic may contain at the top level.  Anything else is a
#: stray token - and a stray token is exactly how a file that "looks fine" makes
#: KiCad show an error and then a blank page, so it is a hard failure here.
TOP_LEVEL = {
    "version", "generator", "uuid", "paper", "title_block", "lib_symbols",
    "polyline", "text", "no_connect", "wire", "label", "symbol",
    "sheet_instances",
}


def verify(text: str, parts) -> list[str]:
    """Read the schematic back and check it against the netlist it came from."""
    problems = []
    try:
        tree = parse_sexpr(text)
    except ValueError as error:
        return ["the file does not parse: %s" % error]
    if len(tree) != 1 or not isinstance(tree[0], list):
        return ["the file is not one balanced (kicad_sch ...) expression"]
    root = tree[0]
    if not root or root[0] != "kicad_sch":
        return ["the file does not start with (kicad_sch ...)"]

    # structural: nothing but known elements, and every one of them a list
    for index, entry in enumerate(root[1:], start=1):
        if not isinstance(entry, list):
            problems.append("top level entry %d is a bare token %r, not an element"
                            % (index, entry))
        elif entry[0] not in TOP_LEVEL:
            problems.append("top level entry %d is %r, which is not a schematic element"
                            % (index, entry[0]))
    for entry in root[1:]:
        if isinstance(entry, list) and entry and entry[0] == "symbol" and \
                isinstance(entry[1], list) and entry[1][0] == "lib_id":
            continue
        if isinstance(entry, list) and entry and entry[0] == "symbol":
            problems.append("a symbol instance has no lib_id straight after it")
    if not any(isinstance(entry, list) and entry and entry[0] == "lib_symbols"
               for entry in root[1:]):
        problems.append("no lib_symbols block")
    else:
        block = next(entry for entry in root[1:]
                     if isinstance(entry, list) and entry and entry[0] == "lib_symbols")
        defined = [child[1] for child in block[1:]
                   if isinstance(child, list) and child and child[0] == "symbol"]
        repeated = {name for name in defined if defined.count(name) > 1}
        if repeated:
            problems.append("lib_symbols defines %d names more than once (e.g. %s)"
                            % (len(repeated), sorted(repeated)[0]))
        missing = {entry[1][1] for entry in root[1:]
                   if isinstance(entry, list) and entry and entry[0] == "symbol"
                   and isinstance(entry[1], list) and entry[1][0] == "lib_id"} - set(defined)
        if missing:
            problems.append("%d symbol instances use an undefined lib_id (e.g. %s)"
                            % (len(missing), sorted(missing)[0]))
    # KiCad's reader has no comment syntax in a schematic: a line starting with
    # ';;' or '#' is a parse error that shows up as "error, blank page"
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(";;") or stripped.startswith("//") \
                or stripped.startswith("#"):
            problems.append("line %d is a comment, which KiCad cannot read: %r"
                            % (number, stripped[:40]))

    # no duplicate uuids anywhere
    uuids = re.findall(r'\(uuid "([0-9a-f-]{36})"\)', text)
    duplicates = {value for value in uuids if uuids.count(value) > 1}
    if duplicates:
        problems.append("%d duplicate uuids (e.g. %s)"
                        % (len(duplicates), sorted(duplicates)[0]))

    def walk(node, name):
        for child in node:
            if isinstance(child, list) and child and child[0] == name:
                yield child

    instances = list(walk(root, "symbol"))
    lib_symbols = list(walk(root, "lib_symbols"))
    definitions = set()
    for block in lib_symbols:
        for symbol in walk(block, "symbol"):
            definitions.add(symbol[1])
    labels = [child[1].strip('"') for child in walk(root, "label")]
    labels = [name.replace('\\"', '"') for name in labels]
    noconnects = list(walk(root, "no_connect"))

    placed: dict[str, tuple[int, str]] = {}
    for instance in instances:
        lib_id = next((child[1] for child in instance if isinstance(child, list)
                       and child and child[0] == "lib_id"), None)
        if lib_id not in definitions:
            problems.append("%s uses a symbol that is not in lib_symbols" % lib_id)
        reference = None
        for child in walk(instance, "property"):
            if child[1] == '"Reference"':
                reference = child[2].strip('"')
        pins = [child[1].strip('"') for child in walk(instance, "pin")]
        placed[reference] = (len(pins), lib_id or "")
        if len(pins) != len(set(pins)):
            problems.append("%s repeats a pin number" % reference)

    expected_labels = 0
    expected_nc = 0
    expected_by_net: dict[str, int] = {}
    for part in parts:
        if part.ref not in placed:
            problems.append("%s is in the netlist but not in the schematic" % part.ref)
            continue
        count, lib_id = placed[part.ref]
        if count != len(part.pins):
            problems.append("%s has %d pins in the schematic, %d on the board"
                            % (part.ref, count, len(part.pins)))
        for _number, net in part.pins:
            if net:
                expected_labels += 1
                expected_by_net[net] = expected_by_net.get(net, 0) + 1
            else:
                expected_nc += 1
    if len(labels) != expected_labels:
        problems.append("%d labels for %d connected pins" % (len(labels), expected_labels))
    # per net, not just in total: a label that landed on the wrong pin would
    # keep the total right and short one net while padding another
    seen_by_net: dict[str, int] = {}
    for name in labels:
        seen_by_net[name] = seen_by_net.get(name, 0) + 1
    for net in sorted(set(expected_by_net) | set(seen_by_net)):
        want, got = expected_by_net.get(net, 0), seen_by_net.get(net, 0)
        if want != got:
            problems.append("net %s has %d labels in the schematic, %d pads on the board"
                            % (net, got, want))
    if len(noconnects) != expected_nc:
        problems.append("%d no-connects for %d unused pins" % (len(noconnects), expected_nc))
    if len(instances) != len(parts):
        problems.append("%d symbol instances for %d parts" % (len(instances), len(parts)))
    return problems


# ------------------------------------------------------------------- the preview
def write_preview(parts, path: Path) -> None:
    """A PNG of the same drawing, so it can be read without KiCad."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:                      # pragma: no cover - optional
        print("Pillow not installed: skipping %s" % path.name)
        return
    # 4 px per mm: a 2.54 mm pin pitch is 10 px, which is what makes a 1.27 mm
    # net label legible next to the pin above it
    scale = 4.0
    width = int(PAGE_W * scale)
    height = int((max(part.y + part.body_h for part in parts) + 30.0) * scale)
    image = Image.new("RGB", (width, height), (250, 250, 246))
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 10)
        big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
    except OSError:                          # pragma: no cover
        font = small = big = ImageFont.load_default()

    def xy(x, y):
        return (x * scale, y * scale)

    draw.text(xy(MARGIN, 2.0), "SV-16 Rev B - schematic (generated)", (20, 20, 20), font=big)

    for band in BAND_ORDER:
        members = [part for part in parts if part.group == band]
        if not members:
            continue
        x0 = max(MARGIN - 8.0, min(p.x - p.cell_w / 2.0 for p in members) - 4.0)
        y0 = min(p.y - p.body_h / 2.0 for p in members) - 14.0
        x1 = min(PAGE_W - MARGIN + 8.0, max(p.x + p.cell_w / 2.0 for p in members) + 4.0)
        y1 = max(p.y + p.body_h / 2.0 for p in members) + 8.0
        draw.rectangle([xy(x0, y0), xy(x1, y1)], outline=(150, 150, 145))
        draw.text(xy(x0 + 2, y0 - 12), BAND_TITLE[band], (30, 30, 90), font=font)

    for part in parts:
        half_w, half_h = part.body_w / 2.0, part.body_h / 2.0
        draw.rectangle([xy(part.x - half_w, part.y - half_h),
                        xy(part.x + half_w, part.y + half_h)],
                       fill=(255, 255, 255), outline=(60, 60, 60))
        draw.text(xy(part.x + half_w + 1, part.y - half_h - 3), part.ref,
                  (0, 0, 0), font=font)
        for number, net, point, side in part.pin_positions():
            px, py = point
            if not net:
                s = 0.8
                draw.line([xy(px - s, py - s), xy(px + s, py + s)], fill=(190, 60, 60))
                draw.line([xy(px - s, py + s), xy(px + s, py - s)], fill=(190, 60, 60))
                continue
            far = far_x = px - STUB if side < 0 else px + STUB
            draw.line([xy(px, py), xy(far_x, py)], fill=(40, 90, 160))
            anchor = "rd" if side < 0 else "ld"
            draw.text(xy(far_x, py - 1.0), net, (20, 60, 20), font=small, anchor=anchor)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print("wrote %s" % path.relative_to(ROOT))


# ------------------------------------------------------------------------ main
def build() -> tuple[str, list[Part]]:
    parts = collect()
    layout(parts)
    taken: dict = {}
    names = {part.ref: symbol_name(part, taken) for part in parts}
    # one definition per distinct symbol: two parts that share a footprint and
    # pin set share the drawing, and lib_symbols may not define a name twice
    libs: list[tuple[str, Part]] = []
    seen_names = set()
    for part in parts:
        name = names[part.ref]
        if name in seen_names:
            continue
        seen_names.add(name)
        libs.append((name, part))
    return emit(parts, names, libs), parts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the schematic on disk is stale")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    text, parts = build()
    problems = verify(text, parts)
    for line in problems[:20]:
        print("  PROBLEM: " + line)

    pins = sum(len(part.pins) for part in parts)
    nets = {(part.ref, number): net for part in parts
            for number, net in part.pins if net}
    if args.check:
        if not SCH.exists() or SCH.read_text() != text:
            print("FAIL: %s is stale - run make schematic" % SCH.name)
            return 1
        if problems:
            print("FAIL: %s is current but not well formed" % SCH.name)
            return 1
        print("%s is current (%d parts, %d pins, %d nets)"
              % (SCH.name, len(parts), pins, len(set(nets.values()))))
        return 0

    SCH.write_text(text)
    if not args.quiet:
        print("wrote %s (%d parts, %d pins, %d labels, %.0f KB)"
              % (SCH.relative_to(ROOT), len(parts), pins, len(nets), len(text) / 1024.0))
        for band in BAND_ORDER:
            members = [part for part in parts if part.group == band]
            if members:
                print("  %-10s %3d parts" % (band, len(members)))
    write_preview(parts, PREVIEW)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
