// SV-16 Rev A — SystemVerilog Package Definitions
// Contains shared constants, types, opcodes, and flag indices.

package sv16_pkg;

    // Architectural Widths
    localparam int DATA_WIDTH    = 16;
    localparam int ADDR_WIDTH    = 16;
    localparam int REG_ADDR_W    = 3;
    localparam int NUM_GPRS      = 8;

    // Status Register (SR) Flag Bit Positions
    localparam int FLAG_Z_BIT    = 0; // Zero flag
    localparam int FLAG_C_BIT    = 1; // Carry / Borrow flag
    localparam int FLAG_N_BIT    = 2; // Negative / Sign flag
    localparam int FLAG_V_BIT    = 3; // Signed Overflow flag
    localparam int FLAG_IE_BIT   = 7; // Global Interrupt Enable

    // Primary Opcodes [15:12]
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

    // Standard ALU Sub-Opcodes (for OP_ALU_RR, bits [2:0])
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

    // Extended ALU Sub-Opcodes (for OP_EXT_ALU, bits [2:0])
    typedef enum logic [2:0] {
        EXT_SHL      = 3'h0,
        EXT_SHR      = 3'h1,
        EXT_MUL      = 3'h2,
        EXT_DIV      = 3'h3,
        EXT_MOD      = 3'h4
    } ext_subop_e;

    // Branch Condition Codes (bits [11:8])
    typedef enum logic [3:0] {
        COND_BRA     = 4'h0, // Branch Always
        COND_BEQ     = 4'h1, // Equal (Z == 1)
        COND_BNE     = 4'h2, // Not Equal (Z == 0)
        COND_BC      = 4'h3, // Carry Set / Below (C == 1)
        COND_BNC     = 4'h4, // Carry Clear / Higher or Same (C == 0)
        COND_BN      = 4'h5, // Negative (N == 1)
        COND_BP      = 4'h6, // Positive (N == 0)
        COND_BVS     = 4'h7, // Overflow Set (V == 1)
        COND_BVC     = 4'h8, // Overflow Clear (V == 0)
        COND_BLT     = 4'h9, // Signed Less Than (N ^ V == 1)
        COND_BGE     = 4'hA, // Signed Greater or Equal (N ^ V == 0)
        COND_BLE     = 4'hB, // Signed Less or Equal (Z | (N ^ V) == 1)
        COND_BGT     = 4'hC  // Signed Greater Than (Z | (N ^ V) == 0)
    } branch_cond_e;

endpackage : sv16_pkg
