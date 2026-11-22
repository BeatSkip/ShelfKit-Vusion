"""Settings > Raspberry Pi GPIO: reset/BOOT pins per pane, kept in the settings table.

Shown only on a Raspberry Pi (gpio_lines.pi_model()). A pane's pins follow its port: when
the pane is opened on another port they are claimed for that one. Pins given on the
command line (--gpio-reset/--gpio-boot) win; such a pane shows them and cannot be edited.
"""

from __future__ import annotations

from . import gpio_lines

SETTING_KEY = "gpio"


def _pin_text(line) -> str:
    return "" if line is None else f"{line.pin}{':high' if line.active_high else ''}"


class GpioConfig:
    def __init__(self, app, locked: set[str] | None = None) -> None:
        self.app = app
        self.locked = set(locked or ())          # pane names configured on the command line
        self.model = gpio_lines.pi_model()
        stored = (app.store.setting(SETTING_KEY, {}) if app.store is not None else {}) or {}
        self.chip = str(stored.get("chip") or "")
        self.pins: dict[str, dict[str, str]] = {
            str(name): {"reset": str(v.get("reset") or ""), "boot": str(v.get("boot") or "")}
            for name, v in (stored.get("panes") or {}).items() if isinstance(v, dict)}
        self.applied: dict[str, tuple] = {}      # pane name -> (port, reset, boot, chip) claimed
        self.errors: dict[str, str] = {}

    # ── claiming ───────────────────────────────────────────────────────────
    def apply(self, pane) -> None:
        """Claim (or let go of) the pins of one pane for the port it has now."""
        name = pane.spec.name
        if name in self.locked:
            return
        pins = self.pins.get(name) or {}
        want = None
        if self.model and pane.spec.port and (pins.get("reset") or pins.get("boot")):
            want = (pane.spec.port, pins.get("reset", ""), pins.get("boot", ""), self.chip)
        if want == self.applied.get(name) and name not in self.errors:
            return
        old = self.applied.pop(name, None)
        if old:
            gpio_lines.release(old[0])
        self.errors.pop(name, None)
        if want is None:
            return
        try:
            gpio_lines.configure(want[0], want[1] or None, want[2] or None, want[3] or None)
            self.applied[name] = want
        except gpio_lines.GpioError as exc:
            self.errors[name] = str(exc)
            return
        if pane.worker.is_open:
            pane.worker._apply_lines()           # put the pins where the lines are now

    def apply_all(self) -> None:
        for pane in self.app.panes.values():
            self.apply(pane)

    # ── the Settings tab ───────────────────────────────────────────────────
    def info(self) -> dict:
        panes = []
        for pane in self.app.panes.values():
            name = pane.spec.name
            active = gpio_lines.mapped(pane.spec.port)
            if name in self.locked:
                reset = _pin_text(active.lines.get("rts")) if active else ""
                boot = _pin_text(active.lines.get("dtr")) if active else ""
            else:
                reset = (self.pins.get(name) or {}).get("reset", "")
                boot = (self.pins.get(name) or {}).get("boot", "")
            panes.append({
                "key": pane.key, "name": name, "port": pane.spec.port,
                "reset": reset, "boot": boot,
                "locked": name in self.locked,
                "active": active.describe() if active else None,
                "error": self.errors.get(name),
            })
        return {"pi": self.model, "chip": self.chip, "panes": panes}

    def configure(self, body: dict) -> dict:
        """{"chip": "", "panes": {"hub": {"reset": "17", "boot": "27"}}} -> ok + info."""
        chip = str(body.get("chip") or "").strip()
        if chip and not chip.replace("/dev/", "").startswith("gpiochip"):
            return {"ok": False, "error": f"{chip!r} is not a gpiochip", **self.info()}
        pins = dict(self.pins)
        for name, roles in (body.get("panes") or {}).items():
            if name in self.locked or not isinstance(roles, dict):
                continue
            entry = {}
            for role in ("reset", "boot"):
                text = str(roles.get(role) or "").strip()
                try:
                    gpio_lines.parse_pin(text)
                except gpio_lines.GpioError as exc:
                    return {"ok": False, "error": f"{name} {role}: {exc}", **self.info()}
                entry[role] = text
            pins[str(name)] = entry
        seen: dict[str, str] = {}
        for name, entry in pins.items():
            if name in self.locked:
                continue
            for role in ("reset", "boot"):
                pin = entry.get(role, "").split(":")[0]
                if not pin:
                    continue
                if pin in seen:
                    return {"ok": False, "error": f"GPIO{pin} is used twice ({seen[pin]} and "
                            f"{name} {role})", **self.info()}
                seen[pin] = f"{name} {role}"
        self.pins, self.chip = pins, chip
        if self.app.store is not None:
            self.app.store.set_setting(SETTING_KEY, {"chip": chip, "panes": pins})
        self.apply_all()
        errors = [f"{n}: {e}" for n, e in self.errors.items()]
        return {"ok": not errors, "saved": True, "error": "; ".join(errors) or None, **self.info()}
