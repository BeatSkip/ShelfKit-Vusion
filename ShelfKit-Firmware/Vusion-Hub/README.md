# Vusion-Hub — the hub target

The hub half of ShelfKit: it listens permanently, **answers every tag poll** (the answer *is* the
acknowledgement), and **forwards images from the host to the tag that just spoke**. Everything the
host knows about the fleet arrives on this board's UART.

Same board as [`../Vusion`](../Vusion) — SES-imagotag Vusion 2.6", AX8052F143 + GDEW026Z39 — but
wired to a PC by serial cable instead of running on a shelf. It keeps the e-paper driver so the hub
can show something itself later; it can also show an image the host sends over serial (below).

## What it does

```
radio: always in receive
  POLL  from a tag ──► POLL_RSP (carries the hub's RSSI) ──► tag treats it as the ACK
      and logs: POLL src=<addr> seq=… rssi=… up=…s att=… hubrssi=…
  DATA  from the host (over UART) ──► reliable DATA frames to that address, one chunk at a time
      and logs: SENT <addr> ok|fail att=N
```

- **`src/main.c`** — the radio loop plus the **host command channel** on UART0 (115200 8N1), one hex
  line per command: `P` → `PONG`; `S<addr:4><payload><chk:2>` → send one reliable frame and answer
  `SENT <addr> ok|fail att=N`; `B…` → the same for up to 16 frames in one line (the hub sends them back
  to back); `Q<id>` → **pre-arm** that tag, so its next poll reply says "data follows" and the tag keeps
  listening; `L<hh>` → ask every tag to wait `hh*10` s; `D…` → draw on the hub's own panel (below). The
  reply goes out before anything is logged, because the tag only waits `SL_RSP_TIMEOUT_MS`. The boot
  banner (`*** ShelfKit hub, node 0001 net 5a dump=1 batch=1 show=1`) advertises what this build can do:
  `dump` relays a tag's flash read-back payloads, `batch` accepts `B` lines, `show` accepts `D`.
- **`src/img_rx.c`** — the hub's copy of the image receiver, fed by `D` lines instead of the radio.
- **`src/epd.c`**, **`src/spi.c`**, **`src/flash.c`**, **`src/pwr.c`**, **`src/board.c`** — the panel
  driver and hardware helpers, shared in spirit with the tag (same hardware pin map).
- The `POLL src=…` line is the whole fleet view: the server parses it, and every tag that ever
  announced itself appears in the Fleet table.

The protocol, the frame format, the retry rules and the exact log lines are in
[Documentation/wireless-link.md](../../Documentation/wireless-link.md).

## Configuration — `include/shelf_config.h`

| Setting | Meaning |
|---|---|
| `SHELF_NODE_ID` | Must stay `SL_NODE_HUB` (`0x0001`) — tags address the hub, not a node id |
| `SHELF_NET_ID` | Network id, must match every tag in the fleet (`0x5A`) |
| `SHELF_POWER_LINES` | Hold the panel supply (U4, PA5) on from boot. Not a radio setting; leave off. PA2 (U5) is always parked low |

## Building and flashing

Open **this folder** in VS Code (not the repo root) so the extension finds `sdcc-project.json`, then
**Ctrl+Shift+B**; output lands in `build/`. *SDCC: Flash* invokes `../Tooling/axsem-flasher.py`
with the hex and your `comPort` setting.

```
python ../Tooling/axsem-flasher.py build/firmware.hex -p COM7
```

By hand, from this folder:

```powershell
$flags = @('-mmcs51','--model-small','--iram-size','256','--xram-size','8192','--code-size','59389')
& 'C:\Program Files\SDCC\bin\sdcc.exe' @flags '-Iinclude' '-I../Shared/sdk/libmf/include' '-I../Shared/firmware/axradio/inc' '-I../Shared/firmware/shelfhw/inc' '-I../Shared/firmware/shelflink/inc' 'src/main.c' -c -o build/main.rel
# … the rest of src/*.c, then link with ../Shared/lib/*.lib
```

The current release build is about 30.8 KB of code and 4.9 KB of XRAM (most of it the 2 KB host receive
ring and the batch line buffer) out of the 59,389 B / 8,192 B the memory model allows; internal RAM is
tight, with roughly 137 B of stack left.

## Talking to it from the host

The server does this for you ([`../../ShelfKit-Server`](../../ShelfKit-Server)); by hand:

```
python ../../ShelfKit-Server/shelfkit/hubhost.py COM4 ping              # expect PONG
python ../../ShelfKit-Server/shelfkit/hubhost.py COM4 send 0100 pic.png # push one image
python ../../ShelfKit-Server/shelfkit/hubhost.py COM4 serve images/     # push new images as tags announce
```

## Notes that cost real time

- **DTR/RTS are not what the docs say on every adapter.** On this board a *released* DTR at reset
  starts the application and an *asserted* one starts the AX8052 serial bootloader — the flasher
  asserts DTR to flash, which is why it works while the reset recipe in the vendor notes fails. The
  server learns the polarity instead of assuming it (`Reset` in the Hub screen's port pane).
- **An RTS glitch is a reset pulse.** Opening a serial port re-applies the modem lines, so the server
  opens the port once and pushes images over it, rather than reopening per transfer.
- UART0 RX is PB5, which is also the panel reset line — the hub's panel is not touched while the
  command channel is in use, and the pin conflict is the reason.
- A full raw image is 404 DATA frames of 28 payload bytes (a compressed label is ~30); the transfer is
  reliable per frame, so a slow link shows up as `att=N` on individual frames, not as a corrupted panel.

## Showing an image on the hub's own panel

`D<msg><chk:2>` carries the same `SM_OP_IMG_BEGIN/CHUNK/END` messages a tag receives over
the air, and feeds them to the tag's `img_rx.c` (copied here with `epd.c`). The hub answers
`OK img` per message; `END` answers only after the refresh (~15 s), during which the hub
keeps its radio but the host must not send. Chunks can be up to 128 bytes. The banner
advertises it as `show=1`.

```
python ../../ShelfKit-Server/shelfkit/hubhost.py COM4 show pic.png
python ../../ShelfKit-Server/shelfkit/hubhost.py COM4 stats       # CPU/RAM/disk of this PC
```

**PB5 is both the panel's RST and the serial RX.** With `HUB_EPD_RST_PULSE 0` (default,
`include/shelf_config.h`) the hub never drives PB5 and resets the panel by cycling its supply
rail, but while the trace is connected every byte the host sends is still a reset pulse on
the panel. If the picture is garbled or stops half way, cut the trace between PB5 and the
panel's RST pin: the rail cycle is then the only reset.

## The serial link is the fragile part

Host commands arrive on UART0 RX (PB5) and the radio log goes out on UART0 TX (PB4), at
115200 baud. The AX8052's UART has a **one byte** receive buffer, and the hub prints a
`SENT` line for every frame of an image push - so a command that arrived while a line
was printing lost bytes and came back as `ERR chk` / `ERR len`. That is what stalled a
push when another tag polled at the same moment.

`log_putc()` now collects receive bytes while it waits for the transmitter, into a 64
byte ring that `host_rx_getc()` drains first. Keep that in mind when adding logging: the
more the hub says per frame, the less headroom there is for the host's next command.
