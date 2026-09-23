/*
 * SV-16 Rev A — Motor Control Application Firmware
 * Target: Real-world DC motor speed and direction control via PWM & H-Bridge
 * Flow:
 *   1. Initialize GPIO (LEDs and motor direction pins DIR1/DIR2)
 *   2. Initialize PWM to 20 kHz carrier frequency
 *   3. Spin motor forward, accelerate smoothly
 *   4. Hold steady speed
 *   5. Decelerate to stop
 *   6. Reverse direction and accelerate smoothly
 */

#include "../drivers/sv16_hardware.h"

int main(void) {
    // 1. Initialize GPIO (pins 0-3: LEDs, pins 4-5: motor direction outputs)
    gpio_init(0x003F);

    // 2. Initialize PWM carrier period (25 MHz clk / 1250 = 20.0 kHz ultrasonic PWM)
    pwm_motor_init(1250);

    // Turn on status LED 0 (active-low)
    gpio_set_bit(0);

    // 3. Set Motor Direction: Forward
    motor_set_direction(1);

    // Smooth acceleration forward: 0% to 80% duty cycle
    for (uint16_t duty = 0; duty <= 1000; duty += 10) {
        pwm_set_speed(duty);
        for (volatile int d = 0; d < 1000; d++); // Millisecond delay loop
    }

    // Steady state speed run
    for (volatile int d = 0; d < 50000; d++);

    // Decelerate to 0% duty
    for (uint16_t duty = 1000; duty > 0; duty -= 10) {
        pwm_set_speed(duty);
        for (volatile int d = 0; d < 1000; d++);
    }
    pwm_set_speed(0);

    // Dead-time pause before reversing H-Bridge
    motor_set_direction(0);
    for (volatile int d = 0; d < 5000; d++);

    // 4. Reverse direction
    motor_set_direction(-1);

    // Smooth acceleration reverse: 0% to 80% duty cycle
    for (uint16_t duty = 0; duty <= 1000; duty += 10) {
        pwm_set_speed(duty);
        for (volatile int d = 0; d < 1000; d++);
    }

    while (1) {
        // Continuous steady run
    }

    return 0;
}
