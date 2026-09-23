# SV-16 Rev B — System Bus Architecture

One 16-bit synchronous bus connects the CPU, the boot loader and every
peripheral. Rev B hardened the protocol in three ways — a held request, a
qualified ack, and a held grant — because the boot loader introduced a second
master, and a bus with two masters that can both be wrong is a bus that will be
wrong.

---

## 1. Signals

| Signal | Width | Direction (from master) | Meaning |
| :--- | ---: | :--- | :--- |
| `addr` | 16 | out | word address |
| `wdata` | 16 | out | write data |
| `we` | 1 | out | 1 = write, 0 = read |
| `req` | 1 | out | request: **asserted and held until `ack`** |
| `rdata` | 16 | in (from slave) | read data; valid in the `ack` cycle |
| `ack` | 1 | in (from slave) | transfer complete |

Masters are the CPU (`u_cpu`) and the boot loader (`u_boot`'s memory port).
Slaves are SRAM, the boot ROM, and the eleven MMIO blocks.

---

## 2. The protocol

**Master side.** A master that needs the bus presents `addr`/`we`/`wdata` and
raises `req`, then *holds everything stable* until it sees `ack`. It may not
change the address, withdraw the request or issue another transfer in the
meantime. This is what makes a slow peripheral (a flash page program) a
non-event: the access simply takes longer.

**Slave side.** Every slave answers exactly one cycle after it sees its own
qualified request:

* SRAM and the boot ROM: one cycle, `rdata` registered from the addressed word.
* MMIO blocks: one cycle for register accesses; the flash controller and the
  boot engine extend this while they are actually talking to flash.
* Unmapped addresses: the interconnect acknowledges them and returns `0x0000`.
  Probing a hole in the map cannot hang the bus.

**Interconnect side.** Two rules, both learned the hard way (see
[VERIFICATION.md](VERIFICATION.md#2-bugs-this-suite-has-caught)):

1. **An ack is qualified by the request that produced it.** A peripheral's `ack`
   is only accepted as valid when the request it belongs to is still in flight
   (`ack_valid = bus_ack && req_q`), and the reply that goes back to a master is
   the reply for *its* transaction (`owner_q` records which master was granted
   the cycle). Without this, a master could latch a value from a transfer that
   belonged to somebody else — which is exactly how instruction fetches were
   corrupted while the loader was writing SRAM.
2. **A grant is held for the whole transfer.** Arbitration happens once per
   transfer, not per cycle: `cpu_pend`/`boot_pend` latch that a master wants the
   bus, and `boot_own` keeps the loader on the bus until its access completes.
   The CPU has priority; the loader waits. A master whose request is waiting
   gets a *withheld* ack, never a lost one.

---

## 3. Arbitration

```
             ┌────────────┐
   CPU  ────►│            │───► SRAM   (0x0000-0x3FFF)
             │  arbiter   │───► ROM    (0xE000-0xE7FF)
  BOOT  ────►│            │───► MMIO   (0xF000-0xF0FF, 16 blocks)
             └────────────┘
```

* **Priority:** CPU first, boot loader second. An image streams in without
  blocking the console: the monitor keeps polling `BOOT_STAT` while bytes land in
  SRAM, because the loader only wins the cycles the CPU is not using.
* **Loader scope:** the loader's memory port only ever targets SRAM (it copies
  an image into RAM). Any cycle where it does not own the bus leaves the CPU in
  complete control of ROM and MMIO, which is why the monitor can run code out of
  the boot ROM throughout a load.
* **No deadlock by construction:** the loader never needs the CPU to make
  progress and the CPU's requests are simply delayed, so a load always
  terminates (the loader has its own watchdog, reported as `BOOT_ERR.TIMEOUT`).

---

## 4. Timing

```
clk        ─┐_┌─┐_┌─┐_┌─┐_┌─
req        ────┘¯¯¯¯¯¯¯└─────────  (held until ack)
ack        ─────────────┘¯¯¯¯¯└───  (one cycle after the slave sees req)
rdata      ──────────────<valid>──  (sampled on the ack edge)
```

* **Single-cycle read** (SRAM, ROM): request in cycle *n*, `ack` + `rdata` in
  cycle *n+1*.
* **Wait states** (flash controller streaming, boot engine while it is busy):
  `ack` arrives later; a data bit that would stall is acknowledged with the
  correct data on the cycle it becomes valid. The flash controller's read FIFO
  adds one wait state per byte when the FIFO is empty.
* **Write**: same shape; `rdata` is meaningless, `ack` still terminates the
  transfer.

The CPU core reads its instruction and its load data from the same bus, through
the same protocol, using `bus_addr_sel` to choose PC / ALU result / stack. There
is no separate instruction bus and no cache — at 12.5 MHz with single-cycle
SRAM, a Harvard split would buy nothing.

---

## 5. Memory map decoding

The interconnect decodes `addr` into exactly one of: SRAM (`addr <= 0x3FFF`),
boot ROM (`0xE000-0xE7FF`), MMIO (`0xF000-0xF0FF`, block = `addr[7:4]`, register
= `addr[3:0]`), or unmapped. See [MEMORY_MAP.md](MEMORY_MAP.md). `MMIO_PRESENT`
lists the blocks that have a slave; unmapped blocks still ack.

---

## 6. Adding a slave

1. Add a block number and (if needed) register offsets in `rtl/sv16_pkg.sv`, and
   set its `MMIO_PRESENT` bit.
2. Instantiate the RTL in `sv16_bus_interconnect.sv` with `req = mmio_req[blk]`,
   `rdata = rd_<name>`, `ack = ack_<name>`.
3. Wire `rd_<name>` and `ack_<name>` through `sv16_top.sv`, add pins to the LPF
   if the block leaves the chip.
4. Add a testbench that drives the bus directly (see
   `simulation/unit/flash_ctrl_tb.sv` for the pattern) and register it in the
   Makefile's `TESTBENCHES` list so `make sim` runs it.

The protocol above is the contract; a slave that registers its ack and returns
read data in the ack cycle will work with both masters without any changes.
