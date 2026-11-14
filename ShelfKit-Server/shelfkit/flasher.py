"""Flash a tag or hub from the web page: through the AXSDB debugger, or the serial bootloader.

Two methods, one status view. Both run in a background thread and report the same four
steps, so the page shows them the same way:

    connect  ->  erase  ->  program  ->  run

debugger   Runs  `axsdb.exe --eraseall --flashprog <file.hex>`  from AXSDB's own `bin`
           folder (it reads init.tcl from there). The tool prints one line per phase:

               Programming Serial 39DC0854     connect (the debugger found the chip)
               Bulk erase...                   erase
               Flash program...                program
               Run program...                  run

           and its exit code says whether it worked. `--eraseall` wipes the WHOLE chip,
           bootloader included, so only a `*-full-*.hex` (bootloader + application) is a
           safe thing to give it. Anything else needs `allow_partial`.

serial     The same protocol as ShelfKit-Firmware/Tooling/axsem-flasher.py (kept as the
           command-line tool): hold BOOT (DTR) through a reset (RTS) to enter the mask-ROM
           bootloader at 38400, `?` for the banner, `K` to erase the application, the HEX
           lines, `R` to run. The port belongs to one of the server's panes, so that pane is
           closed for the transfer and reopened afterwards.

Nothing is flashed while a push, a read-back or the hub's panel redraw is running, and
the queue holds its commands until the flash is over.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path

from . import serial_link

BOOTLOADER_BAUD = 38400
AXSDB_TIMEOUT_S = 180            # a stuck debugger must not hold the page forever
ERASE_WAIT_S = 15.0
LOG_LINES = 400

STEPS = ("connect", "erase", "program", "run")
LABELS = {
    "debugger": {"connect": "Find the chip", "erase": "Erase the chip",
                 "program": "Write the firmware", "run": "Start the program"},
    "serial": {"connect": "Enter the bootloader", "erase": "Erase the application",
               "program": "Write the firmware", "run": "Start the program"},
}

RE_SERIAL = re.compile(r"^\s*Programming\s+Serial\s+(\S+)", re.I)
RE_ERASE = re.compile(r"^\s*Bulk\s+erase", re.I)
RE_PROGRAM = re.compile(r"^\s*Flash\s+program", re.I)
RE_RUN = re.compile(r"^\s*Run\s+program", re.I)

AXSDB_NAMES = ("axsdb.exe", "axsdb")


def resolve_axsdb(setting: str) -> tuple[str | None, bool]:
    """Find axsdb from the Settings value. Returns (path or None, found by itself).

    The setting may name the program or the folder holding it. Empty means "look for
    it": on PATH, then the default ON Semiconductor install.
    """
    text = (setting or "").strip().strip('"')
    if text:
        path = Path(text).expanduser()
        if path.is_dir():
            for name in AXSDB_NAMES:
                if (path / name).is_file():
                    return str(path / name), False
            return None, False
        if path.is_file() and path.name.lower() in AXSDB_NAMES:
            return str(path), False
        return None, False
    found = shutil.which("axsdb")
    if found:
        return found, True
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            candidate = Path(base) / "ON Semiconductor" / "AXSDB" / "bin" / "axsdb.exe"
            if candidate.is_file():
                return str(candidate), True
    return None, False


def axsdb_problem(setting: str) -> str | None:
    """Why this Settings value can't be used, or None. Empty is always fine."""
    if not (setting or "").strip():
        return None
    exe, _ = resolve_axsdb(setting)
    if exe is None:
        return ("No axsdb.exe was found there. Give the path to axsdb.exe, or to the folder "
                "that holds it, such as C:\\Program Files (x86)\\ON Semiconductor\\AXSDB\\bin")
    return None


def same_port(a: str, b: str) -> bool:
    return bool(a) and bool(b) and a.strip().casefold() == b.strip().casefold()


def hex_kind(name: str) -> str:
    low = name.lower()
    if "-full-" in low:
        return "full"
    if "bootloader" in low:
        return "bootloader"
    if "hub" in low:
        return "hub"
    return "app"


def hex_files(folder: Path) -> list[dict]:
    """Every .hex in Release/, newest first, with what kind of image it is."""
    try:
        files = sorted(folder.glob("*.hex"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    out = []
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        size = stat.st_size
        from . import firmware
        info = firmware.file_info(path)
        out.append({"name": path.name, "path": str(path), "size": size,
                    "kind": hex_kind(path.name), "build": info["text"] if info else None,
                    "mtime": stat.st_mtime})
    return out


class Flasher:
    """One flash at a time, with the progress the page draws."""

    def __init__(self, app) -> None:
        self.app = app
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._proc: subprocess.Popen | None = None
        self.active = False
        self.pane: str | None = None
        self.on_hub_port = False        # a serial flash through the hub's own port
        self._reset()

    @property
    def blocks_hub(self) -> bool:
        """True while a flash holds the hub's port; the debugger and a flash through
        any other port leave the hub free to carry on."""
        return self.active and self.on_hub_port

    def _reset(self) -> None:
        self.method = None
        self.file = None
        self.steps = {key: {"state": "waiting", "detail": ""} for key in STEPS}
        self.result = None            # "ok" | "failed" | "cancelled"
        self.error = None
        self.serial_no = None
        self.started = None
        self.finished = None
        self.log: list[str] = []
        self.log_n = 0

    # ── what the page reads ───────────────────────────────────────────────
    def info(self, full: bool = False) -> dict:
        with self._lock:
            labels = LABELS.get(self.method or "debugger")
            out = {
                "active": self.active,
                "method": self.method,
                "file": self.file,
                "pane": self.pane,
                "steps": [{"key": key, "label": labels[key], **self.steps[key]}
                          for key in STEPS],
                "result": self.result,
                "error": self.error,
                "serial": self.serial_no,
                "started": self.started,
                "finished": self.finished,
                "log_n": self.log_n,
            }
            if full:
                out["log"] = list(self.log)
        exe, detected = resolve_axsdb(self.app.prefs.get("axsdb_path", ""))
        out["axsdb"] = {"path": self.app.prefs.get("axsdb_path", ""), "exe": exe,
                        "found": exe is not None, "detected": detected}
        return out

    # ── recording ─────────────────────────────────────────────────────────
    def _say(self, text: str) -> None:
        with self._lock:
            self.log.append(f"{time.strftime('%H:%M:%S')}  {text}")
            if len(self.log) > LOG_LINES:
                del self.log[:len(self.log) - LOG_LINES]
            self.log_n += 1

    def _step(self, key: str, state: str, detail: str | None = None) -> None:
        with self._lock:
            self.steps[key]["state"] = state
            if detail is not None:
                self.steps[key]["detail"] = detail

    def _running(self) -> str | None:
        with self._lock:
            return next((k for k in STEPS if self.steps[k]["state"] == "running"), None)

    def _advance(self, to: str) -> None:
        """Mark every step before `to` done and `to` running."""
        with self._lock:
            for key in STEPS:
                if key == to:
                    break
                if self.steps[key]["state"] in ("waiting", "running"):
                    self.steps[key]["state"] = "done"
            self.steps[to]["state"] = "running"

    # ── starting ──────────────────────────────────────────────────────────
    def start(self, method: str, path: str, pane_key: str | None = None,
              allow_partial: bool = False) -> dict:
        app = self.app
        if method not in ("debugger", "serial"):
            return {"ok": False, "error": "Choose the debugger or the serial bootloader."}
        file = Path(str(path or ""))
        if file.suffix.lower() != ".hex" or not file.is_file():
            return {"ok": False, "error": "Pick a .hex file that exists."}
        kind = hex_kind(file.name)

        exe = None
        if method == "debugger":
            exe, _ = resolve_axsdb(app.prefs.get("axsdb_path", ""))
            if exe is None:
                return {"ok": False,
                        "error": "AXSDB wasn't found. Set its location in Settings."}
            if kind != "full" and not allow_partial:
                return {"ok": False, "needs_confirm": True,
                        "error": f"{file.name} has no bootloader in it, and the debugger erases "
                                 "the whole chip first. Flash a *-full-* image, or confirm "
                                 "that you want the bootloader gone."}
        pane = None
        if method == "serial":
            pane = app.panes.get(pane_key or "")
            if pane is None or not pane.spec.port:
                return {"ok": False, "error": "Pick a serial port that has a port set."}

        with app.lock:
            if self.active:
                return {"ok": False, "error": "A flash is already running. Wait for it to finish."}
            # The debugger never touches the hub, and a flash through another serial port
            # doesn't either, so those run alongside it. Only a flash through the hub's
            # own port has to wait for the hub to be idle.
            on_hub = False
            if method == "serial":
                hub = app.panes.get(app.hub_key())
                on_hub = (pane.key == hub.key
                          or (hub is not None and same_port(pane.spec.port, hub.spec.port)))
            hub_busy = (app.sending or app.display_busy or app.dump.get("active")
                        or any(job["state"] == "running" for job in app.queue))
            if on_hub and hub_busy:
                return {"ok": False,
                        "error": "The hub is busy with a transfer on this port. Wait for it, "
                                 "or flash through the other port."}
            self.active = True
            self.on_hub_port = on_hub
            self.pane = pane_key if method == "serial" else None
            app.status = f"flashing {file.name}"
        self._cancel.clear()
        with self._lock:
            self._reset()
            self.method = method
            self.file = file.name
            self.started = time.time()
        self._say(f"Flashing {file.name} with the "
                  f"{'debugger' if method == 'debugger' else 'serial bootloader'}")
        app._event("flash", None, f"{file.name} via {method}")
        runner = self._run_debugger if method == "debugger" else self._run_serial
        args = (exe, file) if method == "debugger" else (pane, file)
        threading.Thread(target=self._guard, args=(runner, *args), name="flash",
                         daemon=True).start()
        return {"ok": True}

    def cancel(self) -> dict:
        if not self.active:
            return {"ok": False, "error": "Nothing is being flashed."}
        self._cancel.set()
        proc = self._proc
        if proc is not None:
            try:
                proc.terminate()
            except OSError:
                pass
        self._say("Stop requested. The chip may be left half-programmed.")
        return {"ok": True}

    def _guard(self, runner, *args) -> None:
        """Run a flash; whatever happens, finish the record and free the hub."""
        result, error = "failed", None
        try:
            result, error = runner(*args)
        except Exception as exc:  # noqa: BLE001 - a flash must always end in a result
            error = f"{type(exc).__name__}: {exc}"
        if self._cancel.is_set() and result != "ok":
            result, error = "cancelled", "Stopped before it finished. Flash again to recover."
        running = self._running()
        if running is not None:
            self._step(running, "done" if result == "ok" else "failed")
        with self._lock:
            self.result = result
            self.error = error
            self.finished = time.time()
        self._say({"ok": "Flashed.", "cancelled": "Cancelled."}.get(result, f"Failed. {error or ''}"))
        self.app._event("flash", None, f"{self.file}: {result}" + (f" ({error})" if error else ""))
        with self.app.lock:
            self.active = False
            self.pane = None
            self.app.status = {"ok": "flash finished", "cancelled": "flash cancelled"}.get(
                result, "flash failed")

    # ── the debugger ──────────────────────────────────────────────────────
    def _run_debugger(self, exe: str, file: Path) -> tuple[str, str | None]:
        cmd = [exe, "--eraseall", "--flashprog", str(file)]
        self._say("Running: " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
        self._advance("connect")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                cwd=str(Path(exe).parent),            # init.tcl is read from here
                bufsize=0, creationflags=flags)
        except OSError as exc:
            return "failed", f"Couldn't start AXSDB: {exc}"
        self._proc = proc
        timer = threading.Timer(AXSDB_TIMEOUT_S, proc.kill)
        timer.start()
        tail: list[str] = []
        pending = ""
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                pending += chunk.decode("utf-8", "replace")
                # a progress bar redraws its line with \r, so split on either
                *lines, pending = re.split(r"\r\n|\r|\n", pending)
                for line in lines:
                    self._axsdb_line(line, tail)
            if pending.strip():
                self._axsdb_line(pending, tail)
            code = proc.wait()
        finally:
            timer.cancel()
            self._proc = None
        if self._cancel.is_set():
            return "cancelled", None
        if code == 0:
            return "ok", None
        reason = " ".join(tail[-3:]) or "AXSDB gave no reason"
        return "failed", f"AXSDB exited with code {code}. {reason}"

    def _axsdb_line(self, line: str, tail: list[str]) -> None:
        text = line.strip()
        if not text:
            return
        self._say(text)
        tail.append(text)
        match = RE_SERIAL.match(text)
        if match:
            with self._lock:
                self.serial_no = match.group(1)
            self._step("connect", "running", f"Serial {match.group(1)}")
        elif RE_ERASE.match(text):
            self._advance("erase")
        elif RE_PROGRAM.match(text):
            self._advance("program")
        elif RE_RUN.match(text):
            self._advance("run")

    # ── the serial bootloader ─────────────────────────────────────────────
    def _run_serial(self, pane, file: Path) -> tuple[str, str | None]:
        app = self.app
        was_open = pane.worker.is_open
        if was_open:
            pane.worker.close()
            self._say(f"Closed {pane.spec.port} for the transfer")
        ser = None
        try:
            spec = replace(pane.spec, baud=BOOTLOADER_BAUD)
            ser = serial_link._make_serial(spec)
            serial_link._set_line(ser, "dtr", False)
            serial_link._set_line(ser, "rts", False)
            try:
                ser.open()
            except Exception as exc:  # noqa: BLE001 - pyserial raises several types
                return "failed", f"Couldn't open {pane.spec.port}: {exc}"
            return self._bootloader_flash(ser, file)
        finally:
            if ser is not None:
                try:
                    ser.close()
                except Exception:  # noqa: BLE001
                    pass
            if was_open:
                pane.worker.open()
                self._say(f"Reopened {pane.spec.port}")
                app.note(pane.key, "# reopened after flashing")

    @staticmethod
    def _read_line(ser, wait: float) -> str:
        """One line from the port, or what arrived when `wait` seconds ran out."""
        end = time.time() + wait
        buf = bytearray()
        while time.time() < end:
            chunk = ser.read(1)
            if not chunk:
                continue
            if chunk in (b"\n", b"\r"):
                if buf:
                    break
                continue
            buf += chunk
        return buf.decode("utf-8", "replace").strip()

    def _drain(self, ser) -> list[str]:
        out = []
        for _ in range(20):
            line = self._read_line(ser, 0.05)
            if not line:
                break
            out.append(line)
        return out

    def _bootloader_flash(self, ser, file: Path) -> tuple[str, str | None]:
        self._advance("connect")
        # BOOT (DTR) held through a reset (RTS) selects the mask-ROM bootloader
        serial_link._set_line(ser, "rts", False)
        serial_link._set_line(ser, "dtr", True)
        serial_link._set_line(ser, "rts", True)
        time.sleep(0.1)
        serial_link._set_line(ser, "rts", False)
        time.sleep(0.1)
        serial_link._set_line(ser, "dtr", False)

        banner = ""
        for _ in range(3):
            self._drain(ser)
            ser.write(b"?")
            time.sleep(0.1)
            banner = self._read_line(ser, 1.0)
            if banner:
                self._say(f"Banner: {banner}")
            if "Bootloader" in banner:
                break
        else:
            return "failed", ("The chip didn't answer as a bootloader"
                              + (f" (it said: {banner})" if banner else "")
                              + ". Check the cable, the power, and that DTR is wired to BOOT.")
        self._step("connect", "running", banner)
        if self._cancel.is_set():
            return "cancelled", None

        self._advance("erase")
        ser.write(b"K")
        end = time.time() + ERASE_WAIT_S
        answer = ""
        while time.time() < end and "OK" not in answer:
            answer = self._read_line(ser, 1.0)
            if answer:
                self._say(f"Erase: {answer}")
        if "OK" not in answer:
            return "failed", "The bootloader didn't confirm the erase."

        lines = [ln.strip() for ln in file.read_text(encoding="ascii", errors="replace").splitlines()
                 if ln.strip()]
        self._advance("program")
        self._say(f"Programming {len(lines)} lines")
        for index, line in enumerate(lines, start=1):
            if self._cancel.is_set():
                return "cancelled", None
            ser.write((line + "\n").encode())
            time.sleep(0.01)            # the bootloader has no flow control
            if index % 20 == 0 or index == len(lines):
                self._step("program", "running", f"{index}/{len(lines)}")
        for extra in self._drain(ser):
            self._say(f"Bootloader: {extra}")

        self._advance("run")
        time.sleep(0.1)
        ser.write(b"R")
        time.sleep(0.1)
        return "ok", None
