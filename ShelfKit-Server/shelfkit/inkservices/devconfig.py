"""Settings › Develop: what the Develop screen's AI agent may do, what its proposals may
change, and what it reads (its skill files).

Kept in the main database under one key. Everything has a default that matches how the
agent worked before this page existed, so an untouched install behaves the same.

    capabilities  web search limits (the switch is per service, in Settings › AI services),
                  effort (Claude 5 models), repair rounds
    permissions   which file types a proposal may write, whether the app may use the
                  network, whether a proposal may change the app's settings
    skill files   the built-in parts of the system prompt (each can be left out, except the
                  rules) and the owner's own skill files, appended after them
"""
from __future__ import annotations

import re

KEY = "develop_config"

FILE_TYPES = ("py", "xml", "md", "json", "txt", "toml", "sprite")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
PARTS = (   # the built-in skill files, in the order the system prompt holds them
    ("rules", "Rules", "How ShelfKit apps work, the hardware, and the answer format. Always sent."),
    ("sdk", "SDK source", "shelfkit/inkservices/sdk.py, so the agent knows every call an app can make."),
    ("inklayout", "InkLayout reference", "The screen language: elements, icons, charts, examples."),
    ("examples", "Example apps", "Two of the bundled apps, whole, as worked examples."),
)
SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,47}$")
MAX_SKILL = 40_000          # characters in one skill file
MAX_SKILLS = 20
DOMAIN = re.compile(r"^(?=.{1,253}$)[a-z0-9-]+(\.[a-z0-9-]+)+(/[^\s]*)?$")

DEFAULTS = {
    "web_search_max": 5,       # searches per request (Claude, OpenAI)
    "web_domains": [],         # only these sites (Claude, OpenAI; empty: any)
    "effort": "high",          # Claude 5 models: how hard it thinks
    "repair_rounds": 2,        # times it may fix its own errors before you see them
    "file_types": list(FILE_TYPES),
    "allow_network": True,     # generated apps may call tag.fetch_json
    "allow_settings": True,    # proposals may add or change the app's variables and secrets
    "parts": {"sdk": True, "inklayout": True, "examples": True},
    "skills": [],              # [{name, text, enabled}]
}


class ConfigError(ValueError):
    pass


def get(store) -> dict:
    raw = (store.setting(KEY, {}) if store is not None else {}) or {}
    out = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
           for k, v in DEFAULTS.items()}
    for k, v in raw.items():
        if k in out:
            out[k] = v
    out["parts"] = {**DEFAULTS["parts"], **(raw.get("parts") or {})}
    return out


def _save(store, cfg: dict) -> dict:
    store.set_setting(KEY, {k: cfg[k] for k in DEFAULTS})
    return get(store)


def update(store, body: dict) -> dict:
    """Change some settings; unknown keys are refused, values are checked."""
    cfg = get(store)
    for key, value in (body or {}).items():
        if key in ("allow_network", "allow_settings"):
            cfg[key] = bool(value)
        elif key == "web_search_max":
            try:
                cfg[key] = max(1, min(20, int(value)))
            except (TypeError, ValueError):
                raise ConfigError("searches per request must be a whole number") from None
        elif key == "web_domains":
            items = value if isinstance(value, list) else re.split(r"[\s,]+", str(value or ""))
            domains = []
            for d in items:
                d = str(d).strip().lower()
                d = re.sub(r"^https?://", "", d).rstrip("/")
                if not d:
                    continue
                if not DOMAIN.match(d):
                    raise ConfigError(f"{d!r} is not a site name (like docs.python.org)")
                domains.append(d)
            cfg[key] = domains[:32]
        elif key == "effort":
            if value not in EFFORTS:
                raise ConfigError(f"effort is one of {', '.join(EFFORTS)}")
            cfg[key] = value
        elif key == "repair_rounds":
            try:
                cfg[key] = max(0, min(5, int(value)))
            except (TypeError, ValueError):
                raise ConfigError("repair rounds must be a whole number") from None
        elif key == "file_types":
            types = [t for t in FILE_TYPES if t in (value or [])]
            if not {"py", "xml"} & set(types):
                raise ConfigError("allow at least .py or .xml, or the agent cannot change anything that runs")
            cfg[key] = types
        elif key == "parts":
            if not isinstance(value, dict):
                raise ConfigError("parts must be {name: on/off}")
            for name, on in value.items():
                if name not in cfg["parts"]:
                    raise ConfigError(f"no built-in skill file {name!r}")
                cfg["parts"][name] = bool(on)
        else:
            raise ConfigError(f"no setting {key!r}")
    return _save(store, cfg)


def skill(store, name: str, text=None, enabled=None, remove: bool = False,
          rename: str | None = None) -> dict:
    """Add, change, switch on/off, rename or remove one of the owner's skill files."""
    cfg = get(store)
    name = str(name or "").strip()
    skills = cfg["skills"]
    found = next((s for s in skills if s["name"] == name), None)
    if remove:
        if found is None:
            raise ConfigError(f"no skill file {name!r}")
        skills.remove(found)
        return _save(store, cfg)
    if rename is not None:
        rename = str(rename).strip()
        if found is None:
            raise ConfigError(f"no skill file {name!r}")
        if not SKILL_NAME.match(rename):
            raise ConfigError("a name is letters, digits, spaces and - _ . (up to 48)")
        if rename != name and any(s["name"] == rename for s in skills):
            raise ConfigError(f"there is already a skill file {rename!r}")
        found["name"] = rename
        name = rename
    if found is None:
        if not SKILL_NAME.match(name):
            raise ConfigError("a name is letters, digits, spaces and - _ . (up to 48)")
        if len(skills) >= MAX_SKILLS:
            raise ConfigError(f"at most {MAX_SKILLS} skill files")
        found = {"name": name, "text": "", "enabled": True}
        skills.append(found)
    if text is not None:
        text = str(text).replace("\r\n", "\n")
        if len(text) > MAX_SKILL:
            raise ConfigError(f"a skill file holds at most {MAX_SKILL:,} characters")
        found["text"] = text
    if enabled is not None:
        found["enabled"] = bool(enabled)
    return _save(store, cfg)


def public(store) -> dict:
    cfg = get(store)
    return {**cfg, "file_types_all": list(FILE_TYPES), "efforts": list(EFFORTS),
            "part_info": [{"id": i, "label": l, "about": a} for i, l, a in PARTS],
            "max_skill": MAX_SKILL}


def editable(cfg: dict) -> re.Pattern:
    """The file names a proposal may write under these permissions."""
    types = "|".join(re.escape(t) for t in cfg["file_types"]) or "x^"
    return re.compile(rf"^[A-Za-z0-9_-][A-Za-z0-9_.-]{{0,60}}\.({types})$")
