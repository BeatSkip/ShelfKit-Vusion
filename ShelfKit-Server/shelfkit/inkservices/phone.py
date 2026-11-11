"""The tag pages: what opens when someone taps a tag with their phone.

Served by the main server, on its own port, always:

    GET  /tag/<ID>             the NFC link: runs the app's @app.on_open, then 303 to view
    GET  /tag/<ID>/view        the app's page: its current screen and its controls
    GET  /tag/<ID>/screen.png  the tag's current screen
    POST /tag/<ID>/do          a button or a text field (action=, value=), then 303 to view
    GET  /t/<ID>[/...]         older links: 301 to the same page under /tag/

Every link, redirect and form on these pages is relative, so a reverse proxy can put
them under any address or sub-path (https://home.example/shelf/tag/0101) without the
server knowing. To reach them from phones, forward /tag/ (and /t/) to this server and
nothing else: the rest of this port is the admin page, which drives serial ports and
flashes firmware. Settings > "Address phones use" makes the Apps tab show the links
with the proxy's address.

Plain HTML forms, no script, under a Content-Security-Policy that allows none: it has
to work in whatever browser a phone opens an NFC link with. Opening the link twice
within OPEN_DEBOUNCE_S counts once (phones sometimes fire the NFC intent twice), and
the redirect means a reload of the page never re-runs on_open.
"""

from __future__ import annotations

import html
import threading
import time
from http import HTTPStatus
from urllib.parse import parse_qs, quote, urlparse

from .screen import AppError

PREFIX = "tag"
LEGACY_PREFIX = "t"
OPEN_DEBOUNCE_S = 10.0
FORM_LIMIT = 16384
_HEX = set("0123456789ABCDEF")
POLL_NOTE = "The tag shows it after its next check-in, within about 5 minutes."
CSP = ("default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; form-action 'self'; "
       "frame-ancestors 'none'; base-uri 'none'")

_opened: dict = {}              # (id(app), tag) -> when its link was last opened
_opened_lock = threading.Lock()


def _tag_id(raw: str) -> str | None:
    tag = raw.strip().upper()
    if not tag or len(tag) > 4 or not set(tag) <= _HEX:
        return None
    return tag.zfill(4)


_STYLE = """
:root { --bg:#ecebe4; --card:#f7f7f3; --ink:#1c1e20; --ink2:#4a4e52; --rule:#b7b9b5;
        --red:#b0121a; --btn:#1c1e20; --btn-ink:#f2f2ec; color-scheme: light dark; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#2e3337; --card:#383e43; --ink:#eeefea; --ink2:#b8bdbf; --rule:#646b70;
          --red:#ff8a84; --btn:#eeefea; --btn-ink:#24282b; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:16px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
main { max-width:480px; margin:0 auto; padding:16px; }
h1 { font-size:1.4rem; margin:0; }
.sub { color:var(--ink2); font-size:.9rem; margin:2px 0 16px; }
.tag { display:flex; justify-content:center; margin:0 0 16px; }
.tag img { width:228px; max-width:70vw; height:auto; image-rendering:pixelated; background:#fff;
           border:8px solid var(--card); outline:1px solid var(--rule); border-radius:6px; }
.msg { padding:10px 12px; border-radius:6px; margin:0 0 14px; background:var(--card);
       border-left:4px solid var(--ink); }
.msg.err { border-left-color:var(--red); color:var(--red); }
form { margin:0 0 10px; }
button { width:100%; min-height:48px; font:inherit; font-weight:600; border-radius:6px;
         border:1px solid var(--btn); background:var(--btn); color:var(--btn-ink); cursor:pointer; }
.text { display:flex; gap:8px; }
.text input { flex:1 1 auto; min-width:0; min-height:48px; font:inherit; padding:8px 10px;
              border-radius:6px; border:1px solid var(--rule); background:var(--card); color:var(--ink); }
.text button { width:auto; padding:0 16px; }
.foot { color:var(--ink2); font-size:.85rem; margin-top:18px; }
"""


def _page(title: str, body: str) -> bytes:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head>"
            f"<body><main>{body}</main></body></html>").encode("utf-8")


# ── plumbing ───────────────────────────────────────────────────────────────
def _send(handler, status: int, body: bytes, ctype: str) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Security-Policy", CSP)
    # same-origin, not no-referrer: under no-referrer browsers send "Origin: null" with
    # a form post, and the cross-site check below would refuse the page's own buttons
    handler.send_header("Referrer-Policy", "same-origin")
    handler.end_headers()
    handler.wfile.write(body)


def _redirect(handler, location: str, status: int = HTTPStatus.SEE_OTHER) -> None:
    handler.send_response(status)
    handler.send_header("Location", location)
    handler.send_header("Content-Length", "0")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()


def _not_found(handler) -> None:
    _send(handler, HTTPStatus.NOT_FOUND, _page("Not found", "<h1>Not found</h1>"),
          "text/html; charset=utf-8")


def _same_site(handler) -> bool:
    """A browser names the page a POST came from. Accept this server, or the address a
    reverse proxy says it was reached at; a form on another site can set neither."""
    origin = handler.headers.get("Origin")
    if not origin:
        return True
    netloc = urlparse(origin).netloc
    forwarded = (handler.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
    return netloc in {handler.headers.get("Host"), forwarded} - {"", None}


def _route(path: str):
    """(prefix, tag, rest, trailing_slash, parts) for /tag/<ID>[/rest] or /t/..., else None."""
    if not path.startswith(("/tag/", "/t/")):
        return None
    parts = path.strip("/").split("/")
    if len(parts) < 2 or len(parts) > 3 or parts[0] not in (PREFIX, LEGACY_PREFIX):
        return None
    tag = _tag_id(parts[1])
    if tag is None:
        return None
    return parts[0], tag, (parts[2] if len(parts) == 3 else ""), path.endswith("/"), parts


def _host(handler):
    return getattr(handler.app, "inkhost", None)


# ── GET ────────────────────────────────────────────────────────────────────
def handle_get(handler, path: str, raw_query: str) -> bool:
    """Serve a tag page; False when the path is not one (the caller goes on)."""
    if not path.startswith(("/tag/", "/t/")):
        return False
    route = _route(path)
    host = _host(handler)
    if route is None or host is None:
        _not_found(handler)
        return True
    prefix, tag, rest, slash, parts = route
    if prefix == LEGACY_PREFIX:                       # /t/0101/view -> ../../tag/0101/view
        depth = len(parts) - (0 if slash else 1)
        _redirect(handler, "../" * depth + "/".join([PREFIX, *parts[1:]]),
                  HTTPStatus.MOVED_PERMANENTLY)
        return True
    if rest == "":
        _open(handler, host, tag, slash)
    elif rest == "view":
        query = parse_qs(raw_query)
        _view(handler, host, tag, (query.get("m") or [""])[0], (query.get("k") or [""])[0])
    elif rest == "screen.png":
        try:
            png = host.render_png(tag)
        except AppError:
            _not_found(handler)
            return True
        _send(handler, HTTPStatus.OK, png, "image/png")
    else:
        _not_found(handler)
    return True


def _open(handler, host, tag: str, slash: bool) -> None:
    """The NFC link. on_open runs once per tap, then the page is shown by redirect."""
    view = "view" if slash else f"{tag}/view"
    if host.store.app_binding(tag) is None:
        return _redirect(handler, view)
    now = time.monotonic()
    key = (id(handler.app), tag)
    with _opened_lock:
        last = _opened.get(key)
        fresh = last is None or now - last >= OPEN_DEBOUNCE_S
        _opened[key] = now
    message, kind = "", ""
    if fresh:
        result = host.opened(tag)
        if not result.get("ok"):
            message, kind = result.get("error") or "the app failed", "err"
        elif result.get("pushed"):
            message, kind = POLL_NOTE, "ok"
    if message:
        view += f"?m={quote(message)}&k={kind}"
    _redirect(handler, view)


def _view(handler, host, tag: str, message: str, kind: str) -> None:
    info = {}
    try:
        info = handler.app.ink_tag_info(tag) or {}
    except Exception:  # noqa: BLE001 - a nicety
        pass
    name = info.get("alias") or f"Tag {tag}"
    binding = host.store.app_binding(tag)
    item = host.loaded.get(binding["app_id"]) if binding else None
    esc = html.escape

    if binding is None or item is None or item.app is None:
        why = ("No app runs on this tag yet. Pick one for it on the ShelfKit server, "
               "under Apps." if binding is None else
               f"The app {esc(binding['app_id'])} is not available on the server right now.")
        body = (f"<h1>{esc(name)}</h1><p class='sub'>Tag {tag}</p>"
                f"<p class='msg'>{why}</p>")
        return _send(handler, HTTPStatus.OK, _page(name, body), "text/html; charset=utf-8")

    app = item.app
    sub = f"{esc(info['alias'])} · tag {tag}" if info.get("alias") else f"Tag {tag}"
    parts = [f"<h1>{esc(app.title)}</h1><p class='sub'>{sub}</p>",
             f"<div class='tag'><img src='screen.png?t={int(time.time())}' "
             f"alt='What the tag shows'></div>"]
    if message:
        parts.append(f"<p class='msg{' err' if kind == 'err' else ''}' role='status'>"
                     f"{esc(message)}</p>")
    for c in app.controls:
        hidden = f'<input type="hidden" name="action" value="{esc(c.id)}">'
        if c.kind == "button":
            parts.append(f'<form method="post" action="do">{hidden}'
                         f'<button type="submit">{esc(c.label)}</button></form>')
        else:
            parts.append(f'<form method="post" action="do" class="text">{hidden}'
                         f'<input name="value" type="text" maxlength="500" '
                         f'placeholder="{esc(c.placeholder or c.label)}" '
                         f'aria-label="{esc(c.label)}">'
                         f'<button type="submit">{esc(c.label)}</button></form>')
    if app.description:
        parts.append(f"<p class='foot'>{esc(app.description)}</p>")
    _send(handler, HTTPStatus.OK, _page(app.title, "".join(parts)), "text/html; charset=utf-8")


# ── POST ───────────────────────────────────────────────────────────────────
def handle_post(handler, path: str) -> bool:
    """A form post from a tag page; False when the path is not one."""
    if not path.startswith(("/tag/", "/t/")):
        return False
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length > FORM_LIMIT:
        handler.close_connection = True          # the rest of the body is never read
        _send(handler, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, _page("Too long", "<h1>Too long</h1>"),
              "text/html; charset=utf-8")
        return True
    raw = handler.rfile.read(length) if length > 0 else b""
    route = _route(path)
    host = _host(handler)
    if route is None or route[0] != PREFIX or route[2] != "do" or host is None:
        _not_found(handler)
        return True
    if not _same_site(handler):
        _send(handler, HTTPStatus.FORBIDDEN, _page("Refused", "<h1>Refused</h1>"),
              "text/html; charset=utf-8")
        return True
    tag = route[1]
    form = parse_qs(raw.decode("utf-8", "replace"))
    action = (form.get("action") or [""])[0]
    value = (form.get("value") or [None])[0]
    result = host.run_action(tag, action, value)
    if not result.get("ok"):
        message, kind = result.get("error") or "that did not work", "err"
    elif result.get("pushed"):
        message, kind = f"Done. {POLL_NOTE}", "ok"
    else:
        message, kind = "Done. The screen stays the same, so nothing was sent to the tag.", "ok"
    _redirect(handler, f"view?m={quote(message)}&k={kind}")
    return True
