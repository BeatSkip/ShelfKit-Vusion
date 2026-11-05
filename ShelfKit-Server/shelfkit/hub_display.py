"""The hub's own e-paper panel as a live list of the tags that are currently connected.

A tag counts as connected while its last POLL is younger than `timeout_s` (default five
minutes); it drops off the list after that. The panel is redrawn only when the *set* of
connected tags changes - never to update an age - and at most once per `min_interval_s`,
because a refresh takes ~15 s, blanks the hub's radio side for that time (it cannot
answer tag polls while the panel is being driven) and wears the panel.

Configuration (`App.hubdisp.configure()`, `GET/POST /api/hub-display`, or the
`--hub-display*` options of shelfkit-server.py), persisted in the settings table:

    enabled         bool   draw at all (default False: opt in once the hub is flashed with
                           the serial image command, banner "show=1")
    timeout_s       int    seconds of silence before a tag leaves the list (default 300)
    min_interval_s  int    shortest time between two redraws (default 60)
    title           str    header text (default "ShelfKit hub")
    show_alias      bool   print the tag's alias next to its id (default True)

Tags poll every SHELF_POLL_INTERVAL_S (120 s) and stretch that to 10 minutes on a weak
link, so a timeout shorter than the slowest poll interval makes such a tag flap.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

from . import hubhost

DEFAULTS = {
    "enabled": False,
    "timeout_s": 300,
    "min_interval_s": 60,
    "title": "ShelfKit hub",
    "show_alias": True,
}
SETTING_KEY = "hub_display"
TICK_S = 2.0
MAX_ROWS = 12


def _clean(options: dict) -> dict:
    """Validated copy of the recognised options; unknown or bad values are dropped."""
    out: dict = {}
    for name in ("timeout_s", "min_interval_s"):
        if name in options:
            try:
                value = int(options[name])
            except (TypeError, ValueError):
                continue
            if value >= 1:
                out[name] = value
    for name in ("enabled", "show_alias"):
        if name in options:
            out[name] = bool(options[name])
    if "title" in options:
        out["title"] = str(options["title"] or "").strip()[:24] or DEFAULTS["title"]
    return out


def render(ids: list[int], aliases: dict[int, str] | None = None, title: str = "ShelfKit hub",
           show_alias: bool = True, when: datetime | None = None):
    """The panel frame as a 152x296 RGB image."""
    from PIL import Image, ImageDraw

    try:
        from .service_image import BLACK, HEIGHT, RED, WHITE, WIDTH, _font, _fits
    except ImportError:             # not imported as part of the package
        from service_image import BLACK, HEIGHT, RED, WHITE, WIDTH, _font, _fits

    aliases = aliases or {}
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    d = ImageDraw.Draw(image)
    d.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=BLACK, width=2)
    d.rectangle([6, 6, WIDTH - 7, 30], fill=BLACK)
    d.text((WIDTH // 2, 18), _fits(title, _font(15), WIDTH - 20), font=_font(15), fill=WHITE,
           anchor="mm")
    count = f"{len(ids)} tag{'s' if len(ids) != 1 else ''} connected"
    d.text((WIDTH // 2, 42), count, font=_font(12), fill=RED if not ids else BLACK, anchor="ma")

    y = 64
    shown = ids if len(ids) <= MAX_ROWS else ids[:MAX_ROWS - 1]
    mono, small = _font(16, mono=True), _font(11)
    for addr in shown:
        d.text((10, y), f"{addr:04X}", font=mono, fill=BLACK)
        alias = aliases.get(addr) if show_alias else None
        if alias:
            d.text((WIDTH - 10, y + 4), _fits(alias, small, WIDTH - 80), font=small, fill=BLACK,
                   anchor="ra")
        y += 18
    if len(ids) > len(shown):
        d.text((10, y), f"+{len(ids) - len(shown)} more", font=small, fill=RED)
    stamp = (when or datetime.now()).strftime("%Y-%m-%d %H:%M")
    d.text((WIDTH // 2, HEIGHT - 14), stamp, font=_font(10), fill=BLACK, anchor="mm")
    return image


class HubDisplay:
    def __init__(self, app, options: dict | None = None) -> None:
        self.app = app
        self._lock = threading.Lock()
        self.config = dict(DEFAULTS)
        saved = app.store.settings().get(SETTING_KEY) if app.store is not None else None
        if isinstance(saved, dict):
            self.config.update(_clean(saved))
        if options:
            self.configure(**options)
        self.shown: list[int] | None = None     # ids on the glass; None = never drawn
        self.last_push = 0.0
        self.last_result: str | None = None
        self.last_at: float | None = None
        self._force = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ── configuration ─────────────────────────────────────────────────────
    def configure(self, refresh: bool = False, **options) -> dict:
        with self._lock:
            self.config.update(_clean(options))
            if refresh:
                self._force = True
            config = dict(self.config)
        if self.app.store is not None:
            self.app.store.set_setting(SETTING_KEY, config)
        return config

    def info(self) -> dict:
        with self._lock:
            return {**self.config,
                    "shown": None if self.shown is None else [f"{a:04X}" for a in self.shown],
                    "last_result": self.last_result,
                    "last_at": self.last_at}

    # ── the loop ──────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="hub-display", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(TICK_S):
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - a display problem must never kill the server
                self._result(f"error: {type(exc).__name__}: {exc}")

    def active_ids(self, now: float | None = None) -> list[int]:
        now = time.time() if now is None else now
        timeout = self.config["timeout_s"]
        with self.app.lock:
            return sorted(a for a, seen in self.app.tag_seen.items() if now - seen <= timeout)

    def _result(self, text: str) -> None:
        with self._lock:
            self.last_result = text
            self.last_at = time.time()

    def tick(self) -> bool:
        """One look at the fleet; draws when it changed. True if a frame was sent."""
        with self._lock:
            config, force, shown = dict(self.config), self._force, self.shown
        if not config["enabled"]:
            return False
        now = time.time()
        ids = self.active_ids(now)
        if not force and (ids == shown or (shown is None and not ids)):
            return False
        if now - self.last_push < config["min_interval_s"]:
            return False
        app = self.app
        with app.lock:      # claim the hub: nothing else may talk to it while it refreshes
            if (app.sending or app.dump.get("active") or app.display_busy
                    or any(job["state"] == "running" for job in app.queue)):
                return False
            app.display_busy = True
        try:
            with app.lock:
                aliases = {a: (m.get("alias") or "") for a, m in app.tag_meta.items()}
            frame = render(ids, aliases, config["title"], config["show_alias"])
            from . import png2epd
            bw, red = png2epd.to_planes(frame.convert("RGBA"), False)
            self.last_push = time.time()
            ok, why = app.show_on_hub(bw, red)
        finally:
            with app.lock:
                app.display_busy = False
            app._rearm_pending()    # pre-arms sent while the display owned the hub were dropped
        with self._lock:
            self._force = False
            if ok:
                self.shown = ids
        self._result(f"drawn {len(ids)} tag(s)" if ok else f"not drawn: {why}")
        app.note(app.hub_key(), f"# hub display: {self.last_result}")
        return ok
