# tooling/ — host-side scripts and the parked flash-dump firmware

Python 3 helpers that talk to the tag over its serial link, plus the flash-dump firmware that is
deliberately kept out of any target's `src/` so the SDCC build does not compile it.

| File | What it does |
|---|---|
| `png2epd.py` | Converts a PNG into the two 1-bit C arrays the e-paper driver uploads (`epd_image.c` / `epd_image.h`) |
| `hubhost.py` | Host side of the image push: watches the hub's POLL src=... announcements and sends new images to tags over the hub's serial port (`serve`, `send`, `ping`); see Documentation/wireless-link.md |
| `monitor.py` | Merges the hub's and the tag's logs into one timestamped stream on stdout, with a link summary (loss, attempts, RSSI) |
| `hub/monitor.py` | Textual TUI: the same two ports as two side-by-side panes (own log, baud rate, Open/Close, Clear and DTR/RTS buttons each), plus a top bar that browses for an image and pushes it to a tag picked from the ones that announced themselves |
| `flashdump.py` | Resets the tag (BOOT pin via DTR, RESET via RTS) and captures the flash hexdump the parked firmware prints — to console and to a timestamped file |
| `axsem-flasher.py` | Programs an Intel HEX file over the AX8052 serial bootloader: `?` banner → `K` erase → hex lines → `R` run |
| `flashdump_main.c` | The **parked** flash-dump firmware — a drop-in replacement for a target's `src/main.c` |
| `dumps/` | Two captured flash dumps from 2026-09-23, 389,188 bytes each |

None of this is compiled by the SDCC build; `png2epd.py` is the only one that produces build
input, and it writes into a target's `src/`.

## Requirements

```
pip install pyserial      # flashdump.py, axsem-flasher.py, monitor.py, hubhost.py, hub/monitor.py
pip install pillow        # png2epd.py, and the image push in hub/monitor.py
pip install textual       # hub/monitor.py   (or: pip install -r tooling/hub/requirements.txt)
```

## Watching two ports side by side

Two tools share this name. `monitor.py` merges both logs into one stream on stdout; `hub/monitor.py`
opens the same two ports in a Textual TUI instead — one pane per port, each with its own log, baud
rate, Open/Close, Clear, DTR and Reset buttons, plus a bar for pushing an image to a tag:

```
python tooling/hub/monitor.py hub=COM4 tag=COM3
python tooling/hub/monitor.py hub=COM4                    # second pane stays free
python tooling/hub/monitor.py --baud 115200 hub=COM4 tag=COM3
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
port name too (`loop://`), which is handy for trying the layout without hardware.

### Copying both logs

**[Copy logs]** in the top bar merges the two panes by arrival time and puts the result on the
clipboard, in the same `[HH:MM:SS.mmm <port name>] <text>` shape `monitor.py` prints, behind a
header naming both ports and the line count:

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

### Pushing an image to a tag

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

## Regenerating a target's boot image

Run it from the target folder, so the default `--out-dir src` lands in the right place:

```
python ../tooling/png2epd.py polyform-eink.png
```

`--rotate 90` is the default and is what the checked-in planes were generated with; add
`--dither` for Floyd-Steinberg dithering, or `--out-dir` to write the planes elsewhere.

## Capturing a flash dump

1. Copy `flashdump_main.c` over a target's `src/main.c`, rebuild and flash it.
2. From the repo root: `python tooling/flashdump.py COM7` — it pulses reset and writes
   `flashdump_<timestamp>.txt`, stopping at `*** end of dump ***`.
   `--bootloader` resets into the serial bootloader instead (add `--run` to send `R` after the
   banner and capture the dump from the bootloader's own reader); `--list` lists serial ports.
3. The dump firmware prints JEDEC ID first, then a full hexdump at 38400 8N1.

## Flashing a build

```
python tooling/axsem-flasher.py Shelfkit-Hub/build/firmware.hex -p COM7
```

**SDCC: Flash does not call this yet.** `upload` in each target's `sdcc-project.json` is still the
original `echo` placeholder, so the extension only warns that the flash tool is not configured —
exactly as before this cleanup. To wire it up, replace that section with:

```json
  "upload": {
    "tool": "python",
    "args": [
      "../tooling/axsem-flasher.py",
      "${outputHex}",
      "-p",
      "${config:comPort}"
    ]
  }
```

The extension expands `${outputHex}` to the built Intel HEX and `${config:comPort}` to the
`sdcc.comPort` setting, and it anchors the command at the project root — so the relative
`../tooling/…` path resolves and `"sdcc.comPort": "COM7"` in `.vscode/settings.json` picks the
port. The same recipe works for both targets.
