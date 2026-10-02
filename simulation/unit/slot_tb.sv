// SV-16 Rev B — Testbench: A/B image slots and rollback (ADR-019)
//
// The boot_tb checks the single-image path.  This one checks the *policy*: two
// application slots, slot records in the image header, a trial period that has
// to survive a reset, and a rollback that happens with no host attached.
//
// Harness: the boot loader, the flash controller and the SPI flash model wired
// exactly as sv16_top wires them, including the slot-record program handshake
// (the one path boot_tb cannot reach, because its images have no record).
//
// The flash model implements real page-program physics (a program can only
// clear bits), which is what makes the record encoding testable: if a state
// transition were not a bit-subset of the state it came from, the read-back
// check in the loader would fail here and not on hardware.
//
// Checks
//   1. two images with no record: the pick settles on slot 0, BOOT_SRC ignored
//   2. a PENDING image in slot 1 wins the pick; the loader writes TRIED before
//      releasing the CPU (the trial survives a reset), BOOT_STAT.TRIAL is set
//   3. a restart with the record still TRIED retires slot 1 to BAD, sets
//      SLOT_RETRY and boots the GOOD image in slot 0  -> the rollback
//   4. a second restart boots slot 0 again, with no further flash writes
//   5. CONFIRM promotes the running TRIAL image to GOOD and retires the other
//      slot, so the update sticks instead of reverting to slot 0
//   6. a torn record (a state byte that only a power cut can produce) is
//      treated as BAD, never as a bootable image
//   7. BOOT_CTRL[4] NOSLOT=1 boots BOOT_SRC and ignores the records
//
// Requires build/fw/motor_test_img.hex and build/fw/wdt_hang_img.hex
// (`make firmware`); run the binary from the repository root.

`timescale 1ns / 1ps

module slot_tb;

    logic clk = 1'b0;
    always #10 clk = ~clk;          // 50 MHz

    localparam string IMG0_BYTES = "build/fw/motor_test_img.hex";
    localparam string IMG1_BYTES = "build/fw/wdt_hang_img.hex";
    localparam string IMG0_WORDS = "build/fw/motor_test_words.hex";
    localparam string IMG1_WORDS = "build/fw/wdt_hang_words.hex";

    localparam logic [23:0] SLOT0_BASE = 24'h00_0000;
    localparam logic [23:0] SLOT1_BASE = 24'h00_8000;   // ADR-019: 32 KB slots
    localparam logic [23:0] REC_OFFSET = 24'h00_0018;   // image header, 0x18/0x19
    localparam logic [7:0]  REC_SYNC   = 8'hA5;
    localparam logic [7:0]  ST_PEND    = 8'h1F;
    localparam logic [7:0]  ST_TRIED   = 8'h0F;
    localparam logic [7:0]  ST_GOOD    = 8'h07;
    localparam logic [7:0]  ST_BAD     = 8'h04;

    // ------------------------------------------------------------ signals
    logic        rst_n;
    logic [4:0]  bus_addr;      // [4] = target: 0 = flash controller, 1 = boot
    logic [15:0] bus_wdata, bus_rdata;
    logic        bus_req, bus_we, bus_ack;

    logic [3:0]  addr;
    logic [15:0] wdata, rdata;
    logic        we;
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

    // ADR-019 slot-record handshake: loader -> flash controller
    logic        slot_wr_req;
    logic [23:0] slot_wr_addr;
    logic [7:0]  slot_wr_data;
    logic [1:0]  slot_wr_done;

    int          errors = 0, checks = 0;
    int          i;
    logic [15:0] rd;

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
        .auto_boot(auto_boot), .busy(busy),
        .slot_wr_req(slot_wr_req), .slot_wr_addr(slot_wr_addr),
        .slot_wr_data(slot_wr_data), .slot_wr_done(slot_wr_done)
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
        .flash_irq(flash_irq), .id_ok(id_ok), .jedec_id(jedec_id),
        .slot_wr_req(slot_wr_req), .slot_wr_addr(slot_wr_addr),
        .slot_wr_data(slot_wr_data), .slot_wr_done(slot_wr_done)
    );

    sv16_flash_model #(.MEM_BYTES(131072), .PROG_TICKS(24)) model (
        .clk(clk), .rst_n(rst_n),
        .sck(flash_sck), .cs_n(flash_cs_n), .mosi(flash_mosi), .miso(flash_miso)
    );

    sv16_ram #(.DEPTH(16384), .ADDR_WIDTH(14), .INIT_FILE("")) ram (
        .clk(clk), .rst_n(rst_n),
        .addr(m_addr[13:0]), .wdata(m_wdata), .rdata(m_rdata),
        .req(m_req), .we(m_we), .ack(m_ack)
    );

    logic [7:0] img [0:4095];
    logic [15:0] img0_words [0:63];
    logic [15:0] img1_words [0:63];

    // ------------------------------------------------------------- helpers
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

    task automatic boot_write(input logic [3:0] a, input logic [15:0] d);
        bus_write({1'b1, a}, d);
    endtask

    task automatic boot_read(input logic [3:0] a, output logic [15:0] d);
        bus_read({1'b1, a}, d);
    endtask

    // start an automatic load (BOOT_SRC is set, but the policy ignores it while
    // the slot records are in charge -- that is the point of the test)
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
            // `busy` drops as soon as the byte stream ends, which can be
            // before the slot logic has finished writing a record: boot_done is
            // the end of the whole attempt, so wait for both.
            guard = 0;
            while ((busy || !boot_done) && (guard < 400000)) begin
                @(posedge clk); guard++;
            end
            repeat (8) @(posedge clk);
        end
    endtask

    // a reset of the whole part: loader state gone, flash records remain.  This
    // is exactly what the watchdog (ADR-017) does, and it is the reset that the
    // trial period has to survive.
    task automatic part_reset();
        begin
            rst_n = 1'b0;
            repeat (8) @(posedge clk);
            rst_n = 1'b1;
            repeat (8) @(posedge clk);
        end
    endtask

    // Load a byte-per-line hex image (the packer's <prefix>_img.hex) into `img`
    // and return its length.  The length comes from the image's own header
    // (payload words at offset 6), so no file I/O beyond $readmemh is needed.
    // A function cannot write through an array input in Verilog, hence the
    // module-level `img` and a task.
    task automatic load_img(input string path, output int len);
        int words;
        begin
            for (int k = 0; k < 4096; k++) img[k] = 8'hFF;
            $readmemh(path, img);
            if (img[0] !== 8'h53 || img[1] !== 8'h56) begin
                $display("FATAL: %s is not a packed SV-16 image (magic)", path);
                $finish;
            end
            words = (int'(img[7]) << 8) | int'(img[6]);
            len   = 32 + 2 * words;
        end
    endtask

    function automatic logic [23:0] rec_addr(input int slot);
        rec_addr = (slot == 0) ? SLOT0_BASE + REC_OFFSET : SLOT1_BASE + REC_OFFSET;
    endfunction

    task automatic record_write(input int slot, input logic [7:0] sync,
                                input logic [7:0] state);
        begin
            model.mem[rec_addr(slot)]     = sync;
            model.mem[rec_addr(slot) + 1] = state;
        end
    endtask

    task automatic record_read(input int slot, input string what,
                               input logic [7:0] want_state);
        begin
            check(model.mem[rec_addr(slot)] === REC_SYNC,
                  $sformatf("%s: record sync byte", what));
            check(model.mem[rec_addr(slot) + 1] === want_state,
                  $sformatf("%s: record state 0x%02X (got 0x%02X)", what,
                            want_state, model.mem[rec_addr(slot) + 1]));
        end
    endtask

    task automatic check_slot(input int want_slot, input bit want_trial,
                              input int want_words, input string what);
        logic [15:0] st;
        bit          match;
        begin
            boot_read(4'h1, st);
            check(boot_ok == 1'b1, {what, ": image verified"});
            check(st[5] == want_slot[0], {what, ": BOOT_STAT.SLOT selects the image"});
            check(st[7] == want_trial, {what, ": BOOT_STAT.TRIAL"});
            boot_read(4'h7, st);
            check(st == want_words, $sformatf("%s: payload is the expected image (%0d words)",
                                              what, want_words));
            match = 1'b1;
            for (i = 0; i < want_words; i++) begin
                if (ram.mem[i] !== (want_slot == 0 ? img0_words[i] : img1_words[i]))
                    match = 1'b0;
            end
            check(match, {what, ": SRAM holds that image's payload"});
        end
    endtask

    // ---------------------------------------------------------------- test
    int len0, len1;

    initial begin
        $readmemh(IMG0_WORDS, img0_words);
        $readmemh(IMG1_WORDS, img1_words);

        rst_n = 1'b0;
        bus_addr = 5'h00; bus_wdata = 16'h0; bus_req = 1'b0; bus_we = 1'b0;
        boot_start = 1'b0;

        repeat (8) @(posedge clk);
        rst_n = 1'b1;
        repeat (8) @(posedge clk);

        // Two real images: motor_test in slot 0, wdt_hang in slot 1.  Neither
        // has a record yet (the packer only writes one with --slot), so both
        // read as "no record": bootable, untried.
        load_img(IMG0_BYTES, len0);
        for (i = 0; i < len0; i++) model.mem[SLOT0_BASE + i] = img[i];
        load_img(IMG1_BYTES, len1);
        for (i = 0; i < len1; i++) model.mem[SLOT1_BASE + i] = img[i];

        $display("== SV-16 A/B slot + rollback test ==");
        $display("   slot 0 = %0d bytes (motor_test), slot 1 = %0d bytes (wdt_hang)",
                 len0, len1);

        // ---- 1. two record-less images: slot 0 wins the tie --------------
        $display("-- 1. no records: the pick settles on slot 0 --");
        run_boot(24'h008000);            // ask for slot 1: the policy overrides
        check_slot(0, 1'b0, 39, "1. plain images");
        check(model.mem[rec_addr(0)] === 8'h00 && model.mem[rec_addr(0)+1] === 8'h00,
              "1. slot 0 has no record (header padding)");
        check(model.mem[rec_addr(1)] === 8'h00 && model.mem[rec_addr(1)+1] === 8'h00,
              "1. slot 1 has no record (header padding)");

        // ---- 2. a freshly installed image (PENDING) gets its trial -------
        $display("-- 2. PENDING slot 1 wins and is put on trial --");
        record_write(0, REC_SYNC, ST_GOOD);      // the confirmed fallback
        record_write(1, REC_SYNC, ST_PEND);      // the new install
        run_boot(24'h000000);
        check_slot(1, 1'b1, 27, "2. pending install");
        record_read(1, "2. slot 1 marked TRIED before the hand-over", ST_TRIED);
        boot_read(4'hA, rd);
        check(rd[7:0] == 8'h00, "2. no error flags");

        // ---- 3. restart without a CONFIRM -> rollback --------------------
        // This is the watchdog case: the new image never confirmed, the part
        // came back, and the trial must end in a rollback with no host help.
        $display("-- 3. restart inside the trial: retire slot 1, boot slot 0 --");
        part_reset();
        run_boot(24'h008000);                    // ask for the bad slot
        check_slot(0, 1'b0, 39, "3. rollback");
        record_read(1, "3. failed trial retired", ST_BAD);
        boot_read(4'h1, rd);
        check(rd[6] == 1'b1, "3. BOOT_STAT.SLOT_RETRY set");
        check(rd[7] == 1'b0, "3. the fallback image is not on trial");

        // ---- 4. the retired slot stays retired ---------------------------
        $display("-- 4. restart again: the BAD record is never picked --");
        part_reset();
        run_boot(24'h008000);
        check_slot(0, 1'b0, 39, "4. second restart");
        boot_read(4'h1, rd);
        check(rd[6] == 1'b0, "4. no rollback needed this time");
        record_read(1, "4. record unchanged", ST_BAD);

        // ---- 5. CONFIRM makes an update stick ----------------------------
        $display("-- 5. CONFIRM promotes TRIAL -> GOOD and retires slot 0 --");
        record_write(1, REC_SYNC, ST_PEND);      // reinstall the new image
        run_boot(24'h000000);
        check_slot(1, 1'b1, 27, "5. trial boot");
        boot_write(4'h0, 16'h0040);              // BOOT_CTRL[6] = SLOT_CNF
        repeat (20000) @(posedge clk);           // two page programs
        boot_read(4'h1, rd);
        check(rd[7] == 1'b0, "5. BOOT_STAT.TRIAL cleared by CONFIRM");
        record_read(1, "5. slot 1 confirmed", ST_GOOD);
        record_read(0, "5. slot 0 retired", ST_BAD);
        part_reset();
        run_boot(24'h000000);
        check_slot(1, 1'b0, 27, "5. the update survives the reset");

        // ---- 6. a torn record is never bootable --------------------------
        // 0x0E is reachable only by an interrupted program: sync written, state
        // byte half programmed.  It must not decode as a state we trust.
        $display("-- 6. torn record -> BAD, never booted --");
        record_write(0, REC_SYNC, ST_GOOD);
        record_write(1, REC_SYNC, 8'h0E);
        run_boot(24'h000000);
        check_slot(0, 1'b0, 39, "6. torn slot skipped");
        check(model.mem[rec_addr(1) + 1] === 8'h0E,
              "6. the torn record is left alone (it is already unbootable)");
        boot_read(4'hA, rd);
        check(rd[7] == 1'b1, "6. BOOT_ERR.SLOT reports the unusable record");

        // ---- 7. the escape hatch: NOSLOT boots BOOT_SRC ------------------
        $display("-- 7. BOOT_CTRL[4] NOSLOT=1 ignores the records --");
        boot_write(4'h0, 16'h0018);              // AUTO + NOSLOT
        run_boot(24'h008000);                    // raw source: slot 1's image
        check(boot_ok == 1'b1, "7. BOOT_SRC image verified despite its BAD record");
        boot_read(4'h7, rd);
        check(rd == 27, "7. that image's payload is in SRAM");
        check(model.mem[rec_addr(1)] === 8'hA5 &&
              model.mem[rec_addr(1) + 1] === 8'h0E,
              "7. record untouched by a raw boot");

        $display("== %0d checks, %0d failures ==", checks, errors);
        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL");
        $finish;
    end

    initial begin
        #40_000_000;
        $display("RESULT: FAIL (timeout)");
        $finish;
    end

endmodule
