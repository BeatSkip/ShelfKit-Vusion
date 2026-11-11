"""AppHost: runs the apps for the server.

It owns three things:

* **bindings** - which app owns which tag's screen (main store, `app_bindings`),
* **one AppStore per app** - the app's own database, `inkapps/<id>/data/app.db`,
* **the path to the panel** - render the app's screen, and queue it for the tag
  unless it is identical to what was queued last (every push costs tag battery).

App code only ever sees a TagContext and a Canvas. Every call into an app is
wrapped: an exception becomes an error result plus a line in that app's log, and
nothing is pushed. One lock per app serialises its callbacks, since the phone page
and the admin UI can call at the same moment.

The host is given its collaborators instead of reaching for the App:

    enqueue(kind, addr, label, **params) -> dict     App.enqueue
    tag_info(hex_id) -> {"alias", "notes", "battery", "display"}
    fetch(url, params, timeout) -> JSON           what tag.fetch_json uses (default: HTTP)
    clock() -> datetime                           the time apps draw for (tests pick one)

Timers (@app.every) run on a scheduler thread (start_scheduler). They run once when an
app is put on a tag. After a server start the first pass only learns them, so a
restart does not set off a burst of fetches: each runs one interval later. A timer
that fails waits its full interval too, so there is no retry loop against a dead web
API. Timer runs are logged only when they push or fail.
"""

from __future__ import annotations

import hashlib
import io
import threading
import time
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable

from PIL import Image

from .. import displays
from .appstore import AppStore, app_db_path
from .loader import INKAPPS_DIR, LoadedApp, load_apps
from .screen import AppError, LayoutError, draw_screen
from .sdk import InkApp, TagContext, http_json

LOG_LINES = 200
DEFAULT_IMAGE_DIR = Path(__file__).resolve().parents[2] / "data" / "apps"

__all__ = ["AppError", "AppHost", "LayoutError"]


class AppHost:
    def __init__(self, store, enqueue: Callable[..., dict], tag_info: Callable[[str], dict],
                 root: Path = INKAPPS_DIR, image_dir: Path = DEFAULT_IMAGE_DIR,
                 fetch: Callable | None = None, clock: Callable[[], datetime] = datetime.now
                 ) -> None:
        self.store = store
        self.enqueue = enqueue
        self.tag_info = tag_info
        self.fetch = fetch or http_json
        self.clock = clock
        self._due: dict[tuple[str, str, str], float] = {}     # (app, tag, timer) -> when
        self._scheduler: threading.Thread | None = None
        self._stop = threading.Event()
        self.root = Path(root)
        self.image_dir = Path(image_dir)
        self._lock = threading.RLock()
        self._app_locks: dict[str, threading.RLock] = {}
        self._stores: dict[str, AppStore] = {}
        self._logs: dict[str, deque] = {}
        self.loaded: dict[str, LoadedApp] = {}
        self.reload()

    # ── apps ───────────────────────────────────────────────────────────────
    def reload(self) -> dict[str, LoadedApp]:
        """Import every app afresh (picks up edits). Stores stay open."""
        loaded = load_apps(self.root)
        with self._lock:
            self.loaded = loaded
        for item in loaded.values():
            if item.error:
                self._log(item.id, f"load failed: {item.error}")
        return loaded

    def apps(self) -> list[dict]:
        bound: dict[str, list[str]] = {}
        for b in self.store.app_bindings():
            bound.setdefault(b["app_id"], []).append(b["hex_id"])
        out = []
        for item in self.loaded.values():
            entry = (item.app.describe() if item.app else
                     {"id": item.id, "title": item.id, "description": "", "controls": [],
                      "config_fields": [], "has_render": False, "has_on_open": False,
                      "timers": []})
            entry.update(error=item.error, tags=bound.get(item.id, []))
            out.append(entry)
        return out

    def _app(self, app_id: str) -> InkApp:
        item = self.loaded.get(app_id)
        if item is None:
            raise AppError(f"no app {app_id!r} in {self.root}")
        if item.app is None:
            raise AppError(f"app {app_id!r} did not load: {item.error}")
        return item.app

    def store_of(self, app_id: str) -> AppStore:
        """The app's own database, opened on first use."""
        with self._lock:
            st = self._stores.get(app_id)
            if st is None:
                item = self.loaded.get(app_id)
                folder = item.path if item else self.root / app_id
                st = self._stores[app_id] = AppStore(app_db_path(folder), app_id)
            return st

    def app_data(self, app_id: str) -> dict:
        """What the app has stored, for the Apps tab: per tag its settings (defaults
        filled in) and data, the shared document, and its own tables with row counts."""
        item = self.loaded.get(app_id)
        if item is None:                       # never create a folder for a stray id
            return {"ok": False, "error": f"no app {app_id!r} in {self.root}"}
        path = app_db_path(item.path)
        bound = {b["hex_id"]: b for b in self.store.app_bindings() if b["app_id"] == app_id}
        with self._lock:
            opened = app_id in self._stores
        if not opened and not path.exists() and not bound:     # looking writes nothing
            return {"ok": True, "app": app_id, "path": str(path), "size": 0, "shared": {},
                    "tags": [], "tables": []}
        st = self.store_of(app_id)
        dump = st.dump()
        defaults = item.app.config_defaults() if item.app else {}
        hexes = sorted((set(dump["config"]) | set(dump["state"]) | set(bound)) - {""})
        tags = [{"hex_id": hx, "bound": hx in bound,
                 "config": {**defaults, **dump["config"].get(hx, {})},
                 "state": dump["state"].get(hx, {}),
                 "updated": dump["updated"].get(hx),
                 "last_push_at": (bound.get(hx) or {}).get("last_push_at")}
                for hx in hexes]
        size = sum(p.stat().st_size for p in st.path.parent.glob(st.path.name + "*")
                   if p.is_file())
        return {"ok": True, "app": app_id, "path": str(st.path), "size": size,
                "shared": dump["state"].get("", {}), "tags": tags, "tables": dump["tables"]}

    def _app_lock(self, app_id: str) -> threading.RLock:
        with self._lock:
            return self._app_locks.setdefault(app_id, threading.RLock())

    def close(self) -> None:
        self.stop_scheduler()
        with self._lock:
            for st in self._stores.values():
                st.close()
            self._stores.clear()

    # ── log ────────────────────────────────────────────────────────────────
    def _log(self, app_id: str, line: str) -> None:
        with self._lock:
            self._logs.setdefault(app_id, deque(maxlen=LOG_LINES)).append([time.time(), line])

    def log(self, app_id: str) -> list[list]:
        with self._lock:
            return [list(x) for x in self._logs.get(app_id, ())]

    def _failed(self, app_id: str, hex_id: str, what: str, exc: BaseException) -> dict:
        tail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)[-2:])
        self._log(app_id, f"[{hex_id}] {what} failed: {type(exc).__name__}: {exc}\n{tail.strip()}")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # ── bindings ───────────────────────────────────────────────────────────
    def bind(self, hex_id: str, app_id: str, config: dict | None = None) -> dict:
        """Give the tag's screen to the app, save its settings, push its first screen."""
        hex_id = hex_id.upper()
        try:
            self._app(app_id)
        except AppError as exc:
            return {"ok": False, "error": str(exc)}
        if config is not None:
            self.store_of(app_id).set_config(hex_id, dict(config))
        self.store.bind_app(hex_id, app_id)
        self._log(app_id, f"[{hex_id}] bound")
        self._forget_due(hex_id)
        self._run_timers(hex_id)                 # fresh data before the first screen
        return self.refresh(hex_id, force=True)

    def unbind(self, hex_id: str) -> dict:
        """The tag no longer runs an app. Its data stays in the app's store."""
        hex_id = hex_id.upper()
        binding = self.store.app_binding(hex_id)
        self.store.unbind_app(hex_id)
        self._forget_due(hex_id)
        if binding:
            self._log(binding["app_id"], f"[{hex_id}] unbound")
        return {"ok": True}

    def set_config(self, hex_id: str, config: dict) -> dict:
        hex_id = hex_id.upper()
        binding = self.store.app_binding(hex_id)
        if binding is None:
            return {"ok": False, "error": f"tag {hex_id} runs no app"}
        self.store_of(binding["app_id"]).set_config(hex_id, dict(config))
        return self.refresh(hex_id)

    def rename_tag(self, old_hex: str, new_hex: str) -> None:
        """The tag got a new id: every app's data for it follows (the binding itself
        is moved by Store.rename_tag)."""
        for st in self._existing_stores():
            st.rename_tag(old_hex, new_hex)

    def forget_tags(self, hex_ids) -> None:
        for st in self._existing_stores():
            for hex_id in hex_ids:
                st.forget_tag(hex_id)

    def _existing_stores(self) -> list[AppStore]:
        """The stores of apps that have stored something: an app that never stored
        anything has nothing to rename or forget, and gets no database for it."""
        with self._lock:
            opened = set(self._stores)
        return [self.store_of(app_id) for app_id, item in self.loaded.items()
                if app_id in opened or app_db_path(item.path).exists()]

    # ── drawing ────────────────────────────────────────────────────────────
    def _peek_store(self, app_id: str) -> tuple[AppStore, bool]:
        """(store, throwaway). An app that has stored nothing gets an empty in-memory
        store, so looking at it (a preview) writes no file; close a throwaway after use."""
        with self._lock:
            opened = self._stores.get(app_id)
        if opened is not None:
            return opened, False
        item = self.loaded.get(app_id)
        if app_db_path(item.path if item else self.root / app_id).exists():
            return self.store_of(app_id), False
        return AppStore(":memory:", app_id), True

    def _context(self, app: InkApp, hex_id: str, st: AppStore | None = None) -> TagContext:
        info = {}
        try:
            info = self.tag_info(hex_id) or {}
        except Exception:  # noqa: BLE001 - the tag's details are a nicety
            pass
        st = st or self.store_of(app.id)
        return TagContext(
            hex_id=hex_id, alias=info.get("alias"), notes=info.get("notes"),
            config={**app.config_defaults(), **st.config(hex_id)},
            data=st.state(hex_id), shared=st.state(""), db=st.sql,
            battery=info.get("battery"), display=displays.preset(info.get("display")),
            now=self.clock(), fetch=self.fetch,
        )

    def _draw(self, app: InkApp, tag: TagContext):
        """(image, layout result or None); layout warnings go to the app's log."""
        try:
            image, result = draw_screen(app, tag)
        except LayoutError as exc:
            for d in exc.result.diagnostics:
                self._log(app.id, f"[{tag.hex_id}] layout {d['level']}: {d['at']}: {d['msg']}")
            raise
        if result is not None:
            for d in result.diagnostics:
                if d["level"] != "info":
                    self._log(app.id, f"[{tag.hex_id}] layout {d['level']}: {d['at']}: {d['msg']}")
        return image, result

    def _flush_logs(self, app_id: str, tag: TagContext) -> None:
        for _, line in tag.logs:
            self._log(app_id, f"[{tag.hex_id}] {line}")
        tag.logs.clear()

    @staticmethod
    def _png(image: Image.Image) -> bytes:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    def _render(self, app_id: str, hex_id: str):
        """Draw the app's screen for a tag without pushing: (image, layout result)."""
        app = self._app(app_id)
        with self._app_lock(app_id):
            st, throwaway = self._peek_store(app_id)
            tag = self._context(app, hex_id.upper(), st)
            try:
                return self._draw(app, tag)
            except AppError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise AppError(self._failed(app_id, tag.hex_id, "render", exc)["error"]) from exc
            finally:
                self._flush_logs(app_id, tag)
                if throwaway:
                    st.close()

    def preview_png(self, app_id: str, hex_id: str = "0000") -> bytes:
        """What the app would show on this tag, without binding or pushing anything."""
        return self._png(self._render(app_id, hex_id)[0])

    def _bound(self, hex_id: str) -> str:
        binding = self.store.app_binding(hex_id.upper())
        if binding is None:
            raise AppError(f"tag {hex_id.upper()} runs no app")
        return binding["app_id"]

    def render_png(self, hex_id: str) -> bytes:
        """The bound app's current screen for this tag."""
        return self.preview_png(self._bound(hex_id), hex_id)

    def layout_result(self, hex_id: str, app_id: str | None = None):
        """The InkLayout result (diagnostics, boxes) of the tag's screen; None for an
        app that draws in Python."""
        return self._render(app_id or self._bound(hex_id), hex_id)[1]

    def refresh(self, hex_id: str, force: bool = False) -> dict:
        """Draw the tag's screen and queue it, unless it equals what was queued last."""
        from .. import preview

        hex_id = hex_id.upper()
        binding = self.store.app_binding(hex_id)
        if binding is None:
            return {"ok": False, "error": f"tag {hex_id} runs no app"}
        app_id = binding["app_id"]
        try:
            app = self._app(app_id)
        except AppError as exc:
            return {"ok": False, "error": str(exc)}

        with self._app_lock(app_id):
            tag = self._context(app, hex_id)
            try:
                image, _ = self._draw(app, tag)
            except AppError as exc:
                return {"ok": False, "error": str(exc)}
            except Exception as exc:  # noqa: BLE001 - app code
                return self._failed(app_id, hex_id, "render", exc)
            finally:
                self._flush_logs(app_id, tag)

            self.image_dir.mkdir(parents=True, exist_ok=True)
            path = self.image_dir / f"{hex_id}.png"
            image.save(path, format="PNG")
            rendered = preview.render(path, "stretch", "threshold")
            digest = hashlib.sha1(rendered.bw + rendered.red).hexdigest()
            if not force and digest == binding.get("last_hash"):
                return {"ok": True, "pushed": False, "skipped": "identical"}

            queued = self.enqueue("image", int(hex_id, 16), f"app {app_id}",
                                  path=str(path), fit="stretch", dither="threshold",
                                  source="app")
            if not queued.get("ok"):
                return {"ok": False, "error": queued.get("error") or "could not queue the image"}
            self.store.set_app_pushed(hex_id, digest, time.time())
        return {"ok": True, "pushed": True, "skipped": None}

    # ── callbacks ──────────────────────────────────────────────────────────
    def _call(self, hex_id: str, what: str, pick: Callable[[InkApp], Callable | None],
              *args, quiet: bool = False, refresh: bool = True) -> dict:
        hex_id = hex_id.upper()
        binding = self.store.app_binding(hex_id)
        if binding is None:
            return {"ok": False, "error": f"tag {hex_id} runs no app"}
        app_id = binding["app_id"]
        try:
            app = self._app(app_id)
        except AppError as exc:
            return {"ok": False, "error": str(exc)}
        fn = pick(app)
        if fn is None:
            return {"ok": False, "error": f"app {app_id!r} has no {what}"}

        with self._app_lock(app_id):
            tag = self._context(app, hex_id)
            failure = None
            try:
                fn(tag, *args)
            except Exception as exc:  # noqa: BLE001 - app code
                failure = self._failed(app_id, hex_id, what, exc)
            finally:
                # saved even after an exception: losing a half-made change is worse
                st = self.store_of(app_id)
                st.set_state(hex_id, tag.data)
                st.set_state("", tag.shared)
                self._flush_logs(app_id, tag)
        if failure:
            return failure
        if not refresh:
            return {"ok": True, "pushed": False, "skipped": None}
        result = self.refresh(hex_id)
        if not (quiet and result.get("ok") and not result.get("pushed")):
            outcome = ("screen queued" if result.get("pushed") else
                       "screen unchanged" if result.get("ok") else result.get("error"))
            self._log(app_id, f"[{hex_id}] {what}: {outcome}")
        return result

    def run_action(self, hex_id: str, action_id: str, value: str | None = None) -> dict:
        """A button press or a text sent from the tag's page."""
        def pick(app):
            control = app.action(action_id)
            return control.fn if control else None

        binding = self.store.app_binding(hex_id.upper())
        if binding is not None:
            try:
                control = self._app(binding["app_id"]).action(action_id)
            except AppError:
                control = None
            if control is not None and control.kind == "text":
                return self._call(hex_id, f"action {action_id!r}", pick, str(value or ""))
        return self._call(hex_id, f"action {action_id!r}", pick)

    def opened(self, hex_id: str) -> dict:
        """A phone opened the tag's page (an NFC tap). Runs @app.on_open if there is one."""
        binding = self.store.app_binding(hex_id.upper())
        if binding is not None:
            try:
                if self._app(binding["app_id"]).on_open_fn is None:
                    return {"ok": True, "pushed": False, "skipped": "no on_open"}
            except AppError as exc:
                return {"ok": False, "error": str(exc)}
        return self._call(hex_id, "on_open", lambda app: app.on_open_fn)

    # ── timers ─────────────────────────────────────────────────────────────
    def _forget_due(self, hex_id: str) -> None:
        with self._lock:
            for key in [k for k in self._due if k[1] == hex_id]:
                del self._due[key]

    def _timers_of(self, hex_id: str):
        """(app_id, [Timer]) for the tag's app; (None, []) for a tag without one."""
        binding = self.store.app_binding(hex_id)
        if binding is None:
            return None, []
        item = self.loaded.get(binding["app_id"])
        if item is None or item.app is None:
            return binding["app_id"], []
        return binding["app_id"], list(item.app.timers)

    def _run_timers(self, hex_id: str) -> None:
        """Every timer of the tag's app, now, without redrawing (the caller does)."""
        _, timers = self._timers_of(hex_id)
        for timer in timers:
            self._call(hex_id, f"timer {timer.id}", lambda app, fn=timer.fn: fn,
                       quiet=True, refresh=False)

    def update_now(self, hex_id: str) -> dict:
        """The Apps tab's Refresh now: run the app's timers (fresh data), redraw, and
        send the screen if it changed."""
        hex_id = hex_id.upper()
        self._run_timers(hex_id)
        return self.refresh(hex_id)

    def run_due(self, now: float | None = None) -> int:
        """Run every due timer for every bound tag; returns how many ran. `now` is a
        monotonic time. A timer seen for the first time is only scheduled."""
        now = time.monotonic() if now is None else now
        ran = 0
        live = set()
        for b in self.store.app_bindings():
            app_id, timers = self._timers_of(b["hex_id"])
            for timer in timers:
                key = (app_id, b["hex_id"], timer.id)
                live.add(key)
                with self._lock:
                    due = self._due.get(key)
                    if due is None or now < due:
                        if due is None:
                            self._due[key] = now + timer.minutes * 60
                        continue
                    self._due[key] = now + timer.minutes * 60    # also when it fails
                if self._stop.is_set() and self._scheduler is not None:
                    return ran                                   # shutting down
                self._call(b["hex_id"], f"timer {timer.id}", lambda app, fn=timer.fn: fn,
                           quiet=True)
                ran += 1
        with self._lock:
            for key in [k for k in self._due if k not in live]:
                del self._due[key]
        return ran

    def start_scheduler(self, interval: float = 15.0) -> None:
        """Check the timers every `interval` seconds, on a daemon thread."""
        if self._scheduler is not None and self._scheduler.is_alive():
            return
        self._stop.clear()

        def loop() -> None:
            while not self._stop.wait(interval):
                try:
                    self.run_due()
                except Exception as exc:  # noqa: BLE001 - the scheduler must keep going
                    self._log("_host", f"scheduler: {type(exc).__name__}: {exc}")

        self._scheduler = threading.Thread(target=loop, name="inkservices-timers", daemon=True)
        self._scheduler.start()

    def stop_scheduler(self, wait: float = 5.0) -> None:
        self._stop.set()
        thread, self._scheduler = self._scheduler, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(wait)
