# SV-16 Rev A — CPU Architecture Specification

---

## 1. Overview

SV-16 Rev A is a 16-bit register-oriented microprocessor designed for low-latency embedded control, timing, and motor peripheral actuation.

### Architectural Parameters
- **Data Bus Width**: 16 bits
- **Address Bus Width**: 16 bits (addressing up to 64K words)
- **General Purpose Registers**: 8 registers (`R0`–`R7`), 16 bits each
- **Dedicated Architectural Registers**:
  - `PC`: Program Counter (16-bit)
  - `IR`: Instruction Register (16-bit)
  - `SR`: Status Register (16-bit)
  - `SP`: Stack Pointer (16-bit)

---

## 2. Register Organization

### General Purpose Registers (GPR)

```text
 15                                                             0
┌────────────────────────────────────────────────────────────────┐
│                              R0                                │
├────────────────────────────────────────────────────────────────┤
│                              R1                                │
├────────────────────────────────────────────────────────────────┤
│                              R2                                │
├────────────────────────────────────────────────────────────────┤
│                              R3                                │
├────────────────────────────────────────────────────────────────┤
│                              R4                                │
├────────────────────────────────────────────────────────────────┤
│                              R5                                │
├────────────────────────────────────────────────────────────────┤
│                              R6                                │
├────────────────────────────────────────────────────────────────┤
│                              R7 (Frame/Temp or Scratch)        │
└────────────────────────────────────────────────────────────────┘
```

All 8 registers are general read/write registers.

### Special Registers

1. **Program Counter (`PC`)**:
   - Points to the current instruction address.
   - Power-on reset value: `0x0000`.
   - Increments by `1` per instruction word fetched (in word-addressed mode).
   - Updated on `JMP`, `CALL`, `RET`, conditional branch (`Bxx`), and interrupt entry/return.

2. **Instruction Register (`IR`)**:
   - Holds the current 16-bit instruction word during decode and execution.
   - For 2-word instructions, a secondary temporary register (`IMM_REG`) holds the immediate 16-bit data word.

3. **Status Register (`SR`)**:
   - Holds processor flags and CPU status bits:
     - `Bit 0 [Z]`: Zero flag. Set if ALU result == `0x0000`.
     - `Bit 1 [C]`: Carry / Borrow flag. Set on unsigned addition overflow or subtraction borrow.
     - `Bit 2 [N]`: Negative / Sign flag. Set if MSB of result (bit 15) == `1`.
     - `Bit 3 [V]`: Signed Overflow flag. Set if signed addition/subtraction wraps.
     - `Bit 7 [IE]`: Global Interrupt Enable.
     - `Bits [6:4], [15:8]`: Reserved (always read as 0).
   - Power-on reset value: `0x0000`.

4. **Stack Pointer (`SP`)**:
   - Points to the top of the system call/data stack in memory.
   - Power-on reset default: `0x0FFE` (top of internal 4K-word RAM block).
   - Decremented on `PUSH` and `CALL`; incremented on `POP` and `RET`.

---

## 3. Execution Pipeline & Multi-Cycle Control Flow

SV-16 uses a deterministic synchronous multi-cycle finite state machine (FSM).

```text
                     ┌───────────┐
                     │   RESET   │
                     └─────┬─────┘
                           │
                           ▼
                    ┌─────────────┐
        ┌───────────►    FETCH    │
        │           └──────┬──────┘
        │                  │
        │                  ▼
        │           ┌─────────────┐
        │           │   DECODE    │
        │           └──────┬──────┘
        │                  │
        │                  ├────────────────────────┐ (If 2-word instruction)
        │                  │                        │
        │                  │                        ▼
        │                  │                 ┌─────────────┐
        │                  │                 │  FETCH_IMM  │
        │                  │                 └──────┬──────┘
        │                  │                        │
        │                  ▼                        │
        │           ┌─────────────┐                 │
        │           │   EXECUTE   │◄────────────────┘
        │           └──────┬──────┘
        │                  │
        │         ┌────────┴────────┐
        │         ▼                 ▼
        │  ┌─────────────┐   ┌─────────────┐
        │  │   MEMORY    │   │  WRITEBACK  │
        │  └──────┬──────┘   └──────┬──────┘
        │         │                 │
        │         ▼                 │
        │  ┌─────────────┐          │
        │  │  WRITEBACK  │          │
        │  └──────┬──────┘          │
        │         │                 │
        └─────────┴─────────────────┘
```

### State Descriptions

1. **`S_FETCH`**:
   - `bus_addr <= PC`
   - `bus_req <= 1`, `bus_we <= 0`
   - Next state: When `bus_ack == 1`, `IR <= bus_rdata`, `PC <= PC + 1`, transit to `S_DECODE`.

2. **`S_DECODE`**:
   - Decode opcode in `IR`.
   - Read `Rs1` and `Rs2` from Register File.
   - If instruction requires a 16-bit immediate word (`LDI`, `JMP_IMM`, etc.), transition to `S_FETCH_IMM`.
   - Otherwise, transition to `S_EXECUTE`.

3. **`S_FETCH_IMM`**:
   - `bus_addr <= PC`
   - `bus_req <= 1`, `bus_we <= 0`
   - When `bus_ack == 1`, latches immediate value into internal register, `PC <= PC + 1`, transitions to `S_EXECUTE`.

4. **`S_EXECUTE`**:
   - ALU performs arithmetic/logic operation.
   - For branch instructions: evaluate condition flags in `SR`. If condition met: `PC <= target_addr`.
   - For register-to-register instructions: transition to `S_WRITEBACK`.
   - For memory access (`LOAD`, `STORE`, `PUSH`, `POP`): transition to `S_MEMORY`.

5. **`S_MEMORY`**:
   - Perform bus read or write:
     - `LOAD`: `bus_addr <= effective_addr`, `bus_req <= 1`, `bus_we <= 0`.
     - `STORE`: `bus_addr <= effective_addr`, `bus_wdata <= Rs`, `bus_req <= 1`, `bus_we <= 1`.
     - `PUSH`: `SP <= SP - 1`, `bus_addr <= SP - 1`, `bus_wdata <= Rs`, `bus_we <= 1`.
     - `POP`: `bus_addr <= SP`, `SP <= SP + 1`, `bus_we <= 0`.
   - On completion (`bus_ack == 1`):
     - If load/pop: transition to `S_WRITEBACK`.
     - If store/push: transition to `S_FETCH` for next instruction.

6. **`S_WRITEBACK`**:
   - Write computed ALU result or loaded memory data to `Rd` in Register File (`wen = 1`).
   - Latch updated ALU flags into `SR`.
   - Transition to `S_FETCH`.

---

## 4. Subroutines and Call/Return

- **`CALL <target>`**:
  - Pushes current `PC` (return address) onto stack (`SP <= SP - 1; MEM[SP] <= PC`).
  - Sets `PC <= target`.
- **`RET`**:
  - Pops return address from stack (`PC <= MEM[SP]; SP <= SP + 1`).

---

## 5. ALU Specification

The ALU is a 16-bit combinational/registered datapath component with operations:
1. `ADD`: Signed/unsigned 16-bit addition ($A + B$)
2. `SUB`: Signed/unsigned 16-bit subtraction ($A - B$)
3. `AND`: Bitwise AND ($A \ \& \ B$)
4. `OR`:  Bitwise OR ($A \ | \ B$)
5. `XOR`: Bitwise XOR ($A \ \text{^} \ B$)
6. `NOT`: Bitwise NOT ($\sim A$)
7. `SHL`: Logical shift left ($A \ll \text{imm/B}$)
8. `SHR`: Logical shift right ($A \gg \text{imm/B}$)
9. `INC`: Increment ($A + 1$)
10. `DEC`: Decrement ($A - 1$)
11. `MUL`: 16-bit integer multiplication ($A \times B$)
12. `DIV`: 16-bit unsigned integer division ($A / B$)

### Flag Calculation Rules
- **Zero Flag (`Z`)**: Set if `result == 16'h0000`.
- **Negative Flag (`N`)**: Set if `result[15] == 1'b1`.
- **Carry Flag (`C`)**:
  - Addition / INC: Set if carry out of bit 15 ($A + B > 65535$).
  - Subtraction / DEC: Set if borrow occurs ($A < B$).
  - Shifts: Set to the last bit shifted out.
- **Overflow Flag (`V`)**:
  - Signed addition: Set if $(A[15] == B[15]) \ \& \ (result[15] \ne A[15])$.
  - Signed subtraction: Set if $(A[15] \ne B[15]) \ \& \ (result[15] \ne A[15])$.
  - Division by zero: Set if divisor == 0.
