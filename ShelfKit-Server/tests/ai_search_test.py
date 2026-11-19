"""Web search through each AI service's own API, with the SDKs faked (no network).

    python tests/ai_search_test.py
"""
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shelfkit import ai, store as store_mod  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail=None) -> None:
    if ok:
        print(f"  PASS {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name}" + (f"  <<< {detail}" if detail is not None else ""))


CALLS: list[dict] = []


# ── a fake anthropic SDK: the first answer pauses mid-search, the second finishes ──
def _usage(i, o):
    return NS(input_tokens=i, output_tokens=o, cache_read_input_tokens=0)


class _Stream:
    def __init__(self, params):
        self.params = params

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        CALLS.append(self.params)
        if len(CALLS) == 1:
            return NS(stop_reason="pause_turn", usage=_usage(100, 5), content=[
                NS(type="text", text="Let me look that up."),
                NS(type="server_tool_use", input={"query": "open-meteo api"})])
        return NS(stop_reason="end_turn", usage=_usage(50, 20), content=[
            NS(type="web_search_tool_result", content=[]),
            NS(type="text", text='{"summary": '), NS(type="text", text='"found it"}')])


class _Messages:
    def stream(self, **params):
        return _Stream(params)


class _Anthropic:
    def __init__(self, **kw):
        self.messages = _Messages()
        self.beta = NS(messages=_Messages())


fake_anthropic = types.ModuleType("anthropic")
fake_anthropic.Anthropic = _Anthropic
for name in ("AuthenticationError", "PermissionDeniedError", "NotFoundError", "RateLimitError",
             "APIStatusError", "APIConnectionError"):
    setattr(fake_anthropic, name, type(name, (Exception,), {}))


# ── a fake openai SDK: Responses (OpenAI) and chat completions (DeepSeek) ──────────
class _Responses:
    def create(self, **params):
        CALLS.append(params)
        return NS(status="completed", output_text='{"summary": "searched"}',
                  usage=NS(input_tokens=10, output_tokens=3),
                  output=[NS(type="web_search_call", action=NS(query="weather api"))])


class _Msg:
    content = '{"summary": "deep"}'

    def to_dict(self):
        return {"server_tool_calls": [{"calls": [{"kind": "search", "action": {"queries": ["knmi data"]}}]}]}


class _Completions:
    def create(self, **params):
        CALLS.append(params)
        return NS(choices=[NS(finish_reason="stop", message=_Msg())],
                  usage=NS(prompt_tokens=7, completion_tokens=2))


class _OpenAI:
    def __init__(self, **kw):
        self.responses = _Responses()
        self.chat = NS(completions=_Completions())


fake_openai = types.ModuleType("openai")
fake_openai.OpenAI = _OpenAI
fake_openai.OpenAIError = type("OpenAIError", (Exception,), {})
for name in ("AuthenticationError", "NotFoundError", "RateLimitError", "APIStatusError", "APIConnectionError"):
    setattr(fake_openai, name, type(name, (fake_openai.OpenAIError,), {}))


def main() -> int:
    real = {k: sys.modules.get(k) for k in ("anthropic", "openai")}
    sys.modules["anthropic"], sys.modules["openai"] = fake_anthropic, fake_openai
    tmp = Path(tempfile.mkdtemp())
    s = store_mod.Store(tmp / "a.db")
    try:
        for p in ("anthropic", "openai", "deepseek"):
            ai.save(s, p, {"api_key": f"sk-{p}-12345678"})
        msgs = [{"role": "user", "content": "build it"}]
        limits = {"max": 3, "domains": ["open-meteo.com"]}

        # off: no tools in the request
        CALLS.clear()
        ai.ask(s, "sys", msgs, provider="anthropic", json_mode=True, web_search=limits)
        check("with the box off, Claude gets no search tool", "tools" not in CALLS[0], CALLS[0].keys())

        ai.save(s, "anthropic", {"web_search": True, "model": "claude-opus-5-5"})
        CALLS.clear()
        r = ai.ask(s, "sys", msgs, provider="anthropic", json_mode=True, web_search=limits, effort="xhigh")
        tool = CALLS[0]["tools"][0]
        check("Claude gets the web search tool with the limits",
              tool == {"type": "web_search_20260209", "name": "web_search", "max_uses": 3,
                       "allowed_domains": ["open-meteo.com"]}, tool)
        check("the effort setting is sent", CALLS[0]["output_config"] == {"effort": "xhigh"}, CALLS[0].get("output_config"))
        check("a paused search turn is resumed with the reply so far",
              len(CALLS) == 2 and CALLS[1]["messages"][-1]["role"] == "assistant", len(CALLS))
        check("the answer is the text after the last search result, joined",
              r["text"] == '{"summary": "found it"}', r["text"])
        check("the searches are reported and the usage summed",
              r["searches"] == ["open-meteo api"] and r["usage"]["input"] == 150, (r["searches"], r["usage"]))
        ai.save(s, "anthropic", {"model": "claude-sonnet-4-5"})
        CALLS.clear()
        ai.ask(s, "sys", msgs, provider="anthropic", web_search=limits)
        check("older Claude models get the basic search tool", CALLS[0]["tools"][0]["type"] == "web_search_20250305")

        ai.save(s, "openai", {"web_search": True})
        CALLS.clear()
        r = ai.ask(s, "sys", msgs, provider="openai", json_mode=True, web_search=limits)
        check("OpenAI searches through the Responses API with the site filter",
              CALLS[0]["tools"] == [{"type": "web_search", "filters": {"allowed_domains": ["open-meteo.com"]}}]
              and CALLS[0]["max_tool_calls"] == 3 and "JSON" in CALLS[0]["instructions"], CALLS[0])
        check("OpenAI's searches and answer come back", r["text"] == '{"summary": "searched"}'
              and r["searches"] == ["weather api"], r)

        CALLS.clear()
        ai.ask(s, "sys", msgs, provider="deepseek", json_mode=True, web_search=limits)
        check("with the box off, DeepSeek uses JSON mode and no tools",
              CALLS[0].get("response_format") == {"type": "json_object"} and "tools" not in CALLS[0], CALLS[0])
        ai.save(s, "deepseek", {"web_search": True})
        CALLS.clear()
        r = ai.ask(s, "sys", msgs, provider="deepseek", json_mode=True, web_search=limits)
        check("DeepSeek gets its server search tool and no JSON mode (it refuses both together)",
              CALLS[0]["tools"] == [{"type": "deepseek_web_search"}] and "response_format" not in CALLS[0]
              and "JSON" in CALLS[0]["messages"][0]["content"], CALLS[0])
        check("DeepSeek's search queries are reported", r["searches"] == ["knmi data"], r)
    finally:
        for k, v in real.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        s.close()
    print("\nALL PASS" if not FAILED else f"\nFAILED: {', '.join(FAILED)}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
