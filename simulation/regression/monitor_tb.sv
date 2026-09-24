// SV-16 Rev B — Testbench: field firmware update through the ROM monitor
//
// Exercises the recovery / field-update path end to end on the real RTL with a
// blank flash part, exactly the way a user with a serial terminal would:
//
//   blank flash -> boot loader fails -> startup releases the CPU into the boot
//   ROM monitor -> the monitor speaks ASCII over the UART pins -> the host
//   (this testbench) uploads the packed image with the C command -> the monitor
//   programs it into the SPI flash -> verifies it (V) -> boots it (B) -> the CPU
//   runs the freshly uploaded firmware.
//
// Only the UART and SPI pins are touched, so this test doubles as the
// specification for `make upload` and for the serial protocol documented in
// docs/BOOT_AND_PROGRAMMING.md.
//
// Checks
//   1. blank flash: the loader rejects the image and the monitor runs
//   2. the monitor announces itself over the UART
//   3. E erases a sector
//   4. R streams erased flash back (all 0xFF)
//   5. the packed image uploads (per-byte acks, overall CRC accepted)
//   6. the flash now holds the packed image, byte for byte
//   7. R streams that image back, byte for byte
//   8. V reports the image CRC the host computed
//   9. B boots the new firmware: the hardware loader copies the image into
//      SRAM, the CPU jumps to it and the firmware programs GPIO0, PWM0 and
//      the motor-direction pin
//
// Requires build/rom/monitor.hex, build/fw/motor_test_img.hex and
// build/fw/motor_test_words.hex. Run the binary from the repository root.

`timescale 1ns / 1ps

import sv16_pkg::*;

module monitor_tb;

    localparam string ROM_IMAGE     = "build/rom/monitor.hex";
    localparam string IMG_BYTES_HEX = "build/fw/motor_test_img.hex";
    localparam int    IMG_WORDS_N   = 39;                    // payload words
    localparam int    IMG_BYTES     = 32 + IMG_WORDS_N * 2;  // 100 bytes
    localparam int    BIT_TICKS     = 217;                   // 25 MHz / 115200
    localparam int    LOOP_LO       = 30, LOOP_HI = 33;      // motor_test idle loop
    localparam int    MON_LO        = 16'hE000, MON_HI = 16'hE7FF;

    // ------------------------------------------------------------ clock/reset
    logic clk = 1'b0;
    logic ext_rst_n;
    always #20 clk = ~clk;      // 25 MHz board clock, 40 ns period

    // ------------------------------------------------------------------ pins
    logic       uart_rx = 1'b1, uart_tx;
    logic       flash_sck, flash_cs_n, flash_mosi, flash_miso;
    logic       spi0_sck, spi0_cs_n, spi0_mosi;
    wire [15:0] gpio_a, gpio_b;
    logic       pwm_out, motor_dir1, motor_dir2, motor_fault_n;
    logic [3:0] led;

    // ------------------------------------------------------- image under test
    logic [7:0]  img_bytes [0:IMG_BYTES-1];
    logic [15:0] image_crc;          // CRC16 over the whole image (what V returns)

    int          errors = 0, checks = 0;
    bit          monitor_seen = 1'b0;
    bit          seen_loop [0:LOOP_HI+8];
    int          loop_hits = 0;

    sv16_top dut (
        .clk_25m(clk), .ext_rst_n(ext_rst_n),
        .uart_rx(uart_rx), .uart_tx(uart_tx),
        .flash_sck(flash_sck), .flash_cs_n(flash_cs_n),
        .flash_mosi(flash_mosi), .flash_miso(flash_miso),
        .spi0_sck(spi0_sck), .spi0_cs_n(spi0_cs_n), .spi0_mosi(spi0_mosi),
        .spi0_miso(1'b0),
        .gpio_a(gpio_a), .gpio_b(gpio_b),
        .pwm_out(pwm_out), .motor_dir1(motor_dir1), .motor_dir2(motor_dir2),
        .motor_fault_n(motor_fault_n), .led(led)
    );

    // blank flash part: no INIT_FILE means the model comes up erased (0xFF)
    sv16_flash_model #(.MEM_BYTES(131072), .PROG_TICKS(24)) flash (
        .clk(clk), .rst_n(1'b1),
        .sck(flash_sck), .cs_n(flash_cs_n), .mosi(flash_mosi), .miso(flash_miso)
    );

    // =====================================================================
    // Host UART model
    // =====================================================================

    // Transmitter: bit-bang one byte into the SoC's RX pin.
    task automatic uart_send(input logic [7:0] b);
        begin
            uart_rx = 1'b0;                          // start bit
            repeat (BIT_TICKS) @(posedge clk);
            for (int i = 0; i < 8; i++) begin
                uart_rx = b[i];
                repeat (BIT_TICKS) @(posedge clk);
            end
            uart_rx = 1'b1;                          // stop bit
            repeat (BIT_TICKS) @(posedge clk);
        end
    endtask

    task automatic uart_send_str(input string s);
        begin
            for (int i = 0; i < s.len(); i++) uart_send(s[i]);
        end
    endtask

    // Receiver: a textbook UART receiver running continuously from time zero.
    // It is idle until a falling edge, confirms the start bit at its centre,
    // samples the eight data bits one bit time apart and only accepts a byte if
    // the stop bit is high.  A rejected frame parks the receiver until the line
    // has been idle for a full bit time, so it is aligned once and stays
    // aligned: no byte can be lost and no data-bit edge can be taken for a
    // start bit.  Accepted bytes go into a queue that the checks read from, so
    // the checks never race the wire.
    localparam logic [2:0] RX_IDLE  = 3'd0,
                           RX_START = 3'd1,
                           RX_DATA  = 3'd2,
                           RX_STOP  = 3'd3,
                           RX_WAIT  = 3'd4;

    logic [7:0] rx_q [$];

    function automatic string payload_words_str();
        string s2;
        logic [15:0] w;
        s2 = "";
        for (int i = 0; i < 8; i++) begin
            w = {img_bytes[32 + 2*i + 1], img_bytes[32 + 2*i]};
            s2 = {s2, $sformatf("%04x ", w)};
        end
        return s2;
    endfunction

    logic [2:0] rx_state = RX_IDLE;
    int         rx_cnt, rx_idx;
    logic [7:0] rx_sh;

    always @(posedge clk) begin
        case (rx_state)
            RX_IDLE: begin
                rx_cnt <= 0;
                if (uart_tx === 1'b0) rx_state <= RX_START;
            end

            RX_START: begin
                rx_cnt <= rx_cnt + 1;
                if (rx_cnt >= BIT_TICKS / 2) begin     // centre of the start bit
                    rx_cnt   <= 0;
                    rx_idx   <= 0;
                    rx_state <= (uart_tx === 1'b0) ? RX_DATA : RX_WAIT;
                end
            end

            RX_DATA: begin
                rx_cnt <= rx_cnt + 1;
                if (rx_cnt >= BIT_TICKS) begin         // centre of data bit `rx_idx`
                    rx_cnt <= 0;
                    rx_sh  <= {uart_tx, rx_sh[7:1]};   // LSB first
                    if (rx_idx == 3'd7) rx_state <= RX_STOP;
                    else                rx_idx   <= rx_idx + 1;
                end
            end

            RX_STOP: begin
                rx_cnt <= rx_cnt + 1;
                if (rx_cnt >= BIT_TICKS) begin         // centre of the stop bit
                    rx_cnt <= 0;
                    if (uart_tx === 1'b1) begin
                        rx_q.push_back(rx_sh);
                        rx_state <= RX_IDLE;
                    end else begin
                        // rejected frame: re-align on the next idle line
                        rx_state <= RX_WAIT;           // framing error
                    end
                end
            end

            RX_WAIT: begin                             // wait for a clean idle line
                rx_cnt <= (uart_tx === 1'b1) ? (rx_cnt + 1) : 0;
                if ((uart_tx === 1'b1) && (rx_cnt >= BIT_TICKS)) begin
                    rx_cnt   <= 0;
                    rx_state <= RX_IDLE;
                end
            end

            default: rx_state <= RX_IDLE;
        endcase
    end

    task automatic rx_flush;
        logic [7:0] junk;
        begin
            while (rx_q.size() != 0) junk = rx_q.pop_front();
        end
    endtask

    // Pop one byte, waiting up to `limit` clock cycles for it.
    task automatic rx_byte(output logic [7:0] b, output bit ok,
                           input int limit = 200000);
        int guard;
        begin
            ok    = 1'b0;
            b     = 8'h00;
            guard = 0;
            while ((rx_q.size() == 0) && (guard < limit)) begin
                @(posedge clk);
                guard++;
            end
            if (rx_q.size() != 0) begin
                b  = rx_q.pop_front();
                ok = 1'b1;
            end
        end
    endtask

    // Collect everything the monitor sends until the line goes quiet for a
    // while.  Checking for a reply substring is immune to how the prompt bytes
    // interleave with the reply, which is what makes this test stable.
    task automatic collect_reply(output string reply);
        begin
            logic [7:0] b;
            bit         ok;
            reply = "";
            rx_byte(b, ok, 200000);
            while (ok) begin                              // 8 ms of silence ends it
                reply = {reply, b[7:0]};
                rx_byte(b, ok, 200000);
            end
        end
    endtask

    function automatic bit str_contains(input string hay, input string needle);
        begin
            str_contains = 1'b0;
            if ((needle.len() != 0) && (hay.len() >= needle.len())) begin
                for (int i = 0; i + needle.len() <= hay.len(); i++) begin
                    if (hay.substr(i, i + needle.len() - 1) == needle) begin
                        str_contains = 1'b1;
                        break;
                    end
                end
            end
        end
    endfunction

    // Print one byte as two hex characters, as the monitor's R command does.
    function automatic string hex2str(input logic [7:0] v);
        begin
            hex2str = {hex_digit(v[7:4]), hex_digit(v[3:0])};
        end
    endfunction

    function automatic logic [7:0] hex_digit(input logic [3:0] v);
        begin
            hex_digit = (v < 10) ? (8'h30 + v) : (8'h37 + v);
        end
    endfunction

    task automatic send_hex4(input logic [15:0] v);
        begin
            uart_send(hex_digit(v[15:12]));
            uart_send(hex_digit(v[11:8]));
            uart_send(hex_digit(v[7:4]));
            uart_send(hex_digit(v[3:0]));
        end
    endtask

    task automatic send_hex2(input logic [7:0] v);
        begin
            uart_send(hex_digit(v[7:4]));
            uart_send(hex_digit(v[3:0]));
        end
    endtask

    task automatic check(input bit cond, input string name);
        begin
            checks++;
            if (cond) $display("  [PASS] %s", name);
            else begin
                errors++;
                $display("  [FAIL] %s", name);
            end
        end
    endtask

    // CRC16-CCITT, poly 0x1021, init 0xFFFF — the image format's checksum.
    function automatic logic [15:0] crc16(input logic [15:0] crc,
                                          input logic [7:0]  b);
        logic [15:0] c;
        begin
            c = crc ^ {b, 8'h00};   // CRC16 is MSB-first
            for (int i = 0; i < 8; i++)
                c = c[15] ? ((c << 1) ^ 16'h1021) : (c << 1);
            crc16 = c;
        end
    endfunction

    task automatic reset_dut;
        begin
            ext_rst_n = 1'b0;
            repeat (20) @(posedge clk);
            ext_rst_n = 1'b1;
            repeat (20) @(posedge clk);
        end
    endtask

    task automatic wait_for_monitor(output bit reached);
        int n;
        begin
            reached = 1'b0;
            n = 0;
            while ((dut.u_startup.sstate != 3'd3) && (n < 2_000_000)) begin
                @(posedge clk);
                n++;
            end
            reached = (dut.u_startup.sstate == 3'd3);
        end
    endtask

    // ----------------------------------------------------------- watchdogs
    always @(posedge clk) begin
        if (dut.dbg_pc >= MON_LO && dut.dbg_pc <= MON_HI) monitor_seen <= 1'b1;
        if (dut.dbg_pc >= LOOP_LO && dut.dbg_pc <= LOOP_HI) begin
            if (!seen_loop[dut.dbg_pc]) begin
                seen_loop[dut.dbg_pc] <= 1'b1;
                loop_hits++;
            end
        end
    end

    // ---------------------------------------------------------------- stimulus
    logic [7:0]  b;
    bit          ok, bytes_match, reached;
    string       line;
    int          dots, guard;

    initial begin
        $display("== SV-16 ROM monitor / field firmware update test ==");
        ext_rst_n = 1'b0;
        for (int i = 0; i < IMG_BYTES; i++) img_bytes[i] = 8'h00;

        $readmemh(ROM_IMAGE,     dut.u_rom.mem);
        $readmemh(IMG_BYTES_HEX, img_bytes);

        // --- host-side model of the packed image -------------------------
        image_crc = 16'hFFFF;
        for (int i = 0; i < IMG_BYTES; i++) image_crc = crc16(image_crc, img_bytes[i]);
        check(image_crc == {img_bytes[1], img_bytes[0]} ||
              image_crc != 16'h0000, "host CRC model computed");   // sanity only
        $display("    image: %0d bytes, header words=%0d, hdr CRC=0x%04x, payload CRC=0x%04x",
                 IMG_BYTES, {img_bytes[7], img_bytes[6]},
                 {img_bytes[21], img_bytes[20]}, {img_bytes[23], img_bytes[22]});

        // ---- 1. blank flash -------------------------------------------------
        $display("-- 1. blank flash falls back to the monitor --  @%0t", $time);
        reset_dut;
        wait_for_monitor(reached);
        check(reached, "startup entered the monitor state");
        repeat (4) @(posedge clk);
        check(dut.rom_monitor == 1'b1, "rom_monitor flag set");
        check(dut.boot_ready == 1'b1, "boot loader rejected blank flash");
        check(dut.dbg_pc >= MON_LO && dut.dbg_pc <= MON_HI,
              "CPU released inside the boot ROM");

        // ---- 2. banner ------------------------------------------------------
        $display("-- 2. monitor banner --  @%0t", $time);
        collect_reply(line);
        check(str_contains(line, "SV-16 monitor v1"), "monitor sent its banner");

        // ---- 3. E (erase sector) -------------------------------------------
        $display("-- 3. E (erase sector) --  @%0t", $time);
        rx_flush;
        uart_send_str("E0000");
        uart_send(8'h0D);
        collect_reply(line);
        check(str_contains(line, "+OK"), "erase answered +OK");

        // ---- 4. R (stream the first bytes back) ----------------------------
        $display("-- 4. R (read 16 bytes) --  @%0t", $time);
        begin
            string want;
            want = "=";
            for (int i = 0; i < 16; i++) want = {want, hex2str(img_bytes[i])};
            $display("    note: flash is still erased here, all bytes read 0xFF");
        end
        rx_flush;
        uart_send_str("R0000");
        send_hex4(16'h0010);
        uart_send(8'h0D);
        begin
            string want;
            want = "=";
            for (int i = 0; i < 16; i++) want = {want, hex2str(8'hFF)};
            collect_reply(line);
            check(str_contains(line, want), "R streams erased flash back");
        end

        // ---- 5. C (upload the packed image) --------------------------------
        $display("-- 5. C (upload %0d bytes) --  @%0t", IMG_BYTES, $time);
        rx_flush;
        uart_send(8'h43);                     // 'C'
        send_hex4(16'h0000);                  // destination byte address
        send_hex4(IMG_BYTES[15:0]);           // length in bytes
        send_hex4(image_crc);                 // CRC16 of the uploaded bytes
        for (int i = 0; i < IMG_BYTES; i++) begin
            send_hex2(img_bytes[i]);
            // the monitor acknowledges every byte with '.'; reading the ack
            // while sending the next byte keeps the two in lock-step
            rx_byte(b, ok);
            if (ok && b == 8'h2E) dots++;
            else if (ok) $display("    unexpected ack 0x%02x at byte %0d", b, i);
        end
        $display("    per-byte acks: %0d", dots);
        check(dots == IMG_BYTES, "monitor acked every uploaded byte");
        collect_reply(line);
        check(str_contains(line, "+OK"), "upload answered +OK (upload CRC accepted)");

        // ---- 6. flash contents ---------------------------------------------
        $display("-- 6. programmed flash --  @%0t", $time);
        bytes_match = 1'b1;
        for (int i = 0; i < IMG_BYTES; i++)
            if (flash.mem[i] !== img_bytes[i]) begin
                bytes_match = 1'b0;
                if (bytes_match == 1'b0 && i < 8)
                    $display("    byte %0d: flash=0x%02X expected=0x%02X",
                             i, flash.mem[i], img_bytes[i]);
            end
        check(bytes_match, "flash holds the uploaded image byte for byte");

        // ---- 7. R again: the image really is on the wire -------------------
        $display("-- 7. R (read the image back) --  @%0t", $time);
        rx_flush;
        uart_send_str("R0000");
        send_hex4(IMG_BYTES[15:0]);
        uart_send(8'h0D);
        begin
            string want;
            want = "=";
            for (int i = 0; i < IMG_BYTES; i++) want = {want, hex2str(img_bytes[i])};
            collect_reply(line);
            check(str_contains(line, want), "R streams the programmed image back");
        end

        // ---- 8. V (image CRC) ----------------------------------------------
        $display("-- 8. V (image CRC) --  @%0t", $time);
        rx_flush;
        uart_send_str("V0000");
        uart_send(8'h0D);
        begin
            string want;
            want = {"=", hex2str(image_crc[15:8]), hex2str(image_crc[7:0])};
            collect_reply(line);
            $display("    replies: %s (host expects %s)", line, want);
            check(str_contains(line, want), "monitor image CRC matches the host");
        end

        // ---- 9. B (boot the uploaded image) --------------------------------
        $display("-- 9. B (boot the uploaded image) --  @%0t", $time);
        rx_flush;
        uart_send_str("B");
        uart_send(8'h0D);
        collect_reply(line);
        $display("    B reply: %s", line);
        check(str_contains(line, "+OK booting"), "boot command accepted");

        // ---- 9a. what the loader actually put in SRAM ------------------------
        begin
            int bad = -1;
            for (int i = 0; i < (IMG_BYTES - 32)/2; i++) begin
                logic [15:0] want_w;
                want_w = {img_bytes[32 + 2*i + 1], img_bytes[32 + 2*i]};
                if (dut.u_ram.mem[i] !== want_w) begin
                    if (bad < 0) begin
                        bad = i;
                        $display("    RAM word %0d: got 0x%04x want 0x%04x", i,
                                 dut.u_ram.mem[i], want_w);
                    end
                end
            end
            if (bad < 0) $display("    SRAM payload matches the image (%0d words)", (IMG_BYTES-32)/2);
            else begin
                $display("    RAM[0..7]: %04x %04x %04x %04x %04x %04x %04x %04x",
                         dut.u_ram.mem[0], dut.u_ram.mem[1], dut.u_ram.mem[2], dut.u_ram.mem[3],
                         dut.u_ram.mem[4], dut.u_ram.mem[5], dut.u_ram.mem[6], dut.u_ram.mem[7]);
                $display("    WANT payload: %s", payload_words_str());
            end
        end

        guard = 0;
        while ((loop_hits < (LOOP_HI - LOOP_LO + 1)) && (guard < 4_000_000)) begin
            @(posedge clk); guard++;
        end

        begin
            bit all_loop_seen = 1'b1;
            for (int i = LOOP_LO; i <= LOOP_HI; i++) if (!seen_loop[i]) all_loop_seen = 1'b0;
            check(all_loop_seen, "CPU is running the freshly uploaded firmware");
        end

        check(dut.u_gpio0.dir_reg == 16'h003F, "uploaded firmware programmed GPIO direction");
        check(dut.u_pwm0.period_reg == 16'd1250, "uploaded firmware programmed the PWM period");
        check(dut.u_pwm0.ctrl_reg[0] == 1'b1, "uploaded firmware enabled the PWM");
        check(dut.motor_dir1 == 1'b1, "uploaded firmware set the motor direction");
        check(monitor_seen == 1'b1, "the monitor really was the fallback");

        $display("== %0d checks, %0d failures ==", checks, errors);
        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL");
        $finish;
    end

    initial begin
        #300_000_000;
        $display("RESULT: FAIL (timeout)");
        $finish;
    end

endmodule : monitor_tb
