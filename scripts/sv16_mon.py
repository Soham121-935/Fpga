#!/usr/bin/env python3
"""SV-16 host programmer — drive the ROM monitor over UART to update flash.

    scripts/sv16_mon.py upload  build/fw/motor_test_img.hex [--port /dev/ttyUSB0]
    scripts/sv16_mon.py upload  build/fw/motor_test_img.hex --slot 1
    scripts/sv16_mon.py verify  --port /dev/ttyUSB0 [--slot 1]
    scripts/sv16_mon.py boot    --port /dev/ttyUSB0
    scripts/sv16_mon.py commit  --port /dev/ttyUSB0      # confirm a trial image
    scripts/sv16_mon.py term    --port /dev/ttyUSB0
    scripts/sv16_mon.py reset   --port /dev/ttyUSB0      # DTR/RTS reset pulse

Field update into the inactive slot (ADR-019):

    python3 scripts/sv16_fwpack.py build/fw/app.hex -o build/fw/app --slot 1
    scripts/sv16_mon.py upload build/fw/app_img.hex --slot 1
    scripts/sv16_mon.py boot           # the loader picks the new image and puts
                                       # it on trial
    scripts/sv16_mon.py commit         # ... and commits it once it looks good

An image packed without --slot carries no record, so the loader boots it without
a trial (that is how the monitor's own recovery image behaves).

`upload` implements the C (program) command of the ROM monitor
(see docs/BOOT_AND_PROGRAMMING.md):

    C<addr4><len4><crc4>   then len*2 hex digits of payload, no separator
    '.'                    one dot per byte accepted
    +OK / -Exx             result after the whole payload has been consumed

Each byte is sent as two hex characters and the monitor answers with one '.',
so the exchange is self-clocking: this script waits for the dot before sending
the next byte and therefore never overruns the monitor's single-byte receive
FIFO, whatever the host's line rate.

Requires pyserial (`pip install pyserial`).  Without a working port the tool
still packs and prints what it would send (--dry-run), which is enough to
verify the image the monitor will accept.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

from sv16_fwpack import crc16_ccitt  # noqa: E402

DEFAULT_BAUD = 115200
ROOT = "build/fw"

# ADR-019 slots: 32 KB apart, both inside the 64 KB window the monitor's 16-bit
# update protocol can address.
SLOT_BASES = {0: 0x0000, 1: 0x8000}
SLOT_REC_OFFSET = 0x18            # in the image header
SLOT_REC_SYNC = 0xA5
SLOT_STATES = {0x1F: "pending", 0x0F: "tried", 0x07: "good", 0x04: "bad"}


# --------------------------------------------------------------------------- #
# transport
# --------------------------------------------------------------------------- #
class MonitorError(Exception):
    pass


class SerialLink:
    """Thin wrapper so the protocol code never touches pyserial directly."""

    def __init__(self, port: str, baud: int, timeout: float):
        try:
            import serial  # type: ignore
        except ImportError as exc:  # pragma: no cover - host dependent
            raise MonitorError(
                "pyserial is not installed — run: pip install pyserial"
            ) from exc
        self.ser = serial.Serial(port, baud, timeout=timeout)
        self.ser.reset_input_buffer()

    def write(self, data: bytes) -> None:
        self.ser.write(data)

    def read(self, n: int = 1) -> bytes:
        return self.ser.read(n)

    def read_until(self, terminator: bytes, deadline: float) -> bytes:
        buf = b""
        while time.monotonic() < deadline:
            chunk = self.ser.read(1)
            if not chunk:
                continue
            buf += chunk
            if buf.endswith(terminator):
                return buf
        raise MonitorError(f"timeout waiting for {terminator!r} (got {buf!r})")

    def drain(self, quiet: float = 0.05) -> bytes:
        """Read whatever is already there, until the line goes quiet."""
        self.ser.timeout = quiet
        buf = b""
        while True:
            chunk = self.ser.read(64)
            if not chunk:
                break
            buf += chunk
        return buf

    def close(self) -> None:
        self.ser.close()


# --------------------------------------------------------------------------- #
# monitor protocol
# --------------------------------------------------------------------------- #
def sync(link: SerialLink, timeout: float = 2.0) -> None:
    """Send newlines until the prompt '+' comes back, discarding leftovers."""
    deadline = time.monotonic() + timeout
    link.drain()
    while time.monotonic() < deadline:
        link.write(b"\r")
        try:
            link.read_until(b"+", min(0.25, max(0.01, deadline - time.monotonic())))
            return
        except MonitorError:
            continue
    raise MonitorError("no monitor prompt — is the SoC running the monitor? "
                       "check the reset line, the baud rate and the port")


def command(link: SerialLink, text: str, timeout: float = 5.0) -> str:
    link.write(text.encode())
    line = link.read_until(b"\n", time.monotonic() + timeout)
    reply = line.decode(errors="replace").strip()
    if not reply.startswith("+OK") and not reply.startswith("="):
        raise MonitorError(f"command {text!r} rejected: {reply!r}")
    return reply


def image_from_args(args) -> tuple[bytes, int]:
    """Return (image bytes, flash address for the C command).

    With --slot the image goes to that slot's base in the A/B area and must
    carry the slot record the loader reads (the packer writes it with --slot)."""
    if args.image.endswith(".hex"):
        data = bytes(int(line, 16) for line in
                     (l.strip() for l in open(args.image)) if line)
    else:
        data = open(args.image, "rb").read()
    if len(data) > 0x10000:
        raise MonitorError("image larger than the 64 KB flash window")

    slot = getattr(args, "slot", None)
    addr = SLOT_BASES[slot] if slot is not None else 0
    if slot is not None:
        if len(data) > slot_stride():
            raise MonitorError(f"image does not fit in a {slot_stride()} byte slot")
        if data[SLOT_REC_OFFSET] != SLOT_REC_SYNC:
            raise MonitorError(
                "image carries no slot record -- pack it with "
                f"`sv16_fwpack.py ... --slot {slot}` (see ADR-019)")
        state = SLOT_STATES.get(data[SLOT_REC_OFFSET + 1], "unknown")
        print(f"[sv16-mon] slot {slot}: record state '{state}', "
              f"installing at 0x{addr:04X}")
    return data, addr


def slot_stride() -> int:
    return SLOT_BASES[1] - SLOT_BASES[0]


def upload(link: SerialLink, image: bytes, addr: int = 0, sector_size: int = 4096,
           verbose: bool = True) -> None:
    """Erase the sectors the image touches, then stream it as one C command."""
    end = addr + len(image)
    first = (addr // sector_size) * sector_size
    erased = 0
    for base in range(first, ((end + sector_size - 1) // sector_size) * sector_size,
                      sector_size):
        if erase(link, base):
            erased += 1
    if verbose:
        print(f"[sv16-mon] erased {erased} sector(s) of {sector_size} bytes")

    crc = crc16_ccitt(image)
    header = f"C{addr:04X}{len(image):04X}{crc:04X}"
    link.write(header.encode())
    if verbose:
        print(f"[sv16-mon] {header} — streaming {len(image)} bytes "
              f"(CRC16 0x{crc:04X})")

    # Self-clocking upload: every byte is followed by one '.' from the monitor.
    # '\r' restarts the wire state machine if a byte is ever mangled, which the
    # monitor treats as a fresh command.
    for index, byte in enumerate(image):
        link.write(f"{byte:02X}".encode())
        try:
            link.read_until(b".", time.monotonic() + 5.0)
        except MonitorError as exc:
            raise MonitorError(f"stalled after {index} byte(s): {exc}") from exc
        if verbose and (index + 1) % 256 == 0:
            print(f"[sv16-mon]   {index + 1}/{len(image)} bytes")
    reply = link.read_until(b"\n", time.monotonic() + 20.0).decode(errors="replace")
    if "-E" in reply:
        raise MonitorError(f"monitor rejected the image: {reply.strip()!r}")
    if verbose:
        print(f"[sv16-mon] {reply.strip()}")


def erase(link: SerialLink, sector_addr: int) -> bool:
    """Erase one sector.  Returns False if the sector was already blank."""
    # The monitor has no "is it blank?" reply, so erase unconditionally; flash
    # erases are idempotent and fast enough at this size.
    command(link, f"E{sector_addr:04X}", timeout=10.0)
    return True


def verify(link: SerialLink, addr: int = 0) -> int:
    reply = command(link, f"V{addr:04X}", timeout=10.0)
    crc = int(reply.lstrip("="), 16)
    print(f"[sv16-mon] image CRC16 in flash at 0x{addr:04X}: 0x{crc:04X}")
    return crc


def commit(link: SerialLink) -> None:
    """Confirm a trial image (monitor command K, ADR-019)."""
    reply = command(link, "K", timeout=20.0)
    print(f"[sv16-mon] {reply}")
    if "-E8" in reply:
        raise MonitorError("the loader did not record the confirmation")


def boot(link: SerialLink) -> None:
    reply = command(link, "B", timeout=20.0)
    print(f"[sv16-mon] {reply}")


def terminal(link: SerialLink, seconds: float) -> None:
    print("[sv16-mon] interactive: Ctrl-C to leave")
    deadline = time.monotonic() + seconds if seconds else None
    try:
        while deadline is None or time.monotonic() < deadline:
            data = link.read(1)
            if data:
                sys.stdout.write(data.decode(errors="replace"))
                sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        print()


# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action",
                        choices=["upload", "verify", "boot", "commit", "term",
                                 "dump", "reset"],
                        help="what to do with the monitor")
    parser.add_argument("--slot", type=int, choices=[0, 1], default=None,
                        help="A/B slot for upload/verify (ADR-019): the image "
                             "must be packed with the matching --slot")
    parser.add_argument("image", nargs="?", default=f"{ROOT}/motor_test_img.hex",
                        help="image to upload (raw .bin or one-byte-per-line .hex)")
    parser.add_argument("--port", default=os.environ.get("SV16_PORT", "/dev/ttyUSB0"),
                        help="serial port of the SoC (env: SV16_PORT)")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD,
                        help="console baud rate (UART0 reset default is 115200)")
    parser.add_argument("--stats", default=f"{ROOT}/motor_test.txt",
                        help="fwpack report to check the image CRC against")
    parser.add_argument("--dry-run", action="store_true",
                        help="pack and print the upload header, do not touch the port")
    parser.add_argument("--time", type=float, default=0.0,
                        help="seconds to stay in the terminal (0 = until Ctrl-C)")
    args = parser.parse_args(argv)

    if args.action == "reset":
        # The ECP5 has no reset line on the UART; pull DTR low for a moment so
        # that an external reset circuit (or a USB-serial board wired to
        # ext_rst_n through a transistor) reset the SoC.
        try:
            import serial  # type: ignore
        except ImportError:
            print("[sv16-mon] pyserial is not installed — run: pip install pyserial")
            return 1
        ser = serial.Serial(args.port, args.baud)
        ser.dtr = False
        time.sleep(0.1)
        ser.dtr = True
        ser.close()
        print("[sv16-mon] reset pulse sent on DTR")
        return 0

    if args.action in ("upload",) and args.dry_run:
        image, addr = image_from_args(args)
        crc = crc16_ccitt(image)
        print(f"[sv16-mon] image {args.image}: {len(image)} bytes, "
              f"CRC16 0x{crc:04X}")
        print(f"[sv16-mon] would send: C{addr:04X}{len(image):04X}{crc:04X}"
              f" + {len(image) * 2} hex digits")
        if os.path.exists(args.stats):
            report = open(args.stats).read()
            for line in report.splitlines():
                if line.startswith("payload CRC16"):
                    print(f"[sv16-mon] {line}")
        return 0

    try:
        link = SerialLink(args.port, args.baud, timeout=0.5)
    except (MonitorError, OSError) as exc:
        print(f"[sv16-mon] cannot open {args.port}: {exc}")
        return 1

    try:
        if args.action in ("upload", "verify", "boot", "commit"):
            sync(link)
        if args.action == "upload":
            image, addr = image_from_args(args)
            upload(link, image, addr)
            if os.path.exists(args.stats):
                for line in open(args.stats):
                    if line.startswith("payload CRC16"):
                        print(f"[sv16-mon] image built with "
                              f"{line.strip()}")
            verify(link, addr)
        elif args.action == "verify":
            verify(link, SLOT_BASES[args.slot] if args.slot is not None else 0)
        elif args.action == "boot":
            boot(link)
        elif args.action == "commit":
            commit(link)
        elif args.action == "term":
            terminal(link, args.time)
        elif args.action == "dump":
            link.write(b"\r")
            sys.stdout.write(link.drain().decode(errors="replace"))
    except MonitorError as exc:
        print(f"[sv16-mon] error: {exc}")
        return 1
    finally:
        link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
