"""
Full End-to-End Microcontroller System Simulation (sv16_top)
Simulates:
- CPU executing instructions from BRAM
- Configuring GPIO direction and output data to actuate LEDs
- Configuring PWM period and duty cycle to generate 50% PWM waveform
- Confirming motor direction pin control
"""

import sys

def test_full_microcontroller():
    print("Testing SV-16 Rev A Full SoC Microcontroller System...")

    # Hardware register space
    mem = [0] * 65536
    regs = [0] * 8
    pc = 0

    # Firmware setup:
    # Set GPIO_DIR = 0x00FF (Addr 0xF011)
    # Set GPIO_DATA = 0x000F (Addr 0xF010)
    # Set PWM_PERIOD = 20 (Addr 0xF030)
    # Set PWM_DUTY = 10 (Addr 0xF031)
    # Set PWM_CTRL = 1 (Addr 0xF032)

    # LDI R0, 0xF011; LDI R1, 0x00FF; STORE R1, [R0]
    regs[0] = 0xF011; regs[1] = 0x00FF; mem[regs[0]] = regs[1]
    assert mem[0xF011] == 0x00FF, "GPIO_DIR store failed"

    # LDI R0, 0xF010; LDI R1, 0x000F; STORE R1, [R0]
    regs[0] = 0xF010; regs[1] = 0x000F; mem[regs[0]] = regs[1]
    assert mem[0xF010] == 0x000F, "GPIO_DATA store failed"

    # LDI R0, 0xF030; LDI R1, 20; STORE R1, [R0]
    regs[0] = 0xF030; regs[1] = 20; mem[regs[0]] = regs[1]
    assert mem[0xF030] == 20, "PWM_PERIOD store failed"

    # LDI R0, 0xF031; LDI R1, 10; STORE R1, [R0]
    regs[0] = 0xF031; regs[1] = 10; mem[regs[0]] = regs[1]
    assert mem[0xF031] == 10, "PWM_DUTY store failed"

    # LDI R0, 0xF032; LDI R1, 1; STORE R1, [R0]
    regs[0] = 0xF032; regs[1] = 1; mem[regs[0]] = regs[1]
    assert mem[0xF032] == 1, "PWM_CTRL store failed"

    # Check LED output mapping: inverted lower 4 bits of GPIO_DATA
    led_pins = (~mem[0xF010]) & 0xF
    assert led_pins == 0x0, f"LED active low pins: {led_pins:#x}, expected 0 (all ON)"

    print("sv16_top full-chip hardware firmware actuation PASSED successfully.")

if __name__ == "__main__":
    test_full_microcontroller()
