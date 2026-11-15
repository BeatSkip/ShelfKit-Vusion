"""The link a phone opens when it touches a tag, as bytes for the tag's NFC chip.

The chip (FM11NT081D) is an NFC Forum Type 2 tag. The tag firmware writes whole 4-byte
pages of it over SPI when the server sends SM_OP_NFC_WRITE (shelfmsg.h), and reads them
back through SM_OP_FLASH_DUMP with SM_DUMP_NFC set. What goes there:

* 0x00C, the capability container: ``E1 10 6F 00`` = NDEF, version 1.0, 888 bytes of
  data area (0x6F * 8), read and write open to everyone. SES ships the tags with a
  CC a phone reads as "0 bytes, not writable"; over NFC its bits can only be set, never
  cleared, but the wired side writes the EEPROM directly.
* 0x010, the NDEF message: one URI record in a TLV, ``03 L D1 01 PL 55 <prefix> <uri> FE``.
"""
from __future__ import annotations

SM_OP_NFC_WRITE = 14
SM_NFC_CHUNK = 28            # bytes of EEPROM per frame (7 pages)
SM_NFC_LO = 0x00C
SM_NFC_HI = 0x388
SM_DUMP_NFC = 0x800000       # SM_DUMP_NFC (0x80) in the top address byte of a dump request

CC_ADDR = 0x00C
CC = bytes([0xE1, 0x10, 0x6F, 0x00])
NDEF_ADDR = 0x010

# NFC Forum URI record prefixes; the longest that matches is abbreviated to one byte
_PREFIXES = {"https://www.": 0x02, "http://www.": 0x01, "https://": 0x04, "http://": 0x03}


def tag_url(base: str, hex_id: str) -> str:
    """The address a tag's NFC link opens: <base>/tag/<ID>."""
    return f"{base.rstrip('/')}/tag/{hex_id.upper()}"


def ndef_message(url: str) -> bytes:
    """The NDEF TLV for one URI record, padded with zeros to whole pages."""
    code, rest = 0x00, url
    for prefix, value in sorted(_PREFIXES.items(), key=lambda kv: -len(kv[0])):
        if url.startswith(prefix):
            code, rest = value, url[len(prefix):]
            break
    uri = rest.encode("utf-8")
    payload = bytes([code]) + uri
    if len(payload) > 255:
        raise ValueError("the link is too long for a short NDEF record (255 bytes)")
    record = bytes([0xD1, 0x01, len(payload), 0x55]) + payload
    tlv = bytes([0x03, len(record)]) + record + b"\xFE"
    if len(tlv) % 4:
        tlv += bytes(4 - len(tlv) % 4)
    if NDEF_ADDR + len(tlv) > SM_NFC_HI:
        raise ValueError("the link does not fit the NFC chip")
    return tlv


def image(url: str) -> bytes:
    """Everything from the CC on: what the chip should hold from CC_ADDR."""
    return CC + ndef_message(url)


def write_frames(want: bytes, have: bytes | None) -> list[bytes]:
    """SM_OP_NFC_WRITE payloads that turn `have` into `want` (both from CC_ADDR).

    Only chunks that differ are written. The chunk holding the NDEF TLV's start goes
    last: until it lands, a phone still finds the old message, never a half-written one.
    """
    chunks = []
    for off in range(0, len(want), SM_NFC_CHUNK):
        part = want[off:off + SM_NFC_CHUNK]
        if have is not None and have[off:off + len(part)] == part:
            continue
        addr = CC_ADDR + off
        chunks.append(bytes([SM_OP_NFC_WRITE, addr & 0xFF, addr >> 8]) + part)
    head = [c for c in chunks if (c[1] | c[2] << 8) <= NDEF_ADDR]
    return [c for c in chunks if c not in head] + head


def read_url(data: bytes) -> str | None:
    """The URI in an image read back from CC_ADDR, or None if there is none."""
    if len(data) < 10 or data[0] != 0xE1:
        return None
    msg = data[NDEF_ADDR - CC_ADDR:]
    if msg[0] != 0x03 or msg[1] < 5 or msg[2] & 0x07 != 0x01 or msg[5] != 0x55:
        return None
    payload = msg[6:6 + msg[4]]
    if len(payload) < 1:
        return None
    prefix = {v: k for k, v in _PREFIXES.items()}.get(payload[0], "")
    return prefix + payload[1:].decode("utf-8", "replace")
