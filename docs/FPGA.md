# SV-16 Rev B — Lattice ECP5 Target

## 1. Device

| Item | Value |
| :--- | :--- |
| Part | `LFE5U-12F-6TG144C` |
| Family | ECP5 (Lattice Semiconductor) |
| Logic | **12k LUTs = 12,144 LUT4** (datasheet, Table 1.1). Each PFU is 4 slices of 2 LUT4 + 2 FF, so the die has 3,036 PFU positions (24,288 LUT4) — but a 12F guarantees **half of them**, which is why `scripts/sv16_check_budget.py` counts against 12,144 and not against nextpnr's denominator (ADR-025) |
| Block RAM | **32 × `DP16KD`** = 576 Kbit = **72 KB** (datasheet; the 56 blocks / 126 KB figure belongs to the LFE5U-25F — same die, different bin). 18 blocks used = 36 KB |
| Multipliers | 28 × `MULT18X18D`, 1 used |
| PLLs | 2 × `EHXPLLL` (0 used by default, 1 with `CLKSRC=pll`) |
| Package | TQFP-144, **98 bonded I/O** (52 used) — datasheet Table 1.1, `144 TQFP: 0/98`. The 197 in nextpnr's utilisation table is the I/O count of the BGA packages of the same device |
| Speed grade | 6 (fastest) |
| Supply | 1.1 V core, 3.3 V I/O (`LVCMOS33` on every pin) |
| Configuration | SRAM-based — a bitstream must be loaded at every power-up |

## 2. How this design uses the device

| Resource | Used | Where |
| :--- | ---: | :--- |
| LUT4 | 9,407 (**77 %** of the 12,144 the datasheet guarantees for a 12F, incl. carry) | CPU datapath and control, boot loader, flash controller, watchdog, monitor's ROM decoding, the iterative divider |
| Flip-flops | 4,772 (39 %) | CPU state, FIFOs, peripherals, watchdog counters, divider registers |
| `DP16KD` | 18 (**56 %** of 32) | 16 for the 32 KB SRAM, 2 for the 4 KB boot ROM |
| `MULT18X18D` | 1 (4 %) | the ALU's single-cycle 16×16 multiply |
| I/O | 52 (**53 %** of the 98 bonded pins) | UART, two SPI ports, GPIO A/B, PWM, motor control, LEDs, clock, reset |
| `EHXPLLL` | 0 in the default build, 1 with `CLKSRC=pll` | optional PLL system clock (ADR-021) |

## 3. Clocking and timing

* Input: `clk_25m` on pin 133 (25 MHz).
* `CLKSRC` selects the source: `osc` (default) wires the oscillator straight into
  the fabric; `pll` instantiates the `EHXPLLL` hard macro and multiplies it up
  (`make bitstream CLKSRC=pll PLLMHZ=37.5` → 37.5 MHz, VCO 600 MHz). `CLKDIV`
  then optionally halves it in fabric (12.5 MHz fallback).
* Measured Fmax, default (`osc`, 25 MHz): **44.70 MHz** post-route (36.29
  pre-route, nextpnr heap placer, speed grade 6) since the ALU's divider became
  iterative (ADR-018) — ~75 % margin at 25 MHz. The same flow measured 46.17 MHz
  before the PLL option was added; both are well clear of 25 MHz and the
  difference is synthesis ordering, not logic.
* Measured Fmax, `CLKSRC=pll PLLMHZ=37.5`: **45.45 MHz** post-route (37.73
  pre-route) → **PASS at 37.5 MHz** (~20 % margin), the same 2 of 27 blocks.
* The PLL output could also feed the SPI pins or drive `CLKOS` outputs later;
  the design point does not need either.

## 4. Pin constraints

`constraints/ecp5_144tqfp.lpf` — every port of `sv16_top`, all `LVCMOS33`. The
full table with rationale lives in the LPF header and in
[SYNTHESIS_AND_DEPLOYMENT.md](SYNTHESIS_AND_DEPLOYMENT.md#pin-constraints).

Three points worth remembering when editing it:

1. **`SITE` names for TQFP packages are bare pin numbers** (`SITE "102"`, not
   `SITE "P102"`). Both forms appear in the wild; only the bare number places.
2. Four Rev A assignments were **not bonded I/O on this package at all** (`P63`
   clock, `P60` reset, `P38` LED0, `P100` PWM). Validate any new pin against the
   prjtrellis device database (`ECP5/LFE5U-12F/iodb.json`, `packages.TQFP144`)
   before trusting it — a constraint file that places is not the same as a
   constraint file that matches your board.
3. Only the Rev A UART pins (73/74) survived; everything else was re-assigned
   from the database. If you have a Rev A board, the LPF must be re-derived from
   its schematic — the bitstream will not match it.

## 5. Configuration and programming

* FPGA configuration: `make prog` (openFPGALoader over JTAG). Volatile; the
  device is blank at power-up unless the board has its own configuration flash
  for the FPGA.
* Application firmware: over UART, into the external SPI flash
  ([BOOT_AND_PROGRAMMING.md](BOOT_AND_PROGRAMMING.md)).
* External SPI flash for firmware: any W25Q-class part in the 64 KB-1 MB range;
  the loader programs the first 64 KB window, and `FLASH_ID` should read
  `0xEF4018`.
