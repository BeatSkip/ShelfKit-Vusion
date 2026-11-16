"""Settings › AI services, over HTTP.

    GET  /api/ai                        the providers: key set?, last 4, model, enabled, default
    POST /api/ai/account  {provider, api_key?, model?, base_url?, enabled?, default?}
    POST /api/ai/default  {provider}
    POST /api/ai/check    {provider}    a tiny request, to prove the key works
    POST /api/ai/models   {provider}    the provider's model list
    POST /api/ai/token    {name, value?, note?, remove?}   an API token apps read with
                                        tag.token(name); comes back as "…abcd" too

A key goes in and never comes out: GET returns only "…abcd".
"""

from __future__ import annotations

from http import HTTPStatus

from . import AIError, check, models, public, save, save_token, set_default


def _store(handler):
    store = getattr(handler.app, "store", None)
    if store is None:
        handler._error("AI services need the server's database (the server was started with --no-store)",
                       HTTPStatus.SERVICE_UNAVAILABLE)
    return store


def handle_get(handler, path: str, query: dict) -> bool:
    if path != "/api/ai":
        return False
    store = _store(handler)
    if store is not None:
        handler._json(public(store))
    return True


def handle_post(handler, path: str, body: dict) -> bool:
    if not path.startswith("/api/ai/"):
        return False
    store = _store(handler)
    if store is None:
        return True
    provider = str(body.get("provider") or "")
    try:
        if path == "/api/ai/account":
            changes = {k: body[k] for k in ("api_key", "model", "base_url", "enabled", "default") if k in body}
            handler._json(save(store, provider, changes))
        elif path == "/api/ai/default":
            handler._json(set_default(store, provider))
        elif path == "/api/ai/check":
            handler._json({**check(store, provider), **public(store)})
        elif path == "/api/ai/token":
            handler._json({"tokens": save_token(store, body.get("name"), body.get("value"),
                                                body.get("note"), bool(body.get("remove")))})
        elif path == "/api/ai/models":
            handler._json({"models": models(store, provider)})
        else:
            handler._error(f"no such path {path}", HTTPStatus.NOT_FOUND)
    except AIError as exc:
        handler._error(str(exc))
    return True
