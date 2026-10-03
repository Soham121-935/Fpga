#!/usr/bin/env python3
"""SV-16 — elaborate the whole RTL with slang and report every diagnostic.

This is the check that found the 22 errors fixed in "Make the RTL compile":
declarations read before they are declared, missing `timescale, and the
BOOT_CTRL read-back that disagreed with its own write decode.  Unlike a
linter it understands the design, so it catches port-width mismatches,
undeclared identifiers and bad concatenations across module boundaries.

Install:
    python3 -m pip install pyslang

Usage:
    scripts/sv16_slang_check.py                  # errors only (exit 1 on error)
    scripts/sv16_slang_check.py --warnings       # also show warnings
    scripts/sv16_slang_check.py --top sv16_boot  # elaborate a different top

Exit code: 0 clean, 1 errors found, 2 could not run.

Two things worth knowing if you extend this:

  * comp.getRoot() is what forces elaboration.  Without it slang only
    parses, reports nothing, and a broken design looks clean.  The
    --selftest flag plants a deliberate bug to prove the check fires.

  * The RTL relies on `default_nettype none to turn a mistyped signal
    name into an error.  Without it a typo becomes a 1-bit net and this
    check stays silent, which is exactly the failure mode it exists to
    catch.
"""

from __future__ import annotations

import argparse
import glob
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from pyslang.driver import Driver
except ImportError:
    sys.stderr.write(
        "pyslang is not installed - skipping the SystemVerilog elaboration check.\n"
        "    python3 -m pip install pyslang\n")
    sys.exit(2)


def elaborate(top="sv16_top", extra=()):
    """Parse and elaborate every rtl/*.sv.  Returns (driver, diagnostics)."""
    files = sorted(glob.glob(str(ROOT / "rtl" / "*.sv")))
    if not files:
        sys.stderr.write("no rtl/*.sv found under %s\n" % ROOT)
        sys.exit(2)
    line = " ".join(["-I%s" % (ROOT / "rtl"), "--top", top,
                     "--error-limit", "5000"] + list(extra)
                    + [shlex.quote(f) for f in files])
    drv = Driver()
    drv.addStandardArgs()
    if not drv.parseCommandLine(line):
        sys.stderr.write("slang: could not parse the command line\n")
        sys.exit(2)
    if not drv.processOptions():
        sys.stderr.write("slang: bad options\n")
        sys.exit(2)
    if not drv.parseAllSources():
        sys.stderr.write("slang: could not parse the sources\n")
        sys.exit(2)
    comp = drv.createCompilation()
    comp.getRoot()                      # forces elaboration - see module docstring
    return drv, comp, list(comp.getAllDiagnostics())


def message(diag):
    """The diagnostic text, so a selftest can match on it."""
    try:
        return str(diag.formattedMessage)
    except AttributeError:
        return "%s %s" % (diag.code, " ".join(str(a) for a in diag.args))


def selftest():
    """Plant an undeclared identifier and confirm the check reports it."""
    victim = ROOT / "rtl" / "sv16_alu.sv"
    original = victim.read_text()
    anchor = "    logic [16:0] sum_ext;"
    if anchor not in original:
        sys.stderr.write("selftest: anchor missing from %s\n" % victim.name)
        return False
    victim.write_text(original.replace(
        anchor, anchor + "\n    assign selftest_typo = 1'b1 & no_such_sig;", 1))
    try:
        _, _, diags = elaborate()
        fired = [d for d in diags if "selftest_typo" in message(d) or
                 "no_such_sig" in message(d)]
        print("selftest: %d diagnostic(s) on the planted typo" % len(fired))
        return bool(fired)
    finally:
        victim.write_text(original)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--warnings", action="store_true",
                    help="also report warnings (4 are known and benign)")
    ap.add_argument("--top", default="sv16_top")
    ap.add_argument("--selftest", action="store_true",
                    help="plant a deliberate bug and check it is caught")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(0 if selftest() else 1)

    extra = ("-Weverything", "-Wno-missing-top") if args.warnings else ()
    drv, comp, diags = elaborate(args.top, extra=extra)
    drv.reportCompilation(comp, False)

    # Severity has to come from the engine: Diagnostic.isError reflects
    # slang's built-in table, not the severity after -W has been applied,
    # and it calls four benign warnings errors.
    engine = drv.diagEngine
    sev = [str(engine.getSeverity(d.code, d.location)).rsplit(".", 1)[-1]
           for d in diags]
    errors = [d for d, s in zip(diags, sev) if s in ("Error", "Fatal")]
    print("\nslang: %d error(s), %d other diagnostic(s)"
          % (len(errors), len(diags) - len(errors)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
