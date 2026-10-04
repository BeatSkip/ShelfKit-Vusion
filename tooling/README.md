# tooling/ — host-side scripts and the parked flash-dump firmware

Python 3 helpers that talk to the tag over its serial link, plus the flash-dump firmware that is
deliberately kept out of any target's `src/` so the SDCC build does not compile it.

| File | What it does |
|---|---|
| `png2epd.py` | Converts a PNG into the two 1-bit C arrays the e-paper driver uploads (`epd_image.c` / `epd_image.h`) |
| `flashdump.py` | Resets the tag (BOOT pin via DTR, RESET via RTS) and captures the flash hexdump the parked firmware prints — to console and to a timestamped file |
| `axsem-flasher.py` | Programs an Intel HEX file over the AX8052 serial bootloader: `?` banner → `K` erase → hex lines → `R` run |
| `flashdump_main.c` | The **parked** flash-dump firmware — a drop-in replacement for a target's `src/main.c` |
| `dumps/` | Two captured flash dumps from 2026-09-23, 389,188 bytes each |

None of this is compiled by the SDCC build; `png2epd.py` is the only one that produces build
input, and it writes into a target's `src/`.

## Requirements

```
pip install pyserial      # flashdump.py, axsem-flasher.py
pip install pillow        # png2epd.py
```

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
