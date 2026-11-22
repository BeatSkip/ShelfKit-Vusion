"""Reset and BOOT on GPIO pins instead of the serial adapter's RTS and DTR (Linux).

On a Raspberry Pi the hub can hang off the Pi's own UART or off a USB adapter that has
only TX/RX wired. Its RESET and BOOT (PB3) lines then go to two GPIO pins, and every
place that would have driven RTS (reset) or DTR (boot) drives that pin instead:
`serial_link._set_line()` asks `pin_for()` first, so the server's panes, the reset
button, the boot-state learning and the server's serial flasher all follow.

A mapping belongs to one serial port:

    configure("/dev/ttyAMA0", reset="17", boot="27")      # BCM numbers
    configure("/dev/ttyUSB0", reset="17:high")            # active-high reset

The levels copy a USB-serial adapter, so a board wired either way behaves the same:
asserted = the pin is LOW, released = HIGH. Add ":high" to a pin for the opposite.
Pin numbers are the chip's line offsets, which on every Raspberry Pi are the BCM GPIO
numbers (GPIO17 = 17, header pin 11), Pi 5 included.

Needs libgpiod's Python binding: `sudo apt install python3-libgpiod` (API v1) or
`pip install gpiod` (API v2); both work. The user needs access to /dev/gpiochip*
(the `gpio` group on Raspberry Pi OS), not root.

When the process ends the kernel gives the lines back and they float; a released reset
must then be held high by the board or a 10k pull-up, or the hub sits in reset.
"""

from __future__ import annotations

import glob
import os
import threading

_RPI_LABELS = ("pinctrl-rp1", "pinctrl-bcm2712", "pinctrl-bcm2711", "pinctrl-bcm2835")


class GpioError(RuntimeError):
    pass


def pi_model() -> str | None:
    """'Raspberry Pi 4 Model B Rev 1.4' on a Raspberry Pi, else None."""
    for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            with open(path, "rb") as fh:
                model = fh.read().decode("ascii", "replace").strip("\x00 \n")
        except OSError:
            continue
        return model if "Raspberry Pi" in model else None
    return None


def parse_pin(text: str | int | None) -> tuple[int, bool] | None:
    """'17' -> (17, False); '17:high' -> (17, True) = active high. None/'' -> None."""
    if text is None or str(text).strip() == "":
        return None
    num, _, mode = str(text).strip().partition(":")
    try:
        pin = int(num)
    except ValueError:
        raise GpioError(f"not a GPIO number: {text!r}") from None
    if pin < 0 or mode.lower() not in ("", "low", "high"):
        raise GpioError(f"bad GPIO pin {text!r}: use N, N:low or N:high")
    return pin, mode.lower() == "high"


def _chip_label(path: str) -> str:
    name = os.path.basename(path)
    try:
        with open(f"/sys/bus/gpio/devices/{name}/label", encoding="ascii") as fh:
            return fh.read().strip()
    except OSError:
        try:
            with open(f"/sys/class/gpio/{name}/label", encoding="ascii") as fh:
                return fh.read().strip()
        except OSError:
            return ""


def find_chip(name: str | None = None) -> str:
    """/dev/gpiochipN: the one named, else the Pi's header chip, else gpiochip0."""
    if name:
        return name if name.startswith("/") else f"/dev/{name}"
    chips = sorted(glob.glob("/dev/gpiochip*"), key=lambda p: int(p[13:] or 0))
    if not chips:
        raise GpioError("no /dev/gpiochip* here: GPIO lines need Linux with a GPIO chip")
    labels = {c: _chip_label(c) for c in chips}
    for want in _RPI_LABELS:
        for chip, label in labels.items():
            if label == want:
                return chip
    return chips[0]


class _Line:
    """One output line held for the life of the process, through gpiod v2 or v1."""

    def __init__(self, chip: str, pin: int, active_high: bool, consumer: str) -> None:
        try:
            import gpiod
        except ImportError:
            raise GpioError("GPIO lines need libgpiod's Python binding: "
                            "sudo apt install python3-libgpiod  (or pip install gpiod)") from None
        self.chip, self.pin, self.active_high = chip, pin, active_high
        released = 0 if active_high else 1          # the level that does nothing
        try:
            if hasattr(gpiod, "request_lines"):     # libgpiod v2
                from gpiod.line import Direction, Value
                self._v = (Value.INACTIVE, Value.ACTIVE)
                self._req = gpiod.request_lines(
                    chip, consumer=consumer,
                    config={pin: gpiod.LineSettings(direction=Direction.OUTPUT,
                                                    output_value=self._v[released])})
                self._set = lambda level: self._req.set_value(pin, self._v[level])
                self._close = self._req.release
            else:                                   # libgpiod v1 (Debian's python3-libgpiod)
                line = gpiod.Chip(chip).get_line(pin)
                line.request(consumer=consumer, type=gpiod.LINE_REQ_DIR_OUT,
                             default_val=released)
                self._req = line
                self._set = line.set_value
                self._close = line.release
        except PermissionError:
            raise GpioError(f"no access to {chip}: add the user to the 'gpio' group "
                            f"(sudo usermod -aG gpio $USER) and log in again") from None
        except OSError as exc:
            raise GpioError(f"GPIO{pin} on {chip}: {exc}") from None

    def drive(self, asserted: bool) -> None:
        level = int(asserted) if self.active_high else int(not asserted)
        self._set(level)

    def close(self) -> None:
        """Give the line back to the kernel (it floats from then on)."""
        try:
            self._close()
        except (OSError, AttributeError, ValueError):
            pass


class PortPins:
    """The reset and boot lines that stand in for one port's RTS and DTR."""

    def __init__(self, port: str, reset=None, boot=None, chip: str | None = None) -> None:
        self.port = port
        self.chip = find_chip(chip)
        self.lines: dict[str, _Line] = {}
        consumer = f"shelfkit {os.path.basename(port)}"
        try:
            for serial_line, spec in (("rts", reset), ("dtr", boot)):
                parsed = parse_pin(spec)
                if parsed is not None:
                    self.lines[serial_line] = _Line(
                        self.chip, parsed[0], parsed[1],
                        f"{consumer} {'reset' if serial_line == 'rts' else 'boot'}")
        except GpioError:
            self.close()                # don't keep half a mapping
            raise

    def close(self) -> None:
        for line in self.lines.values():
            line.close()
        self.lines = {}

    def describe(self) -> str:
        parts = [f"{'reset' if k == 'rts' else 'boot'}=GPIO{v.pin}{':high' if v.active_high else ''}"
                 for k, v in self.lines.items()]
        return f"{', '.join(parts)} on {self.chip}"


_lock = threading.Lock()
_ports: dict[str, PortPins] = {}


def _key(port: str) -> str:
    return os.path.realpath(port) if port and port.startswith("/") else (port or "")


def configure(port: str, reset=None, boot=None, chip: str | None = None) -> PortPins:
    """Claim the pins for `port` now, so a wiring or permission problem shows at start."""
    release(port)                       # a port's old pins are free before new ones are claimed
    pins = PortPins(port, reset, boot, chip)
    with _lock:
        _ports[_key(port)] = pins
    return pins


def release(port: str | None) -> None:
    """Forget `port`'s pins and give them back to the kernel."""
    with _lock:
        pins = _ports.pop(_key(port), None) if port else None
    if pins is not None:
        pins.close()


def pin_for(port: str | None, serial_line: str):
    """The GPIO line standing in for `serial_line` ('dtr'/'rts') on `port`, or None."""
    if not _ports or not port:
        return None
    pins = _ports.get(_key(port))
    return pins.lines.get(serial_line) if pins else None


def mapped(port: str | None) -> PortPins | None:
    return _ports.get(_key(port)) if port and _ports else None


# ── command line ──────────────────────────────────────────────────────────
def add_arguments(ap, panes: bool = False) -> None:
    """--gpio-reset, --gpio-boot and --gpio-chip on an argparse parser."""
    where = "[PANE:]PIN[:high]" if panes else "PIN[:high]"
    extra = (" Repeatable; PANE is the pane's name (default: the hub pane)." if panes else "")
    group = ap.add_argument_group(
        "GPIO reset/boot (Linux, e.g. Raspberry Pi)",
        "Drive the board's RESET and BOOT from GPIO pins instead of the serial adapter's "
        "RTS and DTR. PIN is the BCM GPIO number; asserted = low, add :high for the "
        "opposite. Needs python3-libgpiod and the 'gpio' group.")
    kw = {"action": "append"} if panes else {}
    group.add_argument("--gpio-reset", metavar=where, help="GPIO for RESET (instead of RTS)." + extra, **kw)
    group.add_argument("--gpio-boot", metavar=where, help="GPIO for BOOT (instead of DTR)." + extra, **kw)
    group.add_argument("--gpio-chip", metavar="CHIP",
                       help="gpiochip to use (default: the Raspberry Pi header chip, else gpiochip0)")


def _split(value: str) -> tuple[str | None, str]:
    head, sep, rest = value.partition(":")
    if sep and head and not head.strip().isdigit():
        return head.strip(), rest
    return None, value


def apply_arguments(args, ports: dict[str, str | None] | str | None) -> list[PortPins]:
    """Claim the pins the options name. `ports` is {pane name: port} (the first entry is
    the default pane) or one port. Raises GpioError with a message for the user."""
    single = not isinstance(ports, dict)
    wanted: dict[str | None, dict] = {}
    for role in ("reset", "boot"):
        values = getattr(args, f"gpio_{role}", None) or []
        for value in ([values] if isinstance(values, str) else values):
            name, pin = (None, value) if single else _split(value)
            parse_pin(pin)                            # complain early about a typo
            wanted.setdefault(name, {})[role] = pin
    if not wanted:
        return []
    claimed = []
    for name, roles in wanted.items():
        if single:
            port = ports
        else:
            if name is None:
                name = "hub" if "hub" in ports else next(iter(ports), None)
            if name not in ports:
                raise GpioError(f"no pane named {name!r} for the GPIO pins "
                                f"(panes: {', '.join(ports) or 'none'})")
            port = ports[name]
        if not port:
            raise GpioError(f"GPIO pins need the port on the command line"
                            + (f", e.g. {name}=/dev/ttyUSB0" if name else ""))
        claimed.append(configure(port, roles.get("reset"), roles.get("boot"),
                                 getattr(args, "gpio_chip", None)))
    return claimed
