# Vusion — the tag target

The battery tag half of ShelfKit: it **polls the hub** every couple of minutes and, when the hub has
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
| `SHELF_POLL_INTERVAL_S` | Base seconds between polls (default 120; one wake-up-timer arm is 128 s at 512 Hz, longer gaps are walked down). Mind the 1 % duty cycle of the 868.3 MHz sub-band |
| `SHELF_LISTEN_WINDOW_S`, `SHELF_LISTEN_GRACE_MS`, `SHELF_LISTEN_QUIET_MS` | How long the receiver stays open after a poll: 2 s when data is coming, 250 ms after a lost reply, 0 after a "nothing queued" reply |
| `SHELF_POLL_ACTIVE_S`, `SHELF_POLL_COOLDOWN_S`, `SHELF_POLL_IDLE_S` | Burst (30 s), cool-down (180 s) and idle (300 s) intervals, see [Listen window and burst polling](#listen-window-and-burst-polling) |
| `SHELF_STATS_EVERY` | Print the `pow …` link/power summary every N polls (2) |
| `SHELF_RADIO_SLEEP`, `SHELF_RADIO_DEEPSLEEP`, `SHELF_MCU_SLEEP`, `SHELF_XTAL_OFF` | The low-power switches (all but `SHELF_XTAL_OFF` are on), see [Power](#power) |
| `SHELF_NFC_POLL`, `SHELF_NFC_RAIL_HOLD`, `SHELF_NFC_PROBE` | NFC wake-on-field (1, 1, 0): a falling edge on PB3 wakes the tag and polls; the rail is held on because with it off PB3 floats and re-triggers every cycle (seen on hardware: a poll every 1.8 s). A storm guard suspends the feature for ~30 poll cycles after 4 consecutive NFC-triggered cycles |
| `SHELF_NFC_URL`, `SHELF_NFC_NDEF_SYNC` | What a phone reads from the tag ("", 1): empty = the phone detects the tag and opens nothing. At boot the tag compares the NFC chip's NDEF area (Type 2, from 0x010) with this and rewrites it only if it differs. A URL (max 48 chars) adds ~100 B of code, which the OTA window cannot take right now (see Documentation/power-audit.md for the size budget) |
| `SHELF_FLASH_POWER_ON`, `SHELF_WIPE_FIRST_BOOT` | Switch the flash rail around every flash access; wipe the owned flash sectors on a first boot |
| `SHELF_POWER_LINES` | Hold the panel supply (U4, PA5) on from boot. Not a radio setting; leave off — the image path powers the panel around each image. PA2 (U5) is always parked low |

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

The current release build is about 40.9 KB of code and about 7 KB of XRAM (the ECO decode buffer alone is
2.5 KB) out of the 59,389 B / 8,192 B the memory model allows; build it for exact figures, the report is
printed by `build-all.py`. Internal RAM is at the wall — new code has to keep its locals out of the
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
| answered | `SHELF_POLL_INTERVAL_S` (120 s), or the burst / cool-down / idle rate below |
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

## Polling on an NFC field

**Enabled** (`SHELF_NFC_POLL 1`); measurements and the Shakedown test sequence are in
`Documentation/nfc-field-detect.md`. At boot `nfc_cfg_fd()` reads the chip's FD configuration
(EEPROM `0x38C` / `0x391`) and rewrites it only if it is not field-detect. Measured: idle HIGH,
active LOW, quiet with no phone; a phone gives bursts of 1-30 ms low pulses, so the first edge
is the event and at most `SHELF_NFC_BURST_MAX` (3) are honoured per poll cycle. While the MCU
sleeps, the wake is a port-change interrupt on PB3 (the only pin wake sleep has), armed around
each sleep in `shelfhw_poll()`.

`SHELF_NFC_POLL` makes the tag react when someone holds a reader to the label: it flashes
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

`SHELF_NFC_POLL 0` removes the feature and leaves PB3 untouched. With a phone in the field at
reset PB3 is low and the tag enters the bootloader, so do not reset it while holding a phone.

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
| listening window | 2 s after a poll, but **closed at once** when the hub's reply said "nothing queued" (`SHELF_LISTEN_QUIET_MS 0`), and after 250 ms when no reply arrived at all; it stays open when the reply said data is coming (`SM_CMD_DATA`) and re-arms while a transfer or a flash read-back is running | 9.5 mA only while open |
| panel, flash rails | off unless a refresh or a flash access needs them | - |

**None of the figures here are measurements.** They are datasheet-class estimates, and the tag has
no shunt, so the first real number will come from a meter or a PPK2 on a battery board. The
history of the model, from the first low-power build to now (each step shrinks the receive window,
which was ~95 % of the energy):

| configuration | modelled average | CR2450 |
|---|---|---|
| 60 s poll, 2 s window, crystal-on radio, standby | 0.65 mA | ~40 days |
| + radio deep sleep | 0.40 mA | ~64 days |
| + 0.7 s grace on idle polls, 120 s poll | 0.07 mA | ~400 days |
| **shipped now:** receiver closed at once on a "nothing queued" reply, 250 ms grace on a lost one, 300 s idle poll | below the previous row; see [power-deepdive.md](../../Documentation/power-deepdive.md) (option 1 + 3 ≈ 45 months modelled) | unmetered |

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
the estimate itself, every `SHELF_STATS_EVERY` polls (2) on the tag's
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
0.3 mA average on its own, while the sleep current is irrelevant. Closing the window when the hub
says nothing is queued, and polling less often, are therefore the two knobs that matter.

Read the line like this:

- `asleep` nearly equal to the elapsed time (e.g. ~118 s per 120 s cycle) → it really is sleeping; the cost is the window.
- `asleep` well below that → something keeps it awake (a stuck transfer, a queue that
  re-arms the window every poll).
- `radio` much larger than the window → the receiver is not being parked; check that
  `listen_cb` runs.
- `avg` moving around is normal: it tracks how many polls carried a queued command and
  therefore opened the full 2 s window.

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
- U5 (PA2) is still unidentified, but measured: active high, no pull, a load on the supply, nothing we use improves with it on. It is parked low at boot (`pwr_park_u5()`). See [pa2-pa5-findings.md](../../Documentation/pa2-pa5-findings.md).

## Listen window and burst polling

- A reply that says "nothing queued" parks the radio at once (`SHELF_LISTEN_QUIET_MS 0`);
  a lost reply keeps a short `SHELF_LISTEN_GRACE_MS` (250 ms, was 700). So a push only
  reaches the tag when the hub was pre-armed (`Q<id>`) before the poll, which makes the
  reply say "data follows". ShelfKit-Server arms on queueing, after a hub reset and after
  a hub-display redraw. Set `SHELF_LISTEN_QUIET_MS 250` if you push without the server.
- A reply that says "data follows" switches the tag to `SHELF_POLL_ACTIVE_S` (30 s). Once the
  hub goes quiet it polls at `SHELF_POLL_COOLDOWN_S` (180 s) for `SHELF_COOLDOWN_POLLS` polls,
  then at `SHELF_POLL_IDLE_S` (300 s). `SHELF_ACTIVE_MAX_POLLS` caps a stuck data flag.
  Link failures and weak-link backoff still apply on top. See Documentation/power-deepdive.md.

## Panel power during an image update

- END starts the refresh and returns; a 100 ms timer watches BUSY. About 100 ms later the radio
  is parked (the END acknowledgement has left by then) and the MCU sleeps between ticks, so the
  12-15 s waveform costs the panel's ~8 mA instead of ~22 mA. `poll_cb` wakes the radio for the
  next poll. The log line `img done busy=<n> <s>s` is unchanged.
- A transfer that is abandoned (30 s without a frame) or ends incomplete now puts the panel to
  sleep and cuts its rail. A refresh that did not report done (busy=0 or 2) leaves the panel
  powered only until the next poll, which then does the same.
- The server waits 2 s (was 5 s) after BEGIN; the tag needs ~1 s to power and reset the panel.

## Compressed images (ECO)

Each plane may arrive ECO-compressed (chain coding, Documentation/ECO-ESL-ImageCompression.pdf):
`ZCHUNK`s fill a 2,560-byte buffer (`SM_ECO_MAX`), and `ZEND` decodes it straight into the panel
(src/eco_rx.c). The 5,624-byte plane never exists in RAM: it is rebuilt in 760-byte bands (40 rows),
re-running the decoder from the top for each band, because chains only walk downward. A label is
~0.5-0.8 KB per plane instead of 5.6 KB, so ~30 frames instead of 404. The log shows
`img zplane <bytes>B <s>s` per plane; `img zplane bad/short` means the plane was not drawn and the
image ends "incomplete". Plain `CHUNK`s still work (the server uses them when a plane does not
compress below the buffer, e.g. dithered photos). Old firmware does not understand ZCHUNK/ZEND:
flash all tags before pushing with this server.

## Serial log is off by default

`SHELF_LOG_UART` is 0 in `include/shelf_config.h`: the tag does not start its UART and prints
nothing, since it is not wired to a serial adapter in service. That saves the baud timer, the UART
and the CPU time spent waiting for characters (about 1 KB of code too). Set it to 1 (or build with
`-DSHELF_LOG_UART=1`) to watch the tag on PB4 while developing. A tapped poll also carries the firmware
version, build and power stats to the hub (`fw=0.0.1+7 avg=50uA life=516d` on the hub's POLL line); the
server keeps the latest per tag and shows it in the tag panel.
