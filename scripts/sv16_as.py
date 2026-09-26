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
- Directives: .org, .word, .equ, .asciiz
- Absolute origin support: the output file starts at the lowest .ORG address, so
  ROM images (.org 0xE000) load 1:1 into sv16_rom's memory array.
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

def ascii_words(literal):
    """'TEXT' -> the list of 16-bit words for .ASCIIZ (one char per word + NUL)."""
    text = literal.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    if text.startswith('\\n'):
        pass
    escaped = text.replace('\\r', '\r').replace('\\n', '\n').replace('\\t', '\t')
    return [ord(c) & 0xFFFF for c in escaped] + [0x0000]


def split_asciiz(line):
    """Return the .ASCIIZ prefix (label + directive) and the quoted literal."""
    q1 = line.find('"')
    q2 = line.rfind('"')
    if q1 < 0 or q2 <= q1:
        raise ValueError(f".ASCIIZ needs a quoted string: {line}")
    return line[:q1].strip(), line[q1:q2 + 1]


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

    srcmap = []                       # (addr, word count, source text)

    for line in cleaned:
        src = line
        if ':' in line.split('"')[0]:
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
            srcmap.append((curr_addr, 1, src))
            curr_addr += 1
            continue
        elif mnemonic == '.ASCIIZ':
            head, literal = split_asciiz(line)
            words = ascii_words(literal)
            instructions_pass1.append((mnemonic, [head, literal], curr_addr))
            srcmap.append((curr_addr, len(words), src))
            curr_addr += len(words)
            continue

        if mnemonic not in OPCODES:
            raise ValueError(f"Unknown mnemonic: {mnemonic}")

        entry = OPCODES[mnemonic]
        fmt = entry[1]
        words = 2 if fmt in ('LDI', 'JMP', 'CALL') else 1

        instructions_pass1.append((mnemonic, tokens[1:], curr_addr))
        srcmap.append((curr_addr, words, src))
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
        elif mnemonic == '.ASCIIZ':
            for i, w in enumerate(ascii_words(args[1])):
                memory_words[curr_addr + i] = w
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
            # The nine-bit immediate is two's complement, so both the unsigned
            # nine-bit form (0x000..0x1FF) and a plain negative number (-256..-1)
            # are accepted.  Anything else used to be masked silently, which
            # turned a typo like `ADDI R1, 0x0200` into `ADDI R1, 0x000`.
            rd = REGISTERS[args[0].upper()]
            value = parse_num(args[1], symbols)
            if value < -256 or value > 0x1FF:
                raise ValueError(
                    f"immediate out of range at 0x{curr_addr:04X}: {mnemonic} "
                    f"{args[1]} is {value}; the nine-bit immediate covers "
                    f"-256..255, written as 0x000..0x1FF")
            imm = value & 0x1FF
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
            delta = target - (curr_addr + 1)     # the CPU adds the offset to
                                                 # the already-incremented PC
            # The branch offset is only eight bits wide and signed: a target
            # further than 127 words away silently wrapped around in the past
            # and sent the CPU into unmapped memory.  Refuse to assemble it.
            if delta < -128 or delta > 127:
                raise ValueError(
                    f"branch out of range at 0x{curr_addr:04X}: {mnemonic} "
                    f"{args[0]} is {delta:+d} words away (limit -128..+127); "
                    f"use a near branch to a JMP trampoline instead")
            rel_offset = delta & 0xFF
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
            # CMP a, b  ->  A = Rd field, B = Rs1 field (see sv16_decoder.sv),
            # result = a - b, so a is the minuend.
            ra = REGISTERS[args[0].upper()]
            rb = REGISTERS[args[1].upper()]
            code = (opcode << 12) | (ra << 9) | (rb << 6)
            memory_words[curr_addr] = code

        elif fmt.startswith('S_'):
            code = 0x0000
            memory_words[curr_addr] = code

    return memory_words, srcmap

def write_listing(path, memory_words, srcmap):
    """Text listing: address, encoded word(s) and the source line."""
    by_line = {}
    for addr, count, src in srcmap:
        for i in range(count):
            by_line[addr + i] = (src, i)
    with open(path, 'w') as f:
        f.write(f"; SV-16 assembler listing -- {len(memory_words)} words\n")
        for addr in sorted(memory_words):
            val = memory_words[addr]
            src, idx = by_line.get(addr, ("", 0))
            tag = src if idx == 0 else f"(cont) {src}"
            f.write(f"{addr:04X}: {val:04X}  {tag}\n")


def write_hex(memory_words, outpath, depth=4096):
    """Write one hex word per line, starting at the lowest assembled address.

    Programs that start at 0 (application images) are padded to `depth` words
    as before.  Programs with a high origin (the ROM monitor at 0xE000) are
    emitted from that origin, which is exactly what `$readmemh` into
    sv16_rom's array expects.
    """
    with open(outpath, 'w') as f:
        base = min(memory_words.keys()) if memory_words else 0
        max_addr = max(memory_words.keys()) if memory_words else 0
        if base == 0:
            limit = max(max_addr + 1, depth)
        else:
            limit = max_addr + 1
        for a in range(base, limit):
            val = memory_words.get(a, 0x0000)
            f.write(f"{val:04X}\n")
    return base

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: sv16_as.py <input.s> <output.hex> [--listing <file>]")
        sys.exit(1)
    listing = None
    if '--listing' in sys.argv:
        i = sys.argv.index('--listing')
        listing = sys.argv[i + 1]
        del sys.argv[i:i + 2]
    with open(sys.argv[1], 'r') as f:
        lines = f.readlines()
    words, srcmap = assemble(lines)
    base = write_hex(words, sys.argv[2])
    top = max(words.keys()) if words else 0
    if listing:
        write_listing(listing, words, srcmap)
    print(f"[OK] Assembled {top - base + 1} words "
          f"(0x{base:04X}..0x{top:04X}) into {sys.argv[2]}")
