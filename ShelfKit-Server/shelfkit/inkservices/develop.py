"""The Develop screen's server side: an app's files, checkpoints, a virtual tag, and
an AI agent that proposes changes.

    GET  /api/dev/files?app=              the app's own text files, editable
    POST /api/dev/save     {app, files: {name: text}, note?}   checkpoint, write, reload
    GET  /api/dev/checkpoints?app=        saved versions of the app's files
    GET  /api/dev/settings?app=          variables, secrets (masked), API token names, per-tag fields
    POST /api/dev/settings {app, kind: var|secret, name, value?, remove?}
    POST /api/dev/delete   {app, file}    checkpoint, remove one file (never app.py), reload
    POST /api/dev/revert   {app, id}      back to a checkpoint (after saving one of now)
    POST /api/dev/virtual  {app, do, action?, value?, now?, config?}
                           do: draw | open | action | timers | config | reset
                           -> {png (base64), ms, diagnostics, data, config, error,
                               phone (the phone page's HTML, if the app has one)}
    POST /api/dev/agent    {app, prompt, provider?, context?}  -> {job}
    GET  /api/dev/agent?job=              the job: steps so far, the proposal, a question
    POST /api/dev/agent/apply   {job, secrets?}  checkpoint, write the files, apply the settings
                                (secrets: values the owner typed for the ones the AI asked for)
    POST /api/dev/agent/reject  {job}
    GET  /api/dev/agent/history?app=      the conversation so far (for a page reload)
    POST /api/dev/agent/forget  {app}     start the conversation again

The virtual tag (FFF0) runs the app's own callbacks in the server, like a real tag,
but it is never bound and nothing is ever pushed. Its data and settings live in the
app's database under FFF0, its shared document under "FFF0:shared", so trying things
never touches the real tags' data (the app's own SQL tables are shared, though).

The agent only proposes. Its proposal is checked without running any of it: app.py
is compiled (not imported) and a new layout.xml is rendered with the virtual tag's
data. Python the AI wrote runs only after the owner presses Accept.
"""

from __future__ import annotations

import ast
import base64
import difflib
import importlib.util
import inspect
import io
import json
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from http import HTTPStatus
from pathlib import Path

from .. import ai, inklayout
from . import appsettings, phone
from . import sdk as sdk_module
from .screen import AppError, tag_view

VIRTUAL = "FFF0"
VIRTUAL_SHARED = "FFF0:shared"
EDITABLE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,60}\.(py|xml|md|json|txt|toml)$")
MAX_FILE = 256_000
CHECKPOINTS_KEEP = 40
HISTORY_KEEP = 12            # messages of the agent conversation kept per app


# ── files and checkpoints ─────────────────────────────────────────────────────
def _folder(host, app_id: str) -> Path:
    if app_id not in {a["id"] for a in host.apps()}:
        raise AppError(f"no app {app_id!r}")
    item = host.loaded.get(app_id)
    return item.path if item else host.root / app_id


def files(host, app_id: str) -> dict:
    folder = _folder(host, app_id)
    out = []
    for f in sorted(folder.iterdir(), key=lambda f: (f.name != "app.py", f.name != "layout.xml", f.name)):
        if f.is_file() and EDITABLE.match(f.name) and f.stat().st_size <= MAX_FILE:
            out.append({"name": f.name, "text": f.read_text(encoding="utf-8", errors="replace")})
    return {"folder": str(folder), "files": out}


def _checkpoint_root(folder: Path) -> Path:
    return folder / "data" / "checkpoints"


def checkpoint(host, app_id: str, note: str, label: str = "") -> dict:
    """Copy the app's editable files aside. Returns the checkpoint's meta."""
    folder = _folder(host, app_id)
    root = _checkpoint_root(folder)
    cid = time.strftime("%Y%m%d-%H%M%S") + f"-{uuid.uuid4().hex[:4]}"
    target = root / cid
    target.mkdir(parents=True)
    names = []
    for f in folder.iterdir():
        if f.is_file() and EDITABLE.match(f.name):
            shutil.copy2(f, target / f.name)
            names.append(f.name)
    meta = {"id": cid, "note": note[:200], "label": label[:40], "at": time.time(), "files": sorted(names)}
    (target / "checkpoint.json").write_text(json.dumps(meta), encoding="utf-8")
    old = sorted(p for p in root.iterdir() if p.is_dir())
    for stale in old[:-CHECKPOINTS_KEEP]:
        shutil.rmtree(stale, ignore_errors=True)
    return meta


def checkpoints(host, app_id: str) -> list[dict]:
    root = _checkpoint_root(_folder(host, app_id))
    out = []
    if root.is_dir():
        for d in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
            try:
                out.append(json.loads((d / "checkpoint.json").read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return out


def _check_files(new: dict) -> dict[str, str]:
    if not isinstance(new, dict) or not new:
        raise AppError("no files to save")
    clean = {}
    for name, text in new.items():
        if not isinstance(name, str) or not EDITABLE.match(name):
            raise AppError(f"{name!r} is not a file name the Develop screen may write")
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_FILE:
            raise AppError(f"{name} is too large or not text")
        clean[name] = text
    return clean


def save(host, app_id: str, new: dict, note: str = "edited by hand", label: str = "") -> dict:
    """Checkpoint, write the files, reload every app. {ok, checkpoint, error (load error)}."""
    clean = _check_files(new)
    folder = _folder(host, app_id)
    meta = checkpoint(host, app_id, f"before: {note}", label)
    for name, text in clean.items():
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    host.reload()
    item = host.loaded.get(app_id)
    return {"ok": True, "checkpoint": meta, "error": item.error if item else None}


def delete(host, app_id: str, name: str) -> dict:
    """Checkpoint, remove one file, reload every app. app.py stays: the app is nothing without it."""
    name = str(name or "")
    if not EDITABLE.match(name):
        raise AppError(f"{name!r} is not a file of the app")
    if name == "app.py":
        raise AppError("app.py is the app itself; it cannot be deleted here")
    folder = _folder(host, app_id)
    target = folder / name
    if not target.is_file():
        raise AppError(f"there is no {name}")
    meta = checkpoint(host, app_id, f"before deleting {name}", "")
    target.unlink()
    host.reload()
    item = host.loaded.get(app_id)
    return {"ok": True, "checkpoint": meta, "error": item.error if item else None}


def revert(host, app_id: str, cid: str) -> dict:
    if not re.fullmatch(r"[0-9a-f-]{10,40}", cid or ""):
        raise AppError("no such checkpoint")
    folder = _folder(host, app_id)
    source = _checkpoint_root(folder) / cid
    if not (source / "checkpoint.json").is_file():
        raise AppError("no such checkpoint")
    meta = json.loads((source / "checkpoint.json").read_text(encoding="utf-8"))
    names = [n for n in meta.get("files", []) if n != "checkpoint.json" and EDITABLE.match(n)
             and (source / n).is_file()]                   # never the checkpoint's own record
    restored = {n: (source / n).read_text(encoding="utf-8") for n in names}
    if "app.py" not in restored:
        raise AppError("that checkpoint has no app.py")
    clean = _check_files(restored)
    now = checkpoint(host, app_id, f"before: revert to {meta.get('label') or cid}")
    for name, text in clean.items():
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    for f in folder.iterdir():                              # files added since go (they are in `now`)
        if f.is_file() and EDITABLE.match(f.name) and f.name not in clean:
            f.unlink()
    host.reload()
    item = host.loaded.get(app_id)
    return {"ok": True, "checkpoint": now, "error": item.error if item else None}


# ── the virtual tag ───────────────────────────────────────────────────────────
def _pretend(now: str | None) -> datetime | None:
    if not now:
        return None
    try:
        return datetime.fromisoformat(str(now))
    except ValueError as exc:
        raise AppError("the pretend time must look like 2026-11-16T21:10") from exc


def virtual(host, app_id: str, do: str = "draw", action: str | None = None,
            value: str | None = None, now: str | None = None, config: dict | None = None) -> dict:
    """Run something for the virtual tag, then draw it. Never binds, never pushes."""
    app = host._app(app_id)
    when = _pretend(now)
    error = None
    with host._app_lock(app_id):
        st = host.store_of(app_id)
        if do == "reset":
            st.set_state(VIRTUAL, {})
            st.set_state(VIRTUAL_SHARED, {})
            st.set_config(VIRTUAL, {})
        elif do == "config":
            fields = {f.key for f in app.config_fields}
            st.set_config(VIRTUAL, {k: str(v) for k, v in (config or {}).items()
                                    if k in fields and str(v) != ""})
        tag = host._context(app, VIRTUAL, st)
        tag.shared = st.state(VIRTUAL_SHARED)
        if when is not None:
            tag.now = when
        calls = []
        if do == "open":
            if app.on_open_fn is None:
                raise AppError("this app does nothing on an NFC tap (no @app.on_open)")
            calls = [("on_open", app.on_open_fn, ())]
        elif do == "action":
            control = app.action(action or "")
            if control is None:
                raise AppError(f"no phone-page control {action!r}")
            calls = [(f"action {control.id!r}", control.fn,
                      (str(value or ""),) if control.kind == "text" else ())]
        elif do == "timers":
            calls = [(f"timer {t.id}", t.fn, ()) for t in app.timers]
        try:
            for what, fn, args in calls:
                try:
                    fn(tag, *args)
                except Exception as exc:  # noqa: BLE001 - app code
                    error = host._failed(app_id, VIRTUAL, what, exc)["error"]
                    break
        finally:
            st.set_state(VIRTUAL, tag.data)
            st.set_state(VIRTUAL_SHARED, tag.shared)
        started = time.perf_counter()
        png, diagnostics = None, []
        try:
            image, result = host._draw(app, tag)
            png = base64.b64encode(host._png(image)).decode("ascii")
            diagnostics = result.diagnostics if result is not None else []
        except AppError as exc:
            error = error or str(exc)
            diagnostics = getattr(getattr(exc, "result", None), "diagnostics", [])
        except Exception as exc:  # noqa: BLE001 - app code
            error = error or host._failed(app_id, VIRTUAL, "render", exc)["error"]
        finally:
            host._flush_logs(app_id, tag)
        ms = round((time.perf_counter() - started) * 1000)
        data = app.data_fn(tag) if (app.data_fn is not None and png) else tag.data
    if calls and not error:
        host._log(app_id, f"[{VIRTUAL}] {calls[0][0] if len(calls) == 1 else 'timers'} (virtual tag)")
    phone_page = None
    if app.controls or app.on_open_fn is not None or app.page_fn is not None:   # it has a phone page
        if do in ("action", "open"):
            message, kind = (error, "err") if error else ("Done. On a real tag the screen follows "
                                                        "at its next check-in.", "ok")
        else:
            message, kind = "", ""
        with host._app_lock(app_id):
            ptag = host._context(app, VIRTUAL, host.store_of(app_id))
            ptag.shared = host.store_of(app_id).state(VIRTUAL_SHARED)
            if when is not None:
                ptag.now = when
            try:
                blocks = host.page_blocks(app, ptag)
            finally:
                host._flush_logs(app_id, ptag)
        phone_page = phone.preview_page(app, "data:image/png;base64," + png if png else "", message, kind, blocks)
    return {"phone": phone_page, "ok": error is None, "error": error, "png": png, "ms": ms, "diagnostics": diagnostics,
            "data": _jsonable(data), "state": _jsonable(tag.data), "config": tag.config,
            "now": tag.now.isoformat(timespec="minutes")}


def _jsonable(value):
    return json.loads(json.dumps(value, default=str))


def _virtual_view(host, app_id: str, var_preview: dict | None = None):
    """(layout data, tag view, shared, now, display) the virtual tag's screen is drawn from;
    var_preview: variables as a proposal would set them (None = remove)."""
    app = host._app(app_id)
    with host._app_lock(app_id):
        st = host.store_of(app_id)
        tag = host._context(app, VIRTUAL, st)
        tag.shared = st.state(VIRTUAL_SHARED)
        for k, v in (var_preview or {}).items():
            if v is None:
                tag.vars.pop(k, None)
            else:
                tag.vars[k] = str(v)
        try:
            data = app.data_fn(tag) if app.data_fn is not None else tag.data
        except Exception:  # noqa: BLE001 - app code; the draft is still worth a look
            data = tag.data
    return data, tag_view(tag), tag.shared, tag.now, tag.display.id


# ── the agent ─────────────────────────────────────────────────────────────────
_JOBS: dict[str, dict] = {}
_HISTORY: dict[str, list[dict]] = {}
_LOCK = threading.Lock()

RULES = """You build and change apps for ShelfKit: small Python programs that own the screen of
an e-paper shelf tag and answer the tag's NFC link with a phone page. You work on ONE app, in
its folder inkapps/<id>/. The owner sees your proposal drawn on a virtual tag and accepts or
rejects it; nothing you write runs before they accept.

THE HARDWARE
- 2.6" e-paper, 152 x 296 pixels, portrait by default; black, white and red only (no grey:
  use the dot/hatch patterns InkLayout offers). Text is drawn 1-bit.
- A coin-cell battery. Every screen change costs battery and takes ~15 s with a flash, and it
  only reaches the glass at the tag's next check-in (up to ~5 minutes; seconds after an NFC tap).
  So: never draw a clock or seconds, and only change what is on screen when something the owner
  cares about changed. The host never re-sends an identical picture.

HOW AN APP RUNS (the host, shelfkit/inkservices/host.py)
- app.py is imported when the server starts or reloads apps. It must define, at module level,
  app = InkApp("<id>", title=..., layout="layout.xml", ...) where <id> is the folder name.
  Importing must be quick and have no side effects: no network, no threads, no sleep.
- The screen: InkApp(layout="layout.xml") renders that InkLayout file with what @app.data
  returns (a dict; default tag.data). @app.data and @app.render run on EVERY redraw, so they
  only read and compute; they never fetch. (@app.render draws with Python on a Canvas instead
  of a layout; prefer a layout.)
- tag.data: this tag's state (a dict, JSON-serialisable values only), saved by the host after
  every callback. tag.shared: one dict shared by every tag running the app. tag.config: the
  owner's settings for this tag (always strings; declare them with app.config_field(key,
  label=, default=)). tag.now: the time to draw for (the owner may pretend another time).
  tag.log(msg): a line in the app's log. tag.db: the app's own SQLite connection.
- The phone page (what a phone opens when it taps the tag) is built by the host from:
  @app.page (fn(tag) -> a list of "text", ("Label", "value") facts, {"heading": ...},
  {"note": ...}, {"link": "...", "url": "https://..."}; shown under the tag's screen; it runs
  on every view, so it only reads), then @app.button("Label") and @app.text_input("Label",
  placeholder=) as big buttons and fields, then the app's description. There is no HTML,
  CSS or script to write. InkApp(..., phone_screen=False) hides the screen on the page.
  @app.on_open runs when a phone taps the tag. After a button, a text input or on_open the
  screen is redrawn and sent if it changed.
- Fresh data: @app.every(minutes=N) runs for every tag on a schedule (N >= 15 unless asked);
  tag.fetch_json(url, params) is the only network access; put results in tag.data.
- App settings (Develop > Settings, the same for every tag): tag.var("name", "default") for
  plain values (a city, a URL, a threshold; always strings) and tag.secret("name") for keys
  and passwords (it falls back to the global API token of that name; None when missing, so
  handle None). Never write a key or a password into a file. You can add, change and remove
  them in "settings" (below). Per-tag settings are app.config_field(...) and tag.config.
- Imports: the Python standard library and shelfkit.inkservices only.
- Files you may write: app.py, layout.xml and other .py .xml .md .json .txt .toml files in the
  app folder (plain names, no folders).

GOOD HABITS
- Text must fit its box: fit="shrink", lines= and | default:"-" in the layout.
- Keep the layout's names in step with what @app.data returns; when you add a value to the
  layout, return it from @app.data.
- Make small, complete changes that do what was asked; keep the owner's code and comments.

ANSWER with one JSON object and nothing else:
{
  "summary": "one sentence: what you changed, or what you need to know",
  "plan": ["short step", ...],
  "files": {"layout.xml": "<the complete new file>", "app.py": "<the complete new file>"},
  "settings": {"vars": {"city": "Utrecht", "old_name": null},
               "secrets": {"weather_key": "", "unused_key": null}},
  "question": "only if you cannot go on without the owner's choice, else null",
  "answers": ["2-4 short answers the owner can click", ...],
  "suggestions": ["2-3 short next requests the owner might make", ...]
}
"files" holds only the files you change, each complete (never a diff or an excerpt). If you
ask a question, leave "files" empty. "settings" (leave it out if nothing changes): a variable
set to a string adds or changes it, null removes it. A secret set to "" asks the owner to type
its value when they accept; set a secret's value only when the owner wrote it in their request
(never invent one); null removes it. Every tag.secret/tag.var name your code reads must exist
or be in "settings". Write plain, short English."""

REFERENCE_APPS = ("pill", "weather", "hello")     # working apps shown to the AI as examples
REFERENCE_MAX = 16000                             # characters of example code
REPAIR_ROUNDS = 2                                 # times the AI may fix its own errors


def _sdk_reference() -> str:
    return inspect.getsource(sdk_module)


def _reference_apps(host, app_id: str) -> str:
    """Up to two of the bundled apps, whole, as worked examples."""
    out, used = [], 0
    for ref in REFERENCE_APPS:
        if ref == app_id or len(out) >= 2:
            continue
        folder = host.root / ref
        parts = []
        for name in ("app.py", "layout.xml"):
            f = folder / name
            if f.is_file():
                parts.append(f"--- inkapps/{ref}/{name} ---\n{f.read_text(encoding='utf-8')}")
        text = "\n".join(parts)
        if not text or used + len(text) > REFERENCE_MAX:
            continue
        out.append(text)
        used += len(text)
    return "\n\n".join(out)


def _system_prompt(host, app_id: str) -> str:
    from ..inklayout import skill
    refs = _reference_apps(host, app_id)
    return (RULES
            + "\n\n=== SDK source (shelfkit/inkservices/sdk.py) ===\n" + _sdk_reference()
            + "\n\n=== InkLayout reference ===\n" + skill.skill_markdown(None, "portrait")
            + (f"\n\n=== Working apps to learn from (not the app you change) ===\n{refs}" if refs else ""))


def _context_text(host, store, app_id: str, ctx: dict) -> str:
    parts = [f"=== the app you work on: inkapps/{app_id}/ ==="]
    for f in files(host, app_id)["files"]:
        parts.append(f"=== {f['name']} ===\n{f['text']}")
    item = host.loaded.get(app_id)
    if item and item.error:
        parts.append(f"=== the app does not load right now ===\n{item.error}")
    try:
        data, tagv, shared, now, _ = _virtual_view(host, app_id)
        parts.append("=== the virtual tag's layout data (what @app.data returns now) ===\n"
                     + json.dumps(_jsonable(data), indent=1)[:6000])
        parts.append(f"=== the virtual tag ===\n{json.dumps(_jsonable(tagv))[:1500]}\nnow: "
                     f"{now.isoformat(timespec='minutes')}")
    except AppError as exc:
        parts.append(f"=== the virtual tag could not draw ===\n{exc}")
    tokens = [t["name"] for t in ai.tokens_public(store)] if store is not None else []
    mine = appsettings.public(store, app_id) if store is not None else {"vars": [], "secrets": []}
    parts.append("=== the app's settings (Develop > Settings) ===\nvariables (tag.var): "
                 + (json.dumps({v["name"]: v["value"] for v in mine["vars"]})[:2000] if mine["vars"] else "none")
                 + "\nsecrets (tag.secret; names only): "
                 + (", ".join(x["name"] for x in mine["secrets"]) or "none")
                 + "\nglobal API tokens (tag.secret or tag.token; names only): "
                 + (", ".join(tokens) or "none"))
    log = host.log(app_id)[-30:]
    if log:
        parts.append("=== the app's recent log ===\n" + "\n".join(line for _, line in log))
    if ctx:
        parts.append("=== what the owner is looking at ===\n" + json.dumps(ctx)[:2000])
    return "\n\n".join(parts)


def _step(job, title, detail="", state="done", **extra):
    job["steps"].append({"title": title, "detail": detail, "state": state, **extra})


def start_agent(host, store, app_id: str, prompt: str, provider: str | None = None,
                ctx: dict | None = None) -> dict:
    prompt = str(prompt or "").strip()
    if not prompt:
        raise AppError("say what to build or change")
    _folder(host, app_id)
    who = ai.describe(store, provider)
    if who.get("error"):
        raise AppError(who["error"])
    job = {"id": uuid.uuid4().hex[:12], "app": app_id, "prompt": prompt[:4000], "status": "running",
           "steps": [], "started": time.time(), "who": who, "proposal": None, "question": None,
           "answers": [], "suggestions": [], "summary": "", "error": None, "preview": None}
    with _LOCK:
        _JOBS[job["id"]] = job
        for old in [k for k, v in _JOBS.items() if time.time() - v["started"] > 6 * 3600]:
            del _JOBS[old]
    threading.Thread(target=_run_agent, args=(host, store, job, provider, ctx or {}),
                     name=f"agent-{job['id']}", daemon=True).start()
    return job


def _asked(job, reply):
    u = reply["usage"]
    job["steps"][-1].update(state="done", detail=f"{reply['model']} · {reply['seconds']} s"
                            + (f" · {u.get('output')} tokens out" if u.get("output") else "")
                            + (f" · {u.get('cached')} read from cache" if u.get("cached") else ""))


def _run_agent(host, store, job: dict, provider: str | None, ctx: dict) -> None:
    app_id = job["app"]
    try:
        current = {f["name"]: f["text"] for f in files(host, app_id)["files"]}
        system = _system_prompt(host, app_id)
        refs = [r for r in REFERENCE_APPS if r != app_id and (host.root / r / "app.py").is_file()][:2]
        _step(job, f"Read {', '.join(current)}, the SDK and the InkLayout reference",
              f"{len(current)} files" + (f"; examples: {', '.join(refs)}" if refs else ""))
        history = list(_HISTORY.get(app_id, []))
        user = f"{_context_text(host, store, app_id, ctx)}\n\n=== the owner asks ===\n{job['prompt']}"
        messages = history + [{"role": "user", "content": user}]
        _step(job, f"Asking {job['who']['label']}", job["who"]["model"], state="running")
        reply = ai.ask(store, system, messages, provider=provider, json_mode=True)
        _asked(job, reply)
        answer = ai.parse_json(reply["text"])
        plan = [str(s)[:200] for s in (answer.get("plan") or [])][:8]
        if plan:
            _step(job, "Plan", "; ".join(plan))

        # the AI's own errors go back to it, a couple of times, before the owner sees them
        rounds = 0
        while True:
            proposed = answer.get("files") or {}
            sett = answer.get("settings") if isinstance(answer.get("settings"), dict) else {}
            var_preview = sett.get("vars") if isinstance(sett.get("vars"), dict) else None
            problems = _propose(host, job, current, proposed, var_preview) if proposed else []
            if not problems or rounds >= REPAIR_ROUNDS:
                break
            rounds += 1
            job["proposal"] = None
            job["preview"] = None
            for s in job["steps"]:            # the earlier proposal is no longer the one to accept
                if s.get("change"):
                    s.update(change=False, title="Proposed a change (with errors)", state="error",
                             detail="sent back to the AI to fix")
            _step(job, f"Fixing its own errors (round {rounds})", "; ".join(problems)[:400], state="running")
            messages = messages + [
                {"role": "assistant", "content": reply["text"][:30000]},
                {"role": "user", "content": "Your change was checked (not run) and has these problems:\n- "
                 + "\n- ".join(problems) + "\nAnswer again with the same JSON, with the complete "
                 "corrected files."}]
            reply = ai.ask(store, system, messages, provider=provider, json_mode=True)
            _asked(job, reply)
            answer = ai.parse_json(reply["text"])

        merged = {**current, **((job["proposal"] or {}).get("files") or {})}
        notes = _settings_proposal(host, store, job, answer, merged)
        if notes:
            _step(job, "Note", "; ".join(notes)[:400])
        with _LOCK:   # the conversation keeps the ask (without the bulky context) and the answer
            hist = _HISTORY.setdefault(app_id, [])
            said = reply["text"][:20000]
            for v in job.get("_secret_values", {}).values():
                said = said.replace(v, "(secret)")
            asked = job["prompt"]
            for v in job.get("_secret_values", {}).values():
                asked = asked.replace(v, "(secret)")
            hist += [{"role": "user", "content": asked}, {"role": "assistant", "content": said}]
            del hist[:-HISTORY_KEEP]
        job["summary"] = str(answer.get("summary") or "")[:500]
        job["suggestions"] = [str(s)[:120] for s in (answer.get("suggestions") or [])][:3]
        if answer.get("question"):
            job["question"] = str(answer["question"])[:300]
            job["answers"] = [str(a)[:80] for a in (answer.get("answers") or [])][:4]
            _step(job, job["question"], "needs your input", state="question")
        job["status"] = "question" if job["question"] else ("proposed" if job["proposal"] else "done")
    except (ai.AIError, AppError) as exc:
        job["error"] = str(exc)
        job["status"] = "error"
        for s in job["steps"]:
            if s["state"] == "running":
                s["state"] = "error"
        _step(job, "Stopped", str(exc), state="error")
    except Exception as exc:  # noqa: BLE001 - never leave a job spinning
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["status"] = "error"
        _step(job, "Stopped", job["error"], state="error")
    job["seconds"] = round(time.time() - job["started"])


# everything an app may use on `app`: InkApp's methods and the attributes __init__ sets
_INKAPP_NAMES = set(dir(sdk_module.InkApp)) | set(re.findall(r"self\.(\w+)\s*[:=]",
                                                              inspect.getsource(sdk_module.InkApp)))


def _contract(app_id: str, source: str, all_files: dict) -> list[str]:
    """What the loader and host need from app.py, read from its syntax tree (never run)."""
    try:
        tree = ast.parse(source, "app.py")
    except SyntaxError as exc:
        return [f"syntax error in app.py line {exc.lineno}: {exc.msg}"]
    problems = []
    made = None
    for node in tree.body:
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "app" for t in node.targets)
                and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", None) == "InkApp"):
            made = node.value
    if made is None:
        problems.append('app.py must define  app = InkApp("%s", ...)  at module level' % app_id)
    else:
        first = made.args[0] if made.args else None
        if not (isinstance(first, ast.Constant) and first.value == app_id):
            problems.append(f'app.py line {made.lineno}: the app id must be "{app_id}" (the folder name)')
        for kw in made.keywords:
            if kw.arg == "layout" and isinstance(kw.value, ast.Constant) and kw.value.value not in all_files:
                problems.append(f"app.py line {made.lineno}: layout={kw.value.value!r} but there is no such file")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "app" \
                and node.attr not in _INKAPP_NAMES:
            problems.append(f"app.py line {node.lineno}: InkApp has no {node.attr!r}")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                top = name.split(".")[0]
                if top and top != "shelfkit" and importlib.util.find_spec(top) is None:
                    problems.append(f"app.py line {node.lineno}: there is no module {top!r} on this server")
    return problems[:8]


def _reads(sources: dict) -> dict:
    """{"secret": {names}, "var": {names}, "var_nodefault": {names}} the code reads."""
    found = {"secret": set(), "var": set(), "var_nodefault": set()}
    for name, text in sources.items():
        if not name.endswith(".py"):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("secret", "token", "var") and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                key = "var" if node.func.attr == "var" else "secret"
                found[key].add(node.args[0].value)
                if key == "var" and len(node.args) < 2 and not node.keywords:
                    found["var_nodefault"].add(node.args[0].value)
    return found


def _settings_proposal(host, store, job: dict, answer: dict, sources: dict) -> list[str]:
    """Turn the answer's "settings" into a change the owner accepts with the files; secrets the
    code reads but nobody has are added as ones to ask for. Returns notes for the check step."""
    raw = answer.get("settings") if isinstance(answer.get("settings"), dict) else {}
    mine = appsettings.public(store, job["app"]) if store is not None else {"vars": [], "secrets": []}
    old_vars = {v["name"]: v["value"] for v in mine["vars"]}
    old_secrets = {x["name"] for x in mine["secrets"]}
    tokens = {t["name"] for t in ai.tokens_public(store)} if store is not None else set()
    vars_out, secrets_out, values, notes = [], [], {}, []
    for name, value in list((raw.get("vars") or {}).items())[:30]:
        name = str(name)
        if not appsettings.NAME.fullmatch(name):
            notes.append(f"ignored the variable name {name!r}")
            continue
        if value is None:
            if name in old_vars:
                vars_out.append({"name": name, "old": old_vars[name], "new": None})
        elif str(value) != old_vars.get(name):
            vars_out.append({"name": name, "old": old_vars.get(name), "new": str(value)[:appsettings.MAX_VALUE]})
    for name, value in list((raw.get("secrets") or {}).items())[:30]:
        name = str(name)
        if not appsettings.NAME.fullmatch(name):
            notes.append(f"ignored the secret name {name!r}")
            continue
        if value is None:
            if name in old_secrets:
                secrets_out.append({"name": name, "action": "remove"})
        elif str(value):
            secrets_out.append({"name": name, "action": "set", "exists": name in old_secrets})
            values[name] = str(value)[:appsettings.MAX_VALUE]
        elif name not in old_secrets:
            secrets_out.append({"name": name, "action": "ask", "token": name in tokens})
    reads = _reads(sources)
    named = {x["name"] for x in secrets_out}
    for name in sorted(reads["secret"] - old_secrets - tokens - named):
        secrets_out.append({"name": name, "action": "ask", "token": False, "why": "the code reads it"})
    gone_vars = {v["name"] for v in vars_out if v["new"] is None}
    have_vars = (set(old_vars) | {v["name"] for v in vars_out}) - gone_vars
    for name in sorted(reads["var_nodefault"] - have_vars):
        notes.append(f'tag.var("{name}") has no default and no such variable is set (it reads None)')
    job["_secret_values"] = values
    if vars_out or secrets_out:
        if not job["proposal"]:
            job["proposal"] = {"files": {}, "stats": [], "before": {}}
            _step(job, "Proposed a settings change", "not saved until you accept", change=True, files="settings")
        job["proposal"]["settings"] = {"vars": vars_out, "secrets": secrets_out}
        parts = [f"{v['name']} = {v['new']!r}" if v["new"] is not None else f"remove {v['name']}" for v in vars_out]
        parts += [f"{x['action']} secret {x['name']}" for x in secrets_out]
        _step(job, "Settings", "; ".join(parts)[:400])
    return notes


def _propose(host, job: dict, current: dict, proposed: dict, var_preview: dict | None = None) -> list[str]:
    """Check a proposal without running it and keep it on the job. Returns the problems that
    should go back to the AI (errors only; layout warnings are the owner's call)."""
    try:
        clean = _check_files({k: v for k, v in proposed.items() if v != current.get(k)})
    except AppError as exc:
        _step(job, "The proposal was not usable", str(exc), state="error")
        return [str(exc)]
    if not clean:
        _step(job, "No file changes", "the proposal matched the files as they are")
        return []
    stats = []
    for name, text in clean.items():
        old = current.get(name, "").splitlines()
        new = text.splitlines()
        added = removed = 0
        for line in difflib.ndiff(old, new):
            added += line.startswith("+ ")
            removed += line.startswith("- ")
        stats.append({"name": name, "added": added, "removed": removed, "new": name not in current})
    job["proposal"] = {"files": clean, "stats": stats, "before": {k: current.get(k, "") for k in clean}}
    _step(job, "Proposed a change", "not saved until you accept", change=True,
          files=" · ".join(f"{s['name']} +{s['added']} −{s['removed']}" for s in stats))

    merged = {**current, **clean}
    problems, checks = [], []
    if "app.py" in clean or "layout.xml" in clean:
        contract = _contract(job["app"], merged.get("app.py", ""), merged)
        problems += contract
        checks.append("app.py checked: " + ("ok (it runs only after you accept)" if not contract
                                            else "; ".join(contract)))
    for name in [n for n in clean if n.endswith(".py") and n != "app.py"]:
        try:
            compile(clean[name], name, "exec")
        except SyntaxError as exc:
            problems.append(f"syntax error in {name} line {exc.lineno}: {exc.msg}")
    layout_name = next((n for n in clean if n.endswith(".xml")), None)
    if layout_name:
        try:
            data, tagv, shared, now, display = _virtual_view(host, job["app"], var_preview)
            result = inklayout.render(clean[layout_name], data, tag=tagv, display=display,
                                      now=now, shared=shared)
            buf = io.BytesIO()
            result.image.save(buf, format="PNG")
            job["preview"] = base64.b64encode(buf.getvalue()).decode("ascii")
            job["proposal"]["diagnostics"] = result.diagnostics
            errors = [d for d in result.diagnostics if d["level"] == "error"]
            warnings = [d for d in result.diagnostics if d["level"] in ("warn", "warning")]
            note = " (drawn with the data the saved app.py returns)" if "app.py" in clean else ""
            checks.append(f"{layout_name} drawn on the virtual tag: {len(errors)} errors, "
                          f"{len(warnings)} warnings{note}")
            problems += [f"{layout_name} at {d['at']}: {d['msg']}" for d in errors[:6]]
        except AppError as exc:
            checks.append(f"layout not drawn: {exc}")
    job["proposal"]["broken"] = bool(problems)
    if checks:
        _step(job, "Checked without running it", "; ".join(checks), state="error" if problems else "done")
    return problems


def job_view(job_id: str) -> dict:
    job = _JOBS.get(job_id or "")
    if job is None:
        raise AppError("no such agent job (the server may have restarted)")
    view = {k: v for k, v in job.items() if k != "proposal" and not k.startswith("_")}
    if job["proposal"]:
        p = job["proposal"]
        view["proposal"] = {"stats": p["stats"], "files": p["files"], "before": p["before"],
                            "broken": p.get("broken", False), "diagnostics": p.get("diagnostics", []),
                            "settings": p.get("settings")}
    return view


def apply(host, job_id: str, secrets: dict | None = None) -> dict:
    job = _JOBS.get(job_id or "")
    if job is None or not job["proposal"]:
        raise AppError("nothing to accept")
    if job.get("applied"):
        raise AppError("already accepted")
    p = job["proposal"]
    if p["files"]:
        result = save(host, job["app"], p["files"], note=f"the AI's change for \"{job['prompt'][:120]}\"",
                      label="AI")
    else:
        result = {"ok": True, "checkpoint": None, "error": None}
    missing = []
    sett = p.get("settings") or {}
    for v in sett.get("vars", []):
        appsettings.save(host.store, job["app"], "var", v["name"], v["new"], remove=v["new"] is None)
    typed = {str(k): str(v) for k, v in (secrets or {}).items() if v}
    for x in sett.get("secrets", []):
        if x["action"] == "remove":
            appsettings.save(host.store, job["app"], "secret", x["name"], remove=True)
        else:
            value = typed.get(x["name"]) or job.get("_secret_values", {}).get(x["name"])
            if value:
                appsettings.save(host.store, job["app"], "secret", x["name"], value)
            elif not x.get("token"):
                missing.append(x["name"])
    job.pop("_secret_values", None)
    result["missing_secrets"] = missing
    job["applied"] = True
    job["status"] = "accepted"
    with _LOCK:
        _HISTORY.setdefault(job["app"], []).append(
            {"role": "user", "content": "(I accepted that change; the files and settings are now as you proposed.)"})
        _HISTORY.setdefault(job["app"], []).append({"role": "assistant", "content": '{"summary": "Noted."}'})
    return result


def reject(job_id: str) -> dict:
    job = _JOBS.get(job_id or "")
    if job is None:
        raise AppError("no such agent job")
    job["status"] = "rejected"
    with _LOCK:
        _HISTORY.setdefault(job["app"], []).append(
            {"role": "user", "content": "(I rejected that change; the files are unchanged.)"})
        _HISTORY.setdefault(job["app"], []).append({"role": "assistant", "content": '{"summary": "Noted."}'})
    return {"ok": True}


def history(app_id: str) -> list[dict]:
    jobs = sorted((j for j in _JOBS.values() if j["app"] == app_id), key=lambda j: j["started"])
    return [{"id": j["id"], "prompt": j["prompt"], "status": j["status"], "summary": j["summary"]}
            for j in jobs[-20:]]


def forget(app_id: str) -> None:
    with _LOCK:
        _HISTORY.pop(app_id, None)


# ── HTTP ──────────────────────────────────────────────────────────────────────
def handle_get(handler, path: str, query: dict) -> bool:
    if not path.startswith("/api/dev/"):
        return False
    host = getattr(handler.app, "inkhost", None)
    if host is None:
        handler._error("InkServices is off (the server runs without a store)", HTTPStatus.SERVICE_UNAVAILABLE)
        return True
    q = {k: (v or [""])[0] for k, v in query.items()}
    try:
        if path == "/api/dev/files":
            handler._json(files(host, q.get("app", "")))
        elif path == "/api/dev/checkpoints":
            handler._json({"checkpoints": checkpoints(host, q.get("app", ""))})
        elif path == "/api/dev/agent":
            handler._json(job_view(q.get("job", "")))
        elif path == "/api/dev/settings":
            app_id = q.get("app", "")
            app = host._app(app_id)
            handler._json({**appsettings.public(handler.app.store, app_id),
                           "tokens": [t["name"] for t in ai.tokens_public(handler.app.store)],
                           "fields": [f.as_dict() for f in app.config_fields]})
        elif path == "/api/dev/agent/history":
            handler._json({"jobs": history(q.get("app", "")),
                           "ai": ai.describe(handler.app.store)})
        else:
            handler._error(f"no such path {path}", HTTPStatus.NOT_FOUND)
    except AppError as exc:
        handler._error(str(exc), HTTPStatus.NOT_FOUND)
    return True


def handle_post(handler, path: str, body: dict) -> bool:
    if not path.startswith("/api/dev/"):
        return False
    host = getattr(handler.app, "inkhost", None)
    if host is None:
        handler._error("InkServices is off (the server runs without a store)", HTTPStatus.SERVICE_UNAVAILABLE)
        return True
    app_id = str(body.get("app") or "")
    try:
        if path == "/api/dev/save":
            handler._json(save(host, app_id, body.get("files") or {}, str(body.get("note") or "edited by hand")))
        elif path == "/api/dev/settings":
            _folder(host, app_id)
            handler._json(appsettings.save(handler.app.store, app_id, str(body.get("kind") or ""),
                                           str(body.get("name") or ""), body.get("value"),
                                           bool(body.get("remove"))))
        elif path == "/api/dev/delete":
            handler._json(delete(host, app_id, str(body.get("file") or "")))
        elif path == "/api/dev/revert":
            handler._json(revert(host, app_id, str(body.get("id") or "")))
        elif path == "/api/dev/virtual":
            handler._json(virtual(host, app_id, str(body.get("do") or "draw"), body.get("action"),
                                  body.get("value"), body.get("now"), body.get("config")))
        elif path == "/api/dev/agent":
            job = start_agent(host, handler.app.store, app_id, body.get("prompt"),
                              body.get("provider") or None, body.get("context") or {})
            handler._json({"job": job["id"]})
        elif path == "/api/dev/agent/apply":
            handler._json(apply(host, str(body.get("job") or ""), body.get("secrets") or {}))
        elif path == "/api/dev/agent/reject":
            handler._json(reject(str(body.get("job") or "")))
        elif path == "/api/dev/agent/forget":
            forget(app_id)
            handler._json({"ok": True})
        else:
            handler._error(f"no such path {path}", HTTPStatus.NOT_FOUND)
    except AppError as exc:
        handler._error(str(exc))
    return True
