# ShelfKit-Server — browser UI and image push for the ShelfKit hub and tags

A local web app over the hub's serial port. The screen layout follows
[docs/web-interface-implementation.md](docs/web-interface-implementation.md): a **Fleet** table as the
home view, an **Editor** with the three-pane preview stack, plus **Queue**, **Logs**, **Stats**,
**Hub**, **Console** and **Settings**. Only some of that is backed by a server — the rest is
interface, clearly marked, so the shape of the finished tool is visible without pretending.

```
ShelfKit-Server/
  shelfkit-server.py     the app - the only thing you run
  shelfkit/              supporting modules, imported by it
    app.py                 panes, logs, tags, the image push (no UI)
    serial_link.py         ports, handshake lines, the reader thread
    store.py               the SQLite state file: settings, tags, bitmaps, events
    webapp.py              the HTTP/JSON layer over app.py
    static/                the page itself: index.html, app.js, style.css
    hubhost.py             hub command channel, image framing, and its own CLI
    png2epd.py             PNG -> the two 1-bit planes the panel streams
  docs/                  the interface spec this layout follows
  requirements.txt       pyserial, pillow
```

Only `pyserial` and `pillow` are needed: the server is the standard library's `http.server` and the
page is plain HTML/JS, with no framework and no build step.

## Install and run

```
pip install -r ShelfKit-Server/requirements.txt

python ShelfKit-Server/shelfkit-server.py hub=COM4 tag=COM3
python ShelfKit-Server/shelfkit-server.py hub=COM4                 # second pane stays free
python ShelfKit-Server/shelfkit-server.py --baud 115200 hub=COM4 tag=COM3
python ShelfKit-Server/shelfkit-server.py --port 9000 --no-browser
python ShelfKit-Server/shelfkit-server.py --db ../lab-state.db     # keep state elsewhere
python ShelfKit-Server/shelfkit-server.py --no-store               # forget everything on exit
python ShelfKit-Server/shelfkit-server.py --list
```

It prints the URL and opens a browser window on it:

```
ShelfKit server on http://127.0.0.1:8765/
  hub    COM4         open @ 38400 8N1
  tag    COM3         open @ 38400 8N1
Ctrl+C to stop
```

Ports named on the command line are opened at startup; ports that only come from the auto-detected
list are pre-filled but left closed. `--baud` sets the initial rate for both panes (default 38400,
the firmware's UART0 rate). The page listens on **127.0.0.1** by default — it can drive a serial port
and read image files on this machine, so it is not meant to be reachable from elsewhere;
`--host 0.0.0.0` is there deliberately if you want it on your LAN.

### Opening the ports

Two ways:

- **On the command line** — `hub=COM4 tag=COM3` opens those two at startup, which is the usual way.
- **In the page** — the **Console** tab holds the two panes: type or pick the port, set the baud,
  press **Open** on each. **DTR**, **Reset** and **Clear** sit on the same row.

Fleet and Hub both tell you when a pane is still closed and give you a button that jumps to the
Console, so an empty fleet table never looks like a broken page.

### Light and dark theme

The button at the right of the top bar switches between them; it shows the theme you would switch
*to*. The choice is remembered in `localStorage` under `shelfkit-theme` and applied by a small
inline script in `<head>`, so a reload comes up in the right palette without a flash of the other
one. On a first visit (nothing stored yet) the page follows the OS (`prefers-color-scheme`); after
that your explicit choice wins. `?theme=light` or `?theme=dark` in the URL forces one for a link or a
screenshot without touching what is saved.

Both palettes are the same layout with a different token set — `:root` holds the dark defaults and
`[data-theme="light"]` overrides the colours, so no rule hard-codes a colour outside those two
blocks. `color-scheme` is set per theme too, which keeps scrollbars and native controls in step.

## What is real, and what is only interface

| Screen | Working today | Interface only (marked in the page) |
|---|---|---|
| **Fleet** | Tag table from every `POLL src=<id>` the hub prints: 4-char hex id, **alias**, status dot (online if heard in the last 30 s, pending while an image is in flight, else offline), last-push age **with a thumbnail of the frame that was pushed**, search, status chips, column sort, row selection with bulk actions (push, **forget**), tag drilldown drawer that edits the alias and notes, **assigns the tag's wireless id** and **forgets the tag** | battery, reflash/clear, map view (hidden until a grid is configured) |
| **Editor** | Browse this machine's folders, pick the image and the target tag, **fit mode** (cover/contain/stretch), **dither** (threshold/Floyd-Steinberg/Bayer 4×4), the **three previews** — colour original, 1:1 on-device frame, and a 4× zoom that follows a drag — a midtone warning, and Push / Cancel with live frame progress. Push is only enabled once a preview has been rendered | templates, plain text, QR, multi-target push, the content library, the render → confirm → queue split |
| **Queue** | The transfer in flight (image or firmware) as a single `sending` row, with its frame progress, and Cancel | job history, attempts, retry, per-tag replacement |
| **Logs** | Event table recorded by the server (`sync`, `push`, `ok`, `fail`, `error`, `boot`, `bootloader`, `open`), consecutive duplicates collapsed into `×N`, filtered by tag or event, **kept across restarts** | the firmware's own event stream (low batt / err) and the per-tag log |
| **Stats** | — | all three charts (needs the stats rollup and battery reporting) |
| **Hub** | Serial link facts (port, state, baud, line count, DTR/RTS) and a read-only tail of the hub's console | firmware version, uptime, EPD mirror, OTA upload, restart |
| **Console** | The two-pane serial view: per-pane port, baud, Open/Close, DTR, Reset, Clear, both logs, Copy logs, Save log. The port and baud you used come back next run | — |
| **Settings** | — | alias CSV import/export, default fit/dither, `LOG_IDS` mode, rotation slots, fleet grid |

Everything in the right-hand column is rendered with the real controls, disabled, and a `soon` chip
or a one-line explanation — no dead ends that leave you wondering whether it is broken.

## The working parts, in detail

### Console (the original two-pane view)

One pane per port, each with its own port field (type it, or pick a detected port from the list), baud
rate, **Open/Close**, **DTR**, **Reset**, **Clear**, and its log below.

Both handshake lines start **released** (DTR low, RTS low). On this board DTR is the BOOT pin and RTS
the RESET line. **DTR** is a level toggle — it holds the boot pin where you put it — while **Reset** is
a push button: the server asserts RTS and releases it 100 ms later on a timer, because a reset line
left asserted would hold the board in reset. Each press is logged in that pane.

**Reset first puts the BOOT pin where the firmware runs**, because a BOOT pin held in bootloader mode
is the one way a reset comes up in the *serial bootloader* — the board then prints
`AX8052 Bootloader V1.1` instead of its firmware banner, stops polling, and looks like "it keeps
resetting". Which DTR level runs the firmware is decided by the board, not by a comment, so the server
watches what came up after its own pulse:

```
# reset pulsed (100 ms)
AX8052 Bootloader V1.1 Checksum 0xA7D2
# board came up in the serial bootloader - the BOOT pin was holding it there
# learned: DTR asserted runs the firmware; resetting again
# reset pulsed again
*** ShelfKit hub, node 0001 net 5a
radio ok, pll rng=10, listening
```

That correction happens once per reset and only when the bootloader actually appeared; after it the
learned level is used for every later press, so the sequence above is not something you have to keep
doing by hand.

The server itself never touches those lines otherwise. Opening a port still re-applies them once (the
driver does that, not this program), so opening it logs exactly what they were left at:

```
# COM4 open @ 38400 8N1, DTR released, RTS released
```

If a board resets *while the console is sitting there*, something else has hold of the port and is
toggling the lines — a second copy of this server, or the SDCC
extension's serial monitor.

**Copy logs** merges both panes by arrival time and puts the result on the clipboard, behind a header
naming both ports and the line count; **Save log** downloads the same text.

```
=== ShelfKit two-port log: hub=COM4, tag=COM3 - 128 lines, 2026-10-16 01:58:28 ===
[01:58:24.770 hub] POLL src=0100 seq=09 rssi=-36 up=6s att=1 hubrssi=-35
[01:58:24.784 tag] poll ok att=1 rssi=-35 hubrssi=-36
```

### Feeds, fit and dither, and the three previews

The pipeline lives in [shelfkit/preview.py](shelfkit/preview.py) and is used for **both** the preview
and the bytes that go to the tag, so what you see cannot disagree with what is sent:

```
load -> composite over white -> turn upright -> fit 152x296 -> quantise to black/white/red
```

- **Upright**: a landscape source is turned 90° (the long-standing default) so it reads correctly on
  the portrait-mounted panel; a portrait one is used as it is.
- **Fit**: `cover` fills the frame and crops the overflow, `contain` letterboxes on white, `stretch`
  distorts to fit. Any source size now renders — the old "resize the source" refusal is gone.
- **Dither**: `threshold` (nearest palette, best for line art), `floyd-steinberg`, or `bayer4`
  (ordered 4×4). Threshold is the default rather than the spec's Floyd-Steinberg: this is a
  three-colour panel, and error diffusion scatters red speckle into white around a logo.
- **On-device** is black/white/**red**, not 1-bit mono, because that is what the panel does — a mono
  preview would hide exactly the mistake it exists to catch.

The three panes are server-rendered PNGs displayed with `image-rendering: pixelated`; the browser
never dithers or resamples anything (spec rule 14). **Original** is the colour frame after fit,
**On device** is the frame the tag will show, and **Zoom 4×** is a 4× viewport into that same PNG
that follows a drag on the device pane. Over 40 % midtone pixels raises a warning — dithering a
muddy photo onto three colours does not come out well.

The preview is addressed by a hash of its inputs (`/api/preview.png?t=…`), so it survives a reload
and the browser may cache it; picking a new image or changing fit/dither invalidates it and Push
turns back off until it has been rendered again.

### Removing tags

Cleaning up after a mix-up is server-side bookkeeping only — nothing is sent to a tag, and a tag
that is still polling simply reappears as a fresh row (with no alias) on its next poll.

| Where | What it does |
|---|---|
| Drawer → **Forget tag** | deletes that one tag, its stored metadata and its log lines |
| Fleet → select rows → **Forget** | the same for a selection |
| Fleet → **Forget silent** | deletes every tag not heard for 10 minutes (a sleeping tag polls once a minute, so it stays) |
| Drawer → **Factory reset** | sends the tag a wipe command: it erases its SPI flash, resets and comes back with a **new random id**; the old row is dropped |

Each delete arms itself: the first click turns the button into **Really forget?**, the second
commits, and it disarms again after four seconds. A tag that is mid-transfer is skipped.

`POST /api/tags/<hex>/forget` removes one; `POST /api/tags/forget` takes `{"addrs": [...]}` or
`{"not_seen_for": 600}`; `POST /api/tags/<hex>/wipe` is the factory reset. Both return `{"result": {"forgot": n, "hexes": [...]}, "state": ...}` —
`forgot` counts only tags that actually existed, and ids freed this way are available to the next
identity assignment.

### Updating a tag's firmware over the air

**Fleet** → click a tag → under **Firmware update** pick one of the HEX files from `Release/`
(written by `ShelfKit-Firmware/Tooling/build-all.py`), then **Reflash**. The `*-full-*.hex`
bundles are filtered out on purpose: they carry the bootloader as well and cannot go over the
air.

The transfer is the same reliable DATA path images use, with the firmware opcodes
(`SM_OP_FW_BEGIN`/`CHUNK`/`END`):

1. the tag erases its SPI flash (about 0.3 s — the worker waits for it),
2. ~1,500 chunks are written straight through and folded into the tag's CRC,
3. `END` makes the tag verify, commit the image with its magic and reset,
4. the bootloader sees the magic, verifies the CRC again, programs the application and
   clears the magic; the tag comes back with the **same id** and its aliases intact.

Progress and Cancel are shared with image pushes, so the Queue screen shows either. The tag
only listens for `SHELF_LISTEN_WINDOW_S` (8 s) after each poll, so a transfer started at a
random moment may wait up to a minute for the next window; the frames are retried for 90 s,
which covers it.

The shell equivalent is `Tooling/ota-send.py`; both use `shelfkit/firmware.py`, so they cannot
disagree about the opcodes or the CRC.

### Assigning a tag's wireless id

A tag's node id is not built into its firmware — it lives in the tag's SPI flash, so one
image fits the whole fleet and the id survives updates. A brand new tag generates a random
16-bit id at first boot and logs it (`id? 3F2A new`); the hub prints it as `POLL src=3f2a …`
like any other tag.

To give it a proper id: click the row in **Fleet**, then under **Wireless identity** either
type a hex id or leave the field empty to take the lowest free one, and press **Assign**. The
server sends one DATA frame (`SM_OP_SET_ID`) over the hub port the Console already has open;
the tag writes the id, reads it back and moves its radio address, so a successful ACK means
the id will still be there after a reset. The server then moves everything it knew about that
tag — alias, notes, map position, counters, last frame — to the new row, so the fleet shows
one tag, not two.

The same thing from a shell, without the UI:
`python ShelfKit-Firmware/Tooling/set-id.py 3F2A 0100`.

### Pushing an image

In the **Editor**: **Browse…** opens a picker over this machine's folders (it starts in `Resources/`)
and lists only folders and image files; click a folder to go in, click an image to use it. Pick the
target under **Target tag** — the list is every node id that announced itself — then **Push to 1
tag**. The button turns into **Cancel** while a transfer runs and stops after the frame in flight.

The push goes over the serial port the Console pane already has open — it sends the hub's `S`/`P`
commands and reads the `SENT`/`PONG` answers out of that pane's own log. That is deliberate: closing
and reopening the port for a transfer re-applies DTR and RTS, and on this board a glitch on RTS is a
reset pulse. Nothing is reopened, the console keeps printing during the transfer, and the frames
appear in the log as they are acknowledged.

The rotation is chosen for you: a 296×152 landscape source is rotated 90 (the long-standing default),
a 152×296 portrait source is sent as it is, and the angle used is logged. Only an image that fits
neither way is refused, since the panel would show garbage.

The spec's two-step flow (render a preview → confirm → queue a job) is deliberately not faked: today
Push sends immediately, and the Editor says so.

A tag refreshes its panel (~15 s) at the end of the transfer and logs `img done busy=1 14.6s`; the
protocol, the frame format and the meaning of the log lines are in
[`../Documentation/wireless-link.md`](../Documentation/wireless-link.md).

### Logs, and where they come from

The server records an event whenever something notable happens, and the Logs screen reads those
events back:

| event | when |
|---|---|
| `sync` | a tag announced itself (`POLL src=…` on the hub pane) |
| `push` | a transfer started (with the image and the fit/dither used) |
| `ok` / `fail` | a transfer finished, or gave up / was cancelled |
| `error` | the send raised (with the message) |
| `boot` | a board printed its `*** ShelfKit …` banner — it just started |
| `bootloader` | a board came up in the AX8052 serial bootloader instead of the app |
| `open` | a port was opened (so you can see when the handshake lines changed) |

Consecutive identical rows with no detail collapse into one with `×N`, the same rule the firmware's
own log uses. Events live in the database, so the history is still there after a restart; the page
asks only for ids it has not seen yet (`&e=<id>` on the poll) and drops any it already has.

`boot` and `bootloader` are worth a look when a tag keeps resetting: they say exactly when a board
restarted, which is the question the serial log alone makes you guess at.

## State on disk

Everything the server would otherwise forget lives in one SQLite file —
`ShelfKit-Server/data/shelfkit.db` by default, `--db PATH` to move it, `--no-store` to run without
one. It is created on first run (folder included) and is the only file the server writes:

| table | what it holds |
|---|---|
| `settings` | the editor's image, fit and dither; the port and baud each pane last used |
| `tags` | alias, notes, map position, last seen, announcement count, last content and its bitmap |
| `bitmaps` | the rendered frames themselves (transport planes + both PNGs), newest 64 |
| `events` | the log above, newest 5000 |

The consequences, all of which are what "persistent" has to mean:

- **Restart and the app looks the same**: the image is back, re-rendered with the same fit and dither,
  the tags are back with their counters and ages, aliases survive, and the Fleet thumbnail of the last
  push still loads — the PNG is served from the store when it is no longer in the render cache.
- **Ages stay honest**: `last_seen` is a wall-clock timestamp, not a monotonic counter, so "36 s ago"
  means 36 s ago and not "since this process started".
- **Nothing is opened behind your back.** The saved port is a *default* for the pane's input; the
  server never reopens it on start, because opening re-applies DTR/RTS and a glitch on RTS is a reset
  pulse on this board.
- **Reset by deleting the file** (with the server stopped). `--no-store` does the same thing for one
  run without touching it.

Storage is best-effort by design: if the database cannot be opened the server prints why and runs
without it, and a failed write is reported in the log rather than failing the request. A console that
refuses to start because its history file is locked would be a worse tool.

## The same thing from a shell

```
python ShelfKit-Server/shelfkit/hubhost.py COM4 serve images/      # watch announcements, push new images
python ShelfKit-Server/shelfkit/hubhost.py COM4 send 0100 pic.png  # push one image to tag 0100 now
python ShelfKit-Server/shelfkit/hubhost.py COM4 ping               # check the hub's command channel
python ShelfKit-Server/shelfkit/hubhost.py --list
```

`serve` keeps one PNG per tag named after its node id in hex (`0100.png`) and pushes it when the
tag announces itself and the file is new or changed since the last successful push (remembered in
`images/.sent.json`).

## Regenerating a target's boot image

`shelfkit/png2epd.py` writes into a firmware folder, so run it from the target so the default
`--out-dir src` lands in the right place:

```
cd ShelfKit-Firmware/Vusion
python ../../ShelfKit-Server/shelfkit/png2epd.py polyform-eink.png
```

`--rotate 90` is the default and is what the checked-in planes were generated with; add
`--dither` for Floyd-Steinberg dithering, or `--out-dir` to write the planes elsewhere.

## How it is put together

`shelfkit-server.py` is only the entry point: it parses the arguments, builds an `App` and hands it
to `webapp`. `app.App` owns the panes, their logs (a 5000-line ring buffer per pane, each line
stamped and sequenced), the tag list and the image push; `serial_link` owns the ports and one reader
thread each. Nothing in `app` or `serial_link` knows a browser exists.

The page polls `GET /api/poll?c=<pane>:<epoch>:<seq>,…` a few times a second and gets back only the
lines it has not seen yet, plus the whole state, which is cheap enough to redraw. `Clear` bumps the
pane's epoch so the next poll tells the browser to wipe that pane. The spec suggests 10–30 s polling;
the console needs 200 ms because it is a live UART tail, and only the diff comes back. The full
endpoint list is in the docstring of [`shelfkit/webapp.py`](shelfkit/webapp.py).

The screens keep the spec's vocabulary on purpose: hex ids are always 4 uppercase characters with no
prefix, the status colours are the same five everywhere, and `image-rendering: pixelated` is already
on the preview surfaces for when they hold real bitmaps.
