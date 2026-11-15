# Gaps, roadmap and pain points

## The planned roadmap (from `Documentation/plans/2026-11-11-inkservices.md`)

| # | Chunk | Status |
|---|---|---|
| 1 | SDK and host core (InkApp, AppHost, per-app DB, duplicate and burst suppression, render CLI) | done |
| 2 | Apps tab (list, bind/unbind, config form, preview, Refresh now, data viewer, log) | done |
| 3 | Phone pages `/tag/<ID>` (forms, on_open, reverse-proxy friendly) | done |
| 4 | NFC link on the tag: the server writes `<address>/tag/<ID>` over the radio (Fleet inspector "Write NFC link", the bulk bar, the app page's "Write to the tag"); firmware 1.1.0-54 | done (differently: server-written, not phone-written) |
| 5 | Timers (`@app.every`) and the reference apps pill and weather | done |
| 6 | **Development mode**: a setting that shows a Dev tab. New app from a template, code editor, virtual tag (preview plus the phone page in a frame), reload, exceptions and log, stats (renders, pushes, skipped duplicates, errors), version history via `git` in the app folder. Tabs: Design / Description & versions / Backend / Debug & stats | not started |
| 7 | **Install from git and isolation**: "Install from GitHub URL" (`git clone --depth 1` into `inkapps/`), manifest check, installed **disabled**. One subprocess per app (JSON lines over stdin/stdout). Update and remove | not started |
| 8 | **AI safety review** before enabling an installed app: send the source to Claude and show the report. Advisory only. API key in settings | not started |
| 9 | **AI layout chat**, then a backend agent, in the Dev tab: describe, render, accept or revert through chunk 6's versions. Superseded for layouts by InkLayout L4 (`/api/layout/chat`) | not started |

InkLayout leftovers: `<image>`, bundled fonts, and L4 (the model adapter plus chat).

## Gaps observed in today's UI and backend

App management:
- **There is no install, update or delete.** An app exists because a folder exists. Disable/enable exists (2026-11-15): a disabled app is not imported and sits in the Apps tab's Disabled section.
- **There is no app metadata** beyond title and description: no version, author, source URL, permissions (there is an `icon=`, one of InkLayout's pixel icons) (for example "fetches from api.open-meteo.com"), or changelog. Nothing in the UI shows where an app came from or what it may do.
- **There are no fleet-level views.** Which app runs on which tag is visible only per app; the Fleet screen doesn't show it. You can't bind one app to several tags at once, even though Fleet has multi-select with Ctrl/Shift.
- **The settings form is typeless.** Every field is a text input: there are no time, date, number, select or location pickers, no validation and no help text. The pill and weather apps ask for "HH:MM", "YYYY-MM-DD" and latitude/longitude as free text.
- **Timers are opaque.** There is no last run, next run, last error or "run now" for a single timer. *Refresh now* runs all of them.
- **There is little feedback on delivery.** "Last sent" is an age. Nothing shows whether the tag has received the push yet, or how long until its next check-in.
- **The log** is in memory (200 lines) and gone after a restart. It has no filter by tag or level.
- **Stored data is read-only JSON.** The app's own tables are row counts only. There is no editing, export, reset, or "forget this tag's data".

App development:
- **Creating an app is a wizard only.** New app (Apps tab) scaffolds `app.py`/`layout.xml` from a template; there is no editing in the UI after that.
- **The playground is detached from apps.** It can load an app's layout but can't save it. Its data is hand-typed JSON, not the app's `@app.data` output or a real tag's data. It doesn't show the app's controls.
- **There is no virtual tag.** Previewing works for any tag id, but actions, settings and Simulate NFC tap need the app *bound to a real tag*, which pushes to real hardware and costs battery.
- **There is no code editing, versioning, diff or revert** in the UI. git exists in the repo, but there is nothing per app.
- **There are no stats**: render time, pushes versus skipped duplicates, error counts, battery cost per app.
- **There is no AI assistance yet:** no layout chat, code agent or safety review, and no API-key setting.
- **There is no time travel or sample-data scenarios.** Apps that depend on time (pill: missed days, reminder time; weather: stale data) are hard to test. `AppHost(clock=…)` exists for tests but isn't exposed in the UI.
- **Errors are hard to place:** a load error shows its line number, but a runtime exception is only a log line.

## Ideas the existing code already makes cheap

- **Virtual tag.** `GET /api/inkapps/preview.png?app=&tag=` already renders any app for any id without binding. A virtual tag needs actions and config that run against a throwaway or in-memory context: `_peek_store` already makes in-memory stores for previews.
- **Layout editing with live diagnostics.** `POST /api/layout/render` returns the PNG, diagnostics and boxes. Saving needs one new route.
- **Data-aware playground.** `@app.data(tag)` can be run for a real or virtual tag to give the playground real data.
- **Time travel.** The host already takes a clock parameter.
- **Stats.** The host knows every render, push, identical skip and failure. Counting them is cheap.
- **AI layout loop.** The skill file and the diagnostics are designed for a cheap model. Only the adapter and the chat route are missing.

## Open questions for the user (don't assume answers)

- Should development happen in the browser, with a code editor in the page, or in the user's own editor, with the server watching files? The spec suggests in the browser, but leaves manual coding open.
- Should versions be per-app git repos, or the main repo?
- Should installed third-party apps be allowed before subprocess isolation (chunk 7) exists?
- Which AI provider and model should the layout chat and safety review use, and where does the key live?
- Is a phone-friendly admin UI wanted, or only desktop?
