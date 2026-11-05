# PA2 (U5) and PA5 (U4): what the two transistor lines do

Measured with the `Shakedown/` probe on one Vusion 2.6" board (the hub, on COM4). Each line
was driven low / high / released / released with the internal pull-up, and after every change
the probe read the supply voltage, the serial flash, the NFC chip, the panel's reaction to
"power on" (0x04) and the AX5043's registers and noise floor. Commands and code:
[`Shakedown/README.md`](../Shakedown/README.md).

## Summary

| | **PA5 -> U4** | **PA2 -> U5** |
|---|---|---|
| Switches | the **e-paper panel supply** | not identified (a load on the supply) |
| Active level | **low** | **high** |
| Released (input) | reads high through a strong external pull-up (< 100 us), so U4 is **off** | **floats**: keeps the level it was last driven to |
| At boot (vendor start-up) | analog input = released = off | analog input = off |
| Firmware does | low only around panel work (`img_rx.c`), otherwise off | **parks it low** at boot and never switches it on |

## PA5 / U4: panel supply, active low

- PA5 low: the panel answers `0x04` (power on): BUSY goes low for 30-55 ms, then idle; `0x02`
  (power off) takes 40-60 ms.
- PA5 high, released, or released with pull-up: BUSY sits low permanently and never reacts. The
  panel has no supply.
- A released PA5 reads 1 even right after being driven low, so the board pulls it up. That is
  why a tag that never touches PA5 has the panel off, and why `pwr_init()` drives it off
  explicitly anyway (floating, the dead panel is back-powered through its SPI pins).
- Switching PA5 changes the supply voltage by nothing measurable while the panel is idle.

### The flash and NFC did not follow U4

The serial flash answered with its real id (`1F 42 00`, an Adesto AT25XE011) in **every** state,
PA5 high included, and the NFC bus gave the same bytes in every state. The older notes say the
flash sits on the rail U4 switches and reads `FF` when it is off. On this board that did not
reproduce. Two explanations fit, and the data cannot separate them:

1. the board was supplied through the `+3V3` pad, which is downstream of U4, so the rail never
   dropped; or
2. the chip was kept alive through its SPI pins (back-powering), as the panel is.

So the firmware still powers the rail (`extflash_power_up()`/`_down()`) around flash and NFC
access. It costs nothing and is correct if explanation 1 is wrong. Re-test on a battery-powered
tag before relying on either behaviour (`2z`/`5h`, then `p`).

## PA2 / U5: a load, off at boot, no pull

- Released after being driven low it stays 0; after being driven high it stays 1 (read back at
  0.1, 1, 10 and 100 ms). There is no pull resistor, so the pin keeps whatever level it holds.
- Driven high (or released after high) the supply reads **about 75 mV lower** (3.30 V -> 3.23 V),
  within 80 ms, every time (six alternations). LEDs and the radio at several mA moved the same
  reading by under 8 mV, so this is a real load, not a measurement artefact. Its size in mA is
  unknown (needs a meter in series).
- With PA2 high, nothing we can see got better or worse: flash, NFC, panel, AX5043 revision,
  crystal status, power status and RSSI noise floor were identical to PA2 low.
- Not tested: the RF path. Whether U5 is an antenna switch, PA or LNA supply needs a second
  board sending frames while PA2 toggles on the receiver (`x2`).

## What changed in the firmware

- `pwr_park_u5()` (`src/pwr.c`, tag and hub): PA2 as an output, driven low. `pwr_init()` calls it
  (the tag already calls `pwr_init()` first thing in `main()`); the hub calls it at boot. A line
  with no pull resistor should not be left to float, and low measured as the lowest-draw state.
- `PWR_USE_U5` stays 0: `pwr_on()` drives U4 only, so nothing in the image path can switch U5 on.
- `SHELF_POWER_LINES` is documented as what it is: it holds the **panel supply** on. It never
  helped the radio, and it never will. Leave it 0.

## Caveats

One board, one supply, one session. The supply reading is the MCU's own ADC against its
reference, so "75 mV" is a relative number. Confirm with a meter before drawing power-budget
conclusions about U5.
