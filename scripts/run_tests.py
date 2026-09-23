#!/usr/bin/env python3
"""
SV-16 Rev A — Verification Runner & Test Harness
Automated test framework for SV-16 unit tests, regressions, syntax validation,
functional model verification, cross-assembler, and instruction set simulator.
"""

import sys
import os
import subprocess
import glob

def check_verilog_syntax(filepath):
    """
    Check Verilog / SystemVerilog syntax if verilator/iverilog is available,
    otherwise performs basic structural syntax validation.
    """
    if subprocess.run(["which", "iverilog"], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0:
        res = subprocess.run(["iverilog", "-g2012", "-t", "null", filepath], capture_output=True, text=True)
        return (res.returncode == 0, res.stderr)
    elif subprocess.run(["which", "verilator"], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0:
        res = subprocess.run(["verilator", "--lint-only", "-Wall", filepath], capture_output=True, text=True)
        return (res.returncode == 0, res.stderr)
    else:
        # Fallback structural check
        with open(filepath, 'r') as f:
            lines = f.readlines()
        modules = 0
        endmodules = 0
        packages = 0
        endpackages = 0
        for line in lines:
            clean = line.split('//')[0].strip()
            tokens = clean.split()
            if 'module' in tokens and not 'endmodule' in tokens:
                modules += 1
            if 'endmodule' in tokens:
                endmodules += 1
            if 'package' in tokens and not 'endpackage' in tokens:
                packages += 1
            if 'endpackage' in tokens:
                endpackages += 1

        if (modules > 0 and modules == endmodules) or (packages > 0 and packages == endpackages):
            return (True, "Structure valid.")
        elif modules == 0 and packages == 0:
            return (True, "Header/include file.")
        else:
            return (False, f"Mismatched blocks: {modules} mod vs {endmodules} endmod, {packages} pkg vs {endpackages} endpkg")

def run_functional_tests():
    """Runs all python-based functional verification testbenches in simulation/"""
    py_tests = sorted(list(set(glob.glob("simulation/**/test_*.py", recursive=True))))
    passed = 0
    failed = 0
    for test in py_tests:
        res = subprocess.run([sys.executable, test], capture_output=True, text=True)
        if res.returncode == 0:
            print(f"[PASS] {test}")
            passed += 1
        else:
            print(f"[FAIL] {test}:\n{res.stderr}\n{res.stdout}")
            failed += 1
    return passed, failed

def run_software_toolchain_tests():
    """Tests cross-assembler and software simulator execution"""
    print("\n--- 3. Software Toolchain (Assembler & Simulator) ---")
    passed = 0
    failed = 0

    # 1. Test Assembler
    res_as = subprocess.run([sys.executable, "scripts/sv16_as.py", "firmware/examples/motor_test.s", "firmware/bootrom.hex"],
                            capture_output=True, text=True)
    if res_as.returncode == 0:
        print("[PASS] scripts/sv16_as.py (Assembly of firmware/examples/motor_test.s)")
        passed += 1
    else:
        print(f"[FAIL] scripts/sv16_as.py:\n{res_as.stderr}")
        failed += 1

    # 2. Test Simulator
    res_sim = subprocess.run([sys.executable, "scripts/sv16_sim.py", "--test"],
                             capture_output=True, text=True)
    if res_sim.returncode == 0:
        print("[PASS] scripts/sv16_sim.py (Execution of bootrom.hex)")
        passed += 1
    else:
        print(f"[FAIL] scripts/sv16_sim.py:\n{res_sim.stderr}")
        failed += 1

    return passed, failed

def run_all_tests():
    print("=" * 60)
    print("SV-16 Rev A — Verification Suite")
    print("=" * 60)

    rtl_files = sorted(glob.glob("rtl/**/*.sv", recursive=True) + glob.glob("rtl/**/*.v", recursive=True))
    sim_files = sorted(glob.glob("simulation/**/*.sv", recursive=True) + glob.glob("simulation/**/*.v", recursive=True))

    all_sv_files = rtl_files + sim_files
    passed = 0
    failed = 0

    print("--- 1. RTL & Testbench Structural Validation ---")
    for fpath in all_sv_files:
        valid, msg = check_verilog_syntax(fpath)
        if valid:
            print(f"[PASS] {fpath}")
            passed += 1
        else:
            print(f"[FAIL] {fpath}: {msg}")
            failed += 1

    print("\n--- 2. Functional Verification Testbenches ---")
    fn_passed, fn_failed = run_functional_tests()
    passed += fn_passed
    failed += fn_failed

    sw_passed, sw_failed = run_software_toolchain_tests()
    passed += sw_passed
    failed += sw_failed

    print("-" * 60)
    print(f"Summary: {passed} passed, {failed} failed")
    print("=" * 60)
    return 1 if failed > 0 else 0

if __name__ == '__main__':
    sys.exit(run_all_tests())
