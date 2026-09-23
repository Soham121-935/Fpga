/*
 * SV-16 Rev A — Low-Level Hardware Peripheral Header
 * Register definitions, peripheral base addresses, and hardware drivers
 */

#ifndef SV16_HARDWARE_H
#define SV16_HARDWARE_H

#include <stdint.h>

// Peripheral Base Addresses (Word Addresses)
#define GPIO_BASE   ((volatile uint16_t*)0xF010)
#define TIMER_BASE  ((volatile uint16_t*)0xF020)
#define PWM_BASE    ((volatile uint16_t*)0xF030)
#define UART_BASE   ((volatile uint16_t*)0xF040)

// GPIO Register Offsets
#define GPIO_DATA   (GPIO_BASE[0])
#define GPIO_DIR    (GPIO_BASE[1])
#define GPIO_SET    (GPIO_BASE[2])
#define GPIO_CLR    (GPIO_BASE[3])

// Timer 0 Register Offsets
#define TMR0_CNT    (TIMER_BASE[0])
#define TMR0_CMP    (TIMER_BASE[1])
#define TMR0_CTRL   (TIMER_BASE[2])
#define TMR0_STAT   (TIMER_BASE[3])

// PWM 0 Register Offsets
#define PWM0_PERIOD (PWM_BASE[0])
#define PWM0_DUTY   (PWM_BASE[1])
#define PWM0_CTRL   (PWM_BASE[2])
#define PWM0_STAT   (PWM_BASE[3])

// UART 0 Register Offsets
#define UART0_DATA  (UART_BASE[0])
#define UART0_STAT  (UART_BASE[1])
#define UART0_BAUD  (UART_BASE[2])
#define UART0_CTRL  (UART_BASE[3])

// --- High-Level Hardware Driver Functions ---

// GPIO Driver
static inline void gpio_init(uint16_t output_mask) {
    GPIO_DIR = output_mask;
}

static inline void gpio_write(uint16_t val) {
    GPIO_DATA = val;
}

static inline void gpio_set_bit(uint8_t pin) {
    GPIO_SET = (1 << pin);
}

static inline void gpio_clr_bit(uint8_t pin) {
    GPIO_CLR = (1 << pin);
}

// PWM Motor Control Driver
static inline void pwm_motor_init(uint16_t period) {
    PWM0_PERIOD = period;
    PWM0_DUTY   = 0; // Motor off initially
    PWM0_CTRL   = 1; // Enable PWM
}

static inline void pwm_set_speed(uint16_t duty) {
    PWM0_DUTY = duty;
}

static inline void motor_set_direction(int dir) {
    if (dir > 0) {
        gpio_set_bit(4); // DIR1 = 1
        gpio_clr_bit(5); // DIR2 = 0
    } else if (dir < 0) {
        gpio_clr_bit(4); // DIR1 = 0
        gpio_set_bit(5); // DIR2 = 1
    } else {
        gpio_clr_bit(4); // Coast / Brake
        gpio_clr_bit(5);
    }
}

// UART Driver
static inline void uart_putc(char c) {
    while (!(UART0_STAT & 1)); // Wait for TX_READY
    UART0_DATA = (uint16_t)c;
}

static inline void uart_puts(const char* s) {
    while (*s) {
        uart_putc(*s++);
    }
}

#endif // SV16_HARDWARE_H
