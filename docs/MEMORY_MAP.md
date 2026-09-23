# SV-16 Rev A — Memory Map & Address Decoding

---

## 1. Address Space Overview

The SV-16 Rev A processor utilizes a unified 16-bit word-addressed memory map providing direct access to 64K words (`0x0000` to `0xFFFF`).

```text
0x0000 ┌────────────────────────────────────────┐
       │ Vector Table & Program / Code RAM       │
       │ (4K Words: 0x0000 - 0x0FFF)             │
0x1000 ├────────────────────────────────────────┤
       │ Data RAM & Stack Space                  │
       │ (4K Words: 0x1000 - 0x1FFF)             │
0x2000 ├────────────────────────────────────────┤
       │ Expansion Memory / Unmapped             │
       │ (0x2000 - 0xEFFF)                       │
0xF000 ├────────────────────────────────────────┤
       │ Memory-Mapped I/O Peripherals           │
       │ (4K Words: 0xF000 - 0xFFFF)             │
0xFFFF └────────────────────────────────────────┘
```

---

## 2. On-Chip BRAM Allocation for Lattice ECP5-12F

The **Lattice ECP5 LFE5U-12F** contains 32 sysMEM DP16KD block RAMs (each 18 Kbit = 16K data bits + 2K parity bits), providing a total of 576 Kbits (~36K 16-bit words).

For Rev A baseline implementation:
- **Program & Data RAM**: Initialized to 8K words (16 KB) internal dual-port / single-port BRAM (`0x0000`–`0x1FFF`).
  - `0x0000`–`0x0FFF` (4K words): Code & Read-Only Constants
  - `0x1000`–`0x1FFE` (4K words): General Data RAM
  - `0x1FFF` down to `0x1A00`: System Call & Return Stack (Full-descending stack, default initial `SP = 0x1FFE`)

---

## 3. Peripheral Memory Map (`0xF000` to `0xFFFF`)

Peripherals are mapped into individual 64-word blocks (`0x0040` words per peripheral):

| Base Address | Peripheral | Description | Registers Defined |
| :--- | :--- | :--- | :--- |
| `0xF000` | **System Control / Core** | CPU status, clocks, reset flags | `SYS_STATUS`, `SYS_CTRL` |
| `0xF010` | **GPIO Controller** | 16-bit General Purpose I/O | `GPIO_DATA`, `GPIO_DIR`, `GPIO_SET`, `GPIO_CLR` |
| `0xF020` | **Timer 0** | 16-bit hardware periodic timer | `TMR0_CNT`, `TMR0_CMP`, `TMR0_CTRL`, `TMR0_STAT` |
| `0xF030` | **PWM Controller 0** | Motor/LED pulse width modulation | `PWM0_PERIOD`, `PWM0_DUTY`, `PWM0_CTRL` |
| `0xF040` | **UART 0** | Asynchronous serial transceiver | `UART0_DATA`, `UART0_STATUS`, `UART0_BAUD`, `UART0_CTRL` |
| `0xF050` | **SPI Controller 0**| Synchronous serial peripheral | `SPI0_DATA`, `SPI0_STATUS`, `SPI0_CTRL`, `SPI0_CLKDIV` |
| `0xF060` | **I2C Controller 0**| Inter-Integrated Circuit master | `I2C0_DATA`, `I2C0_STATUS`, `I2C0_CTRL`, `I2C0_CLKDIV` |
| `0xF070`–`0xFFFF` | Reserved | Reserved for Rev B / future peripherals | - |

---

## 4. Detailed Peripheral Register Offsets

### GPIO Controller (`0xF010`)
- `0xF010`: `GPIO_DATA` — Read: Pin input state. Write: Output latch value.
- `0xF011`: `GPIO_DIR`  — Direction: `1` = Output, `0` = Input.
- `0xF012`: `GPIO_SET`  — Atomic pin set (writing `1` sets corresponding pin high).
- `0xF013`: `GPIO_CLR`  — Atomic pin clear (writing `1` clears corresponding pin low).

### Timer 0 Controller (`0xF020`)
- `0xF020`: `TMR0_CNT`  — Current 16-bit counter value (R/W).
- `0xF021`: `TMR0_CMP`  — 16-bit compare match register (R/W).
- `0xF022`: `TMR0_CTRL` — Control register:
  - Bit 0: `EN` (Timer enable)
  - Bit 1: `AUTO_RELOAD` (Reset counter to 0 on match)
  - Bit 2: `IE` (Interrupt enable on match)
  - Bits 7-4: Prescaler division select (1, 2, 4, 8, 16, 64, 256, 1024)
- `0xF023`: `TMR0_STAT` — Status register:
  - Bit 0: `MATCH` (Set when `CNT == CMP`, write 1 to clear)

### PWM Controller 0 (`0xF030`)
- `0xF030`: `PWM0_PERIOD` — 16-bit period value (sets PWM frequency).
- `0xF031`: `PWM0_DUTY`   — 16-bit duty cycle threshold (high when `counter < duty`).
- `0xF032`: `PWM0_CTRL`   — Control:
  - Bit 0: `EN` (PWM output enable)
  - Bit 1: `POL` (0 = active high, 1 = active low)
  - Bit 2: `FAULT` (Emergency motor brake / shutdown state)

### UART 0 Controller (`0xF040`)
- `0xF040`: `UART0_DATA`   — Read: RX byte [7:0]. Write: TX byte [7:0].
- `0xF041`: `UART0_STATUS` — Status:
  - Bit 0: `TX_READY` (1 = Ready to accept new transmit byte)
  - Bit 1: `RX_VALID` (1 = Receive byte waiting in buffer)
  - Bit 2: `OVERRUN_ERR` (1 = Receive overflow error)
  - Bit 3: `FRAME_ERR` (1 = Framing error)
- `0xF042`: `UART0_BAUD`   — 16-bit baud rate clock divisor (`clk_freq / baud_rate`).
- `0xF043`: `UART0_CTRL`   — Control:
  - Bit 0: `TX_EN`
  - Bit 1: `RX_EN`
  - Bit 2: `TX_IE` (TX interrupt enable)
  - Bit 3: `RX_IE` (RX interrupt enable)
