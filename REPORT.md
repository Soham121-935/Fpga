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
| Date of report | 2026-09-24 |
| Branch | `arena/01a0ce9b-fpga` (this session) |
| Commits | `ec3581b` "Rev B: turn SV-16 from a soft-core into a programmable MCU", `a07f62e` docs correction |
| Remote state | The same work is on the branch **`arena/Rv2`** on `origin` (it appears the session branch was renamed there). `arena/01a0ce9b-fpga` is the branch this session pushes to. |
| Test status | **113 checks, 0 failures** across 4 suites; RTL lint 24/24 clean |
| Bitstream | `make bitstream` → `build/sv16_top.bit`, 275,119 bytes, **timing PASS** at 12.5 MHz |
| Silicon | **never run on hardware** — simulation + static timing only |

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
* The whole flow is **reproducible from one script** (`scripts/sv16_venv.sh`) and
  the bitstream **places, routes and packs for the real part with timing passing**.

**Measured results** (not estimates):

| Metric | Value |
| :--- | :--- |
| FPGA utilization | 7,358 / 24,288 LUT4 (**30 %**), 4,448 FFs (18 %), 18/56 block RAMs, 1 multiplier, 52 I/O |
| Timing | Fmax **14.43 MHz** measured; shipped at **12.5 MHz ⇒ PASS** with ~15 % margin |
| Bitstream | **275,119 bytes** (`build/sv16_top.bit`), boot ROM baked in |
| Verification | **113 checks, 0 failures** (`48 + 24 + 21 + 20`), plus lint + whole-SoC elaboration |
| Code | 24 RTL files / 5,933 lines, 11 scripts / 2,261 lines, 16 documents / ~2,400 lines |

**The one honest headline:** this is functionally a microcontroller now, but it has
not run on silicon, has no JTAG debug, no watchdog in the reset path, no A/B
image rollback and no C compiler. Those are listed with effort estimates in
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
        │                               │   C/R/E/V/B│ image: header│
        └── make upload ────────────────┼───────────►│ + payload    │
            (UART 115200, dot-acked)    │            │ CRC-checked  │
                                        │            └──────┬───────┘
                                        │                   │ power-on / reset
                                        │            ┌──────▼─────────────────┐
                                        │            │  HARDWARE BOOT LOADER  │
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
        │ MMIO 16 blocks × 16 registers│  10 blocks present (MMIO_PRESENT 0x6FF)
        │ 0 sys  1 GPIO A  2 timer     │  block 8 = watchdog (RTL exists, unwired)
        │ 3 PWM  4 UART    5 SPI       │  blocks 11-15 reserved
        │ 6 flash 7 GPIO B 9 IRQ       │
        │ A boot engine                │
 0xF100 ├──────────────────────────────┤
        │ unmapped / reserved          │
 0xFFFF └──────────────────────────────┘
```

### 2.4 Pins actually used (52 of 197, all `LVCMOS33`)

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
| 3 | Preserve the SV-16 CPU architecture and ISA unless there is compelling reason to extend | **[x] DONE — ISA untouched** | no encoding changed; only bug fixes (decoder port mapping, LDI write-back, held bus request). See `docs/ISA.md` §7 |
| 4 | Stay synthesizable for LFE5U-12F-6TG144C and compatible with the pin constraints | **[x] DONE — and proven** | places, routes, packs; timing PASS at 12.5 MHz; LPF rebuilt (the Rev A file could not have placed) |
| 5 | Documentation: capabilities, how to program, how to update firmware, how to build + flash | **[x] DONE** | `BOOT_AND_PROGRAMMING.md` (operator manual), `SYNTHESIS_AND_DEPLOYMENT.md`, plus 6 rewritten docs |
| 6 | Keep builds reproducible via the existing flow; update Makefile/scripts as needed | **[x] DONE** | `make test`, `make bitstream`, `make upload`, `make app`; toolchain bootstrap + synthesis script; generated Yosys script kept for audit |
| 7 | No cosmetic changes — real architectural work | **[x] DONE** | 9 new RTL modules, rewritten interconnect, new bus protocol, boot flow, hardware loader; every change is functional |
| — | Deliverable: RTL/script changes | **[x] DONE** | 24 RTL files, 7 new scripts, Makefile rework |
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

### 4.1 RTL — 24 files, 5,933 lines (`rtl/`)

| Module | Lines | What it is | New in Rev B |
| :--- | ---: | :--- | :---: |
| `sv16_pkg.sv` | 278 | memory map, MMIO blocks, register offsets, opcodes, IRQ vectors | rewritten |
| `sv16_core.sv` | 452 | CPU integration: datapath, memory interface, interrupt/trap entry | rewritten |
| `sv16_control_unit.sv` | 546 | FSM; now holds `req` until `ack` (wait-state capable) | rewritten |
| `sv16_decoder.sv` | 162 | register port selection fixed (STORE data, PUSH source) | rewritten |
| `sv16_alu.sv` | 186 | arithmetic/logic/shift/mul/div, flags | — |
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
| `sv16_gpio.sv` | 89 | atomic set/clear, sync'd inputs (2 ports) | reused ×2 |
| `sv16_timer.sv` / `sv16_pwm.sv` | 119 / 118 | timer with compare IRQ; PWM with hardware fault input | — |
| `sv16_top.sv` | 480 | SoC top: clock divider, reset, 2 SPI ports, 32 GPIO, LED/motor pins | rewritten |

### 4.2 Scripts — 7 new/reworked (`scripts/`)

| Script | Lines | Purpose |
| :--- | ---: | :--- |
| `sv16_venv.sh` | 59 | one-command toolchain bootstrap: Verilator 5.49, Yosys 0.69, nextpnr-ecp5 0.11.1, ecppack |
| `sv16_synth.sh` | 135 | the whole bitstream flow: Yosys → nextpnr → ecppack, with the ROM macro and clock divider injected, logs and timing report kept |
| `sv16_run_tb.sh` | 48 | generic Verilator testbench builder/runner |
| `sv16_mon.py` | 295 | host programmer for the monitor: erase + upload + verify + boot + terminal, self-clocking, `--dry-run` works without hardware |
| `sv16_fwpack.py` | 278 | image packer (header, CRCs, `.bin`/`.hex`/`_img.hex`/`_words.hex`/`.txt`) |
| `sv16_rtl_lint.py` | 175 | structural RTL lint, zero external dependencies |
| `sv16_as.py` | 340 | two-pass assembler (pre-existing, used to build the monitor and examples) |

### 4.3 Firmware — 1,181 lines (`firmware/`)

| File | Lines | Purpose |
| :--- | ---: | :--- |
| `monitor/monitor.s` | 714 | the ROM monitor: console, hex protocol, flash program/read/erase/verify, boot |
| `monitor/` build output | — | `build/rom/monitor.hex` (934 words) + `.lst` disassembly |
| `examples/motor_test.s` | 41 | demo application used by the upload test |
| `examples/motor_control.c` | 62 | intent/documentation (no C compiler yet) |
| `drivers/sv16_hardware.h` | 364 | complete Rev B register map, bit fields, image header, CRC helper, inline helpers |
| `bootrom.hex` | — | legacy Rev A ROM image, kept for `make iss` |

### 4.4 Documentation — 16 files, ~2,400 lines

| Document | Status | Contents |
| :--- | :--- | :--- |
| `BOOT_AND_PROGRAMMING.md` | **new** | boot flow, monitor protocol, image format, host tools, IAP registers, recovery checklist |
| `MCU_READINESS.md` | **new** | MCU-like vs FPGA-soft-core table, gap list to production |
| `PROJECT_STATUS.md` | rewritten | Rev A→Rev B comparison, backlog, verification summary |
| `SYNTHESIS_AND_DEPLOYMENT.md` | rewritten | toolchain, targets, utilization, timing (with the three placer measurements), pin map, programming, reproducibility |
| `MEMORY_MAP.md` | rewritten | Rev B map, MMIO blocks, system registers, vector table, Rev A→B changes |
| `PERIPHERALS.md` | rewritten | register reference for all 10 blocks + programming idioms |
| `BUS_ARCHITECTURE.md` | rewritten | protocol rules, arbitration, timing diagrams, how to add a slave |
| `RESET_AND_CLOCK.md` | rewritten | clock divider, baud derivation, reset causes, startup FSM, fault behaviour |
| `VERIFICATION.md` | rewritten | what runs, the 5 bugs the suite caught, what is *not* verified |
| `ISA.md` | updated | unchanged ISA + Rev B notes on entry, interrupts, trap |
| `ARCHITECTURE_DECISIONS.md` | extended | ADR-012 (boot/storage), 013 (field update), 014 (map), 015 (CPU fixes), 016 (interrupts) |
| `OPEN_QUESTIONS.md` | rewritten | OQ-01..10 resolved (with Rev B changes flagged), OQ-11..18 newly open |
| `FPGA.md` | rewritten | device facts, measured usage, clocking, pin rules |
| `README.md` | rewritten | quick start, blueprint, capability list, honest status |
| `CPU_ARCHITECTURE.md`, `CODING_STANDARDS.md` | unchanged | still accurate (ISA/CPU untouched) |

### 4.5 Verification assets (5 files, 1,681 lines)

`simulation/unit/sv16_flash_model.sv` (273) behavioural SPI NOR — 64 KB, 256 B
pages, 4 KB sectors, `tPROG`/`tERASE` in clocks, JEDEC `0xEF4018`;
`flash_ctrl_tb.sv` (272), `boot_tb.sv` (265), `soc_boot_tb.sv` (240),
`monitor_tb.sv` (521).

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

### 5.2 As a CPU (unchanged from Rev A, by design)

8 × 16-bit GPRs; `LDI`/`JMP`/`CALL` two-word forms; ALU with add/sub/logic/shift/
multiply/divide; Z C N V flags plus a global IE bit; branches ±128 words; stack
with `PUSH`/`POP`/`CALL`/`RET`; trap on illegal opcodes; interrupts with a
priority controller and an 8-entry RAM vector table; `RETI`.
**No instruction encoding changed** — Rev A applications run unchanged.

### 5.3 Peripherals (10 MMIO blocks, 16 registers each)

GPIO A + GPIO B (atomic `SET`/`CLR`, synchronised inputs) · timer with compare
interrupt · PWM with a **hardware fault input** (`motor_fault_n` shuts the output
down without CPU help) · UART with 4-byte FIFOs (console + upload) · SPI master
for expansion · a full **SPI-NOR flash controller** (ID, read stream, page
program, sector erase, CRC over a range, internal `tPROG`/`tERASE` waits) ·
interrupt controller · system control/debug · boot engine.

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
| `flash_ctrl_tb` | **48** | 0 | every flash command, wait states, CRC over a range, error flags |
| `boot_tb` | **24** | 0 | header parse, both CRCs, streaming to SRAM, verify-only, corrupt-image rejection |
| `soc_boot_tb` | **21** | 0 | reset → loader → SRAM content → CPU released at the right entry/SP |
| `monitor_tb` | **20** | 0 | the entire field-update story over a bit-banged UART, including the uploaded app actually running and driving GPIO/PWM/direction |
| **Total** | **113** | **0** | `make sim` |

Plus: `sv16_rtl_lint.py` **24/24 files clean** (multiple drivers, latches, missing
resets, incomplete case) and Verilator elaboration of the whole SoC clean.

### 6.2 Implementation (measured, reproducible)

| Stage | Result |
| :--- | :--- |
| Yosys `synth_ecp5` | 5,982 LUT4 + 1,376 carry, 4,448 FFs, 18 `DP16KD`, 1 `MULT18X18D`, netlist written |
| nextpnr-ecp5 (`--12k --package TQFP144 --speed 6 --freq 12.5`) | places, routes, **timing PASS** |
| ecppack `--compress` | `build/sv16_top.bit`, **275,119 bytes** |
| Placer comparison | heap default = **14.43 MHz** (PASS) · heap `timingweight 50` = 13.15/14.18 MHz (worse) · SA = fails to place carry chains |
| 25 MHz attempt (`CLKDIV=1`) | 14.38 MHz → **FAIL**, flow stops before packing (a broken build cannot ship silently) |

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

---

## 7. Reproduction — every number above, from scratch

```sh
git clone https://github.com/Soham121-935/Fpga.git && cd Fpga
git checkout arena/Rv2                 # or this session's arena/01a0ce9b-fpga

source scripts/sv16_venv.sh            # Verilator + Yosys + nextpnr + ecppack
make test                              # lint + 113 checks           (~2 min)
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

### 8.2 Production-grade gaps (ordered by value per unit of risk)

| # | Item | Why it matters | Effort |
| :--- | :--- | :--- | :--- |
| P1 | **Watchdog in the reset path** (`sv16_wdt.sv` exists, MMIO block 8, `SYS_RSTCAUSE.WDT` reserved) | A software hang currently means manual intervention | 1-2 days: instance + interconnect leg + `MMIO_PRESENT` bit + optional lock bit + tests |
| P2 | **Timing headroom → 25 MHz+** (critical path is CPU: register file → ALU → flags → control FSM, plus `u_sys.illegal_pc`) | Faster part, and the 12.5 MHz default is a workaround, not a design point | 2-4 days: extra FSM stage for flags/branch, register the fault address; then an `EHXPLLL` instead of the fabric divider |
| P3 | **A/B images with rollback** | Today a power cut during `C` loses the only application (recovery is the monitor, but the app is gone) | 3-5 days: two slots, validity flag, "confirm" store, loader policy + tests |
| P4 | **JTAG debug bridge** over the ECP5 TAP using the existing `SYS_CTRL.HALT` / `SYS_DBG_*` hooks | Biggest quality-of-life gap vs a real MCU: halt, resume, peek/poke, breakpoints | 1-2 weeks: TAP shift-register bridge + host tool |
| P5 | **C toolchain** (or an ISA extension to make C practical: register-indirect call, more registers) | Assembly-only is the main practical limit | weeks; ISA change needs its own ADR |
| P6 | **Signed / authenticated updates** (CRC16 detects corruption, not tampering) | Field-update security | 2-3 days for a keyed MAC in the loader + packer |
| P7 | **Brown-out / power-fail handling** | Write-during-brownout corruption is not modelled or mitigated | hardware-dependent |
| P8 | **Interrupt latency specification** | No measurement exists; the core is multi-cycle | 1 day: worst-case measurement in simulation (OQ-15) |
| P9 | **Peripheral coverage in the regression** — timer/PWM/GPIO/UART unit testbenches exist from Rev A but are not in `make sim` (some don't build under Verilator 5) | Coverage gap, not a known bug | 2-3 days to port or retire |
| P10 | **Throughput of firmware updates** — per-byte ack limits upload to ~5 KB/s of payload | Large images take minutes | 1-2 days for a buffered binary/XMODEM mode (OQ-17) |

### 8.3 Tracked design questions still open

See `docs/OPEN_QUESTIONS.md`: RAM remap (OQ-11), vector table placement (OQ-12),
watchdog policy (OQ-13), image slots (OQ-14), latency budget (OQ-15), C toolchain
and ISA extension (OQ-16), update throughput (OQ-17), real board pin assignment
(OQ-18).

---

## 9. Honest limitations (read this before believing anything)

1. **No silicon.** Every claim here is simulation plus static timing analysis.
   The first board will very likely find something (pin, polarity, timing, the
   flash part's command set).
2. **12.5 MHz, ~1 MIPS-core.** The core is multi-cycle by design (ADR-002) and
   the fabric clock divider is a timing workaround, not elegance.
3. **No protection.** No MPU, no privilege levels: any code can write any MMIO
   register, including the flash controller and the reset logic.
4. **Single image.** No rollback; a failed update leaves the monitor, not the
   previous application.
5. **Assembly only.** The assembler is also the linker (`.org`). The C example in
   `firmware/` documents intent, it does not compile.
6. **Update path is intentionally simple.** ASCII, CRC16, per-byte ack, no
   compression, no resume, no flow control.
7. **Two branches exist on the remote** (`arena/Rv2` = the work; this session
   also pushes to `arena/01a0ce9b-fpga`). Make sure PRs target the one you intend.

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
