// SV-16 Rev A — Complete Microcontroller Top-Level Integration
// Module: sv16_top
//
// Target Hardware: Lattice ECP5 LFE5U-12F-6TG144C
// Package: 144-pin TQFP
//
// Integrates:
// - Reset synchronizer bridge
// - SV-16 16-bit CPU Core (sv16_core)
// - System Bus Interconnect & Address Decoder (sv16_bus_interconnect)
// - On-Chip 8K-word Synchronous BRAM (sv16_ram)
// - 16-bit GPIO Controller (sv16_gpio) driving LEDs and Motor Direction pins
// - 16-bit Hardware Timer 0 (sv16_timer)
// - 16-bit Hardware PWM Controller 0 (sv16_pwm) driving external motor stage
// - Hardware UART 0 (sv16_uart) for serial communication
// - Hardware safety motor fault input line

`timescale 1ns / 1ps

module sv16_top (
    input  logic        clk_25m,
    input  logic        ext_rst_n,

    // UART Interface
    input  logic        uart_rx,
    output logic        uart_tx,

    // Status / User LEDs
    output logic [3:0]  led,

    // Motor Driver Interface (External H-Bridge)
    output logic        pwm_out,
    output logic        motor_dir1,
    output logic        motor_dir2,
    input  logic        motor_fault_n
);

    // 1. Reset Synchronizer
    logic rst_sync1, rst_sync2;
    logic sys_rst_n;

    always_ff @(posedge clk_25m or negedge ext_rst_n) begin
        if (!ext_rst_n) begin
            rst_sync1 <= 1'b0;
            rst_sync2 <= 1'b0;
        end else begin
            rst_sync1 <= 1'b1;
            rst_sync2 <= rst_sync1;
        end
    end
    assign sys_rst_n = rst_sync2;

    // 2. CPU Bus Master Signals
    logic [15:0] cpu_bus_addr;
    logic [15:0] cpu_bus_wdata;
    logic [15:0] cpu_bus_rdata;
    logic        cpu_bus_req;
    logic        cpu_bus_we;
    logic        cpu_bus_ack;

    // Core Debug Signals
    logic [15:0] dbg_pc;
    logic [15:0] dbg_ir;
    logic [15:0] dbg_sr;
    logic [15:0] dbg_sp;
    logic [2:0]  dbg_state;

    // 3. CPU Core Instance
    sv16_core u_cpu (
        .clk(clk_25m),
        .rst_n(sys_rst_n),
        .bus_addr(cpu_bus_addr),
        .bus_wdata(cpu_bus_wdata),
        .bus_rdata(cpu_bus_rdata),
        .bus_req(cpu_bus_req),
        .bus_we(cpu_bus_we),
        .bus_ack(cpu_bus_ack),
        .dbg_pc(dbg_pc),
        .dbg_ir(dbg_ir),
        .dbg_sr(dbg_sr),
        .dbg_sp(dbg_sp),
        .dbg_state(dbg_state)
    );

    // 4. Interconnect Slave Wires
    // RAM
    logic [12:0] ram_addr;
    logic [15:0] ram_wdata;
    logic [15:0] ram_rdata;
    logic        ram_we;
    logic        ram_req;
    logic        ram_ack;

    // GPIO
    logic [3:0]  gpio_addr;
    logic [15:0] gpio_wdata;
    logic [15:0] gpio_rdata;
    logic        gpio_we;
    logic        gpio_req;
    logic        gpio_ack;

    // Timer
    logic [3:0]  timer_addr;
    logic [15:0] timer_wdata;
    logic [15:0] timer_rdata;
    logic        timer_we;
    logic        timer_req;
    logic        timer_ack;

    // PWM
    logic [3:0]  pwm_addr;
    logic [15:0] pwm_wdata;
    logic [15:0] pwm_rdata;
    logic        pwm_we;
    logic        pwm_req;
    logic        pwm_ack;

    // UART
    logic [3:0]  uart_addr;
    logic [15:0] uart_wdata;
    logic [15:0] uart_rdata;
    logic        uart_we;
    logic        uart_req;
    logic        uart_ack;

    // 5. System Bus Interconnect Instance
    sv16_bus_interconnect u_bus (
        .clk(clk_25m),
        .rst_n(sys_rst_n),
        .m_bus_addr(cpu_bus_addr),
        .m_bus_wdata(cpu_bus_wdata),
        .m_bus_rdata(cpu_bus_rdata),
        .m_bus_req(cpu_bus_req),
        .m_bus_we(cpu_bus_we),
        .m_bus_ack(cpu_bus_ack),

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

        .timer_addr(timer_addr),
        .timer_wdata(timer_wdata),
        .timer_rdata(timer_rdata),
        .timer_we(timer_we),
        .timer_req(timer_req),
        .timer_ack(timer_ack),

        .pwm_addr(pwm_addr),
        .pwm_wdata(pwm_wdata),
        .pwm_rdata(pwm_rdata),
        .pwm_we(pwm_we),
        .pwm_req(pwm_req),
        .pwm_ack(pwm_ack),

        .uart_addr(uart_addr),
        .uart_wdata(uart_wdata),
        .uart_rdata(uart_rdata),
        .uart_we(uart_we),
        .uart_req(uart_req),
        .uart_ack(uart_ack)
    );

    // 6. On-Chip BRAM Instance (8K words = 16 KB)
    sv16_ram #(.DEPTH(8192), .ADDR_WIDTH(13)) u_bram (
        .clk(clk_25m),
        .rst_n(sys_rst_n),
        .addr(ram_addr),
        .wdata(ram_wdata),
        .rdata(ram_rdata),
        .we(ram_we),
        .req(ram_req),
        .ack(ram_ack)
    );

    // 7. GPIO Controller Instance
    logic [15:0] gpio_pins_in;
    logic [15:0] gpio_pins_out;
    logic [15:0] gpio_pins_oen;

    assign gpio_pins_in = 16'h0000;

    sv16_gpio u_gpio (
        .clk(clk_25m),
        .rst_n(sys_rst_n),
        .addr(gpio_addr),
        .wdata(gpio_wdata),
        .rdata(gpio_rdata),
        .req(gpio_req),
        .we(gpio_we),
        .ack(gpio_ack),
        .gpio_in(gpio_pins_in),
        .gpio_out(gpio_pins_out),
        .gpio_oen(gpio_pins_oen)
    );

    // Map GPIO lower pins to LEDs and Motor Direction outputs
    assign led[3:0]    = ~gpio_pins_out[3:0]; // Inverted for active-low LEDs
    assign motor_dir1  = gpio_pins_out[4];    // Direction A
    assign motor_dir2  = gpio_pins_out[5];    // Direction B

    // 8. Timer 0 Instance
    logic timer_irq;
    sv16_timer u_timer (
        .clk(clk_25m),
        .rst_n(sys_rst_n),
        .addr(timer_addr),
        .wdata(timer_wdata),
        .rdata(timer_rdata),
        .req(timer_req),
        .we(timer_we),
        .ack(timer_ack),
        .timer_irq(timer_irq)
    );

    // 9. PWM Controller 0 Instance
    sv16_pwm u_pwm (
        .clk(clk_25m),
        .rst_n(sys_rst_n),
        .addr(pwm_addr),
        .wdata(pwm_wdata),
        .rdata(pwm_rdata),
        .req(pwm_req),
        .we(pwm_we),
        .ack(pwm_ack),
        .motor_fault_n(motor_fault_n),
        .pwm_out(pwm_out)
    );

    // 10. UART 0 Instance
    logic uart_tx_irq, uart_rx_irq;
    sv16_uart u_uart (
        .clk(clk_25m),
        .rst_n(sys_rst_n),
        .addr(uart_addr),
        .wdata(uart_wdata),
        .rdata(uart_rdata),
        .req(uart_req),
        .we(uart_we),
        .ack(uart_ack),
        .uart_rx(uart_rx),
        .uart_tx(uart_tx),
        .uart_tx_irq(uart_tx_irq),
        .uart_rx_irq(uart_rx_irq)
    );

endmodule : sv16_top
