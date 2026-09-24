# SV-16 Rev B — Verification

Verification for Rev B is simulation-based: self-checking Verilator testbenches
plus two static checks (RTL lint and Verilator elaboration of the whole SoC).
The regression is what the repository's `make test` actually runs — nothing in
the tables below is aspirational.

---

## 1. What runs today

```sh
source scripts/sv16_venv.sh
make test            # lint + firmware + all seven simulation suites
make sim TB=wdt_tb   # a single suite
```

| Suite | File | Checks | Result | What it proves |
| :--- | :--- | ---: | :--- | :--- |
| `wdt_tb` | `simulation/unit/wdt_tb.sv` | 49 | PASS | the watchdog: exact period `(PRESET+1)x2^PRESC`, one-cycle reset request, self-rearm, keyed writes, magic-word feeds, integer prescaler, early-warning interrupt `MARGIN` ticks ahead, windowed feeding, LOCK freezing enable/period/prescaler/window, write-1-to-clear flags, hard-reset-only clearing |
| `wdt_reset_tb` | `simulation/regression/wdt_reset_tb.sv` | 14 | PASS | the whole point of it: an application that hangs is restarted by the hardware — bite, `RSTCAUSE.WDT`, re-boot of the image, application runs again, second hang caught again, external pin clears it |
| `div_tb` | `simulation/unit/div_tb.sv` | 41 | PASS | the ALU's iterative divider (ADR-018): the handshake (16-cycle busy, a start while busy does not restart the run, no stale result after reset), the arithmetic including `0/5`, `1/2`, `0xFFFF/1`, `0x8000/0x8000`, divide-by-zero per OQ-04, and that every other operation is still single-cycle |
| `flash_ctrl_tb` | `simulation/unit/flash_ctrl_tb.sv` | 48 | PASS | the flash controller's command set: ID, read stream, page program + flush, sector erase, CRC over a range, status/wait-state handling, error flags |
| `boot_tb` | `simulation/unit/boot_tb.sv` | 26 | PASS | the hardware boot loader against a behavioural SPI NOR model: header parse, CRCs, payload streaming into SRAM, `BOOT_STAT`/`BOOT_ERR`, verify-only mode, rejection of corrupt images, and a clean "no image anywhere" verdict |
| `slot_tb` | `simulation/unit/slot_tb.sv` | 57 | PASS | the A/B policy end to end (ADR-019), with the loader, the flash controller and the flash model wired as `sv16_top` wires them, including the slot-record program handshake: the pick order (pending > trial > good > no record > bad), a pending image being marked TRIED *before* the CPU is released, a restart inside the trial retiring it to BAD and booting the other slot, a confirmed update retiring the previous image so the update sticks, a torn record being refused, and `BOOT_CTRL[4]` booting `BOOT_SRC` with the records ignored |
| `soc_boot_tb` | `simulation/regression/soc_boot_tb.sv` | 21 | PASS | end-to-end: reset → boot engine → SRAM contains the image → CPU released at the entry point with the image's stack pointer |
| `monitor_tb` | `simulation/regression/monitor_tb.sv` | 21 | PASS | the whole field-programming story over a bit-banged UART: banner, `?`, `C` upload of a real image, `R` readback, `E` erase, `V` CRC, `K` confirm (ADR-019), `B` boot, the application actually running and driving GPIO/PWM/direction pins, and the monitor being the fallback |
| `sv16_rtl_lint.py` | `scripts/sv16_rtl_lint.py` | 25 files | clean | structural checks: multiple drivers, missing `default` in combinational `case`, `always_ff` without reset, latches, etc. |
| Verilator elaboration | `make vlint` | top | clean | the whole SoC (package + 25 modules) elaborates as one design |

Total: **277 checks, 0 failures.**

The SPI flash model implements the physics the A/B record depends on: a page
program can only clear bits (`mem <= mem & data`) and an erase sets a whole
sector back to `0xFF`. Modelling a program as a plain assignment would hide an
encoding that needs a bit set back — a real chip cannot do that without erasing
the sector, image and all — so `slot_tb` would pass here and fail on the board.

`monitor_tb` is the most valuable suite in the set: it is a *system* test. It
bakes `build/rom/monitor.hex` into the ROM model, brings up a blank flash, drives
a real image (`build/fw/motor_test_img.hex`) through the monitor's upload
protocol byte by byte with the ack/dot handshake, verifies the flash contents,
and then checks that a `B` command hands control to the uploaded application with
the expected side effects on the peripherals. `wdt_reset_tb` is the other system
test: it boots a deliberately hanging application out of flash and watches the
watchdog recover it, twice, with no host involved. All six suites are run from
the repository root (they read files from `build/`).

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
6. **The watchdog's feed was swallowed by its own tick** (found by `wdt_tb`):
   at `PRESC = 0` every clock is a tick, and the counter's decrement was
   evaluated after — and therefore overrode — the reload a feed had just
   requested, so feeding the watchdog at its most common setting did nothing.
   The counter now has an explicit priority: window fault, feed, then tick.
7. **A 16-bit period and an 8-bit key cannot share one word**: the first cut
   stored the whole keyed value as the period, so a 32-tick watchdog ran for
   23048 clocks. `CTRL` is keyed; the period registers are frozen by `LOCK`.
8. **The window was enforced on the very first feed**, which would have reset a
   correctly written application one period after arming the watchdog; the first
   period after `ENABLE` is now exempt.
9. **The 25 MHz timing failure was misdiagnosed in the documentation.** It was
   attributed to the CPU's flag/branch path (`u_sys.illegal_pc`'s decrement), with
   "split the flag decision" offered as the fix; the nextpnr critical-path report
   plus a constant-folding experiment showed the culprit was the ALU's
   combinational 16/16 divider. Fixing that (multi-cycle DIV/MOD, ADR-018) took
   Fmax from 14.68 MHz to 46.58 MHz and the shipped clock from 12.5 MHz to
   25 MHz — `div_tb`.

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
| Watchdog under a fault-injection campaign | window, lock and interrupt paths are covered functionally, but not with randomised timing or injected faults |
| Divider performance | DIV/MOD take 18 cycles by construction; no measured worst-case instruction-time table exists yet (OQ-15) |
| The 12.5 MHz fallback configuration | `CLKDIV=2` still builds and the RTL divider is unchanged, but only `CLKDIV=1` is exercised in simulation and by the default bitstream |
| Software (monitor) | exercised through `monitor_tb` only; no unit tests for the assembler, packer or `sv16_mon.py` against a golden corpus |
| Flash endurance / power-loss during program | not modelled |
| Timing | closed by nextpnr's static analysis at 25 MHz (Fmax 46.58 MHz); no SDF/back-annotated simulation and no on-board measurement |

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
