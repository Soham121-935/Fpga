# SV-16 Rev B — Memory Map and Address Decoding

The SV-16 bus is **word addressed**: every address is a 16-bit word index, and
transfers are 16 bits wide. "Byte address" appears only where a byte-oriented
device is involved (SPI flash, the image format, the monitor's flash commands).

---

## 1. Top-level map

| Range (word) | Size | Region | Decoded by | Access |
| :--- | :--- | :--- | :--- | :--- |
| `0x0000-0x3FFF` | 16 K words (32 KB) | **SRAM** — code, data, stack, interrupt vector table | `sv16_ram` | 1-cycle, no wait states |
| `0x4000-0xDFFF` | 40 K words | unmapped | — | read returns `0x0000`, still acknowledged (no fault) |
| `0xE000-0xE7FF` | 2 K words (4 KB) | **Boot ROM** — the resident monitor | `sv16_rom` | 1-cycle read, writes ignored |
| `0xE800-0xEFFF` | 2 K words | unmapped | — | as above |
| `0xF000-0xF0FF` | 256 words | **MMIO** — 16 blocks × 16 registers | `sv16_bus_interconnect` + peripherals | 2 cycles minimum, more with wait states |
| `0xF100-0xFFFF` | 3840 words | unmapped / reserved for future peripherals | — | as above |

### Application flash layout (ADR-019)

| Flash byte range | Contents |
| :--- | :--- |
| `0x000000-0x00001F` | slot A image header (record at `0x18`/`0x19`) |
| `0x000020-0x007FFF` | slot A image payload (up to ~32 KB) |
| `0x008000-0x00801F` | slot B image header (record at `0x8018`/`0x8019`) |
| `0x008020-0x00FFFF` | slot B image payload (up to ~32 KB) |
| `0x010000-...` | free — data area / spare slots for a future revision |

Both slots live inside the 64 KB the monitor's update protocol can address, so
either one can be programmed over UART. The loader chooses between them from the
records (see [ADR-019](ARCHITECTURE_DECISIONS.md#adr-019-ab-application-images-with-a-trial-period-and-hardware-rollback));
an image with no record boots untried from slot A unless the policy is disabled
with `BOOT_CTRL[4]`.

Programs run **from SRAM**, not from flash: the hardware boot loader copies the
image into SRAM before the CPU is released, so instruction fetch is always a
single-cycle RAM access. The boot ROM is executed only when flash has no valid
image (or when the monitor is explicitly requested).

`SYS_MEMCFG` (`0xF00D`) reports the sizes the bitstream was built with:
`[7:4]` = SRAM address width (14 → 16 K words), `[3:0]` = ROM address width
(11 → 2 K words).

---

## 2. MMIO block map (`0xF000-0xF0FF`)

Each block owns 16 word addresses. `MMIO_PRESENT = 0x07FF` marks which blocks
actually have a slave behind them — the interconnect acknowledges unmapped
registers with `0x0000` so probing never hangs.

| Blk | Base | Present | Peripheral | Documented in |
| :--- | :--- | :--- | :--- | :--- |
| `0x0` | `0xF000` | yes | System control, reset cause, debug, timers | section 3 |
| `0x1` | `0xF010` | yes | GPIO port A (16 pins, `gpio_a[15:0]`) | [PERIPHERALS](PERIPHERALS.md#gpio-0xf010-0xf070) |
| `0x2` | `0xF020` | yes | Timer 0 (compare interrupt) | [PERIPHERALS](PERIPHERALS.md#timer-0-0xf020) |
| `0x3` | `0xF030` | yes | PWM 0 (fault input) | [PERIPHERALS](PERIPHERALS.md#pwm-0-0xf030) |
| `0x4` | `0xF040` | yes | UART 0 (console / firmware upload) | [PERIPHERALS](PERIPHERALS.md#uart-0-0xf040) |
| `0x5` | `0xF050` | yes | SPI 0 (generic master, expansion bus) | [PERIPHERALS](PERIPHERALS.md#spi-0-0xf050) |
| `0x6` | `0xF060` | yes | SPI flash controller | [PERIPHERALS](PERIPHERALS.md#flash-controller-0xf060) |
| `0x7` | `0xF070` | yes | GPIO port B (16 pins, `gpio_b[15:0]`) | as GPIO A |
| `0x8` | `0xF080` | yes | Watchdog (windowed, keyed, resets the SoC) | [PERIPHERALS](PERIPHERALS.md#watchdog-0xf080) |
| `0x9` | `0xF090` | yes | Interrupt controller | [PERIPHERALS](PERIPHERALS.md#interrupt-controller-0xf090) |
| `0xA` | `0xF0A0` | yes | Boot loader engine | [BOOT_AND_PROGRAMMING](BOOT_AND_PROGRAMMING.md#5-the-boot-engine-register-block-0xf0a0) |
| `0xB-0xF` | `0xF0B0-0xF0F0` | no | reserved for future peripherals | — |

Adding a peripheral means: a block constant and `MMIO_PRESENT` bit in
`rtl/sv16_pkg.sv`, a request/ack/read-data leg in `sv16_bus_interconnect.sv`,
the instance and its top-level ports in `sv16_top.sv`, and a `LOCATE` in the
pin constraints if it reaches a pin.

---

## 3. System control block (`0xF000`, block 0)

| Off | Name | Access | Contents |
| :--- | :--- | :--- | :--- |
| `0x0` | `SYS_ID` | RO | `0x1602` — family `0x16`, major 0, minor 2 |
| `0x1` | `SYS_CTRL` | RW | `[0]` SOFTRST (restart the boot sequence), `[1]` HALT, `[2]` STEP, `[3]` IRQEN (global interrupt enable), `[4]` RAMREMAP (defined, unused). Unkeyed writes may only touch bits `[3:0]`; bits `[15:8]` must be `0xA5` to change `[15:4]` |
| `0x2` | `SYS_STAT` | RO | `[0]` HALTED, `[1]` STEP_TAKEN, `[2]` IMAGE_OK, `[3]` BOOT_FAIL, `[4]` ROM_MONITOR, `[5]` FLASH_OK, `[6]` FAULT_HALT, `[7]` ILLEGAL_SEEN |
| `0x3` | `SYS_RSTCAUSE` | RW1C | `[0]` pin, `[1]` software, `[2]` CPU fault/illegal opcode, `[3]` watchdog, `[4]` no valid image, `[5]` image loaded |
| `0x4-0x7` | `SYS_DBG_PC/SP/SR/IR` | RO | CPU program counter, stack pointer, status register, instruction register |
| `0x8` | `SYS_FAULT_ADDR` | RO | address of the last illegal instruction |
| `0x9` | `SYS_FAULT_CNT` | RW | count of illegal instructions (write clears) |
| `0xA/B` | `SYS_TICKS_LO/HI` | RO | free-running 32-bit cycle counter |
| `0xC` | `SYS_CPU_STATE` | RO | `{core FSM state, halted}` |
| `0xD` | `SYS_MEMCFG` | RO | RAM/ROM size codes |
| `0xE/F` | `SYS_SCRATCH0/1` | RW | general purpose, **survive a soft reset** (the reset logic never clears them) — the ARM-style "boot reason mailbox" |

The CPU-side debug registers are what makes the monitor able to diagnose a
locked-up application: `SYS_DBG_PC` shows where it stopped, `SYS_FAULT_ADDR`
shows the offending instruction address after an illegal-opcode trap, and
`SYS_RSTCAUSE` says whether that trap caused a restart.

---

## 4. Where code, data and the stack live

| Thing | Location | Notes |
| :--- | :--- | :--- |
| Application code | SRAM, from `0x0000` by convention | `entry` field in the image header; `make app` links at 0 |
| Application data / `.bss` | SRAM, above the code | no linker; the assembler lets you place data with `.org` |
| Stack | SRAM, top | reset value `0x3FFE` (grows down); the image may override it via its header |
| Interrupt vector table | SRAM `0x0020-0x0027` | 8 words, one 16-bit handler address per source (see below); populated by firmware |
| Monitor | Boot ROM `0xE000-0xE3A5` | 934 words; the rest of the 2 K-word ROM reads as `0x0000` |
| Monitor stack | SRAM | the monitor runs on the same stack; it is reset to `0x3FFE` by the startup sequencer |

### Interrupt vector indices

| Index | Source | Vector address |
| :--- | :--- | :--- |
| 0 | Timer 0 compare | `0x0020` |
| 1 | UART 0 RX (byte received) | `0x0021` |
| 2 | UART 0 TX (FIFO room) | `0x0022` |
| 3 | SPI 0 transfer complete | `0x0023` |
| 4 | Flash controller | `0x0024` |
| 5 | GPIO (port A/B edge) | `0x0025` |
| 6 | Watchdog early warning (`IRQ_EN`) | `0x0026` |
| 7 | **TRAP** — illegal opcode / exception | `0x0027` |

The CPU takes an interrupt only when `SR.IE = 1` and `SYS_CTRL.IRQEN = 1`. The
sequence pushes `SR` and `PC` on the stack, then loads the handler address from
the vector table; `RETI` restores `SR` (and therefore `IE`) and returns.

> **Important for applications:** the vector table lives in the *application
> image's* first 64 bytes. An image that uses interrupts must fill
> `0x0020-0x0027` with real handler addresses — a trap taken with an
> unpopulated table will jump to whatever word is there (usually `0x0000`).

---

## 5. Rev A → Rev B changes

| Item | Rev A | Rev B |
| :--- | :--- | :--- |
| SRAM | 8 K words @ `0x0000-0x1FFF` | **16 K words @ `0x0000-0x3FFF`** |
| Boot ROM | none (or `firmware/bootrom.hex` loaded by hand) | **2 K words @ `0xE000-0xE7FF`, monitor baked into the bitstream** |
| MMIO | 4 blocks (GPIO, timer, PWM, UART) | **11 blocks present** of 16 (`MMIO_PRESENT = 0x7FF`): adds SPI, flash controller, GPIO1, watchdog, IRQ controller, boot engine, system control |
| Interrupts | core lines wired ad hoc | IRQ controller with enable/pending/priority + 8-entry vector table |
| Program store | none (JTAG-loaded init file) | **external SPI flash + hardware boot loader**, two A/B slots with a trial period and hardware rollback (ADR-019) |

The ISA is unchanged (see [ISA.md](ISA.md)); Rev B is an address-map and
peripheral change only.
