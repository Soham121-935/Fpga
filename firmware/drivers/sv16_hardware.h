/*
 * SV-16 Rev B — low-level hardware definition header
 * ==================================================
 *
 * Single source of truth for the Rev B register map, bit fields, peripheral
 * addresses and the firmware image header, for C firmware and for hand-written
 * assembly (the constants are just as useful with `#include`-style grep).
 *
 * Two notes before you use it:
 *
 *   1. There is no C compiler for SV-16 yet (see docs/MCU_READINESS.md). The
 *      supported toolchain is scripts/sv16_as.py; this header documents the
 *      machine for that assembler and is ready for a future C backend.
 *   2. All MMIO addresses are **word** addresses, and the bus is 16-bit. Read
 *      and write one 16-bit word at a time; there are no byte accesses.
 *
 * Register layouts are authoritative in docs/PERIPHERALS.md and
 * docs/MEMORY_MAP.md; if the two ever disagree, the RTL and those documents win.
 */

#ifndef SV16_HARDWARE_H
#define SV16_HARDWARE_H

#include <stdint.h>

/* ------------------------------------------------------------------ memory */
#define SV16_SRAM_BASE   0x0000u   /* 16 K words, code + data + stack          */
#define SV16_SRAM_WORDS  16384u
#define SV16_ROM_BASE    0xE000u   /* 2 K words, resident monitor              */
#define SV16_ROM_WORDS   2048u
#define SV16_MMIO_BASE   0xF000u
#define SV16_MMIO_LAST   0xF0FFu

/* Interrupt vector table: one 16-bit handler address per source, in SRAM. */
#define SV16_VEC_BASE    0x0020u
#define SV16_VEC(i)      (*(volatile uint16_t *)(SV16_VEC_BASE + (i)))

#define SV16_IRQ_TIMER0  0
#define SV16_IRQ_UART_RX 1
#define SV16_IRQ_UART_TX 2
#define SV16_IRQ_SPI0    3
#define SV16_IRQ_FLASH   4
#define SV16_IRQ_GPIO    5
#define SV16_IRQ_WDT     6
#define SV16_IRQ_TRAP    7
#define SV16_IRQ_COUNT   8

/* Reset-time defaults (see rtl/sv16_top.sv / sv16_startup.sv). */
#define SV16_RESET_SP    0x3FFEu
#define SV16_RESET_PC    0xE000u   /* monitor: entered when no image is booted */

/* ------------------------------------------------------------------- helpers */
#define SV16_REG16(addr) (*(volatile uint16_t *)(addr))
#define SV16_BIT(n)      ((uint16_t)(1u << (n)))

/* MMIO block access: block index b (0..15), register r (0..15). */
#define SV16_MMIO(b, r)  SV16_REG16(SV16_MMIO_BASE + ((b) << 4) + (r))

#define SV16_BLK_SYS    0
#define SV16_BLK_GPIO0  1
#define SV16_BLK_TIMER0 2
#define SV16_BLK_PWM0   3
#define SV16_BLK_UART0  4
#define SV16_BLK_SPI0   5
#define SV16_BLK_FLASH  6
#define SV16_BLK_GPIO1  7
#define SV16_BLK_WDT    8   /* reserved: not instantiated in Rev B */
#define SV16_BLK_IRQ    9
#define SV16_BLK_BOOT   10

/* ------------------------------------------------------- system control 0xF0 */
#define SYS_ID         SV16_MMIO(SV16_BLK_SYS, 0)   /* RO: 0x1602 */
#define SYS_CTRL       SV16_MMIO(SV16_BLK_SYS, 1)
#define SYS_STAT       SV16_MMIO(SV16_BLK_SYS, 2)   /* RO */
#define SYS_RSTCAUSE   SV16_MMIO(SV16_BLK_SYS, 3)   /* RW1C */
#define SYS_DBG_PC     SV16_MMIO(SV16_BLK_SYS, 4)   /* RO */
#define SYS_DBG_SP     SV16_MMIO(SV16_BLK_SYS, 5)   /* RO */
#define SYS_DBG_SR     SV16_MMIO(SV16_BLK_SYS, 6)   /* RO */
#define SYS_DBG_IR     SV16_MMIO(SV16_BLK_SYS, 7)   /* RO */
#define SYS_FAULT_ADDR SV16_MMIO(SV16_BLK_SYS, 8)   /* RO */
#define SYS_FAULT_CNT  SV16_MMIO(SV16_BLK_SYS, 9)
#define SYS_TICKS_LO   SV16_MMIO(SV16_BLK_SYS, 10)  /* RO */
#define SYS_TICKS_HI   SV16_MMIO(SV16_BLK_SYS, 11)  /* RO */
#define SYS_CPU_STATE  SV16_MMIO(SV16_BLK_SYS, 12)  /* RO */
#define SYS_MEMCFG     SV16_MMIO(SV16_BLK_SYS, 13)  /* RO */
#define SYS_SCRATCH0   SV16_MMIO(SV16_BLK_SYS, 14)  /* survives a soft reset */
#define SYS_SCRATCH1   SV16_MMIO(SV16_BLK_SYS, 15)

/* SYS_CTRL bits; bits [15:8] must be the key to change bits [15:4]. */
#define SYS_CTRL_SOFTRST   SV16_BIT(0)   /* restart the boot sequence */
#define SYS_CTRL_HALT      SV16_BIT(1)   /* stop the CPU at an instruction boundary */
#define SYS_CTRL_STEP      SV16_BIT(2)   /* execute one instruction while halted */
#define SYS_CTRL_IRQEN     SV16_BIT(3)   /* 0 = inhibit all interrupts at the system level */
#define SYS_CTRL_RAMREMAP  SV16_BIT(4)   /* defined, not implemented in Rev B */
#define SYS_CTRL_RESERVED  SV16_BIT(15)
#define SYS_CTRL_KEY       0xA500u       /* OR into a write to change bits [15:4] */

/* SYS_STAT bits */
#define SYS_STAT_HALTED       SV16_BIT(0)
#define SYS_STAT_STEP_TAKEN   SV16_BIT(1)
#define SYS_STAT_IMAGE_OK     SV16_BIT(2)
#define SYS_STAT_BOOT_FAIL    SV16_BIT(3)
#define SYS_STAT_ROM_MONITOR  SV16_BIT(4)
#define SYS_STAT_FLASH_OK     SV16_BIT(5)
#define SYS_STAT_FAULT_HALT   SV16_BIT(6)
#define SYS_STAT_ILLEGAL_SEEN SV16_BIT(7)

/* SYS_RSTCAUSE bits (write 1s to clear) */
#define RSTCAUSE_PIN      SV16_BIT(0)
#define RSTCAUSE_SOFT     SV16_BIT(1)
#define RSTCAUSE_FAULT    SV16_BIT(2)
#define RSTCAUSE_WDT      SV16_BIT(3)   /* reserved until the WDT is wired */
#define RSTCAUSE_BOOTFAIL SV16_BIT(4)
#define RSTCAUSE_FLASHOK  SV16_BIT(5)

/* ----------------------------------------------------------------- GPIO 0xF010 / 0xF070 */
#define GPIO0_DATA SV16_MMIO(SV16_BLK_GPIO0, 0)
#define GPIO0_DIR  SV16_MMIO(SV16_BLK_GPIO0, 1)
#define GPIO0_SET  SV16_MMIO(SV16_BLK_GPIO0, 2)   /* write: data |= mask */
#define GPIO0_CLR  SV16_MMIO(SV16_BLK_GPIO0, 3)   /* write: data &= ~mask */

#define GPIO1_DATA SV16_MMIO(SV16_BLK_GPIO1, 0)
#define GPIO1_DIR  SV16_MMIO(SV16_BLK_GPIO1, 1)
#define GPIO1_SET  SV16_MMIO(SV16_BLK_GPIO1, 2)
#define GPIO1_CLR  SV16_MMIO(SV16_BLK_GPIO1, 3)

/* ----------------------------------------------------------------- Timer 0xF020 */
#define TMR0_CNT  SV16_MMIO(SV16_BLK_TIMER0, 0)
#define TMR0_CMP  SV16_MMIO(SV16_BLK_TIMER0, 1)
#define TMR0_CTRL SV16_MMIO(SV16_BLK_TIMER0, 2)
#define TMR0_STAT SV16_MMIO(SV16_BLK_TIMER0, 3)   /* RW1C: match flag */

#define TMR0_CTRL_ENABLE   SV16_BIT(0)
#define TMR0_CTRL_AUTOLOAD SV16_BIT(1)
#define TMR0_CTRL_IRQ      SV16_BIT(2)
#define TMR0_STAT_MATCH    SV16_BIT(0)

/* ------------------------------------------------------------------- PWM 0xF030 */
#define PWM0_PERIOD SV16_MMIO(SV16_BLK_PWM0, 0)
#define PWM0_DUTY   SV16_MMIO(SV16_BLK_PWM0, 1)
#define PWM0_CTRL   SV16_MMIO(SV16_BLK_PWM0, 2)
#define PWM0_STAT   SV16_MMIO(SV16_BLK_PWM0, 3)   /* RW1C: fault flag */

#define PWM0_CTRL_ENABLE SV16_BIT(0)
#define PWM0_CTRL_INVERT SV16_BIT(1)
#define PWM0_CTRL_FAULT  SV16_BIT(2)   /* enable the motor_fault_n shutdown input */
#define PWM0_STAT_FAULT  SV16_BIT(0)

/* Board wiring: pwm_out drives the motor driver, motor_fault_n is its nFAULT. */
#define MOTOR_DIR1  SV16_BIT(0)        /* GPIOA bit, see the LPF */
#define MOTOR_DIR2  SV16_BIT(1)
#define MOTOR_FAULT_N_PIN_ACTIVE_LOW 1

/* ------------------------------------------------------------------ UART 0xF040 */
#define UART0_DATA   SV16_MMIO(SV16_BLK_UART0, 0)
#define UART0_STATUS SV16_MMIO(SV16_BLK_UART0, 1)
#define UART0_BAUD   SV16_MMIO(SV16_BLK_UART0, 2)
#define UART0_CTRL   SV16_MMIO(SV16_BLK_UART0, 3)
#define UART0_FIFO   SV16_MMIO(SV16_BLK_UART0, 4)

#define UART0_TX_READY  SV16_BIT(0)
#define UART0_RX_READY  SV16_BIT(1)
#define UART0_TX_FULL   SV16_BIT(2)
#define UART0_RX_EMPTY  SV16_BIT(3)
#define UART0_RX_OVERRUN SV16_BIT(4)
#define UART0_TX_IRQ    SV16_BIT(5)
#define UART0_RX_IRQ    SV16_BIT(6)

#define UART0_CTRL_TXEN   SV16_BIT(0)
#define UART0_CTRL_RXEN   SV16_BIT(1)
#define UART0_CTRL_TXIRQ  SV16_BIT(2)
#define UART0_CTRL_RXIRQ  SV16_BIT(3)

/* The reset divisor is derived from the SoC clock: 217 at 25 MHz, 108 at
 * 12.5 MHz, both = 115200 8-N-1.  Only write UART0_BAUD if you want a
 * different rate; values below 4 are clamped. */
#define UART0_BAUD_115200_AT_25MHZ   217u
#define UART0_BAUD_115200_AT_12_5MHZ 108u

/* ------------------------------------------------------------------- SPI 0xF050 */
#define SPI0_DATA   SV16_MMIO(SV16_BLK_SPI0, 0)
#define SPI0_STATUS SV16_MMIO(SV16_BLK_SPI0, 1)
#define SPI0_CTRL   SV16_MMIO(SV16_BLK_SPI0, 2)
#define SPI0_DIV    SV16_MMIO(SV16_BLK_SPI0, 3)

#define SPI0_BUSY     SV16_BIT(0)
#define SPI0_RX_READY SV16_BIT(1)
#define SPI0_TX_READY SV16_BIT(2)
#define SPI0_CS_N     SV16_BIT(3)

#define SPI0_CTRL_ENABLE SV16_BIT(0)
#define SPI0_CTRL_CS_HW  SV16_BIT(1)
#define SPI0_CTRL_CPOL   SV16_BIT(2)
#define SPI0_CTRL_CPHA   SV16_BIT(3)

/* -------------------------------------------------------- Flash controller 0xF060 */
#define FLASH_CMD     SV16_MMIO(SV16_BLK_FLASH, 0)
#define FLASH_STAT    SV16_MMIO(SV16_BLK_FLASH, 1)   /* RO */
#define FLASH_ADDR_LO SV16_MMIO(SV16_BLK_FLASH, 2)
#define FLASH_ADDR_HI SV16_MMIO(SV16_BLK_FLASH, 3)
#define FLASH_LEN     SV16_MMIO(SV16_BLK_FLASH, 4)
#define FLASH_DATA    SV16_MMIO(SV16_BLK_FLASH, 5)
#define FLASH_ID      SV16_MMIO(SV16_BLK_FLASH, 6)   /* RO */
#define FLASH_ID2     SV16_MMIO(SV16_BLK_FLASH, 7)   /* RO */
#define FLASH_CRC_LO  SV16_MMIO(SV16_BLK_FLASH, 8)   /* RO */
#define FLASH_CRC_HI  SV16_MMIO(SV16_BLK_FLASH, 9)   /* RO */
#define FLASH_CTRL    SV16_MMIO(SV16_BLK_FLASH, 10)
#define FLASH_WRCNT   SV16_MMIO(SV16_BLK_FLASH, 11)  /* RO */
#define FLASH_SR      SV16_MMIO(SV16_BLK_FLASH, 12)  /* RO */
#define FLASH_TOTAL   SV16_MMIO(SV16_BLK_FLASH, 13)  /* RO */

#define FLASH_SECTOR_BYTES 4096u
#define FLASH_PAGE_BYTES    256u

/* FLASH_CMD codes */
#define FCMD_NOP         0u
#define FCMD_READ_ID     1u
#define FCMD_READ_START  2u
#define FCMD_WRITE_START 3u
#define FCMD_FLUSH       4u
#define FCMD_ERASE_SECT  5u
#define FCMD_ERASE_CHIP  6u   /* destructive, takes seconds */
#define FCMD_CRC_START   7u
#define FCMD_READ_SR     8u
#define FCMD_WR_ENABLE   9u
#define FCMD_WR_DISABLE  10u
#define FCMD_RELEASE     11u

/* FLASH_STAT bits */
#define FLASH_ST_WIP        SV16_BIT(0)
#define FLASH_ST_CRC_READY  SV16_BIT(1)
#define FLASH_ST_PGM_BUSY   SV16_BIT(2)
#define FLASH_ST_WEL        SV16_BIT(3)
#define FLASH_ST_RX_READY   SV16_BIT(4)
#define FLASH_ST_ID_OK      SV16_BIT(5)
#define FLASH_ST_ERROR      SV16_BIT(6)
#define FLASH_ST_BUSY       SV16_BIT(7)

#define FLASH_EXPECTED_ID 0xEF4018u   /* W25Q-class 8 Mbit part */

/* ------------------------------------------------------- Interrupt controller 0xF090 */
#define IRQ_EN    SV16_MMIO(SV16_BLK_IRQ, 0)
#define IRQ_PEND  SV16_MMIO(SV16_BLK_IRQ, 1)   /* RW1C */
#define IRQ_LINES SV16_MMIO(SV16_BLK_IRQ, 2)   /* RO */
#define IRQ_PRIO  SV16_MMIO(SV16_BLK_IRQ, 3)   /* RO */

/* ---------------------------------------------------------------- Boot engine 0xF0A0 */
#define BOOT_CTRL    SV16_MMIO(SV16_BLK_BOOT, 0)
#define BOOT_STAT    SV16_MMIO(SV16_BLK_BOOT, 1)   /* RO */
#define BOOT_SRC_LO  SV16_MMIO(SV16_BLK_BOOT, 2)
#define BOOT_SRC_HI  SV16_MMIO(SV16_BLK_BOOT, 3)
#define BOOT_SRC_LEN SV16_MMIO(SV16_BLK_BOOT, 4)
#define BOOT_ENTRY   SV16_MMIO(SV16_BLK_BOOT, 5)   /* RO */
#define BOOT_STACK   SV16_MMIO(SV16_BLK_BOOT, 6)   /* RO */
#define BOOT_WORDS   SV16_MMIO(SV16_BLK_BOOT, 7)   /* RO */
#define BOOT_CRC_EXP SV16_MMIO(SV16_BLK_BOOT, 8)   /* RO */
#define BOOT_CRC_ACT SV16_MMIO(SV16_BLK_BOOT, 9)   /* RO */
#define BOOT_ERR     SV16_MMIO(SV16_BLK_BOOT, 10)  /* RW1C */
#define BOOT_MAGIC   SV16_MMIO(SV16_BLK_BOOT, 11)  /* RO */
#define BOOT_HDRVER  SV16_MMIO(SV16_BLK_BOOT, 12)  /* RO */
#define BOOT_NAME0   SV16_MMIO(SV16_BLK_BOOT, 13)  /* RO */
#define BOOT_NAME1   SV16_MMIO(SV16_BLK_BOOT, 14)  /* RO */
#define BOOT_NAME2   SV16_MMIO(SV16_BLK_BOOT, 15)  /* RO */

#define BOOT_CTRL_START       SV16_BIT(0)   /* latched, self-clearing */
#define BOOT_CTRL_ABORT       SV16_BIT(1)
#define BOOT_CTRL_VERIFY_ONLY SV16_BIT(2)   /* validate but do not hand over */
#define BOOT_CTRL_AUTO        SV16_BIT(3)   /* boot from flash on every reset */

#define BOOT_STAT_BUSY     SV16_BIT(0)
#define BOOT_STAT_OK       SV16_BIT(1)
#define BOOT_STAT_FAIL     SV16_BIT(2)
#define BOOT_STAT_CRC_OK   SV16_BIT(3)
#define BOOT_STAT_MAGIC_OK SV16_BIT(4)

/* BOOT_ERR codes (same numbering as the monitor's -E replies) */
#define BOOT_ERR_NONE     0x00u
#define BOOT_ERR_MAGIC    0x01u
#define BOOT_ERR_HDRCRC   0x02u
#define BOOT_ERR_PLDCRC   0x03u
#define BOOT_ERR_TIMEOUT  0x04u
#define BOOT_ERR_LENGTH   0x05u
#define BOOT_ERR_FLASH    0x06u
#define BOOT_ERR_VERIFY   0x07u

/* ---------------------------------------------------------------------------------
 * Firmware image header (see docs/BOOT_AND_PROGRAMMING.md, section 4).
 * Produced by scripts/sv16_fwpack.py; the boot loader validates it before the
 * CPU is released.
 * --------------------------------------------------------------------------------- */
#define SV16_IMG_MAGIC      0x36315653u  /* 'S','V','1','6' little endian */
#define SV16_IMG_HDR_VERSION 0x0001u
#define SV16_IMG_HDR_BYTES   0x20u
#define SV16_IMG_HDR_CRC_LEN 0x14u

typedef struct {
    uint32_t magic;        /* 0x00 */
    uint16_t hdr_version;  /* 0x04 */
    uint16_t words;        /* 0x06: payload length in words */
    uint8_t  name[8];      /* 0x08 */
    uint16_t entry;        /* 0x10: entry word address */
    uint16_t sp;           /* 0x12: initial stack pointer (0 = SV16_RESET_SP) */
    uint16_t hdr_crc;      /* 0x14: CRC16 over bytes 0x00-0x13 */
    uint16_t payload_crc;  /* 0x16: CRC16 over the payload bytes */
    uint16_t reserved[4];  /* 0x18 */
    /* payload follows at 0x20, little-endian 16-bit words */
} sv16_image_header_t;

/* CRC16-CCITT used by the loader, the monitor and the image format
 * (poly 0x1021, init 0xFFFF, no reflection, no final XOR). */
static inline uint16_t sv16_crc16(const uint8_t *data, uint16_t len,
                                  uint16_t crc)
{
    for (uint16_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (int bit = 0; bit < 8; bit++) {
            crc = (crc & 0x8000u) ? (uint16_t)((crc << 1) ^ 0x1021u)
                                  : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

/* ------------------------------------------------------------- tiny helpers */

static inline void sv16_gpio_out(uint16_t dir, uint16_t value)
{
    GPIO0_DIR = dir;
    GPIO0_DATA = value;
}

static inline void sv16_uart_putc(uint16_t c)
{
    while (!(UART0_STATUS & UART0_TX_READY)) {
        /* wait for room in the TX FIFO */
    }
    UART0_DATA = c;
}

static inline uint16_t sv16_uart_getc(void)
{
    while (!(UART0_STATUS & UART0_RX_READY)) {
        /* wait for a byte */
    }
    return UART0_DATA;
}

/* Ask the hardware boot loader to load the image at `src` (flash byte address)
 * and hand over.  Returns 0 on success, or the BOOT_ERR code. */
static inline uint16_t sv16_boot_image(uint32_t src)
{
    BOOT_SRC_LO = (uint16_t)(src & 0xFFFFu);
    BOOT_SRC_HI = (uint16_t)((src >> 16) & 0xFFu);
    BOOT_CTRL = BOOT_CTRL_START;
    while (BOOT_STAT & BOOT_STAT_BUSY) {
        /* the loader streams the image while we wait */
    }
    if (BOOT_STAT & BOOT_STAT_OK) {
        return BOOT_ERR_NONE;
    }
    return (uint16_t)(BOOT_ERR & 0xFFu);
}

#endif /* SV16_HARDWARE_H */
