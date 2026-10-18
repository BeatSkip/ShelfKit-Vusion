"""Everything shelfkit-server does, with no UI attached.

`App` owns the two panes, their logs, the tags that announced themselves and the
image push. The web layer turns its methods into HTTP calls; nothing in here
knows that a browser exists.

Cursors: each pane keeps a monotonically increasing `seq` per logged line, so a
client can ask for "everything after N" instead of re-reading the whole log. A
`Clear` bumps the pane's `epoch`, which tells the client to wipe what it shows.
"""

from __future__ import annotations

import itertools
import re
import threading
import time
from collections import deque
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from . import hubhost
from .serial_link import DEFAULT_BAUD, PortSpec, SerialWorker, available_ports

MAX_LOG_LINES = 5000
RESET_PULSE_S = 0.1  # how long the momentary Reset button holds RTS asserted

# Image push defaults. The editor's fit mode and dither come from
# shelfkit.preview (one pipeline for the preview and the bytes that are sent).
IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
)
# A tag announces itself on the hub's UART log as "POLL src=<node id>".
RE_POLL = re.compile(r"^POLL src=([0-9a-fA-F]{4,8})\b")
RE_PONG = re.compile(r"^PONG\b")
# What the board says when it comes up. Which one appears after a reset tells us
# which BOOT-pin level the firmware needs (see App.pulse_reset).
RE_BOOTLOADER = re.compile(r"^AX8052 Bootloader")
RE_FIRMWARE = re.compile(r"^\*\*\* ShelfKit ")
# How long after a reset pulse we still attribute a boot banner to that reset.
RESET_ATTRIBUTION_S = 4.0
PORT_LIST_TTL_S = 2.0  # cache list_ports(): it is an OS enumeration, not free


def _stamp() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _default_image_dir() -> Path:
    """Where the picker opens: the repo's image folders, else the cwd."""
    repo = Path(__file__).resolve().parent.parent.parent
    for candidate in (Path.cwd() / "Resources", Path.cwd() / "images", repo / "Resources"):
        if candidate.is_dir():
            return candidate
    return Path.cwd()


def pane_key(name: str, index: int) -> str:
    """A URL-safe pane key derived from the device name."""
    safe = "".join(ch for ch in name.lower() if ch.isalnum())
    return safe or chr(ord("a") + index)


def build_specs(ports: list[str], baud: int) -> tuple[list[PortSpec], bool]:
    """Two panes from CLI arguments; returns (specs, whether to open at startup)."""
    detected = [device for device, _ in available_ports()]
    specs: list[PortSpec] = []
    for i, raw in enumerate(ports[:2]):
        name, sep, port = raw.partition("=")
        if not sep:
            name, port = chr(ord("A") + i), raw
        specs.append(PortSpec(name.strip() or chr(ord("A") + i), port.strip(), baud))
    while len(specs) < 2:
        used = {spec.port for spec in specs}
        free = next((dev for dev in detected if dev not in used), "")
        specs.append(PortSpec(chr(ord("A") + len(specs)), free, baud))
    return specs, bool(ports)


class Pane:
    """One port, its worker and its ring buffer of log lines."""

    def __init__(self, key: str, spec: PortSpec, on_line) -> None:
        self.key = key
        self.spec = spec  # what the user asked for
        # The worker keeps its own copy: that is what the open port is using, so
        # a changed port/baud can be noticed and reopened.
        self.worker = SerialWorker(replace(spec), on_line=on_line)
        # (seq, arrival, stamp, text); arrival orders lines across both panes.
        self.log: deque[tuple[int, int, str, str]] = deque(maxlen=MAX_LOG_LINES)
        self.seq = 0
        self.epoch = 0
        # Wakes anything waiting for a line (the image push waits for SENT/PONG).
        self.cond = threading.Condition()

    def add(self, arrival: int, text: str) -> None:
        self.seq += 1
        self.log.append((self.seq, arrival, _stamp(), text))
        with self.cond:
            self.cond.notify_all()

    def clear(self) -> None:
        self.log.clear()
        self.epoch += 1

    def since(self, cursor: int) -> list[list]:
        return [
            [seq, stamp, text]
            for seq, _arrival, stamp, text in self.log
            if seq > cursor
        ]

    def state(self) -> dict:
        worker = self.worker
        return {
            "key": self.key,
            "name": self.spec.name,
            "port": self.spec.port,
            "baud": self.spec.baud,
            "open": worker.is_open,
            "status": worker.status,
            "dtr": worker.dtr,
            "rts": worker.rts,
            "lines": worker.rx_lines,
            "bytes": worker.rx_bytes,
            "epoch": self.epoch,
            "cursor": self.seq,
        }


class App:
    """The two panes plus the image push, safe to call from request threads."""

    def __init__(self, specs: list[PortSpec], auto_open: bool = False, store=None) -> None:
        self.lock = threading.RLock()
        self._arrivals = itertools.count(1)
        self.status = "ready"
        self.image: Path | None = None
        self.sending = False
        self.progress = ""
        self.tags: dict[int, int] = {}
        # Editor: how the image is fitted and dithered, plus the last preview.
        # The push renders through the same function, so what is shown is what is
        # sent (spec: never allow a push without a preview).
        self.fit = "cover"
        self.dither = "threshold"
        self.preview: dict | None = None
        # Bookkeeping the Fleet/Queue/Logs screens show: when a tag was last
        # heard, and what it was last sent. Wall-clock seconds (persisted, so a
        # restart keeps the ages meaningful); ages go over the wire.
        self.tag_seen: dict[int, float] = {}
        # name, when, render key (the key lets the Fleet show the frame as a thumb)
        self.tag_push: dict[int, tuple[str, float, str | None]] = {}
        # Editable per tag: alias, notes, and fleet-map position
        self.tag_meta: dict[int, dict] = {}
        self.send_to: int | None = None
        self.last_answer: str | None = None   # the hub's last SENT/ERR answer
        self._ports = (0.0, [])               # (fetched_at, [(device, description)])
        # The DTR (BOOT) level that makes the board run its firmware rather than
        # the serial bootloader. The documented mapping is "released", but the
        # only authority is the board itself: pulse_reset() watches what comes up
        # and flips this if it guessed wrong.
        self.boot_state = False
        self._reset_at: tuple[str, float] | None = None   # (pane key, deadline)
        self.store = store                      # shelfkit.store.Store, or None
        self.keys: list[str] = []
        self.panes: dict[str, Pane] = {}
        for i, spec in enumerate(specs):
            key = pane_key(spec.name, i)
            self.keys.append(key)
            self.panes[key] = Pane(key, spec, on_line=lambda text, k=key: self._on_line(k, text))
        self._restore()
        if auto_open:
            for key in self.keys:
                self.open_pane(key)

    # ── persistence ────────────────────────────────────────────────────────
    def _restore(self) -> None:
        """Bring back what the last run knew: settings, tags and their content."""
        if self.store is None:
            return
        saved = self.store.settings()
        try:                                   # one source of truth for the options
            from . import preview
            fits, dithers = preview.FIT_MODES, preview.DITHERS
        except Exception:  # noqa: BLE001 - no Pillow: nothing to validate against
            fits, dithers = (), ()
        fit = saved.get("editor.fit")
        dither = saved.get("editor.dither")
        if fit in fits:
            self.fit = fit
        if dither in dithers:
            self.dither = dither
        image = saved.get("editor.image")
        if image and Path(image).is_file():
            self.image = Path(image)
        for key, pane in self.panes.items():
            port = saved.get(f"pane.{key}.port")
            baud = saved.get(f"pane.{key}.baud")
            if port:
                pane.spec.port = str(port)
                pane.worker.spec.port = str(port)
            if isinstance(baud, int) and baud > 0:
                pane.spec.baud = baud
                pane.worker.spec.baud = baud
        for row in self.store.tags():
            addr = int(row["hex_id"], 16)
            self.tags[addr] = int(row["seen_count"] or 0)
            if row["last_seen"]:
                self.tag_seen[addr] = float(row["last_seen"])
            if row["push_name"]:
                self.tag_push[addr] = (
                    row["push_name"],
                    float(row["push_at"] or 0),
                    row["push_key"],
                )
            self.tag_meta[addr] = {
                "alias": row["alias"],
                "notes": row["notes"],
                "row": row["grid_row"],
                "col": row["grid_col"],
            }
        if self.image is not None:
            # Re-render so the preview and its thumbnails are live again.
            threading.Thread(target=self.render_preview, name="restore-preview",
                             daemon=True).start()

    def _save_setting(self, key: str, value) -> None:
        if self.store is not None:
            self.store.set_setting(key, value)

    def _event(self, event: str, hex_id: str | None = None, detail: str | None = None) -> None:
        if self.store is not None:
            self.store.add_event(event, hex_id, detail)

    def events(self, since: int = 0, limit: int = 500) -> list[list]:
        """Event log rows newer than `since` (durable; backs the Logs screen)."""
        if self.store is None:
            return []
        return self.store.events_since(since, limit)

    def event_cursor(self) -> int:
        return self.store.latest_event_id() if self.store is not None else 0

    def bitmap_png(self, key: str, kind: str) -> bytes | None:
        """A rendered frame's PNG: from the render cache, else from the store."""
        try:
            from . import preview
        except Exception:  # noqa: BLE001 - Pillow missing
            preview = None
        if preview is not None:
            rendered = preview.cached(key)
            if rendered is not None:
                return rendered.original_png if kind == "original" else rendered.device_png
        if self.store is not None:
            return self.store.bitmap_png(key, kind)
        return None

    def set_tag(self, hex_id: str, **fields) -> dict | None:
        """Edit a tag's alias/notes/map position, in memory and on disk."""
        try:
            addr = int(hex_id, 16)
        except (TypeError, ValueError):
            return None
        clean: dict = {}
        for name in ("alias", "notes", "grid_row", "grid_col"):
            if name not in fields:
                continue
            value = fields[name]
            if name in ("grid_row", "grid_col"):
                try:
                    clean[name] = int(value) if value not in (None, "") else None
                except (TypeError, ValueError):
                    continue
            else:
                text = ("" if value is None else str(value)).strip()
                clean[name] = text or None
        if "alias" in clean and clean["alias"] is not None:
            clean["alias"] = clean["alias"][:24]
        with self.lock:
            meta = self.tag_meta.setdefault(addr, {"alias": None, "notes": None,
                                                   "row": None, "col": None})
            if "alias" in clean:
                meta["alias"] = clean["alias"]
            if "notes" in clean:
                meta["notes"] = clean["notes"]
            if "grid_row" in clean:
                meta["row"] = clean["grid_row"]
            if "grid_col" in clean:
                meta["col"] = clean["grid_col"]
            hex_code = f"{addr:04X}"
        if self.store is not None:
            self.store.update_tag(hex_code, **clean)
        return dict(meta, hex_id=hex_code)


    # ── logging ────────────────────────────────────────────────────────────
    def _on_line(self, key: str, text: str) -> None:
        self.note(key, text)

    def note(self, key: str, text: str) -> None:
        """Append one line to a pane's log (board output or a "what I am doing" note)."""
        learn = None
        event: tuple[str, str | None, str | None] | None = None
        counted: int | None = None
        with self.lock:
            pane = self.panes.get(key)
            if pane is None:
                return
            pane.add(next(self._arrivals), text)
            match = RE_POLL.match(text)
            if match:
                addr = int(match.group(1), 16)
                self.tags[addr] = self.tags.get(addr, 0) + 1
                self.tag_seen[addr] = time.time()
                counted = addr
                event = ("sync", f"{addr:04X}", None)
            if RE_BOOTLOADER.match(text):
                learn = "bootloader"
                event = ("bootloader", None, text.strip()[:48])
            elif RE_FIRMWARE.match(text):
                self._reset_at = None      # the firmware came up: nothing to learn
                event = ("boot", None, text.strip()[:48])
        if counted is not None and self.store is not None:
            # The store owns the counter, so a restart continues the same number.
            self.tags[counted] = self.store.touch_tag(f"{counted:04X}")
        if event is not None:
            self._event(*event)
        if learn:
            self._learn_boot_state(key)

    def combined_log(self) -> str:
        """Both panes' lines merged by arrival time, as one copyable block."""
        with self.lock:
            rows: list[tuple[int, str]] = []
            for key in self.keys:
                pane = self.panes[key]
                for _seq, arrival, stamp, text in pane.log:
                    rows.append((arrival, f"[{stamp} {pane.spec.name}] {text}"))
            rows.sort(key=lambda row: row[0])  # stable, so equal times keep pane order
            ports = ", ".join(
                f"{p.spec.name}={p.spec.port or '?'}" for p in self.panes.values()
            )
            header = (
                f"=== ShelfKit two-port log: {ports} - {len(rows)} lines, "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ==="
            )
        return "\n".join([header, *(line for _arrival, line in rows)])

    # ── state ──────────────────────────────────────────────────────────────
    def hub_key(self) -> str:
        """The pane whose port talks to the tags: the one named 'hub', else the
        first that has heard an announcement, else the first pane."""
        with self.lock:
            for key in self.keys:
                if self.panes[key].spec.name.strip().lower() == "hub":
                    return key
            for key in self.keys:
                if self.panes[key].worker.rx_lines:
                    return key
            return self.keys[0]

    def _port_list(self) -> list[list[str]]:
        """The detected ports, cached: this is an OS enumeration and the page asks
        for the state several times a second."""
        now = time.monotonic()
        fetched, ports = self._ports
        if now - fetched > PORT_LIST_TTL_S:
            ports = [list(port) for port in available_ports()]
            self._ports = (now, ports)
        return ports

    def state(self) -> dict:
        with self.lock:
            now = time.time()          # wall clock: these ages survive a restart
            detail = {}
            for addr, count in self.tags.items():
                push = self.tag_push.get(addr)
                meta = self.tag_meta.get(addr) or {}
                detail[str(addr)] = {
                    "count": count,
                    "seen": round(now - self.tag_seen.get(addr, now), 1),
                    "alias": meta.get("alias"),
                    "notes": meta.get("notes"),
                    "row": meta.get("row"),
                    "col": meta.get("col"),
                    "push": (
                        {
                            "name": push[0],
                            "age": round(now - push[1], 1),
                            "thumb": (
                                f"/api/preview.png?t={push[2]}&kind=device" if push[2] else None
                            ),
                        }
                        if push is not None
                        else None
                    ),
                }
            return {
                "panes": [self.panes[key].state() for key in self.keys],
                "ports": self._port_list(),
                "tags": [[addr, count] for addr, count in sorted(self.tags.items())],
                "tag_info": detail,
                "hub": self.hub_key(),
                "image": (
                    {"path": str(self.image), "name": self.image.name}
                    if self.image is not None
                    else None
                ),
                "sending": self.sending,
                "send_to": self.send_to,
                "progress": self.progress,
                "status": self.status,
                "reset_ms": int(RESET_PULSE_S * 1000),
                "max_lines": MAX_LOG_LINES,
                "editor": {
                    "fit": self.fit,
                    "dither": self.dither,
                    "preview": self.preview,
                    **self._editor_options(),
                },
            }

    @staticmethod
    def _editor_options() -> dict:
        """The fit modes and dithers the renderer supports (empty without Pillow)."""
        try:
            from . import preview
        except Exception:  # noqa: BLE001 - Pillow missing: no previews, no options
            return {"fits": [], "dithers": [], "midtone_warn": 0.4, "panel": [152, 296]}
        return preview.options()

    def poll(self, cursors: dict[str, str], event_cursor: int = 0) -> dict:
        """New log lines per pane plus new events. Cursors are "epoch:seq"."""
        out: dict[str, dict] = {}
        with self.lock:
            for key in self.keys:
                pane = self.panes[key]
                epoch, seq = _split_cursor(cursors.get(key))
                if epoch != pane.epoch:
                    seq = 0  # the pane was cleared: send what is there now
                out[key] = {
                    "lines": pane.since(seq),
                    "epoch": pane.epoch,
                    "cursor": pane.seq,
                    "reset": epoch != pane.epoch,
                }
        return {
            "panes": out,
            "state": self.state(),
            "events": self.events(event_cursor),
            "event_cursor": self.event_cursor(),
        }

    # ── port control ───────────────────────────────────────────────────────
    def open_pane(self, key: str, port: str | None = None, baud=None) -> None:
        pane = self.panes.get(key)
        if pane is None:
            return
        with self.lock:
            if port is not None and port.strip():
                pane.spec.port = port.strip()
            if baud not in (None, ""):
                try:
                    pane.spec.baud = max(300, int(baud))
                except (TypeError, ValueError):
                    self.status = f"bad baud rate {baud!r}"
                    return
            if not pane.spec.port:
                self.status = f"pick a port for {pane.spec.name} first"
                return
            changed = False
            if pane.worker.is_open:
                if (pane.worker.spec.port, pane.worker.spec.baud) == (
                    pane.spec.port,
                    pane.spec.baud,
                ):
                    return
                changed = True
        if changed:
            pane.worker.close()  # baud/port changed: reopen with the new settings
        pane.worker.spec.port = pane.spec.port
        pane.worker.spec.baud = pane.spec.baud
        pane.worker.open()
        with self.lock:
            self.status = f"{pane.spec.name}: {pane.worker.status}"
            opened = pane.worker.is_open
            lines = (
                f"DTR {'asserted' if pane.worker.dtr else 'released'}, "
                f"RTS {'asserted' if pane.worker.rts else 'released'}"
            )
        if opened:
            # Say what the lines were left at: opening a port re-applies them, and
            # on this board an asserted RTS is a held reset.
            self.note(pane.key, f"# {pane.spec.port} open @ {pane.spec.baud} 8N1, {lines}")
            # Remember the port for next time - as a pre-filled choice, not as an
            # automatic open: opening re-applies the modem lines.
            self._save_setting(f"pane.{key}.port", pane.spec.port)
            self._save_setting(f"pane.{key}.baud", pane.spec.baud)
            self._event("open", None, f"{pane.spec.name}={pane.spec.port}")

    def close_pane(self, key: str) -> None:
        pane = self.panes.get(key)
        if pane is None:
            return
        pane.worker.close()
        with self.lock:
            self.status = f"{pane.spec.name}: closed"

    def clear_pane(self, key: str) -> None:
        pane = self.panes.get(key)
        if pane is not None:
            with self.lock:
                pane.clear()

    def set_line(self, key: str, line: str, value: bool) -> None:
        pane = self.panes.get(key)
        if pane is None or line not in ("dtr", "rts"):
            return
        pane.worker.set_line(line, value)
        with self.lock:
            self.status = f"{pane.spec.name}: {line.upper()} {'asserted' if value else 'released'}"

    def toggle_line(self, key: str, line: str) -> None:
        pane = self.panes.get(key)
        if pane is None or line not in ("dtr", "rts"):
            return
        pane.worker.toggle(line)
        with self.lock:
            self.status = (
                f"{pane.spec.name}: {line.upper()} "
                f"{'asserted' if getattr(pane.worker, line) else 'released'}"
            )

    def pulse_reset(self, key: str) -> bool:
        """Assert RTS, then release it on a timer - a push button, not a toggle.

        The release is always scheduled, even if asserting failed: a reset line
        left held would keep the board in reset, which is the one state this
        button must never end in.

        Before the pulse the BOOT pin (DTR) is put where the *firmware* runs. A
        BOOT pin held in bootloader mode is the one way a reset can come up in
        the serial bootloader instead of the application, and then the board is
        not polling and the log looks like "it keeps resetting".
        """
        pane = self.panes.get(key)
        if pane is None:
            return False
        if not pane.worker.is_open:
            with self.lock:
                self.status = f"{pane.spec.name}: reset needs an open port"
            return False

        if pane.worker.dtr != self.boot_state:
            pane.worker.set_line("dtr", self.boot_state)
            self.note(
                key,
                "# BOOT (DTR) set to "
                f"{'asserted' if self.boot_state else 'released'} so the firmware runs",
            )

        pane.worker.set_line("rts", True)
        self.note(key, f"# reset pulsed ({int(RESET_PULSE_S * 1000)} ms)")
        threading.Timer(RESET_PULSE_S, self._release_reset, args=(key,)).start()
        with self.lock:
            self.status = f"{pane.spec.name}: reset pulsed"
            self._reset_at = (key, time.monotonic() + RESET_ATTRIBUTION_S)
        return True

    def _learn_boot_state(self, key: str) -> None:
        """The board came up in the bootloader: flip BOOT and reset once more.

        The flasher holds the BOOT pin one way to get the bootloader; which way
        is "released" depends on the board and the adapter. Rather than trust a
        comment, watch what actually came up after our own reset pulse.
        """
        with self.lock:
            pending = self._reset_at
            if pending is None or pending[0] != key or time.monotonic() > pending[1]:
                return          # not our reset, or the firmware came up fine
            self._reset_at = None          # one correction per reset
            self.boot_state = not self.boot_state
            learned = self.boot_state
        self.note(
            key,
            "# board came up in the serial bootloader - the BOOT pin was holding it there",
        )
        self.note(
            key,
            "# learned: DTR "
            f"{'asserted' if learned else 'released'} runs the firmware; resetting again",
        )
        pane = self.panes.get(key)
        if pane is None or not pane.worker.is_open:
            return
        pane.worker.set_line("dtr", learned)
        threading.Timer(0.2, self._reset_once, args=(key, False)).start()

    def _release_reset(self, key: str) -> None:
        pane = self.panes.get(key)
        if pane is not None:
            pane.worker.set_line("rts", False)

    def _reset_once(self, key: str, attribute: bool) -> None:
        pane = self.panes.get(key)
        if pane is None or not pane.worker.is_open:
            return
        pane.worker.set_line("rts", True)
        self.note(key, "# reset pulsed again")
        threading.Timer(RESET_PULSE_S, self._release_reset, args=(key,)).start()
        if attribute:
            with self.lock:
                self._reset_at = (key, time.monotonic() + RESET_ATTRIBUTION_S)

    # ── image selection ────────────────────────────────────────────────────
    def browse(self, where: str | None = None) -> dict:
        """One folder's sub-directories and image files, for the picker."""
        base = Path(where).expanduser() if where else _default_image_dir()
        try:
            base = base.resolve()
            if not base.is_dir():
                base = base.parent if base.parent.is_dir() else _default_image_dir()
        except OSError:
            base = _default_image_dir()

        dirs: list[str] = []
        files: list[dict] = []
        try:
            for entry in sorted(base.iterdir(), key=lambda p: p.name.lower()):
                if entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir():
                        dirs.append(entry.name)
                    elif entry.is_file() and entry.suffix.lower() in IMAGE_SUFFIXES:
                        files.append({"name": entry.name, "size": entry.stat().st_size})
                except OSError:
                    continue
        except OSError as exc:
            with self.lock:
                self.status = f"cannot read {base}: {exc}"
        parent = str(base.parent) if base.parent != base else None
        self._save_setting("browse.dir", str(base))
        return {"dir": str(base), "parent": parent, "dirs": dirs, "files": files}

    def set_image(self, path: str) -> bool:
        candidate = Path(path).expanduser()
        if not candidate.is_file():
            with self.lock:
                self.status = f"{path} is not a file"
            return False
        with self.lock:
            self.image = candidate
            self.preview = None        # a new image needs a new preview
            self.status = str(candidate)
        self._save_setting("editor.image", str(candidate))
        return True

    # ── editor: fit/dither + the preview ───────────────────────────────────
    def set_options(self, fit: str | None = None, dither: str | None = None) -> None:
        """Choose how the image is fitted and dithered (preview and push alike)."""
        with self.lock:
            changed = False
            if fit and fit != self.fit:
                self.fit, changed = fit, True
            if dither and dither != self.dither:
                self.dither, changed = dither, True
            if changed:
                self.preview = None    # the old preview no longer matches
                self.status = f"render: {self.fit}, {self.dither}"
        if changed:
            self._save_setting("editor.fit", self.fit)
            self._save_setting("editor.dither", self.dither)

    def render_preview(self) -> dict:
        """Render the picked image for the panel and remember it for the page."""
        with self.lock:
            image = self.image
            fit, dither = self.fit, self.dither
        if image is None:
            return {"ok": False, "error": "pick an image first"}
        try:
            from . import preview
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"previews need Pillow ({exc})"}
        try:
            rendered = preview.render(image, fit, dither)
        except Exception as exc:  # noqa: BLE001 - a bad file must not 500 the page
            with self.lock:
                self.preview = None
                self.status = f"cannot render {image.name}: {exc}"
            return {"ok": False, "error": str(exc)}

        if self.store is not None:
            # Keep the frame: thumbnails and previews must survive a restart.
            try:
                self.store.put_bitmap(rendered, name=image.name)
            except Exception as exc:  # noqa: BLE001 - storage is not worth a 500
                self.status = f"could not store the render: {exc}"

        summary = {
            "key": rendered.key,
            "angle": rendered.angle,
            "source": list(rendered.source),
            "fitted": list(rendered.fitted),
            "midtone": rendered.midtone,
            "fit": fit,
            "dither": dither,
            "original": f"/api/preview.png?t={rendered.key}&kind=original",
            "device": f"/api/preview.png?t={rendered.key}&kind=device",
        }
        with self.lock:
            self.preview = summary
            self.status = (
                f"preview ready: {rendered.fitted[0]}x{rendered.fitted[1]}"
                f"{f', rotation {rendered.angle} deg' if rendered.angle else ''}, {fit}, {dither}"
            )
        return {"ok": True, **summary}

    # ── the image push ─────────────────────────────────────────────────────
    def _wait_line(self, key: str, pattern, start: int, timeout: float):
        """Wait for a log line that arrived after `start` and matches `pattern`.

        The image push talks to the hub over the port the Console pane already
        has open: closing and reopening it for every transfer re-applies DTR/RTS,
        and a glitch on RTS is a reset pulse on the board. So we write the frame
        and watch the pane's log for the hub's answer instead.
        """
        pane = self.panes.get(key)
        if pane is None:
            return None
        end = time.monotonic() + timeout
        while True:
            with self.lock:
                for seq, _arrival, _stamp, text in reversed(pane.log):
                    if seq <= start:
                        break
                    match = pattern.match(text)
                    if match:
                        return match
                remaining = end - time.monotonic()
            if remaining <= 0:
                return None
            # woken by Pane.add() as soon as the line lands
            with pane.cond:
                pane.cond.wait(min(remaining, 0.05))

    def _ping_hub(self, key: str, cancel) -> bool:
        """'P' must answer 'PONG' - the cheap check that the right port is open."""
        pane = self.panes[key]
        for _attempt in range(3):
            if cancel.is_set():
                return False
            with self.lock:
                start = pane.seq
            if not pane.worker.write(b"P\n"):
                return False
            if self._wait_line(key, RE_PONG, start, hubhost.CMD_TIMEOUT_S):
                return True
        return False

    def _send_frame(self, key: str, addr: int, payload: bytes, cancel) -> bool:
        """One reliable DATA frame: write the S line, wait for its SENT answer."""
        pane = self.panes[key]
        line = (hubhost.build_line("S", addr, payload) + "\n").encode("ascii")
        end = time.monotonic() + hubhost.CMD_RETRY_WINDOW_S
        self.last_answer = None
        while time.monotonic() < end:
            if cancel.is_set():
                return False
            with self.lock:
                start = pane.seq
            if not pane.worker.write(line):
                self.last_answer = "port closed"
                return False
            match = self._wait_line(key, hubhost.RE_SENT, start, hubhost.CMD_TIMEOUT_S)
            if match is not None:
                self.last_answer = match.group(2)
                if int(match.group(1), 16) == addr and self.last_answer == "ok":
                    return True
            else:
                self.last_answer = "no answer"
            # No answer, an ERR line or a fail: the hub is busy or the frame was
            # damaged. A repeat is safe - the tag acknowledges and ignores it.
            time.sleep(hubhost.CMD_RETRY_PAUSE_S)
        return False

    def send(self, addr: int) -> bool:
        with self.lock:
            if self.sending:
                self.status = "a transfer is already running"
                return False
            if self.image is None:
                self.status = "pick an image first"
                return False
            key = self.hub_key()
            pane = self.panes[key]
            port = pane.spec.port
            if not port:
                self.status = "the hub pane has no port set"
                return False
            image = self.image
            fit, dither = self.fit, self.dither

        if not pane.worker.is_open:
            # The user asked for this, so open it rather than refusing - but say so,
            # because opening a port re-applies the modem lines.
            self.open_pane(key)
            if not pane.worker.is_open:
                with self.lock:
                    self.status = f"cannot open {port}: {pane.worker.error or 'unknown error'}"
                return False

        with self.lock:
            self.sending = True
            self.send_to = addr
            self.progress = ""
            self._cancel = threading.Event()
            self.status = f"sending {image.name} to {addr:04X} via {port} ..."
            cancel = self._cancel
        self._event("push", f"{addr:04X}", f"{image.name} ({fit}, {dither})")
        threading.Thread(
            target=self._send_worker,
            args=(key, port, addr, image, fit, dither, cancel),
            name="send-image",
            daemon=True,
        ).start()
        return True

    def cancel(self) -> None:
        with self.lock:
            event = getattr(self, "_cancel", None)
            if not self.sending or event is None:
                return
            event.set()
            self.status = "cancelling after the current frame ..."

    def _send_worker(
        self, key: str, port: str, addr: int, path: Path, fit: str, dither: str, cancel
    ) -> None:
        """Mirrors hubhost.send_image(), with a cancellation check per frame.

        Runs over the port the pane already has open - see _wait_line() for why
        it must not close and reopen it. The frames come from shelfkit.preview,
        the same render the editor showed, so the preview cannot lie.
        """
        ok = False
        rendered = None
        try:
            self.note(key, f"# {path.name} -> {addr:04X} via {port}")

            try:
                from . import preview
            except Exception as exc:  # noqa: BLE001
                self.note(key, f"# previews need Pillow: {exc}")
                return

            try:
                rendered = preview.render(path, fit, dither)
            except Exception as exc:  # noqa: BLE001
                self.note(key, f"# cannot render {path.name}: {exc}")
                return
            self.note(
                key,
                f"# {path.name}: {rendered.source[0]}x{rendered.source[1]}"
                f"{f', rotation {rendered.angle} deg' if rendered.angle else ''}"
                f" -> {rendered.fitted[0]}x{rendered.fitted[1]}, {fit}, {dither}",
            )
            bw, red = rendered.bw, rendered.red

            if not self._ping_hub(key, cancel):
                self.note(key, "# hub did not answer P - right port, hub flashed?")
                return
            frames = list(hubhost.image_messages(bw, red))
            self.note(key, f"# {len(frames)} DATA frames to send")
            for i, frame in enumerate(frames):
                if cancel.is_set():
                    self.note(key, f"# cancelled at frame {i + 1}/{len(frames)}")
                    return
                if not self._send_frame(key, addr, frame, cancel):
                    if cancel.is_set():
                        self.note(key, f"# cancelled at frame {i + 1}/{len(frames)}")
                    else:
                        self.note(
                            key,
                            f"# gave up at frame {i + 1}/{len(frames)} "
                            f"(last hub answer: {self.last_answer})",
                        )
                    return
                with self.lock:
                    self.progress = f"{i + 1}/{len(frames)}"
                if i == 0:
                    cancel.wait(hubhost.BEGIN_SETTLE_S)
                if i % 50 == 0:
                    self.note(key, f"# frame {i}/{len(frames)}")
            cancel.wait(hubhost.END_SETTLE_S)
            if cancel.is_set():
                self.note(key, "# cancelled before the refresh finished")
                return
            ok = True
            self.note(key, f"# {addr:04X} updated")
        except Exception as exc:  # noqa: BLE001 - never leave the bar stuck on Cancel
            self.note(key, f"# send error: {exc}")
            self._event("error", f"{addr:04X}", str(exc)[:120])
        finally:
            with self.lock:
                if ok:
                    self.tag_push[addr] = (path.name, time.time(), rendered.key)
                self.sending = False
                self.send_to = None
                self.progress = ""
                self.status = "image sent" if ok else "not sent - see the log"
            if self.store is not None:
                # Durable: the Fleet row and its thumbnail survive a restart.
                try:
                    if rendered is not None:
                        self.store.put_bitmap(rendered, name=path.name)
                    if ok:
                        self.store.record_push(
                            f"{addr:04X}", path.name, rendered.key if rendered else None
                        )
                except Exception as exc:  # noqa: BLE001 - storage must not break a push
                    self.note(key, f"# storage: {exc}")
                self._event("ok" if ok else "fail", f"{addr:04X}", path.name)


def _split_cursor(value: str | None) -> tuple[int, int]:
    """Parse an "epoch:seq" cursor, tolerating a missing or malformed one."""
    if not value:
        return 0, 0
    epoch, _, seq = str(value).partition(":")
    try:
        return int(epoch), int(seq or 0)
    except ValueError:
        return 0, 0
