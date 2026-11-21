# solum/label — label firmware for Solum ZBS243 labels (skeleton)

**Status: a buildable skeleton.** It compiles and links, and nothing more is promised: no
clock setup, no radio, no panel, no flash, no sleep, no OTA yet. No label model has been
chosen, so the pins in [`include/board.h`](include/board.h) are placeholders marked
`TODO(board)`.

## The chip

The **ZBS243** (Samsung, used in SoluM / Solum labels, also sold as SEM9110): an 8051 core
with a 2.4 GHz IEEE 802.15.4 radio, 64 KB flash, a 1 KB info page and 256 B IRAM + 8 KB RAM.
Being an 8051, it builds with the same **SDCC** as the Axsem firmware; its board file is
[`boards/zbs243.json`](../../boards/zbs243.json).

There is **no public datasheet**. Everything known about the chip comes from reverse
engineering (Dmitry Grinberg's work, which the OpenEPaperLink and openESL firmware build on).
So far only these facts are confirmed for this project; the rest is TODO:

| | Status |
|---|---|
| 8051 core, 64 KB flash, 256 B IRAM, 8 KB RAM | confirmed (ZBS_Flasher, openESL) |
| 2.4 GHz 802.15.4 radio | confirmed |
| Where the 8 KB of XRAM sits (`--xram-loc`) | **TODO(soc)**: the board file uses SDCC's default (0x0000) |
| Clock speed (`f_cpu` 16 MHz in the board file) | **TODO(soc)**: unverified; nothing reads it yet |
| Pin direction / function, clock, watchdog registers | **TODO(soc)**: not declared in [`include/zbs243.h`](include/zbs243.h) |

Take those from a verified source (the zbs243 headers and make files of OpenEPaperLink or
openESL) before writing a driver.

## It needs its own hub

The Axsem labels talk sub-GHz (AX5043); the ZBS243 talks **2.4 GHz 802.15.4**. The two cannot
hear each other, so Solum labels need a **2.4 GHz hub** (an 802.15.4 radio, e.g. an ESP32-C6
or another ZBS243, on the server's serial port, speaking the same ShelfLink frames). There is
no hub project for that yet.

## Build

```
python ShelfKit-Firmware/tooling/build-all.py --targets solum --no-record
```

writes `Release/shelfkit-solum-latest.hex` (only the Solum files in `Release/` are replaced).
The image carries the usual `SKFW` version marker ([`src/fwinfo.c`](src/fwinfo.c)).

## What is shared

- `common/shelflink/sl_proto.c`: frame build/parse and the duplicate filter.
- `shelflink.h`, `shelfmsg.h` (message layouts) and `shelfver.h` (version marker).

`shelflink.h` includes `<libmftypes.h>`, which is Axsem's libmf on the other targets;
[`include/libmftypes.h`](include/libmftypes.h) stands in for it here. The radio half of
shelflink (`shelflink.c`) is AX5043-specific and is not built.

## Flashing

The ZBS243 is programmed over its SPI-like debug interface, for example with atc1441's
ZBS_Flasher (an Arduino/ESP32 sketch plus a PC tool). There is no ShelfKit bootloader for it
yet, so there is no OTA and no serial update path. Back up the stock firmware and the info
page before the first flash: the info page holds the label's factory data.

## Next steps

1. Pick the label model; fill in `board.h` from the real board.
2. Verify and declare the SoC registers (clock, GPIO, watchdog, SPI, radio) in `zbs243.h`,
   and the XRAM location in the board file.
3. Radio driver (802.15.4, matching a 2.4 GHz hub), then the poll loop from
   `axsem/label/src/main.c`.
4. Panel driver for the label's display controller, the SPI flash, sleep, the ID record and a
   bootloader.
