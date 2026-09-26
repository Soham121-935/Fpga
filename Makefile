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
# System clock.  Two independent knobs, both build-time (ADR-018, ADR-021):
#
#   CLKSRC = osc   the 25 MHz oscillator straight into the fabric (default)
#   CLKSRC = pll   the on-chip PLL multiplying it to PLLMHZ.  The 25 MHz
#                  reference reaches multiples of 25 MHz and of 12.5 MHz
#                  exactly, so 37.5 MHz is the useful step up (Fmax measured
#                  46.17 MHz); 50 MHz is reachable but does not close.
#   CLKDIV = 1     no fabric divider (default); 2 halves whatever the source is
#
# The default configuration is what every testbench simulates.  Firmware is
# clock-rate agnostic: rtl/sv16_top.sv derives the UART divisor (217 at 25 MHz,
# 347 at 40 MHz) from whichever clock is built, so the console comes up at
# 115200 without software doing anything -- see docs/RESET_AND_CLOCK.md.
#   make bitstream CLKSRC=pll PLLMHZ=37.5
CLKDIV      = 1
CLKSRC      = osc
PLLMHZ      = 37.5
# Timing target: the oscillator frequency for CLKSRC=osc, the generated clock
# for CLKSRC=pll.  Override with FPGA_FREQ=... if you know better.
FPGA_FREQ   ?= $(if $(filter pll,$(CLKSRC)),$(PLLMHZ),25)

BUILD       = build
ROM_DIR     = $(BUILD)/rom
ROM_HEX     = $(ROM_DIR)/monitor.hex
ROM_LST     = $(ROM_DIR)/monitor.lst
FW_DIR      = $(BUILD)/fw
APP         = $(FW_DIR)/motor_test
APP_IMG     = $(APP)_img.hex
HANG        = $(FW_DIR)/wdt_hang
HANG_IMG    = $(HANG)_img.hex

# ADR-019 field update: pack the example application for an A/B slot and install
# it into the *inactive* one.  SLOT=1 is slot B (flash 0x8000), SLOT=0 slot A.
SLOT        ?= 1
SLOT_APP    = $(FW_DIR)/app_slot$(SLOT)

CONSTRAINTS = constraints/ecp5_144tqfp.lpf

PY   = python3
AS   = $(PY) scripts/sv16_as.py
PACK = $(PY) scripts/sv16_fwpack.py

MONITOR_SRC = firmware/monitor/monitor.s
APP_SRC     = firmware/examples/motor_test.s
HANG_SRC    = firmware/examples/wdt_hang.s
# ISA-level regression program (run by simulation/regression/isa_tb.sv): the
# instruction-level test is written in assembly and assembled by the real
# assembler, so what the testbench executes is what a developer would type.
ISA_SRC     = firmware/tests/isa_regress.s
ISA_HEX     = $(FW_DIR)/isa_regress.hex
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
	rtl/sv16_pll.sv \
	rtl/sv16_bus_interconnect.sv \
	rtl/sv16_top.sv

# name:source pairs for `make sim` (add new testbenches here)
TESTBENCHES = \
	wdt_tb:simulation/unit/wdt_tb.sv \
	div_tb:simulation/unit/div_tb.sv \
	flash_ctrl_tb:simulation/unit/flash_ctrl_tb.sv \
	boot_tb:simulation/unit/boot_tb.sv \
	slot_tb:simulation/unit/slot_tb.sv \
	sv16_alu_tb:simulation/unit/sv16_alu_tb.sv \
	sv16_ram_tb:simulation/unit/sv16_ram_tb.sv \
	sv16_timer_tb:simulation/unit/sv16_timer_tb.sv \
	sv16_pwm_tb:simulation/unit/sv16_pwm_tb.sv \
	sv16_gpio_tb:simulation/unit/sv16_gpio_tb.sv \
	sv16_uart_tb:simulation/unit/sv16_uart_tb.sv \
	isa_tb:simulation/regression/isa_tb.sv \
	pll_clock_tb:simulation/regression/pll_clock_tb.sv \
	soc_boot_tb:simulation/regression/soc_boot_tb.sv \
	monitor_tb:simulation/regression/monitor_tb.sv \
	wdt_reset_tb:simulation/regression/wdt_reset_tb.sv

.PHONY: all firmware rom app lint vlint test sim iss bitstream synth prog \
	upload upload-slot slot-image commit mon-verify mon-boot mon-term \
	clean help

all: firmware lint

help:
	@sed -n '2,20p' Makefile

# --------------------------------------------------------------- firmware
firmware: rom app

rom: $(ROM_HEX)

app: $(APP_IMG) $(HANG_IMG) $(ISA_HEX)

$(ISA_HEX): $(ISA_SRC) scripts/sv16_as.py
	@mkdir -p $(FW_DIR)
	$(AS) $< $@ --listing $(FW_DIR)/isa_regress.lst

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
	    --freq $(FPGA_FREQ) --clkdiv $(CLKDIV) --clksrc $(CLKSRC) \
	    --pllmhz $(PLLMHZ) --speed $(FPGA_SPEED) --top $(PROJECT)

# Synthesis only (fast check that the RTL is synthesizable for this device)
synth: $(ROM_HEX)
	@scripts/sv16_synth.sh --out $(BUILD) --rom $(ROM_HEX) --freq $(FPGA_FREQ) \
	    --clkdiv $(CLKDIV) --clksrc $(CLKSRC) --pllmhz $(PLLMHZ) \
	    --speed $(FPGA_SPEED) --top $(PROJECT) --yosys-only

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

# ---- ADR-019 field update (see docs/BOOT_AND_PROGRAMMING.md, section 5) ----
# 1. pack the application so it carries the slot record (PENDING) the loader
#    needs to start a trial, then 2. install it into the inactive slot over the
#    monitor, 3. boot it (the loader picks the pending slot), 4. commit it once
#    it behaves.  Skip step 4 and the next restart rolls back to the other slot.
$(SLOT_APP)_img.hex: $(APP_SRC) scripts/sv16_as.py scripts/sv16_fwpack.py
	@mkdir -p $(FW_DIR)
	$(AS) $(APP_SRC) $(SLOT_APP)_asm.hex --listing $(SLOT_APP).lst
	$(PACK) $(SLOT_APP)_asm.hex -o $(SLOT_APP) --name SLOT$(SLOT) --slot $(SLOT)

slot-image: $(SLOT_APP)_img.hex
	@echo "packed $(SLOT_APP)_img.hex for slot $(SLOT)"

upload-slot: $(SLOT_APP)_img.hex
	$(PY) scripts/sv16_mon.py upload $(SLOT_APP)_img.hex --slot $(SLOT) --port $(PORT)
	@echo "next: make mon-boot  (the loader picks the pending slot), then"
	@echo "      make commit    (once the new image looks good)"

commit:
	$(PY) scripts/sv16_mon.py commit --port $(PORT)

mon-verify:
	$(PY) scripts/sv16_mon.py verify --port $(PORT)

mon-boot:
	$(PY) scripts/sv16_mon.py boot --port $(PORT)

mon-term:
	$(PY) scripts/sv16_mon.py term --port $(PORT)

clean:
	rm -rf $(BUILD)
	rm -f $(PROJECT).json $(PROJECT)_out.config $(PROJECT).bit
