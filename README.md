# SV-16 Rev A — 16-Bit FPGA Microcontroller

SV-16 Rev A is a custom 16-bit microcontroller designed from the ground up in synthesizable SystemVerilog for FPGA deployment, specifically targeting the **Lattice ECP5 LFE5U-12F-6TG144C** FPGA.

The project encompasses the complete processor system:
- 16-bit RISC/load-store datapath with 8 general-purpose registers (`R0`–`R7`)
- Dedicated program counter (`PC`), instruction register (`IR`), status register (`SR`), and stack pointer (`SP`)
- 16-bit ALU (arithmetic, logic, shifts, multiply, divide) with Z, C, N, V flag updates
- Memory-mapped system bus with block RAM and integrated peripherals (GPIO, Timer, PWM, UART, SPI, I²C)
- Synthesizable RTL, comprehensive self-checking testbenches, and hardware verification suite

---

## Target Hardware Specification

- **Target FPGA**: Lattice Semiconductor ECP5
- **Part Number**: `LFE5U-12F-6TG144C`
- **Package**: 144-pin TQFP
- **Speed Grade**: -6
- **HDL Language**: SystemVerilog (`.sv`, `.v`)
- **Synthesis Target**: Lattice Diamond / Project Trellis (Yosys + nextpnr-ecp5)

---

## Repository Structure

```text
.
├── docs/                     # Architectural specifications and design records
│   ├── ARCHITECTURE_DECISIONS.md # Formal architectural decisions (ADRs)
│   ├── BUS_ARCHITECTURE.md      # Memory bus protocol, timing, and arbitration
│   ├── CPU_ARCHITECTURE.md      # CPU registers, datapath, and FSM lifecycle
│   ├── FPGA.md                  # Lattice ECP5 target specifics, clock, constraints
│   ├── ISA.md                   # Complete instruction set definition & opcodes
│   ├── MEMORY_MAP.md            # Memory spaces, address decoding, peripheral map
│   ├── OPEN_QUESTIONS.md        # Tracked architectural questions & ambiguities
│   ├── PERIPHERALS.md           # Specification for GPIO, Timer, PWM, UART, SPI, I2C
│   ├── PROJECT_STATUS.md        # Current phase status and roadmap tracking
│   ├── RESET_AND_CLOCK.md       # Reset domains, power-on sequencing, clocking
│   └── VERIFICATION.md          # Verification strategy, test plans, regression harness
├── rtl/                      # Synthesizable SystemVerilog source files
├── simulation/               # Simulation testbenches and test harnesses
│   ├── unit/                 # Unit testbenches for individual modules
│   └── regression/           # Full CPU and peripheral integration testbenches
├── firmware/                 # SV-16 assembly and C firmware
│   ├── drivers/              # Low-level peripheral drivers
│   └── examples/             # Application examples (GPIO, PWM, Motor control)
├── constraints/              # FPGA constraint files (.lpf for Lattice ECP5)
└── scripts/                  # Build, test, and verification automation scripts
```

---

## Architectural Principles

1. **No Invented Architecture**: Every feature, instruction encoding, register address, and bus protocol is explicitly documented in `docs/` before implementation.
2. **Layer-by-Layer Incremental Construction**: Bottom-up development from register file and ALU up through control unit, memory, peripherals, and firmware.
3. **Hardware Target Primacy**: All RTL is synthesizable for the Lattice ECP5 target; simulation models do not replace synthesizable logic.
4. **Automated Verification**: Every module has a dedicated self-checking testbench covering standard cases and corner cases.
