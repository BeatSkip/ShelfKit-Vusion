# The app SDK and how the host runs an app

Source: `ShelfKit-Server/shelfkit/inkservices/sdk.py`, `host.py`, `loader.py`, `screen.py`, `canvas.py`, `appstore.py`.

## An app on disk

```
ShelfKit-Server/inkapps/
  hello/
    app.py          # must define  app = InkApp("hello", ...)  at module level
    layout.xml      # optional: InkLayout screen (else @app.render draws in Python)
    data/app.db     # created on first write; git-ignored
```

- The folder name is the app id: lower-case letters, digits, `-` and `_`. `InkApp("<id>")` must match it.
- Folders starting with `_` or `.` are ignored, which leaves room for templates and scratch work.
- **Loading:** each app is imported on server start and on **Reload apps** (`POST /api/inkapps/reload`), as a new module object every time.
- **Load errors:** a syntax error, an exception at import or a missing `app` is recorded against that app, as `"<Type>: <msg> (app.py line N)"`. The other apps and the server keep running.
- **No metadata file:** there is no manifest, version, author, icon or dependency list. The only metadata is the `InkApp(...)` arguments: `title`, `description`, `layout`.

## The SDK (what an author writes)

```python
from shelfkit.inkservices import InkApp

app = InkApp("hello", title="Hello", description="A counter and a message", layout="layout.xml")
app.config_field("greeting", label="Greeting", default="Hello!")   # per-tag setting, string only

@app.data                       # what layout.xml sees as `data`; read-only, runs on every redraw
def data(tag):
    return {"greeting": tag.config.get("greeting", ""), "n": tag.data.get("n", 0)}

@app.render                     # alternative to a layout: draw in Python; wins over layout=
def draw(tag, canvas): ...

@app.button("Press me")         # phone page button  -> fn(tag)
def press(tag): tag.data["n"] = tag.data.get("n", 0) + 1

@app.text_input("Message", placeholder="Leave a message")   # -> fn(tag, text)
def message(tag, text): tag.data["msg"] = text.strip()

@app.on_tap                     # the tag reported an NFC tap over the radio (via the hub)
def tapped(tag): ...            # any phone/reader; no page or web address needed

@app.on_open                    # a phone opened the tag's page (/tag/<ID>)
def opened(tag): ...

@app.every(minutes=30)          # >= 1 min; runs once when bound, then every N min
def update(tag): tag.data["wx"] = tag.fetch_json("https://api.open-meteo.com/v1/forecast", {...})
```

**`TagContext` (the `tag` argument):**
- `hex_id`, `alias`, `notes`, `battery` (volts or None), `display` (a preset: width, height, colours)
- `config`: this tag's settings, with defaults filled in
- `data`: this tag's working JSON; change it in place and the host saves it
- `shared`: one JSON document shared by every tag running the app
- `db`: a raw `sqlite3` connection to the app's own database, for its own tables; the app commits itself
- `now`: the host's clock, which tests can set
- `log(msg)`: a line in the app's log
- `fetch_json(url, params)`: http(s) only, 2 MB cap, generic User-Agent. Use it only from a timer or an action, never from `data` or `render`.

**`Canvas`** (for `@app.render`): `text(xy, s, size, color, bold, max_width)`, `wrap(...)`, `rect(box, fill, outline)`, `line(points)`, `paste(image, xy)`, plus `canvas.image`/`canvas.draw` (PIL). Text is 1-bit and clipped to the canvas.

**Controls a phone can use:** only `button` and `text_input`. There is no checklist, select, number, date or confirmation control yet.

**Config fields:** strings only, with a label and a default. There are no types, validation, choices or help text. The pill app asks for "HH:MM" and "YYYY-MM-DD" in plain text fields.

## Lifecycle (AppHost)

| Event | What happens |
|---|---|
| **Bind** (Run on this tag) | Saves the config, runs every timer once (fresh data), renders, and pushes with `force`. Any app the tag ran before is replaced. |
| **Render** | `@app.render`, or `layout.xml` filled with `@app.data` (default `tag.data`). A layout with **errors** is not pushed. Its warnings go to the app log. |
| **Refresh** (after an action, timer or config change) | Renders, saves `data/apps/<HEX>.png`, thresholds it, and compares the SHA1 of the panel planes with `app_bindings.last_hash`. If it's identical, nothing is pushed (`skipped: "identical"`). Otherwise it queues `kind="image", source="app"` on the server queue, which replaces any pending image for that tag. |
| **Action** (a phone button or text, or the admin "try" buttons) | Runs the callback under the app's lock, saves `data`/`shared`, then refreshes. |
| **NFC tap (radio)** | The tag polls at once with its `fw=` report. The server (`App._is_tap`) counts an `fw=` poll from a tag up 30 s or more as a tap (the other one is the boot report), once per 20 s, logs a `tap` event and runs `on_tap` of the app bound to that tag only, on its own thread. Needs the server and hub, not the web page. |
| **NFC tap (phone page)** | `GET /tag/<ID>` runs `on_open`, which is debounced for 10 s. It then redirects to `/tag/<ID>/view`. A phone tap usually runs both. |
| **Timers** | A scheduler thread checks every 15 s. After a server restart the first pass only learns the timers, so a restart doesn't trigger a burst of fetches. A failing timer waits its full interval. Runs are logged only when they push or fail. |
| **Unbind** (Stop) | The binding is removed. The tag keeps its last picture, and the app's data for it stays in the app's database. |
| **Tag renamed or forgotten** | The binding and every app's data for that tag follow the new id or are deleted. |
| **Exception in app code** | Caught. The result is an error, the traceback line goes to the app log, nothing is pushed, and the phone page shows the error. |

**The app log** is in memory, 200 lines per app, and is **lost when the server restarts**.

## Where the state lives

- **Main state DB** (`ShelfKit-Server/data/shelfkit.db`), table `app_bindings(hex_id PK, app_id, last_hash, last_push_at)`: one app per tag.
- **The app's DB** (`inkapps/<id>/data/app.db`):
  - `ink_config(hex_id, data JSON)`: per-tag settings.
  - `ink_state(hex_id, data JSON)`: per-tag data, plus the row `''` for the shared document.
  - `ink_meta`: the owning app id.
  - Any tables the app creates itself.
- Looking at an app (a preview) never creates its database.

## Developer tools outside the UI

```
cd ShelfKit-Server
python -m shelfkit.inkservices list
python -m shelfkit.inkservices render hello --tag 0101 --alias Kitchen --data '{"n":7}' --config '{}' --out hello.png --boxes
python -m shelfkit.inklayout render inkapps/hello/layout.xml --data d.json --out screen.png
python -m shelfkit.inklayout skill [--display ID] [--orientation landscape] [--out SKILL.md]
python tests/inkservices_test.py ; python tests/inklayout_test.py
```

## The reference apps (good fixtures for UI ideas)

- **hello:** a layout app with a counter button, a message text field, a greeting setting and a date footer.
- **pill:** a contraceptive-pill tracker.
  - A tap logs today's pill. The phone page has *Taken* and *Undo last*.
  - The screen is a month grid: taken days solid black, missed days red, today ringed, pill-free days dotted.
  - The bottom bar shows the reminder state.
  - Settings: reminder time, pack start date, pill-free days.
- **weather:** Open-Meteo with no API key, fetched every 30 min.
  - One fetch per place is shared by every tag at that place.
  - The moon phase is computed locally.
  - When the forecast is stale, the screen says so.
  - Settings: place, latitude, longitude. Nothing is fetched until they are set.
