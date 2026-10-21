"""SPI flash read-back: the frames, the assembly, and what the bytes mean.

Shared by the server's "Read flash" action and by
`ShelfKit-Firmware/Tooling/flash-read.py`, so both agree about the wire format
and about how to describe a record.

The tag answers a `SM_OP_FLASH_DUMP` request with `SM_OP_FLASH_DATA` frames; the
hub prints each one on its UART as `… flash=<addr3><n><bytes>`, which is how the
bytes get back to the host. A line looks like:

    DATA src=0102 seq=1a rssi=-30 flash=0010000a534b4944010102…
                                                 ^^ address ^n data
"""

from __future__ import annotations

import re

# shelfmsg.h
SM_OP_FLASH_DUMP = 9
SM_OP_FLASH_DATA = 10
PAGE = 4096                 # SM_DUMP_MAX: one request is at most a page
DEFAULT_RANGE = (0x0000, 0x3000)   # OTA header + identity + reserved sector

#: "DATA src=0102 seq=1a rssi=-30 flash=<addr3><n><bytes>"
RE_FLASH = re.compile(r"DATA src=([0-9a-fA-F]{4})\b.*\bflash=([0-9a-fA-F]+)")


def request_payload(start: int, length: int) -> bytes:
    """The `SM_OP_FLASH_DUMP` payload for one page."""
    return bytes([SM_OP_FLASH_DUMP,
                  start & 0xFF, (start >> 8) & 0xFF, (start >> 16) & 0xFF,
                  length & 0xFF, (length >> 8) & 0xFF])


def parse_line(line: str) -> tuple[str, int, bytes] | None:
    """One hub log line -> (source id, address, bytes), or None if it is not one."""
    match = RE_FLASH.search(line)
    if not match:
        return None
    try:
        raw = bytes.fromhex(match.group(2))
    except ValueError:
        return None
    if len(raw) < 5:
        return None
    address = raw[0] | (raw[1] << 8) | (raw[2] << 16)
    count = raw[3]
    data = raw[4:4 + count]
    if len(data) != count:
        return None                 # a torn line: ignore it rather than guess
    return match.group(1).lower(), address, data


def assemble(lines, size: int, base: int) -> bytearray:
    """Collect dump frames into a buffer; whatever never arrived stays 0xFF."""
    image = bytearray(b"\xff" * size)
    for line in lines:
        parsed = parse_line(line)
        if parsed is None:
            continue
        _source, address, data = parsed
        offset = address - base
        if offset < 0 or offset + len(data) > size:
            continue
        image[offset:offset + len(data)] = data
    return image


def hexdump(data: bytes, base: int = 0) -> str:
    out = []
    for start in range(0, len(data), 16):
        chunk = data[start:start + 16]
        text = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in chunk)
        cells = " ".join(f"{byte:02x}" for byte in chunk)
        out.append(f"{base + start:06x}  {cells:<47}  {text}")
    return "\n".join(out) + "\n"


def describe(data: bytes, base: int) -> list[str]:
    """What the bytes mean, in the terms the firmware uses."""
    from . import firmware

    notes = []
    if base <= 0x1000 and base + len(data) >= 0x100A:
        record = data[0x1000 - base:0x1000 - base + 10]
        if record[:4] == b"SKID":
            ident = record[6] | (record[7] << 8)
            crc_ok = firmware.crc16(record[:8]) == (record[8] | (record[9] << 8))
            notes.append(
                f"identity: id 0x{ident:04X} "
                f"({'assigned' if record[5] & 1 else 'random'}), "
                f"version {record[4]}, CRC {'ok' if crc_ok else 'BAD'}")
        elif record == b"\xff" * 10:
            notes.append("identity: blank (no record - the tag will generate one)")
        else:
            notes.append(f"identity: no magic ({record[:4].hex()})")
    if base == 0 and len(data) >= 16:
        header = data[0:16]
        if header[:4] == b"SKFW":
            length = header[6] | (header[7] << 8)
            crc = header[8] | (header[9] << 8)
            header_ok = firmware.crc16(header[:10]) == (header[10] | (header[11] << 8))
            notes.append(
                f"OTA header: image {length} B, CRC 0x{crc:04X}, "
                f"header CRC {'ok' if header_ok else 'BAD'} -> "
                f"{'a pending update' if header_ok else 'ignored by the bootloader'}")
        elif header == b"\xff" * 16:
            notes.append("OTA header: blank (no pending update)")
        else:
            notes.append(f"OTA header: no magic ({header[:4].hex()})")
        if data[0] == 0x02:
            notes.append(f"internal reset jump: ljmp 0x{(data[1] << 8) | data[2]:04X}")
    if base <= 0x2000 and base + len(data) >= 0x2010:
        reserved = data[0x2000 - base:0x2000 - base + 16]
        notes.append("reserved sector: " + ("blank" if reserved == b"\xff" * 16 else "in use"))
    return notes


def summary(data: bytearray, base: int, frames: int) -> list[str]:
    """`describe()` plus the count of bytes nobody sent."""
    notes = describe(bytes(data), base)
    blank = sum(1 for byte in data if byte == 0xFF)
    notes.append(f"{frames} frames, {len(data)} bytes ({blank} still 0xFF)")
    return notes
