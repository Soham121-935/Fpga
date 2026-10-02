// SV-16 Rev B — System Bus Interconnect
// Module: sv16_bus_interconnect
//
// Single-cycle (pulse) request bus with a shared acknowledge. Rev B adds:
//   * a second bus master: the hardware boot engine (used while the CPU is
//     halted at startup to load firmware from SPI flash into SRAM)
//   * the Rev B address map: 16K-word SRAM, 4K-byte boot ROM, 16 MMIO blocks
//   * unmapped accesses return 0x0000 and acknowledge normally, so stray
//     pointers cannot hang the CPU
//
// Bus contract (see docs/BUS_ARCHITECTURE.md):
//   * a master presents `req` (with address/write-data/we) and holds it until
//     it observes `ack`; a slave that needs wait states simply answers later
//   * a slave asserts `ack` for the request it was presented in the previous
//     cycle (every slave in Rev B registers its acknowledge); read data must be
//     valid in the cycle `ack` is asserted
//   * the bus is granted to one master per *transfer*, not per cycle: the owner
//     keeps the bus from the cycle it presents the request until the cycle the
//     acknowledge returns.  Holding the grant is what keeps the shared read
//     data mux honest - the acknowledge always arrives while the address of the
//     access it belongs to is still driven, so the data that comes back with it
//     belongs to that access
//   * an acknowledge is only meaningful together with the transfer that was
//     presented in the previous cycle by the same master, which is what
//     `req_q`/`owner_q` are for
//
// Address decode (word addresses):
//   0x0000-0x3FFF  SRAM   (16K words / 32 KB)
//   0x4000-0xDFFF  unmapped
//   0xE000-0xE7FF  boot ROM (2K words / 4 KB)
//   0xE800-0xEFFF  unmapped
//   0xF000-0xF0FF  peripherals, 16 blocks x 16 registers
//   0xF100-0xFFFF  unmapped
//
// Rev B: rewritten (ADR-014).

`timescale 1ns / 1ps

import sv16_pkg::*;

module sv16_bus_interconnect (
    input  logic        clk,
    input  logic        rst_n,

    // ------------------------------------------------- CPU bus master
    input  logic [15:0] cpu_addr,
    input  logic [15:0] cpu_wdata,
    input  logic        cpu_req,
    input  logic        cpu_we,
    output logic [15:0] cpu_rdata,
    output logic        cpu_ack,

    // ------------------------------------------- Boot engine bus master
    input  logic [15:0] boot_addr,
    input  logic [15:0] boot_wdata,
    input  logic        boot_req,
    input  logic        boot_we,
    output logic [15:0] boot_rdata,
    output logic        boot_ack,
    input  logic        boot_master,     // 1 = the boot engine owns the bus

    // ------------------------------------------------------------ SRAM
    output logic [13:0] ram_addr,
    output logic [15:0] ram_wdata,
    output logic        ram_we,
    output logic        ram_req,
    input  logic [15:0] ram_rdata,
    input  logic        ram_ack,

    // -------------------------------------------------------- Boot ROM
    output logic [10:0] rom_addr,
    output logic        rom_req,
    input  logic [15:0] rom_rdata,
    input  logic        rom_ack,

    // ------------------------------------------- MMIO block/register bus
    output logic [3:0]  mmio_blk,        // addr[7:4]: block select
    output logic [3:0]  mmio_reg,        // addr[3:0]: register within block
    output logic [15:0] mmio_wdata,
    output logic        mmio_we,
    output logic [15:0] mmio_req,        // one-hot per block
    input  logic [15:0] mmio_present,    // implemented blocks (1 = slave exists)
    input  logic [15:0] mmio_ack,        // per block
    input  logic [15:0] rd_sys,
    input  logic [15:0] rd_gpio0,
    input  logic [15:0] rd_timer0,
    input  logic [15:0] rd_pwm0,
    input  logic [15:0] rd_uart0,
    input  logic [15:0] rd_spi0,
    input  logic [15:0] rd_flash,
    input  logic [15:0] rd_gpio1,
    input  logic [15:0] rd_wdt,
    input  logic [15:0] rd_irq,
    input  logic [15:0] rd_boot,

    // ---------------------------------------------------------- Status
    output logic        unmapped_access
);


    // ------------------------------------------------- Master arbitration
    //
    // Both masters get the bus for a whole transfer: `cpu_pend`/`boot_pend` are
    // set when a master presents a request and cleared when its acknowledge
    // comes back, and while either is set the bus stays with that master.  A
    // master that is displaced (the loader taking the bus while the CPU was
    // presenting) has not lost anything: the CPU holds its request until it is
    // answered and the loader's sequencer holds its write until its own
    // acknowledge arrives.
    //
    // The boot loader is the lower-priority master and may only claim the bus
    // when the CPU has nothing in flight, so the ROM monitor keeps polling
    // BOOT_STAT and driving the UART while an image streams in.  (A loader that
    // could take the bus at any time starved the CPU, and a store that finally
    // completed then re-triggered the loader - one boot command became a storm
    // of attempts.)
    logic cpu_pend, boot_pend;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cpu_pend  <= 1'b0;
            boot_pend <= 1'b0;
        end else begin
            if (cpu_ack)       cpu_pend  <= 1'b0;
            else if (cpu_req)  cpu_pend  <= 1'b1;

            if (boot_ack)      boot_pend <= 1'b0;
            else if (boot_req) boot_pend <= 1'b1;
        end
    end

    logic boot_own;
    assign boot_own = boot_master && (boot_pend || (boot_req && !cpu_pend));

    logic [15:0] m_addr, m_wdata;
    logic        m_req, m_we;

    always_comb begin
        if (boot_own) begin
            m_addr  = boot_addr;
            m_wdata = boot_wdata;
            m_req   = boot_req;
            m_we    = boot_we;
        end else begin
            m_addr  = cpu_addr;
            m_wdata = cpu_wdata;
            m_req   = cpu_req;
            m_we    = cpu_we;
        end
    end

    // ------------------------------------------------------ Slave decode
    logic sel_ram, sel_rom, sel_mmio, sel_unmapped;

    logic mmio_miss;    // MMIO address whose block has no slave implemented

    assign sel_ram      = (m_addr <= RAM_LAST);
    assign sel_rom      = (m_addr >= ROM_BASE) && (m_addr <= ROM_LAST);
    assign sel_mmio     = (m_addr >= MMIO_BASE) && (m_addr <= MMIO_LAST);
    assign mmio_miss    = sel_mmio && !mmio_present[m_addr[7:4]];
    assign sel_unmapped = !(sel_ram || sel_rom || (sel_mmio && !mmio_miss));

    // ------------------------------------------------------------ SRAM
    assign ram_addr  = m_addr[RAM_ADDR_W-1:0];
    assign ram_wdata = m_wdata;
    assign ram_we    = m_we;
    assign ram_req   = m_req && sel_ram;

    // -------------------------------------------------------- Boot ROM
    assign rom_addr  = m_addr[ROM_ADDR_W-1:0];
    assign rom_req   = m_req && sel_rom;

    // ------------------------------------------------------------ MMIO
    assign mmio_blk   = m_addr[7:4];
    assign mmio_reg   = m_addr[3:0];
    assign mmio_wdata = m_wdata;
    assign mmio_we    = m_we;

    always_comb begin
        mmio_req = 16'h0000;
        if (m_req && sel_mmio) mmio_req[mmio_blk] = 1'b1;
    end

    // -------------------------------------------------- Unmapped accesses
    logic unmapped_ack;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) unmapped_ack <= 1'b0;
        else        unmapped_ack <= m_req && (sel_unmapped || mmio_miss);
    end

    assign unmapped_access = m_req && (sel_unmapped || mmio_miss);

    // ------------------------------------------------------- Read mux
    logic [15:0] mmio_rdata;

    always_comb begin
        mmio_rdata = 16'h0000;
        case (mmio_blk)
            BLK_SYS:    mmio_rdata = rd_sys;
            BLK_GPIO0:  mmio_rdata = rd_gpio0;
            BLK_TIMER0: mmio_rdata = rd_timer0;
            BLK_PWM0:   mmio_rdata = rd_pwm0;
            BLK_UART0:  mmio_rdata = rd_uart0;
            BLK_SPI0:   mmio_rdata = rd_spi0;
            BLK_FLASH:  mmio_rdata = rd_flash;
            BLK_GPIO1:  mmio_rdata = rd_gpio1;
            BLK_WDT:    mmio_rdata = rd_wdt;
            BLK_IRQ:    mmio_rdata = rd_irq;
            BLK_BOOT:   mmio_rdata = rd_boot;
            default:    mmio_rdata = 16'h0000;
        endcase
    end

    logic [15:0] bus_rdata;
    always_comb begin
        if      (sel_ram)  bus_rdata = ram_rdata;
        else if (sel_rom)  bus_rdata = rom_rdata;
        else if (sel_mmio) bus_rdata = mmio_rdata;
        else               bus_rdata = 16'h0000;
    end

    logic bus_ack;
    assign bus_ack = ram_ack | rom_ack |
                     (mmio_ack[mmio_blk] & mmio_present[mmio_blk]) |
                     unmapped_ack;

    // -------------------------------------------------- Acknowledge routing
    //
    // Every slave acknowledges the request that was presented to it *one cycle
    // earlier*, so an acknowledge is only meaningful together with
    //
    //   (a) the fact that the interconnect presented a request in the previous
    //       cycle (`req_q`), and
    //   (b) the master that presented it (`owner_q`).
    //
    // Without (a) and (b) the acknowledge of a transaction that has just
    // finished leaks into the first cycle of whoever owns the bus next: the
    // boot loader's last SRAM write handed the CPU a spurious acknowledge and
    // the CPU latched a word of firmware payload instead of the instruction it
    // had asked the ROM for.
    //
    // Qualifying the acknowledge this way also lets a genuinely slow slave
    // stretch a transfer: the CPU holds its request until it is answered, so
    // the request stays presented and the acknowledge lands (and is routed) as
    // soon as the slave raises it.
    logic req_q, owner_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            req_q   <= 1'b0;
            owner_q <= 1'b0;
        end else begin
            req_q   <= m_req;
            owner_q <= boot_own;
        end
    end

    logic ack_valid;
    assign ack_valid = bus_ack && req_q;

    // ------------------------------------------------------ Master replies
    always_comb begin
        cpu_rdata  = bus_rdata;
        boot_rdata = bus_rdata;
        cpu_ack    = ack_valid && !owner_q;
        boot_ack   = ack_valid &&  owner_q;
    end

endmodule : sv16_bus_interconnect
