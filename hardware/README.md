# `hardware/` — the KiCad board for SV-16 Rev B

## One command builds the whole starter kit

```sh
make pcb          # board file + bitmaps + BOM/CPL + FAB_NOTES + PCB_CONNECTIONS.md
make pcb-check    # parse it all back: nets, pads, DRC-lite, placement collisions
```

Everything under `hardware/sv16_board/` is generated from **one** place — the
placement, the netlist and the part list in `scripts/sv16_board_kicad.py`, the
copper in `scripts/sv16_pcb_copper.py` — so a picture, a BOM line and a
connection in `PCB_CONNECTIONS.md` cannot disagree with the board file.

| File | What it is |
| :--- | :--- |
| `sv16_board/sv16_board.kicad_pcb` | **open this in KiCad**: 100 × 100 mm, 4 layers, 141 footprints, 472 pads on 121 nets, 5 zones, 291 vias, 163 stub tracks, no routed signals |
| `sv16_board/sv16_board.kicad_pro` | the project: five net classes with their widths, and the design rules (open this, not the bare board) |
| `sv16_board/pcb_top_view.png` | the board from above — every part, pad, silkscreen label, the `In2.Cu` rail pours and every via |
| `sv16_board/pcb_bottom_view.png` | the same board flipped (a real bottom view: text mirrored) |
| `sv16_board/pcb_net_map.png` | the ratsnest coloured by function, with a legend — the routing plan on one page |
| `sv16_board/pcb_power_map.png` | the power tree, the pour map and the pads the router still owes a trace |
| `sv16_board/pcb_connection_sheets.png` | the six connection sheets, drawn |
| `sv16_board/placement_preview.png` | the floorplan and the ratsnest, as placed |
| `sv16_board/BOM.csv` | grouped BOM: quantity, value, footprint, references, part number, DNP column |
| `sv16_board/JLCPCB_BOM.csv`, `JLCPCB_CPL.csv` | the same list in the columns an assembly service wants (fill the LCSC column from your cart) |
| `sv16_board/FAB_NOTES.md` | the ordering card: stack-up, rules, what to upload, what the generator already did |

## What is in the board file

* the **100 × 100 mm, 4-layer outline** on `Edge.Cuts`, four M3 mounting holes, four fiducials
* **all 141 footprints placed** in functional groups — power top-left, FPGA centre, both flashes
  right, USB/console bottom-right, JTAG and expansion along the bottom/left, motor right
* **the complete netlist** — 472 assigned pads over 121 nets, taken from `PCB_COMPONENTS.md` §4,
  so KiCad draws the ratsnest and you never guess a connection
* **the power copper**: 3V3 pour across `In2.Cu`, 1V1 and 2V5 patches carved out of it where their
  regulators and bulk capacitors live, a solid GND plane on `In1.Cu` and a GND pour on `B.Cu`
* **the escape vias**: 291 of them, each with a 0.2 mm stub from its pad — every GND pad that can
  legally take one straight into the plane, the 3V3 pads into the 3V3 pour, the 1V1/2V5 pads that
  sit over their own patch, the MP1584's exposed pad thermally stitched, and 128 GND stitching vias
  in two rings round the board edge
* **a placement repair pass**: the generator relaxes the hand-typed placement table until no two
  pads of different nets come within 0.2 mm, moving a part at most 9 mm from where the table put it
  (97 parts moved on the first run — the table on its own had overlapping pads)
* **the DNP parts marked**: D6 (INITN LED) and J7 (spare-I/O header) carry KiCad's `dnp`,
  `exclude_from_pos_files` and `exclude_from_bom` attributes, a "NOT FITTED" silkscreen label, and
  they are excluded from the CPL

### What is *not* in it (on purpose)

* **no routed signals** — that is the weekend job, and the escape vias are there to make it short
* **approximate pads** — the footprint names are the real KiCad library identifiers
  (`Package_QFP:LQFP-144_20x20mm_P0.5mm`), but the embedded pad geometry is generated, so run
  **Tools → Update Footprints from Library** before you route
* **seven pads the router owes a trace**: U1 pins 17, 20, 38, 66, 83, 96, 130 and 132 sit over the
  *wrong* rail's pour, and a via there would short two rails. The list is in `PCB_CONNECTIONS.md` §7
  and printed by `python3 scripts/sv16_pcb_copper.py --report`
* **the inner-layer signal routing** — the plane and the pours take most of `In1.Cu`/`In2.Cu`;
  signals go on `F.Cu` and `B.Cu`

### The click-by-click version

`KICAD_TUTORIAL.md` (and `.pdf`) at the repository root walks the whole job step by step — opening
the project, updating the footprints, the rules, filling the zones, the routing order with exact
widths, DRC, gerbers, ordering, first power-up. `PCB_CONNECTIONS.md` (and `.pdf`) is the wiring:
part by part, connector by connector, with the six connection sheets drawn.

## The 2-day route to a finished board

**Day 1 (4–6 h)**
1. Open `sv16_board.kicad_pro`, save it as your own project name.
2. **Tools → Update Footprints from Library.** Fix the ⚠ rows in `PCB_CONNECTIONS.md` §5 for the
   parts you actually bought (electrolytic cans, inductors, USB-C, oscillator, barrel jack).
3. Check the floorplan: Y1 within 10 mm of U1 pin 133, U2 within 15 mm of pins 54/46/47/49,
   switchers away from Y1/U2/U4, U8 between J8 and U4.
4. Press **B** to fill the five zones. Look at `In2.Cu`: every GND pad should have its via into the
   plane, the three rail patches should sit under their own components.
5. Route the **power rails first** (VM_IN → 3V3 → 1V1 → 2V5), then the seven stragglers from
   `PCB_CONNECTIONS.md` §7 to their pours.

**Day 2 (6–8 h)**
6. Route the signal fan-out from U1 (0.2 mm tracks, 0.45/0.2 mm vias), then the two flashes, then
   USB as a 90 Ω pair with no vias.
7. Remaining signals — let the ratsnest guide you; it is the netlist.
8. Run DRC; fix copper errors until clean.
9. Review against `BOARD.md` §11 and `PCB_CONNECTIONS.md` §9 with a second pair of eyes.
10. File → Fabrication Outputs → Gerbers + Excellon drill → zip → order (settings in
    `hardware/sv16_board/FAB_NOTES.md`).

### Regenerating / verifying

```sh
make pcb                                        # rewrite the board, bitmaps, BOM, documents
python3 scripts/sv16_board_kicad.py --check     # nets, pads, DRC-lite, placement collisions
python3 scripts/sv16_pcb_copper.py --report     # what the copper plan did; what routing owes
```

A board file that has not been parsed back is a guess — `make lint` runs all three checks.
