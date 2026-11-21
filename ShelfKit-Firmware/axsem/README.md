# axsem/ — the AX8052F143 platform

The label, hub and bootloader for the AX8052F143 (an 8051 with the AX5043 sub-GHz radio), plus
everything they share. Each target references the shared folders by relative path (`../shared/…`,
`../sdk/…`) from its own `sdcc-project.json` and `.vscode/settings.json`, so the repository holds
exactly one copy. Before this layout existed, the two firmware targets each carried an identical
142 MB copy of it (810 files each, verified byte-for-byte identical).

| Folder | Reached through | Contents |
|---|---|---|
| `label/`, `hub/`, `bootloader/` | — | The three targets, each with its own README |
| `shared/` | `sources`/`includes` in `sdcc-project.json` | The Axsem-only modules: `axradio` (the AX5043 engine), `shelfhw` (board bring-up), `shelflink` (`shelflink.c`, the radio side of the link), `shelfota` (OTA staging) and `shelfid` (the label's identity). The frame format itself is in `../common/shelflink` |
| `sdk/` | `includes` in `sdcc-project.json` | Full Axsem SDK source tree (759 files): `libmf`, `libaxdvk2`, `libax5042`, `libaxdsp`, `libmfcrypto`, each with its IAR/Keil/ARM/SDCC makefiles, headers and sources |
| `lib/` | `libraries` in `sdcc-project.json` | Prebuilt SDCC archives, linked as-is: `libmf.lib`, `libaxdvk2.lib`, `libaxdsp.lib`, `libmfcrypto.lib` |
| `boards/` | `sdcc.boardsDir` in `.vscode/settings.json` | `axsem-8051.json` — the SDCC-MDF board definition. Id `axsem-8052f143` (from `build.mcu`), 26 MHz, 256 B IRAM, 8 KB XRAM, 59389 B code, `--model-small` |
| `components/` | `components` in `sdcc-project.json` | Source components (ESP8266-IDF pattern). Empty apart from its README; each subfolder becomes one source library |

Only `sdk/libmf/include` and `sdk/libaxdvk2/include` are actually on the compiler's include path.
The rest of the SDK is kept as the vendor reference the drivers were written from, and because
`lib/` is built from it.

## Two things to know

- `boards/` used to live in each target's own `.sdcc/boards/` folder. The extension scans
  `sdcc.boardsDir` as a `custom` source and caches the result, so **reload the VS Code window**
  after editing `boards/axsem-8051.json`.
- The extension accepts a relative `sdcc.boardsDir` and resolves it against the active project
  root. If a target's `.vscode/settings.json` is missing (or the target is opened as part of a
  multi-root workspace), the board will not be found and the build will fail with an unknown
  board — keep `"sdcc.boardsDir": "../boards"` in place.

## Changing the SDK

`lib/*.lib` are prebuilt; the build links them and does not recompile `sdk/`. To rebuild an
archive after patching the SDK sources, use the vendor makefiles, e.g.
`sdk/libmf/buildsdcc/Makefile`, and drop the result into `lib/`.
