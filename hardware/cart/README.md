# `hardware/cart/` — what you actually bought

Drop the cart screenshots / order confirmations here (PNG, JPG or PDF). One file per vendor is fine:
`robu_1.png`, `hubtronics.pdf`, `digikey_fpga.png` …

## What each screenshot needs to show

For every line item, the **part number** and the **package/footprint** are what I reconcile against the
board file — a photo of the cart is enough if those are readable:

| Needed on screen | Why |
| :--- | :--- |
| manufacturer part number (e.g. `W25Q64JVSSIQ`, `LM2596S-3.3`, `AO3401`) | tells me the exact pinout and pad geometry |
| package / footprint text (e.g. `SOIC-8 208mil`, `TO-263-5`, `SOT-23`, `0805`, `3.2×2.5 mm`) | this is what changes the board file |
| quantity | decides how many footprints the board carries |
| (if shown) voltage/current rating, e.g. `470 µF 35 V`, `33 µH 3 A` | decides the can and body sizes |

## The parts whose footprint depends on your cart

| Board ref | What matters | If your part differs |
| :--- | :--- | :--- |
| C21, C22, C23, C24 | electrolytic **can size** and voltage (6.3×5.4, 5×5.4, 10×10, 8×6.9 mm) | footprint and courtyard change; I update the map in `PCB_COMPONENTS.md` §2 |
| L1, L2 | inductor **body size** (8×8 mm, 6×6 mm, or a different brand) | same |
| Y1 | 25 MHz oscillator package: **3.2×2.5 mm** or 5×7 mm | same |
| J8 | USB-C 16-pin receptacle model, or **micro-USB** if you chose that | footprint + the CC resistors (R36/R37 omitted for micro-USB) |
| U6 | MP1584 **exposed-pad size** (the SOIC-8E variants differ) | pad geometry |
| U4 | CH340C package: **SOP-16 150 mil** or the SOP-16 3.9 mm body | footprint + pin numbers (confirm against the WCH datasheet) |
| J2 | 1.27 mm box header: bought or skipped? | if skipped, it stays unpopulated |
| Modules | if you bought the **module-first** options from `BOARD.md` §3.5 (LM2596 module, Mini360, CH340C breakout) instead of the chips, say so | that **replaces** the regulator/USB sections of the board: the board becomes a carrier instead of a full design |

## Two questions that change the board

1. **Chips or modules?** Module-first (`BOARD.md` §3.5) means the power and USB sections become 4-pin
   headers and the board shrinks — a different topology, not a footprint tweak.
2. **USB-C or micro-USB?** Micro-USB removes R36/R37 and changes J8 completely.

If the cart is still provisional, say so and I will keep the current footprints and only update the ones
you are sure about.
