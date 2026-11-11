"""What an app author imports: InkApp and the TagContext its callbacks receive.

    from shelfkit.inkservices import InkApp

    app = InkApp("hello", title="Hello")
    app.config_field("greeting", label="Greeting", default="Hello")

    @app.render
    def draw(tag, canvas):
        canvas.text((6, 6), tag.config["greeting"], size=18)

    @app.button("Press me")
    def press(tag):
        tag.data["n"] = tag.data.get("n", 0) + 1

    @app.every(minutes=30)
    def update(tag):
        tag.data["wx"] = tag.fetch_json("https://api.example/forecast", {"q": "x"})

The app never talks to the server directly: everything arrives in the TagContext
and everything it changes goes back through it. That is what lets the host move
apps into their own process later without changing app code.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Literal

from ..displays import DisplayPreset

LOG_KEEP = 200
MIN_TIMER_MINUTES = 1          # a timer redraws and may push: never faster than this
FETCH_LIMIT = 2_000_000        # bytes an app may fetch in one call


def http_json(url: str, params: dict | None = None, timeout: float = 10.0):
    """GET a JSON document. What tag.fetch_json does unless the host gives another
    fetcher (tests do). No cookies, no credentials, a generic User-Agent."""
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"fetch_json wants an http(s) URL, not {url!r}")
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "ShelfKit-InkServices",
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310 - http(s) checked above
        body = res.read(FETCH_LIMIT + 1)
    if len(body) > FETCH_LIMIT:
        raise ValueError(f"{url} sent more than {FETCH_LIMIT} bytes")
    return json.loads(body.decode("utf-8"))


def slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return s or "action"


@dataclass
class Control:
    id: str
    kind: Literal["button", "text"]
    label: str
    placeholder: str
    fn: Callable

    def as_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label,
                "placeholder": self.placeholder}


@dataclass
class Timer:
    id: str
    minutes: float
    fn: Callable

    def as_dict(self) -> dict:
        return {"id": self.id, "minutes": self.minutes}


@dataclass
class ConfigField:
    key: str
    label: str
    default: str = ""

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "default": self.default}


@dataclass
class TagContext:
    """One tag, as an app callback sees it.

    data   - this tag's working data; change it in place, the host saves it
    shared - data shared by every tag running the app, saved the same way
    config - the user's settings for this tag (field defaults filled in)
    db     - the app's own SQLite database for its own tables (None in the
             render CLI); commit what you write
    now    - the time to draw for (the host's clock, so tests can pick one)
    """
    hex_id: str
    alias: str | None
    notes: str | None
    config: dict
    data: dict
    shared: dict
    db: sqlite3.Connection | None
    battery: float | None
    display: DisplayPreset
    now: datetime = field(default_factory=datetime.now)
    logs: list = field(default_factory=list)
    fetch: Callable | None = None           # (url, params, timeout) -> JSON; host-supplied

    def log(self, msg: str) -> None:
        """A line in the app's log (Apps tab), stamped with the tag's id by the host."""
        self.logs.append([time.time(), str(msg)])
        del self.logs[:-LOG_KEEP]

    def fetch_json(self, url: str, params: dict | None = None, timeout: float = 10.0):
        """GET a JSON web API. Use it from @app.every or a button, never from
        @app.data or @app.render: those run on every redraw. Raises on failure; the
        host logs it and keeps the old screen."""
        return (self.fetch or http_json)(url, params, timeout)


class InkApp:
    """An app. Its screen comes from one of two places:

    layout="layout.xml"  an InkLayout file in the app's folder (Documentation/InkLayout.md),
                         filled with what @app.data returns (default: tag.data)
    @app.render          a Python function drawing on a Canvas; wins over a layout
    """

    def __init__(self, app_id: str, title: str = "", description: str = "",
                 layout: str | None = None) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", app_id):
            raise ValueError(f"app id {app_id!r}: use lower-case letters, digits, - and _")
        self.id = app_id
        self.title = title or app_id
        self.description = description
        self.layout = layout
        self.folder = None                      # set by the loader: the app's own folder
        self.render_fn: Callable | None = None
        self.data_fn: Callable | None = None
        self.on_open_fn: Callable | None = None
        self.controls: list[Control] = []
        self.config_fields: list[ConfigField] = []
        self.timers: list[Timer] = []

    # ── declarations ───────────────────────────────────────────────────────
    def config_field(self, key: str, label: str = "", default: str = "") -> None:
        """A per-tag setting the user fills in on the Apps tab (a string for now)."""
        if any(f.key == key for f in self.config_fields):
            raise ValueError(f"config field {key!r} declared twice")
        self.config_fields.append(ConfigField(key, label or key, default))

    def config_defaults(self) -> dict:
        return {f.key: f.default for f in self.config_fields}

    def render(self, fn: Callable) -> Callable:
        """@app.render: fn(tag, canvas) draws the tag's screen."""
        self.render_fn = fn
        return fn

    def data(self, fn: Callable) -> Callable:
        """@app.data: fn(tag) -> dict, what the layout sees as `data`. Read-only: it
        runs on every redraw, so change nothing here (that is what actions are for)."""
        self.data_fn = fn
        return fn

    def layout_path(self):
        """The layout file, or None when the app draws in Python."""
        if not self.layout or self.folder is None:
            return None
        from pathlib import Path
        return Path(self.folder) / self.layout

    def on_open(self, fn: Callable) -> Callable:
        """@app.on_open: fn(tag) runs when a phone opens the tag's page (an NFC tap)."""
        self.on_open_fn = fn
        return fn

    def every(self, minutes: float):
        """@app.every(minutes=30): fn(tag) runs every so often for each tag the app runs
        on, and once when it is put on a tag. The screen is redrawn afterwards and sent
        only if it changed, so a timer that changes nothing costs the tag nothing.
        Draw no clock on the screen unless it is the point: it changes every time."""
        if minutes < MIN_TIMER_MINUTES:
            raise ValueError(f"@app.every: at least {MIN_TIMER_MINUTES} minute")

        def deco(fn: Callable) -> Callable:
            tid = getattr(fn, "__name__", "timer")
            if any(t.id == tid for t in self.timers):
                tid = f"{tid}-{len(self.timers) + 1}"
            self.timers.append(Timer(tid, float(minutes), fn))
            return fn
        return deco

    def _add(self, kind, label: str, action_id: str | None, placeholder: str = ""):
        cid = action_id or slug(label)

        def deco(fn: Callable) -> Callable:
            if self.action(cid) is not None:
                raise ValueError(f"action {cid!r} declared twice in app {self.id!r}")
            self.controls.append(Control(cid, kind, label, placeholder, fn))
            return fn
        return deco

    def button(self, label: str, id: str | None = None):  # noqa: A002 - reads well for authors
        """@app.button("Took my pill"): fn(tag) runs when the button is pressed."""
        return self._add("button", label, id)

    def text_input(self, label: str, placeholder: str = "", id: str | None = None):  # noqa: A002
        """@app.text_input("Message"): fn(tag, text) runs when text is sent."""
        return self._add("text", label, id, placeholder)

    # ── lookups ────────────────────────────────────────────────────────────
    def action(self, action_id: str) -> Control | None:
        return next((c for c in self.controls if c.id == action_id), None)

    def describe(self) -> dict:
        return {"id": self.id, "title": self.title, "description": self.description,
                "controls": [c.as_dict() for c in self.controls],
                "config_fields": [f.as_dict() for f in self.config_fields],
                "has_render": self.render_fn is not None or bool(self.layout),
                "layout": self.layout if self.render_fn is None else None,
                "has_on_open": self.on_open_fn is not None,
                "timers": [t.as_dict() for t in self.timers]}
