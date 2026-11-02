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

## Adaptive check-in

The configured interval is only a starting point (openepaperlink-style backoff). Each
result picks the next gap, and gaps longer than one wake-up-timer arm (~100 s) are
walked down by waking to step a counter, so the CPU stays asleep the whole time:

| last result | next check-in |
|---|---|
| answered | `SHELF_POLL_INTERVAL_S` (16 s as configured) |
| answered, but the hub heard us below `SHELF_WEAK_RSSI_DBM` (-95) | 10 min |
| 1, 2, 3, 4, 5 misses | 32 s, 64 s, 2 min, 4 min, 8 min |
| 6–13 misses | 10 min (`SHELF_POLL_MAX_S`) |
| 14+ misses | 1 h, then 2 h after a day without a hub, then 24 h from the day after |
| hub asks via the reply (`SM_RSP_DELAY`, 10 s units) | at least that long |

The reasoning is the same as openepaperlink's: a failed transmission costs far more
than waiting, and a tag out of range must not spend its battery retrying. The hub can
also park tags itself — `L<hh>` on its console makes every reply carry a delay hint of
`hh*10` seconds.

Counters reset on the first answered poll, and the day-based steps use uptime, so a
tag that comes back into range returns to the base interval immediately.

## Polling on an NFC field (parked)

**Disabled for now** (`SHELF_NFC_POLL 0`); the driver and the findings are kept in
`Documentation/nfc-field-detect.md`, and the section below describes the intended behaviour.

`SHELF_NFC_POLL` would make the tag react when someone holds a reader to the label: it flashes
the **blue LED** and polls within a second instead of waiting out the interval. The LED is
there so the feature can be tested on a battery board with nothing plugged into the serial
port.

The NFC chip's field-detect output is **open drain**: it pulls the line low while a
reader's field is present and releases it otherwise, so the pin needs the weak pull-up it
gets from `DIRB` bit 3 = input and `PORTB` bit 3 = 1 (AND9349/D's pin table: `0 1` is
"Z, Pull-Up"). With an open drain, "a reader arrived" is a **falling edge**.

That is what `EXTIRQ` provides, and its default pin happens to be PB3 already:

| register | value | meaning |
|---|---|---|
| `EXTIRQ` bits 5:4 | `11` | dropping edge |
| `EXTIRQ` bit 6 | `0` | Port B.3 |
| `IE.2` | 1 | External 1 interrupt enable (vector `0x13`) |

The handler sets a flag and disables itself; the main loop flashes the LED, logs
`nfc field` and arms a poll one second out; `listen_cb` re-arms it after the poll. One
event per arrival, and no way for a level that stays present to keep firing.

The first attempt used the pin-change interrupt (`INT_GPIO`). It fired on **both** edges
and on this part its change flag has no documented acknowledge, so it re-fired
continuously. `EXTIRQ` is edge-triggered and self-clearing, which is why it replaces it.

### PB3 is shared with the bootloader's BOOT strap

The same pin is the BOOT input and the serial adapter's **DTR** is wired to it. With an
adapter attached - especially one that is unpowered or holding a level - that line is not
the NFC chip's signal, and the tag will react to the adapter. Treat anything seen with a
serial cable plugged in as a property of the cable; test on a battery board, which is
what the LED is for.

`SHELF_NFC_POLL 0` removes the feature and leaves PB3 untouched.

**The chip has to be configured before it does anything.** By default that pin reports
the NFC chip's EEPROM write-in-progress flag, not a field detect, so the firmware is inert
until the chip's configuration byte is changed. That write needs register details the
datasheet in this repository does not contain - see
[Documentation/nfc-field-detect.md](../../Documentation/nfc-field-detect.md).

## Power

The tag polls as above. Between polls:

| block | state | datasheet |
|---|---|---|
| radio | `AXRADIO_MODE_DEEPSLEEP` (`SHELF_RADIO_DEEPSLEEP`): the AX5043's own deep sleep, 26 MHz XTAL stopped, woken over SPI by `ax5043_wakeup_deepsleep()`. The wake changes mode **first** and only then settles ~4 ms - waiting first left the first frame after a sleep off-frequency | ~50 uA |
| MCU | Sleep (`wtimer_idle(WTFLAG_CANSLEEPCONT)`, `SHELF_MCU_SLEEP`), `PCON.XRAMKEEP` keeping both XRAM halves | ~2 uA |
| wake-up timer | 32.768 kHz crystal, prescaler **7** = **512 Hz** (`SHELF_WAKE_LPXOSC` in `sdcc-project.json`) | 0.7 uA |
| listening window | 2 s after a poll, but **closed after 500 ms** unless the hub's reply said data is coming (`SM_CMD_DATA`); it re-arms while a transfer or a flash read-back is running | 9.5 mA only while open |
| panel, flash rails | off unless a refresh or a flash access needs them | - |

Estimated average and CR2450 life (datasheet figures, not measurements):

| configuration | average | CR2450 |
|---|---|---|
| 60 s poll, 2 s window, crystal-on radio, standby (before this round) | 0.65 mA | 40 days |
| + radio deep sleep | 0.40 mA | 64 days |
| **+ the 500 ms grace on idle polls (what is shipped)** | **0.17 mA** | **~150 days** |
| MCU sleep as well, if the resume worked | 0.09 mA | 300 days |

**Why the tag can boot-loop, and why it must never write `PCON` per poll.** The first
low-power build booted, ran one poll and restarted, forever, but only after an OTA - a
hardware reset was fine. The cause was one line in `shelfhw_measure_vdd()`:
`PCON = (PCON & ~0x0C) | 0x0C` (to keep the XRAM across sleep). That helper runs on
*every* poll, and `PCON.SWRESET` (bit 4) **reads back 1 after a software reset**, so
writing the register back re-armed the reset that had just happened. A hardware reset
clears the bit, which is why a manual reset "fixed" it. Nothing in the poll path may
write `PCON`; `OSCFORCERUN |= 0x08` now sits in `shelfhw_init()` where it belongs.

**The switches only work because the driver includes the config.** `shelfhw.c` used
not to include `shelf_config.h`, so `SHELF_MCU_SLEEP` and `SHELF_RADIO_DEEPSLEEP` were
invisible to it and both features were dead code for a whole round - every build ran
standby + `AXRADIO_MODE_OFF` while the config claimed otherwise. They are compiled in
now, which is why the tag grew by ~50 bytes.

**MCU sleep relies on libmf's resume.** `enter_sleep_cont()` saves SP and a signature
at the top of IRAM and sleeps; `enter_sleep()`/`enter_sleep_cont()` end in
`ljmp 0xE047` (the ROM sleep handler). If a tag ever boot-loops after this build, set
`SHELF_MCU_SLEEP 0` - that is the only switch that changes the resume path.

**The tick base is measured, not assumed.** Prescaler 6 gave ~1024 Hz on hardware (60
counted seconds in 30 real ones), which halved every interval and every link timeout;
prescaler **7** matches `SHELFHW_TICKS_PER_S` = 512. The crystal itself was never the
problem: `OSCRUN` shows the LPXOSC running, and the FRC calibration already used it.

The radio deep sleep is still the least proven step. If a tag stops making its polls,
`SHELF_RADIO_DEEPSLEEP 0` falls back to the crystal-on `AXRADIO_MODE_OFF`; removing
`SHELF_WAKE_LPXOSC` from `Vusion/sdcc-project.json` falls back to the internal RC at
640 Hz.

### Measuring power without a meter

There is no shunt on the board, so the firmware counts **time in each state** and prints
the estimate itself, every `SHELF_STATS_EVERY` polls (5, so every 5 minutes) on the tag's
own serial port:

```
pow awake=1600ms radio=1500ms asleep=58s avg=322uA life=80d
```

| field | meaning | datasheet current |
|---|---|---|
| `awake` | MCU running since boot: the boot, every poll, the listening window | ~3 mA (150 uA/MHz at 20 MHz) |
| `radio` | of that, the transceiver was on (a subset of `awake`) | +9.5 mA RX |
| `asleep` | MCU in Sleep | ~3 uA |
| `avg` | the average draw, computed from the three above | - |
| `life` | days on a 620 mAh CR2450 at that average | - |

The window is the whole story: 1.5 s of a 60 s cycle at 12.5 mA (MCU + receiver) is
0.3 mA average on its own, while the sleep current is irrelevant. Hence:

| configuration | average | CR2450 |
|---|---|---|
| 1.5 s grace, 60 s poll | 0.30 mA | ~86 days |
| 0.7 s grace, 60 s poll | 0.16 mA | ~160 days |
| **0.7 s grace, 120 s poll (current)** | **0.07 mA** | **~400 days** |

The receiver window is ~98 % of the budget at these intervals, so those two knobs are
the whole story: the sleep chain below is worth about 1 uA of the 70.

Read the line like this:

- `asleep` ≈ 58 s per 60 s cycle → it really is sleeping; the cost is the window.
- `asleep` well below that → something keeps it awake (a stuck transfer, a queue that
  re-arms the window every poll).
- `radio` much larger than the window → the receiver is not being parked; check that
  `listen_cb` runs.
- `avg` moving between ~320 and ~430 uA is normal: it tracks how many polls carried a
  queued command and therefore opened the full 2 s window.

The second, slower cross-check is the `vdd=` value each poll already carries: plot it
over days. A CR2450's curve is flat in the middle, so hours prove nothing, but a day
reveals the order of magnitude.

**Battery.** Each poll carries the supply voltage, measured with the AXSEM bootloader's
ADC recipe (`shelfhw_measure_vdd`, volts*256, e.g. 3.00 V -> 0x0300). The hub prints
it as `vdd=0300` and the server shows it in the Fleet **Battery** column and the
drawer as both volts and an **average-CR2450 percentage**, red below 2.5 V. The AX8052
GP ADC has missing codes around mid-scale (erratum, all revisions), so treat the last
digit as a hint, not a measurement.

Other consequences:

- **One wake-up-timer arm caps at 128 s** (16 bits at 512 ticks/s); longer backoff gaps
  are walked down by waking to step a counter.
- **Pushes wait for a window.** The server retries a frame for 90 s
  (`hubhost.CMD_RETRY_WINDOW_S`), and pre-arms the hub (`Q<hex>`) when it queues, so the
  tag keeps its full window open for that poll.

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
- Battery voltage is reported per poll; fuller telemetry (temperature, per-day history) is not.
- The NFC chip and the serial flash have chip selects and a flash driver, but no NFC driver.
- U5 (PA2) is still unidentified and left alone.
