# SV-16 Rev A — Open Architectural Questions

This document records all architectural questions, ambiguities, and design choices requiring resolution before finalizing the hardware implementation.

Per **Rule 1 (Do not invent architecture)**:
- No architectural assumption may be treated as permanent unless formally resolved.
- Where a provisional choice is made to allow incremental progress, it is explicitly marked as `[PROVISIONAL]`.
- If a decision affects compatibility between hardware and firmware, dependent implementation must halt until resolved.

---

## Open Decisions Tracking Table

| ID | Title | Impact Area | Status | Provisional Choice | Target Resolution |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **OQ-01** | Instruction Word Width & Multi-word Encoding | ISA / Decoder / PC | **PROVISIONAL** | Fixed 16-bit instructions for ALU/branch; 2-word (32-bit) for 16-bit immediate load / direct jump | Freeze in Phase 1 |
| **OQ-02** | Endianness & Memory Alignment | System Bus / Memory | **PROVISIONAL** | 16-bit word-addressed memory internally; little-endian byte ordering for external 8-bit bus/UART | Freeze in Phase 1 |
| **OQ-03** | Status Register Flag Bit Assignment | ALU / CPU / Status Reg | **PROVISIONAL** | Bit 0: Z (Zero), Bit 1: C (Carry), Bit 2: N (Negative), Bit 3: V (Overflow), Bits 4-7: Reserved | Freeze in Phase 1 |
| **OQ-04** | Division-by-Zero Handling | ALU / CPU / Interrupt | **PROVISIONAL** | Set V flag, return quotient 0xFFFF, remainder unchanged; optional fault trap in future | Freeze in Phase 1 |
| **OQ-05** | Multiplication Result Bit-Width | ALU / Reg File | **PROVISIONAL** | Single 16-bit register destination receives lower 16 bits; optional high-word stored in dedicated MAC/high reg or separate instruction (`MULH`) | Freeze in Phase 1 |
| **OQ-06** | Stack Growth Direction & Addressing | CPU / SP / Bus | **PROVISIONAL** | Downward growing (full-descending: SP decrements before push, increments after pop) | Freeze in Phase 1 |
| **OQ-07** | Reset Vector Address & Stack Pointer Initial Value | CPU / Reset FSM | **PROVISIONAL** | Reset PC = `0x0000`; Initial SP = `0x0FFE` (top of internal 4KB BRAM) | Freeze in Phase 1 |
| **OQ-08** | Memory Architecture: Harvard vs Von Neumann | Bus / Cache / Memory | **PROVISIONAL** | Unified Von Neumann memory-mapped space on single synchronous bus with multi-cycle arbiter | Freeze in Phase 1 |
| **OQ-09** | Default Master Clock Frequency on Lattice ECP5 | Clock / Constraints | **PROVISIONAL** | 25.0 MHz baseline operating clock generated from onboard oscillator (via internal PLL or direct) | Freeze in Phase 2 |
| **OQ-10** | Peripheral Bus Protocol | System Bus / Peripherals | **PROVISIONAL** | Synchronous wishbone-like strobe/ack or simple valid/ready 16-bit bus | Freeze in Phase 1 |

---

## Detailed Question Breakdowns

### OQ-01: Instruction Word Width & Multi-word Encoding
- **Issue**: SV-16 is a 16-bit architecture. An instruction must specify opcode, source registers, destination register, and potentially immediate values. In 16 bits, encoding `OP (4 bits) + Rd (3 bits) + Rs1 (3 bits) + Rs2 (3 bits)` leaves 3 bits. However, a 16-bit constant (`MOV R0, #0x1234`) cannot fit into a single 16-bit instruction.
- **Provisional Recommendation**:
  - Class 1: Single-word 16-bit instructions (register-register ALU, short branches, single register operations).
  - Class 2: Two-word 32-bit instructions (immediate loads with 16-bit constants, absolute long jumps, direct memory load/store). The instruction fetch FSM fetches the second 16-bit word in the subsequent cycle.

### OQ-02: Endianness & Memory Alignment
- **Issue**: Does memory address 16-bit words (word-addressed `0x0000` to `0xFFFF` = 64k 16-bit words) or 8-bit bytes (byte-addressed `0x0000` to `0xFFFF` = 64k bytes = 32k words)?
- **Provisional Recommendation**: Word-addressed internally (`addr[15:0]` accesses a 16-bit data word directly) avoids unaligned access complexity in Rev A. If byte addressing is adopted, unaligned access must be strictly defined (e.g. traps or ignored LSB). Word addressing simplifies BRAM and peripheral address decoders significantly for Rev A.

### OQ-03: Status Register Bit Assignment
- **Issue**: Standardizing bit positions of `Z`, `C`, `N`, `V` in `SR`.
- **Provisional Recommendation**:
  - `SR[0]`: `Z` (Zero)
  - `SR[1]`: `C` (Carry / Unsigned overflow)
  - `SR[2]`: `N` (Negative / Sign bit)
  - `SR[3]`: `V` (Overflow / Signed overflow)
  - `SR[7:4]`: Interrupt enable / status flags (`IE` = bit 7)
  - `SR[15:8]`: Reserved (read as 0)

### OQ-04: Division by Zero Behavior
- **Issue**: Required behavior when `DIV Rd, Rs` is executed with `Rs == 0`.
- **Provisional Recommendation**:
  - Zero flag `Z = 0`, Carry `C = 0`, Negative `N = 0`, Overflow `V = 1`.
  - Quotient in destination register becomes `0xFFFF` (or saturated value `0x0000`).
  - No hardware lockup; CPU continues executing next instruction.

### OQ-05: 16-bit Multiplier Width
- **Issue**: 16-bit × 16-bit produces a 32-bit result.
- **Provisional Recommendation**:
  - Standard `MUL Rd, Rs` stores lower 16 bits in `Rd` (sufficient for most motor PWM and control loop calculations).
  - Dedicated `MULH Rd, Rs` (or a high register) can capture the upper 16 bits if needed.
  - Lattice ECP5 contains 18×18 sysDSP slices which execute 16×16 single-cycle multiplication trivially in hardware.

### OQ-06: Stack Pointer Semantics
- **Issue**: Push/pop ordering, pre-decrement vs post-decrement.
- **Provisional Recommendation**: Full descending stack:
  - `PUSH Rs`: `SP <= SP - 1`; `MEM[SP] <= Rs`
  - `POP Rd`: `Rd <= MEM[SP]`; `SP <= SP + 1`
  - Stack top is valid data.

### OQ-07: Reset Vector & Memory Bounds
- **Issue**: Power-up entry point and BRAM allocation.
- **Provisional Recommendation**:
  - Power-up PC = `0x0000` (Vector 0: Reset Handler).
  - Vector 1: `0x0001` (Timer Interrupt).
  - Vector 2: `0x0002` (UART Interrupt).
  - Vector 3: `0x0003` (External/GPIO Interrupt).
  - Initial `SP` loaded to `0x0FFE` by reset or startup code.
