"""
Functional Model & Verification for SV-16 Instruction Decoder (sv16_decoder)
Verifies instruction field slicing, opcode classification, and immediate sign extensions.
"""

import sys

def decode(instr16):
    opcode = (instr16 >> 12) & 0xF
    rd = (instr16 >> 9) & 0x7
    rs1 = (instr16 >> 6) & 0x7
    rs2 = (instr16 >> 3) & 0x7
    subop = instr16 & 0x7
    cond = (instr16 >> 8) & 0xF

    # sign extend imm9
    imm9 = instr16 & 0x1FF
    imm9_ext = imm9 - 512 if (imm9 & 0x100) else imm9

    # sign extend offset6
    off6 = instr16 & 0x3F
    off6_ext = off6 - 64 if (off6 & 0x20) else off6

    branch_offset = instr16 & 0xFF
    if branch_offset & 0x80:
        branch_offset_ext = branch_offset - 256
    else:
        branch_offset_ext = branch_offset

    is_two_word = opcode in (0x4, 0x9, 0xA)
    return {
        "opcode": opcode,
        "rd": rd,
        "rs1": rs1,
        "rs2": rs2,
        "subop": subop,
        "cond": cond,
        "imm9_ext": imm9_ext,
        "off6_ext": off6_ext,
        "branch_offset_ext": branch_offset_ext,
        "is_two_word": is_two_word
    }

def test_decoder():
    print("Testing SV-16 Instruction Decoder (sv16_decoder)...")

    # Format R: ADD R1, R2, R3
    d = decode((0x1 << 12) | (1 << 9) | (2 << 6) | (3 << 3) | 0)
    assert d["opcode"] == 0x1 and d["rd"] == 1 and d["rs1"] == 2 and d["rs2"] == 3 and d["subop"] == 0

    # Format I: ADDI R4, #-5
    imm_val = (-5) & 0x1FF
    d = decode((0x2 << 12) | (4 << 9) | imm_val)
    assert d["opcode"] == 0x2 and d["rd"] == 4 and d["imm9_ext"] == -5

    # Format M: LOAD R2, [R5 + 8]
    d = decode((0x5 << 12) | (2 << 9) | (5 << 6) | 8)
    assert d["opcode"] == 0x5 and d["rd"] == 2 and d["rs1"] == 5 and d["off6_ext"] == 8

    # Format B: BEQ +20
    d = decode((0x8 << 12) | (1 << 8) | 20)
    assert d["opcode"] == 0x8 and d["cond"] == 1 and d["branch_offset_ext"] == 20

    # Two-word instructions: LDI, JMP, CALL
    for op in (0x4, 0x9, 0xA):
        d = decode(op << 12)
        assert d["is_two_word"] is True

    print("All sv16_decoder functional verification checks passed successfully.")

if __name__ == "__main__":
    test_decoder()
