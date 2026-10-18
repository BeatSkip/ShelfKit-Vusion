```markdown
# E-Paper Fleet Web UI — Implementation Spec

## Purpose
Web interface to manage a fleet of e-paper shelf tags via a serial-connected hub.
Solves two problems: **fleet health at a glance**, and **push content to tags with
exact on-glass preview**. Everything else is a drilldown from a tag row.

## Non-goals
- No drag-and-drop layers editor.
- No websockets / real-time preview. Poll only.
- No multi-user accounts, roles, or auth beyond a single shared password.
- No per-tag latency or throughput charts.
- No mobile app (responsive web only).

---

## Stack (opinionated, pick one)

**Option A (recommended):** Python + FastAPI + Jinja2 + htmx + Pillow + SQLite.
- Pillow handles resize, dither (`convert('1', dither=Image.Dither.FLOYDSTEINBERG)`),
  threshold, and 1-bit PNG output directly.
- htmx avoids a JS build step.

**Option B:** Node + Express + EJS + sharp + SQLite.
- sharp for resize + `.threshold()`; FS dithering via a small helper loop
  (sharp has no built-in FS).

Either is fine. **Do not use a React SPA** — the whole app is ~10 screens and one
interactive widget (the preview stack); a build step adds overhead for no benefit.

Polling: 10–30 s. The EPD refresh rate is the real rate limit.

---

## Data model (SQLite)

```sql
CREATE TABLE tags (
  id            INTEGER PRIMARY KEY,        -- internal rowid
  hex_id        TEXT NOT NULL UNIQUE,       -- 'A3F2', 4 uppercase hex, no prefix
  alias         TEXT,                       -- optional, 4-6 chars, e.g. 'S03-P4'
  notes         TEXT,
  last_seen     INTEGER,                    -- epoch seconds
  last_status   TEXT,                       -- online|offline|alert|unreachable
  battery_pct   INTEGER,                    -- 0..100, nullable
  current_bitmap_id INTEGER,                -- FK to content_bitmaps.id
  created_at    INTEGER NOT NULL
);

CREATE TABLE content_bitmaps (
  id            INTEGER PRIMARY KEY,
  sha256        TEXT NOT NULL UNIQUE,       -- dedupe identical pushes
  source_kind   TEXT NOT NULL,              -- 'image' | 'template'
  source_ref    TEXT,                       -- original filename or template id
  bitmaps       BLOB NOT NULL,              -- raw 1-bit, 152*296/8 = 5624 bytes
  png_cache     BLOB,                       -- cached PNG render for previews
  template_id   TEXT,                       -- nullable
  created_at    INTEGER NOT NULL
);

CREATE TABLE jobs (
  id            INTEGER PRIMARY KEY,        -- 'J-1042'
  tag_hex_id    TEXT NOT NULL,              -- FK tags.hex_id
  bitmap_id     INTEGER NOT NULL,           -- FK content_bitmaps.id
  state         TEXT NOT NULL,              -- pending|sending|acked|rendered|retrying|failed
  attempts      INTEGER NOT NULL DEFAULT 0,
  error         TEXT,
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL
);

CREATE TABLE events (
  id            INTEGER PRIMARY KEY,
  tag_hex_id    TEXT NOT NULL,
  event         TEXT NOT NULL,              -- sync|online|offline|low batt|stale|ota|err|wake|sleep
  count         INTEGER NOT NULL DEFAULT 1, -- consecutive-dup counter (render-time only)
  ts            INTEGER NOT NULL
);

-- rollups for stats
CREATE TABLE fleet_stats_5m (
  bucket_ts     INTEGER PRIMARY KEY,        -- ts floored to 5 min
  online        INTEGER,
  total         INTEGER,
  alerts        INTEGER
);

CREATE INDEX idx_events_ts ON events(ts DESC);
CREATE INDEX idx_jobs_state ON jobs(state);
```

**ID rendering rule (matches EPD spec):** hex ID is always exactly 4 uppercase
chars, no `0x` prefix, monospace. Alias is optional; when present, it's displayed
alongside or in place of hex depending on user preference. **Never mix** hex and
alias in the same column — that's a per-screen toggle, not per-row.

---

## Image pipeline

Input: any raster (PNG/JPEG/WebP) OR a template field set.
Output: a raw 1-bit buffer, 152 wide × 296 tall (portrait), plus a cached PNG
for previews.

Steps:
1. Load / decode.
2. Convert to grayscale.
3. Resize to 152×296 using the chosen fit mode (`cover` default; `contain` and
   `stretch` selectable).
4. Dither with chosen algorithm:
   - `threshold` — `pixel > 128 ? 255 : 0`. Best for line art / text.
   - `floyd-steinberg` — default. Pillow's built-in.
   - `bayer4` — ordered 4×4 Bayer matrix, applied manually. Best for banners.
5. Convert to 1-bit (`L` → `1`).
6. Encode raw buffer (5624 bytes, 152×296/8, row-major, MSB-left) for transport.
7. Also cache a PNG (`mode='1'`) for web previews and the EPD mirror.

**Never** let the browser do the dithering. Server-rendered PNGs only. The
`image-rendering: pixelated` CSS on the preview ensures 1:1 fidelity.

**Dedupe** by SHA256 of the *source* — if the same image is pushed to 10 tags,
store one bitmap row and point 10 job rows at it.

---

## API

All JSON unless noted. Auth: single shared password in a cookie set by
`POST /login`.

```
GET    /api/tags?search=&status=&sort=&limit=&offset=
       -> [{ hex_id, alias, status, battery_pct, last_seen,
             current_bitmap_png_url, open_job_state }]

GET    /api/tags/:hex_id
       -> { tag fields..., history: [bitmap_id, age], log: [...] }
PATCH  /api/tags/:hex_id
       body: { alias?, notes? }                -> updated tag

POST   /api/tags/content
       body: multipart (file) OR JSON ({ template_id, fields })
       query: ?tag=A3F2&tag=C9D0  (repeatable) OR ?all=1
       -> { job_ids: [...], preview_png: <base64 or URL>, bitmap_sha256 }
       NOTE: does NOT queue. Renders + stores bitmap, returns preview only.
             Idempotent if bitmap already exists (returns existing sha).

POST   /api/jobs
       body: { tag_hex_ids: [...], bitmap_sha256 }
       -> { job_ids: [...] }               -- actual queue operation

GET    /api/jobs?state=open&tag=...
POST   /api/jobs/:id/retry
POST   /api/jobs/:id/cancel

GET    /api/events?since=&tag=&event=&limit=&offset=
       -> [{ id, hex_id, alias, event, count, ts }]

GET    /api/bitmap/:sha.png             -> cached 1-bit PNG (296×152, rotated)
POST   /api/bitmap/:sha/dither-check    -> renders same source in all 3 dithers

GET    /api/stats/fleet?window=24h|7d
       -> [{ bucket_ts, online, total, alerts }]
GET    /api/stats/battery-distribution

POST   /api/hub/ota                     multipart (.bin)
GET    /api/hub/screen.png              -> mirror of hub EPD (same rotation)
GET    /api/hub/info                    -> { version, uptime, serial_state }
POST   /api/hub/restart
GET    /api/hub/console?since=          -> serial log lines (poll)
```

**Rendering contract:** the preview bitmap is authored *portrait* (152×296),
same as the EPD spec. The API rotates to native landscape (296×152) before
sending to the hub. Web previews show portrait.

---

## Screens

### 1. Fleet (home)

Default view = **table**. Alternate view = **map** (same page, toggled).

Table columns (in order):
- checkbox
- `hex_id` — monospace, 4 chars, links to detail
- `alias` — inline-editable, validated 4–6 chars
- `status` — text + coloured dot (`online`=green, `offline`=grey, `alert`=red,
  `pending`=amber, `unreachable`=dark red)
- `battery` — percentage + 3-px-tall sparkline of last 7d
- `last content` — 2× thumbnail of current bitmap + age ("2m", "1h", "3d")

Bulk actions (visible only when ≥1 row selected): `Push`, `Reflash`, `Clear`.

Search matches `hex_id` and `alias`. Status filter chips. Column sort on
`hex_id`, `last_seen`, `battery_pct`.

Map view: renders tags in their physical grid (config-driven rows × cols).
Cell states: filled black = online, outlined = offline, 50% dither = alert,
amber outline = pending. Clicking a cell opens tag detail. Grid legend below.

Row shows `pending` status when any job for that tag is in
`pending|sending|retrying`.

### 2. Editor

Left column = controls. Right column = preview stack.

Controls:
- Source radio: `Upload image` / `Template` / `Plain text` / `QR`
- Upload zone (drag & drop, `.png .jpg .webp`)
- Fit mode: `Cover` (default) / `Contain` / `Stretch`
- Dither: `Floyd-Steinberg` (default) / `Threshold` / `Bayer 4×4`
- Target tags: multi-select (defaults to the tag(s) this was opened from)
- Preview tag selector (dropdown of targets, so the user can compare)

Preview stack (always three panes side by side, or vertically stacked on mobile):
1. **Original** — resized preview, colour.
2. **On device** — 1:1 portrait render at 152×296, `image-rendering: pixelated`.
3. **Zoom 4×** — drag-select a region on the "On device" pane; renders that
   region at 4×.

Warning banner (non-blocking) when the source has >40 % midtone pixels —
the user should know FS will look muddy.

Buttons: `Cancel`, `Push to N tag(s)`.

**Push flow:**
1. `POST /api/tags/content` → returns preview.
2. User confirms → `POST /api/jobs` with the bitmap sha + tag list.
3. Toast: "Queued 2 jobs. Track in Queue." with a link.

**Templates (ship 6 built-in, hardcoded):**
- `price-large` — big price, small SKU beneath.
- `price-left` — product name right, price left.
- `photo-left` — image box left, text right.
- `banner` — full-width text + optional image strip.
- `qr-label` — QR left, label right.
- `blank` — no fields.

Template fields: `title`, `subtitle`, `price`, `image` (optional), `qr_payload`
(optional). Server-side renders the template to the 152×296 1-bit buffer using
the same pipeline. **Do not** ship a generic WYSIWYG editor — templates only.

**Content library** — collapsible panel below the preview stack, showing last
20 bitmaps as thumbnails. Clicking one loads it into the preview stack for a
"push again" flow.

### 3. Queue

Table columns: `job_id`, `hex_id`, `content thumbnail`, `state`, `attempts`,
`age`. State chips coloured per the Fleet legend.

Bulk actions: `Retry failed`, `Cancel pending`.

Per-tag job replacement rule: **if a job is already open for a tag, a new push
for that tag replaces it** (cancel the old job, insert the new one). Prevents
a dead tag from accumulating stale pushes. Confirm in the editor when this
would happen.

### 4. Logs

Fleet event log — infinite scroll table, columns matching the EPD log spec:
`time` (HH:MM:SS), `hex_id`, `alias`, `event`, `×N` (only when N > 1).
Filters: tag, event, time range. Same dedupe rule as EPD: consecutive
`(hex_id, event)` collapse into one row with `×N`.

Per-tag log = same table filtered to one tag.

### 5. Stats

One page, three charts (use a lightweight chart lib — Chart.js or uPlot):
- Online count over the selected window (24h / 7d).
- Alerts opened vs closed, 7d.
- Battery distribution histogram + list of tags `<20%`.

Do not add per-tag latency, throughput, or traffic counters. Ever.

### 6. Hub

Read-only info: firmware version, uptime, serial link state, current EPD
screen mirror (cached PNG, refreshed on the same 20-min rotation cadence).
Actions: OTA upload (`.bin`), restart (with confirm). Serial console: scrollable
tail, poll every 5 s, "do not paste" warning above.

### 7. Settings

- Alias map import/export (CSV: `hex_id,alias,notes`).
- Default fit mode + default dither (applied in Editor).
- `LOG_IDS` display preference for EPD: `hex` | `alias` (all-or-nothing —
  server validates that every tag has an alias before allowing `alias` mode).
- Rotation slot durations (default 20 min per slot).
- Physical grid config (rows × cols) for the Fleet Map view.

---

## Job state machine

```
pending ──► sending ──► acked ──► rendered
   ▲           │
   │           ▼
   └────── retrying ◄── (transient failure)
               │
               ▼ (attempts >= 3)
             failed
```

- `pending` — queued, not yet sent to hub.
- `sending` — handed to serial layer.
- `acked` — hub confirmed receipt.
- `rendered` — hub confirmed full refresh completed.
- `retrying` — transient error (timeout, NAK). Backoff 30 s, then 2 min,
  then 10 min.
- `failed` — attempts ≥ 3. Manual retry required.

Background worker polls `jobs WHERE state IN ('pending','retrying')` every 10 s.

---

## Rules for the implementing agent

1. **Hex IDs are 4 uppercase chars, no prefix, monospace everywhere.** The web
   UI, the API, the DB, and the EPD firmware all use this exact format. Never
   render `0xA3F2` or `41970`.
2. **Portrait-first rendering.** All bitmaps are authored 152×296; rotation to
   the panel's native 296×152 happens at the hub boundary. Web previews,
   API responses, and DB blobs are all 152×296.
3. **Three previews, always.** Original + on-device 1:1 + zoom. The user must
   see the dithered output before queuing. Never allow a push without a
   preview being generated and shown.
4. **Push is two-step.** Render (`/api/tags/content`) → confirm → queue
   (`/api/jobs`). Never fuse these.
5. **Dedupe bitmaps by SHA256.** Identical uploads across tags = one row.
6. **Job replacement per tag.** New push supersedes an open job for the same
   tag, and the UI confirms this explicitly.
7. **Event log dedupe is render-time only.** The `events` table keeps every
   row; the log view collapses consecutive identical `(hex_id, event)` with
   `×N`. Same rule as the EPD firmware — do not diverge.
8. **Alias mode is all-or-nothing.** If the user enables alias display for
   the EPD, every tag must have an alias; the server rejects the switch
   otherwise. In the web UI, per-screen toggle is fine, but never mix hex and
   alias in the same column.
9. **Poll, don't websocket.** EPD refresh is 20 min; anything faster is
   theatre.
10. **No auth beyond a single password.** LAN tool. Multi-user is out of scope.
11. **The Fleet table is the home screen.** Not a dashboard of KPI cards, not
    a chart. A table with status, battery, and last-bitmap thumbnail is 70 % of
    daily value.
12. **Content library, not a CMS.** Thumbnail grid of last 20 bitmaps. Click to
    reload into editor. No folders, no tags, no search.
13. **Templates are code, not user-authored.** Ship 6 hardcoded Jinja/HTML
    templates that render server-side to bitmaps. No WYSIWYG.
14. **`image-rendering: pixelated` on every EPD preview.** 1:1 fidelity is the
    whole point.
15. **Fleet map is optional but real.** If the physical grid is configured
    (Settings → grid rows × cols), the Map view renders tags at those
    positions. Same 4 states as the EPD screen C. If the grid isn't configured,
    hide the Map toggle entirely.

---

## Build order

1. DB + migrations + tag polling from hub serial.
2. Fleet table with status + battery + thumbnail.
3. Editor with 3-pane preview + FS dither + Push.
4. Job queue state machine + Queue screen.
5. Event log view (reuses the hub ring buffer over serial).
6. Templates (all 6) + template render path.
7. Fleet map (config-gated).
8. Hub screen + EPD mirror + OTA.
9. Stats charts (last, because you'll know by then which you actually miss).

Ship each step to yourself before starting the next. The editor preview stack
is the piece most likely to need iteration — budget extra time there.
```