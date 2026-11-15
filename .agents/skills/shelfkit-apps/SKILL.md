---
name: shelfkit-apps
description: How ShelfKit's apps (InkServices) work today, covering the Python SDK, the InkLayout screen language, the host that runs apps and pushes their screens to e-ink tags, the admin Apps tab, the layout playground, the phone pages a tag's NFC link opens, the HTTP API and the known gaps. Load it before brainstorming, designing or reviewing UI for developing new apps or managing installed apps, or before changing anything under ShelfKit-Server/shelfkit/inkservices, shelfkit/inklayout, inkapps/ or static/apps.js.
---

# ShelfKit apps (InkServices)

ShelfKit drives reused SES-imagotag Vusion 2.6" e-paper shelf tags (152×296 px, black/white/red, a CR2450 coin cell, NFC). A hub radio sits on a serial port of a Python server (`ShelfKit-Server`), and the server pushes images to the tags.

**InkServices** is the app layer on that server. An *app* is a small Python program that:

- **owns the screen** of one or more tags and redraws it from its data,
- **answers the tag's NFC link**: a phone that taps the tag opens a page with the app's buttons and text fields,
- **keeps per-tag settings and data** in its own SQLite file,
- **can update itself** on a timer, for example to fetch the weather.

The owner (a single hobbyist running the server at home) writes apps in Python. The long-term goal (the user's own spec, `Documentation/InkServices.md`) is an **Apps tab** for managing apps and a **Development mode** tab for creating them. The development tab would have a virtual tag, sections for front-end design, description and versions, backend and debug/stats, and AI help for layouts and code. Apps would install from a GitHub URL, with an optional AI safety review.

This skill describes **what exists today** so you can brainstorm a better UI for two jobs:

1. **App development:** creating an app, designing its screen, writing its callbacks, testing it on a virtual tag, debugging it.
2. **App management:** seeing what is installed, putting apps on tags, configuring them, looking at their data and logs, installing, updating and removing apps.

## Files to read for depth

| Topic | File |
|---|---|
| The SDK an app author uses, the app lifecycle, and the rules that matter (battery, latency, safety) | [references/sdk-and-runtime.md](references/sdk-and-runtime.md) |
| InkLayout, the XML screen language, and its renderer's diagnostics | [references/inklayout.md](references/inklayout.md) |
| Every UI surface today: Apps tab, layout playground, phone page, Settings, with screenshots | [references/ui-today.md](references/ui-today.md) |
| The HTTP API the UI is built on | [references/http-api.md](references/http-api.md) |
| What's missing, the planned roadmap (chunks 6-9), and the observed pain points | [references/gaps-and-roadmap.md](references/gaps-and-roadmap.md) |
| Screenshots of the current UI | `screenshots/*.png` |

Primary sources in the repo (read them when a detail matters, since they win over this skill):
- `Documentation/InkServices.md`: the user's own vision, in their words.
- `Documentation/InkLayout.md`: the layout language spec and status.
- `Documentation/plans/2026-11-11-inkservices.md`: the implementation plan, with progress and decisions.
- Code: `ShelfKit-Server/shelfkit/inkservices/`, which has
  - `sdk.py`: `InkApp`, `TagContext`
  - `host.py`: `AppHost`
  - `web.py`: the admin API
  - `phone.py`: the tag pages
  - `appstore.py`: each app's own database
  - `loader.py`, `screen.py`, `canvas.py`
- More code: `shelfkit/inklayout/` (the layout engine and skill-file generator), `shelfkit/static/apps.js` (the Apps tab), `shelfkit/static/inkapps.html` (the playground).
- Example apps: `ShelfKit-Server/inkapps/{hello,pill,weather}/`.

## The model in one picture

```
inkapps/<id>/app.py ─┐   (folder = app; id = folder name)
inkapps/<id>/layout.xml ─┤ loader imports on start / "Reload apps"
inkapps/<id>/data/app.db ┘ (git-ignored; per-tag config + data + app's own tables)
        │
        ▼
     AppHost  ── bindings (main DB: which app owns which tag; last pushed hash)
        │  render: @app.render(Canvas)  or  layout.xml filled with @app.data
        │  push only if the pixels changed → server queue → hub → tag at its next poll
        │  scheduler thread: @app.every(minutes=N)
        ▼
  Admin UI (127.0.0.1)                     Phone (through a reverse proxy, /tag/ only)
  #apps tab, /inkapps.html playground      /tag/<ID> → on_open → /tag/<ID>/view (buttons, text)
```

## Facts that constrain any UI design

- **A tag runs one app at a time.** An app can run on many tags, each with its own settings and data, plus one shared document per app.
- **A change reaches the glass only at the tag's next check-in.** That is up to about 5 minutes when idle, and seconds after an NFC tap (the tag polls straight away and again about 5 s later). A full refresh takes about 15 s and the panel flashes. A UI should say "queued" rather than imply the change is instant.
- **Every push costs battery.** The host never pushes a picture identical to the last one, and a queued image for a tag is replaced, never stacked. Apps should avoid clocks on screen.
- **Screens are 152×296, portrait by default, in 3 colours.** There is no grey except dot and hatch patterns. Text is drawn 1-bit. The preview is pixel-exact with what the tag shows.
- **App code is trusted and runs inside the server process.** A crash is caught and logged, but there is no sandbox yet; subprocess isolation is chunk 7. Layout XML is data and safe to render; Python is not.
- **The admin UI is localhost-only**, because it drives serial ports and flashes firmware. Phones only ever see `/tag/...` pages: plain HTML forms, no JavaScript, under a strict CSP.
- **The server is a single-user home tool.** There are no accounts and no multi-user permissions.
- **The UI style** is plain HTML, CSS and vanilla JS with no framework. The look is an industrial "shelf" style: DIN-like font, ink on grey, true-size tag previews, light and dark themes. It is served from `shelfkit/static/`. A new UI should fit `style.css`'s tokens (`--ink`, `--surface`, `--raised`, `--rule`, `--red`, …).

## When brainstorming

- Ground every idea in the APIs that exist (references/http-api.md), and say clearly when an idea needs new backend work.
- Use the user's own spec for the target: Apps tab plus a Development mode tab with a virtual tag, and sections for Design / Description & versions / Backend / Debug & stats. Install from git, an AI safety check, and AI-assisted layout ("cheap model + skill file + renderer diagnostics", InkLayout §4).
- Keep the e-ink realities above visible in the design: the latency, the battery cost, three colours, and pixel-exact previews.
