#!/usr/bin/env python3
"""Give a tag its wireless identity over the air.

    python ShelfKit-Firmware/Tooling/set-id.py 3F2A 0100 -p COM4
    python ShelfKit-Firmware/Tooling/set-id.py 3F2A 0100 --dry-run

Arguments are "current id -> new id", both hex. A tag that was never provisioned
polls with a random 16-bit id and logs it on boot (`id? 3F2A new`), and the hub
prints it in every `POLL src=3f2a …` line, so the current id is easy to find.

The tag stores the new id in its SPI flash, reads it back, then moves its radio
address to it - so the next poll arrives with the new id. Nothing about a firmware
update touches that record: one image still fits every tag.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ShelfKit-Server"))
from shelfkit import hubhost  # noqa: E402 - needs the path above

SM_OP_SET_ID = 7          # shelfmsg.h


def node_id(text: str) -> int:
    try:
        value = int(text, 16)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not hex")
    if value < 2 or value > 0xFFFF:
        raise argparse.ArgumentTypeError("node ids are 0x0002..0xFFFF (0 and 1 are reserved)")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("current", type=node_id, help="the id the tag polls with now")
    parser.add_argument("new", type=node_id, help="the id to give it")
    parser.add_argument("-p", "--port", help="hub serial port")
    parser.add_argument("--dry-run", action="store_true", help="print the frame only")
    args = parser.parse_args(argv)

    frame = bytes([SM_OP_SET_ID, args.new & 0xFF, args.new >> 8])
    print(f"{args.current:04X} -> {args.new:04X}   payload {frame.hex(' ')}")
    if args.dry_run:
        return 0

    hub = hubhost.Hub(args.port)
    if not hub.ping():
        raise SystemExit("the hub did not answer P - right port, hub flashed?")
    if not hub.send_data(args.current, frame):
        raise SystemExit("the tag did not acknowledge; its id is unchanged")
    print(f"acknowledged - {args.new:04X} polls next")
    return 0


if __name__ == "__main__":
    sys.exit(main())
