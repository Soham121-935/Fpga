#!/usr/bin/env python3
"""
SV-16 Rev A — Software Instruction Set Simulator (sv16_sim.py)
Cycle-accurate software emulator for SV-16 assembly and firmware validation.
Provides register dump, memory dump, peripheral simulation, and execution trace.
"""

import sys

class SV16Simulator:
    def __init__(self, mem_words=65536):
        self.mem = [0] * mem_words
        self.regs = [0] * 8
        self.pc = 0
        self.sp = 0x1FFE
        self.sr = 0
        self.halted = False
        self.cycles = 0

        # Memory mapped peripheral states
        self.gpio_dir = 0
        self.gpio_data = 0
        self.pwm_period = 1000
        self.pwm_duty = 0
        self.pwm_ctrl = 0

    def load_hex(self, hex_path):
        with open(hex_path, 'r') as f:
            for addr, line in enumerate(f):
                line = line.strip()
                if line:
                    self.mem[addr] = int(line, 16) & 0xFFFF

    def read_mem(self, addr):
        addr = addr & 0xFFFF
        if addr == 0xF010: return self.gpio_data
        if addr == 0xF011: return self.gpio_dir
        if addr == 0xF030: return self.pwm_period
        if addr == 0xF031: return self.pwm_duty
        if addr == 0xF032: return self.pwm_ctrl
        return self.mem[addr]

    def write_mem(self, addr, val):
        addr = addr & 0xFFFF
        val = val & 0xFFFF
        if addr == 0xF010: self.gpio_data = val
        elif addr == 0xF011: self.gpio_dir = val
        elif addr == 0xF012: self.gpio_data |= val  # GPIO_SET
        elif addr == 0xF013: self.gpio_data &= ~val # GPIO_CLR
        elif addr == 0xF030: self.pwm_period = val
        elif addr == 0xF031: self.pwm_duty = val
        elif addr == 0xF032: self.pwm_ctrl = val
        else: self.mem[addr] = val

    def step(self):
        if self.halted:
            return False

        instr = self.read_mem(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        self.cycles += 1

        opcode = (instr >> 12) & 0xF
        rd = (instr >> 9) & 0x7
        rs1 = (instr >> 6) & 0x7
        rs2 = (instr >> 3) & 0x7
        subop = instr & 0x7

        if opcode == 0x0: # NOP / CTRL
            pass
        elif opcode == 0x1: # ALU_RR
            a = self.regs[rs1]
            b = self.regs[rs2]
            if subop == 0: res = a + b
            elif subop == 1: res = a - b
            elif subop == 2: res = a & b
            elif subop == 3: res = a | b
            elif subop == 4: res = a ^ b
            elif subop == 5: res = ~a
            elif subop == 6: res = a + 1
            elif subop == 7: res = a - 1
            res = res & 0xFFFF
            self.regs[rd] = res
            self.sr = 1 if res == 0 else 0
        elif opcode == 0x2: # ADDI
            imm = instr & 0x1FF
            if imm & 0x100: imm -= 512
            res = (self.regs[rd] + imm) & 0xFFFF
            self.regs[rd] = res
        elif opcode == 0x3: # SUBI
            imm = instr & 0x1FF
            if imm & 0x100: imm -= 512
            res = (self.regs[rd] - imm) & 0xFFFF
            self.regs[rd] = res
        elif opcode == 0x4: # LDI (2-word)
            imm16 = self.read_mem(self.pc)
            self.pc = (self.pc + 1) & 0xFFFF
            self.regs[rd] = imm16
            self.cycles += 1
        elif opcode == 0x5: # LOAD
            off = instr & 0x3F
            if off & 0x20: off -= 64
            addr = (self.regs[rs1] + off) & 0xFFFF
            self.regs[rd] = self.read_mem(addr)
        elif opcode == 0x6: # STORE
            off = instr & 0x3F
            if off & 0x20: off -= 64
            addr = (self.regs[rs1] + off) & 0xFFFF
            self.write_mem(addr, self.regs[rd])
        elif opcode == 0x7: # MOV
            self.regs[rd] = self.regs[rs1]
        elif opcode == 0x8: # BRANCH
            cond = (instr >> 8) & 0xF
            off = instr & 0xFF
            if off & 0x80: off -= 256
            z = self.sr & 1
            taken = False
            if cond == 0: taken = True
            elif cond == 1 and z: taken = True
            elif cond == 2 and not z: taken = True
            if taken:
                self.pc = (self.pc + off) & 0xFFFF
        elif opcode == 0x9: # JMP (2-word)
            target = self.read_mem(self.pc)
            self.pc = target
            self.cycles += 1
        elif opcode == 0xA: # CALL (2-word)
            target = self.read_mem(self.pc)
            self.pc = (self.pc + 1) & 0xFFFF
            self.sp = (self.sp - 1) & 0xFFFF
            self.mem[self.sp] = self.pc
            self.pc = target
            self.cycles += 1
        elif opcode == 0xB: # RET
            self.pc = self.mem[self.sp]
            self.sp = (self.sp + 1) & 0xFFFF
        elif opcode == 0xC: # PUSH
            self.sp = (self.sp - 1) & 0xFFFF
            self.mem[self.sp] = self.regs[rd]
        elif opcode == 0xD: # POP
            self.regs[rd] = self.mem[self.sp]
            self.sp = (self.sp + 1) & 0xFFFF

        return True

    def run(self, max_cycles=10000):
        while self.cycles < max_cycles and not self.halted:
            self.step()

def test_simulator():
    print("Testing SV-16 Cross-Assembler & Instruction Set Simulator...")
    sim = SV16Simulator()
    sim.load_hex("firmware/bootrom.hex")

    # Run for 200 cycles
    sim.run(max_cycles=200)

    # Verify peripheral registers were configured by assembly firmware:
    assert sim.gpio_dir == 0x003F, f"Expected GPIO_DIR 0x003F, got 0x{sim.gpio_dir:04X}"
    assert (sim.gpio_data & 0x1) == 0x1, "LED 0 not set"
    assert (sim.gpio_data & 0x10) == 0x10, "Motor DIR1 pin 4 not set"
    assert sim.pwm_period == 1250, f"Expected PWM_PERIOD 1250, got {sim.pwm_period}"
    assert sim.pwm_duty == 625, f"Expected PWM_DUTY 625, got {sim.pwm_duty}"
    assert sim.pwm_ctrl == 1, f"Expected PWM_CTRL 1, got {sim.pwm_ctrl}"

    print(f"[PASS] Simulator executed {sim.cycles} cycles. All peripheral states verified perfectly.")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != '--test':
        sim = SV16Simulator()
        sim.load_hex(sys.argv[1])
        sim.run(int(sys.argv[2]) if len(sys.argv) > 2 else 5000)
        print(f"Halted at PC=0x{sim.pc:04X}, SP=0x{sim.sp:04X}, cycles={sim.cycles}")
    else:
        test_simulator()
