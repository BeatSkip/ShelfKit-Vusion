# texas/label — tag firmware for TI CC2510 tags (skeleton)

**Status: a buildable skeleton.** It compiles and links, and nothing more is promised: no
radio, no panel, no flash, no sleep, no OTA yet. No tag model has been chosen, so the pins
in [`include/board.h`](include/board.h) are placeholders marked `TODO(board)`.

## The chip

The **TI CC2510F32**: an 8051 core with a 2.4 GHz transceiver, 32 KB flash and 4 KB RAM
(mapped as XDATA at `0xF000`). Being an 8051, it builds with the same **SDCC** as the
Axsem firmware; its board file is [`../texas/boards/ti-cc2510f32.json`](../boards/ti-cc2510f32.json).

## It needs its own hub

The Axsem tags talk sub-GHz (AX5043); the CC2510 talks **2.4 GHz**. The two cannot hear
each other, so CC2510 tags need a **2.4 GHz hub** (a CC2510/CC2511 board on the server's
serial port, speaking the same ShelfLink frames). There is no hub project for that yet.

## Build

```
python ShelfKit-Firmware/tooling/build-all.py --targets texas --no-record
```

writes `Release/shelfkit-texas-latest.hex` (only the Texas files in `Release/` are
replaced). The image carries the usual `SKFW` version marker ([`src/fwinfo.c`](src/fwinfo.c)).

## What is shared

- `common/shelflink/sl_proto.c`: frame build/parse and the duplicate filter.
- `shelflink.h`, `shelfmsg.h` (message layouts) and `shelfver.h` (version marker).

`shelflink.h` includes `<libmftypes.h>`, which is Axsem's libmf on the other targets;
[`include/libmftypes.h`](include/libmftypes.h) stands in for it here. The radio half of
shelflink (`shelflink.c`) is AX5043-specific and is not built.

## Flashing

The CC2510 is programmed over TI's two-wire debug interface (DC/DD + RESET_N) with a
CC Debugger and SmartRF Flash Programmer, or `cc-tool`. There is no ShelfKit bootloader
for it yet, so there is no OTA and no serial update path.

## Next steps

1. Pick the tag model; fill in `board.h` from the real board.
2. Radio driver (2.4 GHz, matching a hub), then the poll loop from `axsem/label/src/main.c`.
3. Panel driver for the tag's display controller.
4. Sleep (PM2 with the sleep timer), the SPI flash, the ID record, a bootloader.
