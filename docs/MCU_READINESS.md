# SV-16 Rev B — How MCU-like is it? (and what is still FPGA-soft-core)

SV-16 started as a soft-core: a CPU written in SystemVerilog that runs from
block RAM inside an FPGA configuration. Rev B adds the parts that make a CPU
into a *microcontroller you can ship and field-update*. This page states
precisely which is which, so nobody has to guess — and lists the remaining gap
to a production-grade part.

---

## 1. Side-by-side

| MCU trait | Rev B status | Evidence |
| :--- | :--- | :--- |
| Non-volatile program store | **MCU-like** | external SPI NOR via `sv16_flash_ctrl`; images CRC-checked |
| Boot loader in hardware | **MCU-like** | `sv16_boot` + `sv16_startup`; runs without CPU help, handles blank/broken flash |
| Factory-resident firmware (can't be erased by the user) | **MCU-like** | monitor in boot ROM (`0xE000`), baked into the bitstream |
| Field reprogramming from a host | **MCU-like** | UART monitor `C` command + `scripts/sv16_mon.py`; `make upload` |
| Reset vector / vector table / stack setup | **MCU-like** | boot ROM at `0xE000`, vector table at `0x0020` in SRAM, SP from the image header |
| Reset cause register | **MCU-like** | `SYS_RSTCAUSE` (`0xF003`): pin, soft, fault, watchdog, boot-fail, flash-ok |
| Debug observability without a logic analyser | **MCU-like** | `SYS_DBG_PC/SP/SR/IR`, `SYS_FAULT_ADDR/CNT`, `SYS_CPU_STATE`, `SYS_SCRATCH0/1`, 32-bit cycle counter |
| Single toolchain recipe, reproducible build | **MCU-like** | `source scripts/sv16_venv.sh && make test bitstream`; the ROM is compiled into the image |
| Memory-mapped peripherals, one bus | **MCU-like** | 32 KB SRAM @ 0, 4 KB boot ROM @ 0xE000, 11 MMIO blocks @ 0xF000 |
| Interrupt controller with priority + vectors | **MCU-like** | 8 sources, priority, per-source enable, global enable, `RETI` |
| Watchdog | **MCU-like** | `sv16_wdt` at `0xF080`: windowed, key-protected, restarts the SoC, survives soft restarts, early-warning interrupt; verified end to end by `wdt_reset_tb` |
| Low-power / clock scaling | **soft-core gap** | one clock; build-time divider only, no runtime clock control, no sleep modes |
| Multiple clock options (PLL, 50–100 MHz) | **soft-core gap** | 25 MHz oscillator ÷ `SV16_CLKDIV`; no EHXPLLL instantiated |
| Hardware debug interface (JTAG/SWD, breakpoints, memory access while halted) | **soft-core gap** | single-step and halt exist (`SYS_CTRL`), but only from firmware/console — no JTAG TAP, no GDB stub |
| Memory protection / privilege levels | **soft-core gap** | no MPU; any code can write any MMIO register |
| In-application programming from the app | **partially MCU-like** | the app can drive `0xF0A0` itself, but the monitor/loader is the only tested path |
| C compiler and libraries | **soft-core gap** | assembler only (`scripts/sv16_as.py`); the `.c` file in `firmware/` is documentation |
| Pin muxing / alternate functions | **soft-core gap** | every port has one fixed function in the LPF; GPIO0/1 are plain ports |
| Cache / instruction prefetch | **soft-core gap** | not needed at this size (SRAM is single cycle) |
| DMA | **soft-core gap** | all transfers are CPU- or loader-driven |
| Verified on silicon | **gap** | simulation + place-and-route only; no board has run this bitstream |

---

## 2. What makes it a *system*, not a CPU demo

* **It boots by itself.** Power on → the hardware loader reads flash, verifies
  it, copies it to SRAM and releases the CPU at the application's entry point
  with the application's stack pointer. No JTAG, no host, no bitstream change.
* **It can be reprogrammed without tools other than a serial port.** The monitor
  is resident, survives any application bug, and the boot engine that loads
  images is hardware, so a bad image cannot make the board unrecoverable.
* **It tells you what went wrong.** Boot errors are code-graded (`-E0`…`-E7`),
  boot status is a readable register, and reset reasons are latched.
* **Its build is one command** and the ROMed monitor is part of the bitstream,
  so the artifact that is programmed matches the source tree exactly.

## 3. What is still "FPGA soft-core"

* You still flash the FPGA **configuration** with a JTAG tool
  (`make prog`, openFPGALoader). Changing *the SoC itself* is an FPGA operation,
  not an MCU operation. Applications, by contrast, are pure serial-port work.
* The CPU is not self-hosting: there is no C compiler, no linker script, no
  runtime library. Firmware is hand-written assembler (the assembler *is* the
  linker: `.org`, labels, `.ASCIIZ`).
* There is no protection between the application and the machine, no
  supervisor/user split, no memory that faults on illegal access.
* The core is not pipelined: roughly 8–10 clocks per instruction depending on
  the addressing mode. At 12.5 MHz that is well under 1 MIPS. This is an
  architecture-level choice (`ADR-002`), not a bug — but it is the reason the
  part is not aimed at compute-heavy work.
* Peripherals are fixed-function and fixed-pin; there is no mux matrix.

## 4. Gap list to a production-grade MCU experience

Ordered by what would unlock the most value per unit of risk:

1. **Timing margin / higher clock.** The design closes at 12.5 MHz
   (Fmax measured 14.68 MHz at speed grade 6). The critical path runs
   register file → ALU → flags → control-unit next-state *and* through
   `u_sys.illegal_pc`'s subtract; splitting the flag/branch decision with one
   extra FSM state or registering the fault address is what buys 25 MHz, and an
   `EHXPLLL` instance would then allow 40–50 MHz.
2. **A/B images with rollback.** Two image slots, a validity flag, and a
   "confirm this image" store from the application. The loader already has
   `BOOT_SRC_LO/HI` and `VERIFY-ONLY`, so the RTL change is small; the missing
   part is a policy (which slot wins, when to fall back).
3. **JTAG debug.** ECP5 has a usable TAP; a small "debug bridge" that maps JTAG
   shift-register words onto the bus (`SYS_CTRL.HALT` + `SYS_DBG_*` already
   give the core-side hooks) would give halt/resume, memory peek/poke and
   breakpoints — the single biggest quality-of-life gap versus an MCU.
4. **C toolchain.** A minimal `sv16-elf-gcc` backend or a small C compiler for
   the 8-register machine. Without it, this is an assembly-only platform.
5. **Signed/protected updates.** CRC16 (integrity) → add a keyed MAC or
   signature check in the loader before handing over.
6. **Brown-out and power-fail handling.** No BOR comparator or flash-safe
   power-loss path is present; a power cut during `C` destroys the image (the
   hardware recovers to the monitor, but the application is lost).
7. **Silicon bring-up.** Everything here is verified in simulation and
   place-and-route. Until a board runs it, treat pin electrical behaviour
   (drive strength, pull-ups, boot straps) and the flash part's real command set
   as unproven.

## 5. Honest summary

Rev B turns SV-16 from *a CPU you can instantiate* into *a device you can
program, run, update over a serial cable and recover when it breaks* — which is
the functional definition of a microcontroller. What it is not yet is a
*protected, debuggable, toolchain-supported* product: no JTAG debug, no A/B
updates, no memory protection, no C compiler, and no silicon validation.
The gap list above is the roadmap; each item is scoped so it can be added
without disturbing the SV-16 ISA or the existing boot flow.
