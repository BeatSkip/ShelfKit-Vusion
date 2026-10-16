#!/usr/bin/env python3
"""monitor.py - two UARTs side by side, plus image push to a tag.

Opens two serial ports and gives each one its own half of the screen, with its
own baud rate, open/close and DTR/RTS controls, so two boards (hub and tag) can
be watched in real time:

    python tooling/hub/monitor.py hub=COM4 tag=COM3
    python tooling/hub/monitor.py hub=COM4            # second pane stays free
    python tooling/hub/monitor.py --baud 115200 hub=COM4 tag=COM3
    python tooling/hub/monitor.py --list

Ports named on the command line are opened at startup. Ports only picked up
from the auto-detected list are pre-filled but left closed, so the tool never
grabs a port you did not ask for.

The top bar pushes an image to one tag. [Browse...] picks an image, the tag list
is every node id that announced itself with a "POLL src=<id>" line on the hub
pane, and [Send] drives the hub's command channel through tooling/hubhost.py. A
serial port cannot be shared, so the hub pane's port is closed for the transfer
and reopened afterwards, and [Send] turns into [Cancel] while one runs. The
rotation is picked to fit the panel rather than assumed: a 296x152 landscape
source is rotated 90, a 152x296 portrait one is used as it is, and the angle is
logged. Only an image that fits neither way is refused (resize the source);
dithering stays off, as in hubhost.py.

Both handshake lines start RELEASED (DTR low, RTS low). On this tag DTR is the
BOOT pin and RTS is the RESET line, so that is the state which neither resets
the board nor drops it into the bootloader. Per pane, "DTR (boot)" is a level
toggle and "Reset" is a push button that pulses RTS for 100 ms. "Copy logs" puts
both logs, merged by arrival time, on the clipboard.

Lines are shown with a millisecond timestamp and decoded as latin-1, matching
tooling/monitor.py; 8N1 is assumed. Any pyserial URL works as a port name too
("loop://", "socket://host:port"), which is handy for testing without hardware.

Requires: pyserial and textual  (pip install -r tooling/hub/requirements.txt)
"""

from __future__ import annotations

import argparse
import queue
import re
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - environment check
    sys.exit("pyserial is required:  pip install pyserial")

try:
    from textual import on, work
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.screen import ModalScreen
    from textual.widgets import (
        Button,
        DirectoryTree,
        Footer,
        Header,
        Input,
        Label,
        RichLog,
        Select,
        Static,
    )
except ImportError:  # pragma: no cover - environment check
    sys.exit("textual is required:  pip install textual")

# hubhost.py owns the hub command channel and the image framing; png2epd.py does
# the actual conversion. Both live in tooling/, one level up from this file.
TOOLING_DIR = Path(__file__).resolve().parent.parent
if str(TOOLING_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLING_DIR))
try:
    import hubhost
except ImportError:  # pragma: no cover - environment check
    sys.exit(f"hubhost.py not found (expected next to this tool, in {TOOLING_DIR})")

DEFAULT_BAUD = 38400
READ_TIMEOUT_S = 0.05
UI_TICK_S = 0.05
TAG_REFRESH_S = 1.0
MAX_LOG_LINES = 5000
MAX_LINES_PER_TICK = 200
RESET_PULSE_S = 0.1  # how long the momentary Reset button holds RTS asserted

# Image push defaults. SEND_ROTATE is only a preference: png2epd.fit_rotation()
# falls back to the angle that actually fits the panel (a 152x296 portrait source
# needs 0, not 90), and the angle used is logged.
SEND_ROTATE = 90
SEND_DITHER = False
IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
)
# A tag announces itself on the hub's UART log as "POLL src=<node id>".
RE_POLL = re.compile(r"^POLL src=([0-9a-fA-F]{4,8})\b")


@dataclass
class PortSpec:
    """One pane's device: a display name, the port and the line speed."""

    name: str
    port: str
    baud: int = DEFAULT_BAUD


def _set_line(ser, line: str, value: bool) -> bool:
    """Set DTR/RTS, tolerating adapters and URL handlers that refuse it.

    NotImplementedError is in the list because pyserial's virtual ports
    (loop://, socket://) implement no modem-control lines at all.
    """
    try:
        setattr(ser, line, value)
        return True
    except (OSError, ValueError, NotImplementedError, serial.SerialException):
        return False


def _make_serial(spec: PortSpec):
    """A configured but not yet opened port. Accepts pyserial URLs as well."""
    if "://" in spec.port:
        return serial.serial_for_url(
            spec.port,
            do_not_open=True,
            baudrate=spec.baud,
            timeout=READ_TIMEOUT_S,
            write_timeout=0.5,
            dsrdtr=False,
            rtscts=False,
        )
    ser = serial.Serial()
    ser.port = spec.port
    ser.baudrate = spec.baud
    ser.timeout = READ_TIMEOUT_S
    ser.write_timeout = 0.5
    # Keep the handshake lines ours: never let the driver auto-drive them.
    ser.dsrdtr = False
    ser.rtscts = False
    return ser


def _stamp() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _native_clipboard(text: str) -> bool:
    """Write to the OS clipboard, in addition to Textual's terminal copy.

    Textual copies with the OSC 52 escape sequence, which some terminals ignore
    (and Windows Terminal gates behind a setting), so the platform tools are the
    reliable path where they exist. Returns True if one of them accepted it.
    """
    if sys.platform == "win32":
        # clip.exe with UTF-16LE: Unicode-safe whatever the console code page is,
        # and unlike plain "utf-16" it adds no BOM, which would otherwise be
        # pasted as a stray U+FEFF at the start of the text.
        attempts = [(["clip"], "utf-16-le")]
    elif sys.platform == "darwin":
        attempts = [(["pbcopy"], "utf-8")]
    else:
        attempts = [
            (["wl-copy"], "utf-8"),
            (["xclip", "-selection", "clipboard"], "utf-8"),
            (["xsel", "--clipboard", "--input"], "utf-8"),
        ]
    for command, encoding in attempts:
        try:
            done = subprocess.run(
                command,
                input=text.encode(encoding),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except (OSError, ValueError):
            continue
        if done.returncode == 0:
            return True
    return False


class SerialWorker:
    """Owns one serial port plus its reader thread; safe to drive from the UI."""

    def __init__(self, spec: PortSpec) -> None:
        self.spec = spec
        self.ser = None
        self.lines: queue.Queue[str] = queue.Queue()
        self.error: str | None = None
        self.rx_bytes = 0
        self.rx_lines = 0
        # DTR = BOOT pin, RTS = RESET line. Released = False, for both.
        self.dtr = False
        self.rts = False
        self.lost = False
        # Node ids announced on this port ("POLL src=<id>"), with a count of how
        # many announcements were seen. Only ever written by the reader thread.
        self.tags: dict[int, int] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ── lifecycle ──────────────────────────────────────────────────────────
    @property
    def is_open(self) -> bool:
        return bool(self.ser is not None and self.ser.is_open)

    @property
    def status(self) -> str:
        if self.error:
            return f"error: {self.error}"
        if not self.is_open:
            return "closed"
        if self.lost:
            return "port lost"
        return f"open @ {self.spec.baud} 8N1"

    def open(self) -> None:
        if self.is_open:
            return
        self.error = None
        self.lost = False
        self._stop.clear()

        try:
            ser = _make_serial(self.spec)
        except (serial.SerialException, OSError, ValueError) as exc:
            self.error = str(exc)
            return
        # Best effort before open(): keeps the lines released from the start.
        _set_line(ser, "dtr", self.dtr)
        _set_line(ser, "rts", self.rts)
        try:
            ser.open()
        except (serial.SerialException, OSError, ValueError) as exc:
            self.error = str(exc)
            return

        self.ser = ser
        self._apply_lines()  # re-assert now the port is really open
        self._thread = threading.Thread(
            target=self._reader, name=f"rx-{self.spec.name}", daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.0)
        ser, self.ser = self.ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:  # noqa: BLE001 - closing must never raise at the UI
                pass

    # ── handshake lines ────────────────────────────────────────────────────
    def _apply_lines(self) -> None:
        if self.ser is None:
            return
        for line in ("dtr", "rts"):
            if not _set_line(self.ser, line, getattr(self, line)):
                self.error = f"{line.upper()} could not be set"

    def set_line(self, line: str, value: bool) -> None:
        """Drive DTR or RTS. Ignored (with a message) while the port is closed."""
        if not self.is_open:
            self.error = f"{line.upper()} needs an open port"
            return
        self.error = None
        setattr(self, line, value)
        self._apply_lines()

    def toggle(self, line: str) -> None:
        """Flip a line and leave it there - used for DTR, the level-held BOOT pin.

        RTS is not toggled: it is pulsed by DevicePane._pulse_reset(), because a
        reset line left asserted holds the board in reset.
        """
        self.set_line(line, not getattr(self, line))

    # ── reading ────────────────────────────────────────────────────────────
    def _reader(self) -> None:
        ser = self.ser
        buf = bytearray()
        while not self._stop.is_set():
            try:
                chunk = ser.read(ser.in_waiting or 1)
            except (serial.SerialException, OSError, TypeError) as exc:
                self.error = str(exc)
                self.lost = True
                break
            if not chunk:
                continue
            self.rx_bytes += len(chunk)
            buf += chunk
            while b"\n" in buf:
                raw, _, rest = bytes(buf).partition(b"\n")
                buf = bytearray(rest)
                self._emit(raw)
        if buf:  # a trailing line without a newline is still worth showing
            self._emit(bytes(buf))

    def _emit(self, raw: bytes) -> None:
        text = raw.decode("latin-1", "replace").rstrip("\r")
        if not text:
            return
        self.rx_lines += 1
        match = RE_POLL.match(text)
        if match:
            addr = int(match.group(1), 16)
            self.tags[addr] = self.tags.get(addr, 0) + 1
        self.lines.put(text)


class DevicePane(Vertical):
    """One half of the split: port controls on top, UART log below."""

    def __init__(self, worker: SerialWorker, key: str) -> None:
        super().__init__(id=f"pane-{key}")
        self.worker = worker
        self.key = key
        self._shown: dict[str, object] = {}
        # (arrived at, timestamp shown, text) for the clipboard copy. Kept
        # separately from RichLog because that stores *wrapped* display strips,
        # so reading it back would split long log lines in two.
        self.history: deque[tuple[float, str, str]] = deque(maxlen=MAX_LOG_LINES)

    def compose(self) -> ComposeResult:
        spec = self.worker.spec
        with Horizontal(classes="toolbar"):
            yield Label(spec.name, classes="device")
            yield Input(value=spec.port, placeholder="COM4", id=f"port-{self.key}", classes="port")
            yield Input(
                value=str(spec.baud),
                placeholder=str(DEFAULT_BAUD),
                type="integer",
                id=f"baud-{self.key}",
                classes="baud",
            )
            yield Button("Open", id=f"open-{self.key}", variant="primary", compact=True)
            yield Button("Clear", id=f"clear-{self.key}", compact=True)
        with Horizontal(classes="lines"):
            yield Button("DTR (boot): off", id=f"dtr-{self.key}", compact=True)
            yield Button(
                "Reset",
                id=f"reset-{self.key}",
                compact=True,
                tooltip=f"Momentary reset: assert RTS for {RESET_PULSE_S * 1000:.0f} ms",
            )
            yield Static("closed", id=f"status-{self.key}", classes="status")
        yield RichLog(
            id=f"log-{self.key}",
            max_lines=MAX_LOG_LINES,
            wrap=True,
            highlight=False,
            markup=False,
        )

    def on_mount(self) -> None:
        self.set_interval(UI_TICK_S, self._tick)

    # ── UI refresh ─────────────────────────────────────────────────────────
    def write_line(self, text: str) -> None:
        """Append a line to this pane's log (e.g. a startup note)."""
        self.query_one(f"#log-{self.key}", RichLog).write(text)
        self._remember(_stamp(), text)

    def _tick(self) -> None:
        log = self.query_one(f"#log-{self.key}", RichLog)
        for _ in range(MAX_LINES_PER_TICK):
            try:
                line = self.worker.lines.get_nowait()
            except queue.Empty:
                break
            stamp = _stamp()
            log.write(f"[{stamp}] {line}")
            self._remember(stamp, line)
        self._refresh()

    def _refresh(self) -> None:
        worker = self.worker
        open_btn = self.query_one(f"#open-{self.key}", Button)
        self._set(open_btn, "label", "Close" if worker.is_open else "Open")
        self._set(open_btn, "variant", "error" if worker.is_open else "primary")

        # Only DTR is a held level, so only it has a state to show; Reset is
        # momentary and always ends released.
        dtr_btn = self.query_one(f"#dtr-{self.key}", Button)
        self._set(dtr_btn, "label", f"DTR (boot): {'on' if worker.dtr else 'off'}")
        self._set(dtr_btn, "variant", "warning" if worker.dtr else "default")

        status = self.query_one(f"#status-{self.key}", Static)
        status.update(f"{worker.status}   rx {worker.rx_bytes} B / {worker.rx_lines} lines")

    def _remember(self, stamp: str, text: str) -> None:
        self.history.append((time.time(), stamp, text))

    # ── reset ──────────────────────────────────────────────────────────────
    def _pulse_reset(self) -> None:
        """Assert RTS, then release it a moment later.

        A push button, not a toggle: leaving RTS asserted would hold the board in
        reset for as long as the button stayed "on", so the release is scheduled
        rather than waiting for a second click.
        """
        if not self.worker.is_open:
            self.worker.error = "reset needs an open port"
            return
        self.worker.set_line("rts", True)
        # Schedule the release whatever happened above: RTS must never be left
        # asserted, and the state flag has to come back down either way.
        self.set_timer(RESET_PULSE_S, self._release_reset)
        if self.worker.error:
            self.write_line(f"# reset not sent: {self.worker.error}")
        else:
            self.write_line(f"# reset pulsed ({RESET_PULSE_S * 1000:.0f} ms)")

    def _release_reset(self) -> None:
        self.worker.set_line("rts", False)

    def _set(self, widget, attribute: str, value) -> None:
        """Assign only on change - these are refreshed 20 times a second."""
        cache_key = f"{widget.id}.{attribute}"
        if self._shown.get(cache_key) != value:
            self._shown[cache_key] = value
            setattr(widget, attribute, value)

    # ── events ─────────────────────────────────────────────────────────────
    @on(Button.Pressed)
    def _on_pressed(self, event: Button.Pressed) -> None:
        kind, _, key = (event.button.id or "").partition("-")
        if key != self.key:
            return
        event.stop()
        if kind == "open":
            self._toggle_open()
        elif kind == "clear":
            self.query_one(f"#log-{self.key}", RichLog).clear()
        elif kind == "dtr":
            self.worker.toggle("dtr")
        elif kind == "reset":
            self._pulse_reset()
        self._refresh()

    def _toggle_open(self) -> None:
        worker = self.worker
        if worker.is_open:
            worker.close()
            self.write_line(f"# closed {worker.spec.port}")
            return

        port = self.query_one(f"#port-{self.key}", Input).value.strip()
        raw_baud = self.query_one(f"#baud-{self.key}", Input).value.strip()
        if not port:
            worker.error = "no port name"
            return
        try:
            baud = int(raw_baud) if raw_baud else DEFAULT_BAUD
        except ValueError:
            worker.error = f"bad baud rate {raw_baud!r}"
            return

        worker.spec.port, worker.spec.baud = port, baud
        worker.open()
        if worker.is_open:
            self.write_line(f"# opened {port} @ {baud} 8N1  (DTR/RTS released)")
        elif worker.error:
            self.write_line(f"# {port}: {worker.error}")


def _selected_tag(select: Select) -> int | None:
    """The node id currently chosen in a Select, or None when nothing is picked.

    Select.BLANK is the bool False and Select.NULL is None - and isinstance(False,
    int) is True - so a plain isinstance() test would read "nothing selected" as
    node 0 and happily send the image there.
    """
    value = select.value
    if value is Select.BLANK or value is Select.NULL or isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _default_image_dir() -> Path:
    """Where the picker opens: the repo's image folders, else the cwd."""
    repo_resources = Path(__file__).resolve().parent.parent.parent / "Resources"
    for candidate in (Path.cwd() / "Resources", Path.cwd() / "images", repo_resources):
        if candidate.is_dir():
            return candidate
    return Path.cwd()


class ImageTree(DirectoryTree):
    """DirectoryTree that shows only folders and image files."""

    def filter_paths(self, paths):
        keep = []
        for path in paths:
            try:
                if path.is_dir() or path.suffix.lower() in IMAGE_SUFFIXES:
                    keep.append(path)
            except OSError:  # unreadable entry - just leave it out
                continue
        return keep


class ImagePickerScreen(ModalScreen[Path | None]):
    """Modal browser for the image to push."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, start: Path) -> None:
        super().__init__()
        self.start = start if start.is_dir() else Path.cwd()

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Label(
                "Pick an image to send   (enter on a file, or type a path below)",
                classes="picker-title",
            )
            yield Input(
                value=str(self.start), placeholder="path to an image file", id="picker-path"
            )
            yield ImageTree(str(self.start), id="picker-tree")
            with Horizontal(id="picker-buttons"):
                yield Button("Use this file", id="picker-ok", variant="primary")
                yield Button("Cancel", id="picker-cancel")

    @on(DirectoryTree.FileSelected)
    def _file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()
        self.dismiss(event.path)

    @on(Button.Pressed, "#picker-ok")
    def _confirm(self) -> None:
        raw = self.query_one("#picker-path", Input).value.strip()
        self.dismiss(Path(raw) if raw else None)

    @on(Button.Pressed, "#picker-cancel")
    def _dismiss(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TwoPortApp(App[None]):
    """Left/right UART monitor with an image-push bar."""

    TITLE = "two-port UART monitor"
    SUB_TITLE = "ShelfKit"
    BINDINGS = [("q", "quit", "Quit")]
    CSS = """
    #imagebar { height: auto; background: $panel; padding: 0 1; }
    #imagebar .device { width: auto; padding: 0 1 0 0; text-style: bold; }
    #imagebar #image-name { width: 1fr; }
    #imagebar #tag-select { width: 28; }
    #imagebar #send-status { width: 1fr; text-align: right; color: $text-muted; }
    #split { height: 1fr; }
    DevicePane {
        width: 1fr;
        height: 1fr;
        border: round $primary;
        padding: 0 1;
    }
    DevicePane .toolbar, DevicePane .lines { height: auto; }
    DevicePane .device { width: auto; padding: 0 1 0 0; text-style: bold; }
    DevicePane Input.port { width: 1fr; }
    DevicePane Input.baud { width: 9; }
    DevicePane .status { width: 1fr; text-align: right; color: $text-muted; }
    DevicePane RichLog { height: 1fr; border-top: solid $panel; }
    ImagePickerScreen { align: center middle; }
    #picker {
        width: 80%;
        height: 80%;
        border: round $primary;
        background: $surface;
        padding: 0 1;
    }
    #picker .picker-title { width: 1fr; text-style: bold; }
    #picker Input { width: 1fr; }
    #picker ImageTree { height: 1fr; border: solid $panel; }
    #picker #picker-buttons { height: auto; }
    """

    def __init__(self, specs: list[PortSpec], auto_open: bool) -> None:
        super().__init__()
        self.devices = [SerialWorker(spec) for spec in specs]
        self.keys = [_key(spec.name, i) for i, spec in enumerate(specs)]
        self.auto_open = auto_open
        self.image_path: Path | None = None
        self._tag_values: tuple[int, ...] = ()
        self._sending = False
        self._cancel_send = threading.Event()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="imagebar"):
            yield Label("Image", classes="device")
            yield Static("(none)", id="image-name")
            yield Button("Browse...", id="browse", compact=True)
            yield Label("Tag", classes="device")
            yield Select([], prompt="no tags heard yet", allow_blank=True, id="tag-select")
            yield Button("Send", id="send", variant="success", compact=True)
            yield Button("Copy logs", id="copy-logs", compact=True)
            yield Static("", id="send-status")
        with Horizontal(id="split"):
            for worker, key in zip(self.devices, self.keys):
                yield DevicePane(worker, key)
        yield Footer()

    def on_mount(self) -> None:
        found = list_ports.comports()
        listing = ", ".join(f"{p.device} ({p.description})" for p in found) or "none detected"
        for worker, key in zip(self.devices, self.keys):
            pane = self.query_one(f"#pane-{key}", DevicePane)
            pane.write_line(f"# serial ports: {listing}")
            pane.write_line(
                f"# {worker.spec.name} -> {worker.spec.port or '(none)'} @ {worker.spec.baud}"
            )
            if self.auto_open and worker.spec.port:
                worker.open()
                if worker.is_open:
                    pane.write_line(f"# opened {worker.spec.port}  (DTR/RTS released)")
                elif worker.error:
                    pane.write_line(f"# {worker.spec.port}: {worker.error}")
        self.set_interval(TAG_REFRESH_S, self._refresh_tags)

    def on_unmount(self) -> None:
        self._cancel_send.set()  # let an in-flight transfer stop at the next frame
        for worker in self.devices:
            worker.close()

    # ── image bar ──────────────────────────────────────────────────────────
    def _status(self, text: str) -> None:
        self.query_one("#send-status", Static).update(text)

    def _note(self, key: str, text: str) -> None:
        self.query_one(f"#pane-{key}", DevicePane).write_line(text)
        self._status(text.lstrip("#").strip())

    def _ui_note(self, key: str, text: str) -> None:
        """_note() called from the transfer thread."""
        try:
            self.call_from_thread(self._note, key, text)
        except Exception:  # noqa: BLE001 - the app may be shutting down
            pass

    def _device_for(self, key: str) -> SerialWorker:
        return self.devices[self.keys.index(key)]

    def _hub_key(self) -> str:
        """The pane whose port talks to the tags: the one named 'hub', else the
        first that has heard an announcement, else the first pane."""
        for key, worker in zip(self.keys, self.devices):
            if worker.spec.name.strip().lower() == "hub":
                return key
        for key, worker in zip(self.keys, self.devices):
            if worker.tags:
                return key
        return self.keys[0]

    def _heard_tags(self) -> dict[int, int]:
        merged: dict[int, int] = {}
        for worker in self.devices:
            for addr, count in worker.tags.items():
                merged[addr] = merged.get(addr, 0) + count
        return merged

    def _refresh_tags(self) -> None:
        tags = self._heard_tags()
        values = tuple(sorted(tags))
        if values == self._tag_values:
            return
        self._tag_values = values
        select = self.query_one("#tag-select", Select)
        previous = _selected_tag(select)
        select.set_options([(f"{addr:04X}   ({tags[addr]} polls)", addr) for addr in values])
        if previous is not None and previous in values:
            select.value = previous  # keep the user's choice across a refresh

    # ── clipboard ──────────────────────────────────────────────────────────
    def _combined_log(self) -> str:
        """Both panes' lines merged by arrival time, as one copyable block."""
        rows: list[tuple[float, str]] = []
        for key, worker in zip(self.keys, self.devices):
            pane = self.query_one(f"#pane-{key}", DevicePane)
            for arrived, stamp, text in pane.history:
                rows.append((arrived, f"[{stamp} {worker.spec.name}] {text}"))
        rows.sort(key=lambda row: row[0])  # stable, so equal times keep pane order
        ports = ", ".join(f"{w.spec.name}={w.spec.port or '?'}" for w in self.devices)
        header = (
            f"=== ShelfKit two-port log: {ports} - {len(rows)} lines, "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ==="
        )
        return "\n".join([header, *(line for _, line in rows)])

    @on(Button.Pressed, "#copy-logs")
    def _on_copy_logs(self) -> None:
        text = self._combined_log()
        lines = text.count("\n")
        if not lines:
            self._status("nothing logged yet")
            return
        reached = []
        try:
            self.copy_to_clipboard(text)  # terminal clipboard (OSC 52)
            reached.append("terminal")
        except Exception:  # noqa: BLE001 - not every driver supports it
            pass
        if _native_clipboard(text):  # and the OS one, where a tool exists
            reached.append("system")
        self._status(
            f"copied {lines} lines ({' + '.join(reached)})"
            if reached
            else f"no clipboard available - {lines} lines not copied"
        )

    @on(Button.Pressed, "#browse")
    def _on_browse(self) -> None:
        def chosen(path: Path | None) -> None:
            if path is None:
                return
            if not path.is_file():
                self._status(f"{path} is not a file")
                return
            self.image_path = path
            self.query_one("#image-name", Static).update(path.name)
            self._status(str(path))

        self.push_screen(ImagePickerScreen(_default_image_dir()), chosen)

    @on(Button.Pressed, "#send")
    def _on_send(self) -> None:
        if self._sending:
            self._cancel_send.set()
            self._status("cancelling after the current frame ...")
            return
        if self.image_path is None:
            self._status("pick an image first")
            return
        addr = _selected_tag(self.query_one("#tag-select", Select))
        if addr is None:
            self._status("no tag selected - wait for a POLL announcement")
            return
        key = self._hub_key()
        port = self._device_for(key).spec.port
        if not port:
            self._status("the hub pane has no port set")
            return

        self._cancel_send.clear()
        self._set_sending(True)
        self._status(f"sending {self.image_path.name} to {addr:04X} via {port} ...")
        self._send_task(key, port, addr, self.image_path)

    def _set_sending(self, sending: bool) -> None:
        self._sending = sending
        button = self.query_one("#send", Button)
        button.label = "Cancel" if sending else "Send"
        button.variant = "warning" if sending else "success"

    def _finish(self, ok: bool) -> None:
        self._set_sending(False)
        self._status("image sent" if ok else "not sent - see the log")

    @work(thread=True, exclusive=True, group="send")
    def _send_task(self, key: str, port: str, addr: int, path: Path) -> None:
        """Mirrors hubhost.send_image(), with a cancellation check per frame."""
        worker = self._device_for(key)
        was_open = worker.is_open
        ok = False
        try:
            if was_open:
                worker.close()  # one serial port cannot serve two owners
                time.sleep(0.2)
            self._ui_note(key, f"# {path.name} -> {addr:04X} via {port}")

            try:
                import png2epd  # tooling/ is already on sys.path
            except SystemExit as exc:  # png2epd exits when Pillow is missing
                self._ui_note(key, f"# {exc.code or 'png2epd is unavailable'}")
                return
            except Exception as exc:  # noqa: BLE001
                self._ui_note(key, f"# cannot load png2epd: {exc}")
                return

            # png2epd.load_planes() rotates first and only then checks the size,
            # so a portrait source fails at the usual 90 degrees. Ask which angle
            # actually fits instead of assuming one.
            try:
                angle, source, fitted = png2epd.fit_rotation(path, SEND_ROTATE)
            except Exception as exc:  # noqa: BLE001
                self._ui_note(key, f"# cannot read {path.name}: {exc}")
                return
            if angle is None:
                self._ui_note(
                    key,
                    f"# rejected: {path.name} is {source[0]}x{source[1]} and no rotation "
                    f"gives {png2epd.PANEL_W}x{png2epd.PANEL_H} - resize the source",
                )
                return
            if angle != SEND_ROTATE:
                self._ui_note(
                    key,
                    f"# {path.name} is {source[0]}x{source[1]}; using rotation {angle} deg "
                    f"({fitted[0]}x{fitted[1]}), not {SEND_ROTATE}",
                )
            else:
                self._ui_note(key, f"# {path.name} -> {fitted[0]}x{fitted[1]}, rotation {angle} deg")

            try:
                bw, red = hubhost.planes_for(path, angle, SEND_DITHER)
            except SystemExit as exc:  # load_planes still exits on a bad size
                self._ui_note(key, f"# rejected: {exc.code or 'bad image'}")
                return
            except Exception as exc:  # noqa: BLE001
                self._ui_note(key, f"# cannot convert {path.name}: {exc}")
                return

            try:
                hub = hubhost.Hub(port)
            except Exception as exc:  # noqa: BLE001
                self._ui_note(key, f"# cannot open {port}: {exc}")
                return
            try:
                if not hub.ping():
                    self._ui_note(key, "# hub did not answer P - right port, hub flashed?")
                    return
                frames = list(hubhost.image_messages(bw, red))
                self._ui_note(key, f"# {len(frames)} DATA frames to send")
                for i, frame in enumerate(frames):
                    if self._cancel_send.is_set():
                        self._ui_note(key, f"# cancelled at frame {i + 1}/{len(frames)}")
                        return
                    if not hub.send_data(addr, frame):
                        self._ui_note(
                            key,
                            f"# gave up at frame {i + 1}/{len(frames)} "
                            f"(last hub answer: {hub.last_result})",
                        )
                        return
                    if i == 0:
                        self._cancel_send.wait(hubhost.BEGIN_SETTLE_S)
                    if i % 50 == 0:
                        self._ui_note(key, f"# frame {i}/{len(frames)}")
                self._cancel_send.wait(hubhost.END_SETTLE_S)
                if self._cancel_send.is_set():
                    self._ui_note(key, "# cancelled before the refresh finished")
                    return
                ok = True
                self._ui_note(key, f"# {addr:04X} updated")
            finally:
                try:
                    hub.ser.close()
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001 - never leave the bar stuck on Cancel
            self._ui_note(key, f"# send error: {exc}")
        finally:
            if was_open:
                worker.open()
                self._ui_note(key, f"# {port} reopened")
            try:
                self.call_from_thread(self._finish, ok)
            except Exception:  # noqa: BLE001
                pass


def _key(name: str, index: int) -> str:
    """A widget-id-safe pane key derived from the device name."""
    safe = "".join(ch for ch in name.lower() if ch.isalnum())
    return safe or chr(ord("a") + index)


def build_specs(ports: list[str], baud: int) -> tuple[list[PortSpec], bool]:
    """Two panes from CLI arguments; returns (specs, whether to open at startup)."""
    detected = [p.device for p in list_ports.comports()]
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
    ap.add_argument("--list", action="store_true", help="list serial ports and exit")
    args = ap.parse_args(argv)

    if args.list:
        for port in list_ports.comports():
            print(f"{port.device}  {port.description}")
        return 0
    if len(args.ports) > 2:
        ap.error("this tool opens exactly two ports")

    specs, auto_open = build_specs(args.ports, args.baud)
    TwoPortApp(specs, auto_open).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
