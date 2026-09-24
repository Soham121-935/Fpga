# SV-16 Rev B — Peripheral Subsystem

Ten memory-mapped blocks are instantiated on the single SV-16 bus (ten of the sixteen decode slots; block 8 and blocks 11-15 are reserved and simply acknowledge reads with `0x0000`) (see
[BUS_ARCHITECTURE.md](BUS_ARCHITECTURE.md)). This page is the register-level
reference for each of them; addresses are **word offsets from the block base**.

`X` = don't care, `RO` = read only, `RW` = read/write, `W1C` = write 1 to clear,
`∧` in the "bits" column means "this is a bit field".

---

## Summary

| Base | Block | Registers | Interrupt |
| :--- | :--- | :--- | :--- |
| `0xF000` | System control | 16 | — |
| `0xF010` | GPIO port A | 4 | edge/level, shared |
| `0xF020` | Timer 0 | 4 | compare match |
| `0xF030` | PWM 0 | 4 | fault |
| `0xF040` | UART 0 | 5 | RX fifo, TX fifo |
| `0xF050` | SPI 0 (master) | 4 | transfer done |
| `0xF060` | Flash controller | 14 | done/error |
| `0xF070` | GPIO port B | 4 | shared with port A |
| `0xF090` | Interrupt controller | 4 | — |
| `0xF0A0` | Boot loader | 16 | — |

System control (`0xF000`) is documented in
[MEMORY_MAP.md](MEMORY_MAP.md#3-system-control-block-0xf000-block-0) and the
boot loader in
[BOOT_AND_PROGRAMMING.md](BOOT_AND_PROGRAMMING.md#5-the-boot-engine-register-block-0xf0a0).

---

## GPIO (`0xF010`, `0xF070`)

Two identical 16-bit ports. Port A drives `gpio_a[15:0]` (shared with the status
LEDs and the motor control pins on the board), port B drives `gpio_b[15:0]`.

| Off | Name | Access | Bits |
| :--- | :--- | :--- | :--- |
| 0 | `DATA` | RW | `[15:0]` output data; reading returns **pins** for inputs and the register for outputs |
| 1 | `DIR` | RW | `[15:0]` `1` = output, `0` = input |
| 2 | `SET` | W | atomic: `data |= wdata` (read-modify-write free, safe with interrupts) |
| 3 | `CLR` | W | atomic: `data &= ~wdata` |

Inputs are synchronised (two flops) before they reach the register. The atomic
`SET`/`CLR` registers are what make single-bit GPIO safe without disabling
interrupts — that is the recommended way to drive a motor direction pin.

---

## Timer 0 (`0xF020`)

| Off | Name | Access | Bits |
| :--- | :--- | :--- | :--- |
| 0 | `CNT` | RW | current count (writes load it) |
| 1 | `CMP` | RW | compare value |
| 2 | `CTRL` | RW | `[0]` ENABLE, `[1]` AUTO-RELOAD, `[2]` IRQ enable |
| 3 | `STAT` | W1C | `[0]` MATCH (compare hit) |

When `CNT == CMP` the `MATCH` flag sets, the optional interrupt fires, and with
AUTO-RELOAD the counter restarts. The timer counts SoC clock cycles, so its
period is `(CMP+1) / f_clk` — 80 µs per 1000 counts at 12.5 MHz.

---

## PWM 0 (`0xF030`)

| Off | Name | Access | Bits |
| :--- | :--- | :--- | :--- |
| 0 | `PERIOD` | RW | `[15:0]` period in clock cycles |
| 1 | `DUTY` | RW | `[15:0]` high time in clock cycles |
| 2 | `CTRL` | RW | `[0]` ENABLE, `[1]` INVERT, `[2]` FAULT enable |
| 3 | `STAT` | W1C | `[0]` FAULT latched (motor driver `nFAULT` pin) |

`motor_fault_n` (pin 103) can shut the PWM output down in hardware; the latch
tells firmware what happened. Because an active-low fault forces the output off
without CPU intervention, this is the one peripheral in the design that behaves
like a *motor-control timer* rather than a generic block.

---

## UART 0 (`0xF040`)

| Off | Name | Access | Bits |
| :--- | :--- | :--- | :--- |
| 0 | `DATA` | RW | transmit (`[7:0]`, write-only) / receive (`[7:0]`, read pops the RX FIFO) |
| 1 | `STATUS` | RO | `[0]` TX READY, `[1]` RX READY, `[2]` TX FULL, `[3]` RX EMPTY, `[4]` RX OVERRUN, `[5]` TX IRQ, `[6]` RX IRQ |
| 2 | `BAUD` | RW | `[15:0]` divisor = `f_clk / baud` (values < 4 are clamped to 4) |
| 3 | `CTRL` | RW | `[0]` TX enable, `[1]` RX enable, `[2]` TX IRQ enable, `[3]` RX IRQ enable |
| 4 | `FIFO` | RW | `[7:0]` FIFO depth readback; writing clears both FIFOs |

4-byte TX and RX FIFOs, 8-N-1, no parity, no flow control. The reset divisor is
derived from the SoC clock configuration in `sv16_top`, so the console is always
115200 regardless of `SV16_CLKDIV`. `UART0` is the firmware-upload port; see
[BOOT_AND_PROGRAMMING.md](BOOT_AND_PROGRAMMING.md).

---

## SPI 0 (`0xF050`)

Generic SPI master for off-chip expansion (sensors, displays, second flash).

| Off | Name | Access | Bits |
| :--- | :--- | :--- | :--- |
| 0 | `DATA` | RW | write `[7:0]` to transmit; read `[7:0]` received byte |
| 1 | `STATUS` | RO | `[0]` busy, `[1]` RX ready, `[2]` TX ready, `[3]` CS asserted |
| 2 | `CTRL` | RW | `[0]` enable, `[1]` CS manual, `[2]` CPOL, `[3]` CPHA |
| 3 | `DIV` | RW | `[15:0]` clock divider (`0` → 1) |

Pins: `spi0_sck`, `spi0_cs_n`, `spi0_mosi`, `spi0_miso`. The flash controller has
its own private SPI port (`flash_*`), so a program can keep expansion traffic
running while a page programs.

---

## Flash controller (`0xF060`)

Owns the dedicated `flash_*` SPI port and all knowledge of the NOR command set
(READ, FAST READ, PAGE PROGRAM, WREN/WRDI, sector erase, RDSR, RDID). It hides
timing from software: `tPROG`/`tERASE` are waited out internally while the bus
stalls.

| Off | Name | Access | Bits |
| :--- | :--- | :--- | :--- |
| 0 | `CMD` | W | command code (see below) |
| 1 | `STAT` | RO | `[0]` SR.WIP, `[1]` CRC READY, `[2]` PGM BUSY, `[3]` WEL, `[4]` RX data available, `[5]` ID valid, `[6]` error, `[7]` busy |
| 2 | `ADDR_LO` | RW | address bits `[15:0]` (byte address) |
| 3 | `ADDR_HI` | RW | address bits `[23:16]` |
| 4 | `LEN` | RW | transfer length in bytes |
| 5 | `DATA` | RW | read pops a byte from the RX FIFO; write pushes a byte into the page buffer |
| 6 | `ID` | RO | JEDEC ID `[15:0]` (`0xEF40` for a W25Q-class part) |
| 7 | `ID2` | RO | JEDEC ID `[23:16]` (`0x18` → 8 Mbit) |
| 8/9 | `CRC_LO/HI` | RO | CRC16 computed over a `CRC_START` range |
| 10 | `CTRL` | RW | `[0]` chip-select control, `[1]` fast-read enable, `[15:8]` wait-state tuning |
| 11 | `WRCNT` | RO | bytes buffered into the current page |
| 12 | `SR` | RO | raw status register from the chip |
| 13 | `TOTAL` | RO | total bytes transferred in the current session |

Command codes (`CMD`):

| Code | Name | Effect |
| :--- | :--- | :--- |
| 0 | `NOP` | no operation |
| 1 | `READ_ID` | read JEDEC ID into `ID`/`ID2`, sets `STAT.ID` |
| 2 | `READ_START` | stream `LEN` bytes from `ADDR` into the RX FIFO |
| 3 | `WRITE_START` | open a write session: erase-free, page-buffered programming |
| 4 | `FLUSH` | program the partial page and close the session |
| 5 | `ERASE_SECT` | erase the 4 KB sector containing `ADDR` |
| 6 | `ERASE_CHIP` | bulk erase (**destructive**, takes seconds) |
| 7 | `CRC_START` | compute CRC16-CCITT over a range into `CRC_LO/HI` |
| 8 | `READ_SR` | refresh `SR` |
| 9/10 | `WR_ENABLE`/`WR_DISABLE` | set/clear the write-enable latch |
| 11 | `RELEASE` | abandon the current session (chip deselect, FIFOs cleared) |

Firmware rarely drives this directly for *images*: the boot engine and the
monitor already implement the erase/program/verify sequence. Use `CRC_START`
plus `READ_START` to verify a region cheaply.

---

## Interrupt controller (`0xF090`)

| Off | Name | Access | Bits |
| :--- | :--- | :--- | :--- |
| 0 | `EN` | RW | `[7:0]` per-source enable |
| 1 | `PEND` | RW | `[7:0]` pending sources (write 1 to clear) |
| 2 | `LINES` | RO | `[7:0]` raw source levels |
| 3 | `PRIO` | RO | index of the source currently being served |

Sources are indexed as in
[MEMORY_MAP.md](MEMORY_MAP.md#interrupt-vector-indices). The controller presents
the highest-priority enabled+pending source to the CPU, which fetches the handler
address from the vector table, pushes `SR` and `PC`, and clears `IE`. `RETI`
restores `SR` and returns. Firmware must additionally set `SYS_CTRL.IRQEN` and
populate the vector table.

---

## Peripheral design idioms worth knowing

* **Ack-based handshake, no busy-wait in the bus.** Every slave returns `ack`
  exactly one cycle after its request; the CPU holds its request until `ack`
  arrives, so a slow peripheral (flash page program) simply delays the access
  instead of corrupting it.
* **Registered read data.** Read values come from the slave's registered read
  port, so a peripheral can change its state without glitching a read in
  flight.
* **Peripheral registers are word-oriented.** `SET`/`CLR`/`W1C` registers exist
  so firmware never needs a read-modify-write cycle.
* **Everything is clocked from one domain.** There is no CDC between
  peripherals; asynchronous inputs (`uart_rx`, `flash_miso`, `motor_fault_n`)
  are synchronised at the top level.
