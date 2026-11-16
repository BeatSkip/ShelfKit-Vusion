"""The Develop screen's server side: an app's files, checkpoints, a virtual tag, and
an AI agent that proposes changes.

    GET  /api/dev/files?app=              the app's own text files, editable
    POST /api/dev/save     {app, files: {name: text}, note?}   checkpoint, write, reload
    GET  /api/dev/checkpoints?app=        saved versions of the app's files
    POST /api/dev/revert   {app, id}      back to a checkpoint (after saving one of now)
    POST /api/dev/virtual  {app, do, action?, value?, now?, config?}
                           do: draw | open | action | timers | config | reset
                           -> {png (base64), ms, diagnostics, data, config, error}
    POST /api/dev/agent    {app, prompt, provider?, context?}  -> {job}
    GET  /api/dev/agent?job=              the job: steps so far, the proposal, a question
    POST /api/dev/agent/apply   {job}     checkpoint, write the proposal, reload
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

import base64
import difflib
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


def revert(host, app_id: str, cid: str) -> dict:
    if not re.fullmatch(r"[0-9a-f-]{10,40}", cid or ""):
        raise AppError("no such checkpoint")
    folder = _folder(host, app_id)
    source = _checkpoint_root(folder) / cid
    if not (source / "checkpoint.json").is_file():
        raise AppError("no such checkpoint")
    restored = {f.name: f.read_text(encoding="utf-8") for f in source.iterdir()
                if f.is_file() and EDITABLE.match(f.name)}
    meta = json.loads((source / "checkpoint.json").read_text(encoding="utf-8"))
    return save(host, app_id, restored, note=f"revert to {meta.get('label') or cid}")


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
    return {"ok": error is None, "error": error, "png": png, "ms": ms, "diagnostics": diagnostics,
            "data": _jsonable(data), "state": _jsonable(tag.data), "config": tag.config,
            "now": tag.now.isoformat(timespec="minutes")}


def _jsonable(value):
    return json.loads(json.dumps(value, default=str))


def _virtual_view(host, app_id: str):
    """(layout data, tag view, shared, now, display) the virtual tag's screen is drawn from."""
    app = host._app(app_id)
    with host._app_lock(app_id):
        st = host.store_of(app_id)
        tag = host._context(app, VIRTUAL, st)
        tag.shared = st.state(VIRTUAL_SHARED)
        try:
            data = app.data_fn(tag) if app.data_fn is not None else tag.data
        except Exception:  # noqa: BLE001 - app code; the draft is still worth a look
            data = tag.data
    return data, tag_view(tag), tag.shared, tag.now, tag.display.id


# ── the agent ─────────────────────────────────────────────────────────────────
_JOBS: dict[str, dict] = {}
_HISTORY: dict[str, list[dict]] = {}
_LOCK = threading.Lock()

RULES = """You build and change apps for ShelfKit: small Python programs that draw the screen of
an e-paper shelf tag (152 x 296 pixels, portrait, black / white / red only, no grey) and answer
the tag's NFC link with a phone page of buttons and text boxes. An app is a folder with app.py
(an InkApp, see the SDK source below) and usually layout.xml (an InkLayout screen, see the
InkLayout reference below), filled from @app.data.

Rules that matter on these tags:
- Every screen change costs battery and reaches the glass only at the tag's next check-in
  (up to ~5 minutes). Never draw a clock or seconds; redraw only when something the owner
  cares about changed. The host never sends a picture identical to the last one.
- Use @app.every(minutes=N) for fetching data (N >= 15 unless asked), never fetch in
  @app.data or @app.render. tag.fetch_json() is the only network call.
- Keep per-tag state in tag.data, settings in app.setting/config_field, shared state in
  tag.shared. Use tag.now for the time (the owner may pretend another time).
- Text must fit its box: prefer fit="shrink" or max lines over overflowing.

Answer with one JSON object:
{
  "summary": "one sentence: what you changed, or what you need to know",
  "plan": ["short step", ...],
  "files": {"layout.xml": "<the complete new file>", "app.py": "<the complete new file>"},
  "question": "only if you cannot go on without the owner's choice, else null",
  "answers": ["2-4 short answers the owner can click", ...],
  "suggestions": ["2-3 short next requests the owner might make", ...]
}
"files" holds only the files you change, each complete (never a diff or an excerpt). Keep the
app's id and folder. If you ask a question, leave "files" empty. Write plain, short English."""


def _sdk_reference() -> str:
    return inspect.getsource(sdk_module)


def _context_text(host, app_id: str, ctx: dict) -> str:
    parts = []
    for f in files(host, app_id)["files"]:
        parts.append(f"=== {f['name']} ===\n{f['text']}")
    try:
        data, tagv, shared, now, _ = _virtual_view(host, app_id)
        parts.append("=== the virtual tag's layout data (what @app.data returns) ===\n"
                     + json.dumps(_jsonable(data), indent=1)[:6000])
        parts.append(f"=== now ===\n{now.isoformat(timespec='minutes')}")
    except AppError as exc:
        parts.append(f"=== the app does not load ===\n{exc}")
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


def _run_agent(host, store, job: dict, provider: str | None, ctx: dict) -> None:
    app_id = job["app"]
    try:
        current = {f["name"]: f["text"] for f in files(host, app_id)["files"]}
        from ..inklayout import skill
        system = (RULES + "\n\n=== SDK source (shelfkit/inkservices/sdk.py) ===\n" + _sdk_reference()
                  + "\n\n=== InkLayout reference ===\n" + skill.skill_markdown(None, "portrait"))
        _step(job, f"Read {', '.join(current)} and the InkLayout reference", f"{len(current)} files")
        history = list(_HISTORY.get(app_id, []))
        user = f"{_context_text(host, app_id, ctx)}\n\n=== the owner asks ===\n{job['prompt']}"
        messages = history + [{"role": "user", "content": user}]
        _step(job, f"Asking {job['who']['label']}", job["who"]["model"], state="running")
        reply = ai.ask(store, system, messages, provider=provider, json_mode=True)
        job["steps"][-1].update(state="done", detail=f"{reply['model']} · {reply['seconds']} s"
                                + (f" · {reply['usage'].get('output')} tokens out" if reply["usage"].get("output") else ""))
        answer = ai.parse_json(reply["text"])
        with _LOCK:   # the conversation keeps the ask (without the bulky context) and the answer
            hist = _HISTORY.setdefault(app_id, [])
            hist += [{"role": "user", "content": job["prompt"]}, {"role": "assistant", "content": reply["text"][:20000]}]
            del hist[:-HISTORY_KEEP]
        job["summary"] = str(answer.get("summary") or "")[:500]
        job["suggestions"] = [str(s)[:120] for s in (answer.get("suggestions") or [])][:3]
        plan = [str(s)[:200] for s in (answer.get("plan") or [])][:8]
        if plan:
            _step(job, "Plan", "; ".join(plan))
        proposed = answer.get("files") or {}
        if proposed:
            _propose(host, job, current, proposed)
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


def _propose(host, job: dict, current: dict, proposed: dict) -> None:
    try:
        clean = _check_files({k: v for k, v in proposed.items() if v != current.get(k)})
    except AppError as exc:
        _step(job, "The proposal was not usable", str(exc), state="error")
        return
    if not clean:
        _step(job, "No file changes", "the proposal matched the files as they are")
        return
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

    checks = []
    if "app.py" in clean:
        try:
            compile(clean["app.py"], "app.py", "exec")
            checks.append("app.py compiles (it runs only after you accept)")
        except SyntaxError as exc:
            checks.append(f"syntax error in app.py line {exc.lineno}: {exc.msg}")
            job["proposal"]["broken"] = True
    if "layout.xml" in clean:
        try:
            data, tagv, shared, now, display = _virtual_view(host, job["app"])
            result = inklayout.render(clean["layout.xml"], data, tag=tagv, display=display,
                                      now=now, shared=shared)
            buf = io.BytesIO()
            result.image.save(buf, format="PNG")
            job["preview"] = base64.b64encode(buf.getvalue()).decode("ascii")
            job["proposal"]["diagnostics"] = result.diagnostics
            errors = [d for d in result.diagnostics if d["level"] == "error"]
            warnings = [d for d in result.diagnostics if d["level"] == "warning"]
            checks.append(f"layout drawn on the virtual tag: {len(errors)} errors, {len(warnings)} warnings")
            if errors:
                job["proposal"]["broken"] = True
        except AppError as exc:
            checks.append(f"layout not drawn: {exc}")
    if checks:
        _step(job, "Checked without running it", "; ".join(checks),
              state="error" if job["proposal"].get("broken") else "done")


def job_view(job_id: str) -> dict:
    job = _JOBS.get(job_id or "")
    if job is None:
        raise AppError("no such agent job (the server may have restarted)")
    view = {k: v for k, v in job.items() if k != "proposal"}
    if job["proposal"]:
        p = job["proposal"]
        view["proposal"] = {"stats": p["stats"], "files": p["files"], "before": p["before"],
                            "broken": p.get("broken", False), "diagnostics": p.get("diagnostics", [])}
    return view


def apply(host, job_id: str) -> dict:
    job = _JOBS.get(job_id or "")
    if job is None or not job["proposal"]:
        raise AppError("nothing to accept")
    if job.get("applied"):
        raise AppError("already accepted")
    result = save(host, job["app"], job["proposal"]["files"], note=f"the AI's change for \"{job['prompt'][:120]}\"",
                  label="AI")
    job["applied"] = True
    job["status"] = "accepted"
    with _LOCK:
        _HISTORY.setdefault(job["app"], []).append(
            {"role": "user", "content": "(I accepted that change; the files are now as you proposed.)"})
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
            handler._json(apply(host, str(body.get("job") or "")))
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
