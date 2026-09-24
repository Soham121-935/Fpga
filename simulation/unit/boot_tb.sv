// SV-16 Rev B — Testbench: hardware boot loader
//
// Verifies the complete "program the device once, it boots its own firmware"
// path with no CPU involved:
//
//   SPI flash model (preloaded with a packed image)
//        -> sv16_flash_ctrl boot stream
//        -> sv16_boot (magic + header CRC + payload CRC verification)
//        -> system bus master -> sv16_ram
//
// Checks
//   1. a valid image loads, verifies and reports entry/stack/name/CRCs
//   2. the SRAM contents match the payload words after the load
//   3. a region without a valid image fails cleanly (no bus hang); with the
//      A/B slot policy enabled by default the loader also reports BOOTERR_SLOT
//   4. the loader can be restarted after a failure and succeeds again
//   5. a payload CRC mismatch is detected (bit flip in flash)
//
// Requires build/fw/motor_test_flash.hex and build/fw/motor_test_words.hex
// (produced by `make firmware`); run the binary from the repository root.

`timescale 1ns / 1ps

module boot_tb;

    logic clk = 1'b0;
    always #10 clk = ~clk;          // 50 MHz

    localparam string FLASH_IMAGE = "build/fw/motor_test_flash.hex";
    localparam string IMG_WORDS   = "build/fw/motor_test_words.hex";
    localparam int    IMG_WORDS_N = 39;
    localparam int    IMG_OFFSET  = 32;      // payload starts after the header

    // ------------------------------------------------------------ signals
    logic        rst_n;
    logic [4:0]  bus_addr;      // [4] = target: 0 = flash controller, 1 = boot
    logic [15:0] bus_wdata, bus_rdata;
    logic        bus_req, bus_we, bus_ack;

    logic [3:0]  addr;
    logic [15:0] wdata, rdata;
    logic        we;                    // write strobe seen by both slaves
    logic        flash_req, flash_ack, boot_req2, boot_ack2;
    logic [15:0] flash_rdata, boot_rdata2;

    assign addr       = bus_addr[3:0];
    assign wdata      = bus_wdata;
    assign we         = bus_we;
    assign flash_req  = bus_req && !bus_addr[4];
    assign boot_req2  = bus_req &&  bus_addr[4];
    assign bus_ack    = bus_addr[4] ? boot_ack2   : flash_ack;
    assign bus_rdata  = bus_addr[4] ? boot_rdata2 : flash_rdata;

    logic        m_req, m_we;
    logic [15:0] m_addr, m_wdata, m_rdata;
    logic        m_ack;

    logic        f_start, f_abort, f_valid, f_ack, f_busy;
    logic [23:0] f_addr;
    logic [15:0] f_len;
    logic [7:0]  f_data;

    logic        boot_start, boot_done, boot_ok, busy, auto_boot;
    logic [15:0] boot_entry, boot_stack;

    logic        flash_sck, flash_cs_n, flash_mosi, flash_miso;
    logic        flash_irq, id_ok;
    logic [23:0] jedec_id;

    int          errors = 0, checks = 0;
    logic [15:0] exp_words [0:IMG_WORDS_N-1];

    // ---------------------------------------------------------------- DUTs
    sv16_boot dut (
        .clk(clk), .rst_n(rst_n),
        .addr(addr), .wdata(wdata), .rdata(boot_rdata2),
        .req(boot_req2), .we(we), .ack(boot_ack2),
        .m_req(m_req), .m_we(m_we), .m_addr(m_addr), .m_wdata(m_wdata),
        .m_ack(m_ack), .m_rdata(m_rdata),
        .f_start(f_start), .f_addr(f_addr), .f_len(f_len),
        .f_valid(f_valid), .f_data(f_data), .f_ack(f_ack), .f_abort(f_abort),
        .f_busy(f_busy),
        .boot_start(boot_start), .boot_done(boot_done), .boot_ok(boot_ok),
        .boot_entry(boot_entry), .boot_stack(boot_stack),
        .auto_boot(auto_boot), .busy(busy)
    );

    sv16_flash_ctrl flash (
        .clk(clk), .rst_n(rst_n),
        .addr(addr), .wdata(wdata), .rdata(flash_rdata),
        .req(flash_req), .we(we), .ack(flash_ack),
        .boot_start(f_start), .boot_addr(f_addr), .boot_len(f_len),
        .boot_valid(f_valid), .boot_data(f_data), .boot_ack(f_ack),
        .boot_abort(f_abort), .boot_busy(f_busy),
        .flash_sck(flash_sck), .flash_cs_n(flash_cs_n),
        .flash_mosi(flash_mosi), .flash_miso(flash_miso),
        .flash_irq(flash_irq), .id_ok(id_ok), .jedec_id(jedec_id)
    );

    sv16_flash_model #(.MEM_BYTES(131072), .PROG_TICKS(24), .INIT_FILE(FLASH_IMAGE)) model (
        .clk(clk), .rst_n(rst_n),
        .sck(flash_sck), .cs_n(flash_cs_n), .mosi(flash_mosi), .miso(flash_miso)
    );

    sv16_ram #(.DEPTH(16384), .ADDR_WIDTH(14), .INIT_FILE("")) ram (
        .clk(clk), .rst_n(rst_n),
        .addr(m_addr[13:0]), .wdata(m_wdata), .rdata(m_rdata),
        .req(m_req), .we(m_we), .ack(m_ack)
    );

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

    task automatic bus_write(input logic [4:0] a, input logic [15:0] d);
        begin
            @(negedge clk);
            bus_addr = a; bus_wdata = d; bus_we = 1'b1; bus_req = 1'b1;
            do @(posedge clk); while (!bus_ack);
            @(negedge clk);
            bus_req = 1'b0; bus_we = 1'b0;
        end
    endtask

    task automatic bus_read(input logic [4:0] a, output logic [15:0] d);
        begin
            @(negedge clk);
            bus_addr = a; bus_we = 1'b0; bus_req = 1'b1;
            do @(posedge clk); while (!bus_ack);
            d = bus_rdata;
            @(negedge clk);
            bus_req = 1'b0;
        end
    endtask

    // boot loader register block lives at 0xF0A0: bit 4 of the tb bus selects it
    task automatic boot_write(input logic [3:0] a, input logic [15:0] d);
        bus_write({1'b1, a}, d);
    endtask

    task automatic boot_read(input logic [3:0] a, output logic [15:0] d);
        bus_read({1'b1, a}, d);
    endtask

    task automatic run_boot(input logic [23:0] src);
        int guard;
        begin
            boot_write(4'h2, src[15:0]);
            boot_write(4'h3, {8'h00, src[23:16]});
            @(negedge clk);
            boot_start = 1'b1;
            @(negedge clk);
            boot_start = 1'b0;
            guard = 0;
            while (!busy && (guard < 20)) begin
                @(posedge clk); guard++;
            end
            guard = 0;
            while (busy && (guard < 200000)) begin
                @(posedge clk); guard++;
            end
            repeat (4) @(posedge clk);
        end
    endtask

    // ---------------------------------------------------------------- test
    logic [15:0] rd;
    int          i;
    bit          words_match;
    logic [7:0]  hdr_save [0:31];

    initial begin
        $readmemh(IMG_WORDS, exp_words);

        rst_n = 1'b0;
        bus_addr = 5'h00; bus_wdata = 16'h0; bus_req = 1'b0; bus_we = 1'b0;
        boot_start = 1'b0;

        repeat (8) @(posedge clk);
        rst_n = 1'b1;
        repeat (8) @(posedge clk);

        $display("== SV-16 hardware boot loader test ==");
        check(auto_boot == 1'b1, "auto-boot enabled out of reset");

        // ---- 1. boot the packed image from flash offset 0 ----------------
        $display("-- 1. valid image at flash offset 0x000000 --");
        run_boot(24'h000000);
        check(boot_ok == 1'b1, "image verified (boot_ok)");
        boot_read(4'h1, rd);
        check(rd[0] == 1'b0, "BOOT_STAT.BUSY cleared");
        check(rd[1] == 1'b1, "BOOT_STAT.OK set");
        check(rd[3] == 1'b1, "BOOT_STAT.CRC_OK set");
        check(rd[4] == 1'b1, "BOOT_STAT.MAGIC_OK set");
        check(boot_entry == 16'h0000, "entry address = 0x0000");
        check(boot_stack == 16'h3FFE, "stack pointer = 0x3FFE");
        boot_read(4'h7, rd);
        check(rd == IMG_WORDS_N, "payload length = 39 words");
        boot_read(4'h8, rd);
        check(rd == 16'h3A7B, "payload CRC from header = 0x3A7B");
        boot_read(4'h9, rd);
        check(rd == 16'h3A7B, "hardware payload CRC matches");
        boot_read(4'hA, rd);
        check(rd[7:0] == 8'h00, "no error flags after a good image");
        boot_read(4'hD, rd);
        check(rd == 16'h4F4D, "image name 'MO'");
        boot_read(4'hE, rd);
        check(rd == 16'h4F54, "image name 'OT'");
        boot_read(4'hF, rd);
        check(rd == 16'h5452, "image name 'RT'");

        // ---- 2. SRAM must hold the payload ------------------------------
        $display("-- 2. SRAM contents --");
        words_match = 1'b1;
        for (i = 0; i < IMG_WORDS_N; i++) begin
            if (ram.mem[i] !== exp_words[i]) begin
                words_match = 1'b0;
                $display("    word %0d: ram=0x%04x exp_words=0x%04x", i, ram.mem[i], exp_words[i]);
            end
        end
        check(words_match, "SRAM payload matches the assembled program");

        // ---- 3. no valid image anywhere -> clean failure ----------------
        // ADR-019: with the A/B policy on (the default) an automatic boot does
        // not stream BOOT_SRC -- it picks a slot from the records, so "no valid
        // image" means erasing the image itself.  The loader must try both
        // slots, refuse, and report both the reason each slot failed and the
        // fact that no slot was bootable.  (BOOT_SRC is ignored on purpose: it
        // is what gives the rollback its meaning.)
        $display("-- 3. no valid image (both slots erased) --");
        for (i = 0; i < 32; i++) hdr_save[i] = model.mem[i];
        for (i = 0; i < 32; i++) model.mem[i] = 8'hFF;
        run_boot(24'h008000);
        check(boot_ok == 1'b0, "boot_ok low for an invalid image");
        boot_read(4'h1, rd);
        check(rd[2] == 1'b1, "BOOT_STAT.FAIL set");
        check(rd[0] == 1'b0, "engine not stuck busy");
        check(rd[6] == 1'b1, "BOOT_STAT.SLOT_RETRY set (both slots were tried)");
        boot_read(4'hA, rd);
        check(rd[0] == 1'b1, "BOOT_ERR magic error reported");
        check(rd[7] == 1'b1, "BOOT_ERR slot error reported (no slot bootable)");
        // put the image back for the remaining tests
        for (i = 0; i < 32; i++) model.mem[i] = hdr_save[i];

        // ---- 4. retry with the good image -------------------------------
        $display("-- 4. restart after failure --");
        run_boot(24'h000000);
        check(boot_ok == 1'b1, "loader restarts and verifies again");
        boot_read(4'h1, rd);
        check(rd[1] == 1'b1, "BOOT_STAT.OK set after retry");

        // ---- 5. payload corruption is detected --------------------------
        $display("-- 5. corrupted payload --");
        model.mem[IMG_OFFSET + 4] = model.mem[IMG_OFFSET + 4] ^ 8'hFF;  // bit flip
        run_boot(24'h000000);
        check(boot_ok == 1'b0, "boot_ok low with a corrupted payload");
        boot_read(4'hA, rd);
        check(rd[2] == 1'b1, "BOOT_ERR payload CRC error reported");

        $display("== %0d checks, %0d failures ==", checks, errors);
        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL");
        $finish;
    end

    initial begin
        #20_000_000;
        $display("RESULT: FAIL (timeout)");
        $finish;
    end

endmodule
