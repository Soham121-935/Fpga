# SV-16 Rev A — Lattice ECP5 Target Specification

---

## 1. Device Hardware Details

```text
Manufacturer:    Lattice Semiconductor
Family:          ECP5 (Low-Cost, High-Performance)
Device:          LFE5U-12F
Full Part Number:LFE5U-12F-6TG144C
Package:         144-pin TQFP (0.5 mm pin pitch)
Speed Grade:     -6 (Commercial Temperature Range: 0°C to 85°C)
Core Voltage:    1.1V
I/O Banks:       8 I/O Banks (3.3V LVCMOS capable)
```

---

## 2. On-Chip Resources

- **LUT4 Logic Elements**: 12,000 LUTs
- **sysMEM Block RAM**: 32 DP16KD blocks (576 Kbits total)
  - Configurable as True Dual-Port, Pseudo Dual-Port, or Single-Port RAM/ROM.
  - Initialized with SV-16 boot firmware via `$readmemh` or bitstream initialization.
- **sysDSP Slices**: 28 Multiplier (18×18) blocks, ideal for single-cycle 16-bit ALU `MUL` operation.
- **sysCLOCK PLLs**: 2 General Purpose Phase-Locked Loops.
- **General Purpose I/O Pins**: Up to 118 user I/O pins available in 144 TQFP package.

---

## 3. Physical Pin Constraints Overview

Constraint definitions reside in `constraints/ecp5_144tqfp.lpf` (Lattice Preference Format):
- Clock Pin: `25 MHz` dedicated primary clock input.
- Reset Pin: Active-low push button input with internal pull-up.
- UART Pins: `uart_tx` (output), `uart_rx` (input with pull-up).
- Status LEDs: 4 to 8 dedicated active-low or active-high LEDs connected to GPIO.
- Motor Control Pins:
  - `pwm_out`: High-speed PWM switching pin to external gate driver / H-Bridge input.
  - `motor_dir1`, `motor_dir2`: Direction control GPIO outputs.
  - `motor_fault_n`: Emergency hardware shutdown input pin.

*Electrical Safety Warning*: Under no circumstances shall motor coils or inductive loads be connected directly to FPGA pins. An external driver stage (such as an L298N, DRV8833, or discrete MOSFET H-Bridge) with freewheeling flyback diodes and adequate decoupling capacitors must be used.
