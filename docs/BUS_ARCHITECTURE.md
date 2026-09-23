# SV-16 Rev A — System Bus Architecture

---

## 1. Bus Overview

The SV-16 system bus is a synchronous, master-slave 16-bit address and data bus optimized for FPGA implementation. It provides clean separation between the CPU execution core, internal memory blocks, and memory-mapped peripheral controllers.

```text
                  ┌────────────────────┐
                  │    SV-16 Core      │
                  │   (Bus Master)     │
                  └─────────┬──────────┘
                            │
              ┌─────────────┼─────────────┐
              │ addr[15:0]  │ wdata[15:0] │ rdata[15:0]
              │ req         │ we          │ ack
              ▼             ▼             ▼
  ┌──────────────────────────────────────────────────┐
  │                 Address Decoder                  │
  └───────────┬──────────────┬─────────────┬─────────┘
              │              │             │
              ▼              ▼             ▼
       ┌─────────────┐ ┌───────────┐ ┌───────────┐
       │   RAM 8K    │ │   GPIO    │ │   Timer   │ ...
       │ (0x0000 -   │ │ (0xF010 - │ │ (0xF020 - │
       │  0x1FFF)    │ │  0xF013)  │ │  0xF023)  │
       └─────────────┘ └───────────┘ └───────────┘
```

---

## 2. Bus Signal Definitions

All signals are synchronous to the positive edge of `clk`.

| Signal Name | Direction (Master perspective) | Width | Description |
| :--- | :--- | :--- | :--- |
| `clk` | Master / System | 1 bit | Master synchronous clock |
| `rst_n` | Master / System | 1 bit | Active-low synchronous/asynchronous system reset |
| `bus_addr` | Master $\to$ Slaves | 16 bits | Word address bus (`0x0000` to `0xFFFF`) |
| `bus_wdata`| Master $\to$ Slaves | 16 bits | Write data bus from CPU to peripherals/RAM |
| `bus_rdata`| Slaves $\to$ Master | 16 bits | Read data bus multiplexed from selected slave |
| `bus_we` | Master $\to$ Slaves | 1 bit | Write Enable: `1` = Write cycle, `0` = Read cycle |
| `bus_req` | Master $\to$ Slaves | 1 bit | Bus Request: Asserted high when master initiates transfer |
| `bus_ack` | Slaves $\to$ Master | 1 bit | Bus Acknowledge: Asserted high by slave when transfer complete |

---

## 3. Bus Transaction Timing

### Single-Cycle Read Access (e.g. Block RAM or Single-Cycle Peripheral Register)
```text
          Cycle 0       Cycle 1       Cycle 2
clk     : ___/‾‾‾\___/‾‾‾\___/‾‾‾\___/‾‾‾\___
bus_addr: ------<    ADDR 0x1000     >-------
bus_req : ____________/‾‾‾‾‾‾‾‾‾‾‾\__________
bus_we  : ___________________________________ (Read = 0)
bus_rdata: -------------<   DATA_VAL   >------
bus_ack : ____________/‾‾‾‾‾‾‾‾‾‾‾\__________
```
- At Clock Cycle 1 posedge: CPU asserts `bus_req = 1`, `bus_we = 0`, sets `bus_addr`.
- Slave decodes address, immediately returns `bus_ack = 1` and valid `bus_rdata`.
- At Clock Cycle 2 posedge: CPU captures `bus_rdata`, deasserts `bus_req`.

### Multi-Cycle Access with Wait-States (e.g. External SPI / UART FIFO)
- If a slave requires multiple clock cycles to complete a transfer (or synchronize clock domains), it holds `bus_ack = 0` until ready.
- The CPU FSM stalls in its current `S_FETCH` or `S_MEMORY` state while `bus_req == 1 && bus_ack == 0`.
- Once the slave asserts `bus_ack = 1`, the transfer completes on the next rising clock edge.
