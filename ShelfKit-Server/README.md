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
one. On a first visit (nothing stored yet) the page follows the OS
(`prefers-color-scheme`); after that your explicit choice wins.

Both palettes are the same layout with a different token set — `:root` holds the dark defaults and
`[data-theme="light"]` overrides the colours, so no rule hard-codes a colour outside those two
blocks. `color-scheme` is set per theme too, which keeps scrollbars and native controls in step.

## What is real, and what is only interface

| Screen | Working today | Interface only (marked in the page) |
|---|---|---|
| **Fleet** | Tag table from every `POLL src=<id>` the hub prints: 4-char hex id, status dot (online if heard in the last 30 s, pending while an image is in flight, else offline), last-push age, search, status chips, column sort, row selection with bulk actions, tag drilldown drawer | alias editing, battery, bitmap thumbnails, reflash/clear, map view (hidden until a grid is configured) |
| **Editor** | Browse this machine's folders, pick the image and the target tag, Push / Cancel, live frame progress | the three preview panes (original / on-device 1:1 / zoom), fit mode, dither choice, templates, plain text, QR, multi-target push, content library |
| **Queue** | The transfer in flight as a single `sending` row, with its frame progress, and Cancel | job history, attempts, retry, per-tag replacement |
| **Logs** | Event table derived from the hub's `POLL` lines, with consecutive duplicates collapsed into `×N`, filtered by tag or event | the firmware's own event stream (online / offline / low batt / err) and the per-tag log |
| **Stats** | — | all three charts (needs the stats rollup and battery reporting) |
| **Hub** | Serial link facts (port, state, baud, line count, DTR/RTS) and a read-only tail of the hub's console | firmware version, uptime, EPD mirror, OTA upload, restart |
| **Console** | The two-pane serial view: per-pane port, baud, Open/Close, DTR, Reset, Clear, both logs, Copy logs, Save log | — |
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
toggling the lines — a second copy of this server, the old `tooling/monitor.py`, or the SDCC
extension's serial monitor.

**Copy logs** merges both panes by arrival time and puts the result on the clipboard, behind a header
naming both ports and the line count; **Save log** downloads the same text.

```
=== ShelfKit two-port log: hub=COM4, tag=COM3 - 128 lines, 2026-10-16 01:58:28 ===
[01:58:24.770 hub] POLL src=0100 seq=09 rssi=-36 up=6s att=1 hubrssi=-35
[01:58:24.784 tag] poll ok att=1 rssi=-35 hubrssi=-36
```

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

The Logs screen is not a database view. It reads the hub pane's UART stream, picks out
`POLL src=<id>` lines and shows them as `sync` events, collapsing consecutive identical
`(hex_id, event)` rows into one with `×N` — the same rule the firmware's own log uses. Reloading the
page replays what the server still holds (5000 lines per pane).

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
cd Shelfkit-Vusion
python ../ShelfKit-Server/shelfkit/png2epd.py polyform-eink.png
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
