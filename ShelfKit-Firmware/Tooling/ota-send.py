#!/usr/bin/env python3
"""Send a firmware image to a tag over the hub's wireless link (OTA update).

    python ShelfKit-Firmware/Tooling/ota-send.py Release/vusion-20261020-86d8bfa-dirty.hex
    python ShelfKit-Firmware/Tooling/ota-send.py build/firmware.bin --addr 0100 -p COM4
    python ShelfKit-Firmware/Tooling/ota-send.py firmware.hex --dry-run

The image is the application's binary (a .hex file is converted). It goes out as
the same reliable DATA frames images use, one chunk per frame, so the hub needs no
new code and a retried frame is harmless: the tag only accepts a chunk whose
offset is exactly how many bytes it already has.

The tag writes the chunks into its SPI flash, checks the CRC at the end, stores a
magic sequence and resets; the bootloader notices the magic, verifies the CRC
again *before* erasing anything, programs the application and clears the magic.
If the transfer is interrupted at any point, the old firmware keeps running.

Timing: BEGIN makes the tag erase its flash (about 0.3 s for a 40 KB image), so
this script waits before the first chunk. A 40 KB image is ~1450 frames and takes
a couple of minutes at the current radio settings.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HUBHOST_DIR = REPO / "ShelfKit-Server" / "shelfkit"
sys.path.insert(0, str(HUBHOST_DIR))
import hubhost  # noqa: E402 - needs the path above

# shelfmsg.h: BEGIN/CHUNK/END and the payload sizes
SM_OP_FW_BEGIN = 4
SM_OP_FW_CHUNK = 5
SM_OP_FW_END = 6
SM_FW_HDR = 3
SM_FW_CHUNK = 28

IMAGE_MAX = 0xA700           # shelfota.h: OTA_MAX_IMAGE (0x3000..0xD7FE window)
ERASE_SETTLE_S = 0.6         # BEGIN erases ~0.3 s of sectors; leave margin


def crc16(data: bytes, crc: int = 0xFFFF) -> int:
    """CRC-16/CCITT, poly 0x1021, MSB first - shelfota.c ota_crc16()."""
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def hex_to_binary(text: str) -> bytes:
    """Intel HEX -> one binary image from address 0.

    The linker emits records out of order and leaves gaps (for instance the
    const the bootloader places with __at, or an image's unused vectors), so the
    records are collected by address first and the holes filled with 0xFF - the
    value erased flash reads as, and the value programming leaves untouched.
    """
    cells: dict[int, int] = {}
    base = 0
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if not line.startswith(":"):
            raise SystemExit(f"line {number}: not an Intel HEX record: {line[:20]!r}")
        raw = bytes.fromhex(line[1:])
        if (sum(raw) & 0xFF) != 0:
            raise SystemExit(f"line {number}: bad checksum")
        count, addr, rtype = raw[0], (raw[1] << 8) | raw[2], raw[3]
        payload = raw[4:4 + count]
        if rtype == 0x00:
            for i, byte in enumerate(payload):
                cells[base + addr + i] = byte
        elif rtype == 0x01:
            break
        elif rtype == 0x02:
            base = ((payload[0] << 8) | payload[1]) << 4
        elif rtype == 0x04:
            base = ((payload[0] << 8) | payload[1]) << 16
        elif rtype not in (0x03, 0x05):
            raise SystemExit(f"line {number}: unsupported record type {rtype}")
    if not cells:
        raise SystemExit("that .hex file has no data records")
    highest = max(cells)
    return bytes(cells.get(addr, 0xFF) for addr in range(highest + 1))


def load_image(path: Path) -> bytes:
    if path.suffix.lower() in (".hex", ".ihx"):
        return hex_to_binary(path.read_text(encoding="ascii", errors="replace"))
    return path.read_bytes()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("image", type=Path, help=".hex/.ihx or raw .bin firmware image")
    parser.add_argument("--addr", default="0100", help="tag node id in hex (default 0100)")
    parser.add_argument("-p", "--port", help="hub serial port (default: the port hubhost picks)")
    parser.add_argument("--chunk", type=int, default=SM_FW_CHUNK,
                        help=f"bytes per frame (max {SM_FW_CHUNK}, default {SM_FW_CHUNK})")
    parser.add_argument("--dry-run", action="store_true", help="parse and checksum only")
    args = parser.parse_args(argv)

    if not args.image.is_file():
        raise SystemExit(f"{args.image} is not a file")
    image = load_image(args.image)
    if len(image) < 4:
        raise SystemExit("that image is too small to be an application")
    if image[0] != 0x02:
        raise SystemExit(f"image does not start with a reset jump (0x{image[0]:02X}); "
                         "the bootloader needs 0x02 hi lo at offset 0")
    if len(image) > IMAGE_MAX:
        raise SystemExit(f"image is {len(image)} B, the bootloader region allows {IMAGE_MAX} B")

    crc = crc16(image)
    entry = (image[1] << 8) | image[2]
    chunk = max(1, min(args.chunk, SM_FW_CHUNK))
    frames = (len(image) + chunk - 1) // chunk
    print(f"image   {args.image.name}: {len(image)} B, entry 0x{entry:04X}, "
          f"crc 0x{crc:04X}")
    print(f"frames  {frames} x {chunk} B, tag 0x{int(args.addr, 16):04X}")
    if args.dry_run:
        print("dry run: nothing sent")
        return 0

    hub = hubhost.Hub(args.port)
    if not hub.ping():
        raise SystemExit("the hub did not answer P - right port, hub flashed?")
    hub.send_data(int(args.addr, 16),
                  bytes([SM_OP_FW_BEGIN, len(image) & 0xFF, len(image) >> 8,
                         crc & 0xFF, crc >> 8]))
    print("BEGIN sent, waiting for the tag to erase its flash ...")
    time.sleep(ERASE_SETTLE_S)

    started = time.time()
    for index, offset in enumerate(range(0, len(image), chunk)):
        payload = bytes([SM_OP_FW_CHUNK, offset & 0xFF, offset >> 8]) + image[offset:offset + chunk]
        if not hub.send_data(int(args.addr, 16), payload):
            raise SystemExit(f"\nframe {index + 1}/{frames} was not acknowledged; "
                             "the tag will not commit a partial image")
        if index % 50 == 0 or index == frames - 1:
            done = min(offset + chunk, len(image))
            rate = done / max(time.time() - started, 1e-3)
            print(f"  {done:6d}/{len(image)} B  {100.0 * done / len(image):5.1f}%  "
                  f"{rate / 1024:.1f} KB/s", end="\r" if index < frames - 1 else "\n")

    hub.send_data(int(args.addr, 16), bytes([SM_OP_FW_END]))
    print("END sent: the tag verifies, commits and resets into the bootloader")
    return 0


if __name__ == "__main__":
    sys.exit(main())
