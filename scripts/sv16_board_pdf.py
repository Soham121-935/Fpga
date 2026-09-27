#!/usr/bin/env python3
"""SV-16 — render BOARD.md to BOARD.pdf.

BOARD.md is the source of truth; this script produces the printable PDF with the
ASCII connection diagrams kept in a monospaced font and the wide tables sized to
fit an A4 page.  It is deliberately optional: `make board-pdf` tells you what to
install if the two pure-Python dependencies are missing, and nothing else in the
build depends on it.

    python3 -m pip install markdown xhtml2pdf
    scripts/sv16_board_pdf.py            # -> BOARD.pdf
    scripts/sv16_board_pdf.py --check    # fail if BOARD.pdf is older than BOARD.md
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "BOARD.md"
APPENDIX = ROOT / "board" / "TQFP144_PINOUT.md"   # generated netlist appendix
DST = ROOT / "BOARD.pdf"

DEJAVU = Path("/usr/share/fonts/truetype/dejavu")
FONT_FILES = {
    "BoardSans": "DejaVuSans.ttf",
    "BoardSans-Bold": "DejaVuSans-Bold.ttf",
    "BoardSans-Oblique": "DejaVuSans-Oblique.ttf",
    "BoardSans-BoldOblique": "DejaVuSans-BoldOblique.ttf",
    "BoardMono": "DejaVuSansMono.ttf",
    "BoardMono-Bold": "DejaVuSansMono-Bold.ttf",
    "BoardMono-Oblique": "DejaVuSansMono-Oblique.ttf",
    "BoardMono-BoldOblique": "DejaVuSansMono-BoldOblique.ttf",
}

CSS = """
@page {
    size: A4 portrait;
    margin: 1.5cm 1.25cm 1.6cm 1.25cm;
    @frame footer_frame {
        -pdf-frame-content: footer_content;
        left: 1.25cm; right: 1.25cm; bottom: 0.75cm; height: 0.8cm;
    }
}
body { font-family: Helvetica; font-size: 9.3pt; line-height: 1.38; color: #111111; }
h1 { font-family: Helvetica-Bold; font-size: 19pt; line-height: 1.2; color: #10243c;
     border-bottom: 1.6pt solid #10243c; padding-bottom: 5pt; margin-bottom: 10pt; }
h2 { font-family: Helvetica-Bold; font-size: 13.5pt; color: #10243c; margin-top: 16pt;
     margin-bottom: 6pt; border-bottom: 0.6pt solid #9aa7b4; padding-bottom: 2pt; }
h3 { font-family: Helvetica-Bold; font-size: 11pt; color: #24405f; margin-top: 12pt; margin-bottom: 4pt; }
h4 { font-family: Helvetica-Bold; font-size: 9.8pt; color: #24405f; margin-top: 10pt; margin-bottom: 3pt; }
p { margin: 0 0 5pt 0; }
ul, ol { margin: 0 0 6pt 14pt; }
li { margin-bottom: 2pt; }
b, strong { font-family: Helvetica-Bold; }
em, i { font-family: Helvetica; }
code { font-family: Courier; font-size: 8.2pt; color: #14314f; }
pre { font-family: Courier; font-size: 7.1pt; line-height: 1.18; color: #10243c;
      background-color: #f4f6f8; border: 0.5pt solid #c3ccd6; padding: 4pt 5pt;
      margin: 4pt 0 8pt 0; }
table { width: 100%; font-size: 7.7pt; margin: 4pt 0 9pt 0; }
th { background-color: #e7ecf2; border: 0.5pt solid #8f9cab; padding: 2.5pt 3pt;
     font-family: Helvetica-Bold; font-size: 7.7pt; text-align: left; color: #10243c; }
td { border: 0.5pt solid #b6c0cb; padding: 2.5pt 3pt; vertical-align: top; }
blockquote { border-left: 2pt solid #9aa7b4; background-color: #f6f8fa; margin: 4pt 0 8pt 0;
             padding: 3pt 6pt; font-size: 8.6pt; color: #33465c; }
hr { border: 0; border-top: 0.6pt solid #c3ccd6; margin: 10pt 0; }
a { color: #1b4b7d; text-decoration: none; }
#footer_content { font-family: Helvetica; font-size: 7.4pt; color: #7a8794; text-align: right; }
"""

FOOTER = (
    '<div id="footer_content">SV-16 microcontroller board blueprint &nbsp;|&nbsp; '
    "LFE5U-12F-6TG144C &nbsp;|&nbsp; page <pdf:pagenumber/> of <pdf:pagecount/></div>"
)


def register_fonts():
    """Point reportlab's built-in font names at DejaVu.

    xhtml2pdf only resolves fonts it can find in reportlab's registry by the
    names reportlab already knows (Helvetica, Courier, Times).  Registering the
    DejaVu TTFs *under those names* gives the document full Unicode coverage
    (arrows, <=, approximately-equal, ohm, micro, multiply, degree) and a real
    monospaced face for the ASCII connection diagrams, without needing
    @font-face support.
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    mapping = {
        "Helvetica": "DejaVuSans.ttf",
        "Helvetica-Bold": "DejaVuSans-Bold.ttf",
        "Helvetica-Oblique": "DejaVuSans-Oblique.ttf",
        "Helvetica-BoldOblique": "DejaVuSans-BoldOblique.ttf",
        "Courier": "DejaVuSansMono.ttf",
        "Courier-Bold": "DejaVuSansMono-Bold.ttf",
        "Courier-Oblique": "DejaVuSansMono-Oblique.ttf",
        "Courier-BoldOblique": "DejaVuSansMono-BoldOblique.ttf",
        "Times-Roman": "DejaVuSerif.ttf",
        "Times-Bold": "DejaVuSerif-Bold.ttf",
        "Times-Italic": "DejaVuSerif-Italic.ttf",
        "Times-BoldItalic": "DejaVuSerif-BoldItalic.ttf",
    }
    loaded = {}
    for reportlab_name, filename in mapping.items():
        path = DEJAVU / filename
        if path.exists():
            pdfmetrics.registerFont(TTFont(reportlab_name, str(path)))
            loaded[reportlab_name] = path
    if "Courier" not in loaded or "Helvetica" not in loaded:
        raise SystemExit("DejaVu fonts not found in %s (needed for the ASCII diagrams)" % DEJAVU)
    for family, suffixes in (("Helvetica", ("", "-Bold", "-Oblique", "-BoldOblique")),
                             ("Courier", ("", "-Bold", "-Oblique", "-BoldOblique")),
                             ("Times", ("-Roman", "-Bold", "-Italic", "-BoldItalic"))):
        names = [family + sfx for sfx in suffixes]
        if all(n in loaded for n in names):
            pdfmetrics.registerFontFamily(family, normal=names[0], bold=names[1],
                                          italic=names[2], boldItalic=names[3])
    return loaded


def appendix_markdown():
    """The generated 144-pin net table, demoted one heading level and placed on a new page."""
    if not APPENDIX.exists():
        return ""
    lines = []
    for line in APPENDIX.read_text().splitlines():
        if line.startswith("#"):
            line = "#" + line
        lines.append(line)
    return "\n\n<div style='page-break-before: always'></div>\n\n" + "\n".join(lines)


def build_html(markdown_text):
    import markdown

    body = markdown.markdown(
        markdown_text + appendix_markdown(),
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
        output_format="html5",
    )
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'/><style>%s</style></head>"
        "<body>%s%s</body></html>" % (CSS, body, FOOTER)
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="verify BOARD.pdf is newer than BOARD.md")
    args = ap.parse_args()

    if args.check:
        if not DST.exists():
            print("ERROR: %s is missing — run scripts/sv16_board_pdf.py" % DST.name)
            return 1
        newest = max(SRC.stat().st_mtime, APPENDIX.stat().st_mtime if APPENDIX.exists() else 0)
        if DST.stat().st_mtime < newest:
            print("ERROR: %s is older than %s — run scripts/sv16_board_pdf.py" % (DST.name, SRC.name))
            return 1
        print("%s is up to date" % DST.name)
        return 0

    try:
        import markdown  # noqa: F401
        import xhtml2pdf  # noqa: F401
    except ImportError as exc:
        print("missing dependency: %s" % exc)
        print("install with:  python3 -m pip install markdown xhtml2pdf")
        return 2

    from xhtml2pdf import pisa

    register_fonts()
    html = build_html(SRC.read_text())
    (ROOT / "build" / "board_pdf.html").parent.mkdir(exist_ok=True, parents=True)
    (ROOT / "build" / "board_pdf.html").write_text(html, encoding="utf-8")

    with DST.open("wb") as out:
        result = pisa.CreatePDF(html.encode("utf-8"), dest=out, encoding="utf-8")
    if result.err:
        print("PDF generation reported %d error(s)" % result.err)
        return 1
    size = DST.stat().st_size
    print("wrote %s (%.0f KB) from %s" % (DST.name, size / 1024.0, SRC.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
