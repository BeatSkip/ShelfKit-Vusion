#!/usr/bin/env python3
"""Read a tag's SPI flash back over the radio.

    python ShelfKit-Firmware/Tooling/flash-read.py 0102
    python ShelfKit-Firmware/Tooling/flash-read.py 0102 --range 0:0x3000 -p COM4
    python ShelfKit-Firmware/Tooling/flash-read.py --from-log console.txt

The tag serves one request at a time: the host asks for a page, the tag reads it
and streams it back in DATA frames, the hub prints each frame as `flash=<hex>` on
its UART, and this script puts the bytes back together. Nothing has to be plugged
into the tag — the only serial port is the hub.

Default range is `0x0000..0x2FFF`: the OTA header, the identity record and the
reserved sector — every byte of metadata the firmware keeps. `--range 0:0x10000`
dumps the lot (a 4 KB page takes a few seconds at the current rate).

`--from-log` reassembles a saved Console log instead of opening the port, which
works when the dump was captured by the server or by hand.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ShelfKit-Server"))

from shelfkit import firmware, hubhost  # noqa: E402 - needs the path above

from shelfkit import flashdump  # noqa: E402 - needs the path above

SM_OP_FLASH_DUMP = flashdump.SM_OP_FLASH_DUMP
SM_OP_FLASH_DATA = flashdump.SM_OP_FLASH_DATA
PAGE = flashdump.PAGE
parse_line = flashdump.parse_line
assemble = flashdump.assemble
hexdump = flashdump.hexdump
describe = flashdump.describe


def read_over_radio(tag: int, start: int, end: int, port: str | None,
                    settle: float) -> list[str]:
    """Ask the tag page by page and collect the hub's log lines."""
    hub = hubhost.Hub(port)
    if not hub.ping():
        raise SystemExit("the hub did not answer P - right port, hub flashed?")
    lines: list[str] = []
    for page_start in range(start, end, PAGE):
        length = min(PAGE, end - page_start)
        payload = bytes([SM_OP_FLASH_DUMP,
                         page_start & 0xFF, (page_start >> 8) & 0xFF, (page_start >> 16) & 0xFF,
                         length & 0xFF, length >> 8])
        print(f"  request 0x{page_start:04X}..0x{page_start + length - 1:04X} "
              f"({length} B)", flush=True)
        if not hub.send_data(tag, payload):
            raise SystemExit(f"the tag did not acknowledge the request for 0x{page_start:04X}")

        # the tag streams the page back; wait until it has sent all of it
        deadline = time.time() + settle + length / 512.0
        got: dict[int, bytes] = {}
        while time.time() < deadline:
            line = hub.read_line(timeout=0.5)
            if not line:
                continue
            lines.append(line)
            parsed = parse_line(line)
            if parsed is None:
                continue
            _src, addr, data = parsed
            if page_start <= addr < page_start + length:
                got[addr] = data
                have = sum(len(chunk) for chunk in got.values())
                print(f"\r  received {have:5d}/{length} B", end="", flush=True)
                if have >= length:
                    break
        print()
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tag", nargs="?", help="tag node id in hex, e.g. 0102")
    parser.add_argument("--range", default="0:0x3000",
                        help="first:last, hex (default 0:0x3000 = all metadata)")
    parser.add_argument("-p", "--port", help="hub serial port (default: hubhost picks)")
    parser.add_argument("-o", "--out", help="output folder (default Data/dumps)")
    parser.add_argument("--from-log", help="reassemble a saved Console log instead of the radio")
    parser.add_argument("--settle", type=float, default=3.0,
                        help="seconds to keep reading after a page (default 3)")
    args = parser.parse_args(argv)

    if not args.from_log and not args.tag:
        parser.error("give a tag id, or --from-log FILE")

    try:
        start, end = (int(part, 16) for part in args.range.split(":"))
    except ValueError:
        parser.error("--range wants first:last in hex, e.g. 0:0x3000")
    if end <= start:
        parser.error("--range must end after it starts")
    size = end - start

    if args.from_log:
        lines = Path(args.from_log).read_text(encoding="utf-8", errors="replace").splitlines()
        print(f"reading {len(lines)} lines from {args.from_log}")
    else:
        tag = int(args.tag, 16)
        print(f"tag 0x{tag:04X}: 0x{start:04X}..0x{end - 1:04X} ({size} B)")
        lines = read_over_radio(tag, start, end, args.port, args.settle)

    data = assemble(lines, size, start)
    frames = sum(1 for line in lines if parse_line(line))
    print(f"\n{frames} frames, {size} bytes assembled")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    where = Path(args.out) if args.out else REPO / "Data" / "dumps"
    where.mkdir(parents=True, exist_ok=True)
    name = f"flash-{'log' if args.from_log else f'{int(args.tag, 16):04X}'}-{stamp}"
    binary = where / f"{name}.bin"
    binary.write_bytes(data)
    text = where / f"{name}.txt"
    text.write_text(hexdump(data, start), encoding="utf-8")
    print(f"  written: {binary.relative_to(REPO) if where.is_relative_to(REPO) else binary}")
    print(f"           {text.relative_to(REPO) if where.is_relative_to(REPO) else text}")

    frames = sum(1 for line in lines if parse_line(line))
    for note in flashdump.summary(data, start, frames):
        print(f"  {note}")
    print(f"  written to {name}.bin / .txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
