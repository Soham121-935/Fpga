# SV-16 Rev B — Synthesis, Timing and Deployment

Target: **Lattice ECP5 `LFE5U-12F-6TG144C`** (12K LUT, TQFP-144, speed grade 6).
Everything in this document was executed against the tree in this repository; the
numbers are measured, not estimated.

---

## 1. Toolchain

Two ways to get a working flow:

**A. Let the repository fetch its own toolchain (recommended, fully scripted).**

```sh
source scripts/sv16_venv.sh      # Verilator + Yosys + nextpnr-ecp5 + ecppack
make test                        # lint + 4 simulation suites
make bitstream                   # Yosys -> nextpnr-ecp5 -> ecppack
```

`sv16_venv.sh` creates `/tmp/sv16-venv` with self-contained wheels
(Verilator 5.49, Yosys 0.69, nextpnr-ecp5 0.11.1, ecppack, all via yowasp) and
symlinks `yosys`, `nextpnr-ecp5` and `ecppack` into `/tmp/sv16-ccwrap`, which it
puts on `PATH`. It must be sourced in the same shell as any build. Re-running it
is cheap and idempotent; `/tmp` being wiped only costs one source.

**B. Use system packages.** Yosys ≥ 0.4x with `synth_ecp5`, nextpnr-ecp5 ≥ 0.6,
`ecppack` (prjtrellis), Verilator ≥ 5.x. The Makefile calls these by name.

---

## 2. Build targets

| Command | What it does |
| :--- | :--- |
| `make firmware` | builds the boot ROM (`build/rom/monitor.hex`) and the example application image |
| `make rom` | assembles `firmware/monitor/monitor.s` (+ `.lst` listing) |
| `make app` | assembles + packs `firmware/examples/motor_test.s` |
| `make lint` | repository RTL lint (`scripts/sv16_rtl_lint.py`, 25 files, no external tools) |
| `make vlint` | Verilator lint of the whole SoC |
| `make sim` | builds and runs all four Verilator testbenches (`TB=name` to pick one) |
| `make test` | `lint` + `firmware` + `sim` |
| `make bitstream` | synthesis + place & route + bitstream → `build/sv16_top.bit` |
| `make synth` | Yosys only (fast "is it still synthesizable for this part?" check) |
| `make prog` | program the device over JTAG (`openFPGALoader`) |
| `make iss` | run the instruction-set simulator on the legacy Rev A ROM image |

Useful overrides: `CLKDIV=1|2`, `FPGA_FREQ=25`, `TB=boot_tb`,
`PORT=/dev/ttyUSB0` (upload), `BOARD=`/`CABLE=` (programming).

### How the boot ROM gets into the bitstream

The ROM is a `$readmemh` initialisation in `rtl/sv16_rom.sv` driven by the macro
`SV16_ROM_INIT_FILE`. `scripts/sv16_synth.sh` writes a one-line header,
`build/sv16_defines.svh`, containing

```verilog
`define SV16_ROM_INIT_FILE "build/rom/monitor.hex"
`define SV16_CLKDIV 2
```

and passes it as the first source file of `read_verilog`, so a bitstream always
bakes in the monitor that was assembled from `firmware/monitor/monitor.s`. The
same header carries the clock divider, which is why the console baud divisor
(`sv16_top` → `sv16_uart.BAUD_DIV_RESET`) always matches the system clock.
Building without a ROM (`--no-rom`) yields a chip that boots to nothing — useful
only for synthesis experiments.

---

## 3. Synthesis and place & route

```sh
make bitstream        # == scripts/sv16_synth.sh --clkdiv 1 --freq 25
```

1. **Yosys** (`synth_ecp5`, ABC9): 7,233 LUT4 + 1,130 carry cells, 4,631 FFs,
   18 `DP16KD` block RAMs (16 for SRAM, 2 for the boot ROM), 1 `MULT18X18D` for
   the ALU multiplier, 52 I/O buffers. The synthesis script, its log and the
   netlist are kept: `build/sv16_synth.ys`, `build/sv16_yosys.log`,
   `build/sv16_top.json`.
2. **nextpnr-ecp5** `--12k --package TQFP144 --speed 6 --freq 25` with
   `constraints/ecp5_144tqfp.lpf`. Report: `build/sv16_nextpnr.log`,
   `build/sv16_top.timing.json`.
3. **ecppack** `--compress` → `build/sv16_top.bit` (~286 KB, ~1.5 Mbit stream
   for a 12F).

### Device utilisation (measured)

| Resource | Used | Available | % |
| :--- | ---: | ---: | ---: |
| LUT4 (incl. carry) | 8,363 | 24,288 | 34 % |
| Flip-flops | 4,631 | 24,288 | 19 % |
| `DP16KD` block RAM | 18 | 56 | 32 % |
| `MULT18X18D` | 1 | 28 | 3 % |
| I/O buffers | 52 | 197 | 26 % |
| `EHXPLLL` | 0 | 2 | 0 % |

Roughly two thirds of the part is still free, which is what funds the roadmap
items in [MCU_READINESS.md](MCU_READINESS.md).

### Timing

The board oscillator is 25 MHz and there is **no PLL in the design**. By default
(`CLKDIV=1`) the SoC runs directly from that oscillator with no fabric divider at
all, so the whole machine — CPU, RAM, ROM and every peripheral — is one 25 MHz
clock domain promoted to a global network by nextpnr:

```sh
make bitstream              # == scripts/sv16_synth.sh --clkdiv 1 --freq 25
make bitstream CLKDIV=2     # 12.5 MHz fallback (fabric divider, 50 % duty)
```

**Measured, on an LFE5U-12F-6 (speed grade 6):**

| Configuration | Achieved Fmax | Requirement | Result |
| :--- | ---: | ---: | :--- |
| `CLKDIV=1`, 25 MHz, heap placer (**default**) | **46.58 MHz** post-route (35.15 pre-route) | 25 MHz | **PASS, ~86 % margin** |
| `CLKDIV=2`, 12.5 MHz, heap placer | 46.58 MHz | 12.5 MHz | PASS |
| `CLKDIV=1`, heap `--placer-heap-timingweight 50` | 13.15 / 14.18 MHz | 25 MHz | worse; not used |
| simulated annealing (`--placer sa`) | — | — | **fails to place** carry chains |
| `CLKDIV=1`, **before** the divider fix (ADR-018) | 14.38 MHz | 25 MHz | FAIL — why the part shipped at 12.5 MHz |

`make bitstream` is expected to exit 0 with `PASS`; if a board ever turns out not
to run at 25 MHz, `CLKDIV=2` is the fallback and the console keeps working because
the UART's divisor is recomputed from the same constant.

#### Why 25 MHz was impossible before (the corrected diagnosis)

For most of Rev B the documentation blamed the CPU: "register file → ALU → flags
→ control-unit next-state, plus `u_sys.illegal_pc`'s decrement", with an extra FSM
state offered as the fix. Reading the actual nextpnr critical-path report showed
that the path was **the ALU's combinational 16/16 divider** (`a / b`, `a % b`),
which sat in the same `always_comb` block as the adder and therefore appeared in
every arithmetic instruction's timing path. A one-line experiment — replacing
`a / b` and `a % b` with constants — moved Fmax from **14.68 MHz to 44.31 MHz**.

The fix (ADR-018) is a single iterative restoring divider inside `sv16_alu`,
driven by a `div_start`/`div_busy` handshake and held by the new `S_DIV_WAIT`
state of the control unit. DIV and MOD keep their encodings, results and flags;
they simply take 18 cycles instead of 1. Every other operation is unchanged and
still single-cycle. That is what took the design from 12.5 MHz to the full 25 MHz
and left ~86 % timing margin for future logic.

Remaining headroom work, in increasing order of effort: instantiate an `EHXPLLL`
to replace the fabric divider and run 40–50 MHz (the fabric now supports it), and
split the flag/branch decision across an extra FSM state if a future feature eats
the margin.

### Pin constraints

`constraints/ecp5_144tqfp.lpf` locates every port of `sv16_top` on a real I/O
site of this package (verified against the prjtrellis device database; for TQFP
packages the `SITE` name is the bare pin number). Note that four of the Rev A
pin assignments (`P63` clock, `P60` reset, `P38` LED0, `P100` PWM) were **not
bonded I/O on the TQFP-144 part at all** — they could never have been placed.
The Rev B map was rebuilt from the device database; only the Rev A UART pins
were kept.

| Signal | Pin | Notes |
| :--- | :--- | :--- |
| `clk_25m` | 133 | 25 MHz oscillator |
| `ext_rst_n` | 134 | `PULLMODE=UP` — a floating reset pin means "not reset" |
| `uart_rx` / `uart_tx` | 73 / 74 | kept from Rev A; console + firmware upload |
| `flash_sck` / `cs_n` / `mosi` / `miso` | 110 / 111 / 112 / 113 | dedicated SPI port to the application flash |
| `spi0_sck` / `cs_n` / `mosi` / `miso` | 114 / 115 / 116 / 117 | expansion bus |
| `led[0..3]` | 39 / 40 / 41 / 44 | mirror GPIOA[3:0] |
| `gpio_a[15:0]` | 45-52, 97-99, 104-108 | also the motor-control connector |
| `gpio_b[15:0]` | 135, 136, 139-143, 128, 124-127, 1-4 | second, independent port |
| `pwm_out` | 88 | `DRIVE=16` |
| `motor_dir1` / `motor_dir2` | 89 / 102 | |
| `motor_fault_n` | 103 | `PULLMODE=UP`; hardware PWM shutdown |

All I/O is `LVCMOS33`. There is no pin muxing: each port has one function fixed
at synthesis time, so changing a peripheral's pin means editing the LPF.

---

## 4. Programming the FPGA

```sh
make prog                                   # openFPGALoader, defaults
make prog BOARD=ecp5-evn CABLE=ft2232       # board/cable overrides
openFPGALoader --fpga-part LFE5U-12F build/sv16_top.bit   # equivalent
```

The configuration is volatile (SRAM-based FPGA): the bitstream comes from JTAG
on every power-up unless an external configuration flash for the FPGA is
programmed separately (`openFPGALoader -f` writes the *FPGA's own* config flash
on boards that have one — that is a different device from the SPI flash SV-16
uses for firmware, and the two must not be confused).

Application firmware is *not* programmed this way; it goes over the serial port
(`make upload`, see
[BOOT_AND_PROGRAMMING.md](BOOT_AND_PROGRAMMING.md)). That split is the point of
Rev B: the FPGA configuration defines the machine, the serial port defines the
program.

---

## 5. Reproducibility

* Every generated artifact lands in `build/` (untracked) with a fixed name.
* `build/sv16_synth.ys` and `build/sv16_defines.svh` are kept so a build can be
  audited or replayed by hand: `yosys -s build/sv16_synth.ys`.
* The ROM and the application image are rebuilt from source by `make bitstream`
  (the bitstream target depends on `build/rom/monitor.hex`), so no binary blobs
  can drift from the assembly.
* Pin constraints, clock divider and timing constraint are all explicit inputs to
  the flow (`constraints/ecp5_144tqfp.lpf`, `CLKDIV`, `FPGA_FREQ`).
* Nothing in the flow downloads anything at build time except
  `scripts/sv16_venv.sh`, which is pinned to specific wheel versions in PyPI.

---

## 6. Using another flow (Lattice Diamond)

The RTL is plain SystemVerilog and the LPF syntax is shared with Diamond, so the
same sources can be targeted there: add the 25 files of `rtl/` (package first),
set `sv16_top` as the top, define `SV16_ROM_INIT_FILE` (a quoted path to
`build/rom/monitor.hex`) and `SV16_CLKDIV 1` as Verilog macros, and use the same
LPF. Diamond will report its own timing; the 25 MHz configuration is the one
with margin. Nothing in `scripts/` other than `sv16_venv.sh` depends on the
open-source toolchain.
