# SV-16 Rev A — Instruction Set Architecture (ISA Rev A)

Status: **FROZEN PROVISIONAL FOR PHASE 1 REVIEW**

---

## 1. Instruction Formats

SV-16 uses 16-bit baseline instruction words. Certain instructions (e.g. 16-bit immediate loads, absolute long jumps) use an optional second 16-bit immediate word.

### Format R (Register-Register Operations)
```text
15    12 11   9 8    6 5    3 2    0
┌───────┬──────┬──────┬──────┬──────┐
│ Opcode│  Rd  │ Rs1  │ Rs2  │ SubOp│
└───────┴──────┴──────┴──────┴──────┘
  4-bit  3-bit  3-bit  3-bit  3-bit
```
- Used for 3-operand or 2-operand ALU operations (`Rd <= Rs1 OP Rs2`).

### Format I (Register-Immediate Operations)
```text
15    12 11   9 8                  0
┌───────┬──────┬────────────────────┐
│ Opcode│  Rd  │    Immediate (9-bit signed)
└───────┴──────┴────────────────────┘
  4-bit  3-bit         9-bit
```
- Used for short immediate addition, subtraction, and comparison (`-256` to `+255`).

### Format M (Memory Load / Store)
```text
15    12 11   9 8    6 5            0
┌───────┬──────┬──────┬─────────────┐
│ Opcode│  Rd  │  Rb  │ Offset (6b) │
└───────┴──────┴──────┴─────────────┘
  4-bit  3-bit  3-bit     6-bit
```
- Address calculation: `Effective Address = Rb + sign_extend(Offset)`.
- If `Rb == 000`, offset acts as small direct address or base `R0`.

### Format B (Branch / Jump)
```text
15    12 11   8 7                  0
┌───────┬──────┬────────────────────┐
│ Opcode│ Cond │    Offset (8-bit signed)
└───────┴──────┴────────────────────┘
  4-bit  4-bit         8-bit
```
- Branch condition evaluates flags in Status Register (`SR`).
- Target: `PC <= PC + sign_extend(Offset)`.

### Format S (Special / Stack / Control)
```text
15    12 11   9 8                  0
┌───────┬──────┬────────────────────┐
│ Opcode│  Rx  │      Sub-Opcode    │
└───────┴──────┴────────────────────┘
  4-bit  3-bit         9-bit
```
- Used for `PUSH Rx`, `POP Rx`, `CALL`, `RET`, `NOP`, `HALT`, `RETI`.

---

## 2. Register Encodings

| Register Name | Register Code (`Rd` / `Rs` / `Rb`) | Description |
| :--- | :--- | :--- |
| `R0` | `3'b000` | General Purpose Register 0 |
| `R1` | `3'b001` | General Purpose Register 1 |
| `R2` | `3'b010` | General Purpose Register 2 |
| `R3` | `3'b011` | General Purpose Register 3 |
| `R4` | `3'b100` | General Purpose Register 4 |
| `R5` | `3'b101` | General Purpose Register 5 |
| `R6` | `3'b110` | General Purpose Register 6 |
| `R7` | `3'b111` | General Purpose Register 7 |

---

## 3. Opcode Assignment Table

| Opcode [15:12] | Mnemonic | Format | Description | Flag Effects |
| :--- | :--- | :--- | :--- | :--- |
| `0000` (`0x0`) | `NOP` / `CTRL` | S | System Control (`NOP`, `HALT`, `EI`, `DI`, `RETI`) | None |
| `0001` (`0x1`) | `ALU_RR` | R | Register-Register ALU operations (SubOp in [2:0]) | Z, C, N, V |
| `0010` (`0x2`) | `ADDI` | I | Add Immediate: `Rd <= Rd + sign_ext(imm9)` | Z, C, N, V |
| `0011` (`0x3`) | `SUBI` | I | Subtract Immediate: `Rd <= Rd - sign_ext(imm9)` | Z, C, N, V |
| `0010` (`0x4`) | `LDI` | S (2-word) | Load 16-bit Immediate: `Rd <= imm16` (word 2) | Z, N |
| `0101` (`0x5`) | `LOAD` | M | Memory Load: `Rd <= MEM[Rb + offset]` | Z, N |
| `0110` (`0x6`) | `STORE`| M | Memory Store: `MEM[Rb + offset] <= Rd` | None |
| `0111` (`0x7`) | `MOV` | R | Register Copy: `Rd <= Rs1` | Z, N |
| `1000` (`0x8`) | `BRANCH`| B | Conditional Branch relative to PC | None |
| `1001` (`0x9`) | `JMP` | S (2-word) | Unconditional Jump absolute: `PC <= imm16` | None |
| `1010` (`0xA`) | `CALL` | S (2-word) | Call Subroutine: `PUSH PC; PC <= imm16` | None |
| `1011` (`0xB`) | `RET` | S | Return from Subroutine: `POP PC` | None |
| `1100` (`0xC`) | `PUSH` | S | Push register to stack: `PUSH Rx` | None |
| `1101` (`0xD`) | `POP` | S | Pop register from stack: `POP Rx` | Z, N |
| `1110` (`0xE`) | `CMP` | R | Compare: compute `Rs1 - Rs2`, discard result | Z, C, N, V |
| `1111` (`0xF`) | `EXT_ALU` | R | Extended ALU (MUL, DIV, Shifts) | Z, C, N, V |

---

## 4. Sub-Opcode Mappings for ALU Operations

### Primary ALU SubOpcodes (`Opcode = 0x1`, Format R, bits [2:0]):
- `3'b000`: `ADD  Rd, Rs1, Rs2` — `Rd <= Rs1 + Rs2`
- `3'b001`: `SUB  Rd, Rs1, Rs2` — `Rd <= Rs1 - Rs2`
- `3'b010`: `AND  Rd, Rs1, Rs2` — `Rd <= Rs1 & Rs2`
- `3'b011`: `OR   Rd, Rs1, Rs2` — `Rd <= Rs1 | Rs2`
- `3'b100`: `XOR  Rd, Rs1, Rs2` — `Rd <= Rs1 ^ Rs2`
- `3'b101`: `NOT  Rd, Rs1`      — `Rd <= ~Rs1`
- `3'b110`: `INC  Rd, Rs1`      — `Rd <= Rs1 + 1`
- `3'b111`: `DEC  Rd, Rs1`      — `Rd <= Rs1 - 1`

### Extended ALU SubOpcodes (`Opcode = 0xF`, Format R, bits [2:0]):
- `3'b000`: `SHL  Rd, Rs1, Rs2` (or imm in `Rs2` field) — Logical Shift Left
- `3'b001`: `SHR  Rd, Rs1, Rs2` (or imm in `Rs2` field) — Logical Shift Right
- `3'b010`: `MUL  Rd, Rs1, Rs2` — Unsigned 16-bit Multiply (`Rd <= (Rs1 * Rs2)[15:0]`)
- `3'b011`: `DIV  Rd, Rs1, Rs2` — Unsigned 16-bit Division (`Rd <= Rs1 / Rs2`)
- `3'b100`: `MOD  Rd, Rs1, Rs2` — Unsigned 16-bit Modulo (`Rd <= Rs1 % Rs2`)
- `3'b101` to `3'b111`: Reserved for future arithmetic expansion

---

## 5. Branch Condition Codes (Format B, `Cond` field bits [11:8])

| Cond [11:8] | Mnemonic | Condition Name | Test in Status Register |
| :--- | :--- | :--- | :--- |
| `4'b0000` | `BRA` | Always / Unconditional | Always true (`1`) |
| `4'b0001` | `BEQ` | Equal / Zero | `Z == 1` |
| `4'b0010` | `BNE` | Not Equal / Non-Zero | `Z == 0` |
| `4'b0011` | `BC` / `BLO` | Carry Set / Below (Unsigned <) | `C == 1` |
| `4'b0100` | `BNC` / `BHS`| Carry Clear / Higher or Same (Unsigned >=) | `C == 0` |
| `4'b0101` | `BN` / `BMI` | Negative / Minus | `N == 1` |
| `4'b0110` | `BP` / `BPL` | Positive / Plus | `N == 0` |
| `4'b0111` | `BVS` | Overflow Set | `V == 1` |
| `4'b1000` | `BVC` | Overflow Clear | `V == 0` |
| `4'b1001` | `BLT` | Less Than (Signed <) | `(N ^ V) == 1` |
| `4'b1010` | `BGE` | Greater or Equal (Signed >=) | `(N ^ V) == 0` |
| `4'b1011` | `BLE` | Less or Equal (Signed <=) | `(Z \| (N ^ V)) == 1` |
| `4'b1100` | `BGT` | Greater Than (Signed >) | `(Z \| (N ^ V)) == 0` |
| `4'b1101`–`4'b1111` | Reserved | Reserved for future condition codes | Always false (`0`) |

---

## 6. Illegal Instruction & Reserved Opcode Handling

Any undefined opcode or sub-opcode (such as reserved condition codes or reserved ALU operations) will:
1. Trigger an illegal instruction exception (if interrupt vector initialized), OR
2. Treat the instruction as a `NOP` without modifying architectural registers or flags, asserting an `illegal_instr` debug flag on the CPU core interface.

---

## 7. Rev B notes (the ISA itself is unchanged)

Rev B did **not** change the ISA: the encodings in sections 1-6 are exactly what
Rev A defined, and every application written for Rev A executes unchanged. What
changed around it is how a program gets *started* and how it talks to the new
hardware:

* **Execution entry.** At power-up the CPU is released by the boot sequencer
  (`rtl/sv16_startup.sv`), not by a hard-wired reset vector. It enters either the
  boot ROM monitor at `0xE000`, or the application's own `entry` address (with the
  application's own `SP`, taken from the flash image header). Programs are
  therefore assembled for the address they will run at — `make app` links at
  `0x0000` because the loader copies payloads to SRAM address 0.
* **Interrupts.** The vector table is 8 words at `0x0020-0x0027`, one 16-bit
  handler address per source ([MEMORY_MAP.md](MEMORY_MAP.md#interrupt-vector-indices)).
  The CPU still pushes `SR` and `PC` before the vector fetch and `RETI` restores
  them; enabling an interrupt now also requires the per-source bit in `IRQ_EN`
  (`0xF090`) and the global bit `SYS_CTRL.IRQEN` (`0xF001`).
* **Trap.** An illegal opcode takes vector 7 and, in addition, latches the
  offending address in `SYS_FAULT_ADDR` and increments `SYS_FAULT_CNT` so a
  monitor or the application itself can diagnose the fault.
* **Memory map.** SRAM is 16 K words at `0x0000`, the boot ROM is at `0xE000`,
  peripherals are at `0xF000-0xF0FF`; see [MEMORY_MAP.md](MEMORY_MAP.md). Rev A's
  map (8 K words of SRAM, four peripherals) is superseded.
* **DIV and MOD are multi-cycle.** The ISA is unchanged — same encodings, same
  results, same flags (including divide-by-zero: `V=1`, quotient `0xFFFF`,
  remainder `0x0000`) — but the ALU serves them with one iterative restoring
  divider instead of a combinational one, so they now take **18 cycles** rather
  than 1 (ADR-018). Every other operation, including `MUL`, is still executed in
  the single `S_EXECUTE` cycle. Firmware that counts cycles around a division
  must allow for the extra 17; nothing else changes.
* **No new instructions.** In particular there is still **no register-indirect
  jump or call**: `JMP` and `CALL` take a 16-bit immediate, and returns use `RET`
  through the stack. That is enough for handlers (the CPU fetches the handler
  address from the vector table itself) and for the monitor's dispatcher
  (compare-and-branch trampolines), but it is the main obstacle to a C compiler —
  a function-pointer call has no encoding. Adding one is an ISA extension that
  would need its own ADR ([OPEN_QUESTIONS.md](OPEN_QUESTIONS.md), OQ-16).
