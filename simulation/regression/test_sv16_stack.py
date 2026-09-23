"""
Functional Verification of SV-16 Stack Pointer, PUSH, POP, CALL, and RET
Simulates full descending stack semantics per ADR-006:
- PUSH: SP decrements by 1, writes to MEM[SP]
- POP: Reads MEM[SP], SP increments by 1
- CALL: Pushes return PC to stack, jumps to target
- RET: Pops return address from stack to PC
"""

import sys

class StackSubroutineTester:
    def __init__(self):
        self.regs = [0] * 8
        self.sp = 0x1FFE
        self.pc = 0
        self.mem = {}

    def push(self, val):
        self.sp -= 1
        self.mem[self.sp] = val & 0xFFFF

    def pop(self):
        val = self.mem[self.sp]
        self.sp += 1
        return val

    def call(self, target_addr, return_addr):
        self.push(return_addr)
        self.pc = target_addr

    def ret(self):
        self.pc = self.pop()

def test_stack_and_subroutines():
    print("Testing SV-16 Stack & Subroutines (PUSH, POP, CALL, RET)...")
    st = StackSubroutineTester()

    # 1. Test PUSH and POP
    init_sp = st.sp
    st.push(0x0042)
    assert st.sp == init_sp - 1
    val = st.pop()
    assert val == 0x0042
    assert st.sp == init_sp

    # 2. Test CALL and RET
    call_site_return = 0x0008
    subroutine_entry = 0x0010
    st.call(target_addr=subroutine_entry, return_addr=call_site_return)
    assert st.pc == subroutine_entry
    assert st.sp == init_sp - 1

    # In subroutine: do work, then RET
    st.ret()
    assert st.pc == call_site_return
    assert st.sp == init_sp

    # 3. Test Nested CALLs
    st.call(target_addr=0x0100, return_addr=0x0020) # Level 1 call
    assert st.sp == init_sp - 1
    st.call(target_addr=0x0200, return_addr=0x0110) # Level 2 call
    assert st.sp == init_sp - 2

    st.ret() # Level 2 return
    assert st.pc == 0x0110
    assert st.sp == init_sp - 1

    st.ret() # Level 1 return
    assert st.pc == 0x0020
    assert st.sp == init_sp

    print("All sv16_stack_subroutine checks (single & nested calls) passed successfully.")

if __name__ == "__main__":
    test_stack_and_subroutines()
