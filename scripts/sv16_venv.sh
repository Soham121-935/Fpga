#!/usr/bin/env bash
# SV-16 — set up a self-contained Verilator toolchain for this checkout.
#
# The simulation flow needs a Verilator binary. This script installs the
# `verilator` PyPI wheel (which ships the full Verilator 5.x compiler plus a
# `verilator-cli` driver) into a private virtual environment, and installs a
# tiny `c++` wrapper that the wheel's build system needs.
#
# Usage:   source scripts/sv16_venv.sh      # from the repository root
#          make sim                        # afterwards
#
# Nothing outside the repository (or $SV16_VENV, if set) is touched.

SV16_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SV16_VENV="${SV16_VENV:-/tmp/sv16-venv}"
SV16_WRAP="${SV16_WRAP:-/tmp/sv16-ccwrap}"

if [ ! -x "$SV16_VENV/bin/verilator-cli" ] || \
   [ ! -x "$SV16_VENV/bin/yowasp-yosys" ] || \
   [ ! -x "$SV16_VENV/bin/yowasp-nextpnr-ecp5" ]; then
    echo "[sv16] creating the tool virtual environment in $SV16_VENV"
    python3 -m venv "$SV16_VENV" || return 1
    "$SV16_VENV/bin/pip" install --quiet --upgrade pip || return 1
    # Verilator for simulation ...
    "$SV16_VENV/bin/pip" install --quiet verilator || return 1
    # ... and the open-source FPGA flow for the bitstream (YoWASP builds of
    # Yosys / nextpnr-ecp5 / ecppack, which run without a system install).
    "$SV16_VENV/bin/pip" install --quiet yowasp-yosys yowasp-nextpnr-ecp5 || return 1
fi

# The wheel passes bare precompiled-header filenames to c++, which c++ rejects;
# the wrapper drops them.
mkdir -p "$SV16_WRAP"
cat > "$SV16_WRAP/c++" <<'WRAP'
#!/bin/bash
args=()
for a in "$@"; do
  case "$a" in
    *__pch.h.fast|*__pch.h.slow) ;;
    *) args+=("$a") ;;
  esac
done
exec /usr/bin/g++ "${args[@]}"
WRAP
chmod +x "$SV16_WRAP/c++"
ln -sf "$SV16_WRAP/c++" "$SV16_WRAP/g++"

# The YoWASP tools spell themselves yowasp-*; give the Makefile the names it
# expects so `make bitstream` works in this environment too.
ln -sf "$SV16_VENV/bin/yowasp-yosys"         "$SV16_WRAP/yosys"
ln -sf "$SV16_VENV/bin/yowasp-nextpnr-ecp5"  "$SV16_WRAP/nextpnr-ecp5"
ln -sf "$SV16_VENV/bin/yowasp-ecppack"       "$SV16_WRAP/ecppack"

export PATH="$SV16_WRAP:$SV16_VENV/bin:$PATH"
export CXXFLAGS="--std=c++20 -fcoroutines"

echo "[sv16] Verilator ready: $(verilator-cli --version | head -1)"
echo "[sv16] Yosys ready:     $(yosys --version 2>/dev/null | head -1)"
echo "[sv16] run 'make sim' for the testbenches, 'make bitstream' for the FPGA image"
