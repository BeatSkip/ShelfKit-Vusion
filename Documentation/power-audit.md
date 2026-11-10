# Vusion tag power audit (2026-11-10)

Scope: `ShelfKit-Firmware/Vusion` and the shared code it links (`shelfhw`, `shelflink`,
`axradio`). This was a code review plus a compile check. **Nothing here was measured on
hardware**: every current is a datasheet figure or an estimate, and every change still needs
a run on a real tag.

## Summary

The tag's own figure (`avg=…uA life=…d`, logged and sent on a tapped poll) is too low for
two separate reasons:

1. **The software ammeter had bugs.** Five of them, all making the number smaller. They are
   fixed (see below).
2. **The ammeter cannot see the board's idle current at all.** It multiplies time in Sleep
   by a constant, 3 µA. At a 300 s poll interval the polls themselves cost only about 2 µA
   average, so that constant *is* the result. The real idle current is very likely tens of
   µA or more, because the switched rail is held on (`SHELF_NFC_RAIL_HOLD 1`). No firmware
   fix can find that number; it needs a meter. This is the larger of the two problems.

So after the fixes the tag will still report roughly 4-6 µA when idle, until
`SHELF_PWR_SLEEP_UA` in `shelf_config.h` is set from a measurement.

## What one cycle costs (estimates)

| Event | Charge | Notes |
|---|---|---|
| Idle poll, answered "nothing queued" | ~0.5-0.7 mAs | ~25-30 ms receiver on, one ~3 ms frame at 15 dBm, ~30 ms CPU. About 2 µA average at 300 s |
| Failed poll (4 attempts, no reply) | ~7 mAs | 4 frames, 4 x 60 ms reply windows, back-offs, 250 ms grace, all with the receiver on. Worth about 12 good polls |
| Image update | ~150-180 mAs (~0.05 mAh) | Refresh ~15 s at ~8 mA is most of it; the receiver stays on through the server's 2 s wait after BEGIN |
| NFC tap | ~1.5 mAs plus the LED | Two polls (at once and 5 s later) and a 50 ms blue pulse |
| Idle floor, as modelled | 3 µA | MCU Sleep with both XRAM halves kept is 2.2 µA in the datasheet, plus the 32 kHz crystal |

One image costs about as much as a day of idle polling. A day of idle polling costs less
than an hour of a 30 µA idle floor.

## Why the reported figure was too low

### Ammeter bugs (fixed)

| # | Bug | Effect |
|---|---|---|
| 1 | `shelfhw_poll()` took its timestamp *before* running the timer callbacks and booked everything up to the end of the idle call as sleep. Every poll, radio wake, flash access and blocking LED pulse runs inside those callbacks | Nearly all CPU time was charged at 3 µA instead of 3 mA |
| 2 | The transmitter was not counted. A frame at 15 dBm draws ~55 mA; the model charged it as receive current | About a quarter of a poll's charge was missing; a failed poll's four frames too |
| 3 | The sum `asleep_s * 1000 * 3` overflowed 32 bits after 16.5 days asleep, `asleep_s * 1000` after 49.7 days, and the tick counters after 97 days | The average became garbage on any tag that had been up for more than two weeks |
| 4 | Radio-on and awake spans were truncated to 16 bits (128 s). A firmware transfer keeps the radio on and never calls `shelfhw_poll()` for minutes | Long transfers were under-counted |
| 5 | The panel refresh (~8 mA for ~15 s) was not counted; the MCU sleeps through it, so it was charged at 3 µA | An image update was almost free in the model |

Also fixed: time in MCU Standby (which is what the MCU uses whenever the receiver is on) was
counted as Sleep. It is now separate and charged at 0.1 mA.

### What the ammeter still cannot see

These are ranked by how much I expect them to matter. All of them need a meter.

1. **PA5 held low against its pull-up.** `pa2-pa5-findings.md` describes a *strong* external
   pull-up on PA5. With `SHELF_NFC_RAIL_HOLD 1` the firmware drives PA5 low from boot, so
   that resistor conducts continuously: 30 µA if it is 100 kΩ, 300 µA if it is 10 kΩ. Measure
   the resistance from PA5 to VDD on an unpowered board; that alone may explain the gap.
2. **The flash sits in standby, 25 µA typical** (AT25XE011; deep power-down is 4.5 µA,
   ultra-deep 0.2 µA). `shelf_id_boot()` sends "release from power-down" and nothing ever
   puts the chip back.
3. **The rest of the held rail**: the NFC chip's standby, and the panel controller, which is
   powered from boot but only put into deep sleep after an image.
4. **The rail state is inconsistent.** It is on from boot (`main()` calls
   `extflash_power_up()`), but `panel_off()` in `img_rx.c` calls `pwr_off()` after every
   image regardless of `SHELF_NFC_RAIL_HOLD`. So after the first image the rail is off until
   the next reboot or flash access. In that state:
   - PB3 has only the MCU's pull-up and `nfc-field-detect.md` records it oscillating; the
     storm guard limits the damage but the feature is effectively off, with a burst of
     NFC-triggered polls every ~30 poll cycles.
   - The three chip selects, EPD reset and EPD D/C are still driven high into unpowered
     chips. That back-powers the rail through their protection diodes (the same doc saw the
     flash answer with the rail off), so "off" may save very little.
   Idle current therefore differs before and after the first image. Measure both.
5. **`OSCFORCERUN |= 0x04` forces the MCU's crystal oscillator on** at boot (AND9349/D
   table 50: "XOSC FRUN: the Crystal Oscillator is always enabled"). `SHELF_XTAL_OFF` is 0,
   so it is never released. Whether that costs anything in Sleep on this part is not
   something I could determine from the manual.
6. **LED current** during the 50 ms pulses and the 250 ms boot pulse.
7. **Battery derating.** `life=` divides the nominal 620 mAh by the average. `power-deepdive.md`
   uses 85 % of that; cold and the 55 mA transmit pulses reduce it further.

## Changes made

All of these compile for the tag and the hub. Tag image: 42,508 bytes against a 42,992 byte
OTA window (it was 42,309), so 484 bytes of headroom remain.

### Ammeter (changes the reported number, not the tag's behaviour)

- `Shared/firmware/shelfhw/shelfhw.c`: only the idle call is timed, and its span goes to
  Sleep or Standby according to what `wtimer_idle()` returned. CPU time is the uptime minus
  those two. Sleep is kept in seconds so it cannot wrap. Radio-on time uses 32-bit
  differences. The API is now `shelfhw_awake_ticks()`, `shelfhw_standby_ticks()`,
  `shelfhw_asleep_s()`, `shelfhw_radio_on_ticks()`.
- `Shared/firmware/shelflink/shelflink.c`: new 32-bit `sl_tx_frames`, counting every frame
  actually handed to the transmitter (requests, retries, ACKs).
- `Vusion/src/img_rx.c`: `img_rx_panel_ticks()` accumulates refresh time.
- `Vusion/src/main.c`: `pow_update()` sums charge in a form that does not overflow and
  adds the transmitter and the panel. The log line and the tapped-poll fields keep their
  format.
- `Vusion/include/shelf_config.h`: the currents are now named constants
  (`SHELF_PWR_MCU_UA`, `SHELF_PWR_SLEEP_UA`, `SHELF_PWR_RADIO_UA`, `SHELF_PWR_PANEL_UA`,
  `SHELF_PWR_TX_UAS`). **Set `SHELF_PWR_SLEEP_UA` to the measured idle current of the whole
  board**; the others matter much less.

### Optimizations (same behaviour, less charge)

- **The statistics line is produced after the radio is parked.** `on_done()` used to call
  `log_stats()` (32-bit divisions plus ~130 characters, about 11 ms at 115200 baud) before
  the listen timer was armed, so all of it ran with the receiver on. It is now flagged and
  done by `listen_cb()` right after `shelfhw_radio_sleep()`. Saves roughly 0.1 mAs every
  second poll with the log on. The line appears after `sleep`/`rslp` instead of before.
- **The red "poll failed" pulse is shown after the radio is parked**, for the same reason:
  50 ms of LED used to extend the receiver-on time by 50 ms (~0.55 mAs per failed poll). The
  pulse now comes about 250 ms later.
- **The NFC probe is compiled out when `SHELF_NFC_PROBE` is 0** (it already was never
  called). No power effect; it returns ~390 bytes, which is what paid for the ammeter fixes.

With `SHELF_RADIO_SLEEP 0` both reorderings fall back to the old immediate behaviour.

## Not changed, and why

Each of these touches timing or hardware state that I could not verify without a tag, so
they are left for you. Ordered by expected gain.

| # | Change | Expected gain | Why it is easy | Why I did not apply it |
|---|---|---|---|---|
| 1 | **Measure, then pick one rail policy.** Either hold the rail and make everything on it sleep, or drop it and drive every pin that touches it low | Possibly most of the real draw | It is a policy decision plus a few lines | Needs the measurements in the next section; the two options conflict, and `panel_off()` currently undoes the configured one |
| 2 | Put the flash into deep power-down (`0xB9`) in `extflash_power_down()` when the rail is held | ~20 µA (25 → 4.5) | One SPI byte; every tag-side access already sends `0xAB` first | **The bootloader never sends `0xAB`.** After a software reset with the rail still up it would read `FF`, see no OTA header, and an update would silently not apply. Add the release to the bootloader first, or release before the OTA reset in `fw_rx.c` |
| 3 | Set `SHELF_LOG_MUTE 1`. The comment in `shelf_config.h` and the README both call muted the default, but the value is 0 | ~100 characters per poll, ~9 ms of CPU, ~6 ms of it with the receiver on: ~0.1 mAs of a ~0.6 mAs poll | One define | `shelfhw.c` records a tag that locked up with the log muted; `radio_settle()` was added to replace the delay the log lines provided. Needs a soak test |
| 4 | Shorten the settles in `shelfhw_radio_wake()`: 3 ms + 4 ms of busy-wait after the receiver is already on | ~0.1 mAs per poll (15-20 %) | Two constants | They were found by experiment on hardware; `deepsleep-debugging-fix.md` shows how fragile this path is |
| 5 | Remove the `radio …` register snapshot logged after every wake | 8 SPI reads plus ~31 characters with the receiver on | Delete one block; the debugging note already says it can go | Same lockup history as #3 |
| 6 | Drop the 250 ms grace after a poll where all four attempts went unanswered | ~2.75 mAs per failed poll (~40 %) | One branch in `on_done()` | It exists to catch a hub that heard the poll but whose reply was lost. A design trade-off, yours to make |
| 7 | Transmit at 10 dBm instead of 15 | About half the transmit charge (~0.07 mAs per frame) | Regenerate `config.c` in AX-RadioLab | Costs range; check hub RSSI across the fleet first |
| 8 | Cut the server's fixed 2 s wait after BEGIN, or make it ACK-driven | ~20 mAs per image | Server-side constant in `hubhost.py` | The tag needs ~0.5 s for the rail ramp and panel reset; needs testing with a cold panel |
| 9 | Add a pull-up on PB3 or power the NFC chip from the always-on rail | Lets the rail be off with NFC working | - | Hardware change |

Smaller things noticed along the way:

- `wtimer0_curtime()` wraps after 97 days at 512 Hz. `next_interval()` uses it as uptime to
  choose the lost-hub back-off (hourly, two-hourly, daily), so a tag that has lost its hub
  drops back to hourly polling for two days after each wrap. The uptime in the poll payload
  is 16 bits of seconds and wraps every 18 hours regardless.
- `pwr_pulse()` in `pwr.c` is unused, about 150 bytes if the OTA window gets tight again.
- `Vusion/README.md` ("Serial log is off by default") says `SHELF_LOG_UART` is 0. It is 1,
  and `SHELF_LOG_MUTE` is 0, so the tag currently prints everything.

## What to measure

A meter in series with the cell (or a PPK2), serial adapter disconnected because its DTR
sits on PB3:

1. Idle current after boot, before any image (rail held on).
2. Idle current after one image update (rail cut by `panel_off()`).
3. Resistance from PA5 to VDD with the board unpowered.
4. Idle current with `SHELF_NFC_POLL 0` and `SHELF_NFC_RAIL_HOLD 0`, for the floor without
   the NFC feature.
5. Charge of one idle poll, to check the ~0.6 mAs estimate and the transmit constant.

Put the result of 1 or 2 into `SHELF_PWR_SLEEP_UA`. If 1 and 2 differ much, that difference
is the answer to rail-policy question #1 above.

## Verification done

- `build-all.py --targets vusion,hub` into a scratch folder: both link, tag image inside the
  OTA window, internal RAM use unchanged. `version.json` and `build-log.md` were restored
  afterwards, so the build counter is still 29 and `Release/` is untouched.
- Not done: flashing, running, or measuring anything. Before trusting the new build, watch
  one tag through boot, several polls, a failed poll (hub off), an image update and an NFC
  tap, and check that `asleep` plus `awake` in the `pow` line adds up to the elapsed time.

Sources for the external figures: [AT25XE011 datasheet](https://cdn.eicom.ru/media/PDF/8070154.pdf),
[Renesas AT25XE011](https://www.renesas.com/en/products/at25xe011),
[AX8052F143 datasheet summary](https://en.sekorm.com/doc/3032985.html); AND9349/D and the
other figures are from the PDFs in this folder.
