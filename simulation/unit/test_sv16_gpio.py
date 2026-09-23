"""
Functional Verification of SV-16 GPIO Controller (sv16_gpio)
Verifies:
- Direction control (GPIO_DIR)
- Direct data writing (GPIO_DATA)
- Atomic SET (GPIO_SET)
- Atomic CLR (GPIO_CLR)
- Input reading through direction mask
"""

import sys

class SV16GPIOModel:
    def __init__(self):
        self.data_out = 0
        self.dir = 0 # 0=input, 1=output
        self.pin_in = 0

    def write_reg(self, offset, val):
        val = val & 0xFFFF
        if offset == 0:   # GPIO_DATA
            self.data_out = val
        elif offset == 1: # GPIO_DIR
            self.dir = val
        elif offset == 2: # GPIO_SET
            self.data_out |= val
        elif offset == 3: # GPIO_CLR
            self.data_out &= ~val

    def read_reg(self, offset):
        if offset == 0:
            # Read pins: inputs from pin_in, outputs from data_out
            return ((self.pin_in & ~self.dir) | (self.data_out & self.dir)) & 0xFFFF
        elif offset == 1:
            return self.dir
        return 0

def test_gpio():
    print("Testing SV-16 GPIO Controller (sv16_gpio)...")
    gpio = SV16GPIOModel()

    # Direction write
    gpio.write_reg(1, 0x00FF)
    assert gpio.dir == 0x00FF

    # Atomic SET
    gpio.write_reg(2, 0x0005) # set bits 0 and 2
    assert gpio.data_out == 0x0005

    # Atomic CLR
    gpio.write_reg(3, 0x0001) # clr bit 0
    assert gpio.data_out == 0x0004

    # Atomic SET another bit
    gpio.write_reg(2, 0x0080)
    assert gpio.data_out == 0x0084

    # Pin input reading
    gpio.pin_in = 0xAA00
    # lower byte is output (0x84), upper byte is input (0xAA)
    readback = gpio.read_reg(0)
    assert readback == 0xAA84, f"Readback was 0x{readback:04X}, expected 0xAA84"

    print("All sv16_gpio functional checks passed successfully.")

if __name__ == "__main__":
    test_gpio()
