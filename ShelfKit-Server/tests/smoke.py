#!/usr/bin/env python3
"""Smoke test for the server: the paths a page actually uses.

    python ShelfKit-Server/tests/smoke.py

No pytest, no hardware: the two serial ports are fakes that answer the hub's `P`
with `PONG` and every `S` frame with `SENT … ok`, so an image push, a service
label and a firmware transfer all run their real code. It covers what broke
before and would break silently otherwise:

* the Editor's render path (`POST /api/preview`, and the restore-on-start thread
  that calls the same function),
* a service label being drawn, rendered and pushed as an image,
* an ordinary image push,
* the stored preview coming back after a restart.

Exit code 0 = everything passed.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))

from shelfkit import firmware, serial_link, store as store_mod, webapp  # noqa: E402
from shelfkit.app import App  # noqa: E402
from shelfkit.serial_link import PortSpec  # noqa: E402

FAILED: list[str] = []
IMAGE_FRAMES = 404          # two 5,624-byte planes at 28 bytes per frame


def check(name: str, ok: bool, detail=None) -> None:
    if ok:
        print(f"  PASS {name}")
        return
    FAILED.append(name)
    print(f"  FAIL {name}" + (f"  <<< {detail}" if detail is not None else ""))


class FakePort:
    """A hub that answers like the firmware does."""

    def __init__(self) -> None:
        self._open = False
        self._dtr = False
        self._rts = False
        self.buf = bytearray()
        self.written: list[str] = []

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    @property
    def dtr(self) -> bool:
        return self._dtr

    @dtr.setter
    def dtr(self, value) -> None:
        self._dtr = bool(value)

    @property
    def rts(self) -> bool:
        return self._rts

    @rts.setter
    def rts(self, value) -> None:
        self._rts = bool(value)

    @property
    def in_waiting(self) -> int:
        return len(self.buf)

    def read(self, n: int = 1) -> bytes:
        if not self.buf:
            time.sleep(0.002)
            return b""
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def feed(self, text: str) -> None:
        self.buf += text.encode("latin-1")

    def write(self, data) -> int:
        line = bytes(data).decode("latin-1").strip()
        self.written.append(line)
        if line == "P":
            self.feed("PONG\r\n")
        elif line.startswith("S"):
            frame = bytes.fromhex(line[1:])
            addr = frame[0] | (frame[1] << 8)
            self.feed(f"SENT {addr:04x} ok att=1\r\n")
            payload = frame[2:-1]
            if payload and payload[0] == 9:          # a flash read-back request
                start = payload[1] | (payload[2] << 8) | (payload[3] << 16)
                length = payload[4] | (payload[5] << 8)
                self.stream(addr, start, length)
        return len(data)

    def stream(self, addr: int, start: int, length: int) -> None:
        """What the tag would send back: 26 bytes per DATA frame."""
        for offset in range(0, length, 26):
            chunk = bytes(FLASH[start + offset:start + offset + min(26, length - offset)])
            header = bytes([(start + offset) & 0xFF, ((start + offset) >> 8) & 0xFF,
                            ((start + offset) >> 16) & 0xFF, len(chunk)])
            self.feed(f"DATA src={addr:04x} seq=1a rssi=-30 flash={(header + chunk).hex()}\r\n")

    def flush(self) -> None:
        pass


FLASH = bytearray(b"\xff" * 0x3000)          # what the "tag" will read back
IDENTITY = bytearray(b"\xff" * 10)
IDENTITY[0:4] = b"SKID"
IDENTITY[4] = 1
IDENTITY[5] = 1
IDENTITY[6] = 0x2A
IDENTITY[7] = 0x01
_crc = firmware.crc16(IDENTITY[:8])
IDENTITY[8] = _crc & 0xFF
IDENTITY[9] = _crc >> 8
FLASH[0x1000:0x100A] = IDENTITY

PORTS: dict[str, FakePort] = {}
serial_link._make_serial = lambda spec: PORTS.setdefault(spec.port, FakePort())


def boot(db: Path, auto_open: bool = True):
    store = store_mod.Store(db)
    app = App([PortSpec("hub", "SMOKE1"), PortSpec("tag", "SMOKE2")], auto_open, store=store)
    server = webapp.make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    return app, store, server, f"http://127.0.0.1:{server.server_address[1]}"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="shelfkit-smoke-"))
    db = tmp / "state.db"
    app, store, server, base = boot(db)

    def get(path: str) -> dict:
        return json.loads(urllib.request.urlopen(base + path, timeout=20).read())

    def post(path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(
            base + path, data=json.dumps(body or {}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        return json.loads(urllib.request.urlopen(request, timeout=60).read())

    def wait_idle(timeout: float = 40.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if not get("/api/state")["sending"]:
                return True
            time.sleep(0.05)
        return False

    try:
        PORTS["SMOKE1"].feed("POLL src=0100 seq=01 rssi=-30\r\n")
        time.sleep(0.2)
        check("a poll makes a tag appear", [a for a, _ in get("/api/state")["tags"]] == [0x100])

        # the Editor's render path - the one that used to raise
        image = str((REPO / "Resources" / "polyform-eink.png").resolve())
        post("/api/image", {"path": image})
        preview = post("/api/preview")
        check("render_preview works", preview.get("ok") is True, preview)
        check("preview publishes both PNGs",
              str(preview.get("device", "")).startswith("/api/preview.png?t="), preview)
        post("/api/editor", {"fit": "contain", "dither": "bayer4"})
        check("render options apply", get("/api/state")["editor"]["fit"] == "contain")
        check("re-render after the options", post("/api/preview").get("ok") is True)

        # a service label: drawn, rendered, pushed wirelessly
        post("/api/tags/0100", {"alias": "S03-P4", "notes": "dev note"})
        label = post("/api/tags/0100/service", {})["result"]
        check("service label accepted", label.get("ok") is True, label)
        check("the label uses the alias", label.get("alias") == "S03-P4", label)
        check("the label file exists", Path(label.get("image", "")).is_file(), label.get("image"))
        check("the push finished", wait_idle())
        frames = [w for w in PORTS["SMOKE1"].written if w.startswith("S")]
        check(f"the label went out as {IMAGE_FRAMES} image frames", len(frames) == IMAGE_FRAMES,
              len(frames))

        # an ordinary image push
        before = len(PORTS["SMOKE1"].written)
        check("send accepted", app.send(0x100) is True)
        check("the push finished", wait_idle())
        sent = [w for w in PORTS["SMOKE1"].written[before:] if w.startswith("S")]
        check("an image is still 404 frames", len(sent) == IMAGE_FRAMES, len(sent))

        # the flash read-back: request, collect from the pane log, save, serve
        result = post("/api/tags/0100/read", {})["result"]
        check("flash read accepted", result.get("ok") is True, result)
        end = time.time() + 60
        while time.time() < end and get("/api/state")["dump"].get("active"):
            time.sleep(0.05)
        dump = get("/api/state")["dump"]
        check("flash read finished", dump.get("ok") is True, dump)
        notes = "\n".join(dump.get("summary") or [])
        check("the identity came back over the air", "id 0x012A (assigned)" in notes, notes)
        check("the reserved sector is reported", "reserved sector: blank" in notes, notes)
        body = urllib.request.urlopen(base + "/api/dump.bin", timeout=30).read()
        check("the dump downloads and holds the record",
              len(body) == 0x3000 and body[0x1000:0x100A] == IDENTITY,
              [len(body), body[0x1000:0x100A].hex()])

        # a restart restores the editor and re-renders its preview
        for pane in app.panes.values():
            pane.worker.close()
        server.shutdown()
        store.close()

        app2, store2, server2, base2 = boot(db, auto_open=False)
        time.sleep(0.8)
        state = json.loads(urllib.request.urlopen(base2 + "/api/state", timeout=20).read())
        check("the preview comes back after a restart", bool(state["editor"]["preview"]),
              state["editor"]["preview"])
        check("the image comes back too",
              bool(state["image"]) and state["image"]["name"] == "polyform-eink.png",
              state["image"])
        for pane in app2.panes.values():
            pane.worker.close()
        server2.shutdown()
        store2.close()
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nRESULT:", "PASS" if not FAILED else f"FAIL {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
