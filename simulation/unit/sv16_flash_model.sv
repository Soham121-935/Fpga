// SV-16 Rev B — Simulation model: SPI NOR flash (25-series compatible)
//
// Behavioural model of a JEDEC SPI NOR flash used to verify sv16_flash_ctrl
// and the hardware boot engine without physical hardware. Clocked on the
// system clock and edge-detecting SCK, so it stays race free under Verilator.
//
// Supported commands (the exact subset the SV-16 controller uses):
//   0x06 WREN   0x04 WRDI   0x05 RDSR   0x03 READ
//   0x02 PP     0x20 SE (4 KB sector)    0x60 CE   0x9F RDID   0xAB RELEASE
//
// Timing model: writes/erases set WIP for a configurable number of clocks so
// firmware status polling is exercised; a program without WREN, and commands
// issued while WIP is set, are ignored exactly like a real device.
//
// Physics that the tests depend on: a page program only clears bits
// (mem <= mem & data) and an erase sets a whole sector back to 0xFF.  Modelling
// the program as a plain assignment would hide the ADR-019 requirement that
// every slot-record transition only ever clear bits -- a real chip cannot turn
// a 0 back into a 1 without erasing the whole 4 KB sector, image and all.
//
// This is a testbench model: not synthesizable, never part of the FPGA build.

`timescale 1ns / 1ps

module sv16_flash_model #(
    parameter int          MEM_BYTES   = 131072,  // two 64 KB A/B slots
    parameter logic [7:0]  ID_MFR      = 8'hEF,   // Winbond
    parameter logic [7:0]  ID_TYPE     = 8'h40,
    parameter logic [7:0]  ID_CAP      = 8'h18,   // 128 Mbit
    parameter int          PROG_TICKS  = 64,
    parameter              INIT_FILE   = ""       // optional $readmemh image
)(
    input  logic clk,
    input  logic rst_n,
    input  logic sck,
    input  logic cs_n,
    input  logic mosi,
    output logic miso
);

    localparam int ADDR_W = $clog2(MEM_BYTES);

    localparam logic [7:0] CMD_WREN = 8'h06,
                           CMD_WRDI = 8'h04,
                           CMD_RDSR = 8'h05,
                           CMD_READ = 8'h03,
                           CMD_PP   = 8'h02,
                           CMD_SE   = 8'h20,
                           CMD_CE   = 8'h60,
                           CMD_RDID = 8'h9F,
                           CMD_REL  = 8'hAB;

    localparam logic [2:0] F_IDLE = 3'd0,
                           F_CMD  = 3'd1,
                           F_ADDR = 3'd2,
                           F_PROG = 3'd3,
                           F_READ = 3'd4,
                           F_ID   = 3'd5,
                           F_SR   = 3'd6,
                           F_SKIP = 3'd7;

    logic [7:0] mem [0:MEM_BYTES-1];

    logic [2:0]  fstate;
    logic [7:0]  cmd;
    logic [23:0] addr;
    logic [2:0]  addr_bytes;
    logic        wel, wip;
    logic [15:0] busy_cnt;

    // erase engine (runs over many clocks - no giant unrolled loops)
    logic        erasing;
    logic [23:0] er_ptr, er_end;

    // byte RX assembly
    logic [2:0]  bit_cnt;
    logic [7:0]  rx_shift;

    // byte TX
    logic [2:0]  out_bit_cnt;
    logic [7:0]  out_shift;
    logic [1:0]  out_bytes_left;
    logic [1:0]  out_idx;
    logic [23:0] rd_addr;

    logic sck_d, cs_d;
    logic miso_r;

    assign miso = miso_r;

    // -------------------------------------------------- output byte source
    logic [7:0] out_next;
    always_comb begin
        case (fstate)
            F_READ:  out_next = mem[rd_addr[ADDR_W-1:0]];
            F_ID:    out_next = (out_idx == 2'd0) ? ID_MFR :
                                (out_idx == 2'd1) ? ID_TYPE : ID_CAP;
            F_SR:    out_next = {6'b000000, wel, wip};
            default: out_next = 8'hFF;
        endcase
    end

    // ------------------------------------------------------------ main FSM
    logic [7:0] rx_byte;
    assign rx_byte = {rx_shift[6:0], mosi};

    integer i;
    initial begin
        for (i = 0; i < MEM_BYTES; i = i + 1) mem[i] = 8'hFF;
        if (INIT_FILE != "") $readmemh(INIT_FILE, mem);
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fstate         <= F_IDLE;
            cmd            <= 8'h00;
            addr           <= 24'd0;
            addr_bytes     <= 3'd0;
            wel            <= 1'b0;
            wip            <= 1'b0;
            busy_cnt       <= 16'd0;
            erasing        <= 1'b0;
            er_ptr         <= 24'd0;
            er_end         <= 24'd0;
            bit_cnt        <= 3'd0;
            rx_shift       <= 8'h00;
            out_bit_cnt    <= 3'd0;
            out_shift      <= 8'h00;
            out_bytes_left <= 2'd0;
            out_idx        <= 2'd0;
            rd_addr        <= 24'd0;
            sck_d          <= 1'b0;
            cs_d           <= 1'b1;
            miso_r         <= 1'b0;
        end else begin
            sck_d <= sck;
            cs_d  <= cs_n;

            // -------------------------------------------------- erase engine
            if (erasing) begin
                if (er_ptr >= er_end) begin
                    erasing <= 1'b0;
                    wel     <= 1'b0;
                end else begin
                    mem[er_ptr[ADDR_W-1:0]] <= 8'hFF;
                    er_ptr <= er_ptr + 24'd1;
                end
            end

            // ---------------------------------------------------- WIP timer
            if (wip && !erasing) begin
                if (busy_cnt <= 16'd1) begin
                    busy_cnt <= 16'd0;
                    wip      <= 1'b0;
                    wel      <= 1'b0;
                end else begin
                    busy_cnt <= busy_cnt - 16'd1;
                end
            end

            // ---------------------------------------- CS assert: new opcode
            if (!cs_n && cs_d) begin
                fstate         <= F_CMD;
                bit_cnt        <= 3'd0;
                rx_shift       <= 8'h00;
                addr_bytes     <= 3'd0;
                out_bit_cnt    <= 3'd0;
                out_bytes_left <= 2'd0;
                out_idx        <= 2'd0;
            end

            // ------------------------------------- CS release: commit command
            if (cs_n && !cs_d) begin
                // page program: the internal write starts now, so WIP rises and
                // WEL is released when it finishes (PROG_TICKS later)
                if ((cmd == CMD_PP) && wel && (fstate == F_PROG)) begin
                    wip      <= 1'b1;
                    busy_cnt <= PROG_TICKS[15:0];
                end
                if ((cmd == CMD_SE) && wel && (fstate == F_ADDR)) begin
                    er_ptr   <= {addr[23:12], 12'h000};
                    er_end   <= {addr[23:12], 12'h000} + 24'd4096;
                    erasing  <= 1'b1;
                    wip      <= 1'b1;
                end
                fstate      <= F_IDLE;
                miso_r      <= 1'b0;
                out_bit_cnt <= 3'd0;
            end

            // --------------------------------------- rising SCK: sample MOSI
            if (!cs_n && sck && !sck_d) begin
                rx_shift <= rx_byte;
                bit_cnt  <= bit_cnt + 3'd1;
                if (bit_cnt == 3'd7) begin
                    bit_cnt <= 3'd0;
                    case (fstate)
                        F_CMD: begin
                            cmd <= rx_byte;
                            case (rx_byte)
                                CMD_WREN: begin wel <= 1'b1; fstate <= F_SKIP; end
                                CMD_WRDI: begin wel <= 1'b0; fstate <= F_SKIP; end
                                CMD_RDSR: begin fstate <= F_SR; out_bytes_left <= 2'd1; end
                                CMD_RDID: begin fstate <= F_ID; out_bytes_left <= 2'd3; out_idx <= 2'd0; end
                                CMD_REL:  begin fstate <= F_SR; out_bytes_left <= 2'd1; end
                                CMD_READ: begin fstate <= F_ADDR; addr_bytes <= 3'd0; end
                                CMD_PP:   begin fstate <= F_ADDR; addr_bytes <= 3'd0; end
                                CMD_SE:   begin fstate <= F_ADDR; addr_bytes <= 3'd0; end
                                CMD_CE: begin
                                    er_ptr  <= 24'd0;
                                    er_end  <= MEM_BYTES[23:0];
                                    erasing <= 1'b1;
                                    wip     <= 1'b1;
                                    fstate  <= F_SKIP;
                                end
                                default: fstate <= F_SKIP;
                            endcase
                            if (wip && (rx_byte != CMD_RDSR) && (rx_byte != CMD_READ))
                                fstate <= F_SKIP;      // device busy
                        end

                        F_ADDR: begin
                            addr       <= {addr[15:0], rx_byte};
                            addr_bytes <= addr_bytes + 3'd1;
                            if (addr_bytes == 3'd2) begin
                                case (cmd)
                                    CMD_READ: begin
                                        fstate         <= F_READ;
                                        rd_addr        <= {addr[15:0], rx_byte};   // 24-bit addr
                                        out_bytes_left <= 2'd3;   // streams until CS rises
                                    end
                                    CMD_PP:   fstate <= F_PROG;
                                    default:  fstate <= F_ADDR;   // SE waits for CS
                                endcase
                            end
                        end

                        F_PROG: begin
                            if (wel) begin
                                if (addr[ADDR_W-1:0] < MEM_BYTES)
                                    // page program: AND, not overwrite
                                    mem[addr[ADDR_W-1:0]]
                                        <= mem[addr[ADDR_W-1:0]] & rx_byte;
                                addr <= {addr[23:8], addr[7:0] + 8'd1};  // page wrap
                            end
                        end

                        default: ;   // reads / id / status accept no data
                    endcase
                end
            end

            // ---------------------------- falling SCK: advance output bit
            // A byte is loaded when out_bit_cnt wraps to 0; the remaining bit
            // shifts are never gated by the byte count, otherwise the final
            // byte of a transfer would be cut short.
            if (!cs_n && !sck && sck_d) begin
                if (out_bit_cnt == 3'd0) begin
                    if (out_bytes_left != 2'd0) begin
                        out_shift   <= out_next;
                        miso_r      <= out_next[7];
                        out_bit_cnt <= 3'd1;
                        if (fstate == F_READ) begin
                            rd_addr <= rd_addr + 24'd1;
                        end else begin
                            out_bytes_left <= out_bytes_left - 2'd1;
                            if (fstate == F_ID) out_idx <= out_idx + 2'd1;
                        end
                    end else begin
                        miso_r <= 1'b0;
                    end
                end else begin
                    out_shift   <= {out_shift[6:0], 1'b0};
                    miso_r      <= out_shift[6];
                    out_bit_cnt <= (out_bit_cnt == 3'd7) ? 3'd0 : out_bit_cnt + 3'd1;
                end
            end
        end
    end

endmodule : sv16_flash_model
