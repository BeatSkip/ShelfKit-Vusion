# The apps UI as it is today

> **Changed 2026-11-15:** the Apps tab is now a home-screen grid (pixel-icon tiles; running = filled with a green tag-count badge, idle = dashed, failed = red), with drag-to-reorder, groups (drop an app on another), a context menu (start, stop, remove from group, disable), a sortable Disabled section, a New app wizard, and an app page with tag cards. The screenshots and the Apps tab section below show the old list layout.

The screenshots in `../screenshots/` were taken 2026-11-15 from a copy of the user's data:
- `apps-tab-hello-bound.png`: an app running on a tag, with stored data open.
- `apps-tab-pill.png` and `apps-tab-weather.png`: apps not running on any tag, shown as a preview.
- `layout-playground.png`
- `phone-page.png`: a phone-width tag page.

The main page is one HTML file (`shelfkit/static/index.html`) with a top nav: Fleet, Editor, Queue, Logs, Diagnostics, Hub, Flash, **Apps**, Settings. Each screen is a `<section data-screen>`. Plain JS (`app.js`, plus `apps.js` for the Apps screen) and one `style.css` with light and dark tokens.

## 1. Apps tab (`#apps`, `static/apps.js`)

**Header:**
- the title "Apps", and the note "Small programs on this server that draw a tag's screen and answer its NFC link. A tag runs one app at a time, and every change reaches it at its next check-in."
- a **Layout playground** link, which opens a separate page
- a **Reload apps** button, which re-imports every `inkapps/*/app.py`

**Left column: the app list.** Each app is a button showing:
- the title
- "On tag F466" / "On 3 tags" / "Not running", or "Did not load" in red

**Right column: the selected app's detail**, top to bottom:

1. **Head:**
   - the title
   - `id · drawn from layout.xml` or `draws in Python`, plus "updates itself every N min" when it has timers
   - the description
   - For an app that didn't load: the error in a `<pre>` with its line number, and a hint to fix the file and press Reload.
2. **Tags:**
   - A table of the tags the app runs on: Tag (picks it), Alias, Last sent (age), **Refresh now**, **Stop**.
   - Below it, a `<select>` with every other known tag ("(replaces weather)" when another app owns it) and a **Run on this tag** button.
3. **The selected tag:**
   - A true-size preview of the tag case with the app's current screen (`/api/inkapps/preview.png`).
   - When the app isn't on any tag yet, it says "Preview on <tag>" and "Nothing is sent until you press Run on this tag".
   - For a tag the app runs on:
     - **Settings for this tag:** one text input per config field (an empty field means the default) and **Save settings**.
     - **What the phone page offers:** the app's buttons and text fields, which actually run, plus **Simulate NFC tap** if the app has `on_open`.
     - The **NFC link**, with a warning when only this computer can open it.
   - A status line after each action, e.g.:
     - "Queued. The tag shows it after its next check-in."
     - "The screen is unchanged, so nothing was sent (saves the tag's battery)."
4. **Stored data** (collapsible):
   - the DB file path and size, the app's own tables with row counts, the tags whose data is kept although they no longer run the app
   - the shared JSON, and the selected tag's `{settings, data}` JSON
   - All read-only.
5. **Log** (collapsible, open by default): timestamped lines, or "Nothing logged since the server started".

**Behaviour:** the tab re-fetches every 5 s while open. The detail is rebuilt only when its shape changes, so typing isn't lost. The preview is re-fetched after an action or a push.

## 2. Layout playground (`/inkapps.html`)

A separate page, with a header link "Back to Apps" and a link to the **Skill file**.

- **Left:**
  - a "Load an app's layout…" select and a display select
  - a monospace `<textarea>` with the XML
  - a Data (JSON) textarea, with a JSON error line under it
- **Right:**
  - the rendered panel at 3× (pixelated)
  - the diagnostics list (error/warn/info, each with its element path)
  - the `boxes` text picture
- It renders as you type, through `POST /api/layout/render`.

What it can't do:
- **save**: an edited layout has to be copied into `inkapps/<id>/layout.xml` by hand
- use the app's real `@app.data` output, its sample data or a real tag's data
- try the app's controls
- chat with an AI

## 3. Phone page (`/tag/<ID>/view`)

A mobile page with no script, in a calm, light style:
- the app title, and the alias · tag id
- the current screen in a case frame
- one full-width dark button per `@app.button`
- a text field plus a send button per `@app.text_input`
- a status message after a post
- the app description as a footer

An unbound tag shows a plain explanation instead.

## 4. Elsewhere

- **Settings → Tag pages for phones → "Address phones use"** (`public_url`): the reverse-proxy address used in the NFC links.
- **Fleet:** a tag running an app looks like any other. The thumbnail is the last frame pushed (an app's push file is `data/apps/<HEX>.png`). There is no indication there of which app a tag runs.
- **Queue:** app pushes appear as image jobs labelled `app <id>`.
- **There is no Development tab.** "Development mode" is not a setting yet.

## UI conventions worth keeping

- Sentence-case labels, written as plain explanations ("Run on this tag", "Refresh now", "Stop").
- Buttons say what will happen, and the hints say what happens on the glass and when.
- True-size tag previews inside a drawn tag case. The panel is the hero.
- Dangerous actions arm first ("Press again to forget…").
- Everything works without a page reload, and nothing is lost while typing during the 5 s refresh.
