# SV-16 Rev B — Completion Report and Blueprint

**What this document is.** A single place to see (a) the blueprint of the machine
as built, (b) everything that was done in this work stream, (c) what the system
can actually do today with the evidence for it, (d) what is still missing, and
(e) how to reproduce every number in this report.

**Scope of the work:** convert the repository from a *custom FPGA soft-core
prototype* into a *practical, MCU-style programmable system* on the Lattice ECP5
**LFE5U-12F-6TG144C**, without changing the SV-16 CPU architecture or ISA.

| | |
| :--- | :--- |
| Date of report | 2026-09-27 (last updated with the software-only roadmap in §8.2) |
| Branch | `arena/01a0ce9b-fpga` (this session) |
| Commits | `ec3581b` Rev B implementation · `62f432a` watchdog (P1) · `56a8b62` divider + full 25 MHz (P2) · `bd83c92` A/B slots (P3) · `7875b1e` P9 regression + ISA suite · `cdfa0c7` PLL clock (P2b) · `e177f7c` P8 latency + four instruction-level fixes · `3b282de`/`b7d7393` datasheet-verified budget (ADR-025) · `dfab015` datasheet cross-check |
| Remote state | On GitHub this work stream was renamed **`arena/01a0ce9b-fpga` → `arena/Rv2`**, so `arena/Rv2` holds the Rev B work up to `a07f62e`. This session pushed `arena/01a0ce9b-fpga` again (P1 watchdog, then P2 timing) and it is a direct descendant of `arena/Rv2`, so it can be fast-forwarded or merged without conflicts. |
| Test status | **473 checks, 0 failures** across 18 suites; RTL lint 26/26 clean |
| Resource budget | checked after place and route against the LFE5U-12F **datasheet** (12,144 LUT4 / 32 block RAM / 28 MULT / 2 PLL / 98 I/O), not against nextpnr's 25F-denominated table — `scripts/sv16_check_budget.py`, ADR-025 |
| Bitstream | `make bitstream` → `build/sv16_top.bit`, 295,665 bytes, **timing PASS at the full 25 MHz** (Fmax 44.70 MHz, ~79 % margin); `CLKSRC=pll PLLMHZ=37.5` → 292,752 bytes, PASS at 37.5 MHz (45.45 MHz) |
| Silicon | **never run on hardware** — simulation + static timing only. The software-only roadmap in §8.2 is written for exactly that constraint |

---

## 1. Executive summary

**Before.** A CPU with peripherals: firmware existed only as a block-RAM init
file, "programming the device" meant rebuilding and re-flashing the FPGA, there
was no program storage, no boot flow, no way to update firmware in the field, and
the pin constraints could not even be placed on the target package.

**Now.** A machine you can turn on, program over a serial cable, and recover when
it breaks:

* At power-on a **hardware boot loader** reads a CRC-checked image out of an
  external SPI NOR flash, verifies it, copies the payload into SRAM, and releases
  the CPU **at the application's own entry point with the application's own stack
  pointer**. No JTAG, no host, no bitstream change.
* A **resident monitor** (934 words, boot ROM `0xE000-0xE3A5`, compiled into the
  bitstream) provides `C/R/E/V/B/?` over UART at **115200 8-N-1**, so a new
  application image can be uploaded from any PC with a serial port
  (`make upload`) — or typed in by hand.
* Whatever goes wrong, the chip **falls back to the monitor** and says why
  (graded boot errors, reset-cause register, fault address, CPU state snapshot).
* If the *application* hangs, a **windowed, key-protected watchdog** (`0xF080`)
  restarts the whole boot sequence, sets `SYS_RSTCAUSE.WDT`, re-boots the image
  and keeps guarding it. The application cannot disarm it, and a breadcrumb left
  in the surviving scratch registers survives the restart.
* The whole flow is **reproducible from one script** (`scripts/sv16_venv.sh`) and
  the bitstream **places, routes and packs for the real part with timing passing**.

**Measured results** (not estimates):

| Metric | Value |
| :--- | :--- |
| FPGA utilization | 9,407 / **12,144** LUT4 (**77 %** of what the datasheet guarantees for a 12F), 4,772 FFs, 18/32 block RAMs (56 %), 1 multiplier, 52/98 I/O |
| Timing | Fmax **44.70 MHz** measured at 25 MHz (36.29 pre-route, ~79 % margin) and **45.45 MHz** at the PLL's 37.5 MHz (~21 % margin); both PASS |
| Bitstream | **295,665 bytes** (`build/sv16_top.bit`), boot ROM baked in |
| Verification | **473 checks, 0 failures** across 18 suites (`49+48+41+35+27+27+26+23+21+21+21+21+20+14+13+11+11+8`), plus lint (26/26) + whole-SoC elaboration |
| Interrupt latency | **11-31 cycles** request → handler over a 24-point arrival sweep (1 cycle in the controller, 6 in the entry sequence), 16 cycles for a 3-word handler + `RETI` — measured and enforced by `irq_latency_tb` (ADR-023) |
| Code | 26 RTL files / 7,469 lines, 11 scripts / 2,488 lines, 29 testbench files / 6,033 lines, 15 documents / 2,731 lines + this report |

**The one honest headline:** this is functionally a microcontroller now, it
runs at the full 25 MHz the board gives it, and a failed firmware update rolls
back by itself, but it has not run on silicon, has no JTAG debug, no memory
protection and no C compiler. Those are listed with effort estimates in
section 8.

---

## 2. Blueprint — what the machine looks like

### 2.1 System

```text
                    ┌──────────────────── LFE5U-12F-6TG144C ─────────────────────┐
  25 MHz osc ──────►│ clk_25m ──► ÷SV16_CLKDIV ──► clk  (12.5 MHz shipped)         │
  (pin 133)         │                                                            │
                    │   ┌───────────────┐        ┌──────────────────────────┐     │
  reset ───────────►│   │   SV-16 CPU   │        │  boot ROM  4 KB          │     │
  (pin 134, PU)     │   │  8 regs x 16b │◄──────►│  monitor, 0xE000-0xE7FF  │     │
                    │   │  16-bit ALU   │        │  (in the bitstream)      │     │
  UART console      │   │  Z C N V IE   │        └──────────────────────────┘     │
  ◄────────────────►│   └───────┬───────┘                                        │
  rx 73 / tx 74     │           │  held req until ack                            │
                    │   ┌───────▼─────────────────────────┐   ┌───────────────┐  │
                    │   │  bus interconnect               │   │  SRAM 32 KB   │  │
                    │   │  qualified acks, held grants,   │◄─►│ 0x0000-0x3FFF │  │
  SPI NOR flash     │   │  2 masters (CPU + boot loader)  │   │ code/data/SP  │  │
  (application)     │   └───────┬─────────────────────────┘   │ vector table  │  │
  sck 110 cs 111    │           │                             └───────────────┘  │
  mosi 112 miso 113 │           │  0xF000-0xF0FF: 16 blocks x 16 registers        │
  ◄────────────────►│   ┌───────▼─────────────────────────────────────────────┐   │
                    │   │ sys | GPIO A | timer | PWM | UART | SPI | flash      │   │
                    │   │ GPIO B | (wdt reserved) | IRQ ctrl | boot engine     │   │
                    │   └──────────────────────────────────────────────────────┘  │
  motor PWM/ dirs   │                                                             │
  pwm 88, dir 89/102│      GPIO A/B (32 pins)   SPI0 expansion (4 pins)          │
  fault 103 (PU)    │      LEDs 39/40/41/44     (sck/cs/mosi/miso 114-117)        │
                    └─────────────────────────────────────────────────────────────┘
```

### 2.2 Where programs live, and how they start

```text
  HOST (PC)                      DEVICE (ECP5)                SPI NOR FLASH
  ─────────                      ─────────────                ──────────────
  scripts/sv16_as.py             ┌──────────────┐
    monitor.s  ──► monitor.hex ──│ boot ROM     │  (baked into the
                                 │ 0xE000       │   bitstream at build time)
                                 └──────┬───────┘
  sv16_as.py + sv16_fwpack.py           │
    myapp.s ──► myapp_img.hex           │            ┌──────────────┐
        │                               │  C/R/E/V/B/K image: header│
        └── make upload ────────────────┼───────────►│ + payload    │
            (UART 115200, dot-acked)    │            │ CRC-checked  │
                                        │            └──────┬───────┘
                                        │                   │ power-on / reset
                                        │            ┌──────▼─────────────────┐
                                        │            │  HARDWARE BOOT LOADER  │
                                        │            │  slot A or B? records  │
                                        │            │  magic? hdr CRC? pld   │
                                        │            │  CRC? length? timeouts │
                                        │            └───┬────────────────┬───┘
                                        │      valid     │                │  invalid
                                        │                ▼                ▼
                                        │        copy payload into    enter monitor
                                        │        SRAM, release CPU    (0xE000)
                                        │        at image entry, SP          │
                                        ▼        from the image header        ▼
                                 you program it again over the same UART ──────┘
```

### 2.3 Memory map

```text
 0x0000 ┌──────────────────────────────┐
        │ SRAM 16 K words (32 KB)      │  application code, data, stack
        │  · 0x0000-0x001F  code       │  (SP resets to 0x3FFE, grows down)
        │  · 0x0020-0x0027  IRQ vector │  ← 8 handler addresses, filled by the app
        │  · 0x3FFE         stack top  │
 0x4000 ├──────────────────────────────┤
        │ unmapped (huge hole)         │  reads return 0x0000, still acked
 0xE000 ├──────────────────────────────┤
        │ BOOT ROM 2 K words (4 KB)    │  monitor: 0xE000-0xE3A5 (934 words)
 0xE800 ├──────────────────────────────┤
        │ unmapped                     │
 0xF000 ├──────────────────────────────┤
        │ MMIO 16 blocks × 16 registers│  11 blocks present (MMIO_PRESENT 0x7FF)
        │ 0 sys  1 GPIO A  2 timer     │  block 8 = watchdog: arm it, feed it,
        │ 3 PWM  4 UART    5 SPI       │  feed it wrongly, or it restarts the SoC
        │ 6 flash 7 GPIO B 9 IRQ       │  blocks 11-15 reserved
        │ A boot engine  8 watchdog    │
 0xF100 ├──────────────────────────────┤
        │ unmapped / reserved          │
 0xFFFF └──────────────────────────────┘
```

### 2.4 Pins actually used (52 of the 98 bonded TQFP-144 I/O, all `LVCMOS33`)

```text
  pin 133 ◄── clk_25m            39 40 41 44 ◄── led[3:0]
  pin 134 ◄── ext_rst_n (PU)     45-52, 97-99, 104-108 = gpio_a[15:0]
  73 / 74  =  uart_rx / uart_tx  135 136 139-143 128 124-127 1-4 = gpio_b[15:0]
  110 111 112 113 = flash sck/cs_n/mosi/miso      (application flash)
  114 115 116 117 = spi0  sck/cs_n/mosi/miso      (expansion bus)
  88 = pwm_out (DRIVE=16)   89/102 = motor_dir1/2   103 = motor_fault_n (PU)

  UART is the only Rev A pin assignment that survived; the other four Rev A
  sites (P63 clk, P60 rst, P38 led0, P100 pwm) are not bonded I/O on this
  package at all, so the whole map was rebuilt from the prjtrellis device
  database.
```

---

## 3. Task completion scoreboard

The original request had seven items. Status of each:

| # | Requested | Status | Where / evidence |
| :--- | :--- | :--- | :--- |
| 1 | Thorough architecture analysis of `sv16_top.sv`, `sv16_core.sv`, `sv16_bus_interconnect.sv`, `sv16_ram.sv`, `docs/MEMORY_MAP.md`, `docs/ISA.md`, `docs/SYNTHESIS_AND_DEPLOYMENT.md`, `Makefile` | **[x] DONE** | analysis drove ADR-012..016 and the Rev B map; findings recorded in `docs/ARCHITECTURE_DECISIONS.md` and `docs/VERIFICATION.md` §2 (5 real defects found and fixed) |
| 2 | Design/implement missing MCU infrastructure: persistent program storage, bootloader/startup loading from NVM, field reprogramming path, UART firmware upload, robust reset/startup, clear memory map, optional GPIO expansion + peripheral organization | **[x] DONE** | SPI NOR + `sv16_boot` + `sv16_startup` + monitor + `sv16_mon.py`; map in `docs/MEMORY_MAP.md`; GPIO B added, 16-block MMIO scheme |
| 3 | Preserve the SV-16 CPU architecture and ISA unless there is compelling reason to extend | **[x] DONE — ISA untouched** | no encoding changed; only bug fixes (decoder port mapping, LDI write-back, held bus request, the I-format source operand + latched writeback per ADR-020, and the control-instruction encodings per ADR-022, which restored `HALT`/`EI`/`DI`/`RETI` to the encodings the decoder always used). See `docs/ISA.md` §7 |
| 4 | Stay synthesizable for LFE5U-12F-6TG144C and compatible with the pin constraints | **[x] DONE — and proven** | places, routes, packs; timing PASS at the full 25 MHz (Fmax 44.70 MHz in the current tree) and at 37.5 MHz with the PLL; LPF rebuilt (the Rev A file could not have placed) |
| 5 | Documentation: capabilities, how to program, how to update firmware, how to build + flash | **[x] DONE** | `BOOT_AND_PROGRAMMING.md` (operator manual), `SYNTHESIS_AND_DEPLOYMENT.md`, plus 6 rewritten docs |
| 6 | Keep builds reproducible via the existing flow; update Makefile/scripts as needed | **[x] DONE** | `make test`, `make bitstream`, `make upload`, `make app`; toolchain bootstrap + synthesis script; generated Yosys script kept for audit |
| 7 | No cosmetic changes — real architectural work | **[x] DONE** | 9 new RTL modules, rewritten interconnect, new bus protocol, boot flow, hardware loader; every change is functional |
| — | Deliverable: RTL/script changes | **[x] DONE** | 25 RTL files, 7 new scripts, Makefile rework |
| — | Deliverable: updated documentation | **[x] DONE** | 16 documents (2 new, 8 rewritten) |
| — | Deliverable: firmware loading/boot flow | **[x] DONE** | hardware loader + monitor protocol + host tool + image format, all tested end to end |
| — | Deliverable: "MCU-like vs FPGA-soft-core" explanation | **[x] DONE** | `docs/MCU_READINESS.md` (side-by-side table) |
| — | Deliverable: what remains missing for production-grade MCU | **[x] DONE** | `docs/MCU_READINESS.md` §4 + this report §8 |

**Everything requested is implemented and verified in simulation. Nothing
requested was deferred** — the remaining work in section 8 is what a
*production* part would additionally need (debug, protection, toolchain,
silicon), which the request explicitly asked to be enumerated rather than built.

---

## 4. Everything that was built (inventory)

### 4.1 RTL — 26 files, 7,469 lines (`rtl/`)

| Module | Lines | What it is | New in Rev B |
| :--- | ---: | :--- | :---: |
| `sv16_pkg.sv` | 278 | memory map, MMIO blocks, register offsets, opcodes, IRQ vectors | rewritten |
| `sv16_core.sv` | 452 | CPU integration: datapath, memory interface, interrupt/trap entry | rewritten |
| `sv16_control_unit.sv` | 570 | FSM; holds `req` until `ack` (wait-state capable); `S_DIV_WAIT` holds DIV/MOD until the divider finishes | rewritten |
| `sv16_decoder.sv` | 162 | register port selection fixed (STORE data, PUSH source) | rewritten |
| `sv16_alu.sv` | 241 | arithmetic/logic/shift/mul/div, flags; **iterative multi-cycle divider** (ADR-018) | **rewritten** |
| `sv16_regfile.sv` | 48 | 8 × 16-bit registers | — |
| `sv16_status_reg.sv` | 97 | Z/C/N/V/IE | — |
| `sv16_pc.sv` | 58 | program counter | — |
| `sv16_bus_interconnect.sv` | 270 | qualified acks, held grants, reply routing, 16 MMIO blocks | **rewritten** |
| `sv16_ram.sv` | 56 | 16 K words, MAP-based | sized up |
| `sv16_rom.sv` | 42 | boot ROM, `$readmemh` from `SV16_ROM_INIT_FILE` | **new** |
| `sv16_crc16.sv` | 49 | CRC16-CCITT, shared by loader/monitor/packer | **new** |
| `sv16_uart.sv` | 367 | 8-N-1 + FIFOs; reset divisor parameterised by the SoC clock | rewritten |
| `sv16_spi_master.sv` | 235 | generic SPI shift engine (mode control, divider) | **new** |
| `sv16_spi.sv` | 132 | SPI0 expansion-bus register block | **new** |
| `sv16_flash_ctrl.sv` | 1,076 | full SPI-NOR controller: ID, read stream, page program, sector erase, CRC over a range, wait states | **new** |
| `sv16_boot.sv` | 542 | hardware boot loader: header parse, CRC verify, SRAM streaming, register block | **new** |
| `sv16_startup.sv` | 223 | reset/boot sequencer, reset causes, monitor escape | **new** |
| `sv16_sys.sv` | 207 | system control, reset cause, fault capture, debug regs, cycle counter, scratch | **new** |
| `sv16_irq_ctrl.sv` | 101 | enable/pending/priority controller | **new** |
| `sv16_wdt.sv` | 265 | windowed, key-protected watchdog: preset/prescaler/window registers, magic-word feed, early-warning interrupt, `LOCK`, reset request into the startup FSM | **new** |
| `sv16_gpio.sv` | 89 | atomic set/clear, sync'd inputs (2 ports) | reused ×2 |
| `sv16_timer.sv` / `sv16_pwm.sv` | 119 / 118 | timer with compare IRQ; PWM with hardware fault input | — |
| `sv16_pll.sv` | 158 | optional `EHXPLLL` system clock (ADR-021) with a delay-based simulation model behind `ifdef VERILATOR` | **new** |
| `sv16_top.sv` | 519 | SoC top: clock source + divider, reset, 2 SPI ports, 32 GPIO, LED/motor pins | rewritten |

### 4.2 Scripts — 7 new/reworked (`scripts/`, ~1,470 lines)

| Script | Lines | Purpose |
| :--- | ---: | :--- |
| `sv16_venv.sh` | 59 | one-command toolchain bootstrap: Verilator 5.49, Yosys 0.69, nextpnr-ecp5 0.11.1, ecppack |
| `sv16_synth.sh` | 138 | the whole bitstream flow: Yosys → nextpnr → ecppack, with the ROM macro and clock divider injected, logs and timing report kept |
| `sv16_run_tb.sh` | 66 | generic Verilator testbench builder/runner; tees every run to `build/vlt/<top>/run.log` and **fails unless the suite prints `RESULT: PASS`** |
| `sv16_mon.py` | 349 | host programmer for the monitor: erase + upload + verify + boot + terminal, self-clocking, `--dry-run` works without hardware |
| `sv16_fwpack.py` | 329 | image packer (header, CRCs, `.bin`/`.hex`/`_img.hex`/`_words.hex`/`.txt`) |
| `sv16_rtl_lint.py` | 175 | structural RTL lint, zero external dependencies |
| `sv16_as.py` | 350 | two-pass assembler (pre-existing, used to build the monitor and examples); now range-checks the nine-bit immediate and accepts negative literals instead of silently masking them |

### 4.3 Firmware — 1,300 lines (`firmware/`)

| File | Lines | Purpose |
| :--- | ---: | :--- |
| `monitor/monitor.s` | 714 | the ROM monitor: console, hex protocol, flash program/read/erase/verify, boot |
| `monitor/` build output | — | `build/rom/monitor.hex` (1,115 words) + `.lst` disassembly |
| `tests/isa_regress.s` | 117 | ISA regression program run by `isa_tb` — branches, immediate arithmetic, stack, subroutine; it is what found the ADR-020 defects |
| `examples/motor_test.s` | 41 | demo application used by the upload test |
| `examples/motor_control.c` | 62 | intent/documentation (no C compiler yet) |
| `examples/wdt_hang.s` | 62 | deliberately hangs *after* arming the watchdog — the image `wdt_reset_tb` boots to prove the recovery path |
| `drivers/sv16_hardware.h` | ~420 | complete Rev B register map, bit fields, image header, CRC helper, inline helpers incl. `sv16_wdt_arm()`/`sv16_wdt_feed()`/`sv16_wdt_lock()` |
| `bootrom.hex` | — | legacy Rev A ROM image, kept for `make iss` |

### 4.4 Documentation — 16 files, ~2,400 lines

| Document | Status | Contents |
| :--- | :--- | :--- |
| `BOOT_AND_PROGRAMMING.md` | **new** | boot flow, monitor protocol, image format, host tools, IAP registers, recovery checklist |
| `MCU_READINESS.md` | **new** | MCU-like vs FPGA-soft-core table, gap list to production |
| `PROJECT_STATUS.md` | rewritten | Rev A→Rev B comparison, backlog, verification summary |
| `SYNTHESIS_AND_DEPLOYMENT.md` | rewritten | toolchain, targets, utilization, timing (with the three placer measurements), pin map, programming, reproducibility |
| `MEMORY_MAP.md` | rewritten | Rev B map, MMIO blocks, system registers, vector table, Rev A→B changes |
| `PERIPHERALS.md` | rewritten | register reference for all 11 blocks + programming idioms |
| `BUS_ARCHITECTURE.md` | rewritten | protocol rules, arbitration, timing diagrams, how to add a slave |
| `RESET_AND_CLOCK.md` | rewritten | clock divider, baud derivation, reset causes, startup FSM, fault behaviour |
| `VERIFICATION.md` | rewritten | what runs, the 11 defects the suites caught, what is *not* verified |
| `ISA.md` | updated | unchanged ISA + Rev B notes on entry, interrupts, trap |
| `ARCHITECTURE_DECISIONS.md` | extended | ADR-012 (boot/storage), 013 (field update), 014 (map), 015 (CPU fixes), 016 (interrupts), 017 (watchdog in the reset path), 018 (multi-cycle divide, full 25 MHz), 019 (A/B images with rollback), 020 (I-format source operand + latched ALU result for writeback) |
| `OPEN_QUESTIONS.md` | rewritten | OQ-01..10 resolved, OQ-13 (watchdog) closed by ADR-017, OQ-14 (slots) closed by ADR-019, OQ-15 (interrupt latency) closed by ADR-023, OQ-19 added (PLL silicon validation by ADR-024); OQ-11/12/16..19 still open |
| `FPGA.md` | rewritten | device facts, measured usage, clocking, pin rules |
| `README.md` | rewritten | quick start, blueprint, capability list, honest status |
| `CPU_ARCHITECTURE.md`, `CODING_STANDARDS.md` | unchanged | still accurate (ISA/CPU untouched) |

### 4.5 Verification assets (26 files, ~5,240 lines)

`simulation/unit/sv16_flash_model.sv` (273) behavioural SPI NOR — 64 KB, 256 B
pages, 4 KB sectors, `tPROG`/`tERASE` in clocks, JEDEC `0xEF4018`;
`simulation/unit/periph_tb.svh` (97) the shared peripheral harness (negedge bus
tasks, `check`, a per-suite watchdog and the `RESULT: PASS` contract);
`monitor_tb.sv` (521), `wdt_tb.sv` (367), `flash_ctrl_tb.sv` (272),
`boot_tb.sv` (265), `soc_boot_tb.sv` (240), `wdt_reset_tb.sv` (188), plus the
rewritten `sv16_alu_tb`/`sv16_timer_tb`/`sv16_pwm_tb`/`sv16_gpio_tb`/
`sv16_uart_tb`/`sv16_ram_tb`, `isa_tb`, `control_tb`, `irq_latency_tb` and
`pll_clock_tb` — 18 suites registered in `make sim`, 473 checks, all of them run
by `scripts/sv16_run_tb.sh`, which now refuses to report a pass unless the suite
itself says `RESULT: PASS`.

### 4.6 Constraints

`constraints/ecp5_144tqfp.lpf` — **rebuilt**: every `sv16_top` port located on a
real I/O site of the TQFP-144 part, verified against the prjtrellis device
database. Header documents the four invalid Rev A sites and the pin table.

---

## 5. What it can do today

### 5.1 As a microcontroller

| Capability | How, exactly | Proof |
| :--- | :--- | :--- |
| Boot a program from non-volatile storage with no host attached | hardware loader validates magic + header CRC + payload CRC + length, copies the payload to SRAM, sets PC/SP from the header | `boot_tb` 24 checks, `soc_boot_tb` 21 checks |
| Recover from any bad/blank flash | loader reports the reason in `BOOT_ERR` (magic / hdr CRC / payload CRC / timeout / length / flash / verify) and the sequencer enters the monitor | `boot_tb` (corrupt-image cases), `soc_boot_tb` |
| Update firmware over a serial cable | `C<addr><len><crc>` + hex payload with per-byte `.` acks, then `V` to verify and `B` to boot | `monitor_tb` 20 checks end to end |
| Do that from a script | `make upload PORT=/dev/ttyUSB0` (packs, erases, uploads, verifies) | `sv16_mon.py upload --dry-run` output: `C00000064DB88`, image CRC `0xDB88` |
| Do it from a human terminal | same protocol, typed by hand (`?` prints the command list) | protocol documented in `BOOT_AND_PROGRAMMING.md` |
| Tell you why it restarted | `SYS_RSTCAUSE`: pin / soft / fault / WDT / no-image / image-loaded; sticky bits, W1C | `docs/RESET_AND_CLOCK.md` §2 |
| Update itself from the application | application drives `BOOT_CTRL.START` (+`VERIFY_ONLY`, `SRC_LO/HI`) and polls `BOOT_STAT` | `sv16_hardware.h:sv16_boot_image()` |
| Survive a soft reset with context | `SYS_SCRATCH0/1` are never cleared by reset | `docs/MEMORY_MAP.md` §3 |
| **Recover by itself from a hung application** | arm the watchdog (3 stores: `WDT_PRESET`, `WDT_WINDOW`, keyed `WDT_CTRL`), feed it from the main loop; on expiry the hardware restarts the boot sequence, sets `RSTCAUSE.WDT`, re-boots the image and re-arms for a full period | `wdt_reset_tb` **14 checks**: a real hanging image is booted from flash, bites, restarts, runs again, bites again — with no host involved |
| Be warned before it bites | `WDT_CTRL.IRQ_EN` raises IRQ 6 `MARGIN` ticks before expiry so the handler can save a breadcrumb in scratch that survives the restart | `wdt_tb` 49 checks |
| Catch a runaway loop that feeds the watchdog non-stop | windowed feeding: a feed earlier than `WINDOW` ticks after the previous one is itself a fault | `wdt_tb` |
| Make the watchdog un-disarmable | `LOCK` freezes enable/period/prescaler/window; only the external reset pin clears the block | `wdt_tb` |

### 5.2 As a CPU (unchanged from Rev A, by design)

8 × 16-bit GPRs; `LDI`/`JMP`/`CALL` two-word forms; ALU with add/sub/logic/shift/
multiply/divide; Z C N V flags plus a global IE bit; branches ±128 words; stack
with `PUSH`/`POP`/`CALL`/`RET`; trap on illegal opcodes; interrupts with a
priority controller and an 8-entry RAM vector table; `RETI`.
**No instruction encoding changed** — Rev A applications run unchanged.
DIV and MOD are the one execution-time change: they now run on the ALU's
iterative divider (18 cycles instead of 1) because the combinational version was
a 68 ns critical path that capped the whole SoC at 12.5 MHz (ADR-018).

### 5.3 Peripherals (11 MMIO blocks, 16 registers each)

GPIO A + GPIO B (atomic `SET`/`CLR`, synchronised inputs) · timer with compare
interrupt · PWM with a **hardware fault input** (`motor_fault_n` shuts the output
down without CPU help) · UART with 4-byte FIFOs (console + upload) · SPI master
for expansion · a full **SPI-NOR flash controller** (ID, read stream, page
program, sector erase, CRC over a range, internal `tPROG`/`tERASE` waits) ·
interrupt controller · system control/debug · boot engine · **watchdog** (windowed, keyed, restarts the SoC, early-warning interrupt).

### 5.4 Observability (the "why is my board doing that" layer)

`SYS_DBG_PC/SP/SR/IR`, `SYS_FAULT_ADDR`, `SYS_FAULT_CNT`, `SYS_CPU_STATE`,
`SYS_STAT` (halted / image ok / boot fail / in monitor / fault halt),
a free-running 32-bit cycle counter, `BOOT_STAT`/`BOOT_ERR`, and hardware
single-step (`SYS_CTRL.HALT` + `STEP`).

---

## 6. Verification evidence

### 6.1 Simulation (re-run at the commit referenced above)

| Suite | Checks | Failures | What it proves |
| :--- | ---: | ---: | :--- |
| `div_tb` | **41** | 0 | the iterative divider (ADR-018): handshake rules, arithmetic incl. `0/5`, `0xFFFF/1`, `0x8000/0x8000`, divide-by-zero per OQ-04, and that everything else is still single-cycle |
| `sv16_alu_tb` | **35** | 0 | the ALU as an instruction sees it: every arithmetic/logic op, the flag rules (MUL overflow sets C *and* V), shift counts, and `DIV`/`MOD` cross-checked against a software model |
| `sv16_uart_tb` | **27** | 0 | the UART at the bit level: divisor, TX/RX FIFOs and level fields, framing, loopback, overrun and frame-error flags, and that an RMW of `CTRL` cannot latch the self-clearing FIFO-clear pulses |
| `sv16_pwm_tb` | **23** | 0 | PWM 0's waveform (period/duty measured edge to edge), 0 %/100 % extremes, the fault input stopping the output, dead-time, interrupt |
| `sv16_timer_tb` | **21** | 0 | timer 0's register set: prescaler, reload, up/down counting, compare/overflow interrupts, W1C flags, one-shot, enable gating |
| `sv16_gpio_tb` | **20** | 0 | direction/data/interrupt registers, the two-clock input synchroniser on every pin, read-modify-write of `DATA`, pin-change interrupt |
| `sv16_ram_tb` | **11** | 0 | the SRAM at the CPU's geometry: read-first behaviour, byte-write masking, address wrapping, `INIT_FILE` loading |
| `isa_tb` | **11** | 0 | **the ISA itself**: `firmware/tests/isa_regress.s` run on the core — reset state, every conditional branch taken and not taken, `ADDI`/`SUBI` values including a negative immediate, PUSH/POP, CALL/RET, stack balance, `DIV`/`MOD` quotient and remainder, final self-loop. Found the two ADR-020 defects and the `DIV`/`MOD` writeback defect (ADR-022) |
| `control_tb` | **27** | 0 | the control group (`NOP`/`HALT`/`EI`/`DI`/`RETI`) at all three levels that can disagree: the assembler must emit five distinct words (it emitted `0x0000` for all five until ADR-022), the decoder must select exactly one and trap a reserved sub-opcode, and the core must set/clear `SR.IE`, really stop on `HALT`, wake into a handler on an enabled interrupt with `RETI` returning after the `HALT`, and stay halted while interrupts are disabled |
| `irq_latency_tb` | **13** | 0 | the interrupt path end to end and its budget (ADR-023): the controller's contribution, a 24-point arrival sweep across `DIV`/`NOP`/`JMP`, the interrupted `DIV` still completing, `RETI` leaving `SP` balanced, the pending bit clearing on acknowledge |
| `wdt_tb` | **49** | 0 | exact period `(PRESET+1)×2^PRESC`, one-cycle reset request, self-rearm, keyed writes, magic-word feeds, integer prescaler, early-warning interrupt timing, windowed feeding, `LOCK` freezing, W1C flags, pin-only clearing |
| `wdt_reset_tb` | **14** | 0 | **the recovery path end to end**: boot a hanging image out of flash → watchdog bites → `RSTCAUSE.WDT` → boot sequence restarts → image re-boots → hangs again → caught again → external pin clears the block |
| `flash_ctrl_tb` | **48** | 0 | every flash command, wait states, CRC over a range, error flags |
| `boot_tb` | **26** | 0 | header parse, both CRCs, streaming to SRAM, verify-only, corrupt-image rejection, clean "no image anywhere" verdict |
| `slot_tb` | **57** | 0 | **the A/B policy end to end** (ADR-019) with the loader, flash controller and flash model wired as the SoC wires them: pick order, TRIED written before the CPU is released, a restart inside the trial rolling back to the other slot, a confirmed update retiring the previous image, a torn record refused, `BOOT_CTRL[4]` bypassing the policy |
| `soc_boot_tb` | **21** | 0 | reset → loader → SRAM content → CPU released at the right entry/SP |
| `monitor_tb` | **21** | 0 | the entire field-update story over a bit-banged UART: upload, read-back, erase, verify, `K` confirm, boot, the uploaded app actually running and driving GPIO/PWM/direction |
| `pll_clock_tb` | **8** | 0 | the PLL clock configuration (ADR-021): reset held while the PLL is unlocked, the generated clock measured at 1.5x the reference, the UART divisor derived from 37.5 MHz, and a real monitor frame decoded at that divisor |
| **Total** | **473** | **0** | `make sim` — every suite is in the Makefile list, and the runner fails any suite that does not print `RESULT: PASS` |

Plus: `sv16_rtl_lint.py` **26/26 files clean** (multiple drivers, latches, missing
resets, incomplete case) and Verilator elaboration of the whole SoC clean.

### 6.2 Implementation (measured, reproducible)

| Stage | Result |
| :--- | :--- |
| Yosys `synth_ecp5` | 8,509 logic LUT4, 4,771 FFs, 18 `DP16KD`, 1 `MULT18X18D` (default build, `build/sv16_yosys.log`) |
| nextpnr-ecp5 (`--12k --package TQFP144 --speed 6 --freq 25`) | places, routes, **timing PASS at 25 MHz**; device utilisation 9,623/24,288 LUT4 (39 %), 4,771 FF (19 %), 18 `DP16KD`, 1 `MULT18X18D`, 52 I/O; the PLL build uses 9,040 LUT4 (37 %) |
| ecppack `--compress` | `build/sv16_top.bit`, **303,962 bytes** |
| Placer comparison | heap default = **43.73 MHz** at 25 MHz (PASS, 34.05 pre-route) · **44.87 MHz** at the PLL's 37.5 MHz (PASS; measured before the ADR-024 feedback fix, whose PLL build now measures 45.45 MHz) · heap `timingweight 50` = 13.15/14.18 MHz (worse) · SA = fails to place chains |
| 25 MHz attempt **before** ADR-018 | 14.38 MHz → FAIL; a constant-folding experiment (`a/b`, `a%b` → constants) measured 44.31 MHz — which is how the real culprit was found |
| Mapping sensitivity (measured, ADR-021) | adding two constant-driven `SYS_STAT` bits to the P9 tree — no logic, nothing observable — took Yosys 7,569 → 8,382 LUT4 and Fmax 46.17 → 43.73 MHz. The flow is deterministic for a given source tree, but absolute numbers move ~10 % whenever the sources change |

### 6.3 Real defects found and fixed by this work

1. A slave `ack` not qualified by its own transfer → the CPU could latch another
   master's read data (corrupted instruction fetches during a load).
2. Bus master starvation → arbitration rewritten to held grants, loader lower
   priority.
3. Boot loader `START` level-sensitive → "boot storm"; now latched, self-clearing.
4. Multi-cycle `boot_go` → `sv16_startup` emits a single-cycle pulse.
5. Flash read streaming off-by-one + a monitor hex helper printing one nibble short.
6. Decoder mis-mapped `STORE` data / `PUSH` source registers (silent corruption in Rev A).
7. Four pin constraints that could never have placed on the target package.
8. **Watchdog feed swallowed by its own tick** — at `PRESC = 0` the counter's
   decrement overrode the reload a feed had just requested, so feeding the
   watchdog at its most common setting silently did nothing (caught by `wdt_tb`).
9. **A 16-bit period cannot share a register with an 8-bit key** — the first cut
   stored the whole keyed value as the period, so a 32-tick watchdog ran for
   23,048 clocks. `CTRL` is keyed; the period registers are frozen by `LOCK`.
10. **The window was enforced on the first feed**, which would have restarted a
    correctly written application one period after it armed the watchdog; the
    first period after `ENABLE` is now exempt.
11. **The 25 MHz timing failure was misdiagnosed in four documents** (this report
    included): the blamed path was the CPU's flag/branch logic and
    `u_sys.illegal_pc`'s decrement, with "split the flag decision" as the fix. The
    nextpnr critical-path report showed the actual path was the ALU's
    combinational **divider** — hence one constant-folding experiment moving Fmax
    from 14.68 to 44.31 MHz. Multi-cycle DIV/MOD then delivered the full 25 MHz.
12. **`ADDI`/`SUBI` committed the wrong value** (caught by the new `isa_tb`, the
    first program in the repository ever to execute an immediate arithmetic
    instruction): the I-format read port was decoded from the immediate field, so
    the first operand was `R{imm[8:6]}` instead of `Rd`, *and* writeback
    re-evaluated the ALU after its operand select had dropped, so the committed
    value was `Rd + R_{Rs2 field}`. The 277 checks that existed before it, and
    every shipped firmware image, never noticed — production code always writes
    `LDI` + `ADD`. Both halves are fixed and the result is now latched for
    writeback (ADR-020), which also took the ALU off the critical path.
13. **Every control instruction assembled to `NOP`** — `EI` could not enable
    interrupts, `RETI` could not return from a handler, `HALT` could not stop the
    core, because `scripts/sv16_as.py` emitted `0x0000` for all five mnemonics
    while the decoder has decoded five distinct encodings since Rev B. No
    firmware in the repository used any of them, which is exactly why it went
    unnoticed; `control_tb` now checks the encoding, the decoder and the
    behaviour (ADR-022).
14. **`HALT` did not halt** — with the encoding fixed, the core still walked
    straight through `S_HALTED` because `!halt_req` was already true; the
    instruction now latches (`sw_halt`) and an enabled interrupt or a debugger
    step resumes it (ADR-022).
15. **`DIV`/`MOD` never reached their wait state** — `S_EXECUTE` tested the
    generic ALU case first, so `is_ext_alu` won the race and `S_DIV_WAIT` was
    dead: the divider ran, and then writeback stored a stale latched result. The
    ALU unit tests all passed, because the divider itself was always correct
    (ADR-022).
16. **The PLL's feedback input was wired to the wrong source** — `CLKINTFB` drove
    `CLKFB` while the configuration bits selected the external `CLKOP` return
    path. nextpnr derives the output frequency from the `FEEDBK_PATH` string and
    cannot see the netlist mismatch, and simulation substitutes a behavioural
    oscillator, so this was found by comparing the primitive against prjtrellis'
    own `ecppll` output rather than by a test. Fixing it moved the PLL build from
    41.40 to **45.45 MHz** and 301,006 to 292,752 bytes (ADR-024, OQ-19).

---

## 7. Reproduction — every number above, from scratch

```sh
git clone https://github.com/Soham121-935/Fpga.git && cd Fpga
git checkout arena/Rv2                 # or this session's arena/01a0ce9b-fpga

source scripts/sv16_venv.sh            # Verilator + Yosys + nextpnr + ecppack
make test                              # lint + 473 checks           (~6 min)
make bitstream                         # Yosys→PnR→pack, timing report (~2 min)
make prog                              # program the FPGA over JTAG
make upload PORT=/dev/ttyUSB0          # program the *firmware* over UART
python3 scripts/sv16_mon.py upload --dry-run     # no hardware needed
```

Notes: `build/` is untracked and excluded from snapshots — `make firmware`
regenerates the ROM and images in seconds; compile logs
(`build/sv16_yosys.log`, `build/sv16_nextpnr.log`, `build/sv16_top.timing.json`)
and the generated Yosys script (`build/sv16_synth.ys`) are kept so any build can
be audited or replayed.

---

## 8. What is left

### 8.1 Before this can be called "proven" (blocking, small)

| # | Item | Why it matters | Effort | Definition of done |
| :--- | :--- | :--- | :--- | :--- |
| B1 | **Silicon bring-up** — LEDs, console banner, `?`, upload, flash ops, motor demo on a real board | Everything so far is simulation; electrical reality (flash part, oscillator, reset RC, drive strength, boot straps) is untested | 1-2 days with a board | banner at 115200, `make upload` succeeds, application survives a power cycle |
| B2 | **Pin map vs. actual board** — the LPF was derived from the device database, not from a Rev A schematic; only UART pins were kept | A bitstream whose pins don't match the board looks like a dead board | hours, given a schematic | LPF re-derived from the board netlist and re-verified by `make bitstream` |
| B3 | **Flash part check** — `FLASH_ID` must read `0xEF4018`; other parts may need command/wait tuning | The whole programming story depends on it | hours | `FLASH_ID`/`ID2` verified on the real part; timings re-checked |

### 8.2 The software-only track (no board required)

Everything below runs, is simulated, and produces measurable numbers **without
hardware**. Ordered so that each step makes the next one easier to see and test.
"Session" = one focused work period; estimates are for this repository's style of
work (implementation + tests + docs + REPORT sync), not for a fresh project.

#### S0 — A virtual board: the SoC on your terminal  *(the enabling step)*

| | |
| :--- | :--- |
| **What** | `make vboard` builds a Verilator model of the whole SoC with the flash model attached and bridges the UART to stdin/stdout, so the real monitor runs in a terminal: banner, `?`, `R`, `V`, `C` upload, `B` boot. `sv16_mon.py` gains a `--transport sim` so the *existing* host tools drive it, and a scripted session becomes a regression suite. |
| **Why first** | It turns "everything is simulation" from a limitation into an interface: you can type at the machine and flash it today, and every later item (upload speed, C compiler, debug stub) gets an end-to-end demo instead of a waveform. It also becomes the cheapest possible integration test. |
| **Deliverable** | `simulation/vboard/` harness + `Makefile` target; `sv16_mon.py --transport sim`; one scripted session checked into `simulation/regression/vboard_tb.sv` (upload → verify → boot → run). |
| **Effort** | 1 session. |

#### S1 — Upload throughput, and tests for the host tools  *(P10, OQ-17)*

| | |
| :--- | :--- |
| **What** | Today: 2 hex characters per byte, each byte acknowledged individually → **~5 KB/s**. Plan: a binary `U` command that (a) sends raw bytes instead of hex (2x), (b) acknowledges per 64/256-byte block instead of per byte (~1.5x), (c) optionally steps the console baud up (115200 → 460800) for the transfer and back afterwards (up to 4x). Staged into a RAM buffer, programmed page-wise, verified with the per-block CRC16 the loader already knows. The existing `C` command stays as the always-works fallback, and A/B slots + rollback stay underneath. |
| **Why** | A 20 KB image currently takes ~4 minutes, which makes the update path painful to use and painful to test. It is the most visible "is this a real MCU?" difference that does not need a compiler. |
| **Deliverable** | Monitor `U` command; `sv16_mon.py --fast`; measured throughput printed by the tool and recorded in VERIFICATION; the negotiated-fallback path tested (host that cannot do `U` still works). Plus **host-tool unit tests** (`tests/test_as.py`, `test_fwpack.py`, `test_mon.py`) — golden assembler corpus, packer round-trip, protocol framing — because a hand-rolled protocol is exactly what breaks silently. |
| **Effort** | 1–2 sessions. |

#### S2 — Write applications in C  *(P5, OQ-16 — the biggest capability gap)*

Broken into sub-steps so each lands green; the ISA is **not** touched until the
work proves it is necessary (the user constraint stands: preserve the ISA unless
there is a compelling reason).

| Step | Deliverable | Notes |
| :--- | :--- | :--- |
| **S2a** | ABI + language-subset decision as an ADR: `int` = 16-bit, `char` = 8-bit, pointers 16-bit, stack-relative locals, args in registers then stack, one translation unit at a time, absolute (non-relocatable) images | Documents what is *not* supported (floats, varargs, bitfields) so the tool does not silently miscompile |
| **S2b** | `scripts/sv16_cc.py`: a C subset compiler → `.s` → the existing assembler. Expressions (precedence, short-circuit), `if`/`while`/`for`/`do`, `break`/`continue`, functions with parameters and returns, locals, globals, arrays, pointers, `char` strings, compound assignment, `switch` (compare-chain), casts | Pure Python, no new dependencies, so it stays reproducible in this flow |
| **S2c** | Runtime: `crt0` (SP from the image header, `.bss` zeroed, `.data` copied), `putc`/`puts`/`printf` subset, `memcpy`/`memset`/`strlen`, 16-bit `mul`/`div`/`mod` helpers, `__aeabi`-style names so the compiler can emit them blindly | Runs from the boot ROM today; the monitor's `puts` is the reference for the UART path |
| **S2d** | Build integration: `make cc C=firmware/apps/motor.c` → image + `.map` + `.lst`; the same flash/upload flow as today | The map file is what makes a 32 KB part workable |
| **S2e** | Regression: a C conformance program (every operator, control-flow shape, pointer case, call depth) compiled and executed in a new `c_tb` suite against expected register/memory values; plus one real C application (closed-loop motor demo: PWM + timer + interrupts) and its simulation test | This is where codegen bugs get caught — the same way the ISA suite found ADR-020/022 |
| **S2f** | *Only if S2e shows it is needed*: ISA extension in the reserved `EXT_ALU` sub-opcodes `3'b101`–`3'b111` (register-indirect `JMP Rn` / `CALL Rn`, for function pointers and jump tables), with its own ADR, assembler support and ISA regression rows | Deferred by default; absolute `CALL imm16` covers everything except indirect calls |

Effort: 3–5 sessions total (S2b and S2e dominate).

#### S3 — Debug a running machine

| Step | Deliverable | Notes |
| :--- | :--- | :--- |
| **S3a** | **UART debug stub** in the monitor: a subset of the GDB Remote Serial Protocol (`?`, `g`, `G`, `m`, `M`, `c`, `s`, `Z0`) so *stock `gdb`* can attach with `target remote /dev/ttyUSB0` and set breakpoints, read memory, step | No new hardware, no new FPGA primitive, works with the console that already exists. Uses the existing `SYS_DBG_*`/halt hooks. Tested in simulation with a Python RSP client — and it is also the natural way to debug the C compiler's output |
| **S3b** | **JTAG debug bridge** on the ECP5 `JTAGG` primitive: ER1 scan chain (instruction `0x32`) into a shift-register bridge driving halt/step/peek/poke, driven from OpenOCD; a behavioural `JTAGG` model behind `` `ifdef VERILATOR `` for simulation | Feasible in this toolchain — the primitive and its ER1/ER2 instructions are proven by LiteX's `ECP5JTAG`, `tomverbeure/ecp5_jtag` and `fpgacapZero`. The 4 TAP pins are **dedicated** on this package (datasheet §4.3.2), so it costs logic only (~300–800 of the ~2,700 free LUT4) |
| **Why this order** | S3a is a day or two of work with zero new primitives and pays off during S2; S3b is the "real MCU" interface but its last mile (a JTAG adapter on a board) is unverifiable here |

Effort: 1–2 sessions for S3a, 1–2 for S3b.

#### S4 — Field integrity: know what happened, and who wrote it

| Step | Deliverable | Notes |
| :--- | :--- | :--- |
| **S4a** | Threat-model ADR: what an attacker with physical access can actually do (they can read the bitstream, so a key baked into it is obfuscation, not secrecy), what CRC16 does and does not protect, and which option is honest — keyed MAC with an in-bitstream key, or nothing claimed at all | Writing this *before* the code is the point: the alternative is a "signed update" claim that does not survive one afternoon with a logic analyser |
| **S4b** | Keyed image authentication in the loader + `sv16_fwpack.py --key` + `make upload --key`, with the format versioned so old images still boot | Only if S4a picks it; the CRC stays as the integrity check underneath |
| **S4c** | **Fault record**: on illegal instruction, zero-vector trap, or watchdog bite, snapshot the PC/SR/SP and a small breadcrumb ring into a reserved flash sector; the monitor gains `L` to dump it after a restart | This is the single most MCU-like missing feature for field use: after a crash on a customer's machine you can read back *where* it died |

Effort: 1–2 sessions.

#### S5 — Capacity and architecture (optional; decide with numbers in hand)

| Item | What it would buy | Cost |
| :--- | :--- | :--- |
| **RAM remap (OQ-11)** | Position-independent images: SRAM at `0x0000` with the boot ROM moved to the top, like an MCU's flash alias. Removes the "everything is linked at 0" constraint that limits image layout and slot freedom | 1 session + ADR; touches the bus decoder and the boot path |
| **More SRAM** | 32 KB → 48/56 KB using the 14 free `DP16KD` blocks (28 KB free of the datasheet's 32) | Small RTL change, but it is *the* resource this part is short of; needs a memory-map update and loader changes |
| **Vector table in ROM (OQ-12)** | A default table in the boot ROM that jumps to a software dispatcher, so an application that forgets its vectors cannot trap into arbitrary code | Half a session |
| **Console/interrupt polish** | An interrupt-driven monitor (no polling), a ring-buffer console, `printf` through the C runtime | Small, quality-of-life |

#### What is *not* on this track

* **Brown-out / power-fail handling (P7)** — needs a voltage monitor in front of the
  FPGA (or a supply supervisor), i.e. hardware. Firmware cannot see a rail dip.
* **Silicon validation of the PLL (OQ-19)** and **"does the placed design fit a real
  12F bin" (OQ-20)** — both are board questions by definition.
* **Pin-map and flash-part checks (B2/B3)** — need the schematic and the part.

### 8.3 Completed (kept for the record)

| # | Item | Evidence |
| :--- | :--- | :--- |
| P11 | **PCB blueprint**: complete component list with part numbers and specifications, power tree and sequencing argument, full 144-pin device/net table, connection circuit diagram, bring-up and acceptance plan, layout guidance, and nine tracked board-level open items | `BOARD.md`, printable as **`BOARD.pdf`** (`make board-pdf`, `scripts/sv16_board_pdf.py`) (+ generated appendix `board/TQFP144_PINOUT.md`, verified by `make lint` through `scripts/sv16_board_pins.py --check`); the device pin database `board/ecp5_tqfp144.json` was cross-built from the prjtrellis database for LFE5U-12F and the Lattice BSDL FPGA-MD-02097, and it exposed the Master-SPI/GPIOA pad sharing that shaped the two-flash architecture (BOARD.md §6.4) |
| P1 | Watchdog in the reset path — windowed, key-protected, restarts the SoC; `RSTCAUSE.WDT` live, `MMIO_PRESENT = 0x7FF` | `sv16_wdt.sv` + ADR-017; 49 unit + 14 system checks |
| P2 | Timing headroom: the real critical path was the ALU's combinational divider, not the flag/branch path | Multi-cycle DIV/MOD + `S_DIV_WAIT` (ADR-018), Fmax 14.68 → 44.70 MHz measured, shipped at the full 25 MHz |
| P2b | Optional `EHXPLLL` system clock at 37.5 MHz, reset gated on lock, all derived constants follow it; feedback path corrected in ADR-024 | ADR-021/024, `pll_clock_tb` (8 checks), 292,752-byte bitstream at 45.45 MHz |
| P3 | A/B images with a trial period, hardware rollback, `make upload-slot` / `make commit` | ADR-019, `slot_tb` (57 checks) |
| P8 | Interrupt latency measured and bounded: 11–31 cycles request → handler over a 24-point sweep, 1 in the controller, 6 in the entry sequence; 16 cycles for a 3-word handler + `RETI` | ADR-023, `irq_latency_tb` (13 checks) enforcing the bounds |
| P9 | Peripheral + ISA regression: 18 suites / 473 checks / 0 failures, runner refuses a suite without `RESULT: PASS` | VERIFICATION.md; the ISA suite found the ADR-020 and ADR-022 defects |
| — | Twelve instruction-level and RTL defects found and fixed (control encodings, `HALT`, `DIV`/`MOD` writeback, `ADDI`/`SUBI`, the PLL feedback tap, the watchdog feed, …) | REPORT §6.3, ADR-020/022/024 |

### 8.4 Tracked design questions still open

See `docs/OPEN_QUESTIONS.md`: RAM remap (OQ-11), vector table placement (OQ-12),
C toolchain and ISA extension (OQ-16 — S2a answers it), update throughput
(OQ-17 — S1 answers it), real board pin assignment (OQ-18 — BOARD.md §6 is the
answer for this part and package), PLL loop-filter and
feedback validation on silicon (OQ-19), and whether this exact placement fits a
real 12F bin (OQ-20). OQ-14 (image slots) is closed by ADR-019, OQ-13 (watchdog)
by ADR-017, OQ-15 (interrupt latency) by ADR-023 and the PLL feedback wiring by
ADR-024. Board-level items that need a physical board (dynamic current, regulator
passives, configuration time, CH340C wiring, USB-C sink behaviour, adapter pinout,
EMC, mechanics, the J5 pad sharing) are tracked as **OQ-B1…OQ-B9** in `BOARD.md`
§13.2.

---

## 9. Honest limitations (read this before believing anything)

1. **No silicon.** Every claim here is simulation plus static timing analysis.
   The first board will very likely find something (pin, polarity, timing, the
   flash part's command set).
2. **25 MHz, ~1 MIPS-class core.** The core is multi-cycle by design
   (ADR-002): DIV/MOD take 18 cycles (ADR-018), and the ISA is unchanged from
   Rev A.
3. **No protection.** No MPU, no privilege levels: any code can write any MMIO
   register, including the flash controller and the reset logic.
4. **Rollback depth is one generation.** A/B keeps the previously confirmed
   image; a second failed update overwrites the oldest one. The records are only
   written by the loader (an application asks; it does not program the flash
   itself), updates are not signed, and slot B needs the UART or an external
   programmer because the monitor's `C` command addresses 64 KB.
5. **Assembly only.** The assembler is also the linker (`.org`). The C example in
   `firmware/` documents intent, it does not compile.
6. **Update path is intentionally simple.** ASCII, CRC16, per-byte ack, no
   compression, no resume, no flow control.
7. **The work exists under two branch names on the remote.** `arena/Rv2` is the
   renamed session branch (Rev B up to `a07f62e`); `arena/01a0ce9b-fpga` is this
   session's branch and is one commit ahead (`b747fb3`, this report). They are
   not divergent — pick one and fast-forward the other, or open the PR from the
   newer one.

---

## 10. Appendix — quick references

### 10.1 Monitor commands (UART 115200 8-N-1)

| Command | Meaning |
| :--- | :--- |
| `C<addr4><len4><crc4>` | program: erase sectors, then receive `len` bytes of hex; `.` per byte, `+OK`/`-E4` |
| `R<addr4><len4>` | read flash as hex text |
| `E<addr4>` | erase the 4 KB sector containing `addr` |
| `V<addr4>` | CRC16 of the image at `addr` → `=<crc4>` |
| `B` | verify and boot the image at 0 |
| `?` | command list |

Errors: `-E0` unknown command, `-E1` bad hex, `-E4` upload CRC, `-E5` flash stuck,
`-E6` boot timeout, `-E7` image rejected. Hex may be upper or lower case.

### 10.2 Firmware image format (produced by `scripts/sv16_fwpack.py`)

```
0x00 4 magic "SV16"          0x10 2 entry address (word)
0x04 2 header version 1      0x12 2 stack pointer (0 -> 0x3FFE)
0x06 2 payload words         0x14 2 header CRC16  (over 0x00-0x13)
0x08 8 image name            0x16 2 payload CRC16
0x18 8 reserved              0x20.. payload, 16-bit words, little endian
```

CRC16-CCITT: poly `0x1021`, init `0xFFFF`, no reflection, no final XOR — bit
identical in RTL, monitor, packer and host tool.
Example (`motor_test`): 34 words / 100 bytes, header CRC `0x2E37`, payload CRC
`0xE083`, whole-image CRC `0xDB88` (what `V0000` returns).

### 10.3 Key registers you will touch first

| Address | Name | Use |
| :--- | :--- | :--- |
| `0xF000` | `SYS_ID` | read `0x1602` to confirm the SoC is alive |
| `0xF002` | `SYS_STAT` | which way did it boot: image ok / boot fail / in monitor / fault |
| `0xF003` | `SYS_RSTCAUSE` | why did it restart (W1C) |
| `0xF004-0xF007` | `SYS_DBG_PC/SP/SR/IR` | where is the CPU / what state |
| `0xF008/0xF009` | `SYS_FAULT_ADDR/CNT` | illegal-opcode diagnostics |
| `0xF040-0xF044` | UART0 | console + upload |
| `0xF060-` | FLASH | `STAT` (bit 5 = ID ok, bit 7 = busy), `ID` = `0xEF40` |
| `0xF0A0/0xF0A1` | `BOOT_CTRL` / `BOOT_STAT` | start/abort a load, poll result |
| `0xF0AA` | `BOOT_ERR` | graded boot failure reason |

### 10.4 Where to read more

`docs/BOOT_AND_PROGRAMMING.md` (how to program) ·
`docs/MCU_READINESS.md` (MCU-like vs soft-core + gap list) ·
`docs/SYNTHESIS_AND_DEPLOYMENT.md` (build, timing, pins, programming) ·
`docs/VERIFICATION.md` (what is tested, what is not) ·
`docs/MEMORY_MAP.md`, `docs/PERIPHERALS.md` (register level) ·
`docs/ARCHITECTURE_DECISIONS.md` (ADR-012…016) ·
`docs/OPEN_QUESTIONS.md` (what is still undecided).
