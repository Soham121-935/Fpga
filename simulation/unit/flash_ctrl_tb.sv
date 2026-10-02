// SV-16 Rev B — Testbench: SPI flash controller + flash model
//
// Functional test of sv16_flash_ctrl against sv16_flash_model:
//   1. RDID      - JEDEC identification
//   2. RDSR      - status register
//   3. SE        - 4 KB sector erase, verify 0xFF
//   4. WRITE     - page-buffer programming (WREN + WRITE_START + data + flush)
//   5. READ      - streaming read with RX FIFO
//   6. CRC       - hardware CRC16 over a flash region
//   7. BOOT      - boot-stream port used by sv16_boot
//
// Run:  verilator --binary -Wno-fatal -Irtl rtl/sv16_pkg.sv rtl/sv16_crc16.sv \
//         rtl/sv16_spi_master.sv rtl/sv16_flash_ctrl.sv \
//         simulation/unit/sv16_flash_model.sv simulation/unit/flash_ctrl_tb.sv \
//         --top-module flash_ctrl_tb

`timescale 1ns / 1ps

module flash_ctrl_tb;

    // ------------------------------------------------------------- clock
    logic clk = 1'b0;
    always #10 clk = ~clk;      // 50 MHz

    // ------------------------------------------------------------- signals
    logic        rst_n;
    logic [3:0]  addr;
    logic [15:0] wdata, rdata;
    logic        req, we, ack;

    logic        boot_start;
    logic [23:0] boot_addr;
    logic [15:0] boot_len;
    logic        boot_valid, boot_ack;
    logic [7:0]  boot_data;
    logic        boot_busy;

    logic        flash_sck, flash_cs_n, flash_mosi, flash_miso;
    logic        flash_irq, id_ok;
    logic [23:0] jedec_id;

    int          errors = 0;
    int          checks = 0;

    // ------------------------------------------------------------ DUT
    sv16_flash_ctrl dut (
        .clk(clk), .rst_n(rst_n),
        .addr(addr), .wdata(wdata), .rdata(rdata), .req(req), .we(we), .ack(ack),
        .boot_start(boot_start), .boot_addr(boot_addr), .boot_len(boot_len),
        .boot_valid(boot_valid), .boot_data(boot_data), .boot_ack(boot_ack),
        .boot_abort(1'b0), .boot_busy(boot_busy),
        .flash_sck(flash_sck), .flash_cs_n(flash_cs_n),
        .flash_mosi(flash_mosi), .flash_miso(flash_miso),
        .flash_irq(flash_irq), .id_ok(id_ok), .jedec_id(jedec_id)
    );

    sv16_flash_model #(
        .MEM_BYTES(131072), .PROG_TICKS(48)
    ) model (
        .clk(clk), .rst_n(rst_n),
        .sck(flash_sck), .cs_n(flash_cs_n), .mosi(flash_mosi), .miso(flash_miso)
    );

    // ------------------------------------------------- reference CRC16
    function automatic [15:0] crc16(input logic [15:0] c_in, input logic [7:0] d);
        logic [15:0] c;
        begin
            c = c_in;
            for (int i = 7; i >= 0; i--) begin
                if (c[15] ^ d[i]) c = (c << 1) ^ 16'h1021;
                else              c = (c << 1);
            end
            crc16 = c;
        end
    endfunction

    // ------------------------------------------------------- bus helpers
    task automatic bus_write(input logic [3:0] a, input logic [15:0] d);
        begin
            @(negedge clk);
            addr = a; wdata = d; we = 1'b1; req = 1'b1;
            do @(posedge clk); while (!ack);
            @(negedge clk);
            req = 1'b0; we = 1'b0;
        end
    endtask

    task automatic bus_read(input logic [3:0] a, output logic [15:0] d);
        begin
            @(negedge clk);
            addr = a; we = 1'b0; req = 1'b1;
            do @(posedge clk); while (!ack);
            d = rdata;
            @(negedge clk);
            req = 1'b0;
        end
    endtask

    task automatic check(input bit cond, input string msg);
        begin
            checks++;
            if (cond) $display("  [PASS] %s", msg);
            else begin
                errors++;
                $display("  [FAIL] %s", msg);
            end
        end
    endtask

    task automatic wait_engine_idle;
        logic [15:0] st;
        begin
            do bus_read(4'h1, st); while (st[0] || st[5]);   // BUSY | PGM_BUSY
        end
    endtask

    // ------------------------------------------------ boot stream capture
    logic [7:0]  boot_rx [0:511];
    int          boot_count;
    assign boot_ack = 1'b1;
    always @(posedge clk) begin
        if (rst_n && boot_valid && boot_ack) begin
            boot_rx[boot_count] = boot_data;
            boot_count          = boot_count + 1;
        end
    end

    // -------------------------------------------------------------- test
    logic [15:0] rd, st;
    logic [7:0]  pattern [0:31];
    logic [7:0]  rb;
    logic [15:0] crc_sw, crc_hw;
    int          i;

    initial begin
        $dumpfile("flash_ctrl_tb.vcd");
        $dumpvars(0, flash_ctrl_tb);

        rst_n      = 1'b0;
        addr       = 4'h0; wdata = 16'h0; req = 1'b0; we = 1'b0;
        boot_start = 1'b0; boot_addr = 24'h0; boot_len = 16'h0;
        boot_count = 0;
        for (i = 0; i < 32; i++) pattern[i] = 8'h5A + i;

        repeat (8) @(posedge clk);
        rst_n = 1'b1;
        repeat (4) @(posedge clk);

        $display("== SV-16 flash controller test ==");

        // ---- 1. RDID -----------------------------------------------------
        $display("-- step 1: RDID --");
        bus_write(4'hA, 16'h0000);          // FLASH_CTRL: fastest SCLK
        bus_write(4'h0, 16'h0001);          // FLASH_CMD = READ_ID
        wait_engine_idle;
        bus_read(4'h6, rd);                 // FLASH_ID  = {type, mfr}
        check(rd == 16'h40EF, "RDID manufacturer/type = 0x40EF");
        bus_read(4'h7, rd);                 // FLASH_ID2 = capacity
        check(rd == 16'h0018, $sformatf("RDID capacity = 0x0018 (got 0x%04x)", rd));
        bus_read(4'h1, st);
        check(st[2] == 1'b1, "STAT.ID_OK set");
        check(jedec_id == 24'hEF4018, $sformatf("jedec_id output = 0xEF4018 (got 0x%06x)", jedec_id));

        // ---- 2. RDSR -----------------------------------------------------
        $display("-- step 2: RDSR / WREN --");
        bus_write(4'h0, 16'h0008);          // FLASH_CMD = READ_SR
        wait_engine_idle;
        bus_read(4'hC, rd);                 // FLASH_SR
        check(rd[7] == 1'b0, "status WIP clear when idle");
        bus_write(4'h0, 16'h0009);          // WREN
        wait_engine_idle;
        bus_write(4'h0, 16'h0008);          // READ_SR
        wait_engine_idle;
        bus_read(4'hC, rd);
        check(rd[1] == 1'b1, $sformatf("WREN sets the flash write-enable latch (SR=0x%02x)", rd[7:0]));
        bus_write(4'h0, 16'h000A);          // WRDI
        wait_engine_idle;

        // ---- 3. sector erase --------------------------------------------
        $display("-- step 3: erase + read --");
        bus_write(4'h2, 16'h1000);          // ADDR_LO
        bus_write(4'h3, 16'h0000);          // ADDR_HI
        bus_write(4'h0, 16'h0005);          // ERASE_SECT
        wait_engine_idle;
        bus_write(4'h2, 16'h1000);
        bus_write(4'h4, 16'd4);             // LEN = 4 bytes
        bus_write(4'h0, 16'h0002);          // READ_START
        wait_engine_idle;
        bus_read(4'h1, st);
        $display("    [dbg] after erase: STAT=0x%04x ADDR=0x%04x", st, rd);
        for (i = 0; i < 4; i++) begin
            bus_read(4'h5, rd);
            check(rd[7:0] == 8'hFF, $sformatf("erased byte %0d = 0xFF (got 0x%02x)", i, rd[7:0]));
        end

        // ---- 4. page programming ----------------------------------------
        $display("-- step 4: page program --");
        bus_write(4'h2, 16'h1000);
        bus_write(4'h3, 16'h0000);
        bus_write(4'h4, 16'd32);            // LEN = 32 bytes
        bus_write(4'h0, 16'h0003);          // WRITE_START
        for (i = 0; i < 32; i++) bus_write(4'h5, {8'h00, pattern[i]});
        wait_engine_idle;                   // wait for the automatic flush
        bus_read(4'hB, rd);                 // WRCNT must be empty again
        check(rd[8:0] == 9'd0, "page buffer empty after auto-flush");
        bus_read(4'h1, st);
        check(st[1] == 1'b0, $sformatf("no error during programming (STAT=0x%04x)", st));

        $display("-- step 5: read back --");
        // ---- 5. read back and compare -----------------------------------
        // The RX FIFO holds 8 bytes, so firmware drains it while the transfer
        // is running (the SPI clock stalls when the FIFO is full: that is the
        // flow control between the flash controller and the CPU).
        bus_write(4'h2, 16'h1000);
        bus_write(4'h4, 16'd32);
        begin bit all_ok = 1'b1; end
        bus_write(4'h0, 16'h0002);          // READ_START
        for (i = 0; i < 32; i++) begin
            do bus_read(4'h1, st); while (!st[3]);   // wait RD_READY
            bus_read(4'h5, rd);
            rb = rd[7:0];
            if (rb !== pattern[i]) $display("    byte %0d: got %02x want %02x", i, rb, pattern[i]);
            check(rb === pattern[i], $sformatf("readback byte %0d matches", i));
        end
        wait_engine_idle;

        $display("-- step 6: CRC --");
        // ---- 6. hardware CRC over the same 32 bytes ---------------------
        crc_sw = 16'hFFFF;
        for (i = 0; i < 32; i++) crc_sw = crc16(crc_sw, pattern[i]);
        bus_write(4'h2, 16'h1000);
        bus_write(4'h4, 16'd32);
        bus_write(4'h0, 16'h0007);          // CRC_START
        wait_engine_idle;
        bus_read(4'h8, rd); crc_hw[7:0]  = rd[7:0];
        bus_read(4'h9, rd); crc_hw[15:8] = rd[7:0];
        check(crc_hw == crc_sw,
              $sformatf("hardware CRC16 0x%04x == host CRC16 0x%04x", crc_hw, crc_sw));
        bus_read(4'h1, st);
        check(st[6] == 1'b1, "STAT.CRC_READY set");

        $display("-- step 7: boot stream --");
        // ---- 7. boot stream --------------------------------------------
        boot_count = 0;
        @(negedge clk);
        boot_addr  = 24'h001000;
        boot_len   = 16'd32;
        boot_start = 1'b1;
        @(negedge clk);
        boot_start = 1'b0;
        for (i = 0; i < 4000 && boot_count < 32; i++) @(posedge clk);
        check(boot_count == 32, $sformatf("boot stream delivered 32 bytes (got %0d)", boot_count));
        begin
            bit ok = 1'b1;
            for (i = 0; i < 32; i++) if (boot_rx[i] !== pattern[i]) ok = 1'b0;
            check(ok, "boot stream bytes match the programmed pattern");
        end

        // ---- summary ----------------------------------------------------
        $display("== %0d checks, %0d failures ==", checks, errors);
        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL");
        $finish;
    end

    initial begin
        #4_000_000;
        $display("RESULT: FAIL (timeout)");
        $finish;
    end

endmodule
