# SV-16 Rev B — Boot, Programming and Field Updates

This document is the operator's manual for the "programmable MCU" side of SV-16:
where firmware lives, how the chip decides what to run, how to get a new program
into it over a plain serial port, and how to recover a board whose flash content
is broken.

Everything below is implemented in RTL that is placed, routed and packed for the
**Lattice ECP5 LFE5U-12F-6TG144C** by `make bitstream`.

---

## 1. The three layers of program storage

| Layer | Device | Size | Written by | Survives power cycle |
| :--- | :--- | :--- | :--- | :--- |
| Boot ROM | FPGA block RAM (`rtl/sv16_rom.sv`) | 2 K words = 4 KB, used: see below | compiled into the bitstream from `build/rom/monitor.hex` | yes (it is part of the configuration) |
| SRAM | FPGA block RAM (`rtl/sv16_ram.sv`) | 16 K words = 32 KB at `0x0000-0x3FFF` | applications at run time; boot loader while loading | no |
| Application flash | external SPI NOR, 512 KB typical (W25Q40 class) | `0x000000-0x0FFFFF` byte address space | the ROM monitor (`C` command) or the application itself through the flash controller | yes |

The boot ROM holds the **monitor** — a small console that lives at
`0xE000-0xE7FF` (word addresses) and is *not* overwritten by applications. The
application flash holds **images** in the format described in section 4. SRAM
holds the running program: SV-16 executes from RAM, not from flash, so flash
reads never sit in the instruction path.

`firmware/bootrom.hex` is the legacy Rev A ROM image; Rev B builds the ROM from
`firmware/monitor/monitor.s` (`make rom`).

---

## 2. What happens at power-on

`rtl/sv16_startup.sv` owns the sequence. The CPU is held in reset while the boot
engine inspects flash:

```
ext_rst_n low ──► S_RESET ──► S_BOOT ──────────────► image valid ──► S_IMAGE ──► S_RUN
                               │   boot engine        (AUTO set)      CPU.entry = image entry,
                               │   streams header +                   CPU.SP    = image stack,
                               │   payload, CRC-checks                SRAM = payload
                               │   each 256-byte page
                               │
                               └── no image / CRC fail ──► S_MONITOR ──► S_RUN
                                                             CPU.PC = 0xE000 (boot ROM)
```

* The boot engine is **hardware**: it drives the SPI flash directly and writes
  the payload into SRAM byte by byte, computing CRC16-CCITT as it goes. It costs
  no CPU cycles and cannot be locked out by a bad application.
* After the first successful `B` (boot) from the monitor, `BOOT_CTRL.AUTO` is
  set, so *every later reset* goes straight into the application.
* Two escape hatches get you back to the monitor:
  1. hold the serial **RX line low** through reset (`boot_ready` override) —
     `rtl/sv16_boot.sv`,
  2. write `SYS_CTRL` with the soft-reset key, or just reprogram flash with the
     monitor already running.
* `SYS_RSTCAUSE` (`0xF003`) records *why* the chip restarted:
  `[0]` external pin, `[1]` software, `[2]` CPU fault, `[3]` watchdog,
  `[4]` no valid image → monitor, `[5]` image loaded. Bits are sticky and are
  cleared by writing ones back.

Startup is also where a *failed* boot leaves evidence: `BOOT_ERR` (`0xF0AA`)
holds the reason (magic / header CRC / payload CRC / timeout / length / flash /
verify error) and the monitor prints it as `-E<n>`.

---

## 3. Field programming over UART — the monitor

The monitor speaks a small ASCII line protocol on UART0. Defaults:
**115200 8-N-1**, no flow control, one byte receive FIFO. The console baud
divisor is derived from the SoC clock divider at build time (`UART0_BAUD`,
`0xF042`; see section 6), so the console rate is 115200 whatever the FPGA is
clocked at.

Commands (a `+` prompt is printed after every command):

| Command | Meaning |
| :--- | :--- |
| `C<addr4><len4><crc4>` | program: erase the sectors, then receive `len` bytes as hex text; `crc4` is the CRC16 of those bytes. Answers `.` per byte, then `+OK` or `-E4` |
| `R<addr4><len4>` | read `len` bytes from flash, printed as hex text |
| `E<addr4>` | erase the 4 KB sector containing `addr` |
| `V<addr4>` | CRC16 of the 100-byte-scale image at `addr` (header + payload) — used to verify a freshly flashed image |
| `B` | verify the image at address 0 and **boot** it |
| `?` | print the command list |

Error replies: `-E0` unknown command, `-E1` bad hex digit, `-E4` upload CRC
mismatch, `-E5` flash controller stuck, `-E6` boot timeout, `-E7` image rejected
by the boot loader. Hex digits may be upper or lower case.

### 3.1 Host side — `make upload`

`scripts/sv16_mon.py` drives the protocol:

```sh
make firmware                       # assemble + pack the example application
make upload PORT=/dev/ttyUSB0       # erase, upload motor_test, verify CRC
make upload PORT=/dev/ttyUSB0 IMG=build/fw/myapp_img.hex
python3 scripts/sv16_mon.py boot --port /dev/ttyUSB0     # just boot the image
python3 scripts/sv16_mon.py term --port /dev/ttyUSB0     # interactive console
python3 scripts/sv16_mon.py upload --dry-run             # no hardware needed
```

The upload is *self-clocking*: the tool sends one payload byte as two hex
characters and waits for the monitor's `.` ack before sending the next, so it
can never overrun the receive FIFO regardless of host speed. `pyserial` is the
only dependency (`pip install pyserial`); `--dry-run` works without it.

A plain terminal works too — `make upload` is a convenience, not a requirement:

```
C00000064DB88<144 hex characters>
....................  (one dot per byte)
+OK
V0000
=DB88
B
+OK booting
```

---

## 4. Firmware image format

`scripts/sv16_fwpack.py` packs the assembler output into the image the boot
loader expects. All multi-byte fields are little endian; the CRC is
CRC16-CCITT (poly `0x1021`, init `0xFFFF`, no reflection, no final XOR — bit
identical to `rtl/sv16_crc16.sv`).

| Offset | Size | Field |
| :--- | :--- | :--- |
| `0x00` | 4 | magic `'S','V','1','6'` (`0x36315653` when read as a little-endian word) |
| `0x04` | 2 | header version (`0x0001`) |
| `0x06` | 2 | payload length in 16-bit words |
| `0x08` | 8 | ASCII image name, zero padded |
| `0x10` | 2 | entry word address (where execution starts) |
| `0x12` | 2 | initial stack pointer (`0` → `0x3FFE`) |
| `0x14` | 2 | header CRC16 over bytes `0x00-0x13` |
| `0x16` | 2 | payload CRC16 over the payload bytes |
| `0x18` | 8 | reserved (zero) |
| `0x20` | n | payload: 16-bit words, little endian |

`make app` produces, for `firmware/examples/motor_test.s`:

```
build/fw/motor_test.bin         100-byte image (raw, for a flash programmer)
build/fw/motor_test_img.hex     100 bytes, one per line — what `make upload` sends
build/fw/motor_test_words.hex   payload words only (regression test reference)
build/fw/motor_test_flash.hex   image + 0xFF padding, for flash simulation
build/fw/motor_test.txt         summary: entry, SP, word count, both CRCs
```

Note that the payload is *link-time address dependent*: an image whose entry is
`0x0000` must be stored at flash address 0 (that is what the boot loader assumes
by default). A different placement is supported through `BOOT_SRC_LO/HI`
(`0xF0A2`/`0xF0A3`) plus `make upload` with a matching address; the monitor
itself always uploads to 0.

---

## 5. The boot engine register block (`0xF0A0`)

Applications may drive the loader directly instead of asking the monitor — this
is the in-application programming (IAP) path.

| Reg | Addr | Access | Meaning |
| :--- | :--- | :--- | :--- |
| `BOOT_CTRL` | `0xF0A0` | RW | `[0]` START (latched, self-clearing), `[1]` ABORT, `[2]` VERIFY-ONLY (load and check, do not hand over), `[3]` AUTO (boot from flash on every reset) |
| `BOOT_STAT` | `0xF0A1` | RO | `[0]` BUSY, `[1]` OK, `[2]` FAIL, `[3]` CRC_OK, `[4]` MAGIC_OK |
| `BOOT_SRC_LO/HI` | `0xF0A2/3` | RW | flash **byte** address of the image (24-bit) |
| `BOOT_SRC_LEN` | `0xF0A4` | RW | bytes to stream (`0` = trust the header) |
| `BOOT_ENTRY` | `0xF0A5` | RO | entry address decoded from the header |
| `BOOT_STACK` | `0xF0A6` | RO | stack pointer decoded from the header |
| `BOOT_WORDS` | `0xF0A7` | RO | payload word count from the header |
| `BOOT_CRC_EXP/ACT` | `0xF0A8/9` | RO | expected vs computed payload CRC |
| `BOOT_ERR` | `0xF0AA` | RW1C | error code (write 1s to clear) |
| `BOOT_MAGIC` | `0xF0AB` | RO | magic word read from flash |
| `BOOT_HDRVER` | `0xF0AC` | RO | header version |
| `BOOT_NAME0..2` | `0xF0AD-F` | RO | image name characters |

Because START is a *latched request*, one store starts exactly one load even
though the CPU holds a store on the bus until it is acknowledged. The loader is
the lowest-priority bus master: while it writes SRAM it steals RAM cycles from
the CPU (which simply waits — the CPU's request is held until acknowledged), and
it never touches the boot ROM, so the monitor keeps polling `BOOT_STAT` while an
image streams past it.

### 5.1 A minimal IAP sequence (assembly)

```
    LDI  R0, 0xF0A0            ; BOOT_CTRL
    LDI  R1, 0x0001            ; START, verify only = 0
    STORE R1, [R0 + 0]
poll:
    LOAD R1, [R0 + 1]          ; BOOT_STAT
    LDI  R2, 0x0001            ; BUSY
    AND  R1, R1, R2
    BNE  poll
    LOAD R1, [R0 + 1]
    LDI  R2, 0x0002            ; OK?
    AND  R1, R1, R2
    BEQ  failed
    JMP  0x0000                ; hand over (entry from BOOT_ENTRY)
```

---

## 6. Flash controller and clocking

Programs normally reach flash through the monitor, but the controller is fully
documented in [PERIPHERALS.md](PERIPHERALS.md#flash-controller-0xf060). Two
things matter for programming:

* **Sector size is 4 KB, page size 256 B.** The controller erases sectors and
  programs whole pages from an internal buffer; a write session is
  `FCMD_ERASE_SECT` → `FCMD_WRITE_START` → stream bytes to `FLASH_DATA` →
  `FCMD_FLUSH`.
* **Timing is internal.** The controller stalls the bus while a page programs or
  a sector erases, so firmware does not have to know the flash's `tPROG`/`tERASE`
  — it just waits for `FLASH_STAT.BUSY` to clear.

The SoC clock is the 25 MHz oscillator (by default `SV16_CLKDIV=1`, i.e. no
divider at all; `make bitstream CLKDIV=2` halves it to 12.5 MHz). The UART divisor
is derived from the same constant, so the console stays at 115200 and firmware
is clock-rate agnostic. What *does* scale with the clock: timer counts, PWM
frequency, SPI bit rate and instruction throughput — and the 18-cycle DIV/MOD
(ADR-018). See
[SYNTHESIS_AND_DEPLOYMENT.md](SYNTHESIS_AND_DEPLOYMENT.md#timing) for the
measured Fmax and how the 25 MHz default came about.

---

## 7. Recovery checklist

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| Banner never appears | no monitor in the bitstream (built without `SV16_ROM_INIT_FILE`), wrong baud, or RX held low at reset | rebuild with `make bitstream` (it embeds `build/rom/monitor.hex`); check `UART0_BAUD` |
| Banner appears, `B` answers `-E7` | flash is blank or the image failed CRC | `make upload PORT=...` to reprogram |
| `C` stops mid-stream with no dots | host ignored the per-byte ack and overflowed the RX FIFO | use `scripts/sv16_mon.py`, not a raw paste |
| `-E5` from `C` | flash controller did not return to idle (wiring / missing flash) | check `FLASH_ID` reads `0xEF4018`; check SCK/CS/MOSI/MISO pins |
| Application starts then resets in a loop | application fault → `SYS_RSTCAUSE.FAULT`, `SYS_FAULT_ADDR`/`SYS_FAULT_CNT` hold the address | read the cause registers with `R`/`V`, or hold RX low to reach the monitor |
| Application restarts every few seconds (or a second time, after a hang) | the watchdog bit: `RSTCAUSE.WDT`, and `WDT_STAT` says why — `TIMEOUT` (not fed in time), `WINFAULT` (fed too early: the period or the window are wrong for the workload), `BADKEY` (bad key/feed word — usually a wild pointer write) | fix the feed call sites, or re-arm with a longer period; read `SYS_SCRATCH0/1` for the breadcrumb the early-warning interrupt left |
| The watchdog restarted the same hung application twice | by design: the watchdog is cleared only by the external reset pin, and it reloads its counter on expiry, so a repeated hang is caught repeatedly. Hold RX low at reset (or press the reset button) to land in the monitor, then upload a working image |
| Board bricks itself | *not possible*: the boot ROM is inside the FPGA configuration, and the boot engine is hardware | re-flash the FPGA if the *bitstream* is bad; re-upload the image if the *application* is bad |

The worst case is always recoverable with a serial cable: the monitor and the
boot engine are part of the bitstream, not of the application image.

---

## 8. What is still missing for production programming

* **No A/B images or rollback.** One image at address 0; a power loss during
  `C` leaves invalid flash, which the hardware boot correctly rejects (the
  monitor comes up) but the *previous* application is gone.
* **No image signing** — CRC16 detects corruption, not tampering.
* **No self-programming of the FPGA configuration** — the bitstream is loaded
  over JTAG only; there is no "application updates the FPGA" path.
* **The monitor is single-ported**: no flow control, no autobaud, no XMODEM.
  Throughput is bounded by the per-byte ack (~115 KB/s of hex text at 115200 →
  roughly 5 KB/s of payload).
* **No C toolchain.** `firmware/examples/motor_control.c` documents intent, but
  the only supported toolchain today is `scripts/sv16_as.py` (assembly).

These are tracked in [MCU_READINESS.md](MCU_READINESS.md).
