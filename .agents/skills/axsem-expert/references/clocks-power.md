# Clocks, oscillators, power modes, wake-up timers, watchdog

Sources: AND9349/D "Power Modes", "Clock", "Wakeup Timer", the F143 datasheet, LibMF manual §3.3 and §3.10,
`Documentation/power-findings-2026-11-13.md`, `power-audit.md`, `deepsleep-debugging-fix.md`.
The MCU and the radio have **separate** power states. This file covers the MCU. The radio is in radio-ax5043.md.

## Oscillators

| Oscillator | Freq | Pins | Use here |
|---|---|---|---|
| **FRCOSC** | 20 MHz RC (calibratable) | - | System clock (`CLKCON = 0`), UART baud, wtimer1 |
| **LPOSC** | 640 Hz or 10.24 kHz RC | - | Fallback wake-timer source (`SHELF_WAKE_LPXOSC` undefined), about 10 % slow uncalibrated |
| **LPXOSC** | 32.768 kHz crystal | **PA3/PA4** | Wake-up timer 0 (512 Hz with prescaler 7). FRCOSC calibration reference |
| **XOSC** | external crystal (MCU's own) | **PA0/PA1** | **Never.** No crystal on this board: PA0 = panel D/C, PA1 = panel CS |
| **RSYSCLK** | from the AX5043 (its 26 MHz crystal, divided) | internal | Optional precise clock. Costs radio current, so leave it off |

- `CLKCON` (SFR 0xC6): CLKSRC bits 2:0 (000 FRCOSC, 001 LPOSC, 010 XOSC, 011 LPXOSC, 100 RSYSCLK), CLKPRE bits 5:3 (prescaler; the reset value is ÷2), CLKMON bits 7:6. `CLKSTAT` shows the actual source. A clock monitor can fall back to FRCOSC if the selected source stops.
- `OSCFORCERUN`: bit 0 FRC, bit 1 LPOSC, **bit 2 XOSC**, bit 3 LPXOSC. These force-run an oscillator even when nobody requests it. The manual says never enable a crystal oscillator without a crystal. Once XOSC is running it keeps going until a reset or falling edges on its pins. libmf `turn_off_xosc()` / `turn_off_lpxosc()` clear the force bit and toggle the pins to stop it.
- `MISCCTRL` bit 0 LPXOSCDIS and bit 1 XOSCDIS permanently disable an oscillator (V1C and later). XOSCDIS is a candidate hardening for this board. Not applied yet: ask before changing.
- `LPXOSCGM` sets the LPXOSC transconductance (0x90 here).
- **FRCOSC calibration against LPXOSC** (the bootloader's sequence, repeated in `shelfhw_init`):
  - Set `FRCOSCREF = 19531` (the target ratio for 20 MHz against the 32.768 kHz crystal at this divider setting; the formula is under `Register: FRCOSCREF` in AND9349), `FRCOSCKFILT = 2800`, `FRCOSCCONFIG = (6<<3) | CLKSRC_LPXOSC`.
  - Start `OSCCALIB = 0x01` and enable the clock-management interrupt `IE_5`.
  - Loop 128 times: `while (!(OSCCALIB & 0x40)) enter_standby(); (void)FRCOSCFREQ1;`.
  - Then `IE_5 = 0`, `OSCCALIB = 0`.

  This is needed for exact 38400/115200 baud. **Sleep resets the calibration**, and nothing restores it on wake.
- Errata (V1 only, so not this silicon, but the libmf helpers handle it): switching clock sources could enable XOSC/LPXOSC by accident. `wtimer*_setclksrc` "take care not to accidentally enable a crystal oscillator". Use them rather than writing `WTCFGx` directly.

## MCU power modes (`PCON` bits 1:0)

| Mode | PCON.PWRMODE | Current (datasheet) | Kept | Wake sources | Restarts at |
|---|---|---|---|---|---|
| Running | 00 | ~150 µA/MHz | all | - | - |
| **Standby** | 01 | **~85 µA** + running peripherals | everything: RAM, all registers | **any enabled interrupt** | continues after the instruction |
| **Sleep** | 10 | 0.5-1.5 µA (0.9 µA with 256 B RAM, 1.5 µA with 4 KB XRAM, 2.2 µA with 8 KB) | IRAM, chosen XRAM halves (`PCON` XRAMKEEP 3:2), SCRATCH0-3, wake timer, GPIO logic | wake-up timer, **port change** interrupt | **0x0000** (reset vector) |
| Deep Sleep | 11 | ~50-100 nA | SCRATCH0-3 only. Pins frozen (`GPIOENABLE=0`) | **only the dedicated pin PB3 going low** (and reset) | 0x0000 |

Facts that matter:

- **Standby** needs an interrupt **enabled** (its `IE_x` bit and `EA`) to wake. In this project that is the wake-up timer, `IE_1`. The vendor demo enabled `IE_3`, which was wrong here. Enter it with `enter_standby()` (it adds the NOP the manual demands after writing PWRMODE=01) or `wtimer_idle(WTFLAG_CANSTANDBY)`.
- **Sleep and Deep Sleep restart at 0x0000.** Peripheral registers are reset "similar to power-on reset". `PCON.WAKEUP` (bit 6) tells a wake from a reset. Peripherals that are reset include the UART, timers, SPI, ADC, radio interface (`RADIOMUX`), FRC calibration, IE/EIE/E2IE, `EXTIRQ`, and `GPIOENABLE` (0 after deep sleep, and `enter_sleep_cont` also clears it).
- A connected **debugger keeps the MCU domain powered**, so Sleep and Deep Sleep behave differently (and draw more current) with DebugLink attached. Use libmf `enter_sleep()` / `enter_deepsleep()`.
- `PCON` bits 7:4 are status flags (BROWNOUT, WAKEUP, WDTRESET, SWRESET). **SWRESET is RW: writing 1 resets the chip, and it reads 1 after a software reset.** Any read-modify-write of PCON after a software reset therefore resets again: a boot loop. That happened on this project. Write PCON only as `PCON = (PCON & 0x0C) | <bits>` and only once at init. The rest of the time use libmf entry functions.
- **Brown-out**: the power-management interrupt (`INT_POWERMGMT`, `IE_6`) fires with `PCON.7` set. The project's handler freezes the GPIOs, disables interrupts and parks in standby forever. Brown-out is about 1.3 V. The supply range is 1.8-3.6 V.

### libmf entry points (AX8052, SDCC)

| Call | Behaviour |
|---|---|
| `enter_standby()` | write PWRMODE=01 + NOP. Returns after the interrupt |
| `enter_sleep()` | Sleep, `noreturn`. Wake restarts through reset. Set XRAMKEEP in PCON yourself first (bits 1:0 written 00) |
| `enter_sleep_cont()` | Sleep, then **returns** after wake. libmf saves SP + a signature at the top of IRAM. The startup (`_sdcc_external_startup` is called again) recognises it and resumes. All peripherals except the system controller must be re-initialised. SDCC only, not with `--xstack` |
| `enter_deepsleep()` | Deep sleep, `noreturn` |
| `wtimer_idle(flags)` | Scheduler-aware idle: standby or sleep depending on flags and pending timers. Returns `WTIDLE_WORK` (events pending), `WTIDLE_SLEEP` (came back from sleep_cont: **re-initialise peripherals now**), or 0 |
| `wtimer_cansleep()` | 0 if wtimer1 has events, or a UART / DebugLink still has TX queued (vetoes linked into section `WTCANSLP*`) |

### The open Sleep problem on these tags (as of 2026-11-13)

- **Fault 1 (found)**: `log_putc()` set `U0CTRL` bit 3 (U0TXIE) after every character. Nothing cleared it, so libmf's UART veto made `wtimer_cansleep()` false forever and the MCU only ever reached Standby. Switch: `SHELF_FIX_UART_SLEEP` (default **0** = old behaviour).
- **Fault 2 (fixed)**: `OSCFORCERUN |= 0x04` forced XOSC on with no crystal. The bootloader still does this on every reset, so the app calls `turn_off_xosc()` (`SHELF_FIX_XOSC=1`). In the comparison test this alone stopped the fast voltage drop.
- **With real Sleep enabled the tag never comes back** (builds C/D). Most likely cause, unproven: wake restarts at 0x0000 = **the bootloader**, which knows nothing about `enter_sleep_cont`. It resets SP, rewrites the ports, recalibrates, powers the flash rail and leaves `GPIOENABLE=0`. Other suspects:
  - the resume marker at IRAM 0xFD-0xFF colliding with a full stack
  - `wtimer_init()` keeping the queue on a wake
  - `WTCFGB` being switched off
  - lost FRC calibration
- Options, none tried:
  1. Plain `enter_sleep()`, treating every wake as a restart, with state in SCRATCH0-3 or retained XRAM.
  2. A new bootloader that checks `PCON.WAKEUP` first and jumps straight to the app. This needs every tag reflashed by wire.
  3. Stay in Standby.
- **Baseline: build B** (XOSC fix on, Sleep fix off), so the MCU uses Standby between polls and the radio is in deep sleep. Keep it unless the user says otherwise.

### After a Sleep wake (what `shelfhw_poll` restores)

```c
woke = wtimer_idle(WTFLAG_CANSLEEPCONT | WTFLAG_CANSLEEP | WTFLAG_CANSTANDBY);
if (woke == WTIDLE_SLEEP) {
    GPIOENABLE = 1;              /* pins were frozen */
    IE = 0x40;                   /* IE_6 power management; EA set later */
    log_uart_start();            /* UART was reset */
    if (!radio_deep) {
        axradio_commsleepexit(); /* RADIOMUX etc. */
        axradio_setup_pincfg2(); /* PORTR without PR6/PR7 pull-ups */
        enable_radio_interrupt_in_mcu_pin();
    }
}
/* NFC: re-arm EXTIRQ / INTCHGB, they were reset too */
```

## Wake-up timer (WTIMER)

- Two 32-bit counters: **wtimer0** (slow clock, keeps running in Sleep) and **wtimer1** (fast clock, stops in Sleep). There are four event (match) registers.
- Registers:
  - `WTCFGA` / `WTCFGB`: clock source and divider.
  - `WTCNTA*`, `WTCNTB*`: counters. Reading the low byte latches the rest (`WTCNTR1`).
  - `WTEVTA*` .. `WTEVTD*`: match registers.
  - `WTIRQEN`: interrupt enables.
  - `WTSTAT`: **clear-on-read with level semantics**. Read it, update the WTEVT, then read again.
- The interrupt is `INT_WAKEUPTIMER` (1), enable `IE_1`. libmf owns it (`wtimer_irq`).
- Here:
  - `wtimer0_setclksrc(CLKSRC_LPXOSC, 7)` gives **512 Hz**. `SHELFHW_TICKS_PER_S = 512`. Prescaler 6 measured as ~1024 Hz.
  - `wtimer1_setclksrc(CLKSRC_FRCOSC, 7)`.
  - One arm holds at most 128 s (`SHELF_POLL_ARM_MAX_S`). Longer waits wake up to step a counter.
- Prescaler argument for `wtimerN_setclksrc`: 1 → ÷1, 2 → ÷2, 3 → ÷4 ... 7 → ÷64. 0 is a special value; the PDF extraction garbled its meaning, so check LibMF §3.10.9 before using it. Measure the real rate on hardware: the project's datasheet arithmetic was off by one step once.
- Use libmf's scheduler (`wtimer0_addrelative` and friends) rather than raw registers. See libmf-axradio.md.

## Watchdog

- `WDTCFG`: bit 4 WDTENA, bit 5 WDTLCK (locks the config until reset), plus clock source and divider. Kick it by writing **0xAE to `WDTRESET`**.
- After a watchdog reset `PCON.WDTRESET` reads 1. Not currently enabled in ShelfKit. If you add it:
  - the watchdog clock keeps counting through standby
  - check what it does in Sleep
  - kick it in the main loop, never in an ISR

## SCRATCH registers

`SCRATCH0`-`SCRATCH3` (32 bits) survive Deep Sleep and Sleep. They are the place for state across a restart-style wake, e.g. a "woke from planned sleep" flag and a sequence counter.

## Current budget reference (tag)

These come from `shelf_config.h`'s software ammeter constants (estimates, not measured):

| Item | Current |
|---|---|
| MCU running on 20 MHz FRC | ~3 mA |
| Radio receiving | ~9.5 mA |
| TX | ~140 µAs per frame |
| Panel refresh | ~8 mA |
| Sleep | `SHELF_PWR_SLEEP_UA` (3 µA, unmeasured) |

Things outside the MCU dominate idle:

- PA5 rail held on (flash standby ~25 µA, NFC, panel controller)
- LED pulses
- a forced oscillator

Measure with a meter in series with the CR2450 before trusting `avg=`/`life=`.
