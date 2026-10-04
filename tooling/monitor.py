#!/usr/bin/env python3
"""monitor.py - watch the Hub and tag debug logs side by side and summarise the link.

Both firmwares log on UART0 TX (PB4) at 38400 8N1. Give each serial port a name:

    python tooling/monitor.py hub=COM7 tag=COM8
    python tooling/monitor.py hub=COM7 tag=COM8 --log run1.txt --summary 60
    python tooling/monitor.py tag=COM8 --reset          # reset the tag first (RTS pulse)
    python tooling/monitor.py --list

Every line is printed with a timestamp and the port name. The link summary is
built from what the firmware prints:

    tag: "poll ok att=N rssi=R hubrssi=H" / "poll FAILED after N attempts"
    hub: "POLL src=.. seq=.. rssi=R [retry] [dup]"

and is shown every --summary seconds and when you press Ctrl+C.
DTR (boot pin) and RTS (reset) are held low while the ports are open, the same
line roles as tooling/axsem-flasher.py, so opening a port does not reset the tag
or send it into the bootloader.
"""

import argparse
import datetime
import re
import sys
import threading
import time
from collections import Counter

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial is required:  pip install pyserial")

BAUD = 38400

RE_TAG_OK = re.compile(r"poll ok att=(\d+) rssi=(-?\d+)(?: hubrssi=(-?\d+))?")
RE_TAG_FAIL = re.compile(r"poll FAILED after (\d+) attempts")
RE_HUB_POLL = re.compile(r"POLL src=([0-9a-f]+) seq=([0-9a-f]+) rssi=(-?\d+)(.*)")


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.ok = 0
        self.failed = 0
        self.attempts = Counter()
        self.tag_rssi = []
        self.hub_rssi = []
        self.hub_polls = 0
        self.hub_dups = 0
        self.hub_retries = 0

    def feed(self, text):
        with self.lock:
            m = RE_TAG_OK.search(text)
            if m:
                self.ok += 1
                self.attempts[int(m.group(1))] += 1
                self.tag_rssi.append(int(m.group(2)))
                if m.group(3) is not None:
                    self.hub_rssi.append(int(m.group(3)))
                return
            m = RE_TAG_FAIL.search(text)
            if m:
                self.failed += 1
                return
            m = RE_HUB_POLL.search(text)
            if m:
                self.hub_polls += 1
                self.hub_retries += " retry" in m.group(4)
                self.hub_dups += " dup" in m.group(4)

    @staticmethod
    def _rssi(values):
        return f"{min(values)}/{sum(values) / len(values):.0f}/{max(values)} dBm" if values else "-"

    def summary(self):
        with self.lock:
            total = self.ok + self.failed
            lines = ["---- link summary ----"]
            if total:
                lines.append(f"tag polls : {total}  ok {self.ok} ({100 * self.ok / total:.1f} %)  "
                             f"failed {self.failed}")
                hist = ", ".join(f"{k} att: {v}" for k, v in sorted(self.attempts.items()))
                lines.append(f"attempts  : {hist or '-'}")
                lines.append(f"rssi at tag (min/avg/max): {self._rssi(self.tag_rssi)}")
                lines.append(f"rssi at hub (min/avg/max): {self._rssi(self.hub_rssi)}")
            else:
                lines.append("no tag polls seen yet")
            if self.hub_polls:
                lines.append(f"hub heard : {self.hub_polls} polls, {self.hub_retries} flagged retry, "
                             f"{self.hub_dups} duplicates")
            return "\n".join(lines)


def open_port(port):
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = BAUD
    ser.timeout = 0.2
    ser.dtr = False          # boot pin released
    ser.rts = False          # reset released
    ser.open()
    return ser


def reader(name, ser, stats, out, out_lock, stop):
    buf = bytearray()
    while not stop.is_set():
        chunk = ser.read(256)
        if not chunk:
            continue
        buf += chunk
        while b"\n" in buf:
            raw, _, rest = bytes(buf).partition(b"\n")
            buf = bytearray(rest)
            text = raw.decode("latin-1").rstrip("\r")
            if not text:
                continue
            stamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            stats.feed(text)
            line = f"[{stamp} {name}] {text}"
            with out_lock:
                print(line)
                if out:
                    out.write(line + "\n")
                    out.flush()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ports", nargs="*", metavar="NAME=PORT", help="e.g. hub=COM7 tag=COM8")
    ap.add_argument("--log", help="also write the timestamped lines to this file")
    ap.add_argument("--summary", type=int, default=0, metavar="SEC", help="print the link summary every SEC seconds")
    ap.add_argument("--reset", action="store_true", help="pulse RESET (RTS) on every port once opened")
    ap.add_argument("--list", action="store_true", help="list serial ports and exit")
    args = ap.parse_args()

    if args.list:
        for p in list_ports.comports():
            print(f"{p.device}  {p.description}")
        return
    if not args.ports:
        ap.error("give at least one NAME=PORT")

    sers = {}
    for spec in args.ports:
        name, sep, port = spec.partition("=")
        if not sep:
            ap.error(f"expected NAME=PORT, got {spec!r}")
        sers[name] = open_port(port)

    if args.reset:
        for ser in sers.values():
            ser.rts = True
        time.sleep(0.1)
        for ser in sers.values():
            ser.rts = False

    stats, stop, out_lock = Stats(), threading.Event(), threading.Lock()
    out = open(args.log, "a", encoding="latin-1") if args.log else None
    threads = [threading.Thread(target=reader, args=(n, s, stats, out, out_lock, stop), daemon=True)
               for n, s in sers.items()]
    for t in threads:
        t.start()

    print("Monitoring " + ", ".join(f"{n}={s.port}" for n, s in sers.items()) + "  (Ctrl+C to stop)")
    try:
        last = time.time()
        while True:
            time.sleep(0.2)
            if args.summary and time.time() - last >= args.summary:
                last = time.time()
                with out_lock:
                    print(stats.summary())
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for t in threads:
            t.join(1)
        for s in sers.values():
            s.close()
        print("\n" + stats.summary())
        if out:
            out.write(stats.summary() + "\n")
            out.close()


if __name__ == "__main__":
    main()
