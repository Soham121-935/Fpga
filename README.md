# SV-16 Rev B — 16-Bit Microcontroller on a Lattice ECP5

SV-16 is a complete 16-bit microcontroller system in synthesizable
SystemVerilog for the **Lattice ECP5 `LFE5U-12F-6TG144C`**. It is not just a
CPU: it boots from SPI flash by itself, runs applications out of on-chip SRAM,
and can be reprogrammed over a plain serial port.

```
        ┌──────────────────────── LFE5U-12F-6TG144C ─────────────────────────┐
 25 MHz │  boot ROM (monitor)          SRAM 32 KB          MMIO 16 blocks    │
 ──────►│  ┌────────────┐   ┌──────────────────────┐  ┌──────────────────┐   │
        │  │ SV-16 CPU  │──►│ bus interconnect     │─►│ GPIO A/B, timer, │   │
 reset ─►│  │ 8 regs,    │   │ held req / qual ack  │  │ PWM+fault, UART, │   │
        │  │ 16-bit ALU │   │ held grant, 2 masters│  │ SPI, flash ctrl, │   │
        │  └────────────┘   └──────────────────────┘  │ IRQ, boot, system│   │
        │      ▲ boot loader (hardware) ─────────────────────────────────►   │
        └──────┼───────────────────────────────────────────────┬──────────┘
               │  streams + CRC-checks the image from flash    │ 4 SPI pins
        ┌──────┴──────────────────────────┐            ┌───────┴─────────┐
        │  SPI NOR flash — the firmware   │            │ UART console /  │
        │  (survives power cycles)        │            │ upload 115200   │
        └─────────────────────────────────┘            └─────────────────┘
```

## Quick start

```sh
source scripts/sv16_venv.sh    # fetches Verilator + Yosys + nextpnr + ecppack
make test                      # lint + 4 simulation suites (113 checks)
make bitstream                 # -> build/sv16_top.bit (boot ROM baked in)
make prog                      # openFPGALoader over JTAG
make app                       # build the example application image
make upload PORT=/dev/ttyUSB0  # erase + upload + verify over UART
```

A fresh board comes up as a monitor on the serial port at **115200 8-N-1**:

```
SV-16 monitor v1
> ?
  C<addr4><len4><crc4>  program flash (hex payload follows)
  R<addr4><len4>        read flash
  E<addr4>              erase 4 KB sector
  V<addr4>              CRC16 of the image at addr
  B                     verify and boot the image at 0
  ?                     this help
+
```

## What it can do

* **16-bit CPU** — 8 general-purpose registers, `LDI/JMP/CALL` 2-word forms,
  ALU with multiply/divide/shift, Z/C/N/V flags, interrupt-enable flag, trap on
  illegal opcodes ([ISA.md](docs/ISA.md)).
* **32 KB SRAM, 4 KB boot ROM, 16 MMIO blocks** — a documented map with no
  decode holes that can hang the bus ([MEMORY_MAP.md](docs/MEMORY_MAP.md)).
* **Peripherals** — two 16-bit GPIO ports with atomic set/clear, timer, PWM with
  a hardware motor-fault input, UART with FIFOs, SPI master, a full SPI-NOR flash
  controller (read/program/erase/CRC), interrupt controller with priority and an
  8-entry vector table ([PERIPHERALS.md](docs/PERIPHERALS.md)).
* **Real boot flow** — power-on → hardware loader validates and copies the flash
  image → CPU released at the application's entry point with the application's
  stack pointer; any failure falls back to the resident monitor
  ([BOOT_AND_PROGRAMMING.md](docs/BOOT_AND_PROGRAMMING.md)).
* **Field updates over UART** — CRC-checked images, per-byte acknowledgement,
  hex protocol a human can type, or `make upload` with `scripts/sv16_mon.py`.
* **Recoverable by design** — the monitor and the loader are in the FPGA
  configuration, so a broken application cannot brick the board; reset causes,
  fault addresses and a CPU state snapshot are all readable registers.

## Build targets

| Command | Result |
| :--- | :--- |
| `make test` | lint + all four Verilator suites |
| `make bitstream` | `build/sv16_top.bit` for the LFE5U-12F-6TG144C, timing PASS at 12.5 MHz |
| `make synth` | Yosys only (fast synthesizability check) |
| `make prog` | program the FPGA over JTAG |
| `make upload PORT=...` | program the *firmware* over the serial port |
| `make iss` | instruction-set simulator on the legacy ROM image |

Clocking: the 25 MHz oscillator is divided by `CLKDIV` (default 2 → 12.5 MHz,
the fastest configuration that closes timing on a speed-grade-6 part; the UART
divisor follows automatically so the console is always 115200).

## Repository layout

```text
docs/            operator manual, memory map, peripherals, flow, verification, ADRs
rtl/             24 SystemVerilog files: CPU, bus, memory, peripherals, SoC top
simulation/      Verilator testbenches (unit + regression) and the SPI flash model
firmware/        monitor assembler source, examples, drivers header, image packer
constraints/     ecp5_144tqfp.lpf — verified pin map for the TQFP-144 part
scripts/         assembler, image packer, RTL lint, TB runner, host programmer, toolchain
build/           generated: ROM image, firmware images, netlist, bitstream (untracked)
```

## Status, honestly

| | |
| :--- | :--- |
| Simulation | 113 checks, 0 failures (`flash_ctrl_tb`, `boot_tb`, `soc_boot_tb`, `monitor_tb`) |
| Synthesis / P&R | places, routes, packs for the target part; 30 % LUTs, 18 % FFs |
| Timing | 14.43 MHz Fmax measured; shipped at 12.5 MHz with margin; 25 MHz does not close |
| Silicon | **never run on hardware** — simulation and static timing only |

What is still missing for a production-grade MCU (watchdog in the reset path,
JTAG debug, A/B image slots with rollback, a C toolchain, silicon bring-up) is
listed with reasoning in
**[docs/MCU_READINESS.md](docs/MCU_READINESS.md)** — including an explicit
MCU-like vs. FPGA-soft-core comparison.

## Documentation

| Document | Contents |
| :--- | :--- |
| [BOOT_AND_PROGRAMMING.md](docs/BOOT_AND_PROGRAMMING.md) | boot flow, monitor protocol, image format, host tools, recovery |
| [MCU_READINESS.md](docs/MCU_READINESS.md) | what is MCU-like, what is still soft-core, gap list |
| [SYNTHESIS_AND_DEPLOYMENT.md](docs/SYNTHESIS_AND_DEPLOYMENT.md) | toolchain, build targets, utilisation, timing, pin map, programming |
| [MEMORY_MAP.md](docs/MEMORY_MAP.md) | address map, MMIO blocks, vector table |
| [PERIPHERALS.md](docs/PERIPHERALS.md) | register reference for every block |
| [BUS_ARCHITECTURE.md](docs/BUS_ARCHITECTURE.md) | protocol, arbitration, timing, adding a peripheral |
| [VERIFICATION.md](docs/VERIFICATION.md) | what is tested, what is not, bugs found |
| [RESET_AND_CLOCK.md](docs/RESET_AND_CLOCK.md) | clocking, reset sources, startup FSM |
| [ISA.md](docs/ISA.md) | instruction set, encodings, Rev B notes |
| [ARCHITECTURE_DECISIONS.md](docs/ARCHITECTURE_DECISIONS.md) | ADR-001..005 (Rev A), ADR-012..016 (Rev B) |
