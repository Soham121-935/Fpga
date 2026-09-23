# SV-16 Rev A — Synthesis, Implementation & Physical Deployment Guide

This guide details the complete procedure for synthesizing the SV-16 Rev A microcontroller, closing timing, and deploying the bitstream to the target **Lattice ECP5 LFE5U-12F-6TG144C** FPGA hardware.

---

## 1. Hardware Target Specifications

- **Device**: Lattice ECP5 `LFE5U-12F`
- **Package**: 144-pin TQFP (`144TQFP`, 0.5 mm pitch)
- **Speed Grade**: `-6`
- **Operating Voltage**: 1.1V Core, 3.3V I/O Banks
- **Primary Clock**: 25.0 MHz onboard oscillator connected to dedicated PCLK pin `P63`
- **Physical Constraints**: `constraints/ecp5_144tqfp.lpf`

---

## 2. FPGA Resource Utilization Estimates

The SV-16 Rev A design is optimized for high resource efficiency on the 12K LUT ECP5:

| Resource Type | Available on 12F | Estimated Used | Utilization (%) |
| :--- | :--- | :--- | :--- |
| **LUT4 Logic Elements** | 12,000 | ~1,650 | ~13.8% |
| **Registers (Flip-Flops)**| 12,000 | ~780 | ~6.5% |
| **sysMEM DP16KD Blocks**| 32 blocks (576 Kb) | 8 blocks (128 Kb) | 25.0% |
| **sysDSP Multiplier Slices**| 28 slices | 1 slice (16×16 MUL) | 3.6% |
| **I/O Pins** | Up to 118 | 12 pins | ~10.2% |

Ample FPGA resources remain available for further memory expansion or additional accelerators in Rev B.

---

## 3. Toolchain Option A: Open-Source Flow (Project Trellis)

The open-source flow uses **Yosys**, **nextpnr-ecp5**, and **Project Trellis**:

### Step 1: Synthesis with Yosys
```bash
yosys -p "read_verilog -sv rtl/*.sv; synth_ecp5 -top sv16_top -json sv16_top.json"
```

### Step 2: Place & Route with nextpnr-ecp5
```bash
nextpnr-ecp5 \
    --12k \
    --package TQFP144 \
    --speed 6 \
    --json sv16_top.json \
    --lpf constraints/ecp5_144tqfp.lpf \
    --textcfg sv16_top_out.config
```

### Step 3: Bitstream Packing with ecppack
```bash
ecppack --compress sv16_top_out.config sv16_top.bit
```

### Step 4: Programming the FPGA
```bash
openFPGALoader -b ecp5 sv16_top.bit
```

Or using `make`:
```bash
make bitstream
make prog
```

---

## 4. Toolchain Option B: Commercial Flow (Lattice Diamond)

1. Launch **Lattice Diamond**.
2. Open or create project `sv16_rev_a.ldf`.
3. Select Part:
   - Family: `ECP5U`
   - Device: `LFE5U-12F`
   - Performance Grade: `-6`
   - Package: `TQFP144`
4. Add all SystemVerilog files from `rtl/*.sv`.
5. Add constraint file `constraints/ecp5_144tqfp.lpf`.
6. Run **Synthesize Design** (Synplify Pro or LSE).
7. Run **Translate Design**, **Map Design**, and **Place & Route Design**.
8. Verify Static Timing Analysis (STA) reports zero timing violations against the 25.0 MHz constraint (Period = 40.0 ns, slack > +15.0 ns typical).
9. Run **Export Files** to generate JEDEC / Bitstream (`sv16_top.bit`).
10. Open **Lattice Diamond Programmer** and write the bitstream to internal SRAM or onboard SPI Flash.

---

## 5. Physical Electrical Hardware Connection (Bench Test)

```text
 ┌─────────────────────────┐               ┌──────────────────────────┐
 │   Lattice ECP5 Board    │               │  External Motor Driver   │
 │   (LFE5U-12F TQFP144)   │               │   (e.g., L298N / DRV)    │
 │                         │               │                          │
 │  Pin P100 (PWM Out)     ├──────────────►│ IN1 / PWM (Speed)        │
 │  Pin P101 (DIR1)        ├──────────────►│ IN2 / DIR (Phase A)      │
 │  Pin P102 (DIR2)        ├──────────────►│ IN3 / DIR (Phase B)      │
 │  Pin P103 (FAULT_N)     │◄──────────────┤ Fault / Overtemp Out     │
 │                         │               │                          │
 │  GND                    ├───────────────┤ GND (Common Ground)      │
 └─────────────────────────┘               └────────────┬─────────────┘
                                                        │
                                                        ▼
                                                ┌───────────────┐
                                                │   DC Motor    │
                                                │   (12V / 24V) │
                                                └───────────────┘
```

### Critical Safety Precautions:
1. **Common Ground**: Ensure the FPGA digital ground and motor driver ground are securely connected.
2. **Flyback Diodes**: Ensure inductive kickback clamp diodes (flyback diodes) are present across motor terminals.
3. **Power Isolation**: Never power the motor directly from the FPGA development board's 3.3V or 5V rail; use an isolated bench power supply for the motor driver stage.
4. **Hardware Emergency Shutdown**: Verify that pulling pin `P103` (`motor_fault_n`) low immediately inhibits PWM output and halts motor rotation.
