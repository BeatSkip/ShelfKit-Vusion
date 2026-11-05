#!/usr/bin/env python3
"""hubhost.py - push images to tags through the hub's serial port.

This is a supporting module of shelfkit-server.py, and also a CLI on its own:

    python ShelfKit-Server/shelfkit/hubhost.py COM4 serve images/   # watch announcements, push new images
    python ShelfKit-Server/shelfkit/hubhost.py COM4 send 0100 pic.png  # push one image to tag 0100 now
    python ShelfKit-Server/shelfkit/hubhost.py COM4 ping               # check the hub's command channel
    python ShelfKit-Server/shelfkit/hubhost.py --list

(from the repo root; `python -m shelfkit.hubhost ...` works too if you are inside
ShelfKit-Server/)

serve: the folder holds one PNG per tag named after its node id in hex (0100.png). When a
tag announces itself and its file is new or changed since the last successful push
(remembered in <folder>/.sent.json), the image is converted (png2epd.py rules: 152x296 after
--rotate, default 90 = a 296x152 landscape source) and sent. The tag refreshes its panel
(~15 s) at the end of the transfer.

show: draw an image on the HUB's own panel (needs a hub built with img_rx, banner "show=1").
stats: render this machine's CPU/RAM/disk as a frame and show it on the hub.
    python ShelfKit-Server/shelfkit/hubhost.py COM4 show pic.png
    python ShelfKit-Server/shelfkit/hubhost.py COM4 stats
The server holds the serial port while it runs: stop it first, or use another port.
The host must stay silent while the hub refreshes (~15 s) - on this board a serial byte
is a reset pulse on the panel (PB5 is both), see HUB_EPD_RST_PULSE in the hub's shelf_config.h.

Hub command channel (115200 8N1, one line per command, hex only):
    D<img msg><chk:2>                 -> OK img   (SM_OP_IMG_* for the hub's own panel)
    P                                 -> PONG
    S<addr:4><payload><chk:2>         -> SENT <addr> ok|fail att=N     (reliable DATA frame)
chk = two's complement of the byte sum, so addr+payload+chk adds up to 0 mod 256.
Image payloads are defined in ShelfKit-Firmware/Shared/firmware/shelflink/inc/shelfmsg.h.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial is required:  pip install pyserial")

BAUD = 115200
OP_BEGIN, OP_CHUNK, OP_END = 1, 2, 3
OP_ZCHUNK, OP_ZEND = 11, 12  # an ECO-compressed plane (shelfmsg.h, shelfkit/eco.py)
ECO_MAX = 2560              # SM_ECO_MAX: the tag's buffer for one compressed plane
# After ZEND the tag decodes the plane into the panel (8 passes over the file) and
# answers nothing meanwhile. The time grows with the file: estimated ~0.3 s for a
# 0.5 KB label, over a second for a full 2.5 KB buffer - the tag logs the real figure
# ("img zplane <n>B <s>s"), tune these from it. The batch retry covers a miss.
DECODE_SETTLE_S = 0.5
DECODE_S_PER_BYTE = 0.0008


def decode_settle(zend):
    """Seconds to wait after a ZEND frame before the next frame."""
    return DECODE_SETTLE_S + DECODE_S_PER_BYTE * (zend[2] | (zend[3] << 8))
PLANE_BW, PLANE_RED = 0, 1
CHUNK = 28                  # SM_IMG_CHUNK
BEGIN_SETTLE_S = 2.0        # the tag resets the panel after acknowledging BEGIN and answers nothing meanwhile.
                            # Measured ~0.9 s (power rail, reset, booster); the tag's receiver is on for
                            # all of this wait, so 5 s cost ~0.01 mAh per image. A slower (cold) panel is
                            # covered by the batch retry.
END_SETTLE_S = 20.0         # ... and refreshes it after acknowledging END
# The hub answers SENT only after all SL_MAX_ATTEMPTS (4) have run out, which
# takes ~4.5 s when the tag is asleep. Waiting 3 s meant the server gave up in the
# middle of the hub's attempts and started a new cycle, so one miss turned into a
# 90 s burst of "SENT ... fail".
CMD_TIMEOUT_S = 6.0
# A tag sleeps between polls (120 s + its window), so a frame may wait a whole
# cycle; below that, a missed push is abandoned before the tag ever polls again.
CMD_RETRY_WINDOW_S = 180.0
CMD_RETRY_PAUSE_S = 0.3
RETRY_COOLDOWN_S = 30.0

RE_POLL = re.compile(r"^POLL src=([0-9a-fA-F]{4})\b")
RE_SENT = re.compile(r"^SENT ([0-9a-fA-F]{4}) (ok|fail) att=(\d+)")


# Frames per 'B' line. One serial round-trip per batch instead of per frame; the
# hub still sends them one at a time and waits for each acknowledgement, so the
# air protocol is unchanged.
BATCH_FRAMES = 16

# Pre-rendering made the first frame leave within ~6 ms of the poll, and hardware
# answered `fail att=4` every time: the tag has just finished sending its poll and is
# only then settling into receive. Rendering used to provide ~80 ms of slack by
# accident. This is that slack, on purpose - far inside the tag's listening window.
PUSH_SETTLE_S = 0.08
BATCH_RETRY_S = 0.3     # pause between batch retries: the tag's window is short


def build_batch_line(addr, frames):
    """The 'B' line for several DATA frames: addr, count, then (len, payload) each."""
    body = bytes([addr & 0xFF, addr >> 8, len(frames)])
    for frame in frames:
        body += bytes([len(frame)]) + bytes(frame)
    chk = (-sum(body)) & 0xFF
    return "B" + (body + bytes([chk])).hex()


def build_line(cmd, addr, payload=b""):
    """The 'S' line for a DATA frame to node addr (int), without the newline."""
    body = bytes([addr & 0xFF, addr >> 8]) + bytes(payload)
    chk = (-sum(body)) & 0xFF
    return f"{cmd}{(body + bytes([chk])).hex()}"


def image_messages(bw, red, chunk=CHUNK, compress=True):
    """Yield the DATA payloads of one image transfer, BEGIN first, END last.

    With compress, each plane goes as ECO chain code (ZCHUNKs + ZEND) when that is
    smaller and fits the tag's buffer - a label is ~0.5-0.8 KB instead of 5.6 KB -
    and as plain CHUNKs otherwise (dithered photos). The hub's own panel (`D` lines)
    does not decode ECO: it is fed with compress=False."""
    yield bytes([OP_BEGIN])
    for plane, data in ((PLANE_BW, bw), (PLANE_RED, red)):
        data = bytes(data)
        packed = None
        if compress:
            try:
                from . import eco
            except ImportError:         # run as a script: shelfkit/ is on sys.path
                import eco
            packed = eco.compress(data)
            if len(packed) > ECO_MAX or len(packed) >= len(data):
                packed = None
        if packed is not None:
            for off in range(0, len(packed), chunk):
                yield bytes([OP_ZCHUNK, plane, off & 0xFF, off >> 8]) + packed[off:off + chunk]
            yield bytes([OP_ZEND, plane, len(packed) & 0xFF, len(packed) >> 8])
        else:
            for off in range(0, len(data), chunk):
                yield bytes([OP_CHUNK, plane, off & 0xFF, off >> 8]) + data[off:off + chunk]
    yield bytes([OP_END])


# Serial chunks for the hub's own panel are not limited by the radio frame.
SER_CHUNK = 128
SHOW_BEGIN_TIMEOUT_S = 15.0     # panel rail cycle + init
SHOW_END_TIMEOUT_S = 120.0      # the refresh blocks the hub (~15 s, up to a minute cold)


def build_img_line(payload):
    """The 'D' line carrying one SM_OP_IMG_* message for the hub's own panel."""
    body = bytes(payload)
    return "D" + (body + bytes([(-sum(body)) & 0xFF])).hex()


class Hub:
    def __init__(self, port):
        # DTR (boot pin) and RTS (reset) low, so opening the port does not reset the hub
        self.ser = serial.Serial()
        self.ser.port, self.ser.baudrate, self.ser.timeout = port, BAUD, 0.2
        self.ser.dtr = False
        self.ser.rts = False
        self.ser.open()
        self.last_result = None  # outcome of the last send_data() attempt, for diagnostics
        self.polls = []         # announcements seen while busy with something else
        self.buf = b""

    def read_line(self, timeout=None):
        """One decoded line, '' if none is complete yet. Announcements are queued on the way."""
        chunk = self.ser.read(max(1, self.ser.in_waiting))
        self.buf += chunk
        if b"\n" not in self.buf:
            return ""
        raw, self.buf = self.buf.split(b"\n", 1)
        line = raw.decode("ascii", "replace").strip()
        m = RE_POLL.match(line)
        if m:
            self.polls.append(int(m.group(1), 16))
        return line

    def wait_for(self, pattern, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            line = self.read_line(timeout)
            if line:
                m = pattern(line)
                if m:
                    return m
        return None

    def ping(self):
        self.ser.reset_input_buffer()
        self.buf = b""
        for _ in range(3):
            self.ser.write(b"P\n")
            if self.wait_for(lambda l: l == "PONG", 1.0):
                return True
        return False

    def send_data(self, addr, payload):
        """Reliable DATA frame to addr. True once the tag acknowledged it."""
        line = (build_line("S", addr, payload) + "\n").encode("ascii")
        end = time.monotonic() + CMD_RETRY_WINDOW_S
        self.last_result = None
        while time.monotonic() < end:
            self.ser.write(line)

            def result(l):
                m = RE_SENT.match(l)
                if m and int(m.group(1), 16) == addr:
                    return m.group(2)
                return l if l.startswith("ERR") else None

            res = self.wait_for(result, CMD_TIMEOUT_S)
            self.last_result = res or "no answer"
            if res == "ok":
                return True
            # no answer / hub-side ERR (line damaged, busy) / radio gave up: try again.
            # A chunk the tag already has is acknowledged and ignored, so repeats are safe.
            time.sleep(CMD_RETRY_PAUSE_S)
        return False

    def show_image(self, bw, red, progress=None):
        """Draw an image on the hub's own panel. True once the refresh finished."""
        msgs = list(image_messages(bw, red, SER_CHUNK, compress=False))
        self.ser.reset_input_buffer()
        self.buf = b""
        for i, msg in enumerate(msgs):
            last = i == len(msgs) - 1
            timeout = SHOW_BEGIN_TIMEOUT_S if i == 0 else SHOW_END_TIMEOUT_S if last else 2.0
            tries = 1 if i == 0 or last else 5      # a repeated chunk is ignored by the hub
            line = (build_img_line(msg) + "\n").encode("ascii")
            res = None
            for _ in range(tries):
                self.ser.write(line)
                res = self.wait_for(lambda l: l if l == "OK img" or l.startswith("ERR") else None,
                                    timeout)
                if res == "OK img":
                    break
                time.sleep(0.2)
            if res != "OK img":
                print(f"  hub: gave up at message {i + 1}/{len(msgs)} (answer: {res or 'none'})")
                return False
            if progress and i % 10 == 0:
                progress(i, len(msgs))
        return True

    def send_image(self, addr, bw, red, progress=None):
        msgs = list(image_messages(bw, red))
        for i, msg in enumerate(msgs):
            if not self.send_data(addr, msg):
                print(f"  {addr:04x}: gave up at message {i + 1}/{len(msgs)}")
                return False
            if i == 0:
                time.sleep(BEGIN_SETTLE_S)
            elif msg[0] == OP_ZEND:
                time.sleep(decode_settle(msg))
            if progress and i % 50 == 0:
                progress(i, len(msgs))
        time.sleep(END_SETTLE_S)
        return True


def planes_for(path, rotate, dither):
    # png2epd is imported here, not at module load, so that `ping` and the hub
    # command channel still work when Pillow is not installed.
    try:
        from . import png2epd          # imported as shelfkit.hubhost
    except ImportError:                # run directly: python shelfkit/hubhost.py
        import png2epd
    return png2epd.load_planes(path, rotate, dither)


def cmd_show(hub, args):
    bw, red = planes_for(args.png, args.rotate, args.dither)
    return show_planes(hub, bw, red)


def show_planes(hub, bw, red):
    start = time.monotonic()
    ok = hub.show_image(bw, red, lambda i, n: print(f"  {i}/{n}", flush=True))
    print(("shown" if ok else "FAILED") + f" in {time.monotonic() - start:.1f} s")
    return 0 if ok else 1


def cmd_stats(hub, args):
    try:
        from . import stats_image, png2epd
    except ImportError:
        import stats_image, png2epd
    img = stats_image.render().convert("RGBA")
    if args.save:
        img.convert("RGB").save(args.save)
        print(f"saved {args.save}")
    bw, red = png2epd.to_planes(img, False)
    return show_planes(hub, bw, red)


def cmd_send(hub, args):
    addr = int(args.addr, 16)
    bw, red = planes_for(args.png, args.rotate, args.dither)
    start = time.monotonic()
    ok = hub.send_image(addr, bw, red, lambda i, n: print(f"  {i}/{n}", flush=True))
    print(("sent" if ok else "FAILED") + f" in {time.monotonic() - start:.1f} s")
    return 0 if ok else 1


def file_key(path, args):
    h = hashlib.sha256(Path(path).read_bytes())
    h.update(f"{args.rotate}{args.dither}".encode())
    return h.hexdigest()


def cmd_serve(hub, args):
    folder = Path(args.folder)
    state_path = folder / ".sent.json"
    sent = json.loads(state_path.read_text()) if state_path.exists() else {}
    cooldown = {}
    print(f"watching announcements, images in {folder}/<addr>.png (Ctrl+C to stop)")
    while True:
        hub.read_line(1.0)
        while hub.polls:
            addr = hub.polls.pop(0)
            name = f"{addr:04x}"
            png = folder / f"{name}.png"
            if not png.exists():
                continue
            key = file_key(png, args)
            if sent.get(name) == key or cooldown.get(name, 0) > time.monotonic():
                continue
            print(f"tag {name} announced, new image {png.name}")
            bw, red = planes_for(png, args.rotate, args.dither)
            if hub.send_image(addr, bw, red):
                sent[name] = key
                state_path.write_text(json.dumps(sent, indent=2))
                print(f"tag {name} updated")
            else:
                cooldown[name] = time.monotonic() + RETRY_COOLDOWN_S
            hub.polls.clear()   # announcements that piled up during the transfer are stale


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port", nargs="?")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("send", "serve"):
        p = sub.add_parser(name)
        if name == "send":
            p.add_argument("addr", help="tag node id in hex, e.g. 0100")
            p.add_argument("png")
        else:
            p.add_argument("folder")
        p.add_argument("--rotate", type=int, default=90, choices=[0, 90, 180, 270])
        p.add_argument("--dither", action="store_true")
    p = sub.add_parser("show", help="draw an image on the hub's own panel")
    p.add_argument("png")
    p.add_argument("--rotate", type=int, default=90, choices=[0, 90, 180, 270])
    p.add_argument("--dither", action="store_true")
    p = sub.add_parser("stats", help="show this machine's CPU/RAM/disk on the hub's panel")
    p.add_argument("--save", help="also save the rendered frame as a PNG")
    sub.add_parser("ping")
    ap.add_argument("--list", action="store_true", help="list serial ports and exit")
    args = ap.parse_args()

    if args.list:
        for p in list_ports.comports():
            print(f"{p.device}  {p.description}")
        return 0
    if not args.port or not args.cmd:
        ap.error("port and a command (send, serve, show, stats, ping) are required")

    hub = Hub(args.port)
    if not hub.ping():
        print("hub does not answer P - check the port and that the hub firmware is flashed")
        return 1
    if args.cmd == "ping":
        print("PONG")
        return 0
    try:
        return {"send": cmd_send, "serve": cmd_serve, "show": cmd_show,
                "stats": cmd_stats}[args.cmd](hub, args)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
