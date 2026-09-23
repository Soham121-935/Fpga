#!/usr/bin/env python3
"""SV-16 firmware image packer.

Turns an assembled program (the one-word-per-line hex file produced by
scripts/sv16_as.py) into the firmware image format that the hardware boot
loader (rtl/sv16_boot.sv) streams out of SPI flash.

Image layout (all multi-byte fields little endian, CRC16-CCITT 0x1021,
init 0xFFFF, no reflection, no final XOR - identical to rtl/sv16_crc16.sv):

    0x00  4  magic 'S','V','1','6'
    0x04  2  header version (0x0001)
    0x06  2  payload length in 16-bit words
    0x08  8  ASCII image name, zero padded
    0x10  2  entry address (word address where the payload lives)
    0x12  2  initial stack pointer (0 = use the reset value)
    0x14  2  header CRC16 over bytes 0x00..0x13
    0x16  2  payload CRC16 over the payload bytes
    0x18  8  reserved (zero)
    0x20 .. payload, little endian words

Outputs
    <prefix>.bin          raw image (header + payload), for `make flash`
    <prefix>.hex          the image as a byte-per-line hex file ($readmemh
                          / host tooling)
    <prefix>_flash.hex    byte-per-line hex for a flash chip: the image at
                          the programmed offset plus 0xFF padding, directly
                          usable as an FPGA RAM/flash simulation init file
    <prefix>.h            optional C header with the image bytes/CRC
    <prefix>.txt          summary report

Usage examples
    scripts/sv16_fwpack.py firmware/examples/motor_test.hex -o build/fw/motor
    scripts/sv16_fwpack.py build/rom/monitor.hex -o build/fw/monitor --entry 0xE000
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

MAGIC = b"SV16"
HDR_VERSION = 0x0001
HDR_SIZE = 32
HDR_CRC_LEN = 20          # bytes covered by the header CRC
DEFAULT_SP = 0x3FFE       # must match BOOT_DEFAULT_SP in rtl/sv16_pkg.sv
DEFAULT_ENTRY = 0x0000
FLASH_ERASED = 0xFF


def crc16_ccitt(data: bytes, crc: int = 0xFFFF) -> int:
    """CRC16-CCITT (poly 0x1021, init 0xFFFF), bit-identical to sv16_crc16."""
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def read_word_hex(path: str) -> list[int]:
    """Read the assembler output: one 16-bit word per line (64K max)."""
    words: list[int] = []
    with open(path, "r") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.split("//")[0].split("#")[0].strip()
            if not line:
                continue
            token = line.split()[0]
            try:
                value = int(token, 16)
            except ValueError:
                raise SystemExit(f"{path}:{lineno}: not a hex word: {token!r}")
            if not 0 <= value <= 0xFFFF:
                raise SystemExit(f"{path}:{lineno}: word out of range: {token!r}")
            words.append(value)
    if not words:
        raise SystemExit(f"{path}: no words found")
    return words


def trim_trailing_zeros(words: list[int]) -> list[int]:
    end = len(words)
    while end > 1 and words[end - 1] == 0x0000:
        end -= 1
    return words[:end]


def build_image(words: list[int], entry: int, sp: int, name: str) -> tuple[bytes, int, int]:
    payload = b"".join(struct.pack("<H", w) for w in words)
    if len(payload) > 0x1FFFE:
        raise SystemExit("payload too large (max 64K words)")

    header = bytearray(HDR_SIZE)
    header[0:4] = MAGIC
    struct.pack_into("<H", header, 0x04, HDR_VERSION)
    struct.pack_into("<H", header, 0x06, len(words))
    name_bytes = name.encode("ascii", "replace")[:8].ljust(8, b"\x00")
    header[0x08:0x10] = name_bytes
    struct.pack_into("<H", header, 0x10, entry & 0xFFFF)
    struct.pack_into("<H", header, 0x12, sp & 0xFFFF)

    hdr_crc = crc16_ccitt(bytes(header[:HDR_CRC_LEN]))
    pld_crc = crc16_ccitt(payload)
    struct.pack_into("<H", header, 0x14, hdr_crc)
    struct.pack_into("<H", header, 0x16, pld_crc)

    return bytes(header) + payload, hdr_crc, pld_crc


def write_byte_hex(path: str, data: bytes, offset: int = 0, wrap: int = 16) -> None:
    with open(path, "w") as fh:
        if offset:
            fh.write(f"@{offset:04X}\n")
        for i, byte in enumerate(data):
            fh.write(f"{byte:02X}\n")
            if wrap and (i + 1) % wrap == 0:
                fh.write("\n") if False else None


def write_flash_hex(path: str, image: bytes, offset: int, total_size: int) -> None:
    """Byte-per-line hex for a whole flash chip / RAM init file."""
    if offset + len(image) > total_size:
        raise SystemExit("image does not fit in the configured flash size")
    with open(path, "w") as fh:
        fh.write(f"@{0:04X}\n") if False else None
        fh.write("00\n") if offset == 0 and False else None
        # pad before the image with 0xFF so a $readmemh consumer sees erased
        # flash everywhere the image is not programmed
        for _ in range(offset):
            fh.write(f"{FLASH_ERASED:02X}\n")
        for byte in image:
            fh.write(f"{byte:02X}\n")
        for _ in range(total_size - offset - len(image)):
            fh.write(f"{FLASH_ERASED:02X}\n")


def write_c_header(path: str, image: bytes, hdr_crc: int, pld_crc: int,
                   words: list[int], entry: int, sp: int, name: str) -> None:
    lines = [
        "/* Generated by scripts/sv16_fwpack.py - do not edit */",
        "#ifndef SV16_IMAGE_H",
        "#define SV16_IMAGE_H",
        "",
        "#include <stdint.h>",
        "",
        f"#define SV16_IMAGE_NAME    \"{name}\"",
        f"#define SV16_IMAGE_ENTRY   0x{entry:04X}",
        f"#define SV16_IMAGE_SP      0x{sp:04X}",
        f"#define SV16_IMAGE_WORDS   {len(words)}",
        f"#define SV16_IMAGE_BYTES   {len(image)}",
        f"#define SV16_IMAGE_HDR_CRC 0x{hdr_crc:04X}",
        f"#define SV16_IMAGE_PLD_CRC 0x{pld_crc:04X}",
        "",
        f"static const uint8_t sv16_image[{len(image)}] = {{",
    ]
    for i in range(0, len(image), 12):
        chunk = ", ".join(f"0x{b:02X}" for b in image[i:i + 12])
        lines.append(f"    {chunk},")
    lines += ["};", "", "#endif /* SV16_IMAGE_H */", ""]
    with open(path, "w") as fh:
        fh.write("\n".join(lines))


def parse_verify(path: str) -> int:
    """Verify a packed .bin image (used by the test suite)."""
    with open(path, "rb") as fh:
        image = fh.read()
    if len(image) < HDR_SIZE:
        print("FAIL: image shorter than the header")
        return 1
    if image[0:4] != MAGIC:
        print("FAIL: bad magic")
        return 1
    version, words = struct.unpack_from("<HH", image, 0x04)
    entry, sp, hdr_crc, pld_crc = struct.unpack_from("<HHHH", image, 0x10)
    payload = image[HDR_SIZE:]
    if version != HDR_VERSION:
        print(f"FAIL: header version 0x{version:04X}")
        return 1
    if words * 2 != len(payload):
        print(f"FAIL: header says {words} words, payload has {len(payload)//2}")
        return 1
    if crc16_ccitt(image[:HDR_CRC_LEN]) != hdr_crc:
        print("FAIL: header CRC mismatch")
        return 1
    if crc16_ccitt(payload) != pld_crc:
        print("FAIL: payload CRC mismatch")
        return 1
    name = image[0x08:0x10].rstrip(b"\x00").decode("ascii", "replace")
    print(f"OK: {path}: '{name}' {words} words, entry 0x{entry:04X}, "
          f"sp 0x{sp:04X}, header CRC 0x{hdr_crc:04X}, payload CRC 0x{pld_crc:04X}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SV-16 firmware image packer")
    ap.add_argument("input", nargs="?", help="assembler hex word file")
    ap.add_argument("-o", "--output", help="output prefix (default: build/fw/image)")
    ap.add_argument("--entry", default=None, help="entry word address (default 0)")
    ap.add_argument("--sp", default=None, help=f"initial stack pointer (default 0x{DEFAULT_SP:04X})")
    ap.add_argument("--name", default=None, help="image name (max 8 ASCII chars)")
    ap.add_argument("--no-trim", action="store_true", help="keep trailing zero words")
    ap.add_argument("--flash-offset", default="0", help="flash offset of the image")
    ap.add_argument("--flash-size", default="65536", help="flash size for the padded hex")
    ap.add_argument("--c-header", action="store_true", help="also write <prefix>.h")
    ap.add_argument("--verify", help="verify an existing .bin image instead")
    args = ap.parse_args(argv)

    if args.verify:
        return parse_verify(args.verify)
    if not args.input:
        ap.error("an input hex file is required")

    def num(value: str) -> int:
        return int(value, 0)

    words = read_word_hex(args.input)
    if not args.no_trim:
        words = trim_trailing_zeros(words)

    name = args.name or os.path.splitext(os.path.basename(args.input))[0][:8]
    entry = DEFAULT_ENTRY if args.entry is None else num(args.entry)
    sp = DEFAULT_SP if args.sp is None else num(args.sp)
    prefix = args.output or os.path.join("build", "fw", "image")
    os.makedirs(os.path.dirname(prefix) or ".", exist_ok=True)

    image, hdr_crc, pld_crc = build_image(words, entry, sp, name)

    bin_path = prefix + ".bin"
    hex_path = prefix + ".hex"
    flash_path = prefix + "_flash.hex"
    txt_path = prefix + ".txt"

    with open(bin_path, "wb") as fh:
        fh.write(image)
    write_byte_hex(hex_path, image)
    # payload words as one hex word per line (regression tests compare against
    # the RAM contents after the hardware boot loader ran)
    with open(prefix + "_words.hex", "w") as fh:
        for word in words:
            fh.write(f"{word:04X}\n")
    write_flash_hex(flash_path, image, num(args.flash_offset), num(args.flash_size))
    # the image alone, one byte per line: the ROM monitor testbench and the
    # `make upload` host script both need exactly this (no 0xFF padding)
    write_byte_hex(prefix + "_img.hex", image)
    if args.c_header:
        write_c_header(prefix + ".h", image, hdr_crc, pld_crc, words, entry, sp, name)

    report = [
        f"input        : {args.input}",
        f"name         : {name}",
        f"entry word   : 0x{entry:04X}",
        f"stack pointer: 0x{sp:04X}",
        f"payload words: {len(words)} ({len(words) * 2} bytes)",
        f"image bytes  : {len(image)}",
        f"header CRC16 : 0x{hdr_crc:04X}",
        f"payload CRC16: 0x{pld_crc:04X}",
        f"binary       : {bin_path}",
        f"byte hex     : {hex_path}",
        f"flash hex    : {flash_path}",
        f"image hex    : {prefix}_img.hex",
        f"words hex    : {prefix}_words.hex",
    ]
    with open(txt_path, "w") as fh:
        fh.write("\n".join(report) + "\n")
    print("\n".join(report))

    # self check: the packer must be able to re-verify what it just wrote
    return parse_verify(bin_path)


if __name__ == "__main__":
    sys.exit(main())
