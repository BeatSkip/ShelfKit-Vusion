"""AI services: the accounts the Settings screen keeps, and one way to ask any of them.

Four providers, each with an API key the owner pastes into Settings › AI services:

* Claude (Anthropic)   - the official `anthropic` SDK
* OpenAI               - the official `openai` SDK
* DeepSeek, Mistral    - their OpenAI-compatible chat endpoints, through the `openai` SDK
                         with the provider's base URL

The SDKs are optional: without them the server runs as before and Settings says which
one to `pip install`. Keys live in the server's own database (settings table), are
never sent back to a browser (only the last four characters), and go nowhere but the
provider's own API.

`ask()` is the one call the rest of the server uses: a system prompt plus a
conversation in, the reply text out, asking for a JSON object when `json=True`.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

ACCOUNTS_KEY = "ai_accounts"          # {provider: {api_key, model, base_url, enabled}}
DEFAULT_KEY = "ai_default"            # the provider the Develop screen uses
TOKENS_KEY = "api_tokens"             # {name: {value, note, at}}: tokens apps read with tag.token()


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    sdk: str                # the Python package that talks to it
    default_model: str
    base_url: str           # "" = the SDK's own
    keys_url: str           # where the owner creates a key
    models: tuple = ()      # suggestions; "Load models" asks the provider for the real list


PROVIDERS = {
    p.id: p for p in (
        Provider("anthropic", "Claude (Anthropic)", "anthropic", "claude-opus-5-5", "",
                 "https://platform.claude.com/settings/keys",
                 ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2")),
        Provider("openai", "OpenAI", "openai", "gpt-5", "",
                 "https://platform.openai.com/api-keys", ()),
        Provider("deepseek", "DeepSeek", "openai", "deepseek-chat", "https://api.deepseek.com",
                 "https://platform.deepseek.com/api_keys", ("deepseek-chat", "deepseek-reasoner")),
        Provider("mistral", "Mistral", "openai", "mistral-large-latest", "https://api.mistral.ai/v1",
                 "https://console.mistral.ai/api-keys", ("mistral-large-latest", "codestral-latest",
                                                         "mistral-medium-latest")),
    )
}
# Claude models that take the server-side refusal fallback (see ask_anthropic)
_FALLBACK_MODELS = ("claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5",
                    "claude-sonnet-5-5")


class AIError(Exception):
    """Something to show the owner: no key, a bad key, the provider said no, ..."""


def sdk_available(name: str) -> bool:
    try:
        __import__(name)
    except ImportError:
        return False
    return True


# ── accounts ──────────────────────────────────────────────────────────────────
def _accounts(store) -> dict:
    raw = store.setting(ACCOUNTS_KEY, {}) or {}
    return {k: v for k, v in raw.items() if k in PROVIDERS and isinstance(v, dict)}


def _mask(key: str) -> str:
    return f"…{key[-4:]}" if len(key) >= 8 else ("set" if key else "")


def public(store) -> dict:
    """Everything Settings shows, without the keys themselves."""
    accounts = _accounts(store)
    default = store.setting(DEFAULT_KEY, None)
    out = []
    for p in PROVIDERS.values():
        acc = accounts.get(p.id, {})
        out.append({
            "id": p.id, "label": p.label, "sdk": p.sdk, "sdk_ok": sdk_available(p.sdk),
            "keys_url": p.keys_url, "default_model": p.default_model,
            "default_base_url": p.base_url, "models": list(p.models),
            "has_key": bool(acc.get("api_key")), "key_hint": _mask(acc.get("api_key", "")),
            "model": acc.get("model") or "", "base_url": acc.get("base_url") or "",
            "enabled": bool(acc.get("enabled", bool(acc.get("api_key")))),
            "checked_at": acc.get("checked_at"), "check": acc.get("check"),
        })
    usable = [x["id"] for x in out if x["has_key"] and x["enabled"]]
    if default not in usable:
        default = usable[0] if usable else None
    return {"providers": out, "default": default, "tokens": tokens_public(store)}


def save(store, provider: str, changes: dict) -> dict:
    """Update one account. api_key "" clears it; a missing api_key keeps the old one."""
    if provider not in PROVIDERS:
        raise AIError(f"unknown AI service {provider!r}")
    accounts = _accounts(store)
    acc = dict(accounts.get(provider, {}))
    had_key = bool(acc.get("api_key"))
    if "api_key" in changes:
        key = str(changes.get("api_key") or "").strip()
        if len(key) > 400 or any(c.isspace() for c in key):
            raise AIError("that does not look like an API key")
        acc["api_key"] = key
        acc.pop("check", None)
        acc.pop("checked_at", None)
    if "model" in changes:
        model = str(changes.get("model") or "").strip()
        if len(model) > 120 or not re.fullmatch(r"[A-Za-z0-9._:/@-]*", model):
            raise AIError("a model name has letters, digits and . _ : / @ - only")
        acc["model"] = model
    if "base_url" in changes:
        url = str(changes.get("base_url") or "").strip().rstrip("/")
        if url and not re.match(r"^https?://[^\s]+$", url):
            raise AIError("the base URL must start with http:// or https://")
        acc["base_url"] = url
    if "enabled" in changes:
        acc["enabled"] = bool(changes["enabled"])
    if changes.get("api_key") and not had_key:
        acc["enabled"] = True            # a first key turns the service on
    accounts[provider] = acc
    store.set_setting(ACCOUNTS_KEY, accounts)
    if changes.get("default"):
        store.set_setting(DEFAULT_KEY, provider)
    return public(store)


def set_default(store, provider: str) -> dict:
    if provider not in PROVIDERS:
        raise AIError(f"unknown AI service {provider!r}")
    store.set_setting(DEFAULT_KEY, provider)
    return public(store)


def _account(store, provider: str | None) -> tuple[Provider, dict]:
    if not provider:
        provider = public(store)["default"]
        if not provider:
            raise AIError("no AI service is set up: add an API key under Settings › AI services")
    if provider not in PROVIDERS:
        raise AIError(f"unknown AI service {provider!r}")
    p = PROVIDERS[provider]
    acc = _accounts(store).get(provider, {})
    if not acc.get("api_key"):
        raise AIError(f"{p.label} has no API key: add one under Settings › AI services")
    if not sdk_available(p.sdk):
        raise AIError(f"{p.label} needs the '{p.sdk}' Python package: pip install {p.sdk}")
    return p, acc


def describe(store, provider: str | None = None) -> dict:
    """{provider, label, model} that ask() would use, or {error}."""
    try:
        p, acc = _account(store, provider)
    except AIError as exc:
        return {"error": str(exc)}
    return {"provider": p.id, "label": p.label, "model": acc.get("model") or p.default_model}


# ── API tokens for apps ───────────────────────────────────────────────────────
def tokens_public(store) -> list[dict]:
    raw = store.setting(TOKENS_KEY, {}) or {}
    return [{"name": k, "hint": _mask(v.get("value", "")), "note": v.get("note", ""),
             "at": v.get("at")} for k, v in sorted(raw.items()) if isinstance(v, dict)]


def save_token(store, name: str, value: str | None = None, note: str | None = None,
               remove: bool = False) -> list[dict]:
    name = str(name or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,40}", name):
        raise AIError("a token name starts with a letter and has letters, digits and _ . - only")
    raw = dict(store.setting(TOKENS_KEY, {}) or {})
    if remove:
        raw.pop(name, None)
    else:
        entry = dict(raw.get(name) or {})
        if value is not None:
            value = str(value).strip()
            if not value or len(value) > 2000:
                raise AIError("paste the token's value")
            entry["value"] = value
            entry["at"] = time.time()
        if note is not None:
            entry["note"] = str(note).strip()[:120]
        if not entry.get("value"):
            raise AIError("paste the token's value")
        raw[name] = entry
    store.set_setting(TOKENS_KEY, raw)
    return tokens_public(store)


def token_value(store, name: str) -> str | None:
    entry = (store.setting(TOKENS_KEY, {}) or {}).get(str(name))
    return entry.get("value") if isinstance(entry, dict) else None


# ── asking ────────────────────────────────────────────────────────────────────
def ask(store, system: str, messages: list[dict], *, provider: str | None = None,
        json_mode: bool = False, max_tokens: int = 32000, timeout: float = 600.0) -> dict:
    """{text, provider, model, usage, seconds}. messages: [{role: user|assistant, content: str}]."""
    p, acc = _account(store, provider)
    model = acc.get("model") or p.default_model
    started = time.monotonic()
    if p.id == "anthropic":
        text, usage = _ask_anthropic(acc, model, system, messages, json_mode, max_tokens, timeout)
    else:
        text, usage = _ask_openai(p, acc, model, system, messages, json_mode, max_tokens, timeout)
    return {"text": text, "provider": p.id, "label": p.label, "model": model, "usage": usage,
            "seconds": round(time.monotonic() - started, 1)}


def _ask_anthropic(acc, model, system, messages, json_mode, max_tokens, timeout):
    import anthropic

    client = anthropic.Anthropic(api_key=acc["api_key"], base_url=acc.get("base_url") or None,
                                 timeout=timeout, max_retries=2)
    sys_text = system + ("\n\nAnswer with one JSON object and nothing else." if json_mode else "")
    params = dict(model=model, max_tokens=max_tokens, system=sys_text, messages=messages)
    if model.startswith(("claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-haiku-5")):
        params["output_config"] = {"effort": "high"}     # coding work: more than the default
    try:
        if model in _FALLBACK_MODELS:
            # a request a safety classifier declines is re-run on a fallback model
            with client.beta.messages.stream(**params, betas=["server-side-fallback-2026-07-01"],
                                             fallbacks="default") as stream:
                message = stream.get_final_message()
        else:
            with client.messages.stream(**params) as stream:
                message = stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise AIError("Claude refused the API key (check it under Settings › AI services)") from exc
    except anthropic.PermissionDeniedError as exc:
        raise AIError(f"Claude: the key may not use this: {exc.message}") from exc
    except anthropic.NotFoundError as exc:
        raise AIError(f"Claude does not know the model {model!r}") from exc
    except anthropic.RateLimitError as exc:
        raise AIError("Claude: rate limited, try again in a minute") from exc
    except anthropic.APIStatusError as exc:
        raise AIError(f"Claude: {exc.status_code} {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise AIError("could not reach Claude (network)") from exc
    if message.stop_reason == "refusal":
        raise AIError("Claude declined this request")
    text = "".join(b.text for b in message.content if b.type == "text")
    if message.stop_reason == "max_tokens":
        raise AIError("the reply was cut off (too long); ask for a smaller change")
    usage = {"input": message.usage.input_tokens, "output": message.usage.output_tokens}
    return text, usage


def _ask_openai(p: Provider, acc, model, system, messages, json_mode, max_tokens, timeout):
    import openai

    client = openai.OpenAI(api_key=acc["api_key"], base_url=acc.get("base_url") or p.base_url or None,
                           timeout=timeout, max_retries=2)
    params = dict(model=model, messages=[{"role": "system", "content": system}, *messages])
    if json_mode:
        params["response_format"] = {"type": "json_object"}
    if p.id == "openai":
        params["max_completion_tokens"] = max_tokens
    else:
        params["max_tokens"] = min(max_tokens, 8192)     # DeepSeek and Mistral cap lower
    try:
        reply = client.chat.completions.create(**params)
    except openai.AuthenticationError as exc:
        raise AIError(f"{p.label} refused the API key (check it under Settings › AI services)") from exc
    except openai.NotFoundError as exc:
        raise AIError(f"{p.label} does not know the model {model!r}") from exc
    except openai.RateLimitError as exc:
        raise AIError(f"{p.label}: rate limited or out of credit") from exc
    except openai.APIStatusError as exc:
        raise AIError(f"{p.label}: {exc.status_code} {exc.message}") from exc
    except openai.APIConnectionError as exc:
        raise AIError(f"could not reach {p.label} (network)") from exc
    choice = reply.choices[0]
    if choice.finish_reason == "length":
        raise AIError("the reply was cut off (too long); ask for a smaller change")
    usage = {"input": getattr(reply.usage, "prompt_tokens", None),
             "output": getattr(reply.usage, "completion_tokens", None)}
    return choice.message.content or "", usage


def models(store, provider: str) -> list[str]:
    """The provider's own model list, for the Settings picker."""
    p, acc = _account(store, provider)
    try:
        if p.id == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=acc["api_key"], base_url=acc.get("base_url") or None,
                                         timeout=30.0)
            return [m.id for m in client.models.list()]
        import openai
        client = openai.OpenAI(api_key=acc["api_key"], base_url=acc.get("base_url") or p.base_url or None,
                               timeout=30.0)
        return sorted(m.id for m in client.models.list())
    except Exception as exc:  # noqa: BLE001 - shown to the owner as is
        raise AIError(f"{p.label}: could not list models: {exc}") from exc


def check(store, provider: str) -> dict:
    """A tiny request, to prove the key and the model work. Remembered for Settings."""
    try:
        r = ask(store, "You check that an API key works.", [{"role": "user", "content": "Reply with OK."}],
                provider=provider, max_tokens=2000, timeout=60.0)
        result = {"ok": True, "text": f"Works: {r['model']} answered in {r['seconds']} s"}
    except AIError as exc:
        result = {"ok": False, "text": str(exc)}
    accounts = _accounts(store)
    if provider in accounts:
        accounts[provider]["check"] = result
        accounts[provider]["checked_at"] = time.time()
        store.set_setting(ACCOUNTS_KEY, accounts)
    return result


def parse_json(text: str) -> dict:
    """The JSON object in a reply, even when a model wrapped it in a code fence or prose."""
    text = text.strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except ValueError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(text[start:end + 1])
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
    raise AIError("the AI did not answer with the JSON it was asked for")
