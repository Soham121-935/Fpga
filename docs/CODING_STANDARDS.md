# SV-16 Rev A — HDL Coding Standards & Infrastructure

---

## 1. HDL Language Standard

- **Language**: SystemVerilog (IEEE 1800-2012 synthesizable subset).
- **Target Synthesizers**: Lattice Diamond (Synplify Pro / Lattice Synthesis Engine) and open-source Yosys.
- **File Extensions**:
  - Synthesizable RTL: `.sv`
  - Testbenches / Verification: `_tb.sv` or `.sv`
  - Packages and Header includes: `.svh` or `.sv`

---

## 2. Naming Conventions

- **Modules**: Snake case prefixed with `sv16_` (e.g., `sv16_regfile`, `sv16_alu`, `sv16_core`, `sv16_soc_top`).
- **Source Files**: Must exactly match module name: `rtl/<module_name>.sv`.
- **Testbench Files**: `simulation/unit/<module_name>_tb.sv` or `simulation/regression/<system_name>_tb.sv`.
- **Signals**:
  - Synchronous clock: `clk`
  - System reset (active-low): `rst_n`
  - Write enable: `<name>_wen` or `we`
  - Data inputs: `<name>_data_in` or `<name>_i`
  - Data outputs: `<name>_data_out` or `<name>_o`
  - Active-low signals: suffix `_n`
  - Constants / Parameters: UPPER_CASE with underscores (e.g., `DATA_WIDTH`, `REG_COUNT`)

---

## 3. Clock and Reset Rules

1. **Clocking**:
   - Single synchronous clock domain for CPU core logic (`clk`).
   - All sequential logic must be triggered on `posedge clk`.
   - Never use falling-edge triggered flip-flops for core logic.
   - Gated clocks inside RTL are strictly forbidden. Use clock enables instead.
2. **Reset**:
   - Asynchronous assertion, synchronous de-assertion reset network (`rst_n`).
   - Every register must have a deterministic reset state.
   - Sequential block template:
     ```systemverilog
     always_ff @(posedge clk or negedge rst_n) begin
         if (!rst_n) begin
             // Reset register contents to known initial values
         end else begin
             // Synchronous state updates
         end
     end
     ```

---

## 4. Combinational Logic Rules

1. Always use `always_comb` for combinational processes (enforces complete assignments and prevents accidental latches).
2. Avoid latches: Ensure every `case` statement has a `default` branch and all conditional branches (`if`/`else`) assign all outputs.
3. Use blocking assignments (`=`) exclusively in `always_comb`.
4. Use non-blocking assignments (`<=`) exclusively in `always_ff`.

---

## 5. Parameterization

All bit widths, memory depths, and addresses must be parameterized or defined in `sv16_pkg.sv` rather than using magic numbers.
