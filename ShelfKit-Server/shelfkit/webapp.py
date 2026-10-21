"""The web UI: a tiny JSON/HTTP front end over shelfkit.app.

Standard library only - `http.server` with one thread per request and one
long-lived poll connection per browser tab. The API is small and boring:

    GET  /                     the page
    GET  /app.js /style.css    its assets
    GET  /api/state            everything the UI needs to draw itself
    GET  /api/poll?c=a:1:12&e=0  new log lines per pane, new events, and the state
    GET  /api/files?dir=...    one folder's sub-directories and image files
    GET  /api/log              both logs merged, as plain text (copy/download)
    GET  /api/preview.png?t=<key>&kind=original|device   a rendered frame
    POST /api/pane/<key>/open      {"port": "...", "baud": 38400}
    POST /api/pane/<key>/close
    POST /api/pane/<key>/clear
    POST /api/pane/<key>/line      {"line": "dtr"|"rts", "value": true|false}
    POST /api/pane/<key>/toggle    {"line": "dtr"}
    POST /api/pane/<key>/reset     one 100 ms RTS pulse
    POST /api/editor               {"fit": "cover", "dither": "threshold"}
    POST /api/image                {"path": "/abs/or/relative.png"}
    POST /api/preview              render the picked image (does not send)
    POST /api/send                 {"addr": 256}
    POST /api/cancel
    POST /api/tags/<hex>           {"alias": "...", "notes": "...", "grid_row": 1, "grid_col": 3}
    POST /api/tags/<hex>/assign    {"id": "0100"}  (empty = next free) over the hub port
    POST /api/tags/<hex>/flash     {"path": "Release/vusion-....hex"}  OTA firmware update
    POST /api/tags/<hex>/forget    delete the server's record of one tag
    POST /api/tags/<hex>/wipe      wipe the tag's flash and reset it into a new id
    POST /api/tags/<hex>/service   draw this tag's service label and push it
    POST /api/tags/forget          {"addrs": [...]} or {"not_seen_for": 600}

State that has to outlive the process lives in shelfkit/store.py (one SQLite
file): settings, tag metadata, rendered bitmaps and the event log.

The server binds to 127.0.0.1 by default: it can drive a serial port and read
image files on this machine, so it is not meant to be reachable from anywhere
else.
"""

from __future__ import annotations

import json
import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .app import App

STATIC_DIR = Path(__file__).resolve().parent / "static"
# Only these are served, so a request path can never escape STATIC_DIR.
ASSETS = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/style.css": "style.css",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "ShelfKit-Server"
    protocol_version = "HTTP/1.1"
    app: App = None  # set by serve()

    # ── plumbing ───────────────────────────────────────────────────────────
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - base class name
        """Silence the access log: the UI polls several times a second."""

    def _send(self, status: int, body: bytes, content_type: str, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The UI is local and always freshly loaded; no-store keeps a stale page
        # from talking to a newer API after a restart. Preview PNGs opt out: they
        # are addressed by a hash of their inputs.
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def _error(self, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        self._json({"error": message}, status)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    # ── routes ─────────────────────────────────────────────────────────────
    def do_GET(self) -> None:  # noqa: N802 - base class name
        url = urlparse(self.path)
        path = unquote(url.path)
        query = parse_qs(url.query)

        if path in ASSETS:
            return self._serve_asset(ASSETS[path])
        if path == "/api/state":
            return self._json(self.app.state())
        if path == "/api/poll":
            cursors = parse_cursors((query.get("c") or [""])[0])
            try:
                event_cursor = int((query.get("e") or ["0"])[0])
            except ValueError:
                event_cursor = 0
            return self._json(self.app.poll(cursors, event_cursor))
        if path == "/api/files":
            return self._json(self.app.browse((query.get("dir") or [None])[0]))
        if path == "/api/preview.png":
            return self._serve_preview(
                (query.get("t") or [""])[0], (query.get("kind") or ["device"])[0]
            )
        if path == "/api/log":
            text = self.app.combined_log()
            return self._send(
                HTTPStatus.OK,
                text.encode("utf-8", "replace"),
                "text/plain; charset=utf-8",
            )
        return self._error(f"no such path {path}", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - base class name
        path = unquote(urlparse(self.path).path)
        body = self._body()
        parts = [part for part in path.split("/") if part]
        # every endpoint is /api/<something>
        if not parts or parts[0] != "api":
            return self._error(f"no such path {path}", HTTPStatus.NOT_FOUND)

        try:
            if parts == ["api", "editor"]:
                self.app.set_options(body.get("fit"), body.get("dither"))
                return self._json(self.app.state())
            if parts == ["api", "preview"]:
                # Rendered server-side and cached under a content key; the page
                # only ever displays the PNGs (spec: the browser does no dithering).
                return self._json(self.app.render_preview())
            if parts == ["api", "image"]:
                if not self.app.set_image(str(body.get("path") or "")):
                    return self._json(self.app.state(), HTTPStatus.CONFLICT)
                return self._json(self.app.state())
            if parts == ["api", "send"]:
                try:
                    addr = int(body.get("addr"))
                except (TypeError, ValueError):
                    return self._error("addr must be a node id")
                if not self.app.send(addr):
                    return self._json(self.app.state(), HTTPStatus.CONFLICT)
                return self._json(self.app.state())
            if parts == ["api", "cancel"]:
                self.app.cancel()
                return self._json(self.app.state())
            if parts == ["api", "tags", "forget"]:
                # batch: {"addrs": [...]} or {"not_seen_for": 600}
                result = self.app.forget_tags(
                    body.get("addrs") or [], body.get("not_seen_for"))
                return self._json({"result": result, "state": self.app.state()})
            if len(parts) == 3 and parts[1] == "tags":
                # Tag metadata: alias, notes and the fleet-map position. The only
                # things on a tag the user types rather than the board reporting.
                updated = self.app.set_tag(parts[2], **body)
                if updated is None:
                    return self._error(f"bad tag id {parts[2]}")
                return self._json({"tag": updated, "state": self.app.state()})
            if len(parts) == 4 and parts[1] == "tags" and parts[3] == "service":
                try:
                    addr = int(parts[2], 16)
                except ValueError:
                    return self._error(f"bad tag id {parts[2]}")
                result = self.app.service_image(
                    addr, body.get("note"), body.get("alias"))
                return self._json({"result": result, "state": self.app.state()})
            if len(parts) == 4 and parts[1] == "tags" and parts[3] == "wipe":
                try:
                    addr = int(parts[2], 16)
                except ValueError:
                    return self._error(f"bad tag id {parts[2]}")
                result = self.app.factory_reset(addr)
                return self._json({"result": result, "state": self.app.state()})
            if len(parts) == 4 and parts[1] == "tags" and parts[3] == "forget":
                try:
                    addr = int(parts[2], 16)
                except ValueError:
                    return self._error(f"bad tag id {parts[2]}")
                result = self.app.forget_tags([addr])
                return self._json({"result": result, "state": self.app.state()})
            if len(parts) == 4 and parts[1] == "tags" and parts[3] == "flash":
                try:
                    addr = int(parts[2], 16)
                except ValueError:
                    return self._error(f"bad tag id {parts[2]}")
                result = self.app.flash_firmware(addr, str(body.get("path") or ""))
                return self._json({"result": result, "state": self.app.state()})
            if len(parts) == 4 and parts[1] == "tags" and parts[3] == "assign":
                try:
                    addr = int(parts[2], 16)
                except ValueError:
                    return self._error(f"bad tag id {parts[2]}")
                result = self.app.assign_id(addr, body.get("id"))
                return self._json({"result": result, "state": self.app.state()})
            if len(parts) == 4 and parts[1] == "pane":
                return self._pane_command(parts[2], parts[3], body)
        except Exception as exc:  # noqa: BLE001 - a bad request must not kill the server
            return self._error(f"{type(exc).__name__}: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)
        return self._error(f"no such path {path}", HTTPStatus.NOT_FOUND)

    def _pane_command(self, key: str, action: str, body: dict) -> None:
        if key not in self.app.panes:
            return self._error(f"no pane {key}", HTTPStatus.NOT_FOUND)
        if action == "open":
            self.app.open_pane(key, body.get("port"), body.get("baud"))
        elif action == "close":
            self.app.close_pane(key)
        elif action == "clear":
            self.app.clear_pane(key)
        elif action == "line":
            line = str(body.get("line") or "").lower()
            if line not in ("dtr", "rts"):
                return self._error("line must be dtr or rts")
            self.app.set_line(key, line, bool(body.get("value")))
        elif action == "toggle":
            line = str(body.get("line") or "").lower()
            if line not in ("dtr", "rts"):
                return self._error("line must be dtr or rts")
            self.app.toggle_line(key, line)
        elif action == "reset":
            self.app.pulse_reset(key)
        else:
            return self._error(f"no action {action}", HTTPStatus.NOT_FOUND)
        return self._json(self.app.state())

    def _serve_preview(self, token: str, kind: str) -> None:
        """A preview PNG: kind=original (colour) or kind=device (1:1 BWR).

        Served from the render cache first, then from the store - a stored frame
        keeps working across a restart, which is what makes Fleet thumbnails
        permanent.
        """
        body = self.app.bitmap_png(token, "original" if kind == "original" else "device")
        if body is None:
            return self._error("that preview has expired - render it again", HTTPStatus.NOT_FOUND)
        # The token is a hash of the render inputs, so this document never changes.
        self._send(HTTPStatus.OK, body, "image/png", cache="max-age=3600, immutable")

    def _serve_asset(self, name: str) -> None:
        path = STATIC_DIR / name
        try:
            body = path.read_bytes()
        except OSError as exc:
            return self._error(f"cannot read {name}: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        self._send(HTTPStatus.OK, body, content_type)


def parse_cursors(value: str) -> dict[str, str]:
    """Parse the poll query: "hub=1:12,tag=0:3" -> {"hub": "1:12", "tag": "0:3"}.

    The separator between the pane name and its cursor is "=", and the cursor
    itself is "epoch:seq". Splitting on ":" first - which is what a "hub:1:12"
    form would suggest - silently turns the key into "hub=1", the lookup misses,
    and every poll then returns the whole buffer again. That is the bug that made
    the console look like it was re-printing: keep the "=" split first.
    A "hub:1:12" form is also accepted for older callers.
    """
    cursors: dict[str, str] = {}
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        key, sep, cursor = part.partition("=")
        if not sep:                      # legacy "hub:1:12"
            key, _, cursor = part.partition(":")
        epoch, _, seq = cursor.partition(":")
        if key:
            cursors[key] = f"{epoch}:{seq}"
    return cursors


def make_server(app: App, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    handler = type("ShelfKitHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve(app: App, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    """Start serving in a background thread; returns the running server."""
    server = make_server(app, host, port)
    threading.Thread(target=server.serve_forever, name="http", daemon=True).start()
    return server
