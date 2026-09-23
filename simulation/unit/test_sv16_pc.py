"""
Functional Model & Verification for SV-16 Program Counter (sv16_pc)
Tests reset, increment, hold, direct load, and relative branches (positive/negative).
"""

import sys

class SV16PCModel:
    def __init__(self):
        self.pc = 0

    def reset(self):
        self.pc = 0

    def step(self, pc_inc=False, pc_load=False, pc_branch=False, target_addr=0, branch_offset=0):
        if pc_load:
            self.pc = target_addr & 0xFFFF
        elif pc_branch:
            # sign extend 8-bit offset
            if branch_offset & 0x80:
                signed_offset = branch_offset - 256
            else:
                signed_offset = branch_offset
            self.pc = (self.pc + signed_offset) & 0xFFFF
        elif pc_inc:
            self.pc = (self.pc + 1) & 0xFFFF

def test_pc():
    print("Testing SV-16 Program Counter (sv16_pc)...")
    pc_mod = SV16PCModel()
    pc_mod.reset()
    assert pc_mod.pc == 0x0000

    # Sequential increment
    pc_mod.step(pc_inc=True)
    assert pc_mod.pc == 0x0001
    pc_mod.step(pc_inc=True)
    assert pc_mod.pc == 0x0002

    # Hold / Stall
    pc_mod.step()
    assert pc_mod.pc == 0x0002

    # Direct load
    pc_mod.step(pc_load=True, target_addr=0x0500)
    assert pc_mod.pc == 0x0500

    # Forward branch (+10)
    pc_mod.step(pc_branch=True, branch_offset=10)
    assert pc_mod.pc == 0x050A

    # Backward branch (-20 = 0xEC)
    pc_mod.step(pc_branch=True, branch_offset=0xEC)
    assert pc_mod.pc == 0x04F6

    print("All sv16_pc functional verification checks passed successfully.")

if __name__ == "__main__":
    test_pc()
