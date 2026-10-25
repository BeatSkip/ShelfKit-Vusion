# Tooling — firmware-side host scripts

Python 3 helpers that build and flash the boards over their serial link. The host-side *application*
— the browser UI and everything it imports — lives in
[`../../ShelfKit-Server/`](../../ShelfKit-Server/README.md), and the flash-dump captures live in
[`../../Data/`](../../Data/).

| File | What it does |
|---|---|
| `build-all.py` | Builds every firmware target and writes ready-to-flash Intel HEX files to `Release/` at the repository root |
| `axsem-flasher.py` | Programs an Intel HEX file over the AX8052 serial bootloader: `?` banner → `K` erase → hex lines → `R` run |
| `ota-send.py` | Sends a new application to a tag over the wireless link (OTA): converts the HEX, sends BEGIN/CHUNK/END, checks the image first with `--dry-run`. The server's Reflash button does the same through the same code (`ShelfKit-Server/shelfkit/firmware.py`) |
| `flash-read.py` | Reads a tag's SPI flash back over the radio (identity, OTA header, reserved sector, or any range) and writes a `.bin` plus a hexdump; `--from-log` reassembles a saved console log |
| `set-id.py` | Gives a tag its wireless id over the air (`current_id new_id`), which it stores in SPI flash and keeps across updates. The server's Fleet drawer does the same thing with a button |

## Building everything

```
python ShelfKit-Firmware/Tooling/build-all.py
python ShelfKit-Firmware/Tooling/build-all.py --version 1.2.0
python ShelfKit-Firmware/Tooling/build-all.py --targets vusion,bootloader
python ShelfKit-Firmware/Tooling/build-all.py --clean
```

```
=== one HEX for both ===
  Release/vusion-full-latest.hex
  bootloader 0xD800..0xF876  (8314 bytes)
  application 0x0003..0xA484  (42088 bytes, entry 0x021B)
  jump vector 0xD7FE = 1B 02

=== ready to flash ===
  vusion-20261021-12a46fc-dirty.hex      118827 bytes  code 42117/59389, xram 1111/8192
  vusion-hub-20261021-12a46fc-dirty.hex  106527 bytes  code 37763/59389, xram 1140/8192
  bootloader-20261021-12a46fc-dirty.hex   23518 bytes  code 8314/65536, xram 428/8192
```

`vusion-full-*.hex` holds the bootloader **and** the application, with the
application's entry installed in the bootloader's jump vector: one flash operation
for a tag that has neither yet. See
[../Bootloader/README.md](../Bootloader/README.md#installing-the-bootloader-and-the-application-at-once).

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

**File names:** `<target>-latest.hex` by default, or `<target>-<version>.hex` when you
pass `--version`. The output folder is cleared of old `.hex`/`.map` files on every
run, so `Release/` always holds exactly the build you just made. The old wording was
`<target>-<date>-<git hash>[-dirty].hex`. The target name comes from the folder (`vusion`,
`vusion-hub`, `bootloader`), not from `build.output_name` — both Vusion projects call their build
`firmware`, which would collide.

`Release/` is git-ignored: it is output, and re-running the script regenerates it.

## Reading a tag's flash back

```
python ShelfKit-Firmware/Tooling/flash-read.py 0102                     # all metadata, 0x0000..0x2FFF
python ShelfKit-Firmware/Tooling/flash-read.py 0102 --range 0:0x10000  # the whole chip
python ShelfKit-Firmware/Tooling/flash-read.py --from-log console.txt  # reassemble a saved log
```

The host asks the tag for a 4 KB page (`SM_OP_FLASH_DUMP`), the tag answers with
`SM_OP_FLASH_DATA` frames that the hub prints as `flash=<hex>`, and the script puts
them back together. It needs nothing plugged into the tag — only the hub port — and
the tag has to be awake, so a dump waits for its next poll at worst.

The same read is available in the server (**Fleet** → tag → **Read flash**), which
shows the metadata inline and serves the `.bin` as a download; both share
`shelfkit/flashdump.py`, so the frames and the descriptions are identical.

Output goes to `Data/dumps/` as `flash-<id>-<timestamp>.bin` and a matching `.txt`
hexdump, and the script prints what the bytes mean:

```
  identity: id 0x0177 (assigned), version 1, CRC ok
  OTA header: blank (no pending update)
  reserved sector: blank
  internal reset jump: ljmp 0x021B
```

A page takes a few seconds, so a whole 128 KiB chip is a coffee break; the default
range is everything the firmware writes.

## Flashing a build

```
python ShelfKit-Firmware/Tooling/axsem-flasher.py Release/vusion-full-latest.hex -p COM7
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
