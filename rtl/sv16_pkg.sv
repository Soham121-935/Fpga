// SV-16 Rev B — SystemVerilog Package Definitions
// Contains shared constants, types, opcodes, flag indices, memory map and
// interrupt vector assignments used by the CPU, the bus fabric and peripherals.
//
// Revision history:
//   Rev A: baseline opcodes / flags
//   Rev B: adds CTRL sub-opcodes (HALT/EI/DI/RETI), interrupt vector indices,
//          the Rev B memory map (32 KB SRAM, 4 KB boot ROM, 16x MMIO blocks)

package sv16_pkg;

    // ---------------------------------------------------------------- widths
    localparam int DATA_WIDTH    = 16;
    localparam int ADDR_WIDTH    = 16;
    localparam int REG_ADDR_W    = 3;
    localparam int NUM_GPRS      = 8;

    // ------------------------------------------------- Status Register (SR)
    localparam int FLAG_Z_BIT    = 0; // Zero flag
    localparam int FLAG_C_BIT    = 1; // Carry / Borrow flag
    localparam int FLAG_N_BIT    = 2; // Negative / Sign flag
    localparam int FLAG_V_BIT    = 3; // Signed Overflow flag
    localparam int FLAG_IE_BIT   = 7; // Global Interrupt Enable

    // ------------------------------------------------------ Primary Opcodes
    typedef enum logic [3:0] {
        OP_CTRL      = 4'h0, // NOP, HALT, EI, DI, RETI
        OP_ALU_RR    = 4'h1, // Register-Register ALU Operations
        OP_ADDI      = 4'h2, // Add Immediate
        OP_SUBI      = 4'h3, // Subtract Immediate
        OP_LDI       = 4'h4, // Load 16-bit Immediate (2-word)
        OP_LOAD      = 4'h5, // Memory Load
        OP_STORE     = 4'h6, // Memory Store
        OP_MOV       = 4'h7, // Register Move
        OP_BRANCH    = 4'h8, // Conditional Branch
        OP_JMP       = 4'h9, // Unconditional Jump (2-word)
        OP_CALL      = 4'hA, // Call Subroutine (2-word)
        OP_RET       = 4'hB, // Return from Subroutine
        OP_PUSH      = 4'hC, // Push to Stack
        OP_POP       = 4'hD, // Pop from Stack
        OP_CMP       = 4'hE, // Compare Registers
        OP_EXT_ALU   = 4'hF  // Extended ALU (MUL, DIV, SHL, SHR)
    } opcode_e;

    // -------------------------------------------------- CTRL sub-opcodes
    // Format S, opcode 0x0, sub-opcode field instr[8:0]
    typedef enum logic [8:0] {
        CTRL_NOP     = 9'h000, // No operation
        CTRL_HALT    = 9'h001, // Stop the core until an interrupt or reset
        CTRL_EI      = 9'h002, // Set SR.IE (enable interrupts)
        CTRL_DI      = 9'h003, // Clear SR.IE (disable interrupts)
        CTRL_RETI    = 9'h004  // Return from interrupt: pop PC and SR
    } ctrl_subop_e;

    // ------------------------------------------------- Standard ALU subops
    typedef enum logic [2:0] {
        ALU_ADD      = 3'h0,
        ALU_SUB      = 3'h1,
        ALU_AND      = 3'h2,
        ALU_OR       = 3'h3,
        ALU_XOR      = 3'h4,
        ALU_NOT      = 3'h5,
        ALU_INC      = 3'h6,
        ALU_DEC      = 3'h7
    } alu_subop_e;

    // ------------------------------------------------- Extended ALU subops
    typedef enum logic [2:0] {
        EXT_SHL      = 3'h0,
        EXT_SHR      = 3'h1,
        EXT_MUL      = 3'h2,
        EXT_DIV      = 3'h3,
        EXT_MOD      = 3'h4
    } ext_subop_e;

    // -------------------------------------------------------- Branch conds
    typedef enum logic [3:0] {
        COND_BRA     = 4'h0,
        COND_BEQ     = 4'h1,
        COND_BNE     = 4'h2,
        COND_BC      = 4'h3,
        COND_BNC     = 4'h4,
        COND_BN      = 4'h5,
        COND_BP      = 4'h6,
        COND_BVS     = 4'h7,
        COND_BVC     = 4'h8,
        COND_BLT     = 4'h9,
        COND_BGE     = 4'hA,
        COND_BLE     = 4'hB,
        COND_BGT     = 4'hC
    } branch_cond_e;

    // --------------------------------------------------- Memory map (Rev B)
    // 0x0000 - 0x3FFF : Internal SRAM, 16K words (32 KB) : code + data + stack
    // 0x4000 - 0xDFFF : Reserved (bus fault is logged, reads return 0)
    // 0xE000 - 0xE7FF : Boot ROM, 2K words (4 KB) — immutable monitor firmware
    // 0xE800 - 0xEFFF : Reserved
    // 0xF000 - 0xF0FF : Memory mapped peripherals (16 blocks x 16 registers)
    localparam logic [15:0] RAM_BASE      = 16'h0000;
    localparam int          RAM_WORDS     = 16384;             // 16K words = 32 KB
    localparam logic [15:0] RAM_LAST      = 16'h3FFF;
    localparam int          RAM_ADDR_W    = 14;

    localparam logic [15:0] ROM_BASE      = 16'hE000;
    localparam int          ROM_WORDS     = 2048;              // 2K words = 4 KB
    localparam logic [15:0] ROM_LAST      = 16'hE7FF;
    localparam int          ROM_ADDR_W    = 11;

    localparam logic [15:0] MMIO_BASE     = 16'hF000;
    localparam logic [15:0] MMIO_LAST     = 16'hF0FF;

    // MMIO block select: addr[7:4] within the 0xF000 page
    localparam logic [3:0] BLK_SYS       = 4'h0; // 0xF000 System control
    localparam logic [3:0] BLK_GPIO0     = 4'h1; // 0xF010 GPIO port A
    localparam logic [3:0] BLK_TIMER0    = 4'h2; // 0xF020 Timer 0
    localparam logic [3:0] BLK_PWM0      = 4'h3; // 0xF030 PWM 0
    localparam logic [3:0] BLK_UART0     = 4'h4; // 0xF040 UART 0
    localparam logic [3:0] BLK_SPI0      = 4'h5; // 0xF050 SPI 0 (generic master)
    localparam logic [3:0] BLK_FLASH     = 4'h6; // 0xF060 SPI flash controller
    localparam logic [3:0] BLK_GPIO1     = 4'h7; // 0xF070 GPIO port B
    localparam logic [3:0] BLK_WDT       = 4'h8; // 0xF080 Watchdog
    localparam logic [3:0] BLK_IRQ       = 4'h9; // 0xF090 Interrupt controller
    localparam logic [3:0] BLK_BOOT      = 4'hA; // 0xF0A0 Boot loader engine
    localparam logic [3:0] BLK_SPARE0    = 4'hB; // 0xF0B0 reserved
    localparam logic [3:0] BLK_SPARE1    = 4'hC; // 0xF0C0 reserved
    localparam logic [3:0] BLK_SPARE2    = 4'hD; // 0xF0D0 reserved
    localparam logic [3:0] BLK_SPARE3    = 4'hE; // 0xF0E0 reserved
    localparam logic [3:0] BLK_SPARE4    = 4'hF; // 0xF0F0 reserved

    // ------------------------------------------- Interrupt vector indices
    // The vector table lives at IRQ_VEC_BASE in SRAM; entry i holds the
    // 16-bit handler address for interrupt source i. Firmware populates it.
    localparam logic [15:0] IRQ_VEC_BASE  = 16'h0020;
    localparam logic [3:0]  IRQ_TIMER0    = 4'd0;
    localparam logic [3:0]  IRQ_UART0_RX  = 4'd1;
    localparam logic [3:0]  IRQ_UART0_TX  = 4'd2;
    localparam logic [3:0]  IRQ_SPI0      = 4'd3;
    localparam logic [3:0]  IRQ_FLASH     = 4'd4;
    localparam logic [3:0]  IRQ_GPIO      = 4'd5;
    localparam logic [3:0]  IRQ_WDT       = 4'd6;
    localparam logic [3:0]  IRQ_TRAP      = 4'd7; // illegal opcode / exception
    localparam int          IRQ_SOURCES   = 8;
    localparam int          IRQ_IDX_W     = 3;

    // ------------------------------------------------ System control regs
    localparam logic [3:0] SYS_ID        = 4'h0;
    localparam logic [3:0] SYS_CTRL      = 4'h1;
    localparam logic [3:0] SYS_STAT      = 4'h2;
    localparam logic [3:0] SYS_RSTCAUSE  = 4'h3;
    localparam logic [3:0] SYS_DBG_PC    = 4'h4;
    localparam logic [3:0] SYS_DBG_SP    = 4'h5;
    localparam logic [3:0] SYS_DBG_SR    = 4'h6;
    localparam logic [3:0] SYS_DBG_IR    = 4'h7;
    localparam logic [3:0] SYS_FAULT_ADDR= 4'h8;
    localparam logic [3:0] SYS_FAULT_CNT = 4'h9;
    localparam logic [3:0] SYS_TICKS_LO  = 4'hA; // free-running cycle counter
    localparam logic [3:0] SYS_TICKS_HI  = 4'hB;
    localparam logic [3:0] SYS_CPU_STATE = 4'hC; // {core FSM state, halted}
    localparam logic [3:0] SYS_MEMCFG    = 4'hD; // RAM/ROM size codes
    localparam logic [3:0] SYS_SCRATCH0  = 4'hE; // survive a soft reset
    localparam logic [3:0] SYS_SCRATCH1  = 4'hF;

    // SYS_ID value: [15:8] = 0x16 family id, [7:4] = major, [3:0] = minor
    localparam logic [15:0] SV16_ID      = 16'h1602;

    // SYS_CTRL bits
    localparam int SYS_CTRL_SOFTRST_BIT = 0;  // 1 = restart boot sequence
    localparam int SYS_CTRL_HALT_BIT    = 1;  // 1 = halt the CPU (debug)
    localparam int SYS_CTRL_STEP_BIT    = 2;  // 1 = single step while halted
    localparam int SYS_CTRL_IRQEN_BIT   = 3;  // 0 = force global IRQ inhibit
    localparam int SYS_CTRL_RAMREMAP_BIT= 4;  // 0 = ROM@0xE000 view (default)

    // SYS_RSTCAUSE bits
    localparam int RSTCAUSE_POR_BIT     = 0;  // external reset pin
    localparam int RSTCAUSE_SOFT_BIT    = 1;  // SYS_CTRL.SOFTRST
    localparam int RSTCAUSE_FAULT_BIT   = 2;  // CPU faulted / illegal opcode
    localparam int RSTCAUSE_WDT_BIT     = 3;  // watchdog
    localparam int RSTCAUSE_BOOTFAIL_BIT= 4;  // no valid flash image -> monitor
    localparam int RSTCAUSE_FLASHOK_BIT = 5;  // valid image loaded from flash

    // ------------------------------------------------ UART0 register map
    localparam logic [2:0] UART_DATA   = 3'd0;
    localparam logic [2:0] UART_STATUS = 3'd1;
    localparam logic [2:0] UART_BAUD   = 3'd2;
    localparam logic [2:0] UART_CTRL   = 3'd3;
    localparam logic [2:0] UART_FIFO   = 3'd4;

    // ------------------------------------------------ SPI0 register map
    localparam logic [2:0] SPI_DATA   = 3'd0;
    localparam logic [2:0] SPI_STATUS = 3'd1;
    localparam logic [2:0] SPI_CTRL   = 3'd2;
    localparam logic [2:0] SPI_DIV    = 3'd3;

    // ---------------------------------------------- FLASH controller map
    localparam logic [3:0] FLASH_CMD     = 4'h0;
    localparam logic [3:0] FLASH_STAT    = 4'h1;
    localparam logic [3:0] FLASH_ADDR_LO = 4'h2;
    localparam logic [3:0] FLASH_ADDR_HI = 4'h3;
    localparam logic [3:0] FLASH_LEN     = 4'h4;
    localparam logic [3:0] FLASH_DATA    = 4'h5;
    localparam logic [3:0] FLASH_ID      = 4'h6;
    localparam logic [3:0] FLASH_ID2     = 4'h7;
    localparam logic [3:0] FLASH_CRC_LO  = 4'h8;
    localparam logic [3:0] FLASH_CRC_HI  = 4'h9;
    localparam logic [3:0] FLASH_CTRL    = 4'hA;
    localparam logic [3:0] FLASH_WRCNT   = 4'hB;
    localparam logic [3:0] FLASH_SR      = 4'hC;
    localparam logic [3:0] FLASH_TOTAL   = 4'hD;

    // flash command codes (write to FLASH_CMD)
    localparam logic [3:0] FCMD_NOP        = 4'd0;
    localparam logic [3:0] FCMD_READ_ID    = 4'd1;
    localparam logic [3:0] FCMD_READ_START = 4'd2;
    localparam logic [3:0] FCMD_WRITE_START= 4'd3;
    localparam logic [3:0] FCMD_FLUSH      = 4'd4;
    localparam logic [3:0] FCMD_ERASE_SECT = 4'd5;
    localparam logic [3:0] FCMD_ERASE_CHIP = 4'd6;
    localparam logic [3:0] FCMD_CRC_START  = 4'd7;
    localparam logic [3:0] FCMD_READ_SR    = 4'd8;
    localparam logic [3:0] FCMD_WR_ENABLE  = 4'd9;
    localparam logic [3:0] FCMD_WR_DISABLE = 4'd10;
    localparam logic [3:0] FCMD_RELEASE    = 4'd11;

    // --------------------------------------------- Watchdog timer (block 8)
    // See rtl/sv16_wdt.sv and docs/PERIPHERALS.md.  Every register except STAT
    // and FEED is key protected: bits [15:8] of the write data must be 0x5A.
    localparam logic [3:0] WDT_CTRL   = 4'h0; // [0] EN [1] LOCK [2] WIN [3] IRQ [6:4] PRESC
    localparam logic [3:0] WDT_STAT   = 4'h1;
    localparam logic [3:0] WDT_PRESET = 4'h2; // reload value in prescaled ticks
    localparam logic [3:0] WDT_FEED   = 4'h3; // write 0x5A5A to kick
    localparam logic [3:0] WDT_WINDOW = 4'h4; // minimum ticks before a legal feed
    localparam logic [3:0] WDT_MARGIN = 4'h5; // early-warning threshold from expiry

    localparam int WDT_CTRL_ENABLE_BIT = 0;
    localparam int WDT_CTRL_LOCK_BIT   = 1;
    localparam int WDT_CTRL_WINDOW_BIT = 2;
    localparam int WDT_CTRL_IRQ_BIT    = 3;
    localparam int WDT_CTRL_PRESC_LO   = 4;
    localparam int WDT_CTRL_PRESC_HI   = 6;

    localparam int WDT_STAT_TIMEOUT_BIT  = 1; // sticky: the watchdog fired
    localparam int WDT_STAT_WINFAULT_BIT = 2; // sticky: a feed arrived too early
    localparam int WDT_STAT_IRQ_BIT      = 4; // sticky: early warning fired
    localparam int WDT_STAT_BADKEY_BIT   = 5; // sticky: keyed write with a bad key
    localparam int WDT_STAT_BLOCKED_BIT  = 6; // sticky: write ignored because LOCKed

    localparam logic [7:0]  WDT_KEY_BYTE = 8'h5A;    // CTRL/PRESET/WINDOW/MARGIN
    localparam logic [15:0] WDT_KEY_FEED = 16'h5A5A; // FEED

    // ------------------------------------------------- Boot loader block
    localparam logic [3:0] BOOT_CTRL     = 4'h0; // [0] START [1] ABORT [2] VERIFY [3] AUTO
    localparam logic [3:0] BOOT_STAT     = 4'h1;
    localparam logic [3:0] BOOT_SRC_LO   = 4'h2; // flash byte address [15:0]
    localparam logic [3:0] BOOT_SRC_HI   = 4'h3; // flash byte address [23:16]
    localparam logic [3:0] BOOT_SRC_LEN  = 4'h4; // bytes (0 = use header size)
    localparam logic [3:0] BOOT_ENTRY    = 4'h5;
    localparam logic [3:0] BOOT_STACK    = 4'h6;
    localparam logic [3:0] BOOT_WORDS    = 4'h7;
    localparam logic [3:0] BOOT_CRC_EXP  = 4'h8;
    localparam logic [3:0] BOOT_CRC_ACT  = 4'h9;
    localparam logic [3:0] BOOT_ERR      = 4'hA; // write 1 to clear
    localparam logic [3:0] BOOT_MAGIC    = 4'hB;
    localparam logic [3:0] BOOT_HDRVER   = 4'hC;
    localparam logic [3:0] BOOT_NAME0    = 4'hD; // image name chars [1:0]
    localparam logic [3:0] BOOT_NAME1    = 4'hE; // image name chars [3:2]
    localparam logic [3:0] BOOT_NAME2    = 4'hF; // image name chars [5:4]

    // ------------------------------------------------------- ADR-019: A/B slots
    // Two application slots 32 KB apart in the first 64 KB of the flash: slot A
    // at 0x000000, slot B at 0x008000.  Both live inside the address window the
    // ROM monitor's 16-bit update protocol can reach, which is what makes a
    // field update into the *inactive* slot possible over UART at all; the rest
    // of the flash stays free.  32 KB is far more than an image can need when
    // the CPU has 16 KB of RAM.  A slot is an ordinary
    // image (same 32-byte header, same CRC16) plus a 2-byte *slot record* that
    // lives in the header bytes reserved for it by format v1 -- the padding at
    // 0x18-0x1F, header word 0x0C:
    //
    //   byte 0x18   sync   SLOT_REC_SYNC     written once, never changes
    //   byte 0x19   state  SLOT_REC_*        the only byte that ever changes
    //
    // The record is part of the image, so it can never collide with program
    // data (unlike a record parked in the flash page the image starts in), and a
    // host tool that writes an image also installs the record.
    //
    // The state byte only ever gets bits *cleared*, which is what SPI NOR
    // allows: a page program can turn 1s into 0s but never back, and there is no
    // erase unit small enough to rewrite one byte in the middle of an image.
    // Hence PENDING is written with both its bits set and everything the loader
    // writes later is a subset of it.  See ADR-019 for the protocol and for what
    // a torn write leaves behind.
    localparam logic [23:0] BOOT_SLOT_STRIDE  = 24'h00_8000; // 32 KB per slot
    localparam logic [23:0] SLOT_REC_OFFSET   = 24'h00_0018; // image header byte
    localparam logic [23:0] SLOT_REC0         = 24'h00_0018; // slot A (base 0)
    localparam logic [23:0] SLOT_REC1         = BOOT_SLOT_STRIDE + SLOT_REC_OFFSET;
    localparam logic [7:0]  SLOT_REC_SYNC     = 8'hA5;
    localparam logic [7:0]  SLOT_REC_PENDING  = 8'h1F; // installed, never booted
    localparam logic [7:0]  SLOT_REC_TRIED    = 8'h0F; // booted, awaiting CONFIRM
    localparam logic [7:0]  SLOT_REC_GOOD     = 8'h07; // confirmed: fallback image
    localparam logic [7:0]  SLOT_REC_BAD      = 8'h04; // trial failed / retired
    // Each state is a bit-subset of the one it comes from:
    //     PENDING 0x1F -> TRIED 0x0F -> { GOOD 0x07 | BAD 0x04 }
    // which is exactly what a page program allows (1 -> 0, never back), so the
    // record can be advanced without erasing the page that holds the header.
    // A sync byte with the erased 0xFF reads as "state never written", and a
    // missing sync byte reads as "no record": both boot the image untried.
    // who gets the next boot: the priority slot is the one that is new, because
    // a slot only becomes GOOD after confirmation while BAD is written once the
    // trial fails -- so "pending" outranks "good", and the fixed order 0 then 1
    // settles ties.  A trial never hangs the system: the watchdog restarts the
    // part (ADR-017) and bad-confirm takes PENDING -> BAD, after which that slot
    // is never tried again and the other one boots (ADR-019).
    // ADR-019 uses spare bits of the existing registers rather than new
    // offsets, so no firmware register map moves:
    //   BOOT_CTRL [4] NOSLOT   1 = ignore the slot records (boot BOOT_SRC)
    //             [5] SLOT_CLR write 1 = forget the loader's cached slot state
    //             [6] SLOT_CNF write 1 = confirm the running image's trial
    //   BOOT_STAT [5] SLOT     slot this attempt chose / booted
    //             [6] SLOT_RETRY  a slot was abandoned during this attempt
    //             [7] SLOT_TRIAL  the running image is still on trial
    localparam int BOOT_CTRL_NOSLOT_BIT    = 4;
    localparam int BOOT_CTRL_SLOTCLR_BIT   = 5;
    localparam int BOOT_CTRL_SLOTCNF_BIT   = 6;
    localparam int BOOT_STAT_SLOT_BIT      = 5;
    localparam int BOOTERR_SLOT_BIT = 7;  // slot record inconsistent / unreadable

    // BOOT_STAT bits
    localparam int BOOT_BUSY_BIT     = 0;
    localparam int BOOT_OK_BIT       = 1;  // image validated
    localparam int BOOT_FAIL_BIT     = 2;  // image rejected
    localparam int BOOT_CRC_OK_BIT   = 3;
    localparam int BOOT_MAGIC_OK_BIT = 4;
    localparam int BOOT_JUMPED_BIT   = 5;
    localparam int BOOT_RETRY_BIT    = 6;  // this attempt gave up and fell back

    // BOOT_ERR bits
    localparam int BOOTERR_MAGIC_BIT  = 0;
    localparam int BOOTERR_HDRCRC_BIT = 1;
    localparam int BOOTERR_PLDRC_BIT  = 2;
    localparam int BOOTERR_TIMEOUT_BIT= 3;
    localparam int BOOTERR_LENGTH_BIT = 4;
    localparam int BOOTERR_FLASH_BIT  = 5;
    localparam int BOOTERR_VER_BIT    = 6;

    // -------------------------------------------- Boot image file format
    // Produced by scripts/sv16_fwpack.py, consumed by sv16_boot and the
    // ROM monitor. All multi-byte fields are little endian.
    //   0x00 4 bytes magic 'S','V','1','6'
    //   0x04 2 bytes header version (0x0001)
    //   0x06 2 bytes payload length in 16-bit words
    //   0x08 8 bytes ASCII image name (zero padded)
    //   0x10 2 bytes entry address (word address, normally 0x0000)
    //   0x12 2 bytes initial stack pointer (0 => default 0x3FFE)
    //   0x14 2 bytes header CRC16 (over bytes 0x00..0x13)
    //   0x16 2 bytes payload CRC16 (over the payload bytes)
    //   0x18 8 bytes reserved
    //   0x20 ...     payload (little endian words)
    localparam logic [31:0] BOOT_MAGIC_VALUE = 32'h36_31_56_53; // 'S','V','1','6'
    localparam logic [15:0] BOOT_HDR_VERSION = 16'h0001;
    localparam int          BOOT_HDR_SIZE    = 32;                 // bytes
    localparam logic [15:0] BOOT_DEFAULT_SP  = 16'h3FFE;
    localparam logic [15:0] IRQ_DEFAULT_SP   = 16'h3FFE;

endpackage : sv16_pkg
