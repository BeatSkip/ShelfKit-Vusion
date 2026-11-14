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
import urllib.error
import urllib.request
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))

from shelfkit import firmware, hubhost, serial_link, store as store_mod, webapp  # noqa: E402
from shelfkit.app import App  # noqa: E402
from shelfkit.serial_link import PortSpec  # noqa: E402

FAILED: list[str] = []
RAW_IMAGE_FRAMES = 404      # two 5,624-byte planes at 28 bytes per frame, uncompressed


def planes_from(frames):
    """Rebuild (bw, red) from one transfer's DATA payloads, as the tag would."""
    from shelfkit import eco
    planes, zbuf = {}, {}
    for f in frames:
        if f[0] == hubhost.OP_CHUNK:
            planes.setdefault(f[1], bytearray()).extend(f[4:])
        elif f[0] == hubhost.OP_ZCHUNK:
            zbuf.setdefault(f[1], bytearray()).extend(f[4:])
        elif f[0] == hubhost.OP_ZEND:
            n = f[2] | (f[3] << 8)
            assert n == len(zbuf[f[1]]) <= hubhost.ECO_MAX
            planes[f[1]] = bytearray(eco.decode(bytes(zbuf[f[1]])))
    return bytes(planes.get(0, b"")), bytes(planes.get(1, b""))


def check(name: str, ok: bool, detail=None) -> None:
    if ok:
        print(f"  PASS {name}")
        return
    FAILED.append(name)
    print(f"  FAIL {name}" + (f"  <<< {detail}" if detail is not None else ""))


class FakePort:
    """A hub that answers like the firmware does."""

    def __init__(self) -> None:
        self.frames: list[bytes] = []   # DATA payloads, one entry per frame
        self._open = False
        self._dtr = False
        self._rts = False
        self.buf = bytearray()
        self.written: list[str] = []
        self.panel: list[bytes] = []    # IMG messages the hub's own panel received
        self.hex_lines: list[str] = []  # what a bootloader flash wrote
        self.booted = False             # ... and whether it then sent R

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
        elif line == "?":                       # the mask-ROM bootloader's banner
            self.feed("AX8052 Bootloader V1.1 Checksum 0xA7D2\r\n")
        elif line == "K":
            self.feed("OK\r\n")
        elif line == "R":
            self.booted = True
        elif line.startswith(":"):
            self.hex_lines.append(line)
        elif line.startswith("S"):
            frame = bytes.fromhex(line[1:])
            addr = frame[0] | (frame[1] << 8)
            self.feed(f"SENT {addr:04x} ok att=1\r\n")
            payload = frame[2:-1]
            self.frames.append(payload)
            if payload and payload[0] == 9:          # a flash read-back request
                start = payload[1] | (payload[2] << 8) | (payload[3] << 16)
                length = payload[4] | (payload[5] << 8)
                self.stream(addr, start, length)
        elif line.startswith("D"):
            # an image message for the hub's own panel: checksum must add up to 0
            raw = bytes.fromhex(line[1:])
            if sum(raw) & 0xFF:
                self.feed("ERR chk\r\n")
            else:
                self.panel.append(raw[:-1])
                self.feed("OK img\r\n")
        elif line.startswith("B"):
            # a batch: address, count, then (length, payload) per frame - the same
            # walk the hub does, so the test catches a format the hub would reject
            raw = bytes.fromhex(line[1:])
            addr = raw[0] | (raw[1] << 8)
            off, count = 3, raw[2]
            for _ in range(count):
                ln = raw[off]
                self.frames.append(raw[off + 1: off + 1 + ln])
                off += 1 + ln
            self.feed(f"SENT {addr:04x} ok att=1\r\n")
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

    def job_state(job_id):
        for job in get("/api/state")["queue"]:
            if job["id"] == job_id:
                return job["state"]
        return None

    def wait_job(job_id, target: str = "done", timeout: float = 60.0) -> bool:
        """A queued command runs when its tag polls, so the test polls for it."""
        end = time.time() + timeout
        while time.time() < end:
            if job_state(job_id) == target:
                return True
            PORTS["SMOKE1"].feed("POLL src=0100 seq=02 rssi=-30 up=13s att=1 hubrssi=-33 vdd=0300\r\n")
            time.sleep(0.2)
        return False

    def wait_idle(timeout: float = 40.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if not get("/api/state")["sending"]:
                return True
            time.sleep(0.05)
        return False

    try:
        # the hub's boot banner is what state() and the push read capabilities from
        PORTS["SMOKE1"].feed("*** ShelfKit hub, node 0001 net 5a dump=1 batch=1 show=1\r\n")
        PORTS["SMOKE1"].feed("POLL src=0100 seq=01 rssi=-30 up=12s att=1 hubrssi=-33 vdd=0300\r\n")
        time.sleep(0.2)
        check("a poll makes a tag appear", [a for a, _ in get("/api/state")["tags"]] == [0x100])
        check("the poll reports 3.00 V",
              get("/api/state")["tag_info"]["256"]["vdd"]["volts"] == 3.0,
              get("/api/state")["tag_info"]["256"].get("vdd"))

        # every poll's voltage is kept and can be read back for the chart
        PORTS["SMOKE1"].feed("POLL src=0100 seq=02 rssi=-30 up=72s att=1 hubrssi=-33 vdd=0300\r\n")
        time.sleep(0.2)
        history = get("/api/voltage?tag=0100&since=0")
        check("both readings are in the voltage history",
              history["count"] == 2 and [p[1] for p in history["points"]] == [3.0, 3.0], history)
        # the Diagnostics screen: one tag's own log, oldest first, and its script
        mine = get("/api/events?tag=0100&limit=50")
        check("a tag's own log holds only its events, oldest first",
              mine["hex_id"] == "0100" and len(mine["events"]) >= 2
              and all(row[2] == "0100" for row in mine["events"])
              and [row[0] for row in mine["events"]] == sorted(row[0] for row in mine["events"]),
              mine["events"][-3:])
        check("an unknown tag has an empty log", get("/api/events?tag=0FFF")["events"] == [])
        with urllib.request.urlopen(base + "/diag.js") as response:
            check("the Diagnostics script is served", b"renderDiag" in response.read())
        try:
            get("/api/voltage?tag=zz")
            refused = False
        except urllib.error.HTTPError as err:
            refused = err.code == 400
        check("a bad tag id is refused", refused)

        # archiving a power measurement keeps its readings and starts a new one
        runs = get("/api/power-runs?tag=0100")
        check("no archived measurement yet", runs["runs"] == [] and runs["current_since"] == 0, runs)
        archived = post("/api/power-runs", {"tag": "0100", "reason": "battery", "note": "CR2450 #2"})
        check("the measurement is archived", archived.get("ok") is True
              and len(archived["runs"]) == 1 and archived["current_since"] > 0, archived)
        run = get(f"/api/power-runs?id={archived['id']}")
        check("the archive holds its readings and stats",
              len(run["points"]) == 2 and run["stats"]["count"] == 2
              and run["reason"] == "battery" and run["note"] == "CR2450 #2", run)
        try:
            post("/api/power-runs", {"tag": "0100", "reason": "battery"})
            empty_refused = False
        except urllib.error.HTTPError as err:
            empty_refused = err.code == 400
        check("an empty measurement is not archived", empty_refused)
        PORTS["SMOKE1"].feed("POLL src=0100 seq=03 rssi=-30 up=90s att=1 hubrssi=-33 vdd=0300\r\n")
        time.sleep(0.2)
        since = get("/api/power-runs?tag=0100")["current_since"]
        check("the new measurement has only the new reading",
              get(f"/api/voltage?tag=0100&since={since}")["count"] == 1)
        deleted = post("/api/power-runs/delete", {"id": archived["id"]})
        check("an archive can be deleted", deleted.get("ok") is True
              and deleted["runs"] == [] and deleted["current_since"] == 0, deleted)

        # which firmware ran when: every report is kept, with the tag's uptime, and each
        # change of version is an install the readings after it are tagged with
        PORTS["SMOKE1"].feed("POLL src=0100 seq=04 rssi=-30 up=1s att=1 hubrssi=-33 vdd=0300"
                             " fw=1.1.0-46 avg=14000uA life=1d\r\n")
        time.sleep(0.2)
        PORTS["SMOKE1"].feed("POLL src=0100 seq=05 rssi=-30 up=3600s att=1 hubrssi=-33 vdd=0300"
                             " fw=1.1.0-46 avg=40uA life=645d\r\n")
        time.sleep(0.2)
        PORTS["SMOKE1"].feed("POLL src=0100 seq=06 rssi=-30 up=2s att=1 hubrssi=-33 vdd=0300"
                             " fw=1.1.0-49 avg=14000uA life=1d\r\n")
        PORTS["SMOKE1"].feed("POLL src=0100 seq=07 rssi=-30 up=130s att=1 hubrssi=-33 vdd=0300\r\n")
        time.sleep(0.3)
        fwh = get("/api/fw-history?tag=0100")
        check("every firmware report is kept with its uptime",
              [r[1:] for r in fwh["reports"]] == [["1.1.0-46", 14000, 1], ["1.1.0-46", 40, 3600],
                                                  ["1.1.0-49", 14000, 2]], fwh)
        check("a change of version is an install",
              [i[1:] for i in fwh["installs"]] == [["1.1.0-46", None], ["1.1.0-49", "1.1.0-46"]],
              fwh)
        check("the install is in the tag's log",
              any(row[3] == "installed" and row[4] == "1.1.0-46 -> 1.1.0-49"
                  for row in get("/api/events?tag=0100&limit=50")["events"]))
        spans = get("/api/voltage?tag=0100&since=0")["firmware"]
        check("readings carry the firmware they were taken under",
              [(s["version"], s["count"]) for s in spans] == [(None, 3), ("1.1.0-46", 2),
                                                              ("1.1.0-49", 2)], spans)
        check("the plot gets the installs with the measurements",
              len(get("/api/power-runs?tag=0100")["installs"]) == 2)

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
        check("service label queued", label.get("ok") is True and label.get("queued"), label)
        check("the queue delivered it on the poll", wait_job(label["queued"]), label)
        # The whole point of pre-rendering: the frames must exist against the job
        # before the tag ever polls, so nothing is rendered after the poll.
        job = next(j for j in app.queue if j["kind"] == "service")
        staged = job["params"].get("staged")
        check("the frames were pre-rendered at enqueue", staged is not None, job.get("state"))
        label_frames = list(staged[0])
        check("the label went out compressed",
              len(label_frames) < RAW_IMAGE_FRAMES / 5
              and any(f[0] == hubhost.OP_ZEND for f in label_frames), len(label_frames))
        check("every staged frame reached the hub",
              PORTS["SMOKE1"].frames[-len(label_frames):] == [bytes(f) for f in label_frames])
        from shelfkit import preview as _pv
        want = _pv.render(str(SERVER / "data" / "service" / "service-0100.png"), "stretch", "threshold")
        check("the compressed label decodes to the rendered planes",
              planes_from(label_frames) == (bytes(want.bw), bytes(want.red)))
        raw = list(hubhost.image_messages(want.bw, want.red, compress=False))
        check("uncompressed is still 404 frames", len(raw) == RAW_IMAGE_FRAMES, len(raw))

        # an ordinary image push
        before = len(PORTS["SMOKE1"].frames)
        check("the hub advertises batching", app.hub_capabilities().get("batch") is True,
              app.hub_capabilities())
        # ── batched DATA line (format only: the fake hub below does not advertise
        #    batch=1, so the push itself still goes out one frame at a time) ──
        line = hubhost.build_batch_line(0x1234, [b"\x01", b"\x02" + b"\x00" * 30])
        raw = bytes.fromhex(line[1:])
        check("batch line is a B line", line[0] == "B")
        check("batch line checksum", (sum(raw) & 0xFF) == 0)
        check("batch line carries addr and count",
              raw[0] == 0x34 and raw[1] == 0x12 and raw[2] == 2)
        check("batch line length byte", raw[3] == 1 and raw[4] == 1 and raw[5] == 31)

        check("send accepted", app.send(0x100) is True)
        check("the push finished", wait_idle())
        sent = PORTS["SMOKE1"].frames[before:]
        st = app.state()["editor"]
        img = _pv.render(str(app.image), st["fit"], st["dither"])
        check("the push decodes to the rendered image",
              planes_from(sent) == (bytes(img.bw), bytes(img.red)), len(sent))

        # two transfers queued at once: the second must alternate, not wait. Run with
        # raw planes (as a dithered photo goes out): a compressed push is ~30 frames
        # and over before the second tag has even polled.
        eco_max, hubhost.ECO_MAX = hubhost.ECO_MAX, 0
        first = app.enqueue("image", 0x0100, "alt-first", path=str(app.image),
                            fit="stretch", dither="threshold")
        second = app.enqueue("image", 0x0101, "alt-second", path=str(app.image),
                             fit="stretch", dither="threshold")
        check("both transfers queued", first.get("ok") is True and second.get("ok") is True,
              [first, second])
        for _ in range(600):
            PORTS["SMOKE1"].feed("POLL src=0100 seq=05 rssi=-30 up=13s att=1 hubrssi=-33 vdd=0300\r\n")
            PORTS["SMOKE1"].feed("POLL src=0101 seq=06 rssi=-30 up=13s att=1 hubrssi=-33 vdd=0300\r\n")
            if (job_state(first["queued"]) == "done"
                    and job_state(second["queued"]) == "done"):
                break
            time.sleep(0.1)
        check("the first transfer finished", job_state(first["queued"]) == "done",
              job_state(first["queued"]))
        check("the second finished too", job_state(second["queued"]) == "done",
              job_state(second["queued"]))
        flat = []
        for item in app.panes[app.hub_key()].since(0):
            flat.extend([item] if isinstance(item, str) else [str(x) for x in item])
        hub_log = "\n".join(flat)
        check("the second tag alternated instead of waiting", "alternating" in hub_log,
              hub_log[-300:])
        hubhost.ECO_MAX = eco_max

        # the flash read-back: request, collect from the pane log, save, serve
        result = post("/api/tags/0100/read", {})["result"]
        check("flash read queued", result.get("ok") is True and result.get("queued"), result)
        check("the queue delivered the read", wait_job(result["queued"]), result)
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

        # the check-in interval: queued like any command, one DATA frame, kept per tag
        bad = post("/api/tags/0100/interval", {"seconds": 45})["result"]
        check("an interval that is not offered is refused", bad.get("ok") is False, bad)
        result = post("/api/tags/0100/interval", {"seconds": 1800})["result"]
        check("interval change queued", result.get("ok") is True and result.get("queued"), result)
        info = get("/api/state")["tag_info"][str(0x100)]
        check("the queued interval shows as pending",
              info.get("poll_pending_s") == 1800 or info.get("poll_s") == 1800, info)
        check("the queue delivered the interval", wait_job(result["queued"]), result)
        check("it went out as SM_OP_SET_POLL, seconds little endian",
              bytes([13, 0x08, 0x07]) in PORTS["SMOKE1"].frames,
              [f.hex() for f in PORTS["SMOKE1"].frames[-3:]])
        info = get("/api/state")["tag_info"][str(0x100)]
        check("the acknowledged interval is kept for the tag",
              info.get("poll_s") == 1800 and info.get("poll_pending_s") is None, info)
        check("and it is in the database",
              next(r for r in app.store.tags() if r["hex_id"] == "0100").get("poll_s") == 1800)

        # ── pre-arms: the tag only stays awake after a poll when the hub was told ──
        hub = PORTS["SMOKE1"]

        def wait_for(pred, secs=3.0):
            end = time.time() + secs
            while time.time() < end:
                if pred():
                    return True
                time.sleep(0.02)
            return False

        hub.written.clear()
        pend = app.enqueue("image", 0x0200, "prearm", path=str(app.image),
                           fit="stretch", dither="threshold")
        check("queueing a command pre-arms its tag", "Q0200" in hub.written, hub.written)
        check("a pre-arm the hub never answers is sent again",
              wait_for(lambda: hub.written.count("Q0200") >= 2, 3.0), hub.written)
        hub.written.clear()
        hub.feed("*** ShelfKit hub, node 0001 net 5a dump=1 batch=1 show=1\r\n")
        check("a reset hub gets its pre-arms back",
              wait_for(lambda: "Q0200" in hub.written), hub.written)
        # one command can be cancelled on its own, by its id
        other = app.enqueue("interval", 0x0201, "one of two", seconds=60)
        one = post("/api/queue/cancel", {"id": pend["queued"]})["result"]
        states = {j["id"]: j["state"] for j in get("/api/state")["queue"]}
        check("cancelling one command leaves the other queued",
              one.get("ok") is True and states.get(pend["queued"]) == "cancelled"
              and states.get(other["queued"]) == "pending", (one, states))
        check("a finished command cannot be cancelled again",
              post("/api/queue/cancel", {"id": pend["queued"]})["result"].get("ok") is False)
        app.cancel_queue()
        hub.written.clear()
        hub.feed("*** ShelfKit hub, node 0001 net 5a dump=1 batch=1 show=1\r\n")
        time.sleep(0.3)
        check("nothing pending, nothing re-armed", not any(w.startswith("Q") for w in hub.written),
              hub.written)

        # ── the hub's own panel lists the connected tags ──
        disp = app.hubdisp
        check("the hub display is off by default", disp.tick() is False and not hub.panel)
        disp.configure(enabled=True, min_interval_s=1, timeout_s=300, title="Test hub")
        check("the config persists",
              store.settings()["hub_display"]["title"] == "Test hub", store.settings())
        check("a connected tag makes the panel draw", disp.tick() is True)
        msgs = hub.panel
        check("BEGIN, 88 chunks of 128 B or less, END", len(msgs) == 90 and msgs[0] == b"\x01"
              and msgs[-1] == b"\x03", len(msgs))
        check("the panel lists tag 0100", "0100" in disp.info()["shown"], disp.info())
        check("no change, no redraw", disp.tick() is False)
        check("the hub was released afterwards", app.display_busy is False)
        before = len(hub.panel)
        for addr in list(app.tag_seen):                  # every tag silent for > 5 minutes
            app.tag_seen[addr] = time.time() - 400
        time.sleep(1.1)
        # the display's own 2 s ticker may get to this redraw before the call below does
        disp.tick()
        check("a tag silent for 5 minutes leaves the panel",
              wait_for(lambda: disp.info()["shown"] == [] and not app.display_busy, 5.0)
              and len(hub.panel) == before + 90, disp.info())
        check("an empty, unchanged panel is left alone", disp.tick() is False)
        check("the display API answers", get("/api/hub-display")["timeout_s"] == 300)
        post("/api/hub-display", {"enabled": False})
        check("the display API configures", get("/api/hub-display")["enabled"] is False)
        app.tag_seen[0x100] = time.time()

        # page settings: validated, stored, and shared through /api/state
        check("prefs start at the defaults", get("/api/state")["prefs"]["late_after_s"] == 330)
        saved = post("/api/prefs", {"late_after_s": 400, "low_battery_v": 2.6, "fleet_view": "table"})
        check("prefs save", saved.get("ok") is True and saved["prefs"]["late_after_s"] == 400, saved)
        check("prefs reach the state", get("/api/state")["prefs"]["fleet_view"] == "table")
        try:
            post("/api/prefs", {"late_after_s": 9000, "silent_after_s": 700})
            refused = False
        except urllib.error.HTTPError as err:
            refused = err.code == 400 and not json.loads(err.read())["ok"]
        check("an impossible time is refused", refused)
        check("a refused change stores nothing", get("/api/state")["prefs"]["late_after_s"] == 400)
        try:
            post("/api/prefs", {"late_after_s": 700, "silent_after_s": 650})
            refused = False
        except urllib.error.HTTPError as err:
            refused = err.code == 400
        check("times out of order are refused", refused)

        # alias CSV: export, then import (including a tag that has not been heard)
        post("/api/tags/0100", {"alias": "A, \"quoted\"", "notes": "n1", "grid_row": 2, "grid_col": 5})
        exported = urllib.request.urlopen(base + "/api/aliases.csv", timeout=20).read().decode()
        check("the export has a header and the tag", exported.startswith("hex_id,alias,notes,shelf,slot")
              and "0100" in exported and '"A, ""quoted"""' in exported, exported)
        result = post("/api/aliases", {"csv": "hex_id,alias,notes,shelf,slot\n"
                                              "0100,Dairy,,1,2\n0abc,Bread,fresh,,\nzzzz,Bad,,,\n"})["result"]
        check("the import applies good rows and reports bad ones",
              result["imported"] == 2 and len(result["problems"]) == 1, result)
        meta = get("/api/state")["tag_info"]["256"]
        check("an import sets alias and clears blanks",
              meta["alias"] == "Dairy" and meta["notes"] is None and meta["row"] == 1, meta)
        check("an import keeps a tag that has not been heard", app.tag_meta[0x0ABC]["alias"] == "Bread")

        # the shelf wall's drag and drop, shelf names, sizes and the inspector's order
        moved = post("/api/tags/layout", {
            "tags": [{"hex": "0100", "grid_row": 3, "grid_col": 1},
                     {"hex": "0ABC", "grid_row": 3, "grid_col": 2}],
            "shelf_names": {"3": "Dairy aisle"}})
        meta = moved["state"]["tag_info"]["256"]
        check("a layout places several tags at once",
              moved.get("ok") is True and meta["row"] == 3 and meta["col"] == 1
              and app.tag_meta[0x0ABC]["row"] == 3, moved.get("error"))
        check("a layout names the shelf",
              moved["state"]["prefs"]["shelf_names"] == {"3": "Dairy aisle"})
        try:
            post("/api/tags/layout", {"tags": [{"hex": "0100", "grid_row": 4, "grid_col": 1},
                                               {"hex": "zz", "grid_row": 1, "grid_col": 1}]})
            refused = False
        except urllib.error.HTTPError as err:
            refused = err.code == 400
        check("a layout with a bad tag is refused", refused)
        check("a refused layout moves nothing", app.tag_meta[0x0100]["row"] == 3)
        post("/api/tags/layout", {"tags": [{"hex": "0ABC", "grid_row": None, "grid_col": None}]})
        check("a layout takes a tag off the shelves", app.tag_meta[0x0ABC]["row"] is None)
        saved = post("/api/prefs", {"wall_size": "small",
                                    "inspector_order": ["firmware", "battery", "nonsense"]})
        check("the new tag sizes and the section order save",
              saved["prefs"]["wall_size"] == "small"
              and saved["prefs"]["inspector_order"][:2] == ["firmware", "battery"], saved["prefs"])
        post("/api/prefs", {"wall_size": "full"})

        # ── flashing: the serial bootloader and the debugger ──
        flash0 = get("/api/state")["flash"]
        check("the flash starts idle with four steps",
              flash0["active"] is False and [x["key"] for x in flash0["steps"]]
              == ["connect", "erase", "program", "run"], flash0)

        def wait_flash(timeout: float = 30.0) -> dict:
            end = time.time() + timeout
            while time.time() < end:
                info = get("/api/state")["flash"]
                if not info["active"] and info["result"]:
                    return info
                time.sleep(0.1)
            return get("/api/state")["flash"]

        hex_lines = [":020000040000FA", ":10000000" + "00" * 16 + "F0", ":00000001FF"]
        app_hex = tmp / "tag-app.hex"
        app_hex.write_text("\n".join(hex_lines) + "\n")
        full_hex = tmp / "tag-full-test.hex"
        full_hex.write_text("\n".join(hex_lines) + "\n")
        tag_pane = app.keys[1]

        started = post("/api/flash", {"method": "serial", "path": str(app_hex), "pane": tag_pane})
        check("a serial flash starts", started.get("ok") is True, started)
        done = wait_flash()
        check("the serial flash finishes", done["result"] == "ok", done)
        check("every serial step is done", all(x["state"] == "done" for x in done["steps"]),
              done["steps"])
        check("the hex lines reached the bootloader", PORTS["SMOKE2"].hex_lines == hex_lines,
              PORTS["SMOKE2"].hex_lines)
        check("the bootloader was told to run", PORTS["SMOKE2"].booted)
        check("the pane is open again afterwards", app.panes[tag_pane].worker.is_open)
        check("the flash is in the event log",
              any(e[3] == "flash" for e in get("/api/poll?c=&e=0")["events"]))
        check("the flash output is served",
              any("Banner" in line for line in get("/api/flash")["flash"]["log"]))

        # the debugger: a fake axsdb prints the real tool's lines
        from shelfkit import flasher as flasher_mod
        windows = sys.platform.startswith("win")
        ext = ".bat" if windows else ".sh"
        ok_tool, bad_tool = tmp / f"fake-axsdb{ext}", tmp / f"fail-axsdb{ext}"
        argv_file = tmp / "argv.txt"
        flasher_mod.AXSDB_NAMES = (*flasher_mod.AXSDB_NAMES, ok_tool.name, bad_tool.name)
        if windows:
            ok_tool.write_text("@echo off\r\necho %*>\"" + str(argv_file) + "\"\r\n"
                               "echo Programming Serial 39DC0854\r\necho Bulk erase...\r\n"
                               "echo Flash program...\r\necho Run program...\r\n")
            bad_tool.write_text("@echo off\r\necho Programming Serial 39DC0854\r\n"
                                "echo Bulk erase...\r\necho ERROR: debugger lost\r\nexit /b 3\r\n")
        else:
            ok_tool.write_text("#!/bin/sh\necho \"$@\" > '" + str(argv_file) + "'\n"
                               "echo Programming Serial 39DC0854\necho Bulk erase...\n"
                               "echo Flash program...\necho Run program...\n")
            bad_tool.write_text("#!/bin/sh\necho Programming Serial 39DC0854\necho Bulk erase...\n"
                                "echo ERROR: debugger lost\nexit 3\n")
            ok_tool.chmod(0o755)
            bad_tool.chmod(0o755)

        try:
            post("/api/prefs", {"axsdb_path": str(tmp / "nowhere" / "axsdb.exe")})
            refused = False
        except urllib.error.HTTPError as err:
            refused = err.code == 400
        check("a missing axsdb path is refused", refused)
        saved = post("/api/prefs", {"axsdb_path": str(ok_tool)})
        check("an axsdb path is stored", saved.get("ok") is True
              and saved["prefs"]["axsdb_path"] == str(ok_tool), saved)
        check("the page can see axsdb was found", get("/api/state")["flash"]["axsdb"]["found"])

        try:
            post("/api/flash", {"method": "debugger", "path": str(app_hex)})
            guarded = None
        except urllib.error.HTTPError as err:
            guarded = json.loads(err.read())
        check("an image without a bootloader needs confirming before --eraseall",
              guarded is not None and guarded.get("needs_confirm") is True, guarded)

        post("/api/flash", {"method": "debugger", "path": str(full_hex)})
        done = wait_flash()
        check("the debugger flash finishes", done["result"] == "ok", done)
        check("every debugger step is done", all(x["state"] == "done" for x in done["steps"]),
              done["steps"])
        check("the chip's serial number is read from the output", done["serial"] == "39DC0854", done)
        argv = argv_file.read_text() if argv_file.exists() else ""
        check("axsdb got the erase and program flags",
              "--eraseall" in argv and "--flashprog" in argv and full_hex.name in argv, argv)

        post("/api/prefs", {"axsdb_path": str(bad_tool)})
        post("/api/flash", {"method": "debugger", "path": str(full_hex)})
        done = wait_flash()
        steps = {x["key"]: x["state"] for x in done["steps"]}
        check("a failing debugger reports the step it failed on",
              done["result"] == "failed" and steps["erase"] == "failed"
              and steps["connect"] == "done" and steps["program"] == "waiting", done)
        check("the failure carries the tool's own words",
              "code 3" in (done["error"] or "") and "debugger lost" in (done["error"] or ""), done)

        # a page on another site must not be able to start any of this
        request = urllib.request.Request(
            base + "/api/prefs", data=b"{}", method="POST",
            headers={"Content-Type": "application/json", "Origin": "http://evil.example"})
        try:
            urllib.request.urlopen(request, timeout=20)
            blocked = False
        except urllib.error.HTTPError as err:
            blocked = err.code == 403
        check("a cross-site POST is refused", blocked)
        request = urllib.request.Request(
            base + "/api/prefs", data=b"{}", method="POST",
            headers={"Content-Type": "application/json", "Origin": base})
        check("a same-site POST is accepted", json.loads(urllib.request.urlopen(request, timeout=20).read())["ok"])
        post("/api/prefs", {"axsdb_path": ""})

        # the debugger runs beside a busy hub; a serial flash only waits on the hub's own port
        post("/api/prefs", {"axsdb_path": str(ok_tool)})
        hub_pane = get("/api/state")["hub"]
        app.sending = True                       # the hub is mid-transfer
        try:
            post("/api/flash", {"method": "debugger", "path": str(full_hex)})
            started = True
        except urllib.error.HTTPError as err:
            started = False
        check("the debugger flashes while the hub is busy", started)
        check("a debugger flash leaves the hub's queue running", not app.flash.blocks_hub)
        wait_flash()
        try:
            post("/api/flash", {"method": "serial", "path": str(app_hex), "pane": hub_pane})
            refused = False
        except urllib.error.HTTPError as err:
            refused = err.code == 409
        check("a serial flash on the busy hub's own port is refused", refused)
        post("/api/flash", {"method": "serial", "path": str(app_hex), "pane": tag_pane})
        check("a serial flash on the other port runs beside a busy hub",
              wait_flash()["result"] == "ok")
        app.sending = False

        # serial ports are settings too
        shown = get("/api/state")["prefs"]
        check("the ports are in the settings", shown["hub_port"] == "SMOKE1"
              and shown["tag_port"] == "SMOKE2", shown)
        try:
            post("/api/prefs", {"tag_port": "smoke1"})
            refused = False
        except urllib.error.HTTPError as err:
            refused = err.code == 400
        check("the tag can't take the hub's port", refused)
        check("a refused port changes nothing", get("/api/state")["prefs"]["tag_port"] == "SMOKE2")
        saved = post("/api/prefs", {"tag_port": "SMOKE3"})
        check("a new tag port is stored", saved["prefs"]["tag_port"] == "SMOKE3", saved)
        check("the pane follows the setting",
              [x["port"] for x in get("/api/state")["panes"] if x["key"] == tag_pane] == ["SMOKE3"])
        post("/api/prefs", {"tag_port": "SMOKE2"})
        hidden = post("/api/prefs", {"show_tag_port": False})
        check("the tag port can be hidden", hidden["prefs"]["show_tag_port"] is False)
        check("hiding it closes it", not [x for x in get("/api/state")["panes"]
                                          if x["key"] == tag_pane][0]["open"])
        post("/api/prefs", {"show_tag_port": True})

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
        check("prefs come back after a restart",
              state["prefs"]["late_after_s"] == 400 and state["prefs"]["fleet_view"] == "table",
              state["prefs"])
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
