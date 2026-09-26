#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# SV-16 — bitstream flow: Yosys (synthesis) -> nextpnr-ecp5 (P&R) -> ecppack.
#
#   source scripts/sv16_venv.sh
#   scripts/sv16_synth.sh                 # full flow into build/
#   scripts/sv16_synth.sh --no-rom        # synthesize with an empty boot ROM
#   scripts/sv16_synth.sh --clkdiv 2      # build the 12.5 MHz conservatively-clocked SoC
#   scripts/sv16_synth.sh --freq 40       # different timing target
#   scripts/sv16_synth.sh --clksrc pll --pllmhz 37.5 # run from the on-chip PLL
#
# Defaults: --clkdiv 1 (SoC clock = the 25 MHz oscillator, Fmax measured 46.17 MHz
# after the ALU divider became multi-cycle, ADR-018), --clksrc osc, --freq =
# reference/clkdiv.  --clksrc pll instantiates the ECP5 PLL (ADR-021) and the
# reference pin stays constrained at 25 MHz; nextpnr derives the generated clock
# from the PLL configuration, so the reported Fmax is for the built frequency.
#
# The boot ROM contents are compiled into the bitstream: the ROM's init file is
# a synthesis-time macro (SV16_ROM_INIT_FILE), so the monitor that comes up on
# a fresh device is exactly build/rom/monitor.hex.  `make firmware` builds it;
# this script refuses to run without it unless --no-rom is given.
#
# Outputs (in --out, default build/):
#   sv16_top.json     synthesized netlist (Yosys)
#   sv16_top.config   placed and routed configuration (nextpnr-ecp5, Trellis)
#   sv16_top.bit      bitstream for the device (ecppack --compress)
#   sv16_top.timing.json  timing/utilization report (nextpnr-ecp5 --report)
#   sv16_synth.ys     the Yosys script that was run (kept for reproducibility)
# ---------------------------------------------------------------------------
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

out="build"
rom="build/rom/monitor.hex"
lpf="constraints/ecp5_144tqfp.lpf"
freq=""
device="--12k"
package="TQFP144"
speed="6"
top="sv16_top"
unconstrained=""
yosys_only=""
clkdiv="1"
clksrc="osc"
pllmhz="40"

while [ $# -gt 0 ]; do
    case "$1" in
        --out)     out="$2"; shift 2 ;;
        --rom)     rom="$2"; shift 2 ;;
        --lpf)     lpf="$2"; shift 2 ;;
        --freq)    freq="$2"; shift 2 ;;
        --clkdiv)  clkdiv="$2"; shift 2 ;;
        --clksrc)  clksrc="$2"; shift 2 ;;
        --pllmhz)  pllmhz="$2"; shift 2 ;;
        --speed)   speed="$2"; shift 2 ;;
        --top)     top="$2"; shift 2 ;;
        --no-rom)  rom=""; shift ;;
        --yosys-only) yosys_only="1"; shift ;;
        --lpf-allow-unconstrained) unconstrained="--lpf-allow-unconstrained"; shift ;;
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

for tool in yosys nextpnr-ecp5 ecppack; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "$tool not found — run: source scripts/sv16_venv.sh" >&2
        exit 1
    }
done

if [ -n "$rom" ] && [ ! -f "$rom" ]; then
    echo "$rom not found — run: make firmware   (or --no-rom)" >&2
    exit 1
fi

mkdir -p "$out"

# Read order matters to Yosys: the package first (the rest import its
# constants), then the modules, then the SoC top (which defines the ROM init
# macro and is the synthesis top).
mapfile -t rtl_files < <(ls rtl/*.sv | grep -vE 'sv16_(pkg|top)\.sv$')
rtl_files=(rtl/sv16_pkg.sv "${rtl_files[@]}" rtl/sv16_top.sv)

ys="$out/sv16_synth.ys"

# The ROM contents are a Verilog macro, so the boot image is compiled into the
# bitstream.  It is supplied through a generated header instead of a `-D` on the
# command line: the path is then a normal Verilog string literal and no shell or
# Yosys-script quoting is involved.
# Which clock source the top level should build.
case "$clksrc" in
    osc) clksrc_def=0 ;;
    pll) clksrc_def=1 ;;
    *) echo "[sv16] --clksrc must be 'osc' or 'pll' (got '$clksrc')" >&2; exit 2 ;;
esac

# ---------------------------------------------------------------- PLL search
# The ECP5 relations (rtl/sv16_pll.sv has the details):
#   fPFD = fREF / CLKI_DIV      10..400 MHz
#   fOUT = fPFD * CLKFB_DIV     feedback from CLKOP, so CLKOP_DIV cancels
#   fVCO = fOUT * CLKOP_DIV     400..800 MHz
# Search for the divider pair that hits the requested frequency most closely,
# then put the VCO near the middle of its range.  The achieved frequency is
# reported and passed to the RTL, which derives the UART divisor from it -- a
# requested frequency that cannot be hit exactly never changes the clock behind
# the user's back without saying so.
pll_clki=1; pll_clkfb=2; pll_clkop=12; pll_out="50"; pll_err="0"
if [ "$clksrc" = "pll" ]; then
    read -r pll_clki pll_clkfb pll_clkop pll_vco pll_out pll_err <<< "$(awk -v ref=25 -v want="$pllmhz" -v vcocentre=600 '
        BEGIN {
            best = ""; besterr = 1e9;
            for (cd = 1; cd <= 16; cd++) {
                pfd = ref / cd;
                if (pfd < 10 || pfd > 400) continue;
                for (fd = 1; fd <= 128; fd++) {
                    out = pfd * fd;
                    if (out < 3.125 || out > 400) continue;
                    err = (out - want) / want; if (err < 0) err = -err;
                    if (err < besterr) { besterr = err; best = cd " " fd " " out; }
                    if (err < 1e-9) break;
                }
            }
            if (best == "") { print "1 2 12 600 25 1"; exit }
            split(best, b, " ");
            cd = b[1]; fd = b[2]; out = b[3];
            div = int(vcocentre / out + 0.5);
            if (div < 1) div = 1; if (div > 128) div = 128;
            vco = out * div;
            while (vco > 800 && div > 1) { div--; vco = out * div; }
            while (vco < 400 && div < 128) { div++; vco = out * div; }
            printf "%d %d %d %d %.4f %.4f\n", cd, fd, div, vco, out, besterr;
        }')"
    if [ "$pll_clkop" -lt 1 ] || [ "$pll_clkop" -gt 128 ] || \
       [ "$(awk -v v="$pll_out" -v d="$pll_clkop" 'BEGIN{printf "%d", (v*d > 800 || v*d < 400)}')" = "1" ]; then
        echo "[sv16] --pllmhz $pllmhz has no legal ECP5 PLL configuration (VCO must stay in 400..800 MHz)" >&2
        exit 2
    fi
    achieved=$(printf '%.4g' "$pll_out")
    errpct=$(awk -v e="$pll_err" 'BEGIN{printf "%.2f", e*100}')
    echo "[sv16] PLL: ${achieved} MHz = 25 / ${pll_clki} x ${pll_clkfb} (VCO ${pll_vco} MHz), requested ${pllmhz} MHz, error ${errpct}%"
    if [ "$(awk -v e="$pll_err" 'BEGIN{print (e > 0.001) ? 1 : 0}')" = "1" ]; then
        echo "[sv16] note: the 25 MHz reference cannot hit ${pllmhz} MHz exactly with integer" \
             "dividers; building ${achieved} MHz. Exact values are multiples of 25 MHz and of 12.5 MHz." >&2
    fi
    pllmhz=$achieved
fi

if [ -z "$freq" ]; then
    if [ "$clksrc" = "pll" ]; then
        freq=$pllmhz                  # the generated clock is the constraint
    else
        freq=$(( 25 / clkdiv ))
    fi
fi

defines="$out/sv16_defines.svh"
{
    if [ -n "$rom" ]; then
        printf '`define SV16_ROM_INIT_FILE "%s"\n' "$rom"
    else
        printf '`define SV16_ROM_INIT_FILE ""\n'
    fi
    printf '`define SV16_CLKDIV %s\n' "$clkdiv"
    printf '`define SV16_CLKSRC %s\n' "$clksrc_def"
    printf '`define SV16_PLL_CLKI_DIV %s\n' "$pll_clki"
    printf '`define SV16_PLL_CLKFB_DIV %s\n' "$pll_clkfb"
    printf '`define SV16_PLL_CLKOP_DIV %s\n' "$pll_clkop"
    printf '`define SV16_PLL_KHZ %s\n' "$(awk -v m="$pllmhz" 'BEGIN{printf "%d", m*1000}')"
} > "$defines"

{
    echo "# generated by scripts/sv16_synth.sh — do not edit"
    echo "verilog_defines -DSYNTHESIS"
    echo "read_verilog -sv $defines ${rtl_files[*]}"
    echo "hierarchy -top $top"
    echo "synth_ecp5 -top $top -json $out/$top.json"
} > "$ys"

echo "[sv16] synthesizing $top: LFE5U-12F-$speed $package, ${freq} MHz system clock" \
     "(${clksrc} clock source, ROM: ${rom:-<empty>})" 
yosys -q -l "$out/sv16_yosys.log" -s "$ys"
if grep -qiE "warning: unable to (open|find).*monitor|failed to open" "$out/sv16_yosys.log"; then
    echo "[sv16] the boot ROM init file could not be read by Yosys:" >&2
    grep -iE "warning|error" "$out/sv16_yosys.log" >&2
    exit 1
fi
grep -E "Number of cells|Number of wire bits|EBR|LUT4" "$out/sv16_yosys.log" \
    | tail -6 | sed 's/^/[sv16] /'

if [ -n "$yosys_only" ]; then
    echo "[sv16] synthesis only (--yosys-only): $out/$top.json"
    exit 0
fi

echo "[sv16] placing and routing (pin constraints: $lpf)"
nextpnr-ecp5 $device --package "$package" --speed "$speed" --freq "$freq" \
    --json "$out/$top.json" --lpf "$lpf" $unconstrained \
    --textcfg "$out/$top.config" --report "$out/$top.timing.json" \
    --log "$out/sv16_nextpnr.log"
grep -E "Info: (Device utilisation|Max frequency|Critical path report)|WARNING|ERROR" \
    "$out/sv16_nextpnr.log" | tail -12 | sed 's/^/[sv16] /'
if grep -qE "^\s*Warning|ERROR" "$out/sv16_nextpnr.log"; then
    echo "[sv16] --- nextpnr warnings ---"
    grep -E "^\s*Warning|ERROR" "$out/sv16_nextpnr.log" | sed 's/^/[sv16] /'
fi

echo "[sv16] packing the bitstream"
ecppack --compress "$out/$top.config" "$out/$top.bit"
ls -l "$out/$top.bit" | awk '{print "[sv16] bitstream: " $9 " (" $5 " bytes)"}'
echo "[sv16] done — program it with: make prog"
