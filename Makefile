# Makefile for SV-16 Rev A Microcontroller
# Target FPGA: Lattice ECP5 LFE5U-12F-6TG144C
# Supports simulation, testing, firmware assembly, and open-source FPGA toolchain flow (Yosys + nextpnr-ecp5)

PROJECT   = sv16_top
FPGA_PKG  = TQFP144
FPGA_TYPE = 12k
DEVICE    = LFE5U-12F-6TG144C

RTL_SRCS = \
	rtl/sv16_pkg.sv \
	rtl/sv16_regfile.sv \
	rtl/sv16_alu.sv \
	rtl/sv16_status_reg.sv \
	rtl/sv16_pc.sv \
	rtl/sv16_decoder.sv \
	rtl/sv16_control_unit.sv \
	rtl/sv16_core.sv \
	rtl/sv16_ram.sv \
	rtl/sv16_gpio.sv \
	rtl/sv16_timer.sv \
	rtl/sv16_pwm.sv \
	rtl/sv16_uart.sv \
	rtl/sv16_bus_interconnect.sv \
	rtl/sv16_top.sv

CONSTRAINTS = constraints/ecp5_144tqfp.lpf

.PHONY: all test asm sim lint clean bitstream prog

all: test asm

# Run direct SystemVerilog hardware simulation testbenches
sv-sim:
	@python3 scripts/run_sv_sim.py

# Run all testbenches, verification suites, and syntax checks
test: sv-sim
	@python3 scripts/run_tests.py

# Assemble boot firmware from assembly to hex
asm:
	@python3 scripts/sv16_as.py firmware/examples/motor_test.s firmware/bootrom.hex

# Run software emulator
sim: asm
	@python3 scripts/sv16_sim.py firmware/bootrom.hex 200

# Open-source Yosys + nextpnr-ecp5 flow (if installed on workstation)
bitstream: $(PROJECT).bit

$(PROJECT).json: $(RTL_SRCS) firmware/bootrom.hex
	yosys -p "verilog_defines -DSYNTHESIS; read_verilog -sv $(RTL_SRCS); synth_ecp5 -top $(PROJECT) -json $(PROJECT).json"

$(PROJECT)_out.config: $(PROJECT).json $(CONSTRAINTS)
	nextpnr-ecp5 --$(FPGA_TYPE) --package $(FPGA_PKG) --speed 6 --json $(PROJECT).json --lpf $(CONSTRAINTS) --textcfg $(PROJECT)_out.config

$(PROJECT).bit: $(PROJECT)_out.config
	ecppack --compress $(PROJECT)_out.config $(PROJECT).bit

# Program Lattice ECP5 development board via openFPGALoader
prog: $(PROJECT).bit
	openFPGALoader -b ecp5 $(PROJECT).bit

clean:
	rm -f $(PROJECT).json $(PROJECT)_out.config $(PROJECT).bit
