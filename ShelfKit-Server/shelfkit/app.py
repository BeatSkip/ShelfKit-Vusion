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
# The tag's identity opcode, from Shared/firmware/shelflink/inc/shelfmsg.h
SM_OP_SET_ID = 7
# Erases the tag's flash and resets it into a fresh random identity
SM_OP_WIPE = 8
# What the tag logs when it has handled one (see Vusion/src/fw_rx.c): "id set 0102"
# or "id set FAILED, ...". The link-layer ACK only proves the frame arrived.
RE_ID_RESULT = re.compile(r"id set (\S+)")
RE_WIPED = re.compile(r"factory reset")
# How long the tag takes to erase its flash after BEGIN (it is busy there, so the
# first chunk would otherwise be lost and need a retry).
FLASH_ERASE_SETTLE_S = 0.6
# How long to wait for the tag's own log line after an identity frame
ID_CONFIRM_S = 6.0
# A flash read-back page: the tag streams it in ~26-byte frames
DUMP_PAGE_TIMEOUT_S = 12.0
DUMP_MAX = 0x10000
REPO_ROOT = Path(__file__).resolve().parents[2]
# Tag ids below this are reserved (0 and 1, the latter being the hub).
FIRST_TAG_ID = 0x0100

IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
)
# A tag announces itself on the hub's UART log as "POLL src=<node id>".
RE_POLL = re.compile(r"^POLL src=([0-9a-fA-F]{4,8})\b")
# the hub prints the tag's supply voltage as vdd=XXXX (volts*256, 3.00 V -> 0x0300)
RE_POLL_VDD = re.compile(r"\bvdd=([0-9a-fA-F]{4})\b")

# Average CR2450 (3 V lithium coin cell): voltage is almost flat until the cell
# is nearly empty, so this is a monotonic estimate, not a coulomb count.
# (voltage, remaining %), linear in between.
CR2450_CURVE = ((3.0, 100), (2.9, 88), (2.8, 72), (2.7, 52), (2.6, 32),
                (2.5, 16), (2.4, 6), (2.3, 0))


def battery_percent(volts: float) -> int:
    """Remaining capacity of an average CR2450, in percent, from its voltage."""
    if volts >= 3.0:
        return 100
    if volts <= 2.3:
        return 0
    for (hi_v, hi_p), (lo_v, lo_p) in zip(CR2450_CURVE, CR2450_CURVE[1:]):
        if lo_v <= volts <= hi_v:
            frac = (hi_v - volts) / (hi_v - lo_v)
            return round(hi_p - frac * (hi_p - lo_p))
    return 0
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
        self.tag_vdd: dict[int, tuple[int, float]] = {}  # addr -> (raw*256, seen_at)
        # name, when, render key (the key lets the Fleet show the frame as a thumb)
        self.tag_push: dict[int, tuple[str, float, str | None]] = {}
        # Editable per tag: alias, notes, and fleet-map position
        self.tag_meta: dict[int, dict] = {}
        self.send_to: int | None = None
        self.last_answer: str | None = None   # the hub's last SENT/ERR answer
        self._ports = (0.0, [])               # (fetched_at, [(device, description)])
        self.dump: dict = {"active": False}    # the last flash read-back
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
                vdd = RE_POLL_VDD.search(text)
                if vdd:
                    self.tag_vdd[addr] = (int(vdd.group(1), 16), time.time())
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
                    "vdd": self._vdd_of(addr, now),
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
                "firmware": self.firmware_candidates(),
                "dump": self.dump,
                "hub_caps": self.hub_capabilities(),
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

    # ── identity ────────────────────────────────────────────────────────────
    def next_tag_id(self) -> int:
        """The lowest free id at or above FIRST_TAG_ID."""
        with self.lock:
            used = set(self.tags)
        candidate = FIRST_TAG_ID
        while candidate in used:
            candidate += 1
        return candidate

    def assign_id(self, addr: int, hex_id: str | None = None) -> dict:
        """Give a tag a new wireless id (SM_OP_SET_ID), and move its record.

        One DATA frame over the hub port the console already has open - the same
        path images and firmware updates use, so nothing is reopened. The tag
        stores the id, reads it back and only then moves its radio address, so a
        successful ACK means the id will still be there after a reset.
        """
        key = self.hub_key()
        pane = self.panes.get(key)
        if pane is None:
            return {"ok": False, "error": "no hub pane"}
        if not pane.worker.is_open:
            return {"ok": False, "error": f"open the {pane.spec.name} port first"}

        if hex_id in (None, ""):
            new = self.next_tag_id()
        else:
            try:
                new = int(str(hex_id).strip().replace("0x", ""), 16)
            except ValueError:
                return {"ok": False, "error": f"{hex_id!r} is not a hex id"}
        if new < 2:
            return {"ok": False, "error": "0 and 1 are reserved (1 is the hub)"}
        if new > 0xFFFF:
            return {"ok": False, "error": "node ids are 16 bits"}
        if new == addr:
            return {"ok": False, "error": f"{new:04X} is already that tag's id"}
        with self.lock:
            if new in self.tags:
                return {"ok": False, "error": f"{new:04X} is in use by another tag"}
        if new >= 0x10000:
            return {"ok": False, "error": "no free id left"}

        payload = bytes([SM_OP_SET_ID, new & 0xFF, new >> 8])
        cancel = threading.Event()
        if not self._ping_hub(key, cancel):
            return {"ok": False, "error": "the hub did not answer P"}
        with self.lock:
            self.status = f"assigning {new:04X} to {addr:04X} ..."
        with self.lock:
            start = self.panes[key].seq
        if not self._send_frame(key, addr, payload, cancel):
            with self.lock:
                self.status = f"{addr:04X} did not acknowledge the id change"
            return {"ok": False, "error": "the tag did not acknowledge"}

        # the ACK only says the frame arrived; the tag stores the record, reads it
        # back and only then moves its radio address. Wait for it to say so.
        answer = self._wait_line(key, RE_ID_RESULT, start, ID_CONFIRM_S)
        if answer is None:
            with self.lock:
                self.status = f"{addr:04X} did not confirm the id change"
            return {"ok": False,
                    "error": "the tag did not confirm - is it awake? see the Console log",
                    "old": f"{addr:04X}", "id": f"{new:04X}"}
        verdict = answer.group(1)
        if verdict.upper().startswith("FAILED"):
            with self.lock:
                self.status = f"{addr:04X} could not store {new:04X}"
            return {"ok": False,
                    "error": f"the tag could not store the id ({verdict}) - see the Console log",
                    "old": f"{addr:04X}", "id": f"{new:04X}"}

        self._rename_tag(addr, new)
        with self.lock:
            self.status = f"{addr:04X} is now {new:04X}"
        self._event("assign", f"{new:04X}", f"was {addr:04X}")
        return {"ok": True, "old": f"{addr:04X}", "id": f"{new:04X}"}

    # ── wireless firmware update ────────────────────────────────────────────
    def firmware_candidates(self) -> list[dict]:
        """The HEX files a tag could be updated with: Release/ newest first."""
        from . import firmware

        found = []
        folder = REPO_ROOT / "Release"
        try:
            files = sorted(folder.glob("*.hex"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            files = []
        for path in files[:12]:
            try:
                stat = path.stat()
            except OSError:
                continue
            found.append({
                "name": path.name,
                "path": str(path),
                "size": stat.st_size,
                "at": round(stat.st_mtime, 1),
                "ok": not path.name.count("-full-"),   # a bundle carries the bootloader
            })
        return found

    def flash_firmware(self, addr: int, path: str) -> dict:
        """Stream a new application to a tag (SM_OP_FW_*), over the hub port.

        The tag stores it in its SPI flash, verifies the CRC and resets; the
        bootloader then programs it and clears the marker. Nothing is opened or
        closed here: it is the port the console already holds.
        """
        from . import firmware

        try:
            image, entry = firmware.check_image(Path(path))
        except firmware.ImageError as exc:
            return {"ok": False, "error": str(exc)}
        key = self.hub_key()
        pane = self.panes.get(key)
        if pane is None:
            return {"ok": False, "error": "no hub pane"}
        if not pane.worker.is_open:
            return {"ok": False, "error": f"open the {pane.spec.name} port first"}
        with self.lock:
            if self.sending:
                return {"ok": False, "error": "another transfer is running"}
            self.sending = True
            self.send_to = addr
            self.progress = ""
            self._cancel = threading.Event()
            self.status = f"flashing {Path(path).name} to {addr:04X} ..."
            cancel = self._cancel
        name = Path(path).name
        self._event("flash", f"{addr:04X}", f"{name} ({len(image)} B)")
        threading.Thread(
            target=self._flash_worker,
            args=(key, addr, image, name, cancel),
            name="flash-firmware",
            daemon=True,
        ).start()
        return {"ok": True, "frames": 2 + (len(image) + firmware.SM_FW_CHUNK - 1) // firmware.SM_FW_CHUNK,
                "entry": f"{entry:04X}", "bytes": len(image)}

    def _flash_worker(self, key: str, addr: int, image: bytes, name: str, cancel) -> None:
        from . import firmware

        total = 2 + (len(image) + firmware.SM_FW_CHUNK - 1) // firmware.SM_FW_CHUNK
        ok = False
        try:
            if not self._ping_hub(key, cancel):
                self.note(key, "# hub did not answer P - right port, hub flashed?")
                return
            self.note(key, f"# firmware {name}: {len(image)} B, {total} frames -> {addr:04X}")
            for index, payload in enumerate(firmware.frames(image), 1):
                if cancel.is_set():
                    self.note(key, f"# cancelled at frame {index}/{total}")
                    return
                if not self._send_frame(key, addr, payload, cancel):
                    if cancel.is_set():
                        self.note(key, f"# cancelled at frame {index}/{total}")
                    else:
                        self.note(key, f"# gave up at frame {index}/{total} "
                                       f"(last hub answer: {self.last_answer})")
                    return
                with self.lock:
                    self.progress = f"{index}/{total}"
                if index == 1:
                    # BEGIN makes the tag erase its flash: give it room before
                    # the first chunk, else that frame just needs a retry
                    cancel.wait(FLASH_ERASE_SETTLE_S)
                elif index % 100 == 0:
                    self.note(key, f"# frame {index}/{total}")
            ok = True
            self.note(key, f"# {addr:04X} has the new firmware, it is resetting")
        except Exception as exc:  # noqa: BLE001 - never leave the bar stuck
            self.note(key, f"# flash error: {exc}")
            self._event("error", f"{addr:04X}", str(exc)[:120])
        finally:
            with self.lock:
                self.sending = False
                self.send_to = None
                self.progress = ""
                self.status = ("firmware sent, the tag is flashing it" if ok
                               else "firmware not sent - see the log")
            self._event("ok" if ok else "fail", f"{addr:04X}", name)

    # ── forgetting tags ─────────────────────────────────────────────────────
    def forget_tags(self, addrs, not_seen_for: float | None = None) -> dict:
        """Delete tags from the server: selected ones, or everything silent for a while.

        Only the server's own bookkeeping goes: aliases, notes, map positions,
        counters, the last frame and the log lines about that id. Nothing is sent
        to the tag - it keeps its wireless id and will show up again as a fresh row
        the next time it polls, which is the point after a mix-up.
        """
        with self.lock:
            now = time.time()
            targets: set[int] = set()
            for value in addrs or []:
                try:
                    targets.add(int(value, 16) if isinstance(value, str) else int(value))
                except (TypeError, ValueError):
                    continue
            if not_seen_for is not None:
                for addr in list(self.tags):
                    seen = self.tag_seen.get(addr)
                    if seen is None or now - seen >= float(not_seen_for):
                        targets.add(addr)
            # never pull the rug out from under a transfer, and only report ids
            # that really were known ("forgot 1" for an unknown id would be a lie)
            for addr in list(targets):
                if self.sending and self.send_to == addr:
                    targets.discard(addr)
            targets &= set(self.tags)
            for addr in targets:
                self.tags.pop(addr, None)
                self.tag_seen.pop(addr, None)
                self.tag_push.pop(addr, None)
                self.tag_meta.pop(addr, None)
            hexes = sorted(f"{addr:04X}" for addr in targets)

        if hexes and self.store is not None:
            self.store.forget_tags(hexes)
        if hexes:
            shown = ", ".join(hexes[:6]) + (f" +{len(hexes) - 6}" if len(hexes) > 6 else "")
            self._event("forget", None, f"{len(hexes)} tag(s): {shown}")
            with self.lock:
                self.status = f"forgot {len(hexes)} tag(s)"
        return {"forgot": len(hexes), "hexes": hexes}

    def hub_capabilities(self) -> dict:
        """What the flashed hub can do, read off its boot banner.

        A hub prints `*** ShelfKit hub, node 0001 net 5a dump=1` when it can forward
        tag DATA payloads, which the flash read-back needs. Without that marker a
        read will relay frames but drop their bytes, so the page says so up front
        instead of failing mysteriously.
        """
        key = self.hub_key()
        pane = self.panes.get(key)
        if pane is None:
            return {"key": key, "dump": None, "banner": None}
        with self.lock:
            lines = [entry[3] for entry in pane.log]
        dump = None
        banner = None
        for line in reversed(lines):
            if "*** ShelfKit hub" in line:
                banner = line.strip()
                dump = "dump=1" in line
                break
        return {"key": key, "dump": dump, "banner": banner}

    # ── flash read-back ─────────────────────────────────────────────────────
    def read_flash(self, addr: int, start: int = 0, length: int = 0x3000) -> dict:
        """Read a range of a tag's SPI flash back over the radio.

        The tag serves one page at a time; each reply frame appears in the hub
        pane's log as `flash=<hex>`, so the bytes are collected from there. Runs
        in a worker: a page takes a few seconds and the page keeps polling.
        """
        from . import flashdump

        if length <= 0 or length > DUMP_MAX or start < 0 or start + length > DUMP_MAX:
            return {"ok": False, "error": f"range 0x{start:X}+{length} is outside the flash"}
        key = self.hub_key()
        pane = self.panes.get(key)
        if pane is None:
            return {"ok": False, "error": "no hub pane"}
        if not pane.worker.is_open:
            return {"ok": False, "error": f"open the {pane.spec.name} port first"}
        with self.lock:
            if self.sending:
                return {"ok": False, "error": "a transfer is running"}
            if self.dump.get("active"):
                return {"ok": False, "error": "a read-back is already running"}
            self.dump = {"active": True, "id": f"{addr:04X}", "start": start,
                         "length": length, "have": 0, "summary": [], "error": None}
            cancel = threading.Event()
            self._dump_cancel = cancel
            self.status = f"reading 0x{start:04X}..0x{start + length - 1:04X} from {addr:04X}"
        self._event("dump", f"{addr:04X}", f"0x{start:04X}+{length}")
        threading.Thread(target=self._dump_worker,
                         args=(key, addr, start, length, cancel),
                         name="flash-read", daemon=True).start()
        return {"ok": True, "start": start, "length": length}

    def _dump_worker(self, key: str, addr: int, start: int, length: int, cancel) -> None:
        from . import flashdump

        pane = self.panes[key]
        lines: list[str] = []
        have: dict[int, bytes] = {}
        error = None
        try:
            if not self._ping_hub(key, cancel):
                error = "the hub did not answer P"
                return
            for page in range(start, start + length, flashdump.PAGE):
                if cancel.is_set():
                    error = "cancelled"
                    return
                want = min(flashdump.PAGE, start + length - page)
                with self.lock:
                    from_seq = pane.seq
                if not self._send_frame(key, addr,
                                        flashdump.request_payload(page, want), cancel):
                    error = f"{addr:04X} did not acknowledge the request for 0x{page:04X}"
                    return
                deadline = time.monotonic() + DUMP_PAGE_TIMEOUT_S + want / 512.0
                got = 0
                relays = 0             # DATA frames from the tag that carried no dump
                while time.monotonic() < deadline and got < want:
                    with self.lock:
                        fresh = [entry for entry in pane.log if entry[0] > from_seq]
                    for seq, _arrival, _stamp, line in fresh:
                        lines.append(line)
                        parsed = flashdump.parse_line(line)
                        if parsed and page <= parsed[1] < page + want:
                            if parsed[1] not in have:
                                have[parsed[1]] = parsed[2]
                                got += len(parsed[2])
                            continue
                        if re.search(rf"DATA src={addr:04x}\b", line):
                            relays += 1
                    if fresh:
                        from_seq = fresh[-1][0]
                    with self.lock:
                        self.dump["have"] = sum(len(chunk) for chunk in have.values())
                    if got < want and not got and relays >= 5:
                        # the tag answered, the hub printed its frame, but the bytes
                        # never made it into the log: an older hub firmware
                        error = ("the hub is dropping the payload - flash the hub with this "
                                 "build: its banner must end in dump=1 and its DATA "
                                 "lines in flash=...")
                        return
                    if got < want:
                        time.sleep(0.05)
                if got < want:
                    error = f"page 0x{page:04X} did not arrive complete ({got}/{want} B)"
                    return
        except Exception as exc:  # noqa: BLE001 - a read must not kill the worker
            error = f"{type(exc).__name__}: {exc}"
        finally:
            data = flashdump.assemble(lines, length, start)
            frames = sum(1 for line in lines if flashdump.parse_line(line))
            # an empty buffer describes nothing: saying "identity: blank" for a read
            # that received no bytes would be a lie, and a harmful one here
            notes = flashdump.summary(data, start, frames) if frames else []
            received = sum(1 for value in data if value != 0xFF)
            result = {"active": False, "ok": error is None, "id": f"{addr:04X}",
                      "start": start, "length": length, "frames": frames,
                      "received": received, "summary": notes, "error": error}
            if frames:                 # a partial dump is still worth keeping
                folder = REPO_ROOT / "ShelfKit-Server" / "data" / "dumps"
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                    base = folder / f"flash-{addr:04X}-{stamp}"
                    base.with_suffix(".bin").write_bytes(bytes(data))
                    base.with_suffix(".txt").write_text(
                        flashdump.hexdump(bytes(data), start), encoding="utf-8")
                    result.update({"bin": base.with_suffix(".bin").name,
                                   "txt": base.with_suffix(".txt").name,
                                   "bin_path": str(base.with_suffix(".bin")),
                                   "txt_path": str(base.with_suffix(".txt"))})
                except OSError as exc:
                    result["error"] = f"saved in memory only: {exc}"
            with self.lock:
                self.dump = result
                self.status = (f"read 0x{start:04X}+{length} from {addr:04X}" if error is None
                               else f"read failed: {error}")
            self._event("ok" if error is None else "fail", f"{addr:04X}", "flash read")

    def dump_file(self, kind: str) -> Path | None:
        """The last read-back's .bin or .txt, for the download links."""
        with self.lock:
            path = self.dump.get(f"{kind}_path")
        return Path(path) if path else None

    def service_image(self, addr: int, note: str | None = None,
                      alias: str | None = None) -> dict:
        """Draw this tag's service label and push it over the air.

        The label carries what a tag in hand needs to be identified: the node id,
        the alias and a note (the tag's stored note unless one is given). It is
        generated at panel size, so it is rendered with fit=stretch and
        dither=threshold - dithering text makes it illegible - and pushed through
        the same wireless path as any other image. The hub port is the only serial
        link involved, and the tag needs nothing plugged in.
        """
        from . import service_image

        with self.lock:
            meta = self.tag_meta.get(addr) or {}
            used_alias = alias if alias is not None else meta.get("alias")
            used_note = note if note is not None else meta.get("notes")
        used_note = (used_note or "").strip()

        path = REPO_ROOT / "ShelfKit-Server" / "data" / "service" / f"service-{addr:04X}.png"
        try:
            service_image.write(path, addr, used_alias, used_note)
        except Exception as exc:  # noqa: BLE001 - Pillow or font trouble
            return {"ok": False, "error": f"cannot draw the label: {exc}"}

        if not self.send(addr, fit="stretch", dither="threshold", image_path=str(path)):
            return {"ok": False, "error": self.status, "image": str(path)}
        return {"ok": True, "id": f"{addr:04X}", "alias": used_alias,
                "note": used_note, "image": str(path)}

    def factory_reset(self, addr: int) -> dict:
        """Wipe a tag's flash and let it come back as a new tag (SM_OP_WIPE).

        Useful when a tag carries an identity that should never have existed: it
        erases the identity record, the pending update marker and the image
        window, resets, and then generates a fresh random id. The server's row for
        the old id is dropped, because that id will not be heard again.
        """
        key = self.hub_key()
        pane = self.panes.get(key)
        if pane is None:
            return {"ok": False, "error": "no hub pane"}
        if not pane.worker.is_open:
            return {"ok": False, "error": f"open the {pane.spec.name} port first"}
        if self.sending and self.send_to == addr:
            return {"ok": False, "error": "a transfer to that tag is running"}
        cancel = threading.Event()
        if not self._ping_hub(key, cancel):
            return {"ok": False, "error": "the hub did not answer P"}
        with self.lock:
            self.status = f"factory resetting {addr:04X} ..."
        with self.lock:
            start = self.panes[key].seq
        if not self._send_frame(key, addr, bytes([SM_OP_WIPE]), cancel):
            return {"ok": False, "error": "the tag did not acknowledge"}
        if self._wait_line(key, RE_WIPED, start, ID_CONFIRM_S) is None:
            return {"ok": False, "error": "the tag did not confirm the reset - see the Console log"}
        # the row goes first: forgetting a tag also drops its log lines, and the
        # record of the wipe itself should survive that
        self.forget_tags([addr])
        self._event("wipe", f"{addr:04X}", "factory reset")
        with self.lock:
            self.status = f"{addr:04X} wiped, it will come back with a new id"
        return {"ok": True, "old": f"{addr:04X}"}

    def _vdd_of(self, addr: int, now: float) -> dict | None:
        """The last reported supply voltage, or None if none has arrived yet."""
        pair = self.tag_vdd.get(addr)
        if pair is None:
            return None
        raw, seen_at = pair
        volts = round(raw / 256.0, 2)
        return {"raw": raw, "volts": volts, "percent": battery_percent(volts),
                "age": round(now - seen_at, 1)}

    def _rename_tag(self, old: int, new: int) -> None:
        """Re-key every in-memory table and the stored row after an assignment."""
        with self.lock:
            for table in (self.tags, self.tag_seen, self.tag_push, self.tag_meta):
                if old in table:
                    table[new] = table.pop(old)
        if self.store is not None:
            self.store.rename_tag(f"{old:04X}", f"{new:04X}")

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

    def send(self, addr: int, fit: str | None = None, dither: str | None = None,
             image_path: str | None = None) -> bool:
        with self.lock:
            if self.sending:
                self.status = "a transfer is already running"
                return False
            image = Path(image_path) if image_path else self.image
            if image is None:
                self.status = "pick an image first"
                return False
            key = self.hub_key()
            pane = self.panes[key]
            port = pane.spec.port
            if not port:
                self.status = "the hub pane has no port set"
                return False
            fit = fit or self.fit
            dither = dither or self.dither

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
