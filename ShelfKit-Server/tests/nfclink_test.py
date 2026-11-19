#!/usr/bin/env python3
"""The NFC link a tag's chip gets over the radio (SM_OP_NFC_WRITE).

    python ShelfKit-Server/tests/nfclink_test.py

No hardware: a fake tag holds the chip's EEPROM, answers SM_OP_NFC_WRITE frames the way
ShelfKit-Axsem/src/fw_rx.c does (bounds included), and answers SM_OP_FLASH_DUMP + SM_DUMP_NFC
with the hub's `flash=` log lines. App.write_nfc_link and App._read_nfc run unchanged.
"""
from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

from shelfkit import nfclink  # noqa: E402
from shelfkit.app import App  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail=None) -> None:
    print(("ok   " if ok else "FAIL ") + name + ("" if ok or detail is None else f": {detail}"))
    if not ok:
        FAILED.append(name)


def test_encoding() -> None:
    url = nfclink.tag_url("https://shelf.example.org/", "f466")
    check("the link ends in /tag/<ID>", url == "https://shelf.example.org/tag/F466", url)
    img = nfclink.image(url)
    check("the CC says NDEF 1.0, 888 bytes, writable", img[:4] == bytes.fromhex("e1106f00"))
    msg = img[4:]
    check("one URI record with the https:// prefix code",
          msg[:2] == bytes([0x03, msg[1]]) and msg[2:4] == b"\xd1\x01" and msg[5:7] == b"\x55\x04")
    check("the TLV length covers the record", msg[1] == 4 + msg[4] and msg[2 + msg[1]] == 0xFE)
    check("whole pages", len(img) % 4 == 0)
    check("it reads back", nfclink.read_url(img) == url, nfclink.read_url(img))
    check("http and bare prefixes", nfclink.read_url(nfclink.image("http://x/tag/0102"))
          == "http://x/tag/0102" and nfclink.read_url(nfclink.image("x/tag/1")) == "x/tag/1")
    try:
        nfclink.image("https://" + "a" * 300)
        check("a link too long is refused", False)
    except ValueError:
        check("a link too long is refused", True)
    frames = nfclink.write_frames(img, None)
    addrs = [f[1] | f[2] << 8 for f in frames]
    check("a blank chip gets every chunk, the message start last",
          addrs[-1] == nfclink.CC_ADDR and sorted(addrs) == list(range(0x00C, 0x00C + len(img), 28)),
          addrs)
    check("every frame fits a radio payload", all(len(f) <= 32 for f in frames))
    check("an up-to-date chip gets nothing", nfclink.write_frames(img, img) == [])


class FakeTag:
    """The tag's NFC EEPROM and the hub log its answers end up in."""

    def __init__(self, addr: int, firmware_has_op: bool = True, cc_sticks: bool = False):
        self.addr = addr
        self.ee = bytearray(0x400)
        self.ee[0x00C:0x010] = bytes.fromhex("e110000f")     # what SES ships
        self.ee[0x010:0x013] = bytes.fromhex("0300fe")
        self.has_op = firmware_has_op
        self.cc_sticks = cc_sticks
        self.writes = []
        self.log: list = []
        self.seq = 0

    def line(self, text: str) -> None:
        self.seq += 1
        self.log.append((self.seq, 0, "", text))

    def receive(self, payload: bytes) -> None:
        op = payload[0]
        if op == nfclink.SM_OP_NFC_WRITE and self.has_op:
            at = payload[1] | payload[2] << 8
            data = payload[3:]
            assert at % 4 == 0 and len(data) % 4 == 0 and data, "unaligned write"
            assert nfclink.SM_NFC_LO <= at and at + len(data) <= nfclink.SM_NFC_HI, "out of range"
            self.writes.append(at)
            for i, value in enumerate(data):
                if self.cc_sticks and 0x00C <= at + i < 0x010:
                    continue
                self.ee[at + i] = value
        elif op == 9:                                      # SM_OP_FLASH_DUMP
            start = payload[1] | payload[2] << 8 | payload[3] << 16
            length = payload[4] | payload[5] << 8
            for off in range(0, length, 26):
                n = min(26, length - off)
                at = start + off
                if payload[3] & 0x80:
                    data = bytes(self.ee[(at & 0x3FF):(at & 0x3FF) + n])
                else:
                    data = b"\xff" * n                    # SPI flash at 0x80000C: nothing
                raw = bytes([at & 0xFF, at >> 8 & 0xFF, at >> 16 & 0xFF, n]) + data
                self.line(f"DATA src={self.addr:04x} seq=01 rssi=-40 flash={raw.hex()}")


def fake_app(tag: FakeTag, base: str = "https://shelf.example.org", local: bool = False):
    pane = types.SimpleNamespace(seq=0, log=tag.log, worker=types.SimpleNamespace(is_open=True),
                                 spec=types.SimpleNamespace(name="hub"))
    events = []
    app = types.SimpleNamespace(lock=threading.RLock(), status="", tag_meta={}, store=None,
                                panes={"hub": pane}, events=events)
    app.hub_key = lambda: "hub"
    app.tag_page_base = lambda: (base, local)
    app._ping_hub = lambda key, cancel: True
    app._event = lambda kind, who, text: events.append((kind, who, text))

    def send(key, addr, payload, cancel):
        pane.seq = tag.seq                                # what was logged before this frame
        tag.receive(payload)
        return True

    app._send_frame = send
    for name in ("nfc_link_for", "_read_nfc", "write_nfc_link"):
        setattr(app, name, types.MethodType(getattr(App, name), app))
    return app


def test_write() -> None:
    import shelfkit.app as app_mod
    app_mod.time.sleep = lambda s: None                   # no settling waits in a test
    tag = FakeTag(0xF466)
    app = fake_app(tag)
    result = app.write_nfc_link(0xF466)
    check("a fresh tag is written", result.get("ok") is True, result)
    check("the chip now opens the tag's page",
          nfclink.read_url(bytes(tag.ee[0x00C:0x060])) == "https://shelf.example.org/tag/F466")
    check("the message start went last", tag.writes and tag.writes[-1] == 0x00C, tag.writes)
    check("the link is remembered", app.tag_meta[0xF466]["nfc_url"].endswith("/tag/F466"))
    tag.writes.clear()
    again = app.write_nfc_link(0xF466)
    check("a second write sends nothing", again.get("ok") and again["written"] == 0 and not tag.writes,
          again)

    old = FakeTag(0x0102, firmware_has_op=False)
    result = fake_app(old).write_nfc_link(0x0102)
    check("old firmware is caught by the read-back",
          result.get("ok") is False and "firmware" in result["error"], result)

    stuck = FakeTag(0x0103, cc_sticks=True)
    result = fake_app(stuck).write_nfc_link(0x0103)
    check("a CC the chip refuses is reported",
          result.get("ok") is False and "capability container" in result["error"], result)

    local = fake_app(FakeTag(0x0104), base="http://127.0.0.1:8787", local=True)
    result = local.write_nfc_link(0x0104)
    check("a link only this computer can open is refused",
          result.get("ok") is False and "Address phones use" in result["error"], result)


def main() -> int:
    test_encoding()
    test_write()
    print("PASS" if not FAILED else f"FAILED: {len(FAILED)}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
