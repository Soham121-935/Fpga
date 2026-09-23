# SV-16 Rev B — Verification

Verification for Rev B is simulation-based: self-checking Verilator testbenches
plus two static checks (RTL lint and Verilator elaboration of the whole SoC).
The regression is what the repository's `make test` actually runs — nothing in
the tables below is aspirational.

---

## 1. What runs today

```sh
source scripts/sv16_venv.sh
make test           # lint + firmware + all four simulation suites
make sim TB=boot_tb # a single suite
```

| Suite | File | Checks | Result | What it proves |
| :--- | :--- | ---: | :--- | :--- |
| `flash_ctrl_tb` | `simulation/unit/flash_ctrl_tb.sv` | 48 | PASS | the flash controller's command set: ID, read stream, page program + flush, sector erase, CRC over a range, status/wait-state handling, error flags |
| `boot_tb` | `simulation/unit/boot_tb.sv` | 24 | PASS | the hardware boot loader against a behavioural SPI NOR model: header parse, CRCs, payload streaming into SRAM, `BOOT_STAT`/`BOOT_ERR`, verify-only mode, rejection of corrupt images |
| `soc_boot_tb` | `simulation/regression/soc_boot_tb.sv` | 21 | PASS | end-to-end: reset → boot engine → SRAM contains the image → CPU released at the entry point with the image's stack pointer |
| `monitor_tb` | `simulation/regression/monitor_tb.sv` | 20 | PASS | the whole field-programming story over a bit-banged UART: banner, `?`, `C` upload of a real image, `R` readback, `E` erase, `V` CRC, `B` boot, the application actually running and driving GPIO/PWM/direction pins, and the monitor being the fallback |
| `sv16_rtl_lint.py` | `scripts/sv16_rtl_lint.py` | 24 files | clean | structural checks: multiple drivers, missing `default` in combinational `case`, `always_ff` without reset, latches, etc. |
| Verilator elaboration | `make vlint` | top | clean | the whole SoC (package + 24 modules) elaborates as one design |

Total: **113 checks, 0 failures.**

`monitor_tb` is the most valuable suite in the set: it is a *system* test. It
bakes `build/rom/monitor.hex` into the ROM model, brings up a blank flash, drives
a real image (`build/fw/motor_test_img.hex`) through the monitor's upload
protocol byte by byte with the ack/dot handshake, verifies the flash contents,
and then checks that a `B` command hands control to the uploaded application with
the expected side effects on the peripherals. All four suites are run from the
repository root (they read files from `build/`).

### Testbench infrastructure

* `scripts/sv16_run_tb.sh` builds any testbench with Verilator (`build/vlt/<top>/`),
  adding `rtl/*.sv` (package first, top last), the SoC top, and the SPI flash
  model when the testbench instantiates it. Testbenches must run from the repo
  root because they `$readmemh` from `build/`.
* `simulation/unit/sv16_flash_model.sv` is a behavioural SPI NOR (64 KB,
  256-byte pages, 4 KB sectors, `tPROG`/`tERASE` modelled in clocks, JEDEC ID
  `0xEF4018`) shared by `flash_ctrl_tb`, `boot_tb`, `soc_boot_tb` and
  `monitor_tb`.
* Watchdogs: every suite has an absolute cycle limit and fails loudly instead of
  hanging, and the CPU-side suites watch `dut.dbg_pc` for runaway execution.

---

## 2. Bugs this suite has caught

Worth recording, because they are the reason the boot path is trustworthy now:

1. **A slave's `ack` was not qualified by its own transfer.** A peripheral acked
   for a request it had already serviced, so the CPU could latch a *stale* read
   value — this corrupted instruction fetches during the loader's RAM writes and
   showed up as monitor code walking off the end of its own text. Fixed by
   qualifying every slave ack with the request (and reply routing with the
   granted master).
2. **A bus master could be starved forever.** Arbitration was rewritten to a
   held-grant scheme with the loader at lower priority: a master keeps the bus
   until its transfer completes, and a pending CPU store cannot be lost while an
   image streams past it.
3. **The boot loader's START strobe was level-based.** The CPU holds a store on
   the bus until it is acknowledged, so a level-sensitive start restarted the
   load on every cycle it stayed asserted (a "boot storm"). `BOOT_CTRL.START` is
   now a latched, self-clearing request.
4. **The loader's start pulse was multi-cycle.** `sv16_startup` now emits a
   single-cycle `boot_go`.
5. **Flash read streaming was off by one** (wait states after the last byte),
   and the monitor's hex helper printed one nibble short.

---

## 3. What is *not* verified

Being explicit about coverage gaps is part of the verification story:

| Area | Status |
| :--- | :--- |
| Real silicon | **never run.** Everything below is simulation + place-and-route. Electrical behaviour, the real flash part, reset-line RC time constants and the 25 MHz oscillator are unproven |
| Reset glitch / power sequencing | only clean pulses are simulated; no brown-out or runt-pulse testing |
| UART framing errors, overrun, break conditions | the model drives clean 8-N-1 only |
| Interrupt latency | the IRQ controller and vector fetch are exercised indirectly; no timing-bound test exists |
| Timer/PWM boundaries | `simulation/unit/*` has older Rev A testbenches for these; they are **not** in the Rev B regression (some of them do not build under Verilator 5) |
| Software (monitor) | exercised through `monitor_tb` only; no unit tests for the assembler, packer or `sv16_mon.py` against a golden corpus |
| Flash endurance / power-loss during program | not modelled |
| Timing | closed by nextpnr's static analysis at 12.5 MHz; no SDF/back-annotated simulation and no on-board measurement |

The Rev A testbenches that remain in `simulation/unit/` and `test_*.py` scripts
document the earlier module-level work; they are excluded from `make sim`
deliberately rather than left broken by accident.

---

## 4. Reproducing a failure

```sh
source scripts/sv16_venv.sh
scripts/sv16_run_tb.sh simulation/regression/monitor_tb.sv monitor_tb
build/vlt/monitor_tb/monitor_tb | head -60     # full trace, from the repo root
```

Assertion helpers `chk()`/`check()` print `[PASS]`/`[FAIL]` lines with a
`== N checks, M failures ==` summary, and each suite exits non-zero on failure,
so it can be used directly from CI (`make test`).
