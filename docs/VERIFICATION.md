# SV-16 Rev A — Verification Strategy and Test Plan

---

## 1. Verification Strategy

SV-16 Rev A enforces strict bottom-up verification (Rule 2 and Rule 40):
1. **Module Unit Testing**:
   - Every RTL module must have an accompanying self-checking testbench (`module_tb.sv` or equivalent).
   - Testbenches check nominal behavior, boundary cases, and invalid inputs.
2. **Subsystem Integration Testing**:
   - Datapath testing: Register File + ALU + SR integration.
   - Memory Subsystem testing: Bus arbiter + RAM + Bus timing.
3. **CPU Execution Verification**:
   - Automated instruction execution tests: verifying every opcode and flag setting against expected architectural state.
   - Self-checking firmware programs run in simulation before FPGA bitstream generation.
4. **Automated Regression Suite**:
   - Executable via command line script (`python3 scripts/run_tests.py` / `make test`).
   - Every git commit must maintain a clean regression run without errors.

---

## 2. Test Plan Matrix

| Module | Testbench Path | Key Corner Cases to Verify | Status |
| :--- | :--- | :--- | :--- |
| **Register File** (`sv16_regfile`) | `simulation/unit/sv16_regfile_tb.sv` | Simultaneous read of same reg, write enable 0 vs 1, read-during-write | Pending Phase 3 |
| **ALU** (`sv16_alu`) | `simulation/unit/sv16_alu_tb.sv` | 0, `0xFFFF`, `0x7FFF`, signed overflow, carry, shift amounts (0, 1, 15, 16), DIV by 0 | Pending Phase 4 |
| **Status Register** (`sv16_status_reg`) | `simulation/unit/sv16_status_reg_tb.sv` | Flag update gating, bit positioning, clear/set | Pending Phase 5 |
| **Program Counter** (`sv16_pc`) | `simulation/unit/sv16_pc_tb.sv` | Reset to 0x0000, increment, target branch load, hold on stall | Pending Phase 6 |
| **Instruction Decoder** (`sv16_decoder`) | `simulation/unit/sv16_decoder_tb.sv` | All 16 primary opcodes, extended sub-opcodes, illegal opcodes | Pending Phase 7 |
| **Control Unit** (`sv16_control_unit`) | `simulation/unit/sv16_control_unit_tb.sv`| FSM transitions, bus wait-states, multi-cycle sequencing | Pending Phase 8 |
| **Minimal CPU Core** (`sv16_cpu`) | `simulation/regression/sv16_cpu_tb.sv` | Execute test program (`MOV`, `ADD`, `SUB`, `JMP`) | Pending Phase 9 |
| **Memory Bus Subsystem** | `simulation/regression/sv16_soc_tb.sv` | RAM read/write, memory-mapped peripheral read/write | Pending Phase 10 |
| **GPIO Controller** | `simulation/unit/sv16_gpio_tb.sv` | Pin direction, pin read, atomic SET/CLR | Pending Phase 13 |
| **Timer 0** | `simulation/unit/sv16_timer_tb.sv` | Prescaler clock division, compare match, auto-reload, interrupt | Pending Phase 14 |
| **PWM Controller 0** | `simulation/unit/sv16_pwm_tb.sv` | Frequency, 0% duty, 50% duty, 100% duty, emergency fault shutdown | Pending Phase 15 |
| **UART 0** | `simulation/unit/sv16_uart_tb.sv` | TX serial framing, RX framing, baud generator precision | Pending Phase 16 |
