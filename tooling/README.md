# tooling/ — firmware-side host scripts and the parked flash-dump firmware

Python 3 helpers that flash, dump and exercise the boards over their serial link, plus the
flash-dump firmware that is deliberately kept out of any target's `src/` so the SDCC build does
not compile it.

The host-side *application* — the browser UI and everything it imports — lives in
[`../ShelfKit-Server/`](../ShelfKit-Server/README.md).

| File | What it does |
|---|---|
| `axsem-flasher.py` | Programs an Intel HEX file over the AX8052 serial bootloader: `?` banner → `K` erase → hex lines → `R` run |
| `dumps/flashdump.py` | Resets the tag (BOOT pin via DTR, RESET via RTS) and captures the flash hexdump the parked firmware prints — to console and to a timestamped file |
| `dumps/flashdump_*.txt` | Two captured flash dumps from 2026-09-23, 389,188 bytes each |
| `monitor.py` | Merges the hub's and the tag's logs into one timestamped stream on stdout, with a link summary (loss, attempts, RSSI) |
| `test_shelflink.py` | Simulator unit tests for the shared link layer: `tests/sl_proto_test.c` (22 checks) and `tests/shelflink_test.c` (40 checks with stubbed radio/timers) |

`flashdump_main.c` — the **parked** flash-dump firmware, a drop-in replacement for a target's
`src/main.c` — is currently only in git history (it was last present at `afd19cf`); the dumps it
produced are kept in `dumps/`.

None of this is compiled by the SDCC build. Only `png2epd.py` (over in
`ShelfKit-Server/shelfkit/`) produces build input, and it writes into a target's `src/`.

## Requirements

```
pip install pyserial      # flashdump.py, axsem-flasher.py, monitor.py
```

The browser UI and its image push need `pillow` as well; that lives in
[`../ShelfKit-Server/requirements.txt`](../ShelfKit-Server/requirements.txt).

## Watching both logs on stdout

```
python tooling/monitor.py hub=COM7 tag=COM8
python tooling/monitor.py hub=COM7 tag=COM8 --log run1.txt --summary 60
python tooling/monitor.py tag=COM8 --reset          # reset the tag first (RTS pulse)
python tooling/monitor.py --list
```

Every line is printed with a timestamp and the port name, and the link summary is built from what
the firmware prints (`poll ok att=N rssi=R hubrssi=H`, `poll FAILED after N attempts`,
`POLL src=.. seq=.. rssi=R [retry] [dup]`), shown every `--summary` seconds and on Ctrl+C. DTR
(boot pin) and RTS (reset) are held low while the ports are open, so opening a port does not reset
the tag or send it into the bootloader. This is the plain-text fallback; the browser UI with the
image push is [`../ShelfKit-Server/shelfkit-server.py`](../ShelfKit-Server/shelfkit-server.py).

## Capturing a flash dump

1. Put the dump firmware in a target's `src/main.c`, rebuild and flash it.
2. From the repo root: `python tooling/dumps/flashdump.py COM7` — it pulses reset and writes
   `flashdump_<timestamp>.txt`, stopping at `*** end of dump ***`.
   `--bootloader` resets into the serial bootloader instead (add `--run` to send `R` after the
   banner and capture the dump from the bootloader's own reader); `--list` lists serial ports.
3. The dump firmware prints JEDEC ID first, then a full hexdump at 38400 8N1.

## Flashing a build

```
python tooling/axsem-flasher.py ShelfKit-Firmware/Vusion-Hub/build/firmware.hex -p COM7
```

**SDCC: Flash calls this now.** `upload` in each target's `sdcc-project.json` already runs this
script with the built hex and the `comPort` workspace setting. The section it uses looks like this:

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

## Testing the link layer

```
python tooling/test_shelflink.py
```

Compiles `tests/sl_proto_test.c` and `tests/shelflink_test.c` for the AX8052 memory model and runs
them on the SDCC simulator (`s51`), reading the per-check results back out — framing, checksums and
the duplicate filter in one, the retry/acknowledge state machine (against stubs for the radio
engine, the wake-up timers and the random source) in the other. No hardware involved. Needs
`sdcc`/`s51` on PATH or in `C:\Program Files\SDCC\bin`.
