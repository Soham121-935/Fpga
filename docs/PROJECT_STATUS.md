# SV-16 Rev B — Project Status

SV-16 is a 16-bit microcontroller system for the Lattice ECP5
**LFE5U-12F-6TG144C**. Rev A built the CPU and its peripherals; **Rev B makes it
a programmable MCU**: it boots from flash by itself, can be reprogrammed over a
serial cable, and reports why it restarted.

---

## 1. Where it stands

| Area | State | Evidence |
| :--- | :--- | :--- |
| CPU and ISA | **frozen, unchanged in Rev B** | [ISA.md](ISA.md), [CPU_ARCHITECTURE.md](CPU_ARCHITECTURE.md) |
| Memory map | Rev B: 32 KB SRAM, 4 KB boot ROM at `0xE000`, 11 MMIO blocks present of 16 | [MEMORY_MAP.md](MEMORY_MAP.md) |
| Peripherals | GPIO ×2, timer, PWM (with hardware fault input), UART, SPI master, flash controller, watchdog, IRQ controller, system control, boot engine | [PERIPHERALS.md](PERIPHERALS.md) |
| Non-volatile program store | SPI NOR + hardware boot loader + CRC-checked images | [BOOT_AND_PROGRAMMING.md](BOOT_AND_PROGRAMMING.md) |
| Field update | ROM monitor over UART (`C`/`R`/`E`/`V`/`B`) + `make upload` | `scripts/sv16_mon.py` |
| Reset and startup | reset-cause register, soft reset, fault halt, auto-boot, RX-low escape to the monitor, **watchdog restart of a hung application** | [RESET_AND_CLOCK.md](RESET_AND_CLOCK.md) |
| Verification | **176 checks, 0 failures** across 6 Verilator suites + lint | [VERIFICATION.md](VERIFICATION.md) |
| Bitstream | builds, places, routes and packs for the target part; timing PASS at 12.5 MHz | [SYNTHESIS_AND_DEPLOYMENT.md](SYNTHESIS_AND_DEPLOYMENT.md) |
| Documentation | operator manual, memory map, peripherals, flow, verification, ADRs | `docs/` |

**Headline result:** `make bitstream` produces `build/sv16_top.bit` (275 KB,
LFE5U-12F-6TG144C, 30 % LUTs, 18 % FFs, timing PASS at 12.5 MHz) containing a
boot ROM monitor; program it, open a serial terminal, and the chip is a
microcontroller you can flash new firmware into with `make upload`.

---

## 2. Rev A → Rev B

| | Rev A | Rev B |
| :--- | :--- | :--- |
| Program storage | none (block RAM init files) | SPI flash + hardware boot loader |
| Firmware update | rebuild the bitstream | serial port, any host, no toolchain needed |
| Boot ROM | none | 4 KB monitor baked into the bitstream |
| Recovery from a bad image | none | automatic: hardware loader rejects it, monitor comes up |
| Recovery from a hung program | none | watchdog (`0xF080`) restarts the boot sequence and re-boots the application |
| SRAM | 8 K words | 16 K words |
| MMIO blocks | 4 | 11 present of 16 |
| Interrupts | ad-hoc lines | controller with enable/pending/priority + 8-entry vector table |
| Observability | none | reset cause, fault address/count, PC/SP/SR/IR, cycle counter, scratch registers that survive a soft reset |
| Pin constraints | four unplaceable sites | rebuilt from the device database; every port on a real I/O |
| Timing | not signed off | measured, constrained, and passing at the shipped clock |

The ISA, the instruction encodings and the programmer's model of the CPU are
untouched — an application written for Rev A runs on Rev B unchanged (provided
it does not rely on the old MMIO layout).

---

## 3. Rev B backlog, in priority order

1. **Timing headroom.** Raise the ceiling above 14.4 MHz (flag/branch FSM stage,
   register the fault address, then an `EHXPLLL`) so the part can run at 25 MHz
   or more.
2. **A/B images with rollback** so a failed update cannot lose the application.
3. **JTAG debug bridge** over the ECP5 TAP using the existing
   `SYS_CTRL.HALT` / `SYS_DBG_*` hooks.
4. **Silicon bring-up** on a real board: LEDs, console, upload, flash, watchdog,
   motor demo — the first time any of this touches hardware.
5. **Rev A testbench clean-up**: port or retire the older module-level tests so
   `make sim` covers the whole peripheral set again.

Full reasoning, and what "production grade" would still require, is in
[MCU_READINESS.md](MCU_READINESS.md).

---

## 4. Verification summary

| Suite | Checks |
| :--- | ---: |
| `wdt_tb` | 49 |
| `flash_ctrl_tb` | 48 |
| `boot_tb` | 24 |
| `soc_boot_tb` | 21 |
| `monitor_tb` | 20 |
| `wdt_reset_tb` | 14 |
| **Total** | **176 passing, 0 failing** |

Plus RTL lint (25 files clean) and whole-SoC Verilator elaboration.
