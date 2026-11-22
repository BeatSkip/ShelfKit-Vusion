"""The hub's own e-paper panel: the fleet of connected tags, plus a line of server stats.

The hub's panel is mounted **landscape**, so the frame is laid out 296 wide x 152 tall and
turned by `rotate` degrees into the panel's native 152x296 before it is sent. The tags take
the panel: a header with the title and the count, then their ids (with the alias when there
is room). The server gets one footer line - CPU, RAM, disk and uptime - next to the time of
the drawing.

A tag counts as connected while its last POLL is younger than `timeout_s` (default five
minutes); it drops off the list after that. The panel is redrawn when the *set* of connected
tags changes - never to update an age - and, with the statistics on, every `stats_interval_s`
so the figures do not go stale. Never more often than once per `min_interval_s`, because a
refresh takes ~15 s, blanks the hub's radio side for that time (it cannot answer tag polls
while the panel is being driven) and wears the panel.

Configuration (`App.hubdisp.configure()`, `GET/POST /api/hub-display`, or the
`--hub-display*` options of shelfkit-server.py), persisted in the settings table:

    enabled           bool   draw at all (default False: opt in once the hub is flashed with
                             the serial image command, banner "show=1")
    timeout_s         int    seconds of silence before a tag leaves the list (default 300)
    min_interval_s    int    shortest time between two redraws (default 60)
    title             str    header text (default "ShelfKit hub")
    show_alias        bool   print the tag's alias next to its id (default True)
    stats             bool   the server statistics line in the footer (default True)
    stats_interval_s  int    redraw for fresh statistics this often, 0 = only when the tags
                             change (default 1800)
    rotate            int    90 or 270: which way the landscape frame is turned onto the
                             panel; flip it when the picture is upside down (default 90)

Tags poll every SHELF_POLL_INTERVAL_S (120 s) and stretch that to 10 minutes on a weak
link, so a timeout shorter than the slowest poll interval makes such a tag flap.
"""

from __future__ import annotations

import platform
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
    "stats": True,
    "stats_interval_s": 1800,
    "rotate": 90,
}
SETTING_KEY = "hub_display"
TICK_S = 2.0
LAND_W, LAND_H = 296, 152           # the hub panel as it is mounted
ROW_H = 16
STAT_NAMES = {"CPU": "cpu", "RAM": "ram", "DISK": "disk"}


def _clean(options: dict) -> dict:
    """Validated copy of the recognised options; unknown or bad values are dropped."""
    out: dict = {}
    for name, low in (("timeout_s", 1), ("min_interval_s", 1), ("stats_interval_s", 0)):
        if name in options:
            try:
                value = int(options[name])
            except (TypeError, ValueError):
                continue
            if value >= low:
                out[name] = value
    for name in ("enabled", "show_alias", "stats"):
        if name in options:
            out[name] = bool(options[name])
    if "title" in options:
        out["title"] = str(options["title"] or "").strip()[:24] or DEFAULTS["title"]
    if "rotate" in options:
        try:
            value = int(options["rotate"])
        except (TypeError, ValueError):
            value = None
        if value in (90, 270):
            out["rotate"] = value
    return out


def _uptime_text(seconds: float | None) -> str:
    if seconds is None:
        return ""
    days, rem = divmod(int(seconds), 86400)
    return f"up {days}d" if days else f"up {rem // 3600}h"


def render(ids: list[int], aliases: dict[int, str] | None = None, title: str = "ShelfKit hub",
           show_alias: bool = True, when: datetime | None = None, stats=None,
           uptime_s: float | None = None, host: str | None = None, rotate: int | None = None):
    """The panel frame: 296x152 landscape, or turned to the native 152x296 when `rotate`
    is given. `stats` is stats_image.collect()'s rows, or None for no statistics line."""
    from PIL import Image, ImageDraw

    try:
        from .service_image import BLACK, RED, WHITE, _fits, _font
    except ImportError:             # not imported as part of the package
        from service_image import BLACK, RED, WHITE, _fits, _font
    try:
        from .stats_image import WARN_PCT
    except ImportError:
        from stats_image import WARN_PCT

    aliases = aliases or {}
    image = Image.new("RGB", (LAND_W, LAND_H), WHITE)
    d = ImageDraw.Draw(image)
    d.fontmode = "1"                # 1-bit glass: no anti-aliasing
    d.rectangle([0, 0, LAND_W - 1, LAND_H - 1], outline=BLACK, width=2)

    # header: title left, tag count right, white on black
    d.rectangle([4, 4, LAND_W - 5, 25], fill=BLACK)
    count = f"{len(ids)} tag{'s' if len(ids) != 1 else ''}"
    head = _font(14)
    count_w = int(d.textlength(count, font=head))
    d.text((10, 15), _fits(title, head, LAND_W - count_w - 34), font=head, fill=WHITE, anchor="lm")
    d.text((LAND_W - 10, 15), count, font=head, fill=WHITE, anchor="rm")

    # the fleet: the whole width between the header and the footer
    top, bottom, right = 32, LAND_H - 20, LAND_W - 8
    mono, small = _font(14, mono=True), _font(11)
    rows = max(1, (bottom - top) // ROW_H)
    if not ids:
        d.text((10, top + 2), "no tags connected", font=_font(13), fill=RED)
    else:
        id_w = int(d.textlength("0000", font=mono))
        with_alias = show_alias and any(aliases.get(a) for a in ids)
        # with aliases two wide columns, without them as many id columns as fit
        col_w = (right - 10) // 2 if with_alias else id_w + 16
        cols = max(1, (right - 10 + 16) // col_w) if not with_alias else 2
        room = rows * cols
        shown = ids if len(ids) <= room else ids[:room - 1]
        for i, addr in enumerate(shown):
            x = 10 + (i // rows) * col_w
            y = top + (i % rows) * ROW_H
            d.text((x, y), f"{addr:04X}", font=mono, fill=BLACK)
            alias = aliases.get(addr) if with_alias else None
            if alias:
                d.text((x + id_w + 6, y + 2), _fits(alias, small, col_w - id_w - 12),
                       font=small, fill=BLACK)
        if len(ids) > len(shown):
            i = len(shown)
            d.text((10 + (i // rows) * col_w, top + (i % rows) * ROW_H + 2),
                   f"+{len(ids) - len(shown)}", font=_font(13), fill=RED)

    # footer: one line of server stats on the left, the time of drawing on the right
    foot, y = _font(10), LAND_H - 11
    d.line([6, LAND_H - 19, LAND_W - 7, LAND_H - 19], fill=BLACK, width=1)
    stamp = (when or datetime.now()).strftime("%d %b %H:%M")
    d.text((LAND_W - 8, y), stamp, font=foot, fill=BLACK, anchor="rm")
    if stats is not None:
        gap = 8
        parts = [(f"{STAT_NAMES.get(name, name.lower())} {text.split()[0] if text else 'n/a'}",
                  pct is not None and pct >= WARN_PCT) for name, pct, text in stats]
        up = _uptime_text(uptime_s)
        if up:
            parts.append((up, False))
        room = LAND_W - 8 - int(d.textlength(stamp, font=foot)) - 12 - 8
        while parts and sum(int(d.textlength(t, font=foot)) + gap for t, _ in parts) - gap > room:
            parts.pop()                 # the uptime goes first, then disk, ...
        x = 8
        for text, hot in parts:
            d.text((x, y), text, font=foot, fill=RED if hot else BLACK, anchor="lm")
            x += int(d.textlength(text, font=foot)) + gap
    if rotate in (90, 270):
        image = image.rotate(rotate, expand=True)
    return image


def server_stats() -> tuple[list, float | None, str]:
    """(rows, uptime in seconds, host name) for the statistics column."""
    from . import stats_image
    return stats_image.collect(), stats_image._uptime_s(), platform.node()


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
        self.last_drawn = 0.0                   # when the glass last changed (statistics age)
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
        stale = (config["stats"] and config["stats_interval_s"] > 0
                 and now - self.last_drawn >= config["stats_interval_s"])
        if not force and not stale and (ids == shown or (shown is None and not ids
                                                          and not config["stats"])):
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
            stats, uptime, host = server_stats() if config["stats"] else (None, None, None)
            frame = render(ids, aliases, config["title"], config["show_alias"], stats=stats,
                           uptime_s=uptime, host=host, rotate=config["rotate"])
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
                self.last_drawn = time.time()
        self._result(f"drawn {len(ids)} tag(s)" if ok else f"not drawn: {why}")
        app.note(app.hub_key(), f"# hub display: {self.last_result}")
        return ok
