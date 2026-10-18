"""Serial ports and their reader threads - no UI in here.

One `SerialWorker` owns one port and one reader thread. Every complete line the
board prints is handed to a callback, so whatever is displaying it (the web UI)
does not have to poll a queue.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

import serial
from serial.tools import list_ports

DEFAULT_BAUD = 38400
READ_TIMEOUT_S = 0.05


@dataclass
class PortSpec:
    """One pane's device: a display name, the port and the line speed."""

    name: str
    port: str
    baud: int = DEFAULT_BAUD


def available_ports() -> list[tuple[str, str]]:
    """(device, description) for everything pyserial can see, for the pickers."""
    return [(p.device, p.description or "") for p in list_ports.comports()]


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


class SerialWorker:
    """Owns one serial port plus its reader thread; safe to drive from a request."""

    def __init__(self, spec: PortSpec, on_line: Callable[[str], None] | None = None) -> None:
        self.spec = spec
        self.ser = None
        self.on_line = on_line
        self.error: str | None = None
        self.rx_bytes = 0
        self.rx_lines = 0
        # DTR = BOOT pin, RTS = RESET line. Released = False, for both.
        self.dtr = False
        self.rts = False
        self.lost = False
        # open()/close() are called from request threads; serialise them.
        self._io_lock = threading.Lock()
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
        with self._io_lock:
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
        with self._io_lock:
            self._stop.set()
            thread, self._thread = self._thread, None
            if thread is not None:
                thread.join(timeout=1.0)
            ser, self.ser = self.ser, None
            if ser is not None:
                try:
                    ser.close()
                except Exception:  # noqa: BLE001 - closing must never raise
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

        RTS is not toggled: it is pulsed by App.pulse_reset(), because a reset
        line left asserted holds the board in reset.
        """
        self.set_line(line, not getattr(self, line))

    # ── writing ────────────────────────────────────────────────────────────
    def write(self, data: bytes) -> bool:
        """Send bytes to the board. False if the port is closed or the write failed.

        The hub's command channel and the image push both come through here.
        Keeping writes and reads on the *same* open port matters on these boards:
        every open() re-applies the modem lines, and a glitch on RTS is a reset
        pulse on the tag.
        """
        with self._io_lock:
            ser = self.ser
            if ser is None or not ser.is_open:
                self.error = "port is not open"
                return False
            try:
                ser.write(data)
                ser.flush()
            except (serial.SerialException, OSError, ValueError) as exc:
                self.error = str(exc)
                self.lost = True
                return False
            return True

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
        if self.on_line is not None:
            self.on_line(text)
