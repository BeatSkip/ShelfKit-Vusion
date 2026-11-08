# ShelfKit-Firmware — one SDCC-MDF project per board

The firmware that runs on the boards. Every target here is a **self-contained SDCC-MDF project**:
its own `src/`, `include/`, `sdcc-project.json` and `.vscode/`, built with SDCC for the AX8052F143
through the [SDCC-MDF extension](https://marketplace.visualstudio.com/items?itemName=dzantemir.sdcc-mdf).
The shared amount of code — the Axsem SDK, the radio layer, the shelf protocol, the hardware helpers,
the board definition — lives once in [`Shared/`](Shared) and is reached by relative path, so a
new target adds a project without copying 140 MB of vendor code.

| Folder | Target | What it does |
|---|---|---|
| `Vusion/` | Tag | Polls the hub every couple of minutes (adaptive), receives an image (raw or compressed) straight into the panel controller, refreshes, sleeps; takes OTA firmware updates and a wireless id |
| `Vusion-Hub/` | Hub | Always listening, answers every poll, relays host frames (single and batched) to the tag that just spoke, can draw on its own panel, speaks a line protocol on UART at 115200 |
| `Tooling/` | Host scripts | The flasher, `build-all.py` (every target into `Release/`), the OTA sender, `set-id.py` and `flash-read.py` (see [Tooling/README.md](Tooling/README.md)) |
| `Bootloader/` | AX8052 serial bootloader | Flash-resident UART bootloader (Axsem V1.1, 38400 baud, at `0xD800`) that erases and programs the application area and jumps to it, and applies an over-the-air image staged in the tag's SPI flash |

Vusion is the SES-imagotag 2.6" BWR label (UU340 variant): AX8052F143 — an 8051 core plus a
sub-GHz radio at 26 MHz — a Good Display **GDEW026Z39** panel (296×152, black/white/red, IL0373),
an NFC chip and a serial flash. `Vusion/` and `Vusion-Hub/` run on identical hardware; they differ
in their `src/main.c` and their `include/shelf_config.h`; the tag adds the OTA, identity and
compressed-image receivers, the hub keeps a smaller image receiver for its own panel.

## Building one target

**Open the target folder itself, not this folder and not the repo root.** The extension activates on
a `sdcc-project.json` in the workspace folder, and the `../Shared/…` paths are resolved against
that folder as the project root.

1. `File ▸ Open Folder…` → `ShelfKit-Firmware/Vusion-Hub` (or `Vusion`).
2. **Ctrl+Shift+B** — `firmware.ihx`, `.hex`, `.map` and `.mem` land in that target's `build/`.
3. *SDCC: Flash* runs the `upload` command from `sdcc-project.json`, which is
   [`Tooling/axsem-flasher.py`](Tooling/axsem-flasher.py) — it wants the serial port in the
   workspace setting `comPort` (see [Tooling/README.md](Tooling/README.md)).

The three files that wire a target to the shared tree, and what they must say from inside
`ShelfKit-Firmware/<target>/`:

| File | Entries |
|---|---|
| `sdcc-project.json` | `sources`/`includes` with `../Shared/firmware/…` and `../Shared/sdk/…`, `libraries: ["../Shared/lib"]`, `components: ["../Shared/components"]`, `upload` args `../Tooling/axsem-flasher.py` |
| `.vscode/settings.json` | `"sdcc.boardsDir": "../Shared/boards"` — scanned as a `custom` board source; the board id `axsem-8052f143` comes from that board JSON's `build.mcu` |
| `.vscode/c_cpp_properties.json` | `${workspaceFolder}/../Shared/sdk/libmf/include` for IntelliSense |

If you move a target deeper, every one of those grows one `../`. The extension deliberately keeps
paths outside the project root absolute on the tool command line (paths inside it become relative),
so no symlinks or junctions are involved.

## Adding another tag type

The point of this folder. A new tag is a new project beside `Vusion/`, sharing everything that is
not board-specific:

1. **Copy an existing target**: `Vusion/` for another tag, `Vusion-Hub/` for a second hub.
2. **Rename it** in `sdcc-project.json`: `name`, and `build.output_name` if you want a distinct hex
   (default `firmware`).
3. **Give it an identity** in `include/shelf_config.h`: the fleet-wide `SHELF_NET_ID` and its own
   `SHELF_POLL_INTERVAL_S` (watch the 1 % duty cycle of the 868.3 MHz
   sub-band). The hub must keep `SL_NODE_HUB`; a tag's own node id is generated on first boot and stored in its
   SPI flash (see [tag-identity.md](../Documentation/tag-identity.md)), not set here.
4. **Choose the panel.** `src/epd.c` is the GDEW026Z39 driver: geometry in `epd.h` (`EPD_W`,
   `EPD_H`, `EPD_PLANE_BYTES`), the init sequence and the BUSY handling in `epd.c`. For a different
   panel, add the driver to `Shared/firmware/` — that is where code earns its place once a second
   target needs it — and leave `src/epd.c` as thin wiring. A mono panel has no red plane, so the
   receiving path (`src/img_rx.c`), the wire format (two planes today) and the hub's frame count have
   to agree; the clean way is a capability byte in the poll.
5. **Choose the board**, if the MCU is not an AX8052F143: add a board JSON to `Shared/boards/` and
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
- Board definitions are cached by the extension; after editing `Shared/boards/…`, reload the window.
- `build/` is git-ignored and is regenerated; it is safe to delete when paths move under it.
- Each target's README covers that target's drivers, logs and quirks; the shared code has
  [Shared/README.md](Shared/README.md).
