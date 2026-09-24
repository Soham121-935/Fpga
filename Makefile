# ---------------------------------------------------------------------------
# SV-16 Rev B — build system
# Target FPGA: Lattice ECP5 LFE5U-12F-6TG144C (12K LUT, TQFP-144, speed 6)
#
#   make firmware    boot ROM image (the monitor) + the example application image
#   make sim         build and run every Verilator testbench
#   make lint        RTL lint
#   make bitstream   Yosys -> nextpnr-ecp5 -> ecppack   (build/sv16_top.bit)
#   make prog        program the device over JTAG
#   make upload      program the *firmware* over the serial port (needs pyserial)
#   make iss         run the instruction-set simulator on the example firmware
#
# Toolchain (either install Verilator/Yosys/nextpnr/ecppack yourself, or let the
# repository fetch self-contained builds of all of them):
#
#   source scripts/sv16_venv.sh
#   make test
#
# See docs/SYNTHESIS_AND_DEPLOYMENT.md for the full flow and
# docs/BOOT_AND_PROGRAMMING.md for how firmware gets into the part.
# ---------------------------------------------------------------------------

PROJECT     = sv16_top
FPGA_DEVICE = LFE5U-12F-6TG144C
FPGA_FAMILY = ecp5
FPGA_TYPE   = 12k
FPGA_PKG    = TQFP144
FPGA_SPEED  = 6
# System clock = 25 MHz oscillator / CLKDIV.  CLKDIV=1 (the shipped default) runs
# the SoC directly from the oscillator with no fabric divider, which is also the
# configuration every testbench simulates (they drive clk_25m and assume 115200
# at 217 clocks/bit).  Since the ALU's divider went multi-cycle (ADR-018) the
# design closes at 25 MHz with ~86% margin (measured Fmax 46.6 MHz); set CLKDIV=2
# only if a board turns out not to run at 25 MHz (see
# docs/SYNTHESIS_AND_DEPLOYMENT.md#timing).
CLKDIV      = 1
FPGA_FREQ   = 25

BUILD       = build
ROM_DIR     = $(BUILD)/rom
ROM_HEX     = $(ROM_DIR)/monitor.hex
ROM_LST     = $(ROM_DIR)/monitor.lst
FW_DIR      = $(BUILD)/fw
APP         = $(FW_DIR)/motor_test
APP_IMG     = $(APP)_img.hex
HANG        = $(FW_DIR)/wdt_hang
HANG_IMG    = $(HANG)_img.hex

CONSTRAINTS = constraints/ecp5_144tqfp.lpf

PY   = python3
AS   = $(PY) scripts/sv16_as.py
PACK = $(PY) scripts/sv16_fwpack.py

MONITOR_SRC = firmware/monitor/monitor.s
APP_SRC     = firmware/examples/motor_test.s
HANG_SRC    = firmware/examples/wdt_hang.s
BOOTROM_HEX = firmware/bootrom.hex

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
	rtl/sv16_rom.sv \
	rtl/sv16_crc16.sv \
	rtl/sv16_uart.sv \
	rtl/sv16_spi_master.sv \
	rtl/sv16_spi.sv \
	rtl/sv16_flash_ctrl.sv \
	rtl/sv16_boot.sv \
	rtl/sv16_startup.sv \
	rtl/sv16_sys.sv \
	rtl/sv16_irq_ctrl.sv \
	rtl/sv16_gpio.sv \
	rtl/sv16_timer.sv \
	rtl/sv16_pwm.sv \
	rtl/sv16_wdt.sv \
	rtl/sv16_bus_interconnect.sv \
	rtl/sv16_top.sv

# name:source pairs for `make sim` (add new testbenches here)
TESTBENCHES = \
	wdt_tb:simulation/unit/wdt_tb.sv \
	div_tb:simulation/unit/div_tb.sv \
	flash_ctrl_tb:simulation/unit/flash_ctrl_tb.sv \
	boot_tb:simulation/unit/boot_tb.sv \
	soc_boot_tb:simulation/regression/soc_boot_tb.sv \
	monitor_tb:simulation/regression/monitor_tb.sv \
	wdt_reset_tb:simulation/regression/wdt_reset_tb.sv

.PHONY: all firmware rom app lint vlint test sim iss bitstream synth prog \
	upload mon-verify mon-boot mon-term clean help

all: firmware lint

help:
	@sed -n '2,20p' Makefile

# --------------------------------------------------------------- firmware
firmware: rom app

rom: $(ROM_HEX)

app: $(APP_IMG) $(HANG_IMG)

$(ROM_HEX): $(MONITOR_SRC) scripts/sv16_as.py
	@mkdir -p $(ROM_DIR)
	$(AS) $< $@ --listing $(ROM_LST)

$(APP_IMG): $(APP_SRC) scripts/sv16_as.py scripts/sv16_fwpack.py
	@mkdir -p $(FW_DIR)
	$(AS) $(APP_SRC) $(APP).hex --listing $(APP).lst
	$(PACK) $(APP).hex -o $(APP) --name MOTORTST

# watchdog-recovery example: used by wdt_reset_tb, harmless elsewhere
$(HANG_IMG): $(HANG_SRC) scripts/sv16_as.py scripts/sv16_fwpack.py
	@mkdir -p $(FW_DIR)
	$(AS) $(HANG_SRC) $(HANG).hex --listing $(HANG).lst
	$(PACK) $(HANG).hex -o $(HANG) --name WDTHANG

# --------------------------------------------------------------- checks
lint:
	$(PY) scripts/sv16_rtl_lint.py $(RTL_SRCS)

# Verilator testbenches (TB=<name> to run just one)
sim: firmware
	@fail=0; \
	for entry in $(TESTBENCHES); do \
	    name=$${entry%%:*}; src=$${entry##*:}; \
	    if [ -n "$(TB)" ] && [ "$(TB)" != "$$name" ]; then continue; fi; \
	    echo "===== $$name"; \
	    scripts/sv16_run_tb.sh $$src $$name || fail=1; \
	done; \
	exit $$fail

# Verilator lint of every RTL file (needs verilator-cli on PATH)
vlint:
	@verilator-cli --lint-only -Wno-fatal -Wno-WIDTHEXPAND -Wno-UNUSEDSIGNAL \
	    -Wno-UNUSEDPARAM -Wno-IMPORTSTAR -Wno-CASEINCOMPLETE -Irtl \
	    $$(ls rtl/*.sv | grep -v 'sv16_top\.sv$$') rtl/sv16_top.sv \
	    --top-module $(PROJECT) && echo "verilator lint: clean"

test: lint firmware sim

# ------------------------------------------------------- instruction set sim
iss: $(BOOTROM_HEX)
	$(PY) scripts/sv16_sim.py $(BOOTROM_HEX) 200

# --------------------------------------------------------------- bitstream
bitstream: firmware $(BUILD)/$(PROJECT).bit

$(BUILD)/$(PROJECT).bit: $(RTL_SRCS) $(ROM_HEX) $(CONSTRAINTS) scripts/sv16_synth.sh
	@scripts/sv16_synth.sh --out $(BUILD) --rom $(ROM_HEX) --lpf $(CONSTRAINTS) \
	    --freq $(FPGA_FREQ) --clkdiv $(CLKDIV) --speed $(FPGA_SPEED) \
	    --top $(PROJECT)

# Synthesis only (fast check that the RTL is synthesizable for this device)
synth: $(ROM_HEX)
	@scripts/sv16_synth.sh --out $(BUILD) --rom $(ROM_HEX) --freq $(FPGA_FREQ) \
	    --clkdiv $(CLKDIV) --speed $(FPGA_SPEED) --top $(PROJECT) --yosys-only

# Program the device (openFPGALoader; BOARD/CABLE can be overridden)
OPENFPGALOADER ?= openFPGALoader
BOARD           ?=
CABLE           ?=
FPGA_PART       ?= LFE5U-12F

prog: $(BUILD)/$(PROJECT).bit
	$(OPENFPGALOADER) $(if $(BOARD),-b $(BOARD),) $(if $(CABLE),-c $(CABLE),) \
	    --fpga-part $(FPGA_PART) $(BUILD)/$(PROJECT).bit

# ------------------------------------------------------- serial programming
# Talks to the ROM monitor: erase + upload + verify (see
# docs/BOOT_AND_PROGRAMMING.md).  Requires pyserial on the host.
PORT ?= /dev/ttyUSB0
IMG  ?= $(if $(FILE),$(FILE),$(APP_IMG))

upload: $(APP_IMG)
	$(PY) scripts/sv16_mon.py upload $(IMG) --port $(PORT)

mon-verify:
	$(PY) scripts/sv16_mon.py verify --port $(PORT)

mon-boot:
	$(PY) scripts/sv16_mon.py boot --port $(PORT)

mon-term:
	$(PY) scripts/sv16_mon.py term --port $(PORT)

clean:
	rm -rf $(BUILD)
	rm -f $(PROJECT).json $(PROJECT)_out.config $(PROJECT).bit
