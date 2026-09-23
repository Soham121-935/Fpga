"""
Functional Model & Verification for SV-16 Status Register (sv16_status_reg)
Verifies ADR-004 flag positions:
Bit 0 = Z, Bit 1 = C, Bit 2 = N, Bit 3 = V, Bit 7 = IE
"""

import sys

class SV16StatusRegModel:
    def __init__(self):
        self.z = 0
        self.c = 0
        self.n = 0
        self.v = 0
        self.ie = 0

    def reset(self):
        self.z = 0
        self.c = 0
        self.n = 0
        self.v = 0
        self.ie = 0

    def update_alu_flags(self, z, c, n, v, enable=True):
        if enable:
            self.z = 1 if z else 0
            self.c = 1 if c else 0
            self.n = 1 if n else 0
            self.v = 1 if v else 0

    def set_ie(self, state):
        self.ie = 1 if state else 0

    def direct_write(self, data16):
        self.z = data16 & 0x1
        self.c = (data16 >> 1) & 0x1
        self.n = (data16 >> 2) & 0x1
        self.v = (data16 >> 3) & 0x1
        self.ie = (data16 >> 7) & 0x1

    def read(self):
        return (self.ie << 7) | (self.v << 3) | (self.n << 2) | (self.c << 1) | self.z

def test_status_reg():
    print("Testing SV-16 Status Register (sv16_status_reg)...")
    sr = SV16StatusRegModel()
    sr.reset()
    assert sr.read() == 0x0000

    # Latch Z, N, V (Z=1, C=0, N=1, V=1 -> 0b1101 = 0xD)
    sr.update_alu_flags(z=1, c=0, n=1, v=1, enable=True)
    assert sr.read() == 0x000D

    # Hold flags when enable=False
    sr.update_alu_flags(z=0, c=1, n=0, v=0, enable=False)
    assert sr.read() == 0x000D

    # Atomic interrupt set (bit 7)
    sr.set_ie(True)
    assert sr.read() == 0x008D
    sr.set_ie(False)
    assert sr.read() == 0x000D

    # Direct architectural write
    sr.direct_write(0x0082) # IE=1, C=1
    assert sr.read() == 0x0082
    assert sr.c == 1 and sr.ie == 1 and sr.z == 0

    print("All sv16_status_reg functional verification checks passed successfully.")

if __name__ == "__main__":
    test_status_reg()
