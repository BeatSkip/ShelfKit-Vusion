# InkServices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let small Python "ink apps" own a tag's screen: they draw it, react to a phone opening the tag's NFC link, and keep their own data, managed from an Apps tab in the server UI.

**Architecture:** A new package `shelfkit/inkservices/` holds the app SDK (what an app author imports), a loader for app folders under `ShelfKit-Server/inkapps/`, and an `AppHost` that binds one app to each tag, renders it to a 152x296 black/white/red PNG, and pushes it through the existing queue (`App.enqueue("image", …)`). A phone reaches an app through the tag's NFC URL `<address>/tag/<ID>`, served on the server's own port so one reverse proxy can forward just `/tag/` to phones (changed 2026-11-12; the first draft had a second LAN listener and `/t/`).

**Tech Stack:** Python standard library (`http.server`, `sqlite3`, `importlib`) and Pillow, as the server already uses. No new dependencies until chunk 8 (AI), which adds the Anthropic SDK.

**Spec:** `Documentation/InkServices.md`

## Global Constraints

- Panel: 152x296 portrait, three colours: black `(0,0,0)`, red `(255,0,0)`, white `(255,255,255)` (`service_image.py` constants). App images are pushed with `fit="stretch"`, `dither="threshold"`.
- One app per tag: a tag shows one screen. An app can run on many tags.
- One shared tag firmware binary: no URL and no ID compiled into the firmware. The ID comes from the tag's flash, and the URL host is whatever was written to the NFC chip (for now, by phone).
- The admin UI and API stay bound to `127.0.0.1` by default. Phones reach only `/tag/<ID>` pages and their form posts, through a reverse proxy that forwards that path alone.
- Tag IDs in URLs and the store are 4 upper-case hex digits (`f"{addr:04X}"`, as everywhere in the server).
- Every image push costs tag battery. Never push an image identical to the last one queued for that tag, and never queue more than one pending app image per tag.
- Tests follow the repo's style: plain scripts with a `check(name, ok)` helper, no pytest (it isn't installed). Run with `python ShelfKit-Server/tests/<file>.py`, where exit code 0 means pass.
- A broken app (import error, exception in a callback) must never stop the server or affect another app.

## Review Focus

1. **An app raises in `render` or a callback.** Expected: no push, the error is in that app's log and shown on the phone page, and other tags keep working. (Task 4, `check("render error is contained", …)`)
2. **The app redraws an identical screen**, e.g. a clock refresh where nothing changed. Expected: no radio transfer. (Task 4, `check("identical render is not pushed", …)`)
3. **Several button presses before the tag polls.** Expected: one pending job carrying the latest image, not a stack of transfers. (Task 5)
4. **A tag is renamed or forgotten.** Expected: its binding and app data follow the new ID or are removed. (Task 1)
5. **An app folder with a syntax error or no `app` object.** Expected: listed with its error, the server starts, and other apps load. (Task 3)

---

## Progress (2026-11-12)

- **Chunk 1 is done** (Tasks 1–5), with rulings noted under Tasks 1 and 2. Additions beyond the plan:
  - `AppHost.preview_png`, `layout_result` and `set_config`
  - `App.start_inkservices()` and `App.ink_tag_info()`
  - `python -m shelfkit.inkservices list|render [--boxes]`
- **InkLayout L1, most of L2, and the L3 skill file are done** (see `Documentation/InkLayout.md` §7). Bundled fonts (the rest of L3) and L4 (model chat) are open. `hello` is now a layout app (`inkapps/hello/layout.xml`).
- **Chunk 2 is done (2026-11-12): the Apps screen** (`#apps` in the main page, code in `static/apps.js`):
  - Apps listed on the left, failed ones marked, with the error and its line number in the detail
  - Per app: the tags it runs on (last sent, Refresh now, Stop) and Run on another tag. Tags already running another app are labelled "replaces …".
  - The picked tag's current screen, its settings form filled with the saved values (an empty field means the app's default), the phone-page buttons and text fields, Simulate NFC tap, and the NFC link
  - Stored data: file, size, the app's own tables with row counts, the shared document, and the picked tag's settings and data. `GET /api/inkapps/data?app=` (`AppHost.app_data`, `AppStore.dump`). Looking at an app never creates its database.
  - Log. Actions now log what they did (`action 'add': screen queued`).
  - Refreshes every 5 s while open. The detail is rebuilt only when its shape changes, so typing is never lost. The preview is fetched again only after an action or a push.
- **Chunk 5 is done (2026-11-12): timers and the first real apps.**
  - `@app.every(minutes=N)` (at least 1 minute). A timer runs once when the app is put on a tag, then every N minutes on a scheduler thread (`AppHost.start_scheduler`, started by `shelfkit-server.py`, stopped by `close`).
  - After a restart the first pass only learns the timers, so a restart sets off no burst of fetches. A failing timer waits its full interval, with no retry loop.
  - The screen is redrawn after each run and sent only if it changed. Runs are logged only when they push or fail.
  - `tag.fetch_json(url, params)`: GET a JSON API, http(s) only, 2 MB cap, generic User-Agent. It goes through the host (`AppHost(fetch=…)`), so tests and the later subprocess move can swap it.
  - `AppHost(clock=…)` sets the time apps draw for, so tests can pick it.
  - The Apps tab's **Refresh now** runs the timers first (fresh data), then redraws. It also shows how often an app updates itself.
  - **`inkapps/pill`** (spec idea 1):
    - Input: an NFC tap logs today's pill (once a day); the phone page has Taken and Undo last.
    - Screen: a month grid (taken black, missed red since tracking began, today ringed red, pill-free days unboxed), and the last time taken.
    - Bottom bar: Due by / Take your pill (red after the reminder time) / Taken today / Pill-free day.
    - Settings: reminder time, pack start, pill-free days.
  - **`inkapps/weather`** (spec idea 2):
    - Data: Open-Meteo with no key, every 30 min. One fetch per place is shared by all its tags.
    - Offline: keeps the newest forecast and says how old it is after 3 h.
    - Moon phase is worked out locally.
    - Settings: place, latitude, longitude. Nothing is fetched until they are set.
  - Checked against one real Open-Meteo response.
  - **Fix:** forgetting or renaming a tag no longer creates an empty database in every app's folder.
- **`/inkapps.html` is now only the layout playground** (linked from the Apps screen), with a link to the skill file.
- **Phone pages are done (chunk 3, 2026-11-12), on the main port:**
  - `GET /tag/<ID>` runs the app's `on_open` (the NFC tap), then redirects to `/tag/<ID>/view`; `/tag/<ID>/screen.png` is the current screen; `POST /tag/<ID>/do` runs a button or text field and redirects back. The old `/t/...` answers 301.
  - Every link and redirect is relative, so the pages work under any proxy prefix. Strict CSP, a same-site check (Host or X-Forwarded-Host), form bodies capped at 16 KB.
  - `shelfkit/inkservices/phone.py`, called first by `webapp.py`. `--phone`/`--phone-host` are gone: the tag pages are always on.
  - New setting `public_url` (Settings > Tag pages for phones > Address phones use): the address the Apps tab shows as each tag's NFC link. Startup prints the tag-page address and a reverse-proxy hint.
- **Preview fix:** looking at an app that has no database yet renders against an in-memory store, so nothing is created.
- **Pill screen redrawn for contrast:** taken days solid black with a white bold number, missed days solid red, today a red ring, pill-free days dotted, future days plain. A legend counts taken and missed days, and "Taken today" is a black bar.
- **Routes:** `shelfkit/inkservices/web.py` (admin API), `shelfkit/inkservices/phone.py` (tag pages).
- **Tests:** `python ShelfKit-Server/tests/inkservices_test.py`, `python ShelfKit-Server/tests/inklayout_test.py`, and the existing `smoke.py`. All pass.

## Roadmap: chunks

Each chunk ends with something you can use or test on its own. Only chunk 1 is broken down into tasks here. Each later chunk gets its own detailed plan when it's next, written against the code as it stands then.

| # | Chunk | What you get at the end | Depends on |
|---|-------|-------------------------|-----------|
| 1 | **SDK + host core** | Write an app in `inkapps/<id>/app.py`, bind it to a tag from Python, render it to PNG (`python -m shelfkit.inkservices render hello`), and push it through the normal queue, with duplicate and burst suppression. | – |
| 2 | **Apps tab (admin UI)** | "Apps" tab: list apps with load errors, bind/unbind tags, per-tag config form from the app's declared fields, current-screen preview, "Refresh now", app data viewer, app log. | 1 |
| 3 | **Phone pages** | `/tag/<ID>` on the server's own port (behind a reverse proxy; Settings > Address phones use): a mobile page generated from the bound app's controls (buttons, text field, checklist) plus the tag's current-screen preview. Posts run the callback, refresh the tag and redirect back. Unbound tag: a plain "no app on this tag" page. | 1 (2 helpful) |
| 4 | **Firmware: per-tag NFC URL** | Tag firmware keeps the URL written to the chip by phone, and at boot only makes sure the text after the last `/tag/` is its own ID (see the chunk 4 notes). | 3 for end-to-end testing |
| 5 | **Schedules + first real apps** | `@app.every(minutes=…)` timers; pill tracker (spec idea 1) and weather/moon (idea 2, Open-Meteo, no key) as reference apps. | 1, 3 |
| 6 | **Development mode** | Setting "Development mode" shows a Dev tab: new app from a template, code editor, virtual tag (preview + phone page in a frame), reload, exceptions and log, stats (renders, pushes, skipped duplicates, errors), version history via `git` in the app folder. Tabs: Design / Description & versions / Backend / Debug & stats. | 2, 3 |
| 7 | **Install from git + isolation** | "Install from GitHub URL": `git clone --depth 1` into `inkapps/`, manifest check, installed **disabled**. Apps move to a subprocess each (JSON lines over stdin/stdout), so a crash or hang can't take the server down. Update and remove. | 1–3 |
| 8 | **AI safety review** | Before enabling an installed app: send its source to Claude with a review prompt and show the report. Advisory only, and the UI says so. API key in settings. | 7 |
| 9 | **AI layout chat (then backend agent)** | Chat in the Dev tab: describe the screen, Claude rewrites the app's `render` function, and you see the virtual tag update. Iterate and accept/revert (via the chunk 6 versions). Later the same loop for callbacks. | 6, 8 (key, client) |

### Decisions taken in this plan (veto before chunk 1 starts)

- **Apps run in-process until chunk 7.** Every app talks to the server only through `TagContext`, so moving apps to a subprocess later doesn't change app code. Third-party apps can't be installed until chunk 7 lands. Note that a subprocess isolates crashes, not file or network access: on Windows it is not a security sandbox, and chunk 8's review is advisory.
- **Phone pages share the admin port, and the reverse proxy is the boundary** (your call, 2026-11-12, replacing the separate listener). The admin page drives serial ports, reads files and flashes firmware, so the proxy must forward only `/tag/` (and the legacy `/t/`). Phone routes are handled before anything else and never touch the admin API. A shared token for the phone pages is still open.
- **App data:** each app has its **own SQLite file**, `inkapps/<id>/data/app.db` (your call, 2026-11-11). Copying the app folder copies its code, its per-tag config and its data, and no app can open another app's file. Inside it:
  - `ink_config`: per-tag settings
  - `ink_state`: per-tag JSON data, plus `hex_id = ""` for data shared by all the app's tags
  - `ink_meta`: which app owns the file
  - any tables the app creates itself through `AppStore.sql`

  The main store keeps only `app_bindings` (which app owns which tag's screen, plus the duplicate-push hash). `inkapps/*/data/` is git-ignored.

### Known constraint: how quickly a phone action reaches the screen

A tag polls every 120–300 s when idle (`SHELF_POLL_INTERVAL_S`, `SHELF_POLL_IDLE_S`). A tap makes it poll immediately and once more about 5 s later (`nfc_follow`). So:
- Work done **while the phone page loads** (the `on_open` hook below, e.g. "log a pill when the tag is tapped") is pushed at the follow-up poll and shows within seconds. That is how the spec describes the pill tracker anyway.
- A **button pressed later** on the page waits for the next poll, up to ~5 min. If that is too slow, the fix is in firmware: stay in the 30 s active poll rate for a minute or two after a tap. Decide during chunk 3 testing, not now.

### Chunk 4 notes (firmware, planned separately)

- **Hazard in today's firmware:** with `SHELF_NFC_URL ""` and `SHELF_NFC_NDEF_SYNC 1`, `nfc_ndef_sync()` (`Vusion/src/nfc_cfg.c:291`) rewrites the NDEF area to an empty message (`03 00 FE`) at every boot, which erases a URL written by phone. Until chunk 4, build with `SHELF_NFC_NDEF_SYNC 0` if you write URLs to tags.
- **New rule at boot:**
  - Read the TLV area at `0x010`.
  - If it holds one short URI record (`03 L D1 01 PL 55 <prefix code> <uri>`) and the URI contains `/tag/`, make the text after the **last** `/tag/` equal the tag's ID as 4 upper-case hex digits. Fix `L`/`PL` and the `FE` terminator, and write only the pages that differ.
  - Anything else is left untouched: no record, another record type, no `/tag/`.
- **The host is set by writing e.g. `https://shelf.example.org/tag/` (the reverse proxy's address) with any NFC writer app.** The tag appends its ID at the next boot.
- **Configuring the host from the server is deferred, as you asked.**
- **OTA window:** about 149 B free. This replaces the compile-time URL code, which cost about 100 B, so measure the size first.
- **Check an ID change:** confirm the tag reboots, or re-runs the sync, after `SM_OP_SET_ID`. Otherwise the URL keeps the old ID until the next reset.

---

## Chunk 1: SDK + host core

### File structure

| File | Responsibility |
|------|----------------|
| `ShelfKit-Server/shelfkit/store.py` (modify) | Schema 5: `app_bindings`, `app_state` tables and their methods; rename/forget carry them |
| `ShelfKit-Server/shelfkit/inkservices/__init__.py` (create) | Public SDK re-exports: `InkApp`, `TagContext`, `Canvas`, colours |
| `ShelfKit-Server/shelfkit/inkservices/sdk.py` (create) | `InkApp` (decorators, declared controls and config fields), `TagContext` |
| `ShelfKit-Server/shelfkit/inkservices/canvas.py` (create) | `Canvas`: the 152x296 drawing surface with text helpers that never overflow |
| `ShelfKit-Server/shelfkit/inkservices/loader.py` (create) | Find and import `inkapps/<id>/app.py`, collect per-app errors |
| `ShelfKit-Server/shelfkit/inkservices/host.py` (create) | `AppHost`: bindings, render, duplicate check, enqueue, callbacks, per-app log |
| `ShelfKit-Server/shelfkit/inkservices/__main__.py` (create) | `python -m shelfkit.inkservices render <app> [--tag ID] [--out PNG]` |
| `ShelfKit-Server/shelfkit/service_image.py` (modify) | Rename `_font` to `font` (public, used by `Canvas`). Keep `_font = font` for existing callers |
| `ShelfKit-Server/shelfkit/app.py` (modify) | `enqueue`: a `source` param replaces that tag's pending job from the same source; `App.inkhost` attribute |
| `ShelfKit-Server/shelfkit-server.py` (modify) | Create the `AppHost` at startup |
| `ShelfKit-Server/inkapps/hello/app.py` (create) | Example app: alias, a press counter, last-refresh time |
| `ShelfKit-Server/tests/inkservices_test.py` (create) | All chunk 1 checks |

### Task 1: Store, schema 5, and the per-app store. **DONE 2026-11-11**

**Ruling during implementation:** at your request, app data moved out of the main store into one SQLite file per app. Everything below this note up to Task 2 is the original text: it shows the superseded single-store design, and the code doesn't match it. What was built:
- `shelfkit/store.py`: `SCHEMA_VERSION = 5`, table `app_bindings(hex_id PK, app_id, last_hash, last_push_at)`
  - `bind_app(hex_id, app_id)`, `unbind_app(hex_id)`, `app_binding(hex_id) -> dict | None`, `app_bindings() -> list[dict]`, `set_app_pushed(hex_id, image_hash, at)`
  - `rename_tag` and `forget_tags` carry the binding
- `shelfkit/inkservices/appstore.py`:
  - `app_db_path(app_dir) -> Path`, which returns `app_dir/data/app.db`
  - `AppStore(path, app_id)`, which raises `AppStoreError` when the file belongs to another app
  - `.config(hex_id) / .set_config(hex_id, dict)`, `.state(hex_id) / .set_state(hex_id, dict)` (`""` = shared)
  - `.tags()`, `.rename_tag(old, new)`, `.forget_tag(hex_id)`, `.sql` (raw connection for the app's own tables), `.close()`
- `inkapps/.gitignore`: `*/data/`
- Tests: `test_store` and `test_appstore` in `tests/inkservices_test.py`

**Original design (superseded):**
- Files: `ShelfKit-Server/shelfkit/store.py` (`SCHEMA_VERSION`, `_SCHEMA`, `_migrate`, the tag rename/forget methods)
- Test: `ShelfKit-Server/tests/inkservices_test.py`
- Interfaces it produced:
  - `Store.bind_app(hex_id: str, app_id: str, config: dict) -> None` (replaces any existing binding of that tag and clears `last_hash`)
  - `Store.unbind_app(hex_id: str) -> None`
  - `Store.app_bindings() -> list[dict]`, each `{"hex_id", "app_id", "config": dict, "last_hash": str | None, "last_push_at": float | None}`
  - `Store.app_binding(hex_id: str) -> dict | None`
  - `Store.set_app_pushed(hex_id: str, image_hash: str, at: float) -> None`
  - `Store.app_state(app_id: str, hex_id: str) -> dict` (`{}` when none; `hex_id=""` is the app-wide document)
  - `Store.set_app_state(app_id: str, hex_id: str, data: dict) -> None`

Tables:
```sql
CREATE TABLE IF NOT EXISTS app_bindings (
    hex_id       TEXT PRIMARY KEY,      -- one app per tag
    app_id       TEXT NOT NULL,
    config       TEXT NOT NULL DEFAULT '{}',
    last_hash    TEXT,                  -- sha1 of the last queued planes: skip identical pushes
    last_push_at REAL
);
CREATE TABLE IF NOT EXISTS app_state (
    app_id     TEXT NOT NULL,
    hex_id     TEXT NOT NULL,           -- '' = shared by every tag running the app
    data       TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (app_id, hex_id)
);
```

- [ ] **Step 1: Write the failing tests** in a new `tests/inkservices_test.py` (copy the `check`/`FAILED` helpers and `sys.path` setup from `smoke.py`; temp DB via `tempfile`):

```python
s = store_mod.Store(tmp / "a.db")
s.bind_app("0101", "hello", {"title": "Hi"})
check("binding stored", s.app_binding("0101")["config"] == {"title": "Hi"})
s.set_app_pushed("0101", "abc", 1.0)
s.bind_app("0101", "hello", {"title": "Ho"})
check("rebind clears last_hash", s.app_binding("0101")["last_hash"] is None)
s.set_app_state("hello", "0101", {"n": 3}); s.set_app_state("hello", "", {"shared": 1})
check("per-tag state", s.app_state("hello", "0101") == {"n": 3})
check("app-wide state", s.app_state("hello", "") == {"shared": 1})
check("missing state is {}", s.app_state("nope", "0101") == {})
# rename / forget: the existing Store.rename_tag / Store.forget_tags
s.rename_tag("0101", "0102")
check("rename moves binding", s.app_binding("0102") is not None and s.app_binding("0101") is None)
check("rename moves state", s.app_state("hello", "0102") == {"n": 3})
s.forget_tags(["0102"])
check("forget drops binding", s.app_binding("0102") is None)
check("forget drops state", s.app_state("hello", "0102") == {})
check("forget keeps app-wide state", s.app_state("hello", "") == {"shared": 1})
# migration: a version-4 DB opens as 5 with the new tables
```

For the migration check, create a DB, set `PRAGMA user_version=4` and drop the two new tables. Reopen it and check `user_version == 5`, then call `bind_app`. `rename_tag` (`store.py:232`) may refuse when the new ID already exists, so call it on a free ID.

- [ ] **Step 2: Run the tests and check they fail.** Run `python ShelfKit-Server/tests/inkservices_test.py`. Expected: `AttributeError: 'Store' object has no attribute 'bind_app'`.
- [ ] **Step 3: Implement.**
  - Set `SCHEMA_VERSION = 5` and append both tables to `_SCHEMA`. The existing `else` branch in `_migrate` already re-runs `_SCHEMA` with `IF NOT EXISTS`.
  - Add the methods with the existing `with self._lock:` and commit pattern. JSON goes through `json.dumps`/`json.loads`, as `settings` does.
  - Extend `rename_tag` and `forget_tags` to update or delete rows in both tables. Forget deletes only rows where `hex_id` matches, never the `""` row.
- [ ] **Step 4: Run the tests and check they pass.** Same command, expected: exit 0. Also run `python ShelfKit-Server/tests/smoke.py` and expect it to still pass.
- [ ] **Step 5: Commit.** `git add ShelfKit-Server/shelfkit/store.py ShelfKit-Server/tests/inkservices_test.py`, message `inkservices: store schema 5 (app bindings and state)`.

### Task 2: SDK (`InkApp`, `TagContext`, `Canvas`). **DONE 2026-11-12**

**Rulings during implementation:**
- **Display presets (your call):** `shelfkit/displays.py` has `DisplayPreset(id, name, width, height, colors)`, `preset(id)` (unknown ids fall back to the default) and `presets()`.
  - The only preset is `vusion-2.6-bwr`, the GDEW026Z39 at 152x296 in black/white/red.
  - `Canvas(display)` takes its size and colours from the preset and refuses colours the panel lacks. `TagContext` carries `display`.
  - Until tags report their panel, the host gives every tag the default preset. The push pipeline (`png2epd`, `preview`, `eco`, `hubhost`) is still fixed at 152x296; that is separate work for when a second panel arrives.
- **Text clipping:** `Canvas` clips text by its 1-bit ink width (`getbbox(mode="1")`), not by `service_image._fits`. Hinted glyphs drawn without anti-aliasing are several pixels wider than the default measurement: Tahoma 14 measures 60 px but draws 67 px. `service_image` itself has the same small overshoot; it was left unchanged.
- **`TagContext` fields:** it also carries `logs` (filled by `tag.log()`). `InkApp` gained `config_defaults()` and `describe()`. The `id=` argument on `button`/`text_input` overrides the slug.

**Files:**
- Create: `shelfkit/inkservices/__init__.py`, `sdk.py`, `canvas.py`
- Modify: `shelfkit/service_image.py` (`font` public alias)
- Test: `tests/inkservices_test.py`

**Interfaces:**
- Produces (what an app author writes):

```python
from shelfkit.inkservices import InkApp, BLACK, RED, WHITE

app = InkApp("hello", title="Hello", description="Counts presses")
app.config_field("greeting", label="Greeting", default="Hello")   # per-tag setting, string

@app.render
def draw(tag, canvas): ...          # tag: TagContext, canvas: Canvas

@app.button("Press me")             # action id defaults to a slug of the label: "press-me"
def press(tag): tag.data["n"] = tag.data.get("n", 0) + 1

@app.text_input("Message", placeholder="Say something")   # action id "message"
def message(tag, text: str): ...

@app.on_open                        # the phone opened /tag/<ID> (= NFC tap)
def opened(tag): ...
```

- `InkApp(app_id: str, title: str = "", description: str = "")`
  - Attributes: `.id`, `.title`, `.description`, `.render_fn`, `.on_open_fn`, `.controls: list[Control]`, `.config_fields: list[ConfigField]`
  - `.action(action_id) -> Control | None`
  - Duplicate action ids raise `ValueError` at decoration time.
- `Control` (dataclass): `id: str`, `kind: Literal["button", "text"]`, `label: str`, `placeholder: str`, `fn: Callable`
- `ConfigField` (dataclass): `key: str`, `label: str`, `default: str`. Strings only in chunk 1; types come with the chunk 2 form.
- `TagContext` (dataclass):
  - `hex_id: str`, `alias: str | None`, `notes: str | None`
  - `config: dict`: the binding's config over the field defaults
  - `data: dict`: per-tag state, mutable, saved by the host after every callback
  - `shared: dict`: app-wide state, saved the same way
  - `db: sqlite3.Connection | None`: the app's own database (`AppStore.sql`) for its own tables, such as logs and usage history. It is `None` in the render CLI.
  - `battery: float | None` (volts), `now: datetime`
  - `log(msg: str) -> None`: goes to the host's per-app log
- `Canvas(width=152, height=296)`:
  - `.image` (PIL RGB) and `.draw` (ImageDraw with `fontmode = "1"`), for raw access
  - `text(xy, s, size=14, color=BLACK, bold=False, mono=False, max_width=None) -> int`: draws one line, cut with an ellipsis to `max_width` (default: to the right edge) and returns the y below it
  - `wrap(xy, s, size=12, color=BLACK, max_width=None, max_lines=3) -> int`
  - `rect(box, fill=None, outline=BLACK)`
  - `line(points, color=BLACK, width=1)`
  - Implement with `service_image.font`, `service_image._fits` and `service_image._wrap`, so text rendering matches the service label (anti-aliasing off, hinted fonts).

- [ ] **Step 1: Write the failing tests:**

```python
from shelfkit.inkservices import InkApp, Canvas, BLACK, RED
a = InkApp("t1", title="T")
@a.button("Press me")
def _p(tag): pass
check("button slug id", a.action("press-me").kind == "button")
try:
    @a.button("Press me")
    def _p2(tag): pass
    check("duplicate action rejected", False)
except ValueError:
    check("duplicate action rejected", True)
c = Canvas()
check("canvas size", c.image.size == (152, 296))
y = c.text((4, 4), "x" * 200, size=14)
check("long text stays inside", c.image.getbbox() is not None and c.image.crop((150, 0, 152, 40)).getcolors() == [(80, (255, 255, 255))])
check("text returns next y", y > 4)
c.rect((0, 100, 20, 120), fill=RED)
check("only panel colours", set(col for _, col in c.image.getcolors(1 << 16)) <= {(0,0,0), (255,0,0), (255,255,255)})
```

- [ ] **Step 2: Run the tests and check they fail** (`ModuleNotFoundError: shelfkit.inkservices`).
- [ ] **Step 3: Implement** the three files and the `service_image.font` rename.
- [ ] **Step 4: Run the tests and check they pass.**
- [ ] **Step 5: Commit.** Message: `inkservices: app SDK and canvas`.

### Task 3: Loader

**Files:**
- Create: `shelfkit/inkservices/loader.py`, `ShelfKit-Server/inkapps/hello/app.py`
- Test: `tests/inkservices_test.py`

**Interfaces:**
- Consumes: `InkApp` (Task 2)
- Produces:
  - `INKAPPS_DIR = Path(__file__).resolve().parents[2] / "inkapps"`
  - `LoadedApp` (dataclass): `id: str`, `path: Path`, `app: InkApp | None`, `error: str | None`
  - `load_apps(root: Path = INKAPPS_DIR) -> dict[str, LoadedApp]`

**Rules:**
- Each subfolder with an `app.py` is one app, and its id is the folder name.
- Import with `importlib.util.spec_from_file_location(f"inkapps_{id}", path)`. A fresh module object on every call is what makes a reload work.
- The module must define a module-level `app` that is an `InkApp` whose `.id` equals the folder name. Otherwise record the error and set `app=None`.
- Any exception during import becomes `error = "<ExcType>: <msg>"` with the last traceback frame inside `app.py`.
- Folders starting with `_` or `.` are skipped.

**`hello` app:**
- A black title bar with the white alias, or the ID if there's no alias
- A big red counter `data["n"]`
- The greeting from config
- The current time at the bottom
- A "Press me" button that increments `n`
- A "Message" text input that stores `data["msg"]`, shown wrapped on the screen

- [ ] **Step 1: Write the failing tests.** They use a temp root containing three folders:
  - `good/app.py`: a minimal `app = InkApp("good")`
  - `broken/app.py`: contains `def (`
  - `noapp/app.py`: contains `x = 1`

```python
apps = loader.load_apps(tmp_root)
check("good app loads", apps["good"].app is not None and apps["good"].error is None)
check("syntax error reported", apps["broken"].app is None and "SyntaxError" in apps["broken"].error)
check("missing app object reported", apps["noapp"].app is None and "app" in apps["noapp"].error)
check("bundled hello loads", loader.load_apps()["hello"].error is None)
```

- [ ] **Step 2: Run the tests and check they fail.**
- [ ] **Step 3: Implement** `loader.py` and `inkapps/hello/app.py`.
- [ ] **Step 4: Run the tests and check they pass.**
- [ ] **Step 5: Commit.** Message: `inkservices: app loader and hello example`.

### Task 4: AppHost

**Files:**
- Create: `shelfkit/inkservices/host.py`
- Test: `tests/inkservices_test.py`

**Interfaces:**
- Consumes:
  - `Store` binding methods and `AppStore` (Task 1, as built). The host opens one `AppStore(app_db_path(loaded.path), app_id)` per loaded app.
    - Config comes from `AppStore.config(hex_id)` over the field defaults. `bind(hex_id, app_id, config)` writes `set_config`.
    - `TagContext.data` and `.shared` come from `AppStore.state(hex_id)` and `.state("")`.
    - `TagContext` also gets `db: sqlite3.Connection` (`AppStore.sql`), for the app's own tables.
    - `AppHost.rename_tag(old, new)` and `AppHost.forget_tags(hex_ids)` call every app store's `rename_tag`/`forget_tag`. `App._rename_tag` and `App.forget_tags` call them after the main store (Task 5).
    - Read the test lines below that mention `s.app_state("ctr", "0101")` as `host.store_of("ctr").state("0101")`.
  - `load_apps`/`LoadedApp` (Task 3), `TagContext`/`Canvas` (Task 2)
  - `preview.render(path, fit, dither)` (existing; returns an object with `.bw`, `.red`)
- Produces:

```python
class AppHost:
    def __init__(self, store, enqueue: Callable[..., dict], tag_info: Callable[[str], dict],
                 root: Path = INKAPPS_DIR, image_dir: Path = <server>/data/apps): ...
    def reload(self) -> dict[str, LoadedApp]
    def apps(self) -> list[dict]          # {"id","title","description","error","controls":[{id,kind,label,placeholder}],"config_fields":[...],"tags":[hex...]}
    def bind(self, hex_id: str, app_id: str, config: dict | None = None) -> dict   # {"ok", "error"?}; then refresh(force=True)
    def unbind(self, hex_id: str) -> dict
    def render_png(self, hex_id: str) -> bytes                                    # raises AppError
    def refresh(self, hex_id: str, force: bool = False) -> dict                   # {"ok", "pushed": bool, "skipped": "identical"|None, "error"?}
    def run_action(self, hex_id: str, action_id: str, value: str | None = None) -> dict  # callback, save state, refresh
    def opened(self, hex_id: str) -> dict                                         # on_open hook, save state, refresh
    def log(self, app_id: str) -> list[list]                                      # [[t, line], ...], last 200
class AppError(Exception): ...
```

- `tag_info(hex_id)` returns `{"alias", "notes", "battery"}`; chunk 1 wires it to `App.tag_meta` and `App._vdd_of`.
- `enqueue(kind, addr: int, label: str, **params)` has the same signature as `App.enqueue`.

**Refresh:**
1. Build `TagContext` from the binding, `tag_info` and the store state.
2. Call `render_fn(tag, canvas)`.
3. Save the PNG to `image_dir / f"{hex_id}.png"`.
4. Call `preview.render(path, "stretch", "threshold")` and take `sha1(bw + red)`.
5. If the hash equals `last_hash` and `force` is false, return `skipped="identical"`.
6. Otherwise call `enqueue("image", int(hex_id, 16), f"app {app_id}", path=str(path), fit="stretch", dither="threshold", source="app")`. If it returns `ok`, call `set_app_pushed`.

**State and locking:**
- After a callback, persist `tag.data` and `tag.shared` with `set_app_state`, even if the callback raised. Partial changes are the app's business; losing them is worse.
- Callbacks run under one `threading.Lock` per app, because the phone page and the admin UI can call at the same time.

**Errors:**
- Every exception from app code is caught and appended to the app log with its traceback tail. `refresh`/`run_action` return `{"ok": False, "error": "<ExcType>: <msg>"}`. Nothing is pushed.

- [ ] **Step 1: Write the failing tests:**
  - Use a fake `enqueue` that appends its call to a list and returns `{"ok": True}`.
  - Use `tag_info = lambda h: {"alias": "A1", "notes": None, "battery": 3.0}`.
  - Use a temp `inkapps` root with these apps:
    - `ctr`: the render draws `data["n"]`, and the button "Add" increments it
    - `bad`: the render raises `RuntimeError("boom")`
    - `same`: draws a fixed rectangle

```python
h = AppHost(s, enqueue=fake, tag_info=info, root=tmp_root, image_dir=tmp / "img")
check("bind pushes once", h.bind("0101", "ctr")["ok"] and len(calls) == 1)
check("push uses app source", calls[-1][1]["source"] == "app" and calls[-1][1]["dither"] == "threshold")
check("identical render is not pushed", h.refresh("0101")["skipped"] == "identical" and len(calls) == 1)
check("forced refresh pushes", h.refresh("0101", force=True)["pushed"] and len(calls) == 2)
r = h.run_action("0101", "add")
check("action changes screen and pushes", r["ok"] and r["pushed"] and len(calls) == 3)
check("action state persisted", s.app_state("ctr", "0101") == {"n": 1})
check("unknown action", h.run_action("0101", "nope")["ok"] is False)
h.bind("0102", "bad")
check("render error is contained", h.refresh("0102", force=True)["ok"] is False and len(calls) == 3)
check("error in app log", any("boom" in line for _, line in h.log("bad")))
check("other tag still works", h.run_action("0101", "add")["ok"])
check("unbound tag", h.refresh("0999")["ok"] is False)
check("bind unknown app", h.bind("0103", "missing")["ok"] is False)
```

- [ ] **Step 2: Run the tests and check they fail.**
- [ ] **Step 3: Implement** `host.py`.
- [ ] **Step 4: Run the tests and check they pass.**
- [ ] **Step 5: Commit.** Message: `inkservices: app host (render, dedupe, callbacks)`.

### Task 5: Queue supersede, server wiring, render CLI

**Files:**
- Modify: `shelfkit/app.py` (`enqueue`, about line 1792; `__init__` for `self.inkhost = None`)
- Modify: `shelfkit-server.py` (after `App(...)`: `app.inkhost = AppHost(store, app.enqueue, <tag_info>)`, only when `store` is not None)
- Create: `shelfkit/inkservices/__main__.py`
- Test: `tests/inkservices_test.py`

**Interfaces:**
- Consumes: `AppHost` (Task 4)
- Produces:
  - `App.enqueue(..., source=...)`: when `params.get("source")` is set, every job in `self.queue` with the same `addr`, `state == "pending"` and the same `params["source"]` is removed before the new one is appended. A running job is never touched.
  - `App.inkhost: AppHost | None`
  - CLI: `python -m shelfkit.inkservices render <app_id> [--tag 0101] [--out file.png]`. It renders with a `TagContext` built from `--tag` (default `"0000"`), empty data and default config, and writes the PNG (default `<app_id>.png`). No store and no queue are involved.

- [ ] **Step 1: Write the failing tests.** Build a real `App` with no ports the way `smoke.py`'s `boot()` does, and give it a temp PNG:

```python
a = boot(...)
a.enqueue("image", 0x0101, "app x", path=png, source="app")
a.enqueue("image", 0x0101, "app x", path=png, source="app")
a.enqueue("image", 0x0101, "manual", path=png)
pend = [j for j in a.queue_jobs() if j["state"] == "pending" and j["addr"] == 0x0101]  # match queue_jobs()'s real keys
check("app pushes supersede", len(pend) == 2)
check("manual push untouched", any(j["label"] == "manual" for j in pend))
rc = subprocess.run([sys.executable, "-m", "shelfkit.inkservices", "render", "hello", "--out", str(tmp / "h.png")], cwd=SERVER).returncode
check("render CLI", rc == 0 and Image.open(tmp / "h.png").size == (152, 296))
```

- [ ] **Step 2: Run the tests and check they fail.**
- [ ] **Step 3: Implement** the supersede in `enqueue` (inside the existing `with self.lock:`), the wiring and `__main__.py`.
- [ ] **Step 4: Run both suites.** Run `python ShelfKit-Server/tests/inkservices_test.py` and `python ShelfKit-Server/tests/smoke.py`, and expect both to pass.
- [ ] **Step 5: Manual check with hardware.**
  - Start the server.
  - In a Python shell against the running process, or through the chunk 2 UI when it exists, call `app.inkhost.bind("<a real tag>", "hello")`.
  - Expected: one "app hello" job in the queue, and the hello screen on the tag at its next poll.
- [ ] **Step 6: Commit.** Message: `inkservices: queue supersede, server wiring, render CLI`. Add a README row under a new "InkServices" heading in `ShelfKit-Server/README.md`.

---

## Self-review notes

**Spec coverage:**

| Spec point | Chunk |
|---|---|
| Python apps with a ready library | 1 |
| Choose which tags run an app | 1 (API), 2 (UI) |
| NFC opens the web interface at `/tag/<TAG_ID>` with buttons/text | 3, 4 |
| Apps tab: running apps, their data, their tags | 2 |
| Dev mode and Dev tab with virtual tag; design / description & versions / backend / debug & stats | 6 |
| Clone from GitHub | 7 |
| AI safety check | 8 |
| AI layout chat, optional backend agent, manual coding kept | 9 (manual coding is the default from chunk 1) |
| Example apps | 5: pill, weather/moon |
| Calendar, todo and message board | Need only the chunk 1–5 SDK, so they're app work, not platform work |

**Open for later chunks:** config field types beyond strings (chunk 2); a token for the phone pages (chunk 3); the post-tap active-poll window (chunk 3 test → firmware).
