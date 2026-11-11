"""HTTP routes for InkServices and InkLayout (admin side, 127.0.0.1 only).

    GET  /api/inkapps                         apps, bindings, known tags
    GET  /api/inkapps/preview.png?app=&tag=   an app's screen for a tag (nothing pushed)
    GET  /api/inkapps/log?app=                the app's log
    GET  /api/inkapps/data?app=               what the app has stored (settings, data, tables)
    GET  /api/inkapps/layout?app=             the app's layout file, as text
    POST /api/inkapps/reload                  re-import every app (picks up edits)
    POST /api/inkapps/bind     {tag, app, config?}
    POST /api/inkapps/unbind   {tag}
    POST /api/inkapps/config   {tag, config}
    POST /api/inkapps/action   {tag, action, value?}     what a phone button will do
    POST /api/inkapps/open     {tag}                     what an NFC tap will do
    POST /api/inkapps/refresh  {tag, force?}    runs the app's timers, then redraws;
                                                force: redraw and send, no timers
    POST /api/layout/render    {layout, data?, tag?, display?}
                               -> {ok, png (base64), diagnostics, boxes, layout, display}
    GET  /api/layout/displays                 the display presets
    GET  /api/layout/skill?display=&orientation=   the InkLayout skill file (Markdown)

webapp.Handler calls handle_get / handle_post first; they return False for a path
that is not theirs.
"""

from __future__ import annotations

import base64
import io
from http import HTTPStatus

from .. import displays, inklayout
from .screen import AppError

_HEX = set("0123456789ABCDEF")


def _hex(value) -> str | None:
    tag = str(value or "").strip().upper()
    return tag if tag and len(tag) <= 4 and set(tag) <= _HEX else None


def _host(handler):
    host = getattr(handler.app, "inkhost", None)
    if host is None:
        handler._error("InkServices is off (the server runs without a store)",
                       HTTPStatus.SERVICE_UNAVAILABLE)
    return host


def _tags(app) -> list[dict]:
    with app.lock:
        known = sorted(set(app.tags) | set(app.tag_meta))
        return [{"id": f"{a:04X}", "alias": (app.tag_meta.get(a) or {}).get("alias")}
                for a in known]


def handle_get(handler, path: str, query: dict) -> bool:
    if path == "/api/layout/displays":
        handler._json({"displays": displays.presets(), "default": displays.DEFAULT_PRESET})
        return True
    if path == "/api/layout/skill":
        from ..inklayout import skill
        q = {k: (v or [""])[0] for k, v in query.items()}
        orientation = "landscape" if q.get("orientation") == "landscape" else "portrait"
        md = skill.skill_markdown(q.get("display") or None, orientation)
        handler._send(HTTPStatus.OK, md.encode("utf-8"), "text/markdown; charset=utf-8")
        return True
    if not path.startswith("/api/inkapps"):
        return False
    host = _host(handler)
    if host is None:
        return True
    q = {k: (v or [""])[0] for k, v in query.items()}
    if path == "/api/inkapps":
        base, local = handler.app.tag_page_base()
        handler._json({"apps": host.apps(), "bindings": host.store.app_bindings(),
                       "tags": _tags(handler.app),
                       "phone_base": base, "phone_base_local": local})
    elif path == "/api/inkapps/preview.png":
        tag = _hex(q.get("tag") or "0000")
        if tag is None:
            handler._error("tag is a hex id such as 0101")
            return True
        try:
            png = (host.preview_png(q["app"], tag) if q.get("app") else host.render_png(tag))
        except AppError as exc:
            handler._error(str(exc), HTTPStatus.UNPROCESSABLE_ENTITY)
            return True
        handler._send(HTTPStatus.OK, png, "image/png")
    elif path == "/api/inkapps/data":
        result = host.app_data(q.get("app", ""))
        if not result.get("ok"):
            handler._error(result["error"], HTTPStatus.NOT_FOUND)
            return True
        handler._json(result)
    elif path == "/api/inkapps/log":
        handler._json({"log": host.log(q.get("app", ""))})
    elif path == "/api/inkapps/layout":
        item = host.loaded.get(q.get("app", ""))
        layout = item.app.layout_path() if item and item.app else None
        if layout is None or not layout.is_file():
            handler._error("that app has no layout file", HTTPStatus.NOT_FOUND)
            return True
        handler._send(HTTPStatus.OK, layout.read_bytes(), "text/plain; charset=utf-8")
    else:
        handler._error(f"no such path {path}", HTTPStatus.NOT_FOUND)
    return True


def handle_post(handler, path: str, body: dict) -> bool:
    if path == "/api/layout/render":
        result = inklayout.render(str(body.get("layout") or ""),
                                  body.get("data") if isinstance(body.get("data"), dict) else {},
                                  tag=body.get("tag") if isinstance(body.get("tag"), dict) else None,
                                  display=body.get("display") or None)
        buf = io.BytesIO()
        result.image.save(buf, format="PNG")
        handler._json({"ok": result.ok, "png": base64.b64encode(buf.getvalue()).decode("ascii"),
                       "diagnostics": result.diagnostics, "boxes": result.boxes,
                       "layout": result.layout, "display": result.display,
                       "size": list(result.image.size)})
        return True
    if not path.startswith("/api/inkapps"):
        return False
    host = _host(handler)
    if host is None:
        return True
    if path == "/api/inkapps/reload":
        host.reload()
        handler._json({"ok": True, "apps": host.apps()})
        return True

    tag = _hex(body.get("tag"))
    if tag is None:
        handler._error("tag is a hex id such as 0101")
        return True
    if path == "/api/inkapps/bind":
        config = body.get("config") if isinstance(body.get("config"), dict) else None
        handler._json(host.bind(tag, str(body.get("app") or ""), config))
    elif path == "/api/inkapps/unbind":
        handler._json(host.unbind(tag))
    elif path == "/api/inkapps/config":
        config = body.get("config")
        if not isinstance(config, dict):
            handler._error("config is an object of field: value")
            return True
        handler._json(host.set_config(tag, config))
    elif path == "/api/inkapps/action":
        value = body.get("value")
        handler._json(host.run_action(tag, str(body.get("action") or ""),
                                      None if value is None else str(value)))
    elif path == "/api/inkapps/open":
        handler._json(host.opened(tag))
    elif path == "/api/inkapps/refresh":
        if body.get("force"):
            handler._json(host.refresh(tag, force=True))
        else:                                   # Refresh now: fresh data, then redraw
            handler._json(host.update_now(tag))
    else:
        handler._error(f"no such path {path}", HTTPStatus.NOT_FOUND)
    return True
