#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# SV-16 — build and run one Verilator testbench.
#
#   source scripts/sv16_venv.sh            # toolchain (once per shell)
#   scripts/sv16_run_tb.sh simulation/regression/monitor_tb.sv monitor_tb
#
# The first argument is the testbench file, the second the top module name
# (default: the file's base name).  Every file in rtl/ is compiled in, plus any
# extra sources listed after the top module name, plus the SPI flash model when
# the testbench needs a flash part.  Binaries land in build/vlt/<name>/ and the
# testbench is run from the repository root, which is where the testbenches
# expect build/rom and build/fw to be.
# ---------------------------------------------------------------------------
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

tb_file="${1:?usage: sv16_run_tb.sh <testbench.sv> [top_module] [extra sources...]}"
shift
top="${1:-$(basename "$tb_file" .sv)}"
[ $# -gt 0 ] && shift
extras=("$@")

if ! command -v verilator-cli >/dev/null 2>&1; then
    echo "verilator-cli not found - run: source scripts/sv16_venv.sh" >&2
    exit 1
fi

# every RTL file except the SoC top, with the top last (it defines the package
# for the rest of the design and declares `SV16_ROM_INIT_FILE`)
mapfile -t rtl_files < <(ls rtl/*.sv | grep -v 'sv16_top\.sv$')

if [ ${#extras[@]} -eq 0 ] && grep -q 'sv16_flash_model' "$tb_file"; then
    extras+=(simulation/unit/sv16_flash_model.sv)
fi

out="build/vlt/$top"
mkdir -p "$out"

verilator-cli --binary -Wno-fatal -Wno-WIDTHEXPAND -Wno-UNUSEDSIGNAL \
    -Wno-UNUSEDPARAM -Wno-IMPORTSTAR -Wno-CASEINCOMPLETE \
    --Mdir "$out" -Irtl "${rtl_files[@]}" rtl/sv16_top.sv \
    "${extras[@]}" "$tb_file" --top-module "$top" -o "$top" >/dev/null

make -C "$out" -f "V$top.mk" -j 4 >/dev/null
exec "./$out/$top"
