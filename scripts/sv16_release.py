#!/usr/bin/env python3
"""SV-16 release builder/verifier — the four artifacts that make the board run.

The FPGA does not read SystemVerilog.  Bringing this design to life means
producing and programming four different things (TEAM_PLAN.md section 14):

  1  bitstream        build/sv16_top.bit      laptop: yosys -> nextpnr -> ecppack
  2  config flash     (the same bitstream)    written into U2 over JTAG, persistent
  3  firmware image   build/fw/*_img.hex      written into U3 over UART by the monitor
  4  boot ROM         inside the bitstream    build/rom/monitor.hex, hardened in BRAM

This script checks everything about those artifacts that can be checked without
hardware, writes a manifest with their SHA-256 hashes, and prints the exact
programming sequence.  Run it on the bench immediately before programming: it is
the difference between "the board does not work" and "the image was stale".

Checks performed
    ROM       re-assemble firmware/monitor/monitor.s and compare byte for byte
              with build/rom/monitor.hex (a stale ROM means the bitstream has an
              old monitor inside it); report words used against the 2 K capacity
    bitstream exists, non-trivial size, and its nextpnr log passes
              scripts/sv16_check_budget.py (the datasheet limits) and reports a
              timing PASS at the requested frequency
    images    parse the header, verify the header CRC and the payload CRC, check
              the payload fits the 32 KB slot, and read the slot record state
    freshness the bitstream must be newer than the ROM, which must be newer than
              monitor.s; an image must be newer than its source

Usage
    scripts/sv16_release.py                    # verify what is in build/
    scripts/sv16_release.py --twice            # also rebuild the bitstream twice
                                               # and compare hashes (determinism)
    make release                               # build then verify, in one go
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sv16_fwpack  # noqa: E402  (same directory, single source of truth for the format)

ROM_CAPACITY_WORDS = 2048          # 2 K words of block RAM, rtl/sv16_rom.sv
SLOT_CAPACITY_BYTES = 0x008000     # 32 KB per A/B slot, ADR-019
MIN_BITSTREAM_BYTES = 100_000      # an ECP5 12F bitstream is ~290 KB; anything
                                   # this small is a truncated or empty file

passes: list[str] = []
fails: list[str] = []
notes: list[str] = []


def ok(msg: str) -> None:
    passes.append(msg)
    print("  [ok]   %s" % msg)


def bad(msg: str) -> None:
    fails.append(msg)
    print("  [FAIL] %s" % msg)


def note(msg: str) -> None:
    notes.append(msg)
    print("  [note] %s" % msg)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kwargs)


# --------------------------------------------------------------- 1. boot ROM
def check_rom(rom_hex: Path, monitor_src: Path) -> dict:
    info: dict = {"path": str(rom_hex.relative_to(ROOT)) if rom_hex.exists() else None}
    if not rom_hex.exists():
        bad("boot ROM %s is missing - run `make rom`" % rom_hex.relative_to(ROOT))
        return info

    words = [line.strip() for line in rom_hex.read_text().splitlines() if line.strip()]
    used = len(words)
    info.update(words=used, capacity=ROM_CAPACITY_WORDS, sha256=sha256(rom_hex))
    if used > ROM_CAPACITY_WORDS:
        bad("boot ROM uses %d words, capacity is %d" % (used, ROM_CAPACITY_WORDS))
    else:
        ok("boot ROM: %d/%d words (%.1f%%), %d words free"
           % (used, ROM_CAPACITY_WORDS, 100.0 * used / ROM_CAPACITY_WORDS,
              ROM_CAPACITY_WORDS - used))

    if not monitor_src.exists():
        note("monitor source %s not found - cannot check freshness" % monitor_src)
        return info

    with tempfile.TemporaryDirectory() as tmp:
        rebuilt = Path(tmp) / "monitor.hex"
        proc = run([sys.executable, "scripts/sv16_as.py", str(monitor_src), str(rebuilt)])
        if proc.returncode != 0:
            note("could not re-assemble the monitor: %s" % proc.stderr.strip()[:200])
        elif rebuilt.read_bytes() == rom_hex.read_bytes():
            ok("boot ROM matches a fresh assembly of %s"
               % monitor_src.relative_to(ROOT))
        else:
            bad("boot ROM does not match a fresh assembly of %s - run `make rom` "
                "and rebuild the bitstream" % monitor_src.relative_to(ROOT))

    if rom_hex.stat().st_mtime < monitor_src.stat().st_mtime:
        bad("boot ROM is older than %s - the bitstream would carry a stale monitor"
            % monitor_src.relative_to(ROOT))
    return info


# -------------------------------------------------------------- 2. bitstream
def check_bitstream(bit: Path, log: Path, freq: float) -> dict:
    info: dict = {}
    if not bit.exists():
        bad("bitstream %s is missing - run `make bitstream`" % bit.relative_to(ROOT))
        return info

    size = bit.stat().st_size
    info.update(path=str(bit.relative_to(ROOT)), bytes=size, sha256=sha256(bit),
                fmax_mhz=None, budget="unknown")
    if size < MIN_BITSTREAM_BYTES:
        bad("bitstream is only %d bytes - truncated or empty" % size)
    else:
        ok("bitstream: %s (%.0f KB, sha256 %s...)" % (bit.name, size / 1024.0,
                                                      info["sha256"][:16]))

    if not log.exists():
        note("nextpnr log %s not found - cannot verify timing or resources"
             % log.relative_to(ROOT))
        return info

    text = log.read_text(errors="replace")
    match = re.search(r"Max frequency for clock '([^']+)':\s*([0-9.]+) MHz\s*\((PASS|FAIL)",
                      text)
    if match:
        info["fmax_mhz"] = float(match.group(2))
        info["fmax_clock"] = match.group(1)
        if match.group(3) == "PASS" and info["fmax_mhz"] >= freq:
            ok("timing: %s at %.2f MHz vs the %.2f MHz constraint"
               % (match.group(1), info["fmax_mhz"], freq))
        else:
            bad("timing: %s at %.2f MHz does not meet the %.2f MHz constraint"
                % (match.group(1), info["fmax_mhz"], freq))
    else:
        note("no 'Max frequency' line in the nextpnr log")

    part = re.search(r"resource budget for (\S+) \(datasheet", text)
    if part:
        info["part_string"] = part.group(1)

    part_string = part.group(1) if part else "LFE5U-12F-6TQFP144"
    proc = run([sys.executable, "scripts/sv16_check_budget.py", str(log), part_string])
    budget_line = next((l for l in proc.stdout.splitlines() if "fit" in l.lower()),
                       proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "")
    info["budget"] = "pass" if proc.returncode == 0 else "fail"
    info["budget_line"] = budget_line.strip()
    if proc.returncode == 0:
        ok("resource budget: %s" % (budget_line.strip() or "within the device limits"))
    else:
        bad("resource budget check failed: %s" % (proc.stdout.strip()[:200]
                                                  or proc.stderr.strip()[:200]))

    for label, pattern in (("LUT4", r"LUT4[^\n]*?(\d[\d,]*)\s*/\s*(\d[\d,]*)\s*([\d.]+)%"),
                           ("sysMEM", r"sysMEM[^\n]*?(\d[\d,]*)\s*/\s*(\d[\d,]*)\s*([\d.]+)%"),
                           ("multipliers", r"multipliers[^\n]*?(\d[\d,]*)\s*/\s*(\d[\d,]*)\s*([\d.]+)%"),
                           ("I/O", r"I/O[^\n]*?(\d[\d,]*)\s*/\s*(\d[\d,]*)\s*([\d.]+)%")):
        m = re.search(pattern, text)
        if m:
            info.setdefault("utilisation", {})[label] = "%s / %s (%s%%)" % (
                m.group(1), m.group(2), m.group(3))
    return info


# ---------------------------------------------------------- 3. firmware image
def check_image(path: Path, source: Path | None) -> dict:
    info: dict = {"path": str(path.relative_to(ROOT))}
    if not path.exists():
        note("image %s not present - build it with `make app` / `make slot-image`"
             % path.relative_to(ROOT))
        return info

    data = bytes(int(line.strip(), 16) & 0xFF
                 for line in path.read_text().splitlines() if line.strip())
    info.update(bytes=len(data), sha256=sha256(path))

    if len(data) < sv16_fwpack.HDR_SIZE:
        bad("%s is shorter than the 32-byte header" % path.name)
        return info
    header = data[:sv16_fwpack.HDR_SIZE]
    if header[:4] != sv16_fwpack.MAGIC:
        bad("%s: bad magic %r (expected %r)" % (path.name, header[:4], sv16_fwpack.MAGIC))
        return info

    payload_words = int.from_bytes(header[0x06:0x08], "little")
    name = header[0x08:0x10].rstrip(b"\x00").decode("ascii", "replace")
    entry = int.from_bytes(header[0x10:0x12], "little")
    sp = int.from_bytes(header[0x12:0x14], "little")
    hdr_crc = int.from_bytes(header[0x14:0x16], "little")
    pay_crc = int.from_bytes(header[0x16:0x18], "little")
    info.update(name=name, entry=entry, sp=sp, payload_words=payload_words)

    if sv16_fwpack.crc16_ccitt(header[:sv16_fwpack.HDR_CRC_LEN]) != hdr_crc:
        bad("%s: header CRC mismatch" % path.name)
    payload = data[sv16_fwpack.HDR_SIZE:sv16_fwpack.HDR_SIZE + payload_words * 2]
    if len(payload) != payload_words * 2:
        bad("%s: payload is %d bytes, header claims %d"
            % (path.name, len(payload), payload_words * 2))
    elif sv16_fwpack.crc16_ccitt(payload) != pay_crc:
        bad("%s: payload CRC mismatch" % path.name)
    else:
        ok("%s: '%s' %d words (%d bytes), header and payload CRCs valid"
           % (path.name, name, payload_words, len(data)))

    if len(data) > SLOT_CAPACITY_BYTES:
        bad("%s is %d bytes - larger than the %d-byte slot"
            % (path.name, len(data), SLOT_CAPACITY_BYTES))
    elif len(data) > 0.75 * SLOT_CAPACITY_BYTES:
        note("%s uses %d of %d slot bytes" % (path.name, len(data), SLOT_CAPACITY_BYTES))

    rec_sync, rec_state = header[sv16_fwpack.SLOT_REC_OFF], header[sv16_fwpack.SLOT_REC_OFF + 1]
    if rec_sync == sv16_fwpack.SLOT_SYNC:
        state = {v: k for k, v in sv16_fwpack.SLOT_STATES.items()}.get(rec_state,
                                                                      "0x%02X" % rec_state)
        info["slot_state"] = state
        if state == "pending":
            ok("%s: slot record says PENDING - the loader will trial it once, then roll "
               "back unless `make commit` is run" % path.name)
        else:
            ok("%s: slot record state '%s'" % (path.name, state))
    else:
        info["slot_state"] = "none"
        note("%s has no slot record - a plain upload (no A/B rollback)" % path.name)

    if entry > 0xFFFF or sp > 0xFFFF:
        bad("%s: entry/stack 0x%04X/0x%04X outside the 16-bit address space"
            % (path.name, entry, sp))

    if source is not None and source.exists() and path.stat().st_mtime < source.stat().st_mtime:
        bad("%s is older than %s - rebuild the image" % (path.name, source.relative_to(ROOT)))
    return info


# ------------------------------------------------------------- 4. freshness
def check_freshness(bit: Path, rom: Path) -> None:
    if bit.exists() and rom.exists() and bit.stat().st_mtime < rom.stat().st_mtime:
        bad("bitstream is older than the boot ROM - rebuild it, the old monitor is "
            "still inside")
    elif bit.exists() and rom.exists():
        ok("bitstream is newer than the boot ROM (the monitor in it is current)")


# --------------------------------------------------------------- manifest
def write_manifest(out_dir: Path, variant: str, freq: float, info: dict,
                   seconds: float) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "generated_by": "scripts/sv16_release.py",
        "git_commit": run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip(),
        "variant": {"clksrc": variant, "constraint_mhz": freq},
        "artifacts": info,
        "checks": {"passed": len(passes), "failed": len(fails),
                   "notes": notes, "failures": fails},
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    readme = out_dir / "README.txt"
    lines = [
        "SV-16 release - %s  (variant: %s, %.2f MHz constraint)"
        % (manifest["generated"], variant, freq),
        "git %s, verified by scripts/sv16_release.py in %.0f s" % (
            manifest["git_commit"], seconds),
        "",
        "Checks: %d passed, %d failed" % (len(passes), len(fails)),
    ]
    lines += ["  FAIL: %s" % f for f in fails]
    lines += ["", "The four artifacts", "-" * 60]
    for key in ("rom", "bitstream"):
        value = info.get(key)
        if not isinstance(value, dict) or not value.get("path"):
            continue
        lines.append("%-10s %s" % (key.upper(), value["path"]))
        size = ("%d bytes  " % value["bytes"]) if "bytes" in value else ""
        lines.append("%-10s %ssha256 %s" % ("", size, value["sha256"]))
        if key == "bitstream" and value.get("fmax_mhz"):
            lines.append("%-10s %.2f MHz Fmax (%s), budget %s"
                         % ("", value["fmax_mhz"], value.get("fmax_clock", "clock"),
                            value.get("budget", "?")))
        if key == "rom" and "words" in value:
            lines.append("%-10s %d/%d words (part of the bitstream, not programmed "
                         "separately)" % ("", value["words"], value["capacity"]))
    for name, image in (info.get("images") or {}).items():
        lines.append("%-10s %s  %d bytes, slot record: %s"
                     % ("IMAGE", image.get("path", name), image.get("bytes", 0),
                        image.get("slot_state", "none")))
    det = info.get("determinism")
    if det:
        lines.append("")
        lines.append("Determinism: bitstream reproduced byte for byte across two builds: %s"
                     % ("yes" if det["same_hash"] else "NO"))
    lines += [
        "",
        "Programming sequence (TEAM_PLAN.md section 14.1, BOARD.md section 9.1)",
        "-" * 60,
        " 1. make prog CABLE=ft232              # volatile config over JTAG (safe)",
        " 2. make mon-term PORT=/dev/ttyUSB0    # 115200, expect the monitor banner",
        " 3. make prog-flash CABLE=ft232        # persistent: writes the config flash U2",
        " 4. make upload-slot SLOT=1 PORT=...   # firmware into U3 over UART",
        "    make mon-boot && make commit       # trial the pending slot, then keep it",
        "",
        "The boot ROM cannot be updated over the serial port - it is part of the",
        "bitstream, so a monitor change means rebuilding and re-flashing steps 1/3.",
    ]
    readme.write_text("\n".join(lines) + "\n")
    return manifest_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build", action="store_true",
                    help="run `make firmware bitstream` first")
    ap.add_argument("--twice", action="store_true",
                    help="rebuild the bitstream and compare hashes (determinism)")
    ap.add_argument("--clksrc", default="osc", choices=("osc", "pll"))
    ap.add_argument("--freq", type=float, default=None,
                    help="timing constraint in MHz (default: 25 for osc, 37.5 for pll)")
    ap.add_argument("--build-dir", default="build")
    ap.add_argument("--out-dir", default=None, help="manifest directory (default: <build>/release)")
    args = ap.parse_args()

    freq = args.freq if args.freq is not None else (37.5 if args.clksrc == "pll" else 25.0)
    build = (ROOT / args.build_dir).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else build / "release"
    started = time.time()

    print("SV-16 release check  (%s, %.2f MHz, %s)"
          % (args.clksrc, freq, build.relative_to(ROOT)))

    if args.build:
        print("\nbuilding firmware + bitstream ...")
        proc = subprocess.run(["make", "firmware", "bitstream", "CLKSRC=%s" % args.clksrc,
                               "BUILD=%s" % args.build_dir, "FPGA_FREQ=%g" % freq],
                              cwd=ROOT)
        if proc.returncode != 0:
            print("build failed", file=sys.stderr)
            return 1

    print("\nboot ROM (artifact 4)")
    info: dict = {"rom": check_rom(build / "rom" / "monitor.hex",
                                   ROOT / "firmware" / "monitor" / "monitor.s")}

    print("\nbitstream (artifacts 1 and 2)")
    bit = build / "sv16_top.bit"
    info["bitstream"] = check_bitstream(bit, build / "sv16_nextpnr.log", freq)
    check_freshness(bit, build / "rom" / "monitor.hex")

    print("\nfirmware images (artifact 3)")
    images = {}
    app_src = ROOT / "firmware" / "examples" / "motor_test.s"
    for name, candidate in (("motor_test", build / "fw" / "motor_test_img.hex"),
                            ("slot1", build / "fw" / "app_slot1_img.hex"),
                            ("wdt_hang", build / "fw" / "wdt_hang_img.hex")):
        if candidate.exists():
            images[name] = check_image(candidate, app_src)
    if not images:
        note("no images in %s - run `make app` and `make slot-image SLOT=1`" % build)

    if args.twice and bit.exists():
        print("\ndeterminism (rebuild the bitstream and compare)")
        first = sha256(bit)
        proc = subprocess.run(["make", "-B", "bitstream", "CLKSRC=%s" % args.clksrc,
                               "BUILD=%s" % args.build_dir, "FPGA_FREQ=%g" % freq],
                              cwd=ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            bad("rebuild failed: %s" % proc.stderr.strip()[-200:])
        elif sha256(bit) == first:
            ok("bitstream reproduces byte for byte (%s...)" % first[:16])
        else:
            bad("bitstream changed between identical builds - the flow is not "
                "deterministic (check for timestamps in the build)")
        info["determinism"] = {"same_hash": sha256(bit) == first, "sha256": first}

    info["images"] = images
    manifest = write_manifest(out_dir, args.clksrc, freq, info, time.time() - started)

    print("\n%d checks passed, %d failed" % (len(passes), len(fails)))
    for failure in fails:
        print("  FAIL: %s" % failure)
    print("manifest: %s" % manifest.relative_to(ROOT))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
