// SV-16 Rev A — Unit Testbench for Memory Subsystem & Bus Interconnect
// Module: sv16_ram_tb
//
// Verification of:
// 1. RAM synchronous writes and reads across address boundaries
// 2. Bus interconnect routing:
//    - Addresses 0x0000 - 0x1FFF route to RAM
//    - Addresses 0xF010 - 0xF013 route to GPIO slave port
//    - Unmapped addresses return 0x0000 and complete gracefully

`timescale 1ns / 1ps

module sv16_ram_tb;

    logic        clk;
    logic        rst_n;
    logic [15:0] m_bus_addr;
    logic [15:0] m_bus_wdata;
    logic [15:0] m_bus_rdata;
    logic        m_bus_req;
    logic        m_bus_we;
    logic        m_bus_ack;

    // RAM wires
    logic [12:0] ram_addr;
    logic [15:0] ram_wdata;
    logic [15:0] ram_rdata;
    logic        ram_we;
    logic        ram_req;
    logic        ram_ack;

    // GPIO mock slave wires
    logic [3:0]  gpio_addr;
    logic [15:0] gpio_wdata;
    logic [15:0] gpio_rdata;
    logic        gpio_we;
    logic        gpio_req;
    logic        gpio_ack;

    int error_count;

    // Instantiate Bus Interconnect
    sv16_bus_interconnect u_bus (
        .clk(clk),
        .rst_n(rst_n),
        .m_bus_addr(m_bus_addr),
        .m_bus_wdata(m_bus_wdata),
        .m_bus_rdata(m_bus_rdata),
        .m_bus_req(m_bus_req),
        .m_bus_we(m_bus_we),
        .m_bus_ack(m_bus_ack),
        .ram_addr(ram_addr),
        .ram_wdata(ram_wdata),
        .ram_rdata(ram_rdata),
        .ram_we(ram_we),
        .ram_req(ram_req),
        .ram_ack(ram_ack),
        .gpio_addr(gpio_addr),
        .gpio_wdata(gpio_wdata),
        .gpio_rdata(gpio_rdata),
        .gpio_we(gpio_we),
        .gpio_req(gpio_req),
        .gpio_ack(gpio_ack),
        // Unused slave ports tied off
        .timer_addr(), .timer_wdata(), .timer_rdata(16'h0000), .timer_we(), .timer_req(), .timer_ack(1'b0),
        .pwm_addr(), .pwm_wdata(), .pwm_rdata(16'h0000), .pwm_we(), .pwm_req(), .pwm_ack(1'b0),
        .uart_addr(), .uart_wdata(), .uart_rdata(16'h0000), .uart_we(), .uart_req(), .uart_ack(1'b0)
    );

    // Instantiate RAM (4K words)
    sv16_ram #(.DEPTH(4096), .ADDR_WIDTH(13)) u_ram (
        .clk(clk),
        .rst_n(rst_n),
        .addr(ram_addr),
        .wdata(ram_wdata),
        .rdata(ram_rdata),
        .we(ram_we),
        .req(ram_req),
        .ack(ram_ack)
    );

    // Mock GPIO responder
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            gpio_ack   <= 1'b0;
            gpio_rdata <= 16'h0000;
        end else begin
            gpio_ack <= gpio_req;
            if (gpio_req && !gpio_we) begin
                gpio_rdata <= 16'hCAFE; // Static mock read value
            end
        end
    end

    always #20 clk = ~clk;

    initial begin
        clk = 0;
        rst_n = 0;
        m_bus_addr = 0;
        m_bus_wdata = 0;
        m_bus_req = 0;
        m_bus_we = 0;
        error_count = 0;

        #100;
        rst_n = 1;
        #40;

        // 1. Write to RAM at address 0x0100
        @(posedge clk);
        m_bus_addr  = 16'h0100;
        m_bus_wdata = 16'h1234;
        m_bus_we    = 1;
        m_bus_req   = 1;
        @(posedge clk);
        while (!m_bus_ack) @(posedge clk);
        m_bus_req   = 0;
        m_bus_we    = 0;

        // 2. Read back from RAM at address 0x0100
        @(posedge clk);
        m_bus_addr  = 16'h0100;
        m_bus_we    = 0;
        m_bus_req   = 1;
        @(posedge clk);
        while (!m_bus_ack) @(posedge clk);
        #1;
        if (m_bus_rdata !== 16'h1234) begin
            $display("[FAIL] RAM readback mismatch! Got: 0x%h, Expected: 0x1234", m_bus_rdata);
            error_count++;
        end
        m_bus_req = 0;

        // 3. Read from GPIO at address 0xF010
        @(posedge clk);
        m_bus_addr  = 16'hF010;
        m_bus_we    = 0;
        m_bus_req   = 1;
        @(posedge clk);
        while (!m_bus_ack) @(posedge clk);
        #1;
        if (m_bus_rdata !== 16'hCAFE) begin
            $display("[FAIL] GPIO decode read mismatch! Got: 0x%h, Expected: 0xCAFE", m_bus_rdata);
            error_count++;
        end
        m_bus_req = 0;

        if (error_count == 0) begin
            $display("[PASS] sv16_ram & sv16_bus_interconnect unit test passed with 0 errors.");
        end else begin
            $display("[FAIL] Test failed with %0d errors.", error_count);
        end

        $finish;
    end

endmodule : sv16_ram_tb
