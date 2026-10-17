# ShelfKit-Server — host-side tooling for the ShelfKit hub and tags

Python 3 that talks to the boards over the hub's serial port: a two-port live monitor with an
image-push bar, the command-line image pusher underneath it, and the PNG→e-paper converter both
of them use. Nothing here is compiled by the SDCC build — see [`../tooling/`](../tooling) for the
flasher, the flash-dump capture and the firmware-side protocol tests.

| File | What it does |
|---|---|
| `shelfkit-server.py` | Textual TUI: two serial ports as two side-by-side panes (own log, baud rate, Open/Close, Clear, DTR and Reset controls each), plus a top bar that browses for an image and pushes it to a tag picked from the ones that announced themselves |
| `hubhost.py` | Host side of the image push without a UI: watches the hub's `POLL src=...` announcements and sends new images to tags (`serve`, `send`, `ping`) |
| `png2epd.py` | Converts a PNG into the two 1-bit C arrays the e-paper driver uploads (`epd_image.c` / `epd_image.h`) |
| `requirements.txt` | `pyserial`, `textual`, `pillow` — the whole tree's Python dependencies |

## Install

```
pip install -r ShelfKit-Server/requirements.txt
```

## Watching two ports side by side

```
python ShelfKit-Server/shelfkit-server.py hub=COM4 tag=COM3
python ShelfKit-Server/shelfkit-server.py hub=COM4                 # second pane stays free
python ShelfKit-Server/shelfkit-server.py --baud 115200 hub=COM4 tag=COM3
python ShelfKit-Server/shelfkit-server.py --list
```

Ports named on the command line are opened straight away; ports that only come from the
auto-detected list are pre-filled but left closed, so the tool never grabs a port you did not ask
for. `--baud` sets the initial rate for both panes (default 38400, the firmware's UART0 rate), and
each pane can then be changed on its own.

Both handshake lines start **released** (DTR low, RTS low). On this board DTR is the BOOT pin and
RTS the RESET line, so that is the state which neither resets the tag nor drops it into the
bootloader. Per pane, **DTR (boot)** is a level toggle — it holds the boot pin where you put it —
while **Reset** is a push button: it asserts RTS for 100 ms and releases it on a timer, because a
toggle left "on" would hold the board in reset. Each press is logged. Any pyserial URL works as a
port name too (`loop://`, `socket://host:port`), which is handy for trying the layout without
hardware.

### Copying both logs

**[Copy logs]** in the top bar merges the two panes by arrival time and puts the result on the
clipboard, in the same `[HH:MM:SS.mmm <port name>] <text>` shape `../tooling/monitor.py` prints,
behind a header naming both ports and the line count:

```
=== ShelfKit two-port log: hub=COM4, tag=COM3 - 128 lines, 2026-10-16 01:58:28 ===
[01:58:24.770 hub] POLL src=0100 seq=09 rssi=-36 up=6s att=1 hubrssi=-35
[01:58:24.784 tag] poll ok att=1 rssi=-35 hubrssi=-36
```

It feeds both clipboards, because neither is reliable on its own: Textual's terminal clipboard
(OSC 52, which some terminals and Windows Terminal builds ignore) *and* the OS one through
`clip` (Windows), `pbcopy` (macOS) or `wl-copy`/`xclip`/`xsel` (Linux). The status line reports which
of the two accepted it. The copy is built from the lines as they arrived rather than from the
rendered panes, so a long line that wrapped on screen is copied as one line.

## Pushing an image to a tag

The top bar does what `hubhost.py` does from the command line, without leaving the window:

1. **[Browse...]** opens a picker listing folders and image files only. It starts in `Resources/`,
   and you can type a path instead of clicking through to one.
2. The **tag** list fills itself in with every node id that announced itself as `POLL src=<id>` on
   the hub pane; the number in brackets is how many announcements were seen.
3. **[Send]** picks the rotation that fits the panel, converts the image and drives the hub's
   command channel. Progress and the result land in the hub pane's log.

The hub pane's port is closed for the duration and reopened afterwards, because one serial port
cannot serve two owners — which is also why that pane's log pauses during a transfer. **[Send]
becomes [Cancel]** while a transfer runs, and quitting cancels it. The rotation is chosen for you:
a 296×152 landscape source is rotated 90 (the long-standing default), a 152×296 portrait source is
sent as it is, and the angle used is logged. Only an image that fits neither way is refused, since
the panel would show garbage. `png2epd.load_planes()` on its own still refuses a portrait source at
`--rotate 90`; pass `--rotate 0`, or call `png2epd.fit_rotation()`.

Which pane is "the hub"? The one named `hub` on the command line; failing that, the first pane that
has heard a `POLL`; failing that, the first pane.

A tag refreshes its panel (~15 s) at the end of the transfer and logs `img done busy=1 14.6s`; the
protocol, the frame format and the meaning of the log lines are in
[`../Documentation/wireless-link.md`](../Documentation/wireless-link.md).

## The same thing from a shell

```
python ShelfKit-Server/hubhost.py COM4 serve images/       # watch announcements, push new images
python ShelfKit-Server/hubhost.py COM4 send 0100 pic.png   # push one image to tag 0100 now
python ShelfKit-Server/hubhost.py COM4 ping                # check the hub's command channel
python ShelfKit-Server/hubhost.py --list
```

`serve` keeps one PNG per tag named after its node id in hex (`0100.png`) and pushes it when the
tag announces itself and the file is new or changed since the last successful push (remembered in
`images/.sent.json`).

## Regenerating a target's boot image

`png2epd.py` lives here but writes into a firmware folder, so run it from the target so the default
`--out-dir src` lands in the right place:

```
cd Shelfkit-Vusion
python ../ShelfKit-Server/png2epd.py polyform-eink.png
```

`--rotate 90` is the default and is what the checked-in planes were generated with; add
`--dither` for Floyd-Steinberg dithering, or `--out-dir` to write the planes elsewhere.
