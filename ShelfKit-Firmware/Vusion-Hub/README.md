# Vusion-Hub — the hub target

The hub half of ShelfKit: it listens permanently, **answers every tag poll** (the answer *is* the
acknowledgement), and **forwards images from the host to the tag that just spoke**. Everything the
host knows about the fleet arrives on this board's UART.

Same board as [`../Vusion`](../Vusion) — SES-imagotag Vusion 2.6", AX8052F143 + GDEW026Z39 — but
wired to a PC by serial cable instead of running on a shelf. It keeps the e-paper driver so the hub
can show something itself later; it does not receive images.

## What it does

```
radio: always in receive
  POLL  from a tag ──► POLL_RSP (carries the hub's RSSI) ──► tag treats it as the ACK
      and logs: POLL src=<addr> seq=… rssi=… up=…s att=… hubrssi=…
  DATA  from the host (over UART) ──► reliable DATA frames to that address, one chunk at a time
      and logs: SENT <addr> ok|fail att=N
```

- **`src/main.c`** — the radio loop plus the **host command channel** on UART0 (38400 8N1):
  `P` → `PONG` (are you there?), `S<addr:4><payload><chk:2>` → send one reliable frame and answer
  `SENT <addr> ok|fail att=N`. The reply goes out before anything is logged, because the tag only
  waits `SL_RSP_TIMEOUT_MS`.
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
| `SHELF_POWER_LINES` | Drive the unidentified PA2/PA5 lines before the radio starts; left off |

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

The build prints the memory report: 37,675 B of code and 1,130 B of XRAM out of the 59,389 B / 8,192 B
the memory model allows, which leaves 137 B of stack.

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
  server learns the polarity instead of assuming it (`Reset` in the Console pane).
- **An RTS glitch is a reset pulse.** Opening a serial port re-applies the modem lines, so the server
  opens the port once and pushes images over it, rather than reopening per transfer.
- UART0 RX is PB5, which is also the panel reset line — the hub's panel is not touched while the
  command channel is in use, and the pin conflict is the reason.
- A full image is 404 DATA frames of 28 payload bytes; the transfer is reliable per frame, so a slow
  link shows up as `att=N` on individual frames, not as a corrupted panel.
