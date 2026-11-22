"""Reset/BOOT on GPIO pins (shelfkit/gpio_lines.py) with a fake gpiod, v1 and v2 API.

    python tests/gpio_test.py
"""
import argparse
import enum
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import serial  # noqa: E402

from shelfkit import gpio_lines, serial_link  # noqa: E402

FAILED: list[str] = []
LEVELS: dict[int, list[int]] = {}       # pin -> every level it was driven to
RELEASED: list[int] = []                # pins given back


def check(name: str, ok: bool, detail=None) -> None:
    if ok:
        print(f"  PASS {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name}" + (f"  <<< {detail}" if detail is not None else ""))


def fake_v2():
    mod = types.ModuleType("gpiod")
    line = types.ModuleType("gpiod.line")

    class Direction(enum.Enum):
        OUTPUT = 1

    class Value(enum.Enum):
        INACTIVE = 0
        ACTIVE = 1

    line.Direction, line.Value = Direction, Value

    class LineSettings:
        def __init__(self, direction, output_value):
            self.output_value = output_value

    class Request:
        def __init__(self, pins):
            self.pins = pins

        def set_value(self, pin, value):
            LEVELS.setdefault(pin, []).append(value.value)

        def release(self):
            RELEASED.extend(self.pins)

    def request_lines(chip, consumer, config):
        for pin, settings in config.items():
            LEVELS.setdefault(pin, []).append(settings.output_value.value)
        return Request(list(config))

    mod.LineSettings, mod.request_lines, mod.line = LineSettings, request_lines, line
    return {"gpiod": mod, "gpiod.line": line}


def fake_v1():
    mod = types.ModuleType("gpiod")
    mod.LINE_REQ_DIR_OUT = 3

    class Line:
        def __init__(self, pin):
            self.pin = pin

        def request(self, consumer, type, default_val):
            LEVELS.setdefault(self.pin, []).append(default_val)

        def set_value(self, value):
            LEVELS.setdefault(self.pin, []).append(value)

        def release(self):
            RELEASED.append(self.pin)

    class Chip:
        def __init__(self, path):
            pass

        def get_line(self, pin):
            return Line(pin)

    mod.Chip = Chip
    return {"gpiod": mod}


def run(flavour: str, modules: dict) -> None:
    gpio_lines._ports.clear()
    LEVELS.clear()
    for name in ("gpiod", "gpiod.line"):
        sys.modules.pop(name, None)
    sys.modules.update(modules)

    pins = gpio_lines.configure("loop://", reset="17", boot="27:high", chip="gpiochip0")
    check(f"{flavour}: the pins start released (reset high, active-high boot low)",
          LEVELS == {17: [1], 27: [0]}, LEVELS)
    check(f"{flavour}: describe() names both pins",
          pins.describe() == "reset=GPIO17, boot=GPIO27:high on /dev/gpiochip0", pins.describe())

    ser = serial.serial_for_url("loop://", do_not_open=True)
    serial_link._set_line(ser, "rts", True)
    serial_link._set_line(ser, "dtr", True)
    serial_link._set_line(ser, "rts", False)
    check(f"{flavour}: asserting RTS pulls the reset pin low, releasing lets it go high",
          LEVELS[17] == [1, 0, 1], LEVELS[17])
    check(f"{flavour}: asserting DTR drives an active-high boot pin high",
          LEVELS[27] == [0, 1], LEVELS[27])

    other = serial.serial_for_url("loop://", do_not_open=True)
    other.port = "/dev/ttyUSB9"
    serial_link._set_line(other, "rts", True)
    check(f"{flavour}: a port without pins leaves the GPIO alone", LEVELS[17] == [1, 0, 1])


def settings_tab() -> None:
    """GpioConfig: what Settings > Raspberry Pi GPIO saves and claims."""
    from shelfkit import gpio_config

    class Worker:
        is_open = False

    class Pane:
        def __init__(self, key, name, port):
            self.key, self.worker = key, Worker()
            self.spec = types.SimpleNamespace(name=name, port=port)

    sys.modules.update(fake_v2())
    gpio_lines._ports.clear()
    LEVELS.clear()
    RELEASED.clear()
    app = types.SimpleNamespace(store=None, panes={"hub": Pane("hub", "hub", "/dev/ttyAMA0"),
                                                   "tag": Pane("tag", "tag", None)})
    real_model = gpio_lines.pi_model
    gpio_lines.pi_model = lambda: None
    cfg = gpio_config.GpioConfig(app)
    result = cfg.configure({"chip": "gpiochip0", "panes": {"hub": {"reset": "17", "boot": "27"}}})
    check("off a Pi the pins are stored but nothing is claimed",
          result["ok"] and result["pi"] is None and not LEVELS, result)

    gpio_lines.pi_model = lambda: "Raspberry Pi 4 Model B Rev 1.4"
    cfg = gpio_config.GpioConfig(app)
    result = cfg.configure({"chip": "gpiochip0", "panes": {"hub": {"reset": "17", "boot": "27"}}})
    hub = result["panes"][0]
    check("on a Pi saving claims the hub's pins",
          result["ok"] and hub["active"] == "reset=GPIO17, boot=GPIO27 on /dev/gpiochip0"
          and LEVELS == {17: [1], 27: [1]}, result)
    check("a pane without a port claims nothing yet", result["panes"][1]["active"] is None)
    result = cfg.configure({"chip": "gpiochip0", "panes": {"hub": {"reset": "17", "boot": "x"}}})
    check("a bad pin is refused and the old pins stay",
          not result["ok"] and "boot" in result["error"] and gpio_lines.mapped("/dev/ttyAMA0"))
    result = cfg.configure({"chip": "gpiochip0", "panes": {"hub": {"reset": "17", "boot": ""},
                                                          "tag": {"reset": "17:high"}}})
    check("one GPIO for two lines is refused", not result["ok"] and "twice" in result["error"],
          result.get("error"))
    result = cfg.configure({"chip": "gpiochip0", "panes": {"hub": {"reset": "22", "boot": ""}}})
    check("changing a pin gives the old ones back first",
          result["ok"] and sorted(RELEASED) == [17, 27]
          and result["panes"][0]["active"] == "reset=GPIO22 on /dev/gpiochip0", (RELEASED, result))
    app.panes["hub"].spec.port = "/dev/ttyUSB0"
    cfg.apply(app.panes["hub"])
    check("the pins follow the pane to its new port",
          gpio_lines.mapped("/dev/ttyUSB0") is not None and gpio_lines.mapped("/dev/ttyAMA0") is None)
    result = cfg.configure({"chip": "gpiochip0", "panes": {"hub": {"reset": "", "boot": ""}}})
    check("emptying the fields hands the lines back to the adapter",
          result["ok"] and gpio_lines.mapped("/dev/ttyUSB0") is None)

    gpio_lines.configure("/dev/ttyUSB0", reset="5", chip="gpiochip0")
    locked = gpio_config.GpioConfig(app, locked={"hub"})
    result = locked.configure({"panes": {"hub": {"reset": "9"}}})
    check("command-line pins are shown and cannot be changed",
          result["panes"][0]["locked"] and result["panes"][0]["reset"] == "5"
          and gpio_lines.mapped("/dev/ttyUSB0").lines["rts"].pin == 5, result["panes"][0])
    gpio_lines.pi_model = real_model
    gpio_lines._ports.clear()


def main() -> int:
    check("parse_pin reads N and N:high", gpio_lines.parse_pin("17") == (17, False)
          and gpio_lines.parse_pin("4:high") == (4, True) and gpio_lines.parse_pin("") is None)
    for bad in ("x", "17:up", "-1"):
        try:
            gpio_lines.parse_pin(bad)
            check(f"parse_pin refuses {bad!r}", False)
        except gpio_lines.GpioError:
            check(f"parse_pin refuses {bad!r}", True)

    run("gpiod v2", fake_v2())
    run("gpiod v1", fake_v1())

    # pane names on the server's command line
    gpio_lines._ports.clear()
    ap = argparse.ArgumentParser()
    gpio_lines.add_arguments(ap, panes=True)
    args = ap.parse_args(["--gpio-reset", "17", "--gpio-boot", "27",
                          "--gpio-reset", "tag:22:high", "--gpio-chip", "gpiochip0"])
    claimed = gpio_lines.apply_arguments(args, {"tag": "/dev/ttyUSB1", "hub": "/dev/ttyUSB0"})
    by_port = {p.port: p.describe() for p in claimed}
    check("pins without a pane name go to the hub pane, 'tag:' to the tag pane",
          by_port == {"/dev/ttyUSB0": "reset=GPIO17, boot=GPIO27 on /dev/gpiochip0",
                      "/dev/ttyUSB1": "reset=GPIO22:high on /dev/gpiochip0"}, by_port)
    try:
        gpio_lines.apply_arguments(ap.parse_args(["--gpio-reset", "aisle:5"]), {"hub": "/dev/x"})
        check("an unknown pane name is refused", False)
    except gpio_lines.GpioError:
        check("an unknown pane name is refused", True)
    try:
        gpio_lines.apply_arguments(ap.parse_args(["--gpio-reset", "5"]), {"hub": None})
        check("a pane without a port is refused", False)
    except gpio_lines.GpioError:
        check("a pane without a port is refused", True)

    settings_tab()

    sys.modules.pop("gpiod", None)
    sys.modules["gpiod"] = None             # as if libgpiod is not installed
    try:
        gpio_lines.configure("/dev/ttyUSB0", reset="17", chip="gpiochip0")
        check("a missing gpiod says what to install", False)
    except gpio_lines.GpioError as exc:
        check("a missing gpiod says what to install", "python3-libgpiod" in str(exc), exc)

    print("all passed" if not FAILED else f"{len(FAILED)} failed: {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
