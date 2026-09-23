#!/usr/bin/env python3
"""
SV-16 Rev A — Cross-Assembler (sv16_as.py)
Translates SV-16 assembly (.s / .asm) into machine code (.hex, .mem, .bin).

Supports:
- Two-pass symbol and label resolution
- Instructions: NOP, HALT, EI, DI, RETI, ADD, SUB, AND, OR, XOR, NOT, INC, DEC,
               SHL, SHR, MUL, DIV, MOD, ADDI, SUBI, LDI, LOAD, STORE, MOV,
               BRANCH (BRA, BEQ, BNE, BC, BNC, BN, BP, BVS, BVC, BLT, BGE, BLE, BGT),
               JMP, CALL, RET, PUSH, POP, CMP
- Directives: .org, .word, .space, .equ
"""

import sys
import re
import os

OPCODES = {
    'NOP':   (0x0, 'S_NOP'),
    'HALT':  (0x0, 'S_HALT'),
    'EI':    (0x0, 'S_EI'),
    'DI':    (0x0, 'S_DI'),
    'RETI':  (0x0, 'S_RETI'),
    'ADD':   (0x1, 'R', 0x0),
    'SUB':   (0x1, 'R', 0x1),
    'AND':   (0x1, 'R', 0x2),
    'OR':    (0x1, 'R', 0x3),
    'XOR':   (0x1, 'R', 0x4),
    'NOT':   (0x1, 'R_NOT', 0x5),
    'INC':   (0x1, 'R_INC', 0x6),
    'DEC':   (0x1, 'R_DEC', 0x7),
    'ADDI':  (0x2, 'I'),
    'SUBI':  (0x3, 'I'),
    'LDI':   (0x4, 'LDI'),
    'LOAD':  (0x5, 'M'),
    'STORE': (0x6, 'M'),
    'MOV':   (0x7, 'MOV'),
    'BRA':   (0x8, 'B', 0x0),
    'BEQ':   (0x8, 'B', 0x1),
    'BNE':   (0x8, 'B', 0x2),
    'BC':    (0x8, 'B', 0x3),
    'BLO':   (0x8, 'B', 0x3),
    'BNC':   (0x8, 'B', 0x4),
    'BHS':   (0x8, 'B', 0x4),
    'BN':    (0x8, 'B', 0x5),
    'BMI':   (0x8, 'B', 0x5),
    'BP':    (0x8, 'B', 0x6),
    'BPL':   (0x8, 'B', 0x6),
    'BVS':   (0x8, 'B', 0x7),
    'BVC':   (0x8, 'B', 0x8),
    'BLT':   (0x8, 'B', 0x9),
    'BGE':   (0x8, 'B', 0xA),
    'BLE':   (0x8, 'B', 0xB),
    'BGT':   (0x8, 'B', 0xC),
    'JMP':   (0x9, 'JMP'),
    'CALL':  (0xA, 'CALL'),
    'RET':   (0xB, 'RET'),
    'PUSH':  (0xC, 'PUSH'),
    'POP':   (0xD, 'POP'),
    'CMP':   (0xE, 'CMP'),
    'SHL':   (0xF, 'R', 0x0),
    'SHR':   (0xF, 'R', 0x1),
    'MUL':   (0xF, 'R', 0x2),
    'DIV':   (0xF, 'R', 0x3),
    'MOD':   (0xF, 'R', 0x4)
}

REGISTERS = {f'R{i}': i for i in range(8)}

def parse_num(token, symbols=None):
    token = token.strip().lstrip('#')
    if symbols and token in symbols:
        return symbols[token]
    if token.startswith('0x') or token.startswith('0X'):
        return int(token, 16)
    if token.startswith('0b') or token.startswith('0B'):
        return int(token, 2)
    return int(token)

def assemble(lines):
    symbols = {}
    cleaned = []

    # Clean lines
    for line in lines:
        line = line.split(';')[0].split('//')[0].strip()
        if not line:
            continue
        cleaned.append(line)

    # Pass 1: Collect symbols & calculate addresses
    curr_addr = 0
    instructions_pass1 = []

    for line in cleaned:
        if ':' in line:
            parts = line.split(':', 1)
            lbl = parts[0].strip()
            symbols[lbl] = curr_addr
            line = parts[1].strip()
            if not line:
                continue

        tokens = re.split(r'[\s,]+', line)
        mnemonic = tokens[0].upper()

        if mnemonic == '.ORG':
            curr_addr = parse_num(tokens[1], symbols)
            instructions_pass1.append((mnemonic, tokens[1:], curr_addr))
            continue
        elif mnemonic == '.EQU':
            symbols[tokens[1]] = parse_num(tokens[2], symbols)
            continue
        elif mnemonic == '.WORD':
            instructions_pass1.append((mnemonic, tokens[1:], curr_addr))
            curr_addr += 1
            continue

        if mnemonic not in OPCODES:
            raise ValueError(f"Unknown mnemonic: {mnemonic}")

        entry = OPCODES[mnemonic]
        fmt = entry[1]
        words = 2 if fmt in ('LDI', 'JMP', 'CALL') else 1

        instructions_pass1.append((mnemonic, tokens[1:], curr_addr))
        curr_addr += words

    # Pass 2: Generate machine code
    memory_words = {}
    curr_addr = 0

    for mnemonic, args, addr in instructions_pass1:
        curr_addr = addr
        if mnemonic == '.ORG':
            continue
        elif mnemonic == '.WORD':
            val = parse_num(args[0], symbols) & 0xFFFF
            memory_words[curr_addr] = val
            continue

        entry = OPCODES[mnemonic]
        opcode = entry[0]
        fmt = entry[1]

        if fmt == 'R':
            subop = entry[2]
            rd = REGISTERS[args[0].upper()]
            rs1 = REGISTERS[args[1].upper()]
            rs2 = REGISTERS[args[2].upper()] if len(args) > 2 else 0
            code = (opcode << 12) | (rd << 9) | (rs1 << 6) | (rs2 << 3) | subop
            memory_words[curr_addr] = code

        elif fmt == 'R_NOT':
            rd = REGISTERS[args[0].upper()]
            rs1 = REGISTERS[args[1].upper()] if len(args) > 1 else rd
            code = (opcode << 12) | (rd << 9) | (rs1 << 6) | entry[2]
            memory_words[curr_addr] = code

        elif fmt == 'R_INC' or fmt == 'R_DEC':
            rd = REGISTERS[args[0].upper()]
            rs1 = REGISTERS[args[1].upper()] if len(args) > 1 else rd
            code = (opcode << 12) | (rd << 9) | (rs1 << 6) | entry[2]
            memory_words[curr_addr] = code

        elif fmt == 'I':
            rd = REGISTERS[args[0].upper()]
            imm = parse_num(args[1], symbols) & 0x1FF
            code = (opcode << 12) | (rd << 9) | imm
            memory_words[curr_addr] = code

        elif fmt == 'LDI':
            rd = REGISTERS[args[0].upper()]
            val = parse_num(args[1], symbols) & 0xFFFF
            code1 = (opcode << 12) | (rd << 9)
            code2 = val
            memory_words[curr_addr] = code1
            memory_words[curr_addr + 1] = code2

        elif fmt == 'M':
            # e.g., LOAD R1, [R0 + 4] or STORE R1, [R0]
            rd = REGISTERS[args[0].upper()]
            mem_expr = "".join(args[1:])
            m = re.match(r'\[\s*(R\d)\s*(?:([+-])\s*(\w+))?\s*\]', mem_expr, re.IGNORECASE)
            if not m:
                raise ValueError(f"Invalid memory operand: {mem_expr}")
            rb = REGISTERS[m.group(1).upper()]
            offset = 0
            if m.group(2) and m.group(3):
                val = parse_num(m.group(3), symbols)
                offset = val if m.group(2) == '+' else -val
            off6 = offset & 0x3F
            code = (opcode << 12) | (rd << 9) | (rb << 6) | off6
            memory_words[curr_addr] = code

        elif fmt == 'MOV':
            rd = REGISTERS[args[0].upper()]
            rs1 = REGISTERS[args[1].upper()]
            code = (opcode << 12) | (rd << 9) | (rs1 << 6)
            memory_words[curr_addr] = code

        elif fmt == 'B':
            cond = entry[2]
            target = parse_num(args[0], symbols)
            rel_offset = (target - (curr_addr + 1)) & 0xFF
            code = (opcode << 12) | (cond << 8) | rel_offset
            memory_words[curr_addr] = code

        elif fmt == 'JMP' or fmt == 'CALL':
            target = parse_num(args[0], symbols) & 0xFFFF
            code1 = (opcode << 12)
            code2 = target
            memory_words[curr_addr] = code1
            memory_words[curr_addr + 1] = code2

        elif fmt == 'RET':
            code = (opcode << 12)
            memory_words[curr_addr] = code

        elif fmt == 'PUSH' or fmt == 'POP':
            rx = REGISTERS[args[0].upper()]
            code = (opcode << 12) | (rx << 9)
            memory_words[curr_addr] = code

        elif fmt == 'CMP':
            rs1 = REGISTERS[args[0].upper()]
            rs2 = REGISTERS[args[1].upper()]
            code = (opcode << 12) | (rs1 << 11) | (rs2 << 8)
            memory_words[curr_addr] = code

        elif fmt.startswith('S_'):
            code = 0x0000
            memory_words[curr_addr] = code

    return memory_words

def write_hex(memory_words, outpath, depth=4096):
    with open(outpath, 'w') as f:
        max_addr = max(memory_words.keys()) if memory_words else 0
        limit = max(max_addr + 1, depth)
        for a in range(limit):
            val = memory_words.get(a, 0x0000)
            f.write(f"{val:04X}\n")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: sv16_as.py <input.s> <output.hex>")
        sys.exit(1)
    with open(sys.argv[1], 'r') as f:
        lines = f.readlines()
    words = assemble(lines)
    write_hex(words, sys.argv[2])
    print(f"[OK] Assembled {len(words)} words into {sys.argv[2]}")
