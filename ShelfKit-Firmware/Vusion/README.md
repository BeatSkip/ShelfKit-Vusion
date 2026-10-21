# Vusion — the tag target

The battery tag half of ShelfKit: it **polls the hub** every few seconds and, when the hub has
content for it, **receives an image and refreshes the panel**. It drives nothing else — the hub
drives, the tag listens.

Built for the SES-imagotag **Vusion 2.6" BWR label** (UU340 variant): an **Axsem AX8052F143**
(8051 core + sub-GHz radio, 26 MHz crystal) driving a Good Display **GDEW026Z39** e-paper panel
(296×152, black/white/red, IL0373 controller), with an NFC chip and a serial flash on the same SPI bus.
Same hardware as [`../Vusion-Hub`](../Vusion-Hub); only the firmware role differs.

## What it does

```
poll timer (SHELF_POLL_INTERVAL_S) ─► POLL ─► hub
                                        ◄── POLL_RSP (the acknowledgement; carries the hub's RSSI)
             ── on failure: retry with jittered back-off, up to SL_MAX_ATTEMPTS ──
                                        ◄── DATA: image chunks ──► straight into the panel controller
             ACK per chunk, then refresh the panel, log "img done busy=…", sleep
```

- **`src/main.c`** — the loop: poll, log the result, sleep until the next tick. Blue LED pulses once
  at boot; a green pulse marks the start of an image reception; red is reserved for failures
  (`shelfhw_led_pulse`, 50 ms).
- **`src/img_rx.c`** — the receiving side: on DATA, powers the panel rail, brings the panel up from
  deep sleep, writes each chunk into the controller as it arrives (there is no room to buffer a
  frame), refreshes, and logs `img done busy=N S.Ss` so you can see whether the glass reacted.
- **`src/shelf_id.c`** — the wireless identity: read from SPI flash at boot, random at
  first boot, assignable over the air, and kept across updates
  ([Documentation/tag-identity.md](../../Documentation/tag-identity.md)).
- **`src/fw_rx.c`** — the firmware receiver: streams an OTA image into the SPI flash, checks
  its CRC, stores the magic the bootloader looks for and resets (see
  [Documentation/ota-update.md](../../Documentation/ota-update.md)).
- **`src/epd.c`** — the GDEW026Z39/IL0373 driver: rotated 152 wide × 296 tall, two 5624-byte planes
  (black/white and red), OTP waveform, BUSY-bounded command waits.
- **`src/spi.c`**, **`src/flash.c`**, **`src/pwr.c`**, **`src/board.c`** — bus, serial flash,
  the transistor lines (U4 = panel supply), and the pin map.

The wire protocol, retries, addressing and the image frame format are in
[Documentation/wireless-link.md](../../Documentation/wireless-link.md).

## Configuration — `include/shelf_config.h`

Everything tag-specific is in one header:

| Setting | Meaning |
|---|---|
| `SHELF_NET_ID` | Network id, must match the hub (`0x5A`). The node id is not here — it lives in the tag's SPI flash |
| `SHELF_POLL_INTERVAL_S` | Seconds between polls (default 5; mind the 1 % duty cycle of the 868.3 MHz sub-band) |
| `SHELF_STATS_EVERY` | Print link statistics every N polls |
| `SHELF_POWER_LINES` | Drive the unidentified PA2/PA5 lines before the radio starts — the panel rail is separate and handled around each image |

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

The build prints the memory report: 40,622 B of code and 1,084 B of XRAM out of the 59,389 B / 8,192 B
the memory model allows. Internal RAM is at the wall — new code has to keep its locals out of the
overlay (the OTA receiver uses `__xdata` statics, and the shared CRC/header helpers are `__reentrant`).

## First boot on a used tag

With no identity record in the SPI flash, the tag treats the flash as untrusted and
erases every sector the firmware owns — the OTA header included, because a stale
update marker there would make the bootloader overwrite the application on the next
reset — before it generates its random id. `SHELF_WIPE_FIRST_BOOT 0` in
`shelf_config.h` skips that. The same wipe is available on demand: the server's
**Factory reset** button sends `SM_OP_WIPE`.

## Power

The tag polls every `SHELF_POLL_INTERVAL_S` (30 s). Two very different things are
available for the current draw, and only the first one is enabled by default:

**Always on (default, what is verified on hardware):**

| block | between polls |
|---|---|
| MCU | standby (`wtimer_idle(WTFLAG_CANSTANDBY)`), woken by the low-power timer |
| radio | listening (`AXRADIO_MODE_ASYNC_RECEIVE`) - this is the ~10 mA |
| panel | rail off after a refresh (`pwr_off()`), image held without power |

**Opt-in radio sleep (`SHELF_RADIO_SLEEP 1`) - experimental:**

| block | between polls |
|---|---|
| radio | `AXRADIO_MODE_DEEPSLEEP` for the gap, woken before each poll |
| 26 MHz crystal | not forced (`OSCFORCERUN` bit 2 cleared), only with `SHELF_XTAL_OFF 1` |
| tags | listens `SHELF_LISTEN_WINDOW_S` (8 s) after each poll, since that is when the hub can send |

> **It does not work yet on hardware.** With this enabled a tag polled once and then
> went completely silent, which points at `radio_enter_deepsleep()`: it rewrites
> `RADIOMUX`/`PORTR` and drives the AX5043's SYSCLK output, and the AX8052F143 takes
> its clock from that same domain. Enable it in two steps while watching the tag's
> log:
>
> 1. `SHELF_RADIO_SLEEP 1`, `SHELF_XTAL_OFF 0` — radio only. The tag logs `sleep`
>    when it parks the radio and `wake` before the next poll.
> 2. If that survives, `SHELF_XTAL_OFF 1` as well — adds the crystal stop.
>
> Silence in the log *after* `sleep` means the chip stopped rather than the timer;
> repeating `poll FAILED` lines mean the timer is fine and the radio came back wrong.

Other consequences:

- **The wake-up timer caps the interval at ~102 s** (`SHELFHW_TICKS_PER_S` = 640 ticks
  per second compared in 16 bits). 30 s is the default, 60 s works, 100 s is the edge.
- **Pushes wait for a window when the radio sleeps.** The server retries a frame for
  90 s (`hubhost.CMD_RETRY_WINDOW_S`), so a push started at any moment lands within
  one poll cycle. With the radio always listening (default) this does not apply.

## Hardware notes that cost real time

- **PA5 (transistor U4) must be driven off at boot, not left floating.** Floating, the
  unpowered panel is back-powered through the SPI pins it shares with the flash: reads
  still look sane, but a page program is not accepted. That is why the identity write
  failed ("read back ffff") until an image push had run `pwr_init()`, and why OTA
  chunks stalled the tag for the old 0.5 s flash timeout and lost their ACKs. `main()`
  now calls `pwr_init()` (rail driven off) before it touches the flash.
- **PA5 (transistor U4) is the panel supply, active low.** Without it the panel accepts a whole init
  sequence and a whole frame over SPI and then runs no refresh waveform — which looks exactly like a
  dead panel. `img_rx.c::panel_power_on()` drives it on before every image, independently of
  `SHELF_POWER_LINES`. This was the bug behind a tag that logged a clean transfer and never changed.
- **Panel reset shares PB5 with UART0 RX.** With UART0 enabled the pin belongs to the UART and the
  reset pulse never reaches the panel; the tag logs on TX only and leaves RX alone.
- **BUSY is active low on this board** (the bare Good Display module is active high). If init hangs or
  frames come out corrupt, flip `EPD_BUSY_ACTIVE_HIGH` in `epd.h`.
- The panel needs its **supply on and a settle** before the init sequence, and the refresh needs a
  generous BUSY timeout (`epd_cmd_wait(0x12, …, 3000, 60000)`); a short one makes a slow but healthy
  refresh look like a failure.
- LEDs: 50 ms bounded pulses only (blue boot, green on reception start, red for errors). Holding an
  LED on at 3.3 V is how these boards get hot.

## Known gaps

- Partial refresh and rotation slots; today every update is a full ~15-second flash.
- No battery or telemetry report on the wire (the fleet table shows `—`).
- The NFC chip and the serial flash have chip selects and a flash driver, but no NFC driver.
- U5 (PA2) is still unidentified and left alone.
