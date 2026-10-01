# `hardware/` — the KiCad base for the SV-16 board

## `sv16_board/sv16_board.kicad_pcb` — open this in KiCad

A **starting point for layout, not a finished board**. It contains:

* the **100 × 100 mm, 4-layer board outline** on `Edge.Cuts`, four mounting holes (M3) and four fiducials
* **all 141 footprints placed** in functional groups — power top-left, FPGA centre, both flashes right,
  USB/console bottom-right, JTAG and expansion bottom-left, motor right ("place" table is in
  `scripts/sv16_board_kicad.py`, so it is reproducible and reviewable)
* **the complete netlist** — 472 assigned pads over 133 nets, taken from `PCB_COMPONENTS.md` §4. KiCad
  draws the ratsnest from this, so you can route without guessing a single connection
* **`sv16_board.kicad_pro`** — the project file, with the five net classes (Default / Power / Switching /
  USB / JTAG) and their widths, so the router starts with the right rules. Open the project, not the
  bare board, if you want those to apply
* **two ground zones defined** — a solid GND plane on `In1.Cu` and a GND pour on `B.Cu`. They are
  outlines only: KiCad fills them on the first *Fill All Zones* (**B**)
* net classes `Default` / `Power` / `Switching` / `USB` / `JTAG` with the widths from
  `PCB_COMPONENTS.md` §7
* `placement_preview.png` — the floorplan and the ratsnest, rendered by the generator

### What is *not* in it (on purpose)

* **no routed tracks** — routing is the weekend job
* **approximate pads** — the footprint names are the real KiCad library identifiers
  (`Package_QFP:LQFP-144_20x20mm_P0.5mm`), but the embedded pad geometry is generated, so
  **update the footprints from the library before you route**: in KiCad, Tools → Update Footprints from
  Library (or per part: right-click → Update Footprint…), keeping the placement and the nets
* **no inner power pours** — `In2.Cu` is left for you to split into 3V3 / 1V1 / 2V5; the GND plane
  and the bottom pour are already defined
* **the power parts of the AP62300 / LP5907** — see `PCB_COMPONENTS.md` §10 corrections 6–7 and
  `cart/RECONCILED.md`: a 10 kΩ resistor and six ceramics still have to be bought, and the 470 µF input
  bulk in the cart is a 16 V part on a 12 V rail

### The 2-day route to a finished board

**Day 1 (4–6 h)**
1. Open `sv16_board.kicad_pcb`, save it as your own project name.
2. Tools → Update Footprints from Library. Fix the ⚠ footprint rows in `PCB_COMPONENTS.md` §2 for the
   parts you actually bought (electrolytic cans, inductors, USB-C, oscillator).
3. Check the floorplan against `BOARD.md` §11 and move anything that violates it (Y1 within 10 mm of U1
   pin 133, U2 within 15 mm of the SPI pads, switchers away from the oscillator and flash).
4. **Fill the zones (B)** and check that the plane actually reaches every GND pad; fix any isolated
   islands before routing.
5. Split `In2.Cu` into the 3V3 / 1V1 / 2V5 pours, then route the **power rails first** (VM_IN → 3V3 →
   1V1 → 2V5), because they set the plane splits.

**Day 2 (6–8 h)**
6. Route the FPGA fan-out (0.25 mm traces, 0.2 mm vias), then the two flashes, then USB as a 90 Ω pair.
7. Remaining signals — let the ratsnest guide you; it is the netlist.
8. Run DRC; fix clearance and unconnected items until clean.
9. Review against `BOARD.md` §11 and the checklist in `TEAM_PLAN.md` §4 with a second pair of eyes.
10. File → Fabrication Outputs → Gerbers + Excellon drill → zip → order.

### Regenerating / verifying

```sh
make kicad-board                    # rewrite the .kicad_pcb and the preview
python3 scripts/sv16_board_kicad.py --check    # parse it back: nets, pads, duplicates, balance
```

`--check` re-reads the file it wrote: balanced parentheses, 141 footprints, 472 pads with nets, no
duplicate references, no duplicate nets, both zones, and every connection landing on a pad that exists. A board file that has not been
parsed back is a guess.
