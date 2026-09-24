# SV-16 Rev B — Lattice ECP5 Target

## 1. Device

| Item | Value |
| :--- | :--- |
| Part | `LFE5U-12F-6TG144C` |
| Family | ECP5 (Lattice Semiconductor) |
| Logic | 12K LUT4 (24,288 LUT4 + 1,376 carry positions in nextpnr's count) |
| Block RAM | 56 × `DP16KD` (18 Kbit each → 126 Kbit) |
| Multipliers | 28 × `MULT18X18D` |
| PLLs | 2 × `EHXPLLL` (unused in Rev B) |
| Package | TQFP-144, 197 usable I/O |
| Speed grade | 6 (fastest) |
| Supply | 1.1 V core, 3.3 V I/O (`LVCMOS33` on every pin) |
| Configuration | SRAM-based — a bitstream must be loaded at every power-up |

## 2. How this design uses the device

| Resource | Used | Where |
| :--- | ---: | :--- |
| LUT4 | 8,363 (34 %) | CPU datapath and control, boot loader, flash controller, watchdog, monitor's ROM decoding, the iterative divider |
| Flip-flops | 4,631 (19 %) | CPU state, FIFOs, peripherals, watchdog counters, divider registers |
| `DP16KD` | 18 (32 %) | 16 for the 32 KB SRAM, 2 for the 4 KB boot ROM |
| `MULT18X18D` | 1 (3 %) | the ALU's single-cycle 16×16 multiply |
| I/O | 52 (26 %) | UART, two SPI ports, GPIO A/B, PWM, motor control, LEDs, clock, reset |
| `EHXPLLL` | 0 | clock is divided in fabric (see below) |

## 3. Clocking and timing

* Input: `clk_25m` on pin 133 (25 MHz).
* `SV16_CLKDIV` divides it in fabric; **`CLKDIV=1` is the shipped default**, so
  the SoC clock *is* the oscillator and there is no generated clock at all.
  `CLKDIV=2` (12.5 MHz) remains available as a conservative fallback.
* Measured Fmax: **46.58 MHz** (nextpnr, heap placer, speed grade 6) since the
  ALU's divider became iterative (ADR-018) — ~86 % margin at 25 MHz. Before that
  change the same flow measured 14.68 MHz, which is why the part shipped at
  12.5 MHz for most of Rev B.
* An `EHXPLLL` could now be used to run 40–50 MHz or to feed a stable clock to
  the SPI pins, but it is not needed to hit the design point.

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
