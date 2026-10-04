# ShelfKit — AX8052F143 e-paper shelf label

Monorepo skeleton for two firmware targets for the **SES-imagotag Vusion 2.6" BWR shelf label**
(UU340 variant): an **Axsem AX8052F143** (8051 core plus a 2.4 GHz radio, 26 MHz crystal) driving
a **Good Display GDEW026Z39** e-paper panel (296×152, black/white/red, IL0373 controller), an NFC
chip and a serial flash. Built with **SDCC** and the **SDCC-MDF** VS Code extension.

Two targets over one shared vendor tree:

| Folder | What it is |
|---|---|
| `Shelfkit-Hub/` | A self-contained SDCC-MDF project: own `src/`, `sdcc-project.json`, `.vscode/` |
| `Shelfkit-Vusion/` | Same layout, currently building the same firmware |
| `shared/` | Everything both targets use — Axsem SDK, prebuilt libraries, board definition, datasheets |
| `tooling/` | Host-side Python scripts and the parked flash-dump firmware |

> The two targets are currently **byte-for-byte identical**. They exist so they can diverge; the
> first file you will change is each target's `src/main.c`.

## Requirements

- [SDCC](https://sdcc.sourceforge.net/) — the build below was verified against the 3.6.0 install
  at `C:\Program Files\SDCC`, already on `PATH` as `sdcc`.
- VS Code with the
  [SDCC-MDF extension](https://marketplace.visualstudio.com/items?itemName=dzantemir.sdcc-mdf)
  (`dzantemir.sdcc-mdf`, verified against 0.29.17).
- For the host scripts: Python 3 with `pyserial` (`flashdump.py`, `axsem-flasher.py`) and
  `Pillow` (`png2epd.py`).

## Building a target

**Open the target folder itself, not this root.** The SDCC-MDF extension activates on a
`sdcc-project.json` in the workspace folder, and the `../shared/…` paths are resolved against
that folder as the project root.

1. `File ▸ Open Folder…` → `Shelfkit-Hub` (or `Shelfkit-Vusion`).
2. **Ctrl+Shift+B** (*SDCC: Build*). Output lands in that target's `build/`: `firmware.ihx`,
   `firmware.hex`, `firmware.map`, `firmware.mem`.
3. *SDCC: Flash* still runs the original placeholder — see [tooling/README.md](tooling/README.md)
   for the one-edit recipe that wires up the real flasher.

Verified build (SDCC 3.6.0, identical for both targets):

```
Other memory:
   Name             Start    End      Size     Max
   ---------------- -------- -------- -------- --------
   PAGED EXT. RAM                         0      256
   EXTERNAL RAM     0x0001   0x0192     402     8192
   ROM/EPROM/FLASH  0x0000   0x4665   18022    59389
Stack starts at: 0x57 (sp set to 0x56) with 169 bytes available.
```

## How the targets reach the shared tree

Plain relative paths, so a clone works from anywhere:

| File | Entry |
|---|---|
| `<target>/sdcc-project.json` | `includes: ["include", "../shared/sdk/libmf/include", "../shared/sdk/libaxdvk2/include"]`, `libraries: ["../shared/lib"]`, `components: ["../shared/components"]` |
| `<target>/.vscode/settings.json` | `"sdcc.boardsDir": "../shared/boards"` — scanned as a `custom` board source; the board id `axsem-8052f143` is taken from the board JSON's `build.mcu` |
| `<target>/.vscode/c_cpp_properties.json` | `"${workspaceFolder}/../shared/sdk/libmf/include"` for IntelliSense |

The extension resolves every one of these with `path.resolve(projectRoot, …)`, and it deliberately
keeps paths outside the project root absolute on the tool command line (while paths inside it
become relative). So the shared tree needs no symlinks, junctions or copies.

## Notes

- Nothing here is under version control yet. Each target's `.gitignore` covers `build/` and the
  SDCC intermediates; `shared/` and `tooling/` are content you would commit as well.
- `shared/lib/*.lib` are SDCC archives built from `shared/sdk/` with the vendor's `buildsdcc`
  makefiles. All four are passed to the linker; only `libmf` is referenced by the code so far.
- Each target's `include/` is an empty placeholder that is already on the include path.
- License: the code in each `src/` has no license declared. The Axsem SDK under `shared/sdk/` and
  `shared/lib/` retains its original terms — compiler headers are GPL with a linking exception,
  the rest is vendor-licensed.
