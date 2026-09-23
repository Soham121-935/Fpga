# SV-16 Rev A — Peripheral Subsystem Architecture

---

## 1. Scope

This document defines the hardware peripheral architecture for SV-16 Rev A. Peripherals provide the bridge between CPU instructions and real-world electrical systems.

The primary target demonstration is:
```text
SV-16 CPU Firmware
        │
    (System Bus)
        │
   PWM Peripheral
        │
    FPGA Pin (TQFP-144)
        │
  External Motor Driver (H-Bridge)
        │
     DC Motor
```

---

## 2. Peripheral Specifications

### 2.1 GPIO Controller (`0xF010`)
- **Port Width**: 16 bidirectional I/O pins (`gpio_pin[15:0]`).
- **Input Filtering / Synchronizer**: 2-stage flip-flop synchronizer on all input pins to prevent metastability into internal logic.
- **Direction Register (`GPIO_DIR`)**:
  - `1`: Pin is configured as digital output (`gpio_oen = 1`).
  - `0`: Pin is configured as high-impedance digital input (`gpio_oen = 0`).
- **Atomic Operations (`GPIO_SET` / `GPIO_CLR`)**:
  - Eliminates read-modify-write race conditions when controlling individual pins from firmware.
  - Writing `1` to `GPIO_SET[k]` asserts pin `k` high.
  - Writing `1` to `GPIO_CLR[k]` asserts pin `k` low.

### 2.2 Hardware Timer 0 (`0xF020`)
- **Counter Width**: 16 bits (`0` to `65535`).
- **Clock Prescaler**: Configurable power-of-two clock division (1, 2, 4, 8, 16, 64, 256, 1024).
- **Match Register**: Triggers interrupt or auto-reload when `counter == compare`.
- **Interrupt Output**: Asserts level-sensitive interrupt line to core interrupt controller.

### 2.3 Hardware PWM Controller 0 (`0xF030`)
- **Resolution**: 16-bit counter resolution.
- **Clock Base**: System clock divided by programmable prescaler.
- **Operation**:
  - Counter increments each tick from `0` to `PWM_PERIOD - 1`.
  - When counter wraps to `0`, PWM output is set high.
  - When counter reaches `PWM_DUTY`, PWM output is set low.
  - Generates glitch-free, high-resolution duty cycles from 0.0% to 100.0%.
- **Safety Fault Input**: External hardware emergency stop or overcurrent detect pin immediately forces PWM outputs low asynchronously.

### 2.4 Hardware UART 0 (`0xF040`)
- **Baud Generation**: 16-bit programmable fractional/integer divider.
  - Default: 115,200 baud from 25 MHz system clock (`divisor = 25,000,000 / 115,200 ≈ 217`).
- **Framing**: 8 data bits, 1 stop bit, no parity (8-N-1).
- **Buffering**: Single-byte double-buffered TX and RX registers (with status flags for overrun and framing errors).

---

## 3. Peripheral Address Decoding Scheme

Address decoding is performed by examining `bus_addr[15:4]`:
- `16'hF01_` $\implies$ GPIO Controller
- `16'hF02_` $\implies$ Timer 0
- `16'hF03_` $\implies$ PWM Controller 0
- `16'hF04_` $\implies$ UART 0
- `16'hF05_` $\implies$ SPI 0
- `16'hF06_` $\implies$ I2C 0
