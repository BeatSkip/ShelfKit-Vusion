# Tooling — firmware-side host scripts

Python 3 helpers that build and flash the boards over their serial link. The host-side *application*
— the browser UI and everything it imports — lives in
[`../../ShelfKit-Server/`](../../ShelfKit-Server/README.md), and the flash-dump captures live in
[`../../Data/`](../../Data/).

| File | What it does |
|---|---|
| `build-all.py` | Builds every firmware target and writes ready-to-flash Intel HEX files to `Release/` at the repository root |
| `axsem-flasher.py` | Programs an Intel HEX file over the AX8052 serial bootloader: `?` banner → `K` erase → hex lines → `R` run |

## Building everything

```
python ShelfKit-Firmware/Tooling/build-all.py
python ShelfKit-Firmware/Tooling/build-all.py --version 1.2.0
python ShelfKit-Firmware/Tooling/build-all.py --targets vusion,bootloader
python ShelfKit-Firmware/Tooling/build-all.py --clean
```

```
=== ready to flash ===
  vusion-20261018-1326e7e-dirty.hex      106841 bytes  code 37866/59389, xram 1047/8192
  vusion-hub-20261018-1326e7e-dirty.hex  106286 bytes  code 37675/59389, xram 1130/8192
  bootloader-20261018-1326e7e-dirty.hex   17120 bytes  code 6038/65536, xram 392/8192
```

It builds each target exactly the way SDCC-MDF does, because it reads the target's own
`sdcc-project.json` and the board definition that file names:

- `build.flags` of the project (this is where the bootloader's `-Wl-bHOME=0xe400` and its 64 KB code
  space live),
- CPU, memory model and the IRAM/XRAM/code sizes from [`../Shared/boards/`](../Shared/boards),
- `sources` (directories are walked for `.c` and `.asm`, and every source directory's `inc/` is added
  to the include path), `includes`, `libraries` (every `*.lib`) and `defines`.

The compiler work happens in a temp directory, so a VS Code build and this script never fight over
object files. Each HEX lands in `Release/` with its `.map` next to it — the map is where you confirm
placement, and the `.mem` figures are printed in the summary.

**File names:** `<target>-<version>-<date>.hex` when you pass `--version`, otherwise
`<target>-<date>-<git hash>[-dirty].hex`. The target name comes from the folder (`vusion`,
`vusion-hub`, `bootloader`), not from `build.output_name` — both Vusion projects call their build
`firmware`, which would collide.

`Release/` is git-ignored: it is output, and re-running the script regenerates it.

## Flashing a build

```
python ShelfKit-Firmware/Tooling/axsem-flasher.py Release/vusion-20261018-1326e7e-dirty.hex -p COM7
```

**SDCC: Flash calls this too.** `upload` in each target's `sdcc-project.json` runs this script with
`${outputHex}` (the file just built) and `${config:comPort}`:

```json
  "upload": {
    "tool": "python",
    "args": [
      "../Tooling/axsem-flasher.py",
      "${outputHex}",
      "-p",
      "${config:comPort}"
    ]
  }
```

The extension anchors the command at the project root, so the relative `../Tooling/…` path resolves;
set `sdcc.comPort` in the target's `.vscode/settings.json` to pick the port.

The flasher talks to the **mask-ROM** bootloader, selected by holding the BOOT pin at reset (the
adapter's DTR line). That is the only thing that can write the top of the flash, so it is also how
`bootloader-*.hex` gets installed in the first place.

## Requirements

```
pip install pyserial
```

SDCC must be on `PATH` or in its default Windows install (`C:\Program Files\SDCC\bin`) for
`build-all.py`; the flasher needs only `pyserial`.

## What used to be here

`monitor.py` (a timestamped two-port log merge with a link summary on stdout) and `test_shelflink.py`
(62 simulator unit checks for the link layer) are gone. The first was superseded by the server's
Console and Logs screens, which merge the logs, keep them across restarts and add the image push. The
second lost its test sources (`tooling/tests/*.c`) and could no longer run; if the protocol needs
regression tests again, they have to be restored from git history first.
