# SV-16 Rev A — Architecture Decisions Record (ADR)

This file tracks foundational architectural decisions made for the SV-16 Rev A microcontroller.

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
