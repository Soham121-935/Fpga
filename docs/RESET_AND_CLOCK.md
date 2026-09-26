# SV-16 Rev B — Reset and Clock Architecture

Rev B turns reset from "hold the CPU for N cycles" into a *boot sequencer*, and
makes the clock a build-time decision that is shared with the console baud rate.

---

## 1. Clocking

The system clock comes from one of two build-time sources, selected with
`CLKSRC`, and then (optionally) divided in fabric by `SV16_CLKDIV`
(`rtl/sv16_top.sv`, ADR-021):

```
clk_25m ─┬─ osc: ─────────────────────────┐
         └─ pll: EHXPLLL ──► (CLKDIV) ──► clk ──► CPU, RAM, ROM, peripherals
```

* `CLKSRC = osc` → **the shipped default**: the 25 MHz oscillator *is* the SoC
  clock, no PLL, no divider, no generated clock (`make bitstream`). It closes
  with ~75 % margin (measured Fmax 43.7 MHz, 46.2 MHz before the PLL option was
  added — the difference is synthesis ordering, not logic).
* `CLKSRC = pll` → the on-chip `EHXPLLL` multiplies the 25 MHz reference up:
  `make bitstream CLKSRC=pll PLLMHZ=37.5` builds a **37.5 MHz** system clock
  (12.5 MHz PFD, ×3 feedback, ÷16 VCO divider, VCO 600 MHz), which closes timing
  at 44.87 MHz measured (~20 % margin). The reference reaches multiples of
  25 MHz and of 12.5 MHz exactly; 50 MHz is reachable but does not close on this
  speed grade. The synthesis script reports the requested and achieved frequency
  and refuses an illegal VCO.
* `SV16_CLKDIV = 2` halves whichever source is selected
  (`make bitstream CLKDIV=2`) — the conservative fallback for a board that
  cannot run at speed; the fabric divider then produces a 50 % duty clock.
* Every testbench simulates the default configuration (25 MHz, 217 clocks per
  UART bit); `simulation/regression/pll_clock_tb.sv` covers the PLL one.

The divider output (or the PLL output) is promoted to a global clock network by
nextpnr, so it has global clock skew characteristics even when generated in
fabric.

**Reset waits for the clock.** `sv16_startup` takes a `clk_ready` input and
holds the entire SoC in reset while it is low; with `CLKSRC=pll` that is the
PLL's `LOCK`, so the machine never starts executing on a clock that is not
there yet. The gate is compiled out in the oscillator configuration
(`GATE_ON_CLK_READY`), and the PLL's own `RST` is the raw reset — never gated on
its own lock signal, which would deadlock the PLL.

Because the UART's reset baud divisor is *computed in `sv16_top`* from the same
constants, the console stays 115200 8-N-1 whatever is selected — 217 clocks per
bit at 25 MHz, 326 at 37.5 MHz — and firmware does not have to know which clock
it is running on. `SYS_STAT[9:8]` (CLK_SRC_PLL, PLL_LOCKED) lets software check
if it cares. What does scale with the clock: timer counts, PWM period, SPI bit
rates, and instruction throughput.

Asynchronous inputs (`uart_rx`, `flash_miso`, `spi0_miso`, `motor_fault_n`,
`ext_rst_n`) are synchronised at the top level; there are no other clock domains
and no CDC inside the design.

---

## 2. Reset sources and the reset-cause register

| Source | Condition | Recorded in `SYS_RSTCAUSE` (`0xF003`) |
| :--- | :--- | :--- |
| External pin | `ext_rst_n` low (internally pulled up) | bit 0 |
| Software | `SYS_CTRL.SOFTRST` with the `0xA5` key | bit 1 |
| CPU fault | illegal opcode / exception trap | bit 2 |
| Watchdog | `sv16_wdt` timeout (`0xF080`); the watchdog is cleared only by the pin, so it survives every other reset | bit 3 |
| Boot failure | no valid image found in flash | bit 4 |
| Boot success | image validated and loaded | bit 5 |

Bits are sticky (they accumulate across resets) and are cleared by writing ones
back, so firmware can read the reason for the *last* reset and its history.
`SYS_SCRATCH0/1` are deliberately *not* cleared by a soft reset, giving an
application a place to leave a breadcrumb across a restart.

---

## 3. Startup sequence

`rtl/sv16_startup.sv` is the reset/boot controller. It owns `cpu_rst_n` (which
resets the CPU and peripherals but never itself) and the CPU's boot vector:

```
S_RESET   ext_rst_n released, hold the CPU in reset, clear SYS state,
          sample the serial RX line (a held-low RX forces the monitor)
   │
S_BOOT    pulse boot_go to the boot engine. If AUTO is not set, go straight to
   │      the monitor. Otherwise wait for the loader to finish.
   │
S_WAIT    loader busy → wait. DONE + OK → load entry/stack, go to S_IMAGE.
          DONE + FAIL → monitor (S_MONITOR).
   │
S_IMAGE   release the CPU with PC = image entry, SP = image stack pointer,
          then S_RUN. The image is already in SRAM, copied by hardware.
   │
S_MONITOR release the CPU with PC = 0xE000 (boot ROM) and SP = 0x3FFE.
   │
S_RUN     normal operation. Observes soft-reset requests, `SYS_CTRL.HALT`,
          CPU faults and watchdog timeouts; any of them restarts the
          sequence at S_RESET or S_BOOT.
```

Two properties matter in practice:

* **The boot engine, not the CPU, decides whether an image is usable.** It
  checks magic, header CRC, payload CRC, length and a watchdog, and it reports
  the failure reason in `BOOT_ERR` — the CPU cannot be tricked into running a
  half-written image.
* **The monitor is resident and reachable.** A soft reset with AUTO clear, or an
  RX line held low at reset, always lands in the boot ROM; the monitor and the
  loader live in the FPGA configuration, so a broken application cannot remove
  them.

---

## 4. Debug and fault behaviour

* A **watchdog bite** restarts the sequence at `S_RESET` (not the pin), sets
  `RSTCAUSE.WDT`, and re-runs the boot attempt. Because the watchdog block hangs
  off `rst_n` rather than `cpu_rst_n`, it keeps running across that restart and
  auto-reloads its counter, so an application that hangs again is restarted
  again. `SYS_SCRATCH0/1` and the early-warning interrupt (`IRQ_WDT`) give it a
  chance to leave evidence before the reset lands.
* `SYS_CTRL.HALT` stops the CPU at an instruction boundary; `SYS_CTRL.STEP`
  then executes exactly one instruction. This is how the monitor's
  `SYS_DBG_PC/SP/SR/IR` registers are meant to be used as a poor man's debugger.
* On an illegal opcode the core enters the trap sequence at vector 7
  (`0x0027`), pushing `SR` and `PC` first. The system block latches the fault
  address (`SYS_FAULT_ADDR`), increments `SYS_FAULT_CNT`, and can halt the core
  (`SYS_STAT.FAULT_HALT`) so the faulting PC can be read out.
* `SYS_STAT.ROM_MONITOR` / `IMAGE_OK` / `BOOT_FAIL` let firmware tell which way
  the chip came up.

---

## 5. Rev A → Rev B

| | Rev A | Rev B |
| :--- | :--- | :--- |
| Clock | 25 MHz straight from the oscillator | the same 25 MHz oscillator (÷ `SV16_CLKDIV`, default 1), console baud derived from the same constant |
| Reset | held for a fixed number of cycles | sequenced FSM with reset-cause tracking and boot hand-over |
| Boot vector | fixed ROM/RAM start | image entry + image stack pointer loaded by hardware |
| Recovery | none | monitor fallback on any boot failure, RX-low escape at reset |
| Fault visibility | none | fault address, count, PC/SP/SR/IR snapshot, halted core |
| Hung-application recovery | none (a hung program stays hung) | watchdog restarts the boot sequence and re-boots the application |
