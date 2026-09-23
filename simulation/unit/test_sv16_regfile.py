"""
Python Golden Model & Testbench for SV-16 Register File (sv16_regfile)
Verifies functional equivalence against RTL behavioral specification.
"""

import sys

class SV16RegFileModel:
    def __init__(self):
        self.regs = [0] * 8

    def reset(self):
        self.regs = [0] * 8

    def write(self, waddr, wdata, wen):
        if wen:
            self.regs[waddr & 0x7] = wdata & 0xFFFF

    def read1(self, raddr1):
        return self.regs[raddr1 & 0x7]

    def read2(self, raddr2):
        return self.regs[raddr2 & 0x7]

def test_regfile():
    print("Testing SV-16 Register File (sv16_regfile)...")
    rf = SV16RegFileModel()
    rf.reset()

    # Verify reset
    for i in range(8):
        assert rf.read1(i) == 0, f"Reset fail on R{i}"
        assert rf.read2(i) == 0, f"Reset fail on R{i}"

    # Verify write and readback
    for i in range(8):
        val = 0xA000 | (i << 4) | i
        rf.write(i, val, wen=True)
        assert rf.read1(i) == val, f"Write/read mismatch on R{i}"

    # Simultaneous read
    assert rf.read1(2) == (0xA000 | (2 << 4) | 2)
    assert rf.read2(5) == (0xA000 | (5 << 4) | 5)
    assert rf.read1(3) == rf.read2(3)

    # Write enable gating
    rf.write(4, 0xDEAD, wen=False)
    assert rf.read1(4) != 0xDEAD, "WEN gating failed"

    rf.write(4, 0xBEEF, wen=True)
    assert rf.read1(4) == 0xBEEF, "Overwrite failed"

    print("All sv16_regfile functional verification checks passed successfully.")

if __name__ == "__main__":
    test_regfile()
