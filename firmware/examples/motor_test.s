; SV-16 Rev A Bootloader & Motor Control Test Program
; Target: SV-16 SoC on Lattice ECP5 FPGA

.ORG 0x0000
    ; 1. Initialize Stack Pointer is done in hardware (0x1FFE)
    ; 2. Configure GPIO Direction (0xF011): Pins 0-3 Output (LEDs), Pins 4-5 Output (DIR1, DIR2)
    LDI R0, 0xF011
    LDI R1, 0x003F
    STORE R1, [R0 + 0]

    ; 3. Turn on Status LED 0 (active-low LED -> write 1 to GPIO pin 0)
    LDI R0, 0xF010
    LDI R1, 0x0001
    STORE R1, [R0 + 0]

    ; 4. Initialize PWM carrier period (0xF030) = 1250 (20 kHz @ 25 MHz)
    LDI R0, 0xF030
    LDI R1, 1250
    STORE R1, [R0 + 0]

    ; 5. Set Motor Direction 1 (DIR1 = 1, DIR2 = 0)
    ; Bit 4 is DIR1 -> Set pin 4
    LDI R0, 0xF012      ; GPIO_SET
    LDI R1, 0x0010      ; Pin 4
    STORE R1, [R0 + 0]

    ; 6. Set PWM Duty Cycle (0xF031) = 625 (50% duty cycle)
    LDI R0, 0xF031
    LDI R1, 625
    STORE R1, [R0 + 0]

    ; 7. Enable PWM Controller (0xF032 = 1)
    LDI R0, 0xF032
    LDI R1, 1
    STORE R1, [R0 + 0]

    ; 8. Enter Heartbeat / Main Loop
main_loop:
    NOP
    NOP
    JMP main_loop
