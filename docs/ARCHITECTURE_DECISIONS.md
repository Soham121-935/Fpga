# SV-16 — Architecture Decisions Record (ADR)

This file tracks foundational architectural decisions for the SV-16
microcontroller. ADR-001..005 are the Rev A foundation; ADR-012..016 are the
Rev B decisions that turn the CPU into a programmable MCU (boot and program
storage, field update, Rev B memory map, CPU fixes, interrupt controller).

> Numbering note: ADR-006..011 were never written up; the decisions they were
> reserved for (peripheral set, pin constraints, verification strategy, bus
> arbitration sweep) ended up recorded in `PERIPHERALS.md`, `FPGA.md`,
> `VERIFICATION.md` and `BUS_ARCHITECTURE.md` instead. The RTL references only
> ADR-012..016, which are all present below.

---

## ADR-001: Target Device and Toolchain Compatibility
- **Status**: **ACCEPTED**
- **Context**: The master specification explicitly selects the Lattice ECP5 `LFE5U-12F-6TG144C`. The design must synthesize both in Lattice Diamond and open-source Yosys + nextpnr-ecp5 environments.
- **Decision**: All RTL must adhere to standard synthesizable SystemVerilog (IEEE 1800-2012 subset widely supported by Yosys and Diamond Synplify Pro). Avoid vendor-proprietary macro instantiation in core CPU RTL; vendor primitives (like PLL or DP16KD) should be isolated in top-level wrappers (`rtl/fpga_wrappers/`).
- **Consequences**: RTL remains fully portable, simulatable with standard Verilog/SystemVerilog engines, and directly synthesizable on Lattice ECP5.

---

## ADR-002: Multi-Cycle FSM Control Architecture for Rev A
- **Status**: **ACCEPTED**
- **Context**: SV-16 Rev A prioritizes correctness, reliability, simplicity, and debuggability over maximum pipeline throughput (Section 11, Master Spec). A pipelined design introduces data hazards, forwarding logic, branch penalties, and complex stall logic that increases verification surface exponentially.
- **Decision**: SV-16 Rev A uses a multi-cycle synchronous FSM:
  1. `FETCH`: Read instruction word from memory at `PC`, latch into `IR`, increment `PC`.
  2. `DECODE`: Decode opcode, extract operand fields, read register file operands `Rs1` and `Rs2`. If instruction is 2-word, fetch immediate word.
  3. `EXECUTE`: Perform ALU operation or evaluate branch condition or compute memory effective address.
  4. `MEMORY`: Read or write bus memory if LOAD/STORE/PUSH/POP.
  5. `WRITEBACK`: Write result to destination register `Rd` in register file, update status flags in `SR`.
- **Consequences**: Eliminates pipeline hazards; guarantees deterministic execution; makes single-stepping and trace debugging straightforward.

---

## ADR-003: Register File Organization
- **Status**: **ACCEPTED**
- **Context**: Spec mandates 8 general-purpose registers: `R0`, `R1`, `R2`, `R3`, `R4`, `R5`, `R6`, `R7`, each 16 bits (128 bits total storage).
- **Decision**:
  - 2 asynchronous/synchronous read ports (`rdata1`, `rdata2`) with 3-bit addresses (`raddr1`, `raddr2`).
  - 1 synchronous write port (`wdata`) with 3-bit address (`waddr`) and active-high write enable (`wen`).
  - `R0` is a general read/write register (NOT hardwired to 0, matching standard 16-bit CISC/RISC architectures; clear operations can set `R0` explicitly).
- **Consequences**: Allows dual-operand instructions like `ADD Rd, Rs` or `ADD Rd, Rs1, Rs2` in a single execute cycle.

---

## ADR-004: Status Register (SR) Flag Definitions
- **Status**: **PROVISIONAL (Awaiting Final Signoff)**
- **Context**: Master instruction mandates architectural flags `Z` (Zero), `C` (Carry), `N` (Negative), and `V` (Overflow).
- **Decision**:
  - `SR[0]`: `Z` (Zero flag: set when ALU result == 0)
  - `SR[1]`: `C` (Carry flag: unsigned borrow/carry out of bit 15)
  - `SR[2]`: `N` (Negative flag: bit 15 of result)
  - `SR[3]`: `V` (Overflow flag: signed two's complement overflow)
  - `SR[7]`: `IE` (Global Interrupt Enable: 1 = enabled, 0 = disabled)
  - `SR[6:4]`, `SR[15:8]`: Reserved (read as 0)
- **Consequences**: Unambiguous hardware bit mapping and assembly flag condition testing.

---

## ADR-005: Memory Bus Organization
- **Status**: **PROVISIONAL (Awaiting Final Signoff)**
- **Context**: Need a simple, synthesizable, synchronous system bus connecting CPU to internal BRAM and memory-mapped peripherals.
- **Decision**: A unified 16-bit synchronous bus:
  - `bus_addr[15:0]`: 16-bit word address
  - `bus_wdata[15:0]`: 16-bit write data
  - `bus_rdata[15:0]`: 16-bit read data
  - `bus_we`: Write enable (1 = write, 0 = read)
  - `bus_req`: Bus access request strobe
  - `bus_ack`: Slave acknowledge (ready) signal
- **Consequences**: Zero wait-state access for single-cycle on-chip BRAM (`ack = 1`), wait-state support for slower peripheral access or UART FIFOs.

---

## ADR-012: Program storage and boot — hardware loader + SPI NOR + resident monitor
- **Status**: **ACCEPTED** (Rev B)
- **Context**: Rev A had no non-volatile program store: firmware existed only as a
  block-RAM init file, and "programming the device" meant rebuilding and
  re-flashing the FPGA. Treating SV-16 as an MCU requires that a program survive
  power cycles and that it can be replaced without touching the FPGA
  configuration.
- **Decision**:
  - Applications are stored as CRC-checked images in an external **SPI NOR flash**
    (see `docs/BOOT_AND_PROGRAMMING.md`, section 4 for the image format).
  - The **boot loader is hardware**, not a CPU program: `rtl/sv16_boot.sv` is a
    second bus master that reads flash, verifies magic/header CRC/payload CRC and
    copies the payload into SRAM before the CPU is released. A CPU program cannot
    do this, because the program that would do it is the one being replaced — and
    because a broken image must not be able to prevent recovery.
  - A **resident monitor** lives in the boot ROM (`0xE000`, 2 K words, compiled
    into the bitstream) and is entered whenever no valid image is found, when the
    loader fails, when software requests it, or when the serial RX line is held
    low through reset.
- **Consequences**: Programming the FPGA defines the machine; programming the
  serial port defines the application. A board whose application is broken can
  always be recovered with a serial cable. Cost: 18 block RAMs (SRAM + ROM) and
  roughly 1.4 k LUTs for the loader; the boot ROM contents become a synthesis-time
  macro (`SV16_ROM_INIT_FILE`) that the Makefile regenerates from assembly.

---

## ADR-013: Field reprogramming over UART with a framing protocol
- **Status**: **ACCEPTED** (Rev B)
- **Context**: The field-update path has to work with nothing but a serial
  terminal, on a byte-oriented UART with a 4-byte FIFO and no flow control, and
  it has to be verifiable end to end.
- **Decision**:
  - The monitor speaks a small **fixed-width ASCII protocol**:
    `C<addr4><len4><crc4>` + payload, `R<addr4><len4>`, `E<addr4>`, `V<addr4>`,
    `B`, `?`. Every command answers (`+OK`, `=crc4`, `.` per byte, `-E<n>`).
  - The upload is **self-clocking**: the host sends one payload byte and waits for
    the monitor's `.` before sending the next. That makes the exchange immune to
    FIFO overrun no matter how fast the host writes, at the cost of throughput
    (roughly 5 KB/s of payload at 115200 baud).
  - Data integrity is a **CRC16-CCITT** over the uploaded bytes, checked by the
    monitor *before* the image is trusted, plus the header and payload CRCs that
    the loader re-checks at every boot.
  - **All flash knowledge lives in `rtl/sv16_flash_ctrl.sv`** (command set, page
    buffering, sector erase, `tPROG`/`tERASE` waits, CRC over a range). Neither
    the monitor nor an application has to know NOR timing.
- **Consequences**: A host tool (`scripts/sv16_mon.py`, `make upload`) is a
  convenience, not a requirement — the protocol is human-typeable. Images are
  verified twice (monitor + loader). Cost: hex text doubles the wire time versus a
  binary protocol; there is no resume and no compression. (A/B slots with
  rollback arrived later, in ADR-019.)

---

## ADR-014: Rev B memory map and peripheral block organization
- **Status**: **ACCEPTED** (Rev B)
- **Context**: Rev A's map had 8 K words of SRAM, no ROM, four peripherals at
  hand-picked addresses and spare ports wired "when a peripheral appears".
  Adding flash, boot, system control and a second GPIO needed a scheme, not more
  special cases.
- **Decision**:
  - SRAM grows to **16 K words** (`0x0000-0x3FFF`), the **boot ROM** occupies
    `0xE000-0xE7FF`, and all peripherals live in a single **MMIO window**
    `0xF000-0xF0FF` organized as **16 blocks × 16 registers**, with the block
    selected by `addr[7:4]` and the register by `addr[3:0]`.
  - `MMIO_PRESENT` marks which of the 16 blocks have a slave; unmapped addresses
    (including unimplemented blocks) are acknowledged and read as `0x0000`, so
    probing the map cannot hang the bus.
  - The block numbers are fixed by `rtl/sv16_pkg.sv`: 0 system, 1 GPIO A,
    2 timer, 3 PWM, 4 UART, 5 SPI, 6 flash, 7 GPIO B, 8 watchdog (reserved),
    9 interrupt controller, 0xA boot, 0xB-0xF reserved.
- **Consequences**: A new peripheral is a 16-register block plus a `MMIO_PRESENT`
  bit; the decoder is a shift/mask instead of a tree of comparators, which keeps
  the top level readable and the decode timing shallow. The interrupt vector table
  lives at `0x0020` in SRAM (8 words), which keeps it inside the application's own
  image.

---

## ADR-015: CPU fixes — register selection, two-word LDI, and the held-request bus contract
- **Status**: **ACCEPTED** (Rev B)
- **Context**: Bringing up the monitor exposed three CPU-side defects: Rev A
  mis-mapped the `STORE` data field and the `PUSH` register field in the decoder,
  `LDI` needed an explicit write-back state, and the control unit dropped bus
  requests when a slave withheld its ack.
- **Decision**:
  - Decoder port assignment is fixed (`docs/ISA.md` is authoritative): `STORE`
    takes its data from `Rs2`, `PUSH` from its explicit register field;
    `CMP` uses `Rs1`/`Rs2`.
  - `LDI` (two-word immediate) is routed through `S_WRITEBACK` like any other
    register write, so one write path exists for all register writes.
  - The CPU **holds** `bus_addr`/`bus_we`/`bus_wdata`/`bus_req` until `bus_ack`
    arrives, and does not advance its FSM on a cycle without an ack. Load data is
    captured only on the ack of the load's own transfer.
- **Consequences**: Slow peripherals and bus contention become invisible to
  instruction semantics — an access takes longer instead of returning the wrong
  value. This is the change that made the loader, the flash controller and the
  monitor coexist; it is also why the whole regression (113 checks) is the
  gate for any further bus work.

---

## ADR-016: Interrupt controller with enable/pending/priority and a RAM vector table
- **Status**: **ACCEPTED** (Rev B)
- **Context**: Rev A wired peripheral interrupt lines directly to the core, with
  no way to mask, prioritize or observe them, and no handler dispatch mechanism.
- **Decision**:
  - A dedicated controller (`0xF090`) provides per-source **enable**, **pending**
    (with write-1-to-clear), raw **lines**, and the index of the source being
    served; eight sources are defined (timer, UART RX/TX, SPI, flash, GPIO,
    watchdog, TRAP) in `sv16_pkg.sv`.
  - The handler address is fetched from an **8-entry vector table in SRAM at
    `0x0020`**, one word per source, populated by the application image. The CPU
    pushes `SR` and `PC` before the vector fetch and `RETI` restores `SR`.
  - Global gating is two-level: `SYS_CTRL.IRQEN` (system) and `SR.IE` (CPU), so
    both the system writer and the interrupt-disabled code path can inhibit
    interrupts.
- **Consequences**: Handlers can be written in assembly with a plain address
  table; an unpopulated table is visible (a trap jumps to whatever word is there),
  so images that use interrupts must fill `0x0020-0x0027`. Priority is fixed by
  index; there is no nesting control and no interrupt latency specification yet.

---

## ADR-017: Watchdog in the reset path, protected by a key and a lock
- **Status**: **ACCEPTED** (Rev B)
- **Context**: An MCU that can be reprogrammed in the field but cannot recover
  from its own firmware hanging is only half a microcontroller: the classic
  failure mode is a control loop that stops making progress, and the classic
  answer is a watchdog that restarts the system. Rev B had `SYS_RSTCAUSE.WDT`
  reserved, an IRQ slot for the watchdog and a spare MMIO block, but no timer
  behind them. It also had a design question: a watchdog that software can
  disable (by accident, or by a wild pointer) is worth very little.
- **Decision**:
  - A dedicated block (`rtl/sv16_wdt.sv`, MMIO block 8 at `0xF080`) with
    `(PRESET + 1) x 2^PRESC` clock period, so the same block covers "the control
    loop stalled" (milliseconds) and "the boot load never finished" (hundreds of
    milliseconds).
  - A timeout **restarts the boot sequence** through `sv16_startup` and sets
    `RSTCAUSE.WDT`. It is not a trap or an interrupt: a hung program cannot be
    relied on to handle anything.
  - **Protection**: `CTRL` (which holds ENABLE, LOCK, WINDOW_EN and PRESC) is
    keyed with `0x5A` in the top byte; `FEED` requires the magic word `0x5A5A`;
    `PRESET`/`WINDOW`/`MARGIN` are plain 16-bit registers but are frozen by
    `LOCK`. `LOCK` can only be cleared by the external reset pin. (A 16-bit
    period and an 8-bit key cannot share one 16-bit register — hence the split
    rather than a keyed write to every register.)
  - The block hangs off the **hard reset** (`rst_n`), never the SoC's own soft
    restart (`cpu_rst_n`), and it **auto-reloads its counter on expiry**. So an
    application that hangs twice is restarted twice, and each restart gets a
    full period to reach the code that feeds it.
  - An **early-warning interrupt** (`IRQ_WDT`, source 6) fires `MARGIN` ticks
    before expiry so software can leave a breadcrumb in `SYS_SCRATCH0/1`, which
    survive a restart.
  - **Windowed feeding** (`WINDOW_EN` + `WINDOW`) rejects feeds that arrive too
    soon after the previous one, which is the only way to catch a runaway loop
    that feeds the watchdog non-stop. The first period after `ENABLE` is exempt
    so that arming the watchdog and feeding it immediately stays legal.
- **Consequences**: A hung application now recovers by itself — proven end to
  end by `wdt_reset_tb`, which boots a deliberately hanging image out of flash
  and watches the hardware restart it twice with no host involved. The watchdog
  starts disabled, so an application must arm it (three stores); a watchdog that
  arms itself at reset was rejected because the boot ROM monitor and the loader
  would then have to feed it too, and the monitor is the recovery path — it must
  not be able to be interrupted by the thing it is there to recover from. The
  cost is 1 block of MMIO, ~220 lines of RTL and 281 extra LUTs.

---

## ADR-018: DIV and MOD move to a multi-cycle divider (and the SoC ships at 25 MHz)
- **Status**: **ACCEPTED** (Rev B)
- **Context**: The SoC shipped at 12.5 MHz because 25 MHz did not close timing
  (measured Fmax 14.68 MHz). The documented explanation was that the critical
  path ran "register file → ALU → flags → control-unit next-state" and through
  `u_sys.illegal_pc`, and the documented fix was to split the branch decision
  with an extra FSM state. **Both were wrong.** The nextpnr critical-path report
  and a one-line experiment settled it: replacing the ALU's `a / b` and `a % b`
  with constants lifted Fmax from 14.68 MHz to 44.31 MHz in a single change.
  A 16/16 combinational divider is a deep cascade of 16 conditional subtracts
  (each a 16-bit carry chain), and every arithmetic instruction paid for it
  because the divider sat inside the same combinational block as the adder.
- **Decision**:
  - `sv16_alu` keeps a **single iterative restoring divider** for both DIV and
    MOD: `div_start` (one-cycle pulse, operands latched) → `div_busy` high for
    exactly 16 clocks → quotient/remainder available in `result`, with the flags
    valid in the same cycle `div_busy` falls.
  - The control unit gets one new state, **`S_DIV_WAIT` (5'd16)**: S_EXECUTE
    pulses `alu_div_start` for a DIV/MOD and hands over to S_DIV_WAIT, which
    holds until `alu_div_busy` falls and only then raises `flag_update_en` (early
    capture would latch a flag computed from an intermediate remainder) before
    continuing to S_WRITEBACK.
  - The ISA is unchanged: DIV/MOD still exist, with identical results and flags,
    including the divide-by-zero behaviour of OQ-04 (`V=1`, quotient `0xFFFF`,
    remainder `0x0000`). What changes is the cycle count: 18 cycles instead of 1.
    This is exactly what a real MCU does with a hardware divider used by a rare
    instruction — an instruction-level optimisation would have shortened it, a
    machine-level one forbids a 68 ns path.
  - With the divider out of the way, **the shipped clock becomes the full
    25 MHz** (the oscillator, no fabric divider at all: `CLKDIV=1`), at a
    measured Fmax of 46.58 MHz — ~86 % margin. The divided-clock option stays in
    the build (`make bitstream CLKDIV=2`) as a fallback for a board that cannot
    run at 25 MHz, and the clock divider RTL is unchanged.
- **Consequences**: The CPU is twice as fast as the part shipped an hour earlier,
  the bus and peripherals run at 25 MHz (UART divisor recomputes itself from
  `CLK_HZ`: 217 clocks/bit at 25 MHz, 0.006 % baud error), the flash controller
  is unaffected because it polls the device's WIP bit rather than counting
  clocks, and the SPI master's divider is a register (SCLK = 3.125 MHz at reset).
  Simulation now matches hardware exactly: the six testbenches have always driven
  `clk_25m` at 25 MHz and assumed 217 cycles/bit, so the bitstream is finally
  clocked like the thing that is verified. The cost is 25 RTL lines, one FSM
  state, and 16 extra cycles for the two rarest instructions; ~1,150 LUTs were
  freed (7,233 vs 6,147 logic LUTs is more, but the 4,448→4,631 FF and 18 BRAM
  counts are unchanged and the part is still only 34 % full).

---

## ADR-019: A/B application images with a trial period and hardware rollback
- **Status**: **ACCEPTED** (Rev B)
- **Context**: ADR-012 gave the SoC a hardware boot loader and ADR-013 a way to
  reprogram it over UART, but there was exactly one image at flash address 0.
  A field update is therefore a *destructive* operation: the monitor erases the
  sector holding the running image, and a power cut, a bad build or a hang in
  the new firmware leaves the part with nothing bootable. The recovery path is
  the monitor, which needs a host. The WDT (ADR-017) can restart a hung
  application, but it restarts it into the same broken image, so a hang is a
  boot loop, not a recovery. What was missing is the thing every practical MCU
  has: an update that can be undone by the part itself.
- **Decision**:
  - **Two slots, 32 KB apart, inside the first 64 KB of the flash**: slot A at
    `0x000000`, slot B at `0x008000`. Keeping both inside the 64 KB the
    monitor's 16-bit update protocol can address is deliberate (a 64 KB stride
    pushed slot B out of reach, i.e. the *inactive* slot — the one a field
    update must write — could only be programmed with an external programmer).
    32 KB per slot is far more than an image can use with 32 KB of RAM.
  - **The slot record lives in the image header**, in the eight reserved bytes
    of the format-v1 header, at byte offset `0x18` (header word `0x0C`; the
    header CRC covers `0x00-0x13`, so writing a record cannot invalidate the
    image, and it can never collide with payload bytes):
    - `0x18` = sync `0xA5`, written once and never changed,
    - `0x19` = state, the only byte that ever changes:
      `0x1F` PENDING (installed, never booted) → `0x0F` TRIED (booted, awaiting
      confirmation) → `0x07` GOOD (confirmed, the fallback image) or `0x04` BAD
      (trial failed / retired).
  - **Every transition only clears bits** (`0x1F → 0x0F → 0x07 / 0x04`). This is
    not cosmetic: a page program on real NOR flash can only turn 1s into 0s, and
    no erase unit is small enough to rewrite one byte in the middle of an image,
    so any encoding that needed a bit set back would need a sector erase — which
    would erase the image the record belongs to. The read-back check in the
    loader (`rec_b1 == l_wr_data`) is what keeps the encoding honest, and the
    flash *simulation model* implements the same physics (program = AND) so a
    violation fails `slot_tb` instead of the board.
  - **The record is written by the loader as one 2-byte page program** (sync +
    state), so a power cut can leave `{0xA5, 0xFF}` — "record started, state
    never written" — which the classifier reads as *no record*, or a state byte
    with unrecognised bits, which it reads as BAD and reports in `BOOT_ERR[7]`.
    Fail toward rollback: a torn record can never promote an image.
  - **Pick order** (the class value doubles as the priority, ties settle on
    slot A): PENDING > TRIAL > GOOD > no-record > BAD. A PENDING image is the
    new one and wins; a TRIAL image has already had its chance and is retired
    (BAD) *without being loaded*; GOOD is the confirmed image; an image with no
    record at all (one flashed by any other tool) boots untried, which is how
    every existing image and the monitor's own recovery image keep working.
  - **Trial and rollback**: on the first boot of a PENDING slot the loader
    writes TRIED *before* releasing the CPU, then streams the image. If the part
    restarts before the application confirms, the record still says TRIED, so
    the loader writes BAD and boots the other slot — in the same attempt, with
    no host. The state is in *flash*, not in the loader: the reset that triggers
    the rollback is exactly the reset that would clear a flip-flop copy of it
    (an earlier draft used a `tried` register and could never have worked on
    hardware; `slot_tb` now pulses `rst_n` to prove the flash version does).
  - **Confirmation** is one write: `BOOT_CTRL[6]` (write-only pulse) makes the
    loader program `0x07` over the running slot's record and then retire the
    *other* slot's record to BAD. With two GOOD records the pick would settle on
    slot A and a confirmed update would silently revert; retiring the other
    image keeps exactly one live image, and the retired one is the image that
    was current before the update.
  - **Registers are the existing ones** — no new offsets, so no firmware
    register map moves: `BOOT_CTRL[4]` NOSLOT (active low: 1 = ignore the
    records and boot `BOOT_SRC`), `[5]` SLOT_CLR, `[6]` SLOT_CNF;
    `BOOT_STAT[5]` SLOT, `[6]` RETRY, `[7]` TRIAL; `BOOT_ERR[7]` SLOT. A write
    that carries a write-only pulse bit is a *control* write: it does not touch
    AUTO or NOSLOT, so an application committing its own trial cannot disarm the
    boot policy by accident.
  - **Tooling**: `sv16_fwpack.py --slot N [--slot-state ...]` writes the record
    into the image (so the image a host flashes *is* the record);
    `make slot-image SLOT=1` / `make upload-slot SLOT=1` install it into the
    inactive slot over UART; `make mon-boot` boots it (the loader picks the
    pending slot); `make commit` (monitor command `K`) commits it. Firmware uses
    `sv16_boot_confirm()` from `firmware/drivers/sv16_hardware.h`.
- **Consequences**: A field update is now non-destructive: the previous image
  is untouched until the new one has proved itself, a hang or a power cut during
  the trial rolls back by itself on the next restart, and the recovery path is
  the fallback image rather than the monitor. The demo image
  (`firmware/examples/motor_test.s`) commits itself at the end of its
  initialisation, so the shipped example exercises the whole loop. Cost: ~430
  lines of RTL across `sv16_boot.sv`/`sv16_flash_ctrl.sv`, one slot-record
  plumbing path (a 2-byte page program that re-uses the existing program
  sequencer and takes priority over an application page flush), one new flash
  command *sequence* (not a new command), and `slot_tb` (57 checks) as the
  regression. Limitations, documented in
  [BOOT_AND_PROGRAMMING.md](BOOT_AND_PROGRAMMING.md#8-what-is-still-missing-for-production-programming):
  records are not written while the application runs (a write costs one page
  program, so the update tool decides when), there is no signed image (ADR-019
  is integrity, not authenticity), and the rollback depth is one generation.
