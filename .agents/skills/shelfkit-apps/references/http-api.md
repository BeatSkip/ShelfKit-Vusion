# HTTP API behind the apps UI

All on the server's one port. The admin routes are meant for `127.0.0.1` only. A reverse proxy should forward only `/tag/` (and the legacy `/t/`) to phones. Code: `shelfkit/inkservices/web.py` (admin) and `shelfkit/inkservices/phone.py` (phone pages).

## Admin (JSON unless noted)

| Route | Body / query | Returns / does |
|---|---|---|
| `GET /api/inkapps` | | `{apps, bindings, tags, phone_base, phone_base_local}` (see below) |
| `GET /api/inkapps/preview.png?app=&tag=` | | A PNG of what the app draws for that tag, with nothing pushed. Without `app`: the bound app's current screen. 422 with the error text if the app fails. |
| `GET /api/inkapps/data?app=` | | `{ok, path, size, shared, tags:[{hex_id, bound, config, state}], tables:[{name, rows}]}`. Only the app's own tables' row counts are returned, not their rows. |
| `GET /api/inkapps/log?app=` | | `{log: [[unix_time, line], ...]}`, up to 200 lines, in memory only |
| `GET /api/inkapps/layout?app=` | | The app's `layout.xml` as text (404 if it has none) |
| `POST /api/inkapps/reload` | `{}` | Re-imports every app. Returns `{ok, apps}`. |
| `POST /api/inkapps/grid` | `{grid}` | Saves the Apps grid: `["app_id", {id, name, apps: [...]}, ...]` (order and groups). Returned as `grid` by `GET /api/inkapps`. |
| `POST /api/inkapps/disable` | `{app}` | Stops the app on every tag and stops importing it; files and data stay. Returns `{ok, stopped}`. |
| `POST /api/inkapps/enable` | `{app}` | Imports it again. Returns `{ok, error}` (error: it did not load). |
| `POST /api/inkapps/create` | `{id, title, description, icon, draw, timer_minutes, on_open, fields, buttons, dry_run?}` | The New app wizard (`inkservices/scaffold.py`): writes `inkapps/<id>/app.py` (+ `layout.xml`) and loads it. With `dry_run`: only returns `{files}`. |
| `POST /api/inkapps/bind` | `{tag, app, config?}` | Puts the app on the tag: runs its timers, renders, pushes. Returns `{ok, pushed, skipped}` or `{ok:false, error}`. |
| `POST /api/inkapps/unbind` | `{tag}` | Stops the app on that tag (its data is kept) |
| `POST /api/inkapps/config` | `{tag, config}` | Saves the tag's settings, then refreshes |
| `POST /api/inkapps/action` | `{tag, action, value?}` | Runs a button or text control as the phone would |
| `POST /api/inkapps/open` | `{tag}` | Simulates an NFC tap (`on_open`) |
| `POST /api/inkapps/refresh` | `{tag, force?}` | Runs the timers, redraws and sends if changed. With `force`: redraws and sends, without timers. |
| `POST /api/layout/render` | `{layout, data?, tag?, display?}` | `{ok, png (base64), diagnostics, boxes, layout, display, size}`. Needs no app or AI. |
| `GET /api/layout/icons` | | `{size: 12, icons: {name: [12 rows of '#'/'.']}}`, the pixel icons, also used as app icons |
| `GET /api/layout/displays` | | `{displays:[{id,name,width,height,colors}], default}` |
| `GET /api/layout/skill?display=&orientation=` | | The InkLayout skill file (Markdown) |

What one entry of `GET /api/inkapps` `apps[]` looks like (from `InkApp.describe()` plus host fields):

```json
{"id": "hello", "title": "Hello", "description": "…",
 "controls": [{"id": "press-me", "kind": "button", "label": "Press me", "placeholder": ""},
              {"id": "message", "kind": "text", "label": "Message", "placeholder": "…"}],
 "config_fields": [{"key": "greeting", "label": "Greeting", "default": "Hello!"}],
 "icon": "message", "disabled": false, "installed_at": 1794409966.5,
 "has_render": true, "layout": "layout.xml", "has_on_open": false,
 "timers": [{"id": "update", "minutes": 30}],
 "error": null, "tags": ["F466"]}
```

The other fields:
- `bindings[]`: `{hex_id, app_id, last_hash, last_push_at}`.
- `tags[]`: every tag the server knows, as `{id, alias}`.
- `phone_base`: the address the NFC links use (Settings → "Address phones use", or the server's own address).
- `phone_base_local`: true when only this computer can open that address.

Results of actions use `{ok, pushed, skipped: null | "identical" | "no on_open", error?}`.

Related server APIs a UI may want:
- `GET /api/poll`: the whole fleet state, including each tag's status, battery, last push and the queue. The main page draws from it.
- `POST /api/prefs`: settings, including `public_url`.
- `POST /api/tags/<hex>/nfc`: queues writing `<public_url>/tag/<ID>` to the tag's NFC chip at its next check-in (read back afterwards). Answers `{result, state}`. The tag's state carries `nfc_url` (as read back) and `nfc_pending`.
- The queue screen's APIs: the queue shows app pushes as `kind=image, source=app`.

## Phone pages (no JavaScript, strict CSP, relative links)

| Route | |
|---|---|
| `GET /tag/<ID>` | The NFC link. Runs `on_open` (debounced 10 s), then sends a 303 redirect to `view` |
| `GET /tag/<ID>/view` | The app title, alias and tag id, the current screen (`screen.png`), one form per control, the description |
| `GET /tag/<ID>/screen.png` | The tag's current screen |
| `POST /tag/<ID>/do` | `action=&value=` (form). Runs the control, then sends a 303 redirect back to `view` with a message |
| `GET /t/<ID>...` | A 301 redirect to `/tag/<ID>...` |

The pages enforce a same-site check (Host / X-Forwarded-Host) and cap form bodies at 16 KB. An unbound tag shows "No app runs on this tag yet".

## Not there yet (no route exists)

None of these exist yet:
- editing or saving code or a layout from the UI
- installing from git, updating or deleting an app
- versions
- statistics (renders, pushes, skipped duplicates, errors)
- a persisted log
- AI layout chat (`/api/layout/chat` is planned)
- AI safety review
- browsing an app's own tables
