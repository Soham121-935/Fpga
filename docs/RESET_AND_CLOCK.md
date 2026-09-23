# SV-16 Rev A — Reset and Clock Architecture

---

## 1. Target Clock Architecture

- **FPGA Device**: Lattice ECP5 `LFE5U-12F-6TG144C`
- **Primary System Clock Frequency (`clk`)**: **25.0 MHz** (Period = 40.0 ns)
- **Clock Source**: Onboard 25 MHz oscillator connected to dedicated primary clock pin (PCLK) on Lattice ECP5.
- **Clock Distribution**: Routed via Lattice ECP5 primary clock routing networks (`DCS` / `PCLK` tree) for ultra-low skew (<150 ps).
- **Design Philosophy**: Prioritize timing margin, signal integrity, and reliable multi-peripheral operation over excessive clock speed. A 25 MHz system clock provides ample performance for 16-bit real-time motor PID loops, sensor reading, and UART communications.

---

## 2. Reset Architecture

### Reset Inputs and Conditions
1. **External Hardware Reset Pin (`ext_rst_n`)**: Active-low physical push button or supervisory reset IC pin.
2. **Power-On Reset (POR)**: Internal Lattice ECP5 power-good detector.

### Reset Synchronization
- An asynchronous assert, synchronous de-assert reset bridge (2-stage flip-flop synchronizer) ensures clean startup without reset race conditions or metastability:
```text
           VCC
            │
          ┌─┴─┐   ┌───┐   ┌───┐
ext_rst_n─┤ D ├───┤ D ├───┤ D ├──► sys_rst_n (to all CPU logic)
          │   │   │   │   │   │
clk ──────┤CLK├───┤CLK├───┤CLK│
          └───┘   └───┘   └───┘
```

### Architectural State on Reset Release
- **`PC`**: Reset to `0x0000` (Vector 0: Reset Handler).
- **`IR`**: Reset to `16'h0000` (`NOP`).
- **`SR`**: Reset to `16'h0000` (Flags cleared, interrupts disabled).
- **`SP`**: Reset to `16'h1FFE` (Top of internal data RAM).
- **Registers `R0`–`R7`**: Reset to `16'h0000`.
- **CPU Control FSM**: State set to `S_FETCH`.
- **System Bus**: `bus_req = 0`, `bus_we = 0`.
- **Peripherals (GPIO, PWM, Timer, UART)**: Outputs disabled, all pins high-Z inputs, PWM duty 0%.
