"""An app's own settings: variables and secrets, the same for every tag running the app.

They live in the server's database (settings key "app_settings"), never in the app's folder,
so they stay out of git, out of checkpoints and out of what the AI agent is sent (it gets the
secrets' names only). An app reads them with tag.var(name) and tag.secret(name); a secret
the app does not have falls back to the global API token of that name
(Settings > AI services > API tokens).

Per-tag settings are something else: app.config_field(...) in app.py, set per tag.
"""
from __future__ import annotations

import re
import time

from .screen import AppError

KEY = "app_settings"            # {app_id: {"vars": {name: value}, "secrets": {name: {value, at}}}}
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,40}")
MAX_VALUE = 4000


def _all(store) -> dict:
    raw = store.setting(KEY, {}) if store is not None else {}
    return raw if isinstance(raw, dict) else {}


def _of(store, app_id: str) -> dict:
    entry = _all(store).get(app_id)
    return entry if isinstance(entry, dict) else {}


def _mask(value: str) -> str:
    return f"…{value[-4:]}" if len(value) >= 8 else ("set" if value else "")


def variables(store, app_id: str) -> dict:
    return {k: str(v) for k, v in (_of(store, app_id).get("vars") or {}).items()}


def secret(store, app_id: str, name: str) -> str | None:
    entry = (_of(store, app_id).get("secrets") or {}).get(str(name))
    return entry.get("value") if isinstance(entry, dict) else None


def public(store, app_id: str) -> dict:
    """What the Settings tab shows: variables in full, secrets masked."""
    mine = _of(store, app_id)
    return {
        "vars": [{"name": k, "value": str(v)} for k, v in sorted((mine.get("vars") or {}).items())],
        "secrets": [{"name": k, "hint": _mask(v.get("value", "")), "at": v.get("at")}
                    for k, v in sorted((mine.get("secrets") or {}).items()) if isinstance(v, dict)],
    }


def save(store, app_id: str, kind: str, name: str, value: str | None = None,
         remove: bool = False) -> dict:
    if kind not in ("var", "secret"):
        raise AppError("kind is var or secret")
    name = str(name or "").strip()
    if not NAME.fullmatch(name):
        raise AppError("a name starts with a letter and has letters, digits and _ . - only (up to 41)")
    allv = dict(_all(store))
    mine = dict(allv.get(app_id) or {})
    group = dict(mine.get("vars" if kind == "var" else "secrets") or {})
    if remove:
        group.pop(name, None)
    else:
        value = "" if value is None else str(value)
        if len(value) > MAX_VALUE:
            raise AppError(f"a value is at most {MAX_VALUE} characters")
        if kind == "secret" and not value:
            raise AppError("a secret needs a value")
        group[name] = value if kind == "var" else {"value": value, "at": time.time()}
    mine["vars" if kind == "var" else "secrets"] = group
    allv[app_id] = mine
    store.set_setting(KEY, allv)
    return public(store, app_id)
