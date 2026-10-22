# Deep-sleep wake debugging and fix (Vusion tag)

## Symptom

With `SHELF_RADIO_SLEEP=1`, `SHELF_RADIO_DEEPSLEEP=1` and `SHELF_MCU_SLEEP=1`, the first poll after boot succeeded. Every poll after a sleep failed with `poll FAILED after 4 attempts`. The tag logged `wake` with no "radio wake failed", so `axradio_set_mode(ASYNC_RECEIVE)` returned OK. The hub never heard the tag's transmissions.

## Causes

The cause was a set of state that the AX8052 and AX5043 lose or leave wrong across Sleep and deep sleep. Per the AX8052 programming manual (AND9349/D, "Power Modes"), Sleep powers down the CPU and the registers of the powered-down peripherals. The continue-after-sleep path in libmf only restores the stack and jumps back, so the firmware has to restore the rest itself. Several things were missing. I did not isolate which of them was decisive, because the fixes were flashed together.

1. **MCU pins and interrupts after Sleep.**
   - `GPIOENABLE` is cleared by `enter_sleep_cont` and by the wake, so it must be set back to 1.
   - The interrupt enable (`IE`) was not restored, so the radio interrupt (IE_4) stayed disabled. TX waits on the radio IRQ for the crystal-ready event and for FIFO service, so transmit stalled.
   - The radio SPI mux (`RADIOMUX`) was not restored on the OFF-mode path. `axradio_commsleepexit()` is now called there.
2. **Frequency not programmed after deep-sleep wake.**
   - `axradio_set_channel` writes the frequency into the FREQ set (A or B) that `PLLLOOP` bit 7 does not select, then flips the bit.
   - After deep sleep the chip is reset, and FREQA was never written again (init only writes it once, for channel 0). The radio was therefore on the wrong frequency.
   - The wake case in `axradio_set_mode` now writes `PLLLOOP = 0x89` first, so the frequency lands in FREQA.
3. **PORTR left with pull-ups.**
   - The libmf deep-sleep wake sets `PORTR = 0xEB`, which enables pull-ups on PR6/PR7.
   - `sl_init()` removes them via `axradio_setup_pincfg2()` after bring-up, but the wake path never did.
   - The wake path now calls it too.
4. **Wake failures were ignored.**
   - If the wake handshake or PLL ranging fails, the engine returns early and stays in `AXRADIO_MODE_DEEPSLEEP`, so the receiver was never turned on.
   - `shelfhw_radio_wake()` now retries up to 8 times with about 4 ms between tries. It waits for the PLL after the mode change, not before. It returns an error that `poll_cb` checks.

## Changes

- `Shared/firmware/shelfhw/shelfhw.c`
  - Added the `radio_deep` flag.
  - The radio interrupt is now disabled when the radio is parked and re-enabled on wake.
  - `shelfhw_radio_wake()` now retries and returns `uint8_t`.
  - It calls `axradio_setup_pincfg2()`.
  - `shelfhw_poll()` restores `GPIOENABLE` and `IE` after a Sleep wake. It also calls `axradio_commsleepexit()` and `axradio_setup_pincfg2()` when the radio is not in deep sleep.
- `Shared/firmware/shelfhw/inc/shelfhw.h`: new `shelfhw_radio_wake` prototype.
- `Shared/firmware/axradio/easyax5043.c`: `PLLLOOP = 0x89` on deep-sleep wake. It also gained `axradio_dbg_snapshot()`, a register snapshot (PWRMODE, POWSTAT, PLLLOOP, PLLRANGINGA, FREQA) for diagnosing this kind of problem.
- `Shared/firmware/axradio/inc/axradio.h`: declares `axradio_dbg_snapshot()`.
- `Vusion/src/main.c`: `poll_cb` handles a wake failure, and a `radio ...` register line is logged after each wake.

## Notes

- Never write `PCON` from the poll path (the SWRESET bit causes a boot loop).
- To isolate sleep problems in future, use `SHELF_RADIO_DEEPSLEEP 0` (radio OFF mode) and `SHELF_MCU_SLEEP 0` (MCU Standby only) in `Vusion/include/shelf_config.h`.
- The diagnostic `radio ...` log line is still in `main.c`. It can be removed once the fix is accepted.
