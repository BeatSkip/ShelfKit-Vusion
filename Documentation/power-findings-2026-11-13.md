# Battery drain: findings and first hardware test (2026-11-13)

Follows `power-audit.md` (2026-11-10) and `power-deepdive.md`. Those were models; this note
has the first evidence from real tags, two firmware faults, and the result of the comparison
builds in `Release/compare/`.

## Status

- **Baseline is build B (1.1.0-38): crystal-oscillator fix on, sleep fix off.** The source
  builds this by default.
- The oscillator fix looks like the large saving, on a 15 minute test of one tag. It needs a
  run of several hours, and a meter, before it is trusted.
- The sleep fix makes the tag stop responding after its first Sleep. It is switched off and
  the cause is open.

## The symptom

A fresh CR2450 lasted under 24 hours, which is an average of roughly 10-20 mA. The model and
the tag's own estimate both said months.

## Evidence from the server database (builds up to 1.1.0-36)

From `ShelfKit-Server/data/shelfkit.db`, tables `voltage` and `events`:

- Tags polled exactly on schedule (180 s and 300 s gaps), with no reboot loops and no NFC
  storms while draining. The current is drawn between polls.
- Fresh cells sagged at once: E1D6 went 3.18 V -> 2.83 V in one hour -> 2.61 V in 8 hours.
  5E05, F466 and 55FD had the same shape. It happened before the first image (rail held on)
  and after it (rail cut).
- Every tag's own estimate settled at 104-118 uA. That is the 100 uA "Standby" bucket of
  the software ammeter plus a little: the MCU was never in Sleep.
- At end of life a tag boot-loops: E1D6 reported three boots in 55 s with VDD readings of
  0.83-1.6 V. Each boot costs seconds at about 14 mA, so a weak cell is finished off quickly.

## Fault 1: the MCU never entered Sleep

`log_putc()` in `Shared/firmware/shelfhw/shelfhw.c` sets `U0CTRL` bit 3 (U0TXIE) after every
character. No UART interrupt is enabled, so nothing clears it. libmf links a veto into
`wtimer_cansleep()` (section `WTCANSLP1`, from `uart0init.c`): `uart_txidle()` reports busy
while that bit is set. After the first logged character `wtimer_idle()` always chooses
Standby.

This also explains two older notes: the tag that "locked up with the log muted" and the one
that "breaks with `SHELF_LOG_UART 0`" were the only builds that really entered Sleep.

Cost of the fault itself: Standby is 85 uA plus running clocks, so well under 1 mA.

## Fault 2: the MCU's fast crystal oscillator was forced on with no crystal

`shelfhw_init()` did `OSCFORCERUN |= 0x04`. The comments called it the radio's 26 MHz
crystal. It is not: bit 2 is XOSC FRUN, the MCU's own crystal oscillator on **PA0/PA1**
(AND9349/D table 50). On this board PA0 is the panel D/C line and PA1 the panel chip select,
both driven as digital outputs. The manual says not to enable it without a crystal on those
pins, and that once enabled it runs until it sees falling edges on its pins or a reset.

The bootloader sets the same bit on every reset (`Bootloader/src/main.c`, the calibration
sequence), so the oscillator is already running when the application starts. libmf's own
LPXOSC calibration path only sets bit 3.

Fix: `turn_off_xosc()` (libmf) at boot instead of the force. It clears the bit and toggles
PA0/PA1 a few times, then restores them. The bootloader is unchanged, because it cannot be
updated over the air; the application switches the oscillator off after it.

## Switches

In `shelfhw.c`, overridable with `build-all.py --define`:

| Switch | Default | Meaning |
|---|---|---|
| `SHELF_FIX_XOSC` | 1 | 1 = switch the XOSC off at boot. 0 = force it on (old behaviour) |
| `SHELF_FIX_UART_SLEEP` | 0 | 1 = do not set U0TXIE, so Sleep is possible. 0 = old behaviour, Standby only |

`SHELF_NFC_POLL` and `SHELF_NFC_RAIL_HOLD` in `Vusion/include/shelf_config.h` can now be
overridden the same way. With the sleep fix on, the UART is re-initialised after each wake
from Sleep (`log_uart_start()`), because Sleep resets it and `log_putc()` waits on it.

## Comparison builds and first result

Recorded builds 37-41, tag application only, in `Release/compare/` (labels and commands in
its README; the rows in `ShelfKit-Firmware/build-log.md` carry the defines).

| Label | Build | XOSC fix | Sleep fix | Tag | Result |
|---|---|---|---|---|---|
| A baseline | 1.1.0-37 | off | off | B79F | 2.89 V -> 2.75 V in 15 minutes, as before |
| B xosc only | 1.1.0-38 | on | off | E1D6 | flat at 3.09-3.11 V over 14 minutes, polling on schedule |
| C sleep only | 1.1.0-39 | off | on | 9016 | one poll after boot, then dead |
| D both | 1.1.0-40 | on | on | B69F | one poll after boot, then dead |
| E both, no NFC | 1.1.0-41 | on | on | - | not flashed |
| D with bootloader bundle | 1.1.0-42 | on | on | 15B3 (wired) | serial test below: silent after the first Sleep |

Limits of this result: one tag per variant, different cells, about 15 minutes, no current
measurement. A and B differ clearly, but the size of the saving is not known.

## Open: the tag does not come back from Sleep

With the sleep fix on (C and D):

- The boot poll works, and a queued image is delivered on it.
- After that there is no scheduled poll.
- An NFC tap gives no blue LED pulse and no poll.
- Pulling and refitting the battery gives one more boot poll, then the same again.

So after the first Sleep the tag responds to neither the wake-up timer nor the pin change on
PB3.

### Wired test (tag 15B3 on COM4, build 1.1.0-42 = D with the serial log)

Flashed over the serial bootloader (application-only hex), log captured at 115200:

```
[  0.28] *** ShelfKit tag, node 15b3 net 5a dump=1 fw=1.1.0-42
[  1.56] poll ok att=1 rssi=-35 hubrssi=-35
[  1.56] sleep
[  1.56] rslp err=0 eng=2
          (nothing more in 345 s)
```

- Nothing at the 100 s timer step or at the 300 s poll.
- A simulated tap (the adapter's DTR pulls PB3 low for 20 ms) at 20 s and 40 s: no reaction.
- Listening at 38400 (the bootloader's rate) after the `rslp` line, through a tap and past
  100 s: zero bytes.
- The same tag reflashed with B (1.1.0-38): the simulated tap gives `nfc field (wake)`, a
  poll one second later and the follow-up 5 s after that. So the tap simulation is valid,
  and B's `pow` line shows `asleep=0s`: B never enters Sleep.

The tag was left on B.

### Most likely cause: a wake from Sleep goes through the bootloader

Read from the code, consistent with the test, not proven by it:

- The AX8052 restarts at address 0x0000 after Sleep. libmf's continue-after-sleep
  (`enter_sleep_cont()`, `sleepcont.c`) expects the *application's* start-up there: it finds
  its marker at the top of internal RAM, restores the stack pointer and returns.
- On these tags 0x0000 is the **bootloader**. It knows nothing about a wake from Sleep. On
  every start it resets its own stack, rewrites every port and direction register
  (`_sdcc_external_startup` in `Bootloader/src/main.c`), runs 128 oscillator calibration
  cycles, initialises the UART, powers the flash rail and looks for an OTA image, and only
  then jumps to the application with `SP = 7`.
- `enter_sleep_cont()` clears `GPIOENABLE` before sleeping and the bootloader never sets it
  again. All pins stay frozen while the bootloader runs, which fits the silence at 38400.
- Where exactly it stops is not known: the bootloader may hang (its calibration loop waits
  in Standby for an interrupt), or it may reach the application with the resume marker or
  the hardware state destroyed.

If this is right, Sleep cannot work on a tag with this bootloader, whatever the application
does, and the bootloader cannot be updated over the air. `deepsleep-debugging-fix.md` may
have been tested on a tag flashed without the bootloader in front.

Ways forward, none tried:

1. Do not use libmf's Sleep-continue. Use plain `enter_sleep()` and treat every wake as a
   restart, keeping the little state that matters in the SCRATCH register or retained XRAM.
   The bootloader still runs on every wake, so it must get through cleanly and cheaply
   (it powers the flash rail and prints on each start).
2. A new bootloader that checks PCON's wake bit first and jumps straight to the
   application. Needs every tag reflashed over the wire.
3. Stay in Standby (the current baseline) and reduce what runs in it.

A meter reading on a B tag decides whether any of this is worth doing: if B idles in the
low hundreds of microamps, Standby is already good for months.

Other leads from reading the code, none verified:

- `enter_sleep_cont()` stores its resume marker and stack pointer at the top of internal RAM
  (0xFF-0xFD). The tag's internal RAM is full, so the stack may collide with them.
- `wtimer_init()` keeps the old timer queue when PCON reports a wake from Sleep. If the
  resume fails and the tag restarts through `main()`, the timers would not run.
- `wtimer_preparesleep()` switches wake-up timer B off (`WTCFGB = 0x0F`) and Sleep resets
  the fast oscillator's calibration settings; the wake path restores neither.
- `Documentation/deepsleep-debugging-fix.md` describes an earlier round of Sleep fixes. It is
  not clear that Sleep was really reached in those tests, given fault 1.

## Still to do

1. Run B for several hours on fresh cells next to an A tag and compare the voltage curves.
2. Put a meter in series with the cell on a B tag: idle current between polls. Enter the
   result as `SHELF_PWR_SLEEP_UA` in `shelf_config.h`; the tag's `avg=`/`life=` figure is
   meaningless until then.
3. Build E-style with the sleep fix off (`--define SHELF_NFC_POLL=0 --define
   SHELF_NFC_RAIL_HOLD=0`) to see what the held rail costs on top of B.
4. Debug the Sleep wake with a serial log, then re-enable `SHELF_FIX_UART_SLEEP`.
5. The comments around `SHELF_XTAL_OFF` (`shelf_config.h`, `shelfhw_radio_sleep()`) still
   describe `OSCFORCERUN` bit 2 as the 26 MHz crystal. The switch is 0, so the code is not
   built, but the description is wrong.
