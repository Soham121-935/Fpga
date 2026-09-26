# SV-16 Rev B — Reset and Clock Architecture

Rev B turns reset from "hold the CPU for N cycles" into a *boot sequencer*, and
makes the clock a build-time decision that is shared with the console baud rate.

---

## 1. Clocking

There is **no PLL in the design**. The board's 25 MHz oscillator (`clk_25m`,
pin 133) is divided in fabric by `SV16_CLKDIV` in `rtl/sv16_top.sv` and drives
every flip-flop in the SoC from one clock domain:

```
clk_25m ──► divider (SV16_CLKDIV) ──► clk ──► CPU, RAM, ROM, all peripherals
```

* `SV16_CLKDIV = 1` → **the shipped default**: the SoC clock *is* the 25 MHz
  oscillator, no divider, no generated clock (`make bitstream`). It closes with
  ~85 % margin (measured Fmax 46.17 MHz) since DIV/MOD became multi-cycle
  (ADR-018).
* `SV16_CLKDIV = 2` → 12.5 MHz fallback (`make bitstream CLKDIV=2`) for a board
  that cannot run at 25 MHz; the fabric divider then produces a 50 % duty clock.
* Larger values are legal (integer divide) but slow the part down.
* Every testbench simulates `SV16_CLKDIV = 1`: they drive `clk_25m` at 25 MHz and
  assume 217 cycles per UART bit, so the bitstream and the simulation now run at
  the same frequency.

The divider output is promoted to a global clock network by nextpnr, so it has
global clock skew characteristics even though it is generated in fabric.

Because the UART's reset baud divisor is *computed in `sv16_top`* from the same
constant, the console stays 115200 8-N-1 whatever the divider is — firmware does
not have to know the system clock to talk to the monitor. What does scale with
the clock: timer counts, PWM period, SPI bit rates, and instruction throughput.

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
