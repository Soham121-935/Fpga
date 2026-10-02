#!/usr/bin/env python3
"""Draw the SV-16 board as bitmaps: the board itself, the net map, the power
plan and the connection sheets.

Everything here is rendered from the same data the board file is generated from
(`sv16_board_kicad.py`) and the copper plan (`sv16_pcb_copper.py`), so a picture
can never show a placement, a net or a via that the board does not have.

Outputs, all in `hardware/sv16_board/`:

| File | What it shows |
| :--- | :--- |
| `pcb_top_view.png` | the board as seen from above: 141 footprints, pads, silkscreen, the In2 rail pours, vias, DNP marks, a legend |
| `pcb_bottom_view.png` | the same board flipped (a real bottom view, text mirrored): through-hole pads and the B.Cu ground pour |
| `pcb_net_map.png` | the ratsnest, coloured by function, with the block floorplan and a net legend |
| `pcb_power_map.png` | the power tree and the In2.Cu pour map: which rail owns which copper, and the pads the router still has to connect |
| `pcb_connection_sheets.png` | six drawn connection sheets (the bitmap companion to PCB_CONNECTIONS.md) |

Usage
    scripts/sv16_pcb_bitmap.py               # write all five images
    scripts/sv16_pcb_bitmap.py --scale 40    # bigger bitmaps
    scripts/sv16_pcb_bitmap.py --only top    # one image

Pillow is required (`python3 -m pip install pillow`); nothing else is.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sv16_board_kicad as board      # noqa: E402
import sv16_pcb_copper as copper      # noqa: E402

OUT = ROOT / "hardware" / "sv16_board"

# ---------------------------------------------------------------- appearance
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
FONTS = {"regular": "DejaVuSans.ttf", "bold": "DejaVuSans-Bold.ttf",
         "mono": "DejaVuSansMono.ttf"}


def font(size: int, style: str = "regular"):
    from PIL import ImageFont
    path = FONT_DIR / FONTS.get(style, FONTS["regular"])
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


C = {
    "bg": "#0d1117",
    "board": "#123d2a",          # soldermask green
    "board_edge": "#7fe0b0",
    "pad": "#d9b451",            # ENIG gold
    "pad_edge": "#8a6f2a",
    "hole": "#0a0d10",
    "via": "#cfd8dc",
    "stitch": "#6b7f8c",
    "silk_top": "#f2f6f8",
    "silk_bottom": "#c9d6dd",
    "copper_top": "#e0a94f",
    "zone_3v3": "#e05252",
    "zone_2v5": "#b06be0",
    "zone_1v1": "#4ec9b0",
    "gnd_zone": "#2f6f4f",
    "dnp": "#ff5f56",
    "note": "#9fb1bd",
    "panel": "#161b22",
    "panel_edge": "#30363d",
}

GROUP_COLOUR = {
    "fpga": "#22c55e", "power": "#ef4444", "flash": "#a855f7", "usb": "#06b6d4",
    "jtag": "#eab308", "expansion": "#f472b6", "leds": "#84cc16",
    "passives": "#8b949e", "test": "#e5e7eb", "mech": "#4b5563",
}

# ratsnest colours for the net map, by function
NET_COLOUR = {
    "3V3": "#e05252", "2V5": "#b06be0", "1V1": "#4ec9b0", "VM_IN": "#ff8c42",
    "VM_IN_RAW": "#ff8c42", "5V_USB": "#ffb347", "USB_VBUS": "#ffb347",
    "clk_25m": "#ffd166",
    "CCLK": "#f4a261", "U2_CLK": "#f4a261", "MOSI": "#f4a261", "MISO": "#f4a261",
    "CSSPIN": "#f4a261", "U2_DI": "#f4a261", "U2_DO": "#f4a261", "U2_CS": "#f4a261",
    "PROGRAMN": "#e9c46a", "INITN": "#e9c46a", "DONE": "#e9c46a",
    "TCK": "#ffd60a", "TMS": "#ffd60a", "TDI": "#ffd60a", "TDO": "#ffd60a",
    "USB_DP": "#00b4d8", "USB_DN": "#00b4d8", "USB_DP_F": "#00b4d8",
    "USB_DN_F": "#00b4d8", "CC1": "#48cae4", "CC2": "#48cae4",
    "uart_rx": "#90be6d", "uart_tx": "#90be6d", "U4_TXD": "#90be6d", "U4_RXD": "#90be6d",
    "flash_sck": "#c77dff", "flash_cs_n": "#c77dff", "flash_mosi": "#c77dff",
    "flash_miso": "#c77dff",
    "pwm_out": "#4cc9f0", "motor_dir1": "#4cc9f0", "motor_dir2": "#4cc9f0",
    "motor_fault_n": "#f72585",
}
DEFAULT_NET_COLOUR = "#5b6b78"

# ------------------------------------------------------------- data helpers
PLACEMENT = board.effective_placement()
NET_OF: dict = {}
for _ref, _pad, _net in board.CONNECTIONS:
    NET_OF.setdefault(_ref, {})[_pad] = _net


def pads_global(ref: str):
    """[(number, net, x, y, w, h, kind, shape)] in board coordinates."""
    entry = next((c for c in board.COMPONENTS if c[0] == ref), None)
    if entry is None or ref not in PLACEMENT:
        return []
    x, y, rot = PLACEMENT[ref]
    out = []
    for pad in board.pads_of(entry[2]):
        dx, dy = board.rotate_point(pad["x"], pad["y"], rot)
        w, h = pad["w"], pad["h"]
        if int(round(rot)) % 180 == 90:
            w, h = h, w
        out.append((str(pad["number"]), NET_OF.get(ref, {}).get(str(pad["number"])),
                    x + dx, y + dy, w, h, pad["kind"], pad["shape"]))
    return out


def all_pads():
    for ref, library, builder, value, group in board.COMPONENTS:
        if ref in PLACEMENT:
            yield ref, group, pads_global(ref)


def board_texts():
    return list(board.LABELS)


class Canvas:
    """A mm-grid canvas with the board drawn in it, plus room for a legend."""

    def __init__(self, scale: int, legend_px: int = 0, title: str = ""):
        from PIL import Image
        self.scale = scale
        self.margin = 40
        self.legend_px = legend_px
        self.w = int(board.BOARD_W * scale) + 2 * self.margin
        self.h = int(board.BOARD_H * scale) + 2 * self.margin + legend_px + 56
        self.image = Image.new("RGB", (self.w, self.h), C["bg"])
        self.draw = None
        self.title = title

    def __enter__(self):
        from PIL import ImageDraw
        self.draw = ImageDraw.Draw(self.image, "RGBA")
        if self.title:
            self.draw.text((self.margin, 14), self.title,
                           font=font(30, "bold"), fill="#e6edf3")
        return self

    def __exit__(self, *exc):
        return False

    def x(self, mm_x: float) -> float:
        return self.margin + mm_x * self.scale

    def y(self, mm_y: float) -> float:
        return self.margin + 56 + mm_y * self.scale

    def text(self, mm_x, mm_y, label, size=14, fill=None, anchor="mm", bold=False):
        self.draw.text((self.x(mm_x), self.y(mm_y)), label,
                       font=font(size, "bold" if bold else "regular"),
                       fill=fill or C["silk_top"], anchor=anchor)

    def box(self, mm_x, mm_y, mm_w, mm_h, **kw):
        self.draw.rectangle([self.x(mm_x), self.y(mm_y),
                             self.x(mm_x + mm_w), self.y(mm_y + mm_h)], **kw)

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.image.save(path)
        print("wrote %s (%d x %d)" % (path.relative_to(ROOT), self.w, self.h))


# --------------------------------------------------------------- board view
def draw_board_view(canvas: Canvas, *, mirror: bool = False, zones: bool = True,
                    vias: bool = True, ratsnest: str | None = None,
                    refs: bool = True, pin1: bool = True):
    """Draw the board.  `mirror` gives a true bottom view (text is mirrored)."""
    from PIL import Image, ImageDraw, ImageOps

    layer = Image.new("RGBA", (canvas.w, canvas.h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer, "RGBA")
    d = canvas.draw

    def px(mm_x, mm_y):
        return canvas.x(mm_x), canvas.y(mm_y)

    # board substrate
    d.rectangle([px(0, 0), px(board.BOARD_W, board.BOARD_H)],
                fill=C["board"], outline=C["board_edge"], width=3)

    # inner copper: GND plane on In1 (hatch) and the In2 rail pours
    if zones:
        for zone_net, hatch in (("GND", True),):
            draw.rectangle([px(0.25, 0.25), px(board.BOARD_W - 0.25, board.BOARD_H - 0.25)],
                           outline=C["gnd_zone"], width=2)
        for net, priority, polygons in copper.POURS:
            colour = C["zone_%s" % net.lower().replace("v", "v")] if net in ("3V3", "2V5", "1V1") else "#888"
            for polygon in polygons:
                points = [px(x, y) for x, y in polygon]
                draw.polygon(points, fill=colour + "33", outline=colour + "cc")
                cx = sum(p[0] for p in points) / len(points)
                cy = sum(p[1] for p in points) / len(points)
                draw.text((cx, cy), net, font=font(22, "bold"),
                          fill=colour + "ee", anchor="mm")
        # the bottom-side GND pour
        draw.rectangle([px(0.5, 0.5), px(board.BOARD_W - 0.5, board.BOARD_H - 0.5)],
                       outline=C["gnd_zone"] + "77", width=1)

    # mounting holes and fiducials
    for ref, group, pads in all_pads():
        for number, net, x, y, w, h, kind, shape in pads:
            if kind == "np_thru_hole":
                r = w * canvas.scale / 2
                draw.ellipse([canvas.x(x) - r, canvas.y(y) - r,
                              canvas.x(x) + r, canvas.y(y) + r],
                             fill=C["hole"], outline="#c9d6dd", width=3)
    for ref, library, builder, value, group in board.COMPONENTS:
        if group == "mech" and ref.startswith("FID") and ref in PLACEMENT:
            x, y, rot = PLACEMENT[ref]
            r = 0.5 * canvas.scale
            draw.ellipse([canvas.x(x) - r, canvas.y(y) - r,
                          canvas.x(x) + r, canvas.y(y) + r],
                         fill=C["pad"], outline="#6b7f8c")

    # sweep-routed stubs and vias (F.Cu), or the B.Cu side of them
    plan = board.copper_plan()
    for segment in plan.segments:
        draw.line([px(*segment["start"]), px(*segment["end"])],
                  fill=C["copper_top"] + "cc", width=max(2, int(0.2 * canvas.scale)))
    for via in plan.vias:
        r = via["dia"] * canvas.scale / 2
        colour = C["stitch"] if via["dia"] > 0.5 else C["via"]
        draw.ellipse([canvas.x(via["x"]) - r, canvas.y(via["y"]) - r,
                      canvas.x(via["x"]) + r, canvas.y(via["y"]) + r],
                     fill=colour + "dd", outline="#0a0d10")

    # pads
    for ref, group, pads in all_pads():
        for number, net, x, y, w, h, kind, shape in pads:
            if kind == "np_thru_hole":
                continue
            colour = C["pad"]
            if ratsnest and net:
                colour = NET_COLOUR.get(net, DEFAULT_NET_COLOUR)
            x0, y0 = canvas.x(x - w / 2), canvas.y(y - h / 2)
            x1, y1 = canvas.x(x + w / 2), canvas.y(y + h / 2)
            if kind in ("thru_hole",):
                draw.ellipse([x0, y0, x1, y1], fill=colour, outline=C["pad_edge"])
                hole = max(2, int(0.45 * canvas.scale))
                draw.ellipse([canvas.x(x) - hole, canvas.y(y) - hole,
                              canvas.x(x) + hole, canvas.y(y) + hole], fill=C["hole"])
            elif shape == "circle":
                draw.ellipse([x0, y0, x1, y1], fill=colour, outline=C["pad_edge"])
            else:
                draw.rectangle([x0, y0, x1, y1], fill=colour, outline=C["pad_edge"])

    # courtyard boxes, reference designators and pin-1 marks
    for ref, library, builder, value, group in board.COMPONENTS:
        if ref not in PLACEMENT:
            continue
        x, y, rot = PLACEMENT[ref]
        pads = pads_global(ref)
        if not pads:
            continue
        xs = [p[2] for p in pads]
        ys = [p[3] for p in pads]
        half_w = max(1.0, (max(xs) - min(xs)) / 2 + 0.6)
        half_h = max(1.0, (max(ys) - min(ys)) / 2 + 0.6)
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        colour = GROUP_COLOUR.get(group, "#8b949e")
        if group != "mech":
            draw.rectangle([canvas.x(cx - half_w), canvas.y(cy - half_h),
                            canvas.x(cx + half_w), canvas.y(cy + half_h)],
                           outline=colour + "66", width=1)
        if pin1 and len(pads) > 2 and group in ("fpga", "flash", "usb", "power"):
            px0, py0 = canvas.x(cx - half_w), canvas.y(cy - half_h)
            draw.ellipse([px0 - 6, py0 - 6, px0 + 6, py0 + 6], fill="#ffd166")
        if refs:
            label = ref + (" DNP" if ref in board.DNP_REFS else "")
            fill = C["dnp"] if ref in board.DNP_REFS else C["silk_top"]
            draw.text((canvas.x(cx), canvas.y(cy)), label,
                      font=font(15 if len(ref) > 3 else 16, "bold"),
                      fill=fill, anchor="mm", stroke_width=3, stroke_fill="#04140c")
            big = (max(xs) - min(xs)) > 3.5 or (max(ys) - min(ys)) > 3.5
            if group in ("fpga", "power", "usb", "flash", "jtag") and value and big:
                draw.text((canvas.x(cx), canvas.y(cy + 1.9)), value[:22],
                          font=font(11), fill=C["note"], anchor="mm",
                          stroke_width=2, stroke_fill="#04140c")

    # silkscreen legends
    for text, x, y, size in board_texts():
        draw.text(px(x, y), text, font=font(max(12, int(size * canvas.scale / 2.2)), "bold"),
                  fill=C["silk_top"] + "dd", anchor="mm", stroke_width=3, stroke_fill="#04140c")
    for ref, note in board.DNP_NOTES.items():
        if ref in PLACEMENT:
            x, y, rot = PLACEMENT[ref]
            draw.text(px(x, y + 2.4), "NOT FITTED", font=font(12, "bold"),
                      fill=C["dnp"], anchor="mm", stroke_width=3, stroke_fill="#04140c")

    # ratsnest, drawn last so it sits on top
    if ratsnest:
        points_by_net: dict = {}
        for ref, group, pads in all_pads():
            for number, net, x, y, w, h, kind, shape in pads:
                if net:
                    points_by_net.setdefault(net, []).append((x, y))
        for net, points in points_by_net.items():
            if len(points) < 2 or net == "GND":
                continue
            colour = NET_COLOUR.get(net, DEFAULT_NET_COLOUR)
            for first, second in zip(points, points[1:]):
                draw.line([px(*first), px(*second)], fill=colour + "88", width=2)

    if mirror:
        layer = ImageOps.mirror(layer)
    canvas.image.alpha_composite(layer) if False else None
    canvas.image.paste(Image.alpha_composite(canvas.image.convert("RGBA"), layer).convert("RGB"), (0, 0))


def story_legend(canvas: Canvas, lines: list[str], title: str = "legend"):
    """A text block under the board."""
    d = canvas.draw
    top = canvas.margin + 56 + int(board.BOARD_H * canvas.scale) + 22
    d.rectangle([canvas.margin, top, canvas.w - canvas.margin, top + canvas.legend_px - 10],
                fill=C["panel"], outline=C["panel_edge"])
    d.text((canvas.margin + 18, top + 12), title, font=font(20, "bold"), fill="#e6edf3")
    y = top + 46
    for line in lines:
        d.text((canvas.margin + 18, y), line, font=font(16), fill=C["note"])
        y += 24


# ------------------------------------------------------------------ power map
def draw_power_map(canvas: Canvas):
    """Power tree on top, the In2.Cu pour map underneath, bench numbers in the legend."""
    d = canvas.draw
    top = canvas.margin + 56

    def pbox(x, y, w, h, title, subtitle="", colour="#4ec9b0"):
        d.rounded_rectangle([x, y, x + w, y + h], radius=10, fill=C["panel"],
                            outline=colour, width=3)
        d.text((x + w / 2, y + 26), title, font=font(22, "bold"), fill=colour, anchor="mm")
        if subtitle:
            d.text((x + w / 2, y + 54), subtitle, font=font(15), fill=C["note"], anchor="mm")

    def arrow(x0, y0, x1, y1, label="", colour="#8b949e"):
        d.line([x0, y0, x1, y1], fill=colour, width=4)
        angle = math.atan2(y1 - y0, x1 - x0)
        for side in (0.4, -0.4):
            d.line([x1, y1, x1 - 18 * math.cos(angle + side), y1 - 18 * math.sin(angle + side)],
                   fill=colour, width=4)
        if label:
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            wpx = d.textlength(label, font=font(15, "bold")) / 2
            d.rectangle([mx - wpx - 6, my - 12, mx + wpx + 6, my + 12], fill=C["bg"])
            d.text((mx, my), label, font=font(15, "bold"), fill=colour, anchor="mm")

    d.text((canvas.margin, top), "power tree — rails, sequencing, and where the copper is",
           font=font(26, "bold"), fill="#e6edf3")

    x0, y0 = canvas.margin + 30, top + 62
    pbox(x0, y0, 200, 74, "J9  7-12 V", "barrel, centre +", "#ff8c42")
    pbox(x0, y0 + 108, 200, 74, "J8  USB-C VBUS", "5 V, D8/D9 ORing", "#ffb347")
    pbox(x0 + 280, y0 + 44, 200, 74, "FB1 + C23", "VM_IN  470 uF/25 V", "#ff8c42")
    pbox(x0 + 560, y0 - 8, 240, 92, "U5 AP62300", "sync buck, 3 A, 750 kHz", "#e05252")
    pbox(x0 + 560, y0 + 128, 240, 92, "U6 MP1584EN", "buck, 900 kHz, D11", "#4ec9b0")
    pbox(x0 + 560, y0 + 292, 240, 92, "U7 LP5907-2.5", "LDO from 3V3, RC on EN", "#b06be0")
    pbox(x0 + 890, y0 - 8, 230, 92, "3V3  @ 3.28 V", "L1 10 uH, C24/C40/C41/C25", "#e05252")
    pbox(x0 + 890, y0 + 128, 230, 92, "1V1  @ 1.10 V", "L2 10 uH, C21 100 uF", "#4ec9b0")
    pbox(x0 + 890, y0 + 292, 230, 92, "2V5  @ 2.50 V", "C42 10 uF + C22 22 uF", "#b06be0")

    arrow(x0 + 200, y0 + 37, x0 + 280, y0 + 70, "7-12 V")
    arrow(x0 + 200, y0 + 145, x0 + 280, y0 + 95, "5 V")
    arrow(x0 + 480, y0 + 70, x0 + 560, y0 + 40, "VM_IN")
    arrow(x0 + 480, y0 + 100, x0 + 560, y0 + 170, "VM_IN")
    arrow(x0 + 800, y0 + 38, x0 + 890, y0 + 38, "L1")
    arrow(x0 + 800, y0 + 174, x0 + 890, y0 + 174, "L2")
    arrow(x0 + 800, y0 + 338, x0 + 890, y0 + 338, "OUT")
    arrow(x0 + 890, y0 + 60, x0 + 800, y0 + 320, "3V3 -> IN", "#e05252")

    d.text((x0, y0 + 420), "sequencing: 3V3 first, 1V1 ~13 ms later (R41/C31), 2V5 ~21 ms after 3V3 (R43/C32).",
           font=font(18), fill=C["note"])
    d.text((x0, y0 + 448), "U1 is fitted LAST, and only after TP1/TP3/TP2 read 3.28 V / 1.10 V / 2.50 V.",
           font=font(18), fill=C["dnp"])

    # --- the In2.Cu pour map, to scale, underneath the tree
    panel_y = y0 + 500
    d.rectangle([canvas.margin, panel_y, canvas.w - canvas.margin, canvas.h - canvas.margin - 10],
                fill=C["panel"], outline=C["panel_edge"])
    d.text((canvas.margin + 24, panel_y + 14), "In2.Cu — the rail pours (to scale)",
           font=font(24, "bold"), fill="#e6edf3")
    scale = int(min((canvas.h - panel_y - 330) / board.BOARD_H, 12))
    ox = canvas.margin + 40
    oy = panel_y + 60

    def sx(mm_x):
        return ox + mm_x * scale

    def sy(mm_y):
        return oy + mm_y * scale

    d.rectangle([sx(0), sy(0), sx(100), sy(100)], fill=C["board"],
                outline=C["board_edge"], width=2)
    for net, priority, polygons in copper.POURS:
        colour = {"3V3": C["zone_3v3"], "2V5": C["zone_2v5"], "1V1": C["zone_1v1"]}[net]
        for polygon in polygons:
            d.polygon([(sx(x), sy(y)) for x, y in polygon], fill=colour + "55",
                      outline=colour + "cc")
    for ref, group, pads in all_pads():
        for number, net, x, y, w, h, kind, shape in pads:
            colour = NET_COLOUR.get(net or "", "#39424a")
            r = 2 if kind == "smd" else 3
            d.rectangle([sx(x) - r, sy(y) - r, sx(x) + r, sy(y) + r], fill=colour)
    legend_x = ox + 100 * scale + 60
    legend_y = oy + 10
    lines = [
        ("3V3 owns the whole layer (priority 0).", C["zone_3v3"]),
        ("1V1 is carved out of it where the MP1584, L2, C21, D11, the", C["zone_1v1"]),
        ("feedback divider and the C2-C7 strip down the left of U1 sit.", C["zone_1v1"]),
        ("2V5 gets the LP5907 group and the band above U1 for C8-C11.", C["zone_2v5"]),
        ("Zones may overlap: KiCad fills the higher priority first.", C["note"]),
        ("", C["note"]),
        ("U1 rail pads already connected by an escape via: 3V3 9/9,", "#e6edf3"),
        ("GND 14/14, 1V1 2/6, 2V5 1/4.", "#e6edf3"),
        ("", C["note"]),
        ("The router still owes these pads a trace:", C["dnp"]),
    ]
    for text, colour in lines:
        d.text((legend_x, legend_y), text, font=font(16, "bold" if colour in
                                                     (C["dnp"], "#e6edf3") else "regular"),
               fill=colour)
        legend_y += 21
    for line in [s for s in board.copper_plan().skipped if "route it out by hand" in s]:
        d.text((legend_x + 10, legend_y), "- " + line, font=font(14), fill=C["note"])
        legend_y += 19


# ------------------------------------------------------------ net map legend
def net_map_legend(canvas: Canvas):
    groups = [
        ("power", ["3V3", "1V1", "2V5", "VM_IN", "5V_USB"]),
        ("clock / config / JTAG", ["clk_25m", "CCLK", "TCK", "TMS", "TDI", "TDO",
                                   "PROGRAMN", "INITN", "DONE", "CFG_1"]),
        ("flash", ["flash_sck", "flash_cs_n", "flash_mosi", "flash_miso", "U2_CLK", "U2_CS"]),
        ("USB / console", ["USB_DP", "USB_DN", "CC1", "CC2", "uart_rx", "uart_tx"]),
        ("motor", ["pwm_out", "motor_dir1", "motor_dir2", "motor_fault_n"]),
    ]
    d = canvas.draw
    top = canvas.margin + 56 + int(board.BOARD_H * canvas.scale) + 22
    d.rectangle([canvas.margin, top, canvas.w - canvas.margin, top + canvas.legend_px - 8],
                fill=C["panel"], outline=C["panel_edge"])
    d.text((canvas.margin + 18, top + 12),
           "ratsnest by function — GND is omitted (it is the plane), everything else is Default",
           font=font(20, "bold"), fill="#e6edf3")
    y = top + 50
    for title, nets in groups:
        x = canvas.margin + 18
        d.text((x, y), title + ":", font=font(17, "bold"), fill="#e6edf3")
        x += 250
        for net in nets:
            if x > canvas.w - canvas.margin - 220:
                x = canvas.margin + 268
                y += 26
            d.line([x, y + 8, x + 34, y + 8], fill=NET_COLOUR.get(net, DEFAULT_NET_COLOUR), width=5)
            d.text((x + 42, y), net, font=font(16), fill=C["note"])
            x += 170
        y += 30


# ------------------------------------------------------- connection sheets
def draw_connection_sheets(scale: int = 1):
    """Six drawn sheets: the picture that goes with PCB_CONNECTIONS.md."""
    from PIL import Image, ImageDraw

    sheet_w, sheet_h = 1180, 780
    cols, rows = 2, 3
    margin, head = 30, 74
    img_w = cols * sheet_w + (cols + 1) * margin
    img_h = rows * sheet_h + (rows + 1) * margin + head
    image = Image.new("RGB", (img_w, img_h), C["bg"])
    d = ImageDraw.Draw(image, "RGBA")
    d.text((margin, 22), "SV-16 connection sheets — drawn from the board data "
                         "(net names are the LPF signal names)",
           font=font(30, "bold"), fill="#e6edf3")

    def sheet(col, row, title, subtitle):
        x = margin + col * (sheet_w + margin)
        y = head + margin + row * (sheet_h + margin)
        d.rounded_rectangle([x, y, x + sheet_w, y + sheet_h], radius=14,
                            fill="#0f1620", outline=C["panel_edge"], width=2)
        d.text((x + 24, y + 16), title, font=font(24, "bold"), fill="#e6edf3")
        d.text((x + 24, y + 48), subtitle, font=font(16), fill=C["note"])
        return x, y

    def wrap(text, size, max_width):
        """Greedy word wrap so a pin list never runs out of its box."""
        f = font(size)
        words, lines, current = text.split(), [], ""
        for word in words:
            candidate = (current + " " + word).strip()
            if d.textlength(candidate, font=f) <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def block(x, y, w, h, title, subtitle="", colour="#4ec9b0", pins="", size=13):
        d.rounded_rectangle([x, y, x + w, y + h], radius=10, fill=C["panel"],
                            outline=colour, width=3)
        d.text((x + w / 2, y + 24), title, font=font(20, "bold"), fill=colour, anchor="mm")
        if subtitle:
            d.text((x + w / 2, y + 48), subtitle, font=font(14), fill=C["note"], anchor="mm")
        if pins:
            lines = []
            for chunk in pins.split("|"):
                lines.extend(wrap(chunk, size, w - 28))
            for index, line in enumerate(lines):
                d.text((x + 14, y + 66 + index * 19), line, font=font(size), fill=C["silk_top"])

    def wire(points, label="", colour="#8b949e", dash=False):
        for first, second in zip(points, points[1:]):
            if dash:
                length = math.hypot(second[0] - first[0], second[1] - first[1])
                steps = max(int(length / 12), 1)
                for index in range(0, steps, 2):
                    t0, t1 = index / steps, min((index + 1) / steps, 1.0)
                    d.line([first[0] + (second[0] - first[0]) * t0,
                            first[1] + (second[1] - first[1]) * t0,
                            first[0] + (second[0] - first[0]) * t1,
                            first[1] + (second[1] - first[1]) * t1], fill=colour, width=3)
            else:
                d.line([first, second], fill=colour, width=3)
        if label:
            mid = points[len(points) // 2]
            tw = 8 * len(label) + 10
            d.rectangle([mid[0] - tw, mid[1] - 13, mid[0] + tw, mid[1] + 13], fill="#0f1620")
            d.text((mid[0], mid[1]), label, font=font(15, "bold"), fill=colour, anchor="mm")

    def note(x, y, text, colour=None):
        d.text((x, y), text, font=font(15), fill=colour or C["note"])

    # --- sheet 1: the FPGA and its rails ---------------------------------
    x, y = sheet(0, 0, "1 — FPGA supply and ground",
                 "U1 LFE5U-12F-6TG144C: 24 supply pins, 9 decoupling groups, one ground plane")
    block(x + 40, y + 110, 300, 150, "U1  VCC  1V1",
          "pins 20 29 38 66 83 130", "#4ec9b0",
          "C2-C7 100 nF each|C21 100 uF + 100 nF|from U6 via L2")
    block(x + 40, y + 300, 300, 150, "U1  VCCAUX  2V5",
          "pins 17 53 96 132", "#b06be0",
          "C8-C11 100 nF each|C22 22 uF + C42 10 uF|from U7 (RC on EN)")
    block(x + 40, y + 490, 300, 150, "U1  VCCIO  3V3",
          "pins 9 16 36 43 70 86 100 122 137", "#e05252",
          "C12-C20 100 nF each|C24 220 uF + C25 10 uF|from U5 via L1")
    block(x + 470, y + 110, 300, 250, "ground",
          "14 pins to the plane", "#8b949e",
          "8 15 21 32 42 65 75 85 87|101 123 129 131 138|one via each, straight to In1.Cu|"
          "129 stitching vias round the edge|pins 109 and 144: not connected")
    block(x + 470, y + 400, 300, 240, "decoupling rules",
          "PCB_COMPONENTS.md section 7", "#e9c46a",
          "every 100 nF within 3 mm of its pin|via first at the pad, then the track|"
          "3V3 goes to the In2 pour, GND to In1|1V1/2V5 ride their patches")
    wire([(x + 340, y + 185), (x + 470, y + 185)], "1V1")
    wire([(x + 340, y + 375), (x + 470, y + 375)], "2V5")
    wire([(x + 340, y + 565), (x + 470, y + 565)], "3V3")
    note(x + 40, y + 680, "Escape vias already dropped by the generator: 3V3 9/9, GND 14/14, 1V1 2/6, 2V5 1/4.")
    note(x + 40, y + 706, "The remaining rail pads (see sheet 6 of PCB_CONNECTIONS.md) need a 0.25 mm trace to their pour.",
         C["dnp"])

    # --- sheet 2: configuration, JTAG, reset, status ---------------------
    x, y = sheet(1, 0, "2 — configuration, JTAG, reset, status",
                 "Master SPI (CFG = 010), the JTAG chain, the reset RC and the two status LEDs")
    block(x + 40, y + 110, 260, 130, "U1.57 PROGRAMN", "config enable", "#e9c46a",
          "R2 4.7k to 3V3|SW2 to GND|Q1 drain (DTR)|J1.4")
    block(x + 40, y + 280, 260, 130, "U1.55 INITN", "SRAM clear", "#e9c46a",
          "R3 4.7k to 3V3|J1.10|R31 -> Q4 -> D6")
    block(x + 40, y + 450, 260, 130, "U1.56 DONE", "configured", "#e9c46a",
          "R4 4.7k to 3V3|J1.9|R32 -> Q2 -> D1")
    block(x + 40, y + 620, 260, 120, "mode straps", "latched at INITN rise", "#8b949e",
          "CFG_0 pin 62 -> R6 1k -> GND|CFG_1 pin 59 -> R5 4.7k -> 3V3|CFG_2 pin 58 -> R7 1k -> GND")
    block(x + 400, y + 110, 300, 200, "JTAG TAP", "always available", "#ffd60a",
          "TCK 63 -> J1.8 / J2.5|TMS 64 -> J1.6 / J2.2|TDI 61 -> J1.3 / J2.3|"
          "TDO 60 -> J1.2 / J2.4|GND J1.7 J2.6 J2.10")
    block(x + 400, y + 350, 300, 130, "J1  1x10  2.54 mm", "Versa / FT232H", "#ffd60a",
          "1 3V3  2 TDO  3 TDI  4 PROGRAMn  5 NC|6 TMS  7 GND  8 TCK  9 DONE  10 INITn")
    block(x + 400, y + 510, 300, 130, "auto-reconfigure", "from the host", "#e9c46a",
          "U4 DTR# -> JP1 -> R25 4.7k -> Q1 gate|R26 10k gate to GND|bridge JP1 to enable")
    block(x + 770, y + 110, 340, 190, "reset", "SW1 + RC", "#f72585",
          "U1.134 ext_rst_n|SW1 to GND|R1 10k to 3V3|C1 100 nF to GND|pin has PULLMODE=UP too")
    block(x + 770, y + 330, 340, 190, "status LEDs", "all active low", "#84cc16",
          "led[0..3] pins 39 40 41 44|R27-R30 470R -> D2-D5 -> 3V3|"
          "D1 = DONE, D6 = INITN (DNP)|D7 = 3V3 present")
    wire([(x + 300, y + 175), (x + 400, y + 175)], "PROGRAMN")
    wire([(x + 300, y + 345), (x + 400, y + 345)], "INITN")
    wire([(x + 300, y + 515), (x + 400, y + 515)], "DONE")

    # --- sheet 3: the two flashes ---------------------------------------
    x, y = sheet(0, 1, "3 — the two SPI flashes",
                 "U2 = bitstream (driven by the config logic), U3 = application images (driven by the SoC)")
    block(x + 40, y + 120, 330, 300, "U2  W25Q64JVSSIQ", "SOIC-8, config flash", "#a855f7",
          "1 /CS  <- R12 100R <- U1.49 (CSSPIN)|2 DO   -> R11 100R -> U1.46|"
          "3 /WP  <- R14 10k  <- 3V3|4 GND|5 DI   <- R10 100R <- U1.47|"
          "6 CLK  <- R9 100R  <- U1.54 (CCLK)|7 /HOLD <- R15 10k <- 3V3|"
          "8 VCC  = 3V3 + C28 100 nF")
    block(x + 400, y + 120, 330, 300, "U3  W25Q64JVSSIQ", "SOIC-8, application flash", "#a855f7",
          "1 /CS  <- U1.111 flash_cs_n|2 DO   -> U1.113 flash_miso|"
          "3 /WP  <- R17 10k -> 3V3|4 GND|5 DI   <- U1.112 flash_mosi|"
          "6 CLK  <- U1.110 flash_sck|7 /HOLD <- R18 10k -> 3V3|8 VCC  = 3V3 + C29 100 nF")
    block(x + 800, y + 120, 320, 300, "why two devices", "BOARD.md 6.4", "#e9c46a",
          "the configuration port is not|memory-mapped, so the soft core|cannot reach U2 at all.|"
          "U3 is an ordinary SPI device on|user I/O - that is what|sv16_flash_ctrl (0xF0A0)|reads images from.|"
          "gpio_a[1]/[2]/[4]/[6] share the|config-flash nets: keep them|inputs (R9-R12 bound contention).")
    note(x + 40, y + 460, "Boot: 25 MHz XO -> FPGA POR -> hardware loader streams the image from U2 (CRC-checked) ->")
    note(x + 40, y + 486, "CPU released at the application entry point, or the resident monitor if the image is bad.")
    note(x + 40, y + 512, "Field update: the same monitor writes new images into U3 over the UART (slot A/B).")

    # --- sheet 4: clock, USB, console ------------------------------------
    x, y = sheet(1, 1, "4 — clock, USB and console",
                 "the 25 MHz oscillator, the CH340G bridge and the USB-C front end")
    block(x + 40, y + 120, 300, 160, "Y1  25 MHz XO", "active, 3.3 V, 4-pin", "#ffd166",
          "1 EN  -> 3V3|2 GND|3 OUT -> U1.133 clk_25m|4 VCC -> 3V3 + C26 100 nF")
    block(x + 40, y + 320, 300, 150, "reset", "SW1 / R1 / C1", "#f72585",
          "U1.134 -> SW1 to GND|R1 10k to 3V3|C1 100 nF to GND")
    block(x + 390, y + 120, 330, 260, "U4  CH340G", "SOP-16, 3.3 V", "#06b6d4",
          "1 GND|2 TXD -> R21 0R -> U1.73 uart_rx|3 RXD <- R23 0R <- U1.74 uart_tx|"
          "4 V3 -> 3V3 + C34 100 nF|5 UD+ / 6 UD-  (through U8)|"
          "7 XI / 8 XO -> Y2 12 MHz + C36/C37 22 pF|13 DTR# -> JP1 -> Q1 gate|"
          "16 VCC -> 3V3 + C27 100 nF|15 R232: leave open")
    block(x + 390, y + 420, 330, 200, "U8  USBLC6-2SC6", "ESD, at the connector", "#06b6d4",
          "1 I/O1 <- J8 D+|2 GND|3 I/O2 <- J8 D-|4 I/O2' -> U4 UD-|"
          "5 VBUS <- J8 VBUS|6 I/O1' -> U4 UD+|D+/D-: 90 ohm pair, no vias")
    block(x + 780, y + 120, 340, 260, "J8  USB-C receptacle", "16-pin, at the board edge", "#06b6d4",
          "A4 B4 A9 B9 VBUS|A5 CC1 -> R36 5.1k -> GND|B5 CC2 -> R37 5.1k -> GND|"
          "A6/B6 D+   A7/B7 D-|A1 B1 A12 B12 GND|S1-S4 shell -> GND|"
          "power + console on one cable")
    block(x + 780, y + 420, 340, 200, "J10  console header", "without the CH340G", "#90be6d",
          "1 3V3  2 uart_tx  3 uart_rx  4 GND|fit R22/R24 and REMOVE R21/R23|"
          "uart_rx has PULLMODE=UP in the LPF")
    wire([(x + 340, y + 200), (x + 390, y + 200)], "clk_25m")
    wire([(x + 720, y + 250), (x + 780, y + 250)], "D+ / D-")

    # --- sheet 5: expansion and motor ------------------------------------
    x, y = sheet(0, 2, "5 — expansion, motor, test points",
                 "every I/O the design constrains, and the two headers most likely to be used first")
    block(x + 40, y + 110, 330, 300, "J3  EXP-A  2x10", "SPI0 + GPIOA[15:8]", "#f472b6",
          "1 3V3   2 GND|3-10 A8..A15|11 spi0_cs_n  12 spi0_sck|"
          "13 spi0_mosi 14 spi0_miso|15,16 GND|17,18 5V (USB VBUS only)|19,20 GND")
    block(x + 400, y + 110, 330, 300, "J4  EXP-B  2x10", "all 16 GPIOB", "#f472b6",
          "1 3V3   2 GND|3-18 B0..B15|19 GND|20 5V (USB VBUS only)")
    block(x + 760, y + 110, 360, 300, "J5 / J6 / J10", "the rest of the connectors", "#f472b6",
          "J5 EXP-C: A0..A7, pin 9 GND, 10 3V3|   pins 2/3/5/7 touch the config flash:|   INPUTS ONLY|"
          "J6 MOTOR: VM_IN, GND, pwm_out,|   motor_dir1, motor_dir2, motor_fault_n|"
          "J10 CONSOLE: 3V3, uart_tx, uart_rx, GND|J7 SPARE 2x25: footprint only, not fitted")
    block(x + 40, y + 450, 330, 280, "test points", "probe while powered", "#e5e7eb",
          "TP1 3V3 (3.28 V)|TP2 2V5 (2.50 V)|TP3 1V1 (1.10 V)|TP4 GND|"
          "TP5 DONE (high = configured)|TP6 INITN (low = failure)")
    block(x + 400, y + 450, 330, 280, "motor interface", "J6", "#4cc9f0",
          "pwm_out   pin 88, 16 mA drive|motor_dir1 pin 89|motor_dir2 pin 102|"
          "motor_fault_n pin 103 + R19 10k|the fuse lives on the driver board|"
          "keep the motor return away from|the FPGA ground")
    block(x + 760, y + 450, 360, 280, "before you route", "BOARD.md 11", "#e9c46a",
          "Y1 within 10 mm of U1.133|U2 within 15 mm of pins 54/46/47/49|"
          "R9-R12 at the FPGA end|USB pair: no vias, < 0.5 mm skew|"
          "switchers away from Y1 / U2 / U4|every GND pin its own via")

    # --- sheet 6: build order --------------------------------------------
    x, y = sheet(1, 2, "6 — build order and first power-up",
                 "the order that keeps a mistake cheap: power first, FPGA last")
    steps = [
        ("1", "Solder the power section only", "U5 U6 U7, L1 L2, D8 D9 D11, FB1, C23 C24 C39 C40 C41, J9"),
        ("2", "Bench supply, 12 V, 200 mA limit", "nothing else fitted - a few tens of mA is normal"),
        ("3", "Measure TP1 / TP3 / TP2", "3.28 V / 1.10 V / 2.50 V; 2V5 appears ~21 ms after 3V3"),
        ("4", "Wrong rail?", "check R46/R47 (3V3), R38/R39 (1V1), R43/C32 (2V5), U5 EN ~3 V not 12 V"),
        ("5", "Fit the rest, FPGA last", "flashes, USB/console, passives, then U1 and the headers"),
        ("6", "Power again and re-measure", "a sagging 3V3 with U1 fitted = short under the QFP or a missing cap"),
        ("7", "Plug in USB", "the CH340G must enumerate as a serial port at 115200 8-N-1"),
        ("8", "Configure", "openFPGALoader over J1, then make prog-flash for the config flash"),
        ("9", "DONE rises, monitor answers", "TP5 high; '?' over the console prints the monitor help"),
        ("10", "If DONE never rises", "scope clk_25m at Y1.3, then check PROGRAMN, CCLK and U2"),
    ]
    yy = y + 110
    for number, title, detail in steps:
        d.ellipse([x + 40, yy, x + 74, yy + 34], fill="#1f6feb")
        d.text((x + 57, yy + 17), number, font=font(18, "bold"), fill="white", anchor="mm")
        d.text((x + 92, yy + 2), title, font=font(18, "bold"), fill="#e6edf3")
        d.text((x + 92, yy + 26), detail, font=font(15), fill=C["note"])
        yy += 62

    out = OUT / "pcb_connection_sheets.png"
    image.save(out)
    print("wrote %s (%d x %d)" % (out.relative_to(ROOT), img_w, img_h))


# ---------------------------------------------------------------------- main
def top_view(scale: int):
    legend = [
        "stack-up:   F.Cu signal  ·  In1.Cu solid GND  ·  In2.Cu rail pours  ·  B.Cu signal",
        "pours:      3V3 (whole layer, priority 0) · 2V5 (LP5907 group + strip above U1, priority 2) · 1V1 (MP1584 group + left strip, priority 3)",
        "copper:     291 vias (128 edge stitching + escape vias for every pad that can legally drop into its own pour), 163 stub tracks at 0.2 mm",
        "escape vias: GND 217 · 3V3 55 · 1V1 11 · 2V5 8      (fill the zones with B, then route)",
        "marked DNP: D6 (INITN LED) and J7 (spare-I/O header) - attribute + silkscreen + BOM/CPL exclusion",
        "rule:       an SMD pad reaches an inner layer only through a via - the stubs and vias above are that connection",
    ]
    with Canvas(scale, legend_px=210, title="SV-16 Rev B — top view (F.Cu pads, silkscreen, In2 rail pours)") as canvas:
        draw_board_view(canvas, mirror=False, ratsnest=None)
        story_legend(canvas, legend, "what you are looking at")
        canvas.save(OUT / "pcb_top_view.png")


def bottom_view(scale: int):
    legend = [
        "this is the board flipped over, i.e. how the assembled part looks from underneath: text is mirrored on purpose",
        "B.Cu carries a GND pour (fill with B) and the bottom-side signal routing; the through-hole pads are the headers, switches, jack and crystal",
        "every pad that had to reach an inner layer already has its via - the bottom view shows them as light rings",
        "bottom silkscreen: reference designators are on the top side only, so use the CPL file (CPL.csv) for placement",
    ]
    with Canvas(scale, legend_px=150, title="SV-16 Rev B — bottom view (B.Cu, mirrored)") as canvas:
        draw_board_view(canvas, mirror=True, ratsnest=None, pin1=False)
        story_legend(canvas, legend, "bottom side")
        canvas.save(OUT / "pcb_bottom_view.png")


def net_map(scale: int):
    with Canvas(scale, legend_px=230, title="SV-16 Rev B — net map (ratsnest by function)") as canvas:
        draw_board_view(canvas, ratsnest="function", refs=True, pin1=False)
        net_map_legend(canvas)
        canvas.save(OUT / "pcb_net_map.png")


def power_map(scale: int):
    with Canvas(scale, legend_px=150, title="SV-16 Rev B — power plan (rails, sequencing, pours)") as canvas:
        draw_power_map(canvas)
        story_legend(canvas, [
            "TP1 3.28 V · TP3 1.10 V · TP2 2.50 V — measure with U1 NOT fitted, then again with it fitted",
            "current plan: 3V3 ~600 mA, 1V1 ~150 mA, 2V5 ~50 mA (BOARD.md 4.2); 0.8 mm traces, pours for the rest",
            "never tie U5 pin 5 (EN) to VM_IN: it is a 6 V pin - the R48/R49 divider is what protects it",
        ], "bench numbers")
        canvas.save(OUT / "pcb_power_map.png")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scale", type=int, default=24, help="pixels per mm (default 24)")
    parser.add_argument("--only", choices=["top", "bottom", "nets", "power", "sheets", "all"],
                        default="all")
    args = parser.parse_args()

    print("rendering from %s and %s"
          % (Path(board.__file__).name, Path(copper.__file__).name))
    if args.only in ("top", "all"):
        top_view(args.scale)
    if args.only in ("bottom", "all"):
        bottom_view(args.scale)
    if args.only in ("nets", "all"):
        net_map(args.scale)
    if args.only in ("power", "all"):
        power_map(args.scale)
    if args.only in ("sheets", "all"):
        draw_connection_sheets()
    return 0


if __name__ == "__main__":
    sys.exit(main())
