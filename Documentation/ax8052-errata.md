# AX8052 silicon errata (applied)

Source: [AX8052-ERR-D.PDF](AX8052-ERR-D.PDF) (Onsemi, Rev 3). The AX8052 in the
ShelfKit boards is a 2017-era part, so it is almost certainly **V2** (`SILICONREV`
0x90) — the decisive proof is that the tag enters `enter_standby()` every poll and
keeps polling, which the V1-only "wake from sleep resets the system controller"
erratum would have broken.

The items that matter for this firmware:

| erratum | revisions | what this firmware does |
|---|---|---|
| Wake from sleep resets system controller, stops crystals | V1 | not applicable (V1C/V2); `enter_standby()` between polls is used and verified |
| Deep-sleep wake on PB3 / RESET_N / GPIOENABLE quirks | V1 | deep sleep is not used: the radio parks in `AXRADIO_MODE_OFF`, never `DEEPSLEEP` |
| LPOSC auto-calibration glitches | V1 | not enabled; the wake timer runs from the plain LPOSC |
| FRCOSC calibration from radio clock | V1 | the FRC is calibrated from the LPXOSC crystal, not the radio clock |
| Clock-source switch accidentally enables XOSC/LPXOSC | V1 | no runtime clock-source switching |
| GP ADC missing codes at mid-scale | **V1, V1C, V2** | affects the battery reading: four channels are averaged, but the last digit of the voltage is only a hint |
| Current spike after entering standby | V1 | `wtimer_idle(WTFLAG_CANSTANDBY)` uses libmf's safe entry |

If the battery gauge ever needs to be exact, a two-point per-board calibration
against a known supply is the reliable fix for the ADC missing-code erratum.

