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
sys.path.insert(0, str(REPO / "ShelfKit-Server"))

from shelfkit import firmware, hubhost  # noqa: E402 - needs the path above

SM_OP_FW_BEGIN = firmware.SM_OP_FW_BEGIN
SM_OP_FW_CHUNK = firmware.SM_OP_FW_CHUNK
SM_OP_FW_END = firmware.SM_OP_FW_END
SM_FW_CHUNK = firmware.SM_FW_CHUNK
IMAGE_MAX = firmware.IMAGE_MAX   # 0xA7F0, the 0x3000..0xD7FE window
crc16 = firmware.crc16
load_image = firmware.load_image
# the tag erases its flash after BEGIN; give it room before the first chunk
ERASE_SETTLE_S = 0.6


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

    try:
        image, entry = firmware.check_image(args.image)
    except firmware.ImageError as exc:
        raise SystemExit(str(exc))

    crc = crc16(image)
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
