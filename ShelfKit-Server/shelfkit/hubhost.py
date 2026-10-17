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

Hub command channel (38400 8N1, one line per command, hex only):
    P                                 -> PONG
    S<addr:4><payload><chk:2>         -> SENT <addr> ok|fail att=N     (reliable DATA frame)
chk = two's complement of the byte sum, so addr+payload+chk adds up to 0 mod 256.
Image payloads are defined in shared/firmware/shelflink/inc/shelfmsg.h.
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

BAUD = 38400
OP_BEGIN, OP_CHUNK, OP_END = 1, 2, 3
PLANE_BW, PLANE_RED = 0, 1
CHUNK = 28                  # SM_IMG_CHUNK
BEGIN_SETTLE_S = 5.0        # the tag resets the panel after acknowledging BEGIN and answers nothing meanwhile
END_SETTLE_S = 20.0         # ... and refreshes it after acknowledging END
CMD_TIMEOUT_S = 3.0
CMD_RETRY_WINDOW_S = 20.0   # keep repeating a frame this long: a busy tag fails fast, so count time, not tries
CMD_RETRY_PAUSE_S = 0.3
RETRY_COOLDOWN_S = 30.0

RE_POLL = re.compile(r"^POLL src=([0-9a-fA-F]{4})\b")
RE_SENT = re.compile(r"^SENT ([0-9a-fA-F]{4}) (ok|fail) att=(\d+)")


def build_line(cmd, addr, payload=b""):
    """The 'S' line for a DATA frame to node addr (int), without the newline."""
    body = bytes([addr & 0xFF, addr >> 8]) + bytes(payload)
    chk = (-sum(body)) & 0xFF
    return f"{cmd}{(body + bytes([chk])).hex()}"


def image_messages(bw, red):
    """Yield the DATA payloads of one image transfer, BEGIN first, END last."""
    yield bytes([OP_BEGIN])
    for plane, data in ((PLANE_BW, bw), (PLANE_RED, red)):
        for off in range(0, len(data), CHUNK):
            yield bytes([OP_CHUNK, plane, off & 0xFF, off >> 8]) + bytes(data[off:off + CHUNK])
    yield bytes([OP_END])


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

    def send_image(self, addr, bw, red, progress=None):
        msgs = list(image_messages(bw, red))
        for i, msg in enumerate(msgs):
            if not self.send_data(addr, msg):
                print(f"  {addr:04x}: gave up at message {i + 1}/{len(msgs)}")
                return False
            if i == 0:
                time.sleep(BEGIN_SETTLE_S)
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
    sub.add_parser("ping")
    ap.add_argument("--list", action="store_true", help="list serial ports and exit")
    args = ap.parse_args()

    if args.list:
        for p in list_ports.comports():
            print(f"{p.device}  {p.description}")
        return 0
    if not args.port or not args.cmd:
        ap.error("port and a command (send, serve, ping) are required")

    hub = Hub(args.port)
    if not hub.ping():
        print("hub does not answer P - check the port and that the hub firmware is flashed")
        return 1
    if args.cmd == "ping":
        print("PONG")
        return 0
    try:
        return {"send": cmd_send, "serve": cmd_serve}[args.cmd](hub, args)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
