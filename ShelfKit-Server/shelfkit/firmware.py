"""OTA firmware images: Intel HEX to binary, the CRC, and the DATA payloads.

One place for the wire format, shared by the server's Reflash action and by
Tooling/ota-send.py, so the two cannot disagree about an opcode or the CRC. The
constants mirror `Shared/firmware/shelflink/inc/shelfmsg.h` and
`Shared/firmware/shelfota/inc/shelfota.h`.
"""

from __future__ import annotations

from pathlib import Path

# shelfmsg.h: firmware transfer opcodes and the payload layout
SM_OP_FW_BEGIN = 4
SM_OP_FW_CHUNK = 5
SM_OP_FW_END = 6
SM_FW_HDR = 3
SM_FW_CHUNK = 28          # SL_MAX_PAYLOAD - SM_FW_HDR

# shelfota.h: the image has to fit between 0x3000 and the bootloader's jump vector
IMAGE_MAX = 0xA7F0        # 0x3000..0xD7FE, minus the two vector bytes
BYTES = "bytes"           # only used in messages


class ImageError(ValueError):
    """The file is not something the tag can accept."""


def crc16(data: bytes, crc: int = 0xFFFF) -> int:
    """CRC-16/CCITT, poly 0x1021, MSB first - shelfota.c ota_crc16()."""
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def hex_to_binary(text: str) -> bytes:
    """Intel HEX -> one binary image from address 0.

    Records arrive out of order and with gaps (the linker emits neither the
    padding between sections nor anything it did not write), so they are
    collected by address and the holes filled with 0xFF: the value erased flash
    reads as, and the value programming leaves untouched.
    """
    cells: dict[int, int] = {}
    base = 0
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if not line.startswith(":"):
            raise ImageError(f"line {number}: not an Intel HEX record")
        try:
            raw = bytes.fromhex(line[1:])
        except ValueError:
            raise ImageError(f"line {number}: not hex")
        if (sum(raw) & 0xFF) != 0:
            raise ImageError(f"line {number}: bad checksum")
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
            raise ImageError(f"line {number}: unsupported record type {rtype}")
    if not cells:
        raise ImageError("that .hex file has no data records")
    highest = max(cells)
    if highest >= 0x10000:
        raise ImageError(f"address 0x{highest:04X} is outside the 64 KB flash")
    return bytes(cells.get(addr, 0xFF) for addr in range(highest + 1))


def load_image(path: Path) -> bytes:
    """Read a .hex/.ihx or a raw .bin and return the application binary."""
    path = Path(path)
    if not path.is_file():
        raise ImageError(f"{path} is not a file")
    try:
        if path.suffix.lower() in (".hex", ".ihx"):
            return hex_to_binary(path.read_text(encoding="ascii", errors="replace"))
        return path.read_bytes()
    except OSError as exc:
        raise ImageError(f"cannot read {path}: {exc}")


def check_image(path: Path) -> tuple[bytes, int]:
    """Load an image and check it is one the bootloader can install.

    Returns (image, entry address). Raises ImageError with a reason the UI can
    show, before anything is sent.
    """
    image = load_image(path)
    if len(image) < 4:
        raise ImageError("that image is too small to be an application")
    if image[0] != 0x02:
        raise ImageError(
            f"image starts with 0x{image[0]:02X}, not a reset jump (0x02); "
            "the bootloader needs 02 hi lo at offset 0")
    if len(image) > IMAGE_MAX:
        raise ImageError(
            f"image is {len(image)} bytes, the OTA window allows {IMAGE_MAX}")
    return image, (image[1] << 8) | image[2]


def frames(image: bytes, chunk: int = SM_FW_CHUNK):
    """The DATA payloads of one transfer: BEGIN, one CHUNK each, END."""
    chunk = max(1, min(chunk, SM_FW_CHUNK))
    crc = crc16(image)
    yield bytes([SM_OP_FW_BEGIN, len(image) & 0xFF, len(image) >> 8,
                 crc & 0xFF, crc >> 8])
    for offset in range(0, len(image), chunk):
        yield (bytes([SM_OP_FW_CHUNK, offset & 0xFF, offset >> 8])
               + image[offset:offset + chunk])
    yield bytes([SM_OP_FW_END])
