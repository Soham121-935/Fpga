# SV-16 — Open Architectural Questions

Rev A recorded its open questions as `[PROVISIONAL]` choices so that
implementation could proceed. Rev B either **resolved** them in hardware or left
them explicitly open. This file is the current scoreboard; the items that are
still open are the ones with no decision recorded anywhere else in `docs/`.

---

## Status table

| ID | Question | Status | Resolution / where it lives now |
| :--- | :--- | :--- | :--- |
| OQ-01 | Instruction width and multi-word encoding | **RESOLVED** | 16-bit words; `LDI`/`JMP`/`CALL` are 2 words — [ISA.md](ISA.md) |
| OQ-02 | Endianness and alignment | **RESOLVED** | word-addressed internal bus; little-endian bytes for external devices and the image format |
| OQ-03 | Status register flag assignment | **RESOLVED** | Z=0, C=1, N=2, V=3, IE=7 — [CPU_ARCHITECTURE.md](CPU_ARCHITECTURE.md), ADR-004 |
| OQ-04 | Division by zero | **RESOLVED** | documented ALU behaviour (V flag, defined quotient) — [CPU_ARCHITECTURE.md](CPU_ARCHITECTURE.md) |
| OQ-05 | Multiply result width | **RESOLVED** | low 16 bits to the destination register; no `MULH` |
| OQ-06 | Stack direction | **RESOLVED** | full-descending, downward; reset SP `0x3FFE` (was `0x0FFE` when SRAM was 4 KB) |
| OQ-07 | Reset vector and stack pointer | **RESOLVED (changed in Rev B)** | reset enters the boot sequencer, not address 0: the monitor runs at `0xE000`, an application is entered at *its own* entry address and *its own* stack pointer, both taken from the flash image header. Interrupt vectors are a separate 8-entry table at `0x0020` — [MEMORY_MAP.md](MEMORY_MAP.md#4-where-code-data-and-the-stack-live) |
| OQ-08 | Harvard vs von Neumann | **RESOLVED** | single unified bus; no cache (single-cycle SRAM) — [BUS_ARCHITECTURE.md](BUS_ARCHITECTURE.md) |
| OQ-09 | Default master clock | **RESOLVED (changed again in Rev B)** | the full 25 MHz oscillator with `CLKDIV=1` (no fabric divider), now that the ALU divider is iterative and Fmax measures 44.70 MHz in the current tree; `CLKDIV=2` builds a 12.5 MHz fallback. Still no PLL — [ADR-018](ARCHITECTURE_DECISIONS.md), [SYNTHESIS_AND_DEPLOYMENT.md](SYNTHESIS_AND_DEPLOYMENT.md#timing) |
| OQ-10 | Peripheral bus protocol | **RESOLVED** | held request until ack, one-cycle registered ack, held grant, unmapped accesses acked with `0x0000` — [BUS_ARCHITECTURE.md](BUS_ARCHITECTURE.md) |
| OQ-13 | Watchdog in the reset path, and how it is disabled | **RESOLVED in Rev B (new)** | implemented as `sv16_wdt` at `0xF080`: a timeout restarts the boot sequence and sets `RSTCAUSE.WDT`; `CTRL` is keyed (`0x5A`), `FEED` needs `0x5A5A`, and `LOCK` freezes the period registers until the external reset pin clears the block. Option (a) *write-keyed disable* was rejected — an application that can only be *disabled* by a key can still be disabled by a wild pointer write — [ADR-017](ARCHITECTURE_DECISIONS.md), [PERIPHERALS.md](PERIPHERALS.md#watchdog-0xf080), [RESET_AND_CLOCK.md](RESET_AND_CLOCK.md) |

---

## Questions that are genuinely open in Rev B

| ID | Question | Why it matters | Options on the table |
| :--- | :--- | :--- | :--- |
| OQ-11 | **Should the RAM remap bit be implemented?** `SYS_CTRL[4]` (`RAMREMAP`) is defined and currently unused: the boot ROM stays at `0xE000` while applications are linked at `0x0000`, which is why images must be assembled for address 0 | A remap that puts SRAM at 0 with the ROM at the top would allow position-independent images and a second image slot; without it every image is tied to address 0 | (a) leave as documentation-only, (b) implement RAM-at-0 + ROM-at-top like an MCU's flash alias, (c) support both via the existing bit and a build-time default |
| OQ-12 | **Where do interrupt vectors belong?** Currently `0x0020` in SRAM, inside the application image | An application that forgets to populate them traps into arbitrary code; a ROM-side table would be safer but less flexible | (a) keep them in the image and document loudly, (b) put a default table in the boot ROM that jumps to a software dispatcher, (c) add a vector-table base register |
| OQ-14 | **Image slots: A/B with rollback, or single slot?** | A power failure during `C` currently destroys the only image (recovery is the monitor, but the application is gone) | **RESOLVED (ADR-019)**: option (b) — two slots 32 KB apart, a bit-monotonic 2-byte record in the image header, a trial period whose state is in flash, and rollback by the loader on the next restart. (c), a log-structured update, was rejected as more machinery than a 32 KB part needs; the rollback depth is one generation |
| OQ-15 | Interrupt latency budget | **RESOLVED (ADR-023, P8)** | measured over a 24-point arrival sweep: **11–31 cycles** request → handler, of which the IRQ controller contributes 1 and the entry sequence 6; the worst case is 31 because `DIV` (22 cycles) cannot be abandoned mid-flight. `irq_latency_tb` now enforces both bounds, so a regression that lengthens the path fails the suite |
| OQ-16 | **Is a C toolchain in scope?** | The ISA has 8 registers and no register-indirect jumps; a C compiler would need a software stack for pointers | (a) stay assembler-only and say so, (b) extend the ISA (add `JMP [Rn]`, more registers) to make C practical, (c) write a restricted C compiler for the existing ISA |
| OQ-17 | **Do we need more than one UART / a DMA path for programming?** | The per-byte ack upload is ~5 KB/s of payload; a large image takes minutes | (a) accept it, (b) add a binary/XMODEM mode that buffers a page without per-byte acks, (c) add DMA from the flash controller to SRAM |
| OQ-20 | **Does this design configure and run on a real LFE5U-12F bin?** The build flow now enforces the datasheet's 12F budget ([ADR-025](ARCHITECTURE_DECISIONS.md#adr-025-the-resource-budget-is-the-datasheets-not-the-toolchains)), but the *placement* was chosen by nextpnr against a device model that is the 25F die (identical tilegrid, only the idcode differs), so nothing in this repository can confirm that the placed cells all lie inside the resources a 12F guarantees | The failure mode is a bitstream that programs (right idcode, right frames) and behaves differently from simulation, which would be misdiagnosed as a logic bug | (a) configure a real 12F and run the bring-up checklist, (b) cross-check the mapping against Lattice Diamond's utilisation for the same netlist, (c) keep the design under ~50 % of the datasheet budget as a safety margin |
| OQ-19 | **How are the PLL's feedback wiring and loop-filter trims validated?** The `EHXPLLL` configuration bits (feedback tap, `ICP_CURRENT`, `LPF_RESISTOR`) are now the ones prjtrellis' `ecppll` generates ([ADR-024](ARCHITECTURE_DECISIONS.md#adr-024-the-pll-feedback-path--clkfb-driven-by-the-clkop-net-not-clkintfb)), but nothing in this repository can prove that the loop locks at 37.5 MHz on silicon: simulation substitutes a behavioural oscillator and nextpnr derives the output frequency from a parameter string | An unlocked or mis-trimmed PLL holds the whole SoC in reset (`sv16_startup` waits on `locked`), so the failure mode is "no console at all", not "wrong baud rate" | (a) scope `CLKOP` and the `LOCK` pin on a board and record the lock time, (b) widen the loop-filter trims if lock is marginal, (c) ship oscillator-only until a PLL build has been measured |
| OQ-18 | **Pin assignment for a real board** | The Rev B LPF was derived from the device database, not from a Rev A schematic; only the UART pins were kept | (a) re-derive from the Rev A board netlist, (b) design a Rev B carrier, (c) keep the current map and treat it as the reference design |

The gap list toward a production-grade part (JTAG debug, memory
protection, C toolchain, silicon bring-up) is summarized in
[MCU_READINESS.md](MCU_READINESS.md).
