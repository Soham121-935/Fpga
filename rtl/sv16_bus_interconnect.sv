// SV-16 Rev A — System Bus Interconnect & Address Decoder
// Module: sv16_bus_interconnect
//
// Decodes 16-bit word addresses per docs/MEMORY_MAP.md:
//   0x0000 - 0x1FFF : Internal RAM (8K words: Code + Data + Stack)
//   0xF010 - 0xF013 : GPIO Controller
//   0xF020 - 0xF023 : Timer 0
//   0xF030 - 0xF033 : PWM Controller 0
//   0xF040 - 0xF043 : UART 0
//   Default / Unmapped: Returns 0x0000 with immediate ack

`timescale 1ns / 1ps

module sv16_bus_interconnect (
    input  logic        clk,
    input  logic        rst_n,

    // Master Bus (from CPU Core)
    input  logic [15:0] m_bus_addr,
    input  logic [15:0] m_bus_wdata,
    output logic [15:0] m_bus_rdata,
    input  logic        m_bus_req,
    input  logic        m_bus_we,
    output logic        m_bus_ack,

    // Slave Port 0: Internal RAM (0x0000 - 0x1FFF)
    output logic [12:0] ram_addr,
    output logic [15:0] ram_wdata,
    input  logic [15:0] ram_rdata,
    output logic        ram_we,
    output logic        ram_req,
    input  logic        ram_ack,

    // Slave Port 1: GPIO (0xF010 - 0xF013)
    output logic [3:0]  gpio_addr,
    output logic [15:0] gpio_wdata,
    input  logic [15:0] gpio_rdata,
    output logic        gpio_we,
    output logic        gpio_req,
    input  logic        gpio_ack,

    // Slave Port 2: Timer 0 (0xF020 - 0xF023)
    output logic [3:0]  timer_addr,
    output logic [15:0] timer_wdata,
    input  logic [15:0] timer_rdata,
    output logic        timer_we,
    output logic        timer_req,
    input  logic        timer_ack,

    // Slave Port 3: PWM 0 (0xF030 - 0xF033)
    output logic [3:0]  pwm_addr,
    output logic [15:0] pwm_wdata,
    input  logic [15:0] pwm_rdata,
    output logic        pwm_we,
    output logic        pwm_req,
    input  logic        pwm_ack,

    // Slave Port 4: UART 0 (0xF040 - 0xF043)
    output logic [3:0]  uart_addr,
    output logic [15:0] uart_wdata,
    input  logic [15:0] uart_rdata,
    output logic        uart_we,
    output logic        uart_req,
    input  logic        uart_ack
);

    // Address range decode flags
    logic sel_ram;
    logic sel_gpio;
    logic sel_timer;
    logic sel_pwm;
    logic sel_uart;
    logic sel_unmapped;

    assign sel_ram   = (m_bus_addr <= 16'h1FFF);
    assign sel_gpio  = (m_bus_addr[15:4] == 12'hF01);
    assign sel_timer = (m_bus_addr[15:4] == 12'hF02);
    assign sel_pwm   = (m_bus_addr[15:4] == 12'hF03);
    assign sel_uart  = (m_bus_addr[15:4] == 12'hF04);
    assign sel_unmapped = m_bus_req && !sel_ram && !sel_gpio && !sel_timer && !sel_pwm && !sel_uart;

    // Route to RAM
    assign ram_addr  = m_bus_addr[12:0];
    assign ram_wdata = m_bus_wdata;
    assign ram_we    = m_bus_we;
    assign ram_req   = m_bus_req && sel_ram;

    // Route to GPIO
    assign gpio_addr  = m_bus_addr[3:0];
    assign gpio_wdata = m_bus_wdata;
    assign gpio_we    = m_bus_we;
    assign gpio_req   = m_bus_req && sel_gpio;

    // Route to Timer
    assign timer_addr  = m_bus_addr[3:0];
    assign timer_wdata = m_bus_wdata;
    assign timer_we    = m_bus_we;
    assign timer_req   = m_bus_req && sel_timer;

    // Route to PWM
    assign pwm_addr  = m_bus_addr[3:0];
    assign pwm_wdata = m_bus_wdata;
    assign pwm_we    = m_bus_we;
    assign pwm_req   = m_bus_req && sel_pwm;

    // Route to UART
    assign uart_addr  = m_bus_addr[3:0];
    assign uart_wdata = m_bus_wdata;
    assign uart_we    = m_bus_we;
    assign uart_req   = m_bus_req && sel_uart;

    // Unmapped ack generation
    logic unmapped_ack_reg;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            unmapped_ack_reg <= 1'b0;
        end else begin
            unmapped_ack_reg <= sel_unmapped;
        end
    end

    // Master Read Data & Ack Multiplexing
    always_comb begin
        if (sel_ram) begin
            m_bus_rdata = ram_rdata;
            m_bus_ack   = ram_ack;
        end else if (sel_gpio) begin
            m_bus_rdata = gpio_rdata;
            m_bus_ack   = gpio_ack;
        end else if (sel_timer) begin
            m_bus_rdata = timer_rdata;
            m_bus_ack   = timer_ack;
        end else if (sel_pwm) begin
            m_bus_rdata = pwm_rdata;
            m_bus_ack   = pwm_ack;
        end else if (sel_uart) begin
            m_bus_rdata = uart_rdata;
            m_bus_ack   = uart_ack;
        end else begin
            m_bus_rdata = 16'h0000;
            m_bus_ack   = unmapped_ack_reg;
        end
    end

endmodule : sv16_bus_interconnect
