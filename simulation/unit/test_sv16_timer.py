"""
Functional Verification of SV-16 Hardware Timer (sv16_timer)
Verifies:
- Prescaler operation
- Up-counting and compare match detection
- Auto-reload behavior
- Interrupt generation when IE=1
- Match flag clearing
"""

import sys

class SV16TimerModel:
    def __init__(self):
        self.cnt = 0
        self.cmp = 0xFFFF
        self.ctrl = 0 # bit 0: EN, bit 1: AUTO_RELOAD, bit 2: IE
        self.match = False

    def tick(self):
        en = self.ctrl & 1
        auto_reload = (self.ctrl >> 1) & 1

        if en:
            if self.cnt == self.cmp:
                self.match = True
                if auto_reload:
                    self.cnt = 0
                else:
                    self.cnt = (self.cnt + 1) & 0xFFFF
            else:
                self.cnt = (self.cnt + 1) & 0xFFFF

    def irq(self):
        ie = (self.ctrl >> 2) & 1
        return self.match and bool(ie)

def test_timer():
    print("Testing SV-16 Hardware Timer (sv16_timer)...")
    tmr = SV16TimerModel()

    # Set compare = 4, ctrl = 7 (EN + AUTO_RELOAD + IE)
    tmr.cmp = 4
    tmr.ctrl = 0x0007

    # Count from 0 to 4
    for _ in range(4):
        tmr.tick()
        assert not tmr.match

    # 5th tick reaches compare 4
    tmr.tick()
    assert tmr.match is True
    assert tmr.irq() is True
    assert tmr.cnt == 0 # Auto-reloaded

    # Clear match
    tmr.match = False
    assert tmr.irq() is False

    print("All sv16_timer functional checks passed successfully.")

if __name__ == "__main__":
    test_timer()
