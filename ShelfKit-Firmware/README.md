# ShelfKit-Firmware — one folder per chip platform

The firmware that runs on the boards, grouped by chip platform, because each platform has its own
toolchain, vendor code and radio (a hub can only talk to labels with the same radio):

```
ShelfKit-Firmware/
  axsem/                 AX8052F143 (8051 + AX5043 sub-GHz radio), SDCC
    label/               the shelf label firmware
    hub/                 the hub firmware
    bootloader/          serial + OTA bootloader at 0xD800
    shared/              axradio, shelfhw, shelflink (radio side), shelfota, shelfid
    sdk/  lib/           the Axsem SDK sources and its prebuilt .lib archives
  texas/                 TI CC2510 (8051 + 2.4 GHz radio), SDCC
    label/
  silabs/                Silicon Labs EFR32FG22 (Cortex-M33 + 2.4 GHz radio), Arm GCC
    label/
  common/                code every platform compiles
    shelflink/           the ShelfLink frame format: sl_proto.c, shelflink.h, shelfmsg.h, shelfver.h
  tooling/               build-all.py, the flasher, OTA sender, set-id, flash-read
  version.json  build-log.md
```

Every target is a **self-contained project**: its own `src/`, `include/` and `sdcc-project.json`
(or `gcc-project.json` for the Arm one), and for the SDCC targets a `.vscode/` for the
[SDCC-MDF extension](https://marketplace.visualstudio.com/items?itemName=dzantemir.sdcc-mdf),
which also holds the board definition (`.vscode/boards/*.json`).
Everything else is reached by relative path, so a new target adds a project without copying
140 MB of vendor code. See [axsem/README.md](axsem/README.md) for the Axsem SDK and shared code.

| Folder | Target | What it does |
|---|---|---|
| `axsem/label/` | Label | Polls the hub every couple of minutes (adaptive), receives an image (raw or compressed) straight into the panel controller, refreshes, sleeps; takes OTA firmware updates and a wireless id |
| `axsem/hub/` | Hub | Always listening, answers every poll, relays host frames (single and batched) to the tag that just spoke, can draw on its own panel, speaks a line protocol on UART at 115200 |
| `texas/label/` | Label (skeleton) | TI **CC2510** tags (8051 + 2.4 GHz radio), SDCC. Builds; no radio or panel driver yet, placeholder pins. Needs a 2.4 GHz hub of its own — see [its README](texas/label/README.md) |
| `silabs/label/` | Label (skeleton) | Silicon Labs **EFR32FG22** tags (Cortex-M33 + 2.4 GHz radio), Arm GCC (`gcc-project.json`). Builds once `arm-none-eabi-gcc` is installed; no drivers yet, placeholder pins. Needs a 2.4 GHz hub — see [its README](silabs/label/README.md) |
| `tooling/` | Host scripts | The flasher, `build-all.py` (every target into `Release/`), the OTA sender, `set-id.py` and `flash-read.py` (see [tooling/README.md](tooling/README.md)) |
| `axsem/bootloader/` | AX8052 serial bootloader | Flash-resident UART bootloader (Axsem V1.1, 38400 baud, at `0xD800`) that erases and programs the application area and jumps to it, and applies an over-the-air image staged in the tag's SPI flash |

axsem/label runs on the SES-imagotag Vusion 2.6" BWR label (UU340 variant): AX8052F143 — an 8051 core plus a
sub-GHz radio at 26 MHz — a Good Display **GDEW026Z39** panel (296×152, black/white/red, IL0373),
an NFC chip and a serial flash. `axsem/label/` and `axsem/hub/` run on identical hardware; they differ
in their `src/main.c` and their `include/shelf_config.h`; the tag adds the OTA, identity and
compressed-image receivers, the hub keeps a smaller image receiver for its own panel.

## Building one target

**Open the target folder itself, not this folder and not the repo root.** The extension activates on
a `sdcc-project.json` in the workspace folder, and the `../shared/…`, `../sdk/…` and
`../../common/…` paths are resolved against that folder as the project root.

1. `File ▸ Open Folder…` → `ShelfKit-Firmware/axsem/hub` (or `axsem/label`).
2. **Ctrl+Shift+B** — `firmware.ihx`, `.hex`, `.map` and `.mem` land in that target's `build/`.
3. *SDCC: Flash* runs the `upload` command from `sdcc-project.json`, which is
   [`tooling/axsem-flasher.py`](tooling/axsem-flasher.py) — it wants the serial port in the
   workspace setting `comPort` (see [tooling/README.md](tooling/README.md)).

The three files that wire an Axsem target to the shared tree, and what they must say from inside
`ShelfKit-Firmware/axsem/<target>/`:

| File | Entries |
|---|---|
| `sdcc-project.json` | `sources`/`includes` with `../shared/…`, `../sdk/…` and `../../common/shelflink`, `libraries: ["../lib"]`, `upload` args `../../tooling/axsem-flasher.py` |
| `.vscode/settings.json` | `"sdcc.boardsDir": ".vscode/boards"` — scanned as a `custom` board source; the board id `axsem-8052f143` comes from that board JSON's `build.mcu` |
| `.vscode/boards/axsem-8051.json` | The board definition: 26 MHz, 256 B IRAM, 8 KB XRAM, 59389 B code, `--model-small`. The extension cannot take a board inline in `sdcc-project.json` and would read every other JSON in `.vscode/` as a board, hence the subfolder. Each project has its own copy; `build-all.py` stops if the copies differ, so edit all three |
| `.vscode/c_cpp_properties.json` | `${workspaceFolder}/../sdk/libmf/include` and the shared `inc/` folders for IntelliSense |

If you move a target deeper, every one of those grows one `../`. The extension deliberately keeps
paths outside the project root absolute on the tool command line (paths inside it become relative),
so no symlinks or junctions are involved.

## Adding another label type

A new label on an existing platform is a new project beside `axsem/label/` (for example
`axsem/label-4in2/`), sharing everything that is not board-specific. A new chip platform is a new
top-level folder like `texas/`, with its own `label/` (and later `hub/`) and `shared/`;
only `common/` and `tooling/` are shared across platforms.

1. **Copy an existing target**: `axsem/label/` for another label, `axsem/hub/` for a second hub.
2. **Rename it** in `sdcc-project.json`: `name`, and `build.output_name` if you want a distinct hex
   (default `firmware`).
3. **Give it an identity** in `include/shelf_config.h`: the fleet-wide `SHELF_NET_ID` and its own
   `SHELF_POLL_INTERVAL_S` (watch the 1 % duty cycle of the 868.3 MHz
   sub-band). The hub must keep `SL_NODE_HUB`; a tag's own node id is generated on first boot and stored in its
   SPI flash (see [tag-identity.md](../Documentation/tag-identity.md)), not set here.
4. **Choose the panel.** `src/epd.c` is the GDEW026Z39 driver: geometry in `epd.h` (`EPD_W`,
   `EPD_H`, `EPD_PLANE_BYTES`), the init sequence and the BUSY handling in `epd.c`. For a different
   panel, add the driver to `axsem/shared/` — that is where code earns its place once a second
   target needs it — and leave `src/epd.c` as thin wiring. A mono panel has no red plane, so the
   receiving path (`src/img_rx.c`), the wire format (two planes today) and the hub's frame count have
   to agree; the clean way is a capability byte in the poll.
5. **Choose the board**, if the MCU is not an AX8052F143: add a board JSON to the project's `.vscode/boards/` and
   point `board` in `sdcc-project.json` at its `build.mcu`.
6. **Keep the protocol.** Any tag must speak the same POLL / POLL_RSP / DATA / ACK frames
   ([Documentation/wireless-link.md](../Documentation/wireless-link.md)); the hub and the server only
   know about addresses and frames, not about panel types.
7. **Mind the memory.** `--model-small`, 256 B IRAM, 8 KB XRAM, 59389 B code. SDCC leaves no spare
   internal RAM, so buffers go in `__xdata`; a full 152×296 BWR frame is 2 × 5624 B and cannot be
   held whole — the current design streams it.

## Toolchain and notes

- [SDCC](https://sdcc.sourceforge.net/) 3.6.0, on `PATH` as `sdcc`; the extension was verified against
  0.29.17.
- `"sdcc.shellPath": "cmd.exe"` in each target's `.vscode/settings.json` works around the extension's
  single-quoted tool paths, which PowerShell cannot call without `&`. After changing it, reload the
  VS Code window — the extension reuses its build terminal.
- Board definitions are cached by the extension; after editing a `.vscode/boards/…` file, reload the window.
- `build/` is git-ignored and is regenerated; it is safe to delete when paths move under it.
- Each target's README covers that target's drivers, logs and quirks; the Axsem SDK and shared
  code have [axsem/README.md](axsem/README.md).
- The layout moved on 2026-11-21 (`ShelfKit-Axsem` → `axsem/label`, `ShelfKit-Axsem-Hub` →
  `axsem/hub`, `Bootloader` → `axsem/bootloader`, `Shared/` split into `axsem/` and `common/`,
  `Tooling` → `tooling`). The release file names did not change.
