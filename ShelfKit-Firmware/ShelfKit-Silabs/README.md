# ShelfKit-Silabs — tag firmware for Silicon Labs EFR32FG22 tags (skeleton)

**Status: a buildable skeleton.** A vector table, a reset handler, the shared ShelfLink
frame code and a main loop: no clocks, GPIO, radio, panel, flash, sleep or OTA yet. No tag
model has been chosen, so the pins in [`include/board.h`](include/board.h) are placeholders
marked `TODO(board)`.

## The chip

The **EFR32FG22** (Flex Gecko, series 2): an Arm Cortex-M33 at up to 76.8 MHz with a
2.4 GHz radio. The project assumes the **EFR32FG22C224F512** (512 KB flash, 32 KB RAM); for
another part change the memory sizes in [`linker/efr32fg22.ld`](linker/efr32fg22.ld) and
`flash_size` / `ram_size` in [`gcc-project.json`](gcc-project.json).

## It needs its own hub

The Axsem tags talk sub-GHz (AX5043); the FG22 talks **2.4 GHz**. CC2510 and FG22 tags are
both 2.4 GHz, but they share a hub only if both use the same modulation, rate and frame
format, which is not decided yet. There is no hub project for this family yet.

## Build

It needs the **Arm GNU Toolchain** (`arm-none-eabi-gcc`), which SDCC does not cover.
`build-all.py` looks on `PATH`, then in the default Arm GNU Toolchain and Simplicity Studio
install folders, and stops with an install hint when it finds none:

```
winget install Arm.GnuArmEmbeddedToolchain
python ShelfKit-Firmware/Tooling/build-all.py --targets silabs --no-record
```

That writes `Release/shelfkit-silabs-latest.hex` and its `.map`. The project is described in
`gcc-project.json` (not `sdcc-project.json`): sources and includes as in the SDCC projects,
plus `cflags`, `ldflags` and the linker script. The `SKFW` version marker
([`src/fwinfo.c`](src/fwinfo.c)) sits in its own `.fwinfo` section, kept by the linker script.

## What is shared

- `Shared/firmware/shelflink/sl_proto.c`: frame build/parse and the duplicate filter.
- `shelflink.h`, `shelfmsg.h` (message layouts) and `shelfver.h` (version marker).

The shared headers use SDCC's 8051 keywords (`__xdata`, `__code`);
[`include/libmftypes.h`](include/libmftypes.h) defines them away for the Cortex-M.

## Flashing

Over SWD with a J-Link (Simplicity Commander: `commander flash shelfkit-silabs-latest.hex`)
or any CMSIS-DAP probe with OpenOCD/pyOCD. No ShelfKit bootloader for it yet; Silicon Labs'
Gecko bootloader is the obvious base for OTA later.

## Next steps

1. Pick the tag model; fill in `board.h` from the real board.
2. Bring in the Gecko SDK (emlib for CMU/GPIO/USART, RAIL for the radio) and its startup file.
3. Radio driver matching a 2.4 GHz hub, then the poll loop from `ShelfKit-Axsem/src/main.c`.
4. Panel driver, EM2 sleep with the BURTC, SPI flash, ID record, bootloader.
