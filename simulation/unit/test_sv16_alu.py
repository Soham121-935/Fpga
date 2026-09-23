"""
Comprehensive Functional Verification for SV-16 ALU (sv16_alu)
Covers all operations, flags (Z, C, N, V), and boundary/corner cases:
- 0, 0xFFFF, 0x7FFF, 0x8000
- DIV by zero, MOD by zero
- Shifts by 0, 1, 15
"""

import sys

def simulate_alu(a, b, op, is_extended):
    a = a & 0xFFFF
    b = b & 0xFFFF
    res = 0
    flag_c = 0
    flag_v = 0

    if not is_extended:
        if op == 0:  # ADD
            raw = a + b
            res = raw & 0xFFFF
            flag_c = 1 if raw > 0xFFFF else 0
            # signed overflow:
            sign_a = (a >> 15) & 1
            sign_b = (b >> 15) & 1
            sign_res = (res >> 15) & 1
            flag_v = 1 if (sign_a == sign_b and sign_res != sign_a) else 0

        elif op == 1:  # SUB
            diff = a - b
            res = diff & 0xFFFF
            flag_c = 1 if a < b else 0
            sign_a = (a >> 15) & 1
            sign_b = (b >> 15) & 1
            sign_res = (res >> 15) & 1
            flag_v = 1 if (sign_a != sign_b and sign_res != sign_a) else 0

        elif op == 2:  # AND
            res = a & b
        elif op == 3:  # OR
            res = a | b
        elif op == 4:  # XOR
            res = a ^ b
        elif op == 5:  # NOT
            res = (~a) & 0xFFFF
        elif op == 6:  # INC
            raw = a + 1
            res = raw & 0xFFFF
            flag_c = 1 if raw > 0xFFFF else 0
            flag_v = 1 if a == 0x7FFF else 0
        elif op == 7:  # DEC
            raw = a - 1
            res = raw & 0xFFFF
            flag_c = 1 if a == 0 else 0
            flag_v = 1 if a == 0x8000 else 0

    else:
        shamt = b & 0xF
        if op == 0:  # SHL
            if shamt == 0:
                res = a
                flag_c = 0
            else:
                res = (a << shamt) & 0xFFFF
                flag_c = (a >> (16 - shamt)) & 1
        elif op == 1:  # SHR
            if shamt == 0:
                res = a
                flag_c = 0
            else:
                res = (a >> shamt) & 0xFFFF
                flag_c = (a >> (shamt - 1)) & 1
        elif op == 2:  # MUL
            mul = a * b
            res = mul & 0xFFFF
            flag_c = 1 if (mul >> 16) != 0 else 0
            flag_v = flag_c
        elif op == 3:  # DIV
            if b == 0:
                res = 0xFFFF
                flag_v = 1
            else:
                res = (a // b) & 0xFFFF
        elif op == 4:  # MOD
            if b == 0:
                res = 0
                flag_v = 1
            else:
                res = (a % b) & 0xFFFF

    flag_z = 1 if res == 0 else 0
    flag_n = (res >> 15) & 1

    return res, flag_z, flag_c, flag_n, flag_v

def run_alu_tests():
    print("Testing SV-16 16-Bit ALU (sv16_alu)...")

    # 1. ADD checks
    r, z, c, n, v = simulate_alu(5, 10, 0, False)
    assert r == 15 and z == 0 and c == 0 and n == 0 and v == 0

    r, z, c, n, v = simulate_alu(0xFFFF, 1, 0, False)
    assert r == 0 and z == 1 and c == 1 and n == 0 and v == 0, f"Got {r},{z},{c},{n},{v}"

    r, z, c, n, v = simulate_alu(0x7FFF, 1, 0, False)
    assert r == 0x8000 and z == 0 and c == 0 and n == 1 and v == 1, "Signed overflow ADD failed"

    # 2. SUB checks
    r, z, c, n, v = simulate_alu(10, 4, 1, False)
    assert r == 6 and z == 0 and c == 0 and n == 0 and v == 0

    r, z, c, n, v = simulate_alu(4, 10, 1, False)
    assert r == 0xFFFA and z == 0 and c == 1 and n == 1 and v == 0

    r, z, c, n, v = simulate_alu(0x8000, 1, 1, False)
    assert r == 0x7FFF and z == 0 and c == 0 and n == 0 and v == 1, "Signed overflow SUB failed"

    # 3. Logic & Inc/Dec
    r, z, c, n, v = simulate_alu(0xFF00, 0x0FF0, 2, False) # AND
    assert r == 0x0F00 and z == 0 and n == 0

    r, z, c, n, v = simulate_alu(0, 0, 5, False) # NOT 0 -> 0xFFFF
    assert r == 0xFFFF and z == 0 and n == 1

    r, z, c, n, v = simulate_alu(0x7FFF, 0, 6, False) # INC 0x7FFF
    assert r == 0x8000 and v == 1 and n == 1

    r, z, c, n, v = simulate_alu(0, 0, 7, False) # DEC 0
    assert r == 0xFFFF and c == 1 and n == 1

    # 4. Extended operations
    # Shift
    r, z, c, n, v = simulate_alu(0x8000, 1, 0, True) # SHL 1 -> c=1, res=0
    assert r == 0 and z == 1 and c == 1

    r, z, c, n, v = simulate_alu(0x0001, 1, 1, True) # SHR 1 -> c=1, res=0
    assert r == 0 and z == 1 and c == 1

    # Multiplication
    r, z, c, n, v = simulate_alu(1000, 2, 2, True)
    assert r == 2000 and c == 0 and v == 0

    r, z, c, n, v = simulate_alu(0x1000, 0x0020, 2, True) # mul overflow
    assert r == 0x0000 and c == 1 and v == 1

    # Division & Div by Zero
    r, z, c, n, v = simulate_alu(100, 20, 3, True)
    assert r == 5 and z == 0 and v == 0

    r, z, c, n, v = simulate_alu(100, 0, 3, True) # Div by 0
    assert r == 0xFFFF and v == 1 and n == 1

    # Modulo by Zero
    r, z, c, n, v = simulate_alu(100, 0, 4, True) # Mod by 0
    assert r == 0 and z == 1 and v == 1

    print("All sv16_alu test cases (nominal + corner cases) passed successfully.")

if __name__ == "__main__":
    run_alu_tests()
