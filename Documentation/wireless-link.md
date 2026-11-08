# Wireless link (868 MHz) — design, findings, status

Hub (`ShelfKit-Firmware/Vusion-Hub`) and tag (`ShelfKit-Firmware/Vusion`) run on identical hardware and share all radio code in
`ShelfKit-Firmware/Shared/firmware/`. This document records what was found, how the link works, what was verified on
hardware, and what is left.

## Status (2026-11-08)

The link has run on real boards since the first bring-up (hub and tag a few cm apart, RSSI −33…−38 dBm,
polls acknowledged on the first attempt), and since then carries everything the system does:

- **Polls** every 2 minutes by default, adaptive (30 s while the hub has data, 3 min cool-down, 5 min
  idle, 10 min on a weak link, then hourly / daily with no hub) — see the tag README.
- **Images**, raw (404 frames) or ECO-compressed (~30 frames), batched by the hub, to several tags with
  alternating transfers.
- **OTA firmware**, **id assignment**, **flash read-back** and **factory reset** over the same DATA path.
- Tags sleep (radio deep sleep + MCU sleep) between polls, so the hub is *pre-armed* (`Q<id>`) before a
  command: the poll reply then says "data follows" and the tag keeps its receiver open.

Still not measured: packet loss over a long run, range, and the effect of the PA2/PA5 transistor lines
on range. The tag's poll interval is no longer the ~5.6 s of the early bring-up (see [Timing](#timing)).

## Findings

| # | Finding |
|---|---|
| 1 | The AX8052F143 has the **sub-GHz AX5043** radio on-chip, not a 2.4 GHz radio (the old READMEs say 2.4 GHz — wrong). |
| 2 | The generated `WirelessDemo/` is one-way (ASYNC_TRANSMIT master, ASYNC_RECEIVE slave), button-triggered, no ACK, and written for the Axsem *Minikit* (LED lib, COM0 display, button on PC4, whole-port writes). Its pin setup would clobber the tag's EPD/NFC/flash pins, so only the radio engine and PHY config were reused. |
| 3 | PHY (from `config.c`): 868.300 MHz, FSK, 25 kHz deviation, 100 kbit/s, 15 dBm, 26 MHz crystal, sync word `CC AA CC AA`, 3-byte hardware-filtered address, hardware CRC-16. |
| 4 | **SDCC-MDF links component libraries *after* `libmf.lib`**, so a component that calls libmf would fail. Therefore the shared code is added as plain `sources` entries (`../Shared/firmware/<name>`) plus `includes`, not as `components`. |
| 5 | **`libmf.lib` as shipped makes the linker exit with status 1.** It was built with `--debug`, so 29 global debug labels (`C$libmftypes.h$351$4$73`, …) are defined by several modules. Any radio firmware links two of them → "Multiple definition", exit 1, which SDCC-MDF reports as a failed build (the `.ihx` is still written). Fixed once by renaming the repeats in place (same length, so archive offsets stayed valid); `ShelfKit-Firmware/Shared/lib/libmf.lib` is committed in patched form. If the library is ever rebuilt from `ShelfKit-Firmware/Shared/sdk/`, that rename has to be re-applied. |
| 6 | The same label clash also hit the engine itself (inline `enter_critical()` from `libmftypes.h`); `easyax5043.c` now has local static copies of those helpers. |
| 7 | SDCC 3.6.0: function pointers with several arguments must be `__reentrant`; the shelflink "done" callback therefore takes one struct pointer. |
| 8 | **Standby needs the wake-up-timer interrupt enabled.** `wtimer_idle(WTFLAG_CANSTANDBY)` enters standby with `EA = 0`; standby only ends if the wake source's enable bit is set in `IE`. The demo uses `IE_3` — that is Timer 1 on the AX8052, not the wake-up timer. The wake-up timer is vector 1 → **`IE_1`**. Without it the tag slept forever after its first poll. Fixed in `shelfhw_poll()` (the radio interrupt, `IE_4`, is enabled by the engine). |
| 9 | Pin/clock facts used: UART0 TX on PB4 at 115200 (needs the FRC oscillator slaved to the 32 kHz LPXOSC, sequence copied from the existing demo); PB5 (EPD reset / UART RX) is never driven; chip selects PA1/PB1/PC0 are parked high at boot. |
| 10 | Loading the debug firmware shows `rssi≈−35 dBm` at a few cm — the receiver is not saturated and reception is clean at this distance. |

## Architecture

```
ShelfKit-Firmware/Shared/firmware/
  axradio/    vendor radio engine (easyax5043.c, axradio.h) + PHY config (config.c) + axradio_platform.h glue
  shelfhw/    board bring-up, wake-up timers, LEDs, UART0 TX log (log_*), shelfhw_poll() main-loop step
  shelflink/  shelflink.c   acknowledged request/response state machine
              sl_proto.c    pure frame build/parse + duplicate filter (host-testable)
              shelfmsg.h    application payloads (POLL / POLL_RSP)
<target>/include/shelf_config.h   node id, network id, poll interval, SHELF_POWER_LINES
<target>/src/main.c               hub: listen + answer;  tag: periodic poll
```

Both projects list the three `ShelfKit-Firmware/Shared/firmware/*` folders under `sources` and their `inc/` folders under
`includes` in `sdcc-project.json` (and in `.vscode/c_cpp_properties.json` for IntelliSense).

### Radio mode

Both nodes stay in `AXRADIO_MODE_ASYNC_RECEIVE` permanently. Calling `axradio_transmit()` from that mode
makes the engine switch to TX and fall back to RX when the packet is out, so a node hears the reply to its
own transmission with no mode juggling. Cost: the receiver is always on (fine for the hub; the tag will need
a low-power scheme later).

### Frame

Engine frame: length byte, 3-byte address, payload, CRC-16 (hardware).

```
address (3)   dest node id lo, dest node id hi, network id        (hardware filtered, mask FF FF FF)
payload:
  [0]     version (high nibble, =1) | type (low nibble)
  [1]     flags            bit0 = retry
  [2..3]  source node id, little endian
  [4]     sequence number
  [5..]   data, 0..32 bytes
```

Types: `1 POLL`, `2 POLL_RSP`, `3 DATA`, `4 ACK`. Hub node id is `0x0001`; tags use `0x0100` and up.
Network id `0x5A` (both ends must match).

### Reliability

- Initiator (`sl_send`): transmit, open a 60 ms response window, if nothing matching arrives wait a random
  5 + (0…20·attempt) ms and retransmit (same sequence number, retry flag set), up to 4 transmissions, then
  report `SL_ERR_NORESPONSE`. A response matches on source node **and** sequence number; a late answer to an
  earlier attempt still counts.
- A transmission refused by the engine is counted (`tx_err`) and handled like a lost one.
- Responder: DATA is acknowledged automatically (also duplicates, so a lost ACK is repaired) but delivered to
  the application once; POLL is delivered every time with `dup` set on repeats, and the application answers
  with `sl_reply()` quickly (the tag only waits 60 ms).
- Duplicate filter: last sequence number per source, 8 sources, round-robin eviction.
- Tunables (`-D` in `sdcc-project.json` `defines`): `SL_RSP_TIMEOUT_MS`, `SL_MAX_ATTEMPTS`, `SL_BACKOFF_MS`.
- Counters in `sl_stats`: `tx_req tx_att tx_ok tx_fail tx_err rx_ok rx_dup rx_bad rx_stray`.

### Application payloads (`shelfmsg.h`)

- POLL (tag→hub, 6 B): uptime s (u16 LE), attempts the previous poll needed, RSSI of the hub's previous answer (i8), supply voltage (u16 LE, volts×256; older firmware sends 4 B without it).
- POLL_RSP (hub→tag, 3 B): command (`SM_CMD_NONE`, or `SM_CMD_DATA` = "data follows, stay awake"), RSSI the hub measured (i8), and a delay hint in 10 s units (`SM_RSP_DELAY`) that makes the tag wait at least that long.
- DATA opcodes: `IMG_BEGIN/CHUNK/END` (1–3), `FW_BEGIN/CHUNK/END` (4–6), `SET_ID` (7), `WIPE` (8), `FLASH_DUMP`/`FLASH_DATA` (9/10), `IMG_ZCHUNK`/`IMG_ZEND` (11/12).

### Timing

The tag's wake-up timer now runs from the 32.768 kHz crystal with prescaler 7, i.e. **512 Hz**
(`SHELF_WAKE_LPXOSC=1` in `Vusion/sdcc-project.json`; `SHELFHW_TICKS_PER_S` = 512), measured on hardware
(prescaler 6 gave ~1024 Hz). The early builds used the on-chip LPOSC at a nominal 640 Hz, which ran
~10 % slow; removing that define falls back to it. One timer arm holds 128 s, longer gaps are walked
down by waking to step a counter.

## Image push (host -> hub -> tag)

The tag announces itself with its normal POLL; the hub prints `POLL src=<addr> ...` on UART0 TX; the host
decides whether that tag needs a new image and, if so, tells the hub over UART0 RX (PB5) to send it.
The hub never decides anything and never stores an image. The tag is always listening, so the hub can
transmit to it at any time.

```
tag  --POLL-->  hub  --"POLL src=0100 ..."-->  host  (image for 0100 new?)
tag  <--DATA(BEGIN, CHUNK..., END)--  hub  <--"S0100<payload><chk>"--  host
```

**Host -> hub** (hex lines, `\n` terminated, `ShelfKit-Server/shelfkit/hubhost.py` implements the host side):

| Line | Hub does |
|---|---|
| `P` | answers `PONG` |
| `S<addr:4><payload 0..32 B><chk:2>` | reliable DATA frame to node `addr` (shelflink retries, 4 transmissions), then prints `SENT <addr> ok\|fail att=N`. `chk` = two's complement of the byte sum. A bad line gets `ERR len\|hex\|chk\|addr\|cmd\|busy\|send` and is ignored; the host resends. |

The hub's main loop never sleeps (`shelfhw_poll_awake()`), it polls the UART between wtimer callbacks. UART RX is polled
with only the one-byte holding register, so the protocol is strictly request/response from the host (one command in
flight, wait for `SENT`), checksummed, and retried on timeout. While the hub logs a `POLL` line (~18 ms) incoming bytes
can be lost, which the checksum + retry covers.

**Hub -> tag** (DATA payloads, `shelfmsg.h`): `BEGIN`, then 28-byte `CHUNK`s (plane, 16-bit offset in the plane), then
`END`. The tag has no RAM for a frame buffer (5624 B per plane): each chunk is shifted straight into the IL0373's frame
memory (`epd_stream_*`). Out-of-order/repeated chunks are ignored (offset must equal the next expected one), `END`
refreshes only when both planes are complete. BEGIN switches the panel supply on (transistor
U4 on PA5), resets the panel (~0.5 s) and END refreshes it (~15 s), both after the ACK, so the
host pauses after them (5 s / 20 s). The tag does not poll while a transfer runs.
A full image is ~404 messages, roughly 20-30 s.

`END` logs what the panel actually did: `img done busy=1 14.6s` is a real refresh waveform,
`busy=0` means the IL0373 never pulled BUSY at all (no supply or no reset pulse - check PA5 and
PB5), and `busy=2` means the waveform was still running when the wait ran out, in which case the
panel is left powered rather than being put to sleep mid-refresh.

Host: `python ShelfKit-Server/shelfkit/hubhost.py COM4 serve images/` pushes `images/<addr>.png` to a tag when it announces itself and the
file is new or changed (state in `images/.sent.json`); `send <addr> <png>` pushes once; `ping` checks the channel.
`ShelfKit-Server/shelfkit-server.py` does the same from a two-pane web UI.

**Status: working on hardware.** If a push does not start: `hubhost.py COM4 ping` — no PONG means the PB5
receive setup (`host_rx_init`, input + pull-up, no PALTB bit) is the first suspect; then `send` an image to a
tag and watch the tag's `img begin / img refresh / img done` log lines.

**Compressed planes.** A plane may instead arrive as `ZCHUNK` frames (up to `SM_ECO_MAX` = 2,560 bytes) and a
`ZEND`, which the tag decodes in bands straight into the panel (`eco_rx.c`); a label is ~0.5–0.8 KB per
plane. The host falls back to plain `CHUNK`s for a plane that does not compress. **Batches:** a hub that
advertises `batch=1` accepts `B<addr><count>(<len><payload>)…<chk>` lines of up to 16 frames and sends
them back to back. **Pre-arm:** `Q<id>` flags that tag's next poll reply, `L<hh>` asks every tag to wait
`hh*10` s.
## Debug output and tools

Both firmwares log on UART0 TX (PB4, 115200 8N1).

**LEDs are pulses, never levels.** They sit directly behind the e-paper glass and a lit LED warms
the panel into a visible blob on the frame, so every indication is one bounded flash
(`shelfhw_led_pulse`, 50 ms; 250 ms for the boot flash) and no LED is ever left on. The
`SHELFHW_LED_PULSE_MS` / `SHELFHW_LED_BOOT_PULSE_MS` defines in `shelfhw.h` are the only durations:

| LED | Where | Meaning |
|---|---|---|
| blue | hub + tag | one flash at boot, when the radio came up |
| green | hub | a tag announced itself (one flash per `POLL` line) |
| green | tag | an image transfer is starting (`BEGIN`) |
| red | hub + tag | error: repeating flash if radio init failed; on the tag one flash per failed poll |

Successful polls are silent on the tag by design - a per-poll flash kept an LED lit most of the
time. The UART log carries that information instead. LED polarity is still unverified: the pin map
says active low, the firmware assumes active high (`SHELFHW_LED_ACTIVE_HIGH`). If the wrong LED
lights, or one appears to be on permanently, that define is the single switch.

Example (tag / hub):

```
poll ok att=1 rssi=-35 hubrssi=-36
POLL src=0100 seq=09 rssi=-36 up=6s att=1 hubrssi=-35
```

| Tool | Use |
|---|---|
| `ShelfKit-Server/shelfkit-server.py hub=COM4 tag=COM3 [--baud N]` | Local web UI: Fleet, Editor, Queue, Logs, Hub (a pane per port with its own log, baud rate, Open/Close, DTR and Reset), Flash and Settings. |
| `ShelfKit-Server/shelfkit/hubhost.py COM4 serve\|send\|ping ...` | The same image push without a UI, plus `ping` for the hub's command channel. |
| `ShelfKit-Firmware/Tooling/axsem-flasher.py <hex> -p COMx` | Flash over the AX8052 serial bootloader (works). |
| `Data/flashdump.py COMx` | Capture the parked dump firmware's hexdump of the SPI flash. |

Build memory (SDCC 3.6.0, release build): hub 30.8 KB, tag 40.9 KB of 59,389 B code; XRAM 4.9 KB (hub) and 7.0 KB (tag) of 8 KB;
**internal RAM is tight** — 137–154 B of stack left, "no spare internal RAM" on the tag. Watch this when
adding features (put buffers in `__xdata`).

Building: SDCC-MDF builds each target as before (open the target folder, Ctrl+Shift+B). The
`upload` section of `sdcc-project.json` already points at `axsem-flasher.py`, so *SDCC: Flash* uses it
(set `sdcc.comPort`). During this session builds were verified with an equivalent manual SDCC script;
**please run one real SDCC-MDF build per target** to confirm the extension accepts the `../Shared/firmware`
source entries and no longer reports a failed link.

## Open questions / next steps

1. **Long-run loss test**: leave `ShelfKit-Server` attached and watch the Hub and Logs screens for hours;
   then repeat at distance / through walls. Expect near-0 % loss at short range; failures show up as
   `att=2+` or `FAILED`.
2. **PA2/PA5 transistor lines**: PA5 (U4) is the panel supply and has nothing to do with the radio;
   PA2 (U5) is a switched load that changed nothing we could see in the radio's registers or
   noise floor, and is parked low ([pa2-pa5-findings.md](pa2-pa5-findings.md)). Still open: whether
   U5 is in the RF path - needs a second board sending while PA2 toggles on the receiver.
3. **LED polarity**: the pin map says active low, the firmware assumes active high
   (`SHELFHW_LED_ACTIVE_HIGH`). Confirm which LED lights and flip the define if inverted.
4. ~~Clock~~: done, the wake-up timer runs from the 32 kHz crystal.
5. **Tag power**: done as tag-initiated polling with radio deep sleep and MCU sleep between polls; what is left
   is metering it ([power-deepdive.md](power-deepdive.md)).
6. **Duty cycle**: 868.3 MHz is in the 1 % sub-band. A ~14-byte frame at 100 kbit/s is only a few ms of air
   time (plus 112-bit preamble), so 5 s polling is far inside the limit, but retries and many tags must be budgeted.
7. **Hub RX→TX→RX turnaround** against the tag's 60 ms window has not been measured (works at 1 attempt so far).
8. Tag identity is no longer a compile-time define: it lives in SPI flash ([tag-identity.md](tag-identity.md)). The hub's duplicate table still holds only 8 sources, which bounds how many tags it can filter at once.
