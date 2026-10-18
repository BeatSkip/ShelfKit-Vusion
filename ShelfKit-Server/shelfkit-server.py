#!/usr/bin/env python3
"""shelfkit-server.py - browser UI for the ShelfKit hub and tags.

Serves a local web page with one pane per serial port (its own log, baud rate,
Open/Close, Clear, and DTR / Reset controls) and a bar that pushes an image to a
tag picked from the ones that announced themselves:

    python ShelfKit-Server/shelfkit-server.py hub=COM4 tag=COM3
    python ShelfKit-Server/shelfkit-server.py hub=COM4          # second pane free
    python ShelfKit-Server/shelfkit-server.py --baud 115200 hub=COM4 tag=COM3
    python ShelfKit-Server/shelfkit-server.py --no-browser --port 9000
    python ShelfKit-Server/shelfkit-server.py --list

Ports named on the command line are opened at startup; ports only picked up from
the auto-detected list are pre-filled but left closed, so nothing is grabbed
without asking. The page is served on 127.0.0.1 by default - it can drive a
serial port and read image files on this machine, so it is not meant to be
reachable from anywhere else.

Both handshake lines start RELEASED (DTR low, RTS low). On this tag DTR is the
BOOT pin and RTS is the RESET line, so that is the state which neither resets the
board nor drops it into the bootloader. Per pane, "DTR" is a level toggle and
"Reset" is a push button that pulses RTS for 100 ms.

[Copy logs] merges both panes by arrival time and puts them on the clipboard;
[Save log] downloads the same text. [Send] closes the hub pane's port for the
duration of the transfer (one serial port cannot serve two owners) and reopens
it afterwards; the rotation is picked to fit the panel rather than assumed.

Requires pyserial (the page itself is plain HTML/JS, served from the standard
library) and pillow for the image conversion:

    pip install -r ShelfKit-Server/requirements.txt
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

try:
    import serial  # noqa: F401 - only to fail with a helpful message
except ImportError:  # pragma: no cover - environment check
    sys.exit(
        "pyserial is required:  pip install -r ShelfKit-Server/requirements.txt"
    )

from shelfkit import webapp  # noqa: E402 - after the sys.path fix above
from shelfkit.app import App, build_specs  # noqa: E402
from shelfkit.serial_link import DEFAULT_BAUD, available_ports  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "ports", nargs="*", metavar="[NAME=]PORT", help="up to two, e.g. hub=COM4 tag=COM3"
    )
    ap.add_argument(
        "--baud", type=int, default=DEFAULT_BAUD, help=f"initial baud rate (default {DEFAULT_BAUD})"
    )
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    ap.add_argument(
        "--port", type=int, default=8765, help="HTTP port, 0 picks a free one (default 8765)"
    )
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    ap.add_argument("--list", action="store_true", help="list serial ports and exit")
    args = ap.parse_args(argv)

    if args.list:
        for device, description in available_ports():
            print(f"{device}  {description}")
        return 0
    if len(args.ports) > 2:
        ap.error("this tool opens exactly two ports")

    specs, auto_open = build_specs(args.ports, args.baud)
    app = App(specs, auto_open)

    try:
        server = webapp.make_server(app, args.host, args.port)
    except OSError as exc:
        print(f"cannot listen on {args.host}:{args.port} - {exc}", file=sys.stderr)
        return 1

    host, port = server.server_address[:2]
    # 0.0.0.0 is not a URL you can open; show the loopback address instead and
    # mention what it is actually bound to.
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown}:{port}/"
    bind = "" if shown == host else f"  (listening on {host}:{port})"
    # flush=True so the URL is visible when the output is piped, not just on a
    # terminal (python block-buffers stdout otherwise).
    print(f"ShelfKit server on {url}{bind}", flush=True)
    for spec, pane in zip(specs, app.panes.values()):
        print(f"  {spec.name:<6} {spec.port or '(no port)':<12} {pane.worker.status}", flush=True)
    print("Ctrl+C to stop", flush=True)

    if not args.no_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()

    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print()
    finally:
        for pane in app.panes.values():
            pane.worker.close()
        server.server_close()
        print("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
