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
    tokens: Callable | None = None          # name -> str | None; Settings > AI services
    vars: dict = field(default_factory=dict)   # the app's variables (Develop > Settings)
    secrets: Callable | None = None         # name -> str | None; the app's secrets, then API tokens

    def log(self, msg: str) -> None:
        """A line in the app's log (Apps tab), stamped with the tag's id by the host."""
        self.logs.append([time.time(), str(msg)])
        del self.logs[:-LOG_KEEP]

    def fetch_json(self, url: str, params: dict | None = None, timeout: float = 10.0):
        """GET a JSON web API. Use it from @app.every or a button, never from
        @app.data or @app.render: those run on every redraw. Raises on failure; the
        host logs it and keeps the old screen."""
        return (self.fetch or http_json)(url, params, timeout)

    def token(self, name: str) -> str | None:
        """An API token the owner saved under Settings > AI services > API tokens
        (a weather service's key, say), so it never has to be written in app.py.
        None when there is no token by that name."""
        return self.tokens(name) if self.tokens else None

    def var(self, name: str, default: str | None = None) -> str | None:
        """A variable of the app, set in Develop > Settings (the same for every tag):
        a city, a URL, a threshold. Always a string; default when it is not set."""
        return self.vars.get(name, default)

    def secret(self, name: str) -> str | None:
        """A secret of the app (an API key, a password), set in Develop > Settings and never
        written in the app's files. Falls back to the global API token of the same name
        (Settings > AI services). None when neither exists."""
        if self.secrets:
            return self.secrets(name)
        return self.token(name)


PAGE_LIMIT = 60          # blocks on a phone page


def page_blocks(items) -> list[dict]:
    """What @app.page returns, checked and made uniform: [{kind, text, value?, url?}].

        "a paragraph"                          kind text
        ("Label", "value")                     kind fact (a row of a small table)
        {"heading": "This week"}               kind heading
        {"note": "small, grey"}                kind note
        {"link": "Forecast", "url": "https://..."}   kind link (http and https only)
    """
    if items is None:
        return []
    if isinstance(items, (str, tuple, dict)):
        items = [items]
    out = []
    for item in list(items)[:PAGE_LIMIT]:
        if isinstance(item, str):
            out.append({"kind": "text", "text": item})
        elif isinstance(item, tuple) and len(item) == 2:
            out.append({"kind": "fact", "text": str(item[0]), "value": str(item[1])})
        elif isinstance(item, dict) and "heading" in item:
            out.append({"kind": "heading", "text": str(item["heading"])})
        elif isinstance(item, dict) and "note" in item:
            out.append({"kind": "note", "text": str(item["note"])})
        elif isinstance(item, dict) and "link" in item:
            url = str(item.get("url") or "")
            if not re.match(r"https?://", url):
                raise ValueError(f"page link {item['link']!r}: the url must start with http:// or https://")
            out.append({"kind": "link", "text": str(item["link"]), "url": url})
        else:
            raise ValueError(f"@app.page: cannot show {item!r} (use a string, a (label, value) pair, "
                             "or a dict with heading, note or link)")
    return out


class InkApp:
    """An app. Its screen comes from one of two places:

    layout="layout.xml"  an InkLayout file in the app's folder (Documentation/InkLayout.md),
                         filled with what @app.data returns (default: tag.data)
    @app.render          a Python function drawing on a Canvas; wins over a layout

    icon="pill" picks the app's icon on the Apps tab from InkLayout's pixel icons
    (the same ones <icon name="..."> draws); without one the tab shows its initial.
    """

    def __init__(self, app_id: str, title: str = "", description: str = "",
                 layout: str | None = None, icon: str | None = None,
                 phone_screen: bool = True) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", app_id):
            raise ValueError(f"app id {app_id!r}: use lower-case letters, digits, - and _")
        self.id = app_id
        self.title = title or app_id
        self.description = description
        self.layout = layout
        self.icon = icon or None
        self.folder = None                      # set by the loader: the app's own folder
        self.render_fn: Callable | None = None
        self.data_fn: Callable | None = None
        self.on_open_fn: Callable | None = None
        self.page_fn: Callable | None = None
        self.phone_screen = bool(phone_screen)  # the phone page shows the tag's screen at the top
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

    def page(self, fn: Callable) -> Callable:
        """@app.page: fn(tag) returns extra content for the phone page (what an NFC tap
        opens), shown under the tag's screen and above the buttons. Return a list of:
            "a paragraph"                          plain text
            ("Label", "value")                     a row of a small table of facts
            {"heading": "This week"}               a heading
            {"note": "small, grey text"}
            {"link": "Forecast", "url": "https://..."}
        It runs on every page view, so it only reads (tag.data, tag.var...); never fetch.
        The page has no scripts and no HTML of the app's own: this is all it can add.
        InkApp(..., phone_screen=False) leaves the tag's screen off the page."""
        self.page_fn = fn
        return fn

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
                "icon": self.icon,
                "controls": [c.as_dict() for c in self.controls],
                "config_fields": [f.as_dict() for f in self.config_fields],
                "has_render": self.render_fn is not None or bool(self.layout),
                "layout": self.layout if self.render_fn is None else None,
                "has_on_open": self.on_open_fn is not None,
                "has_page": self.page_fn is not None,
                "timers": [t.as_dict() for t in self.timers]}
