# AX8052 silicon errata

Source: `vendor/AX8052-errata.txt` (onsemi AX8052-ERR-D, Rev 3), `Documentation/ax8052-errata.md`.
Read the silicon revision from `SILICONREV`: 0x8E = V1, 0x8F = V1C, 0x90 = V2. **The ShelfKit tags are almost
certainly V2.** Evidence: standby between polls works, and the V1 sleep-wake erratum would have broken it. If
you depend on the revision, log `SILICONREV` once at boot to confirm.

| Erratum | Revisions | Effect | Workaround / status here |
|---|---|---|---|
| Deep-sleep wake on PB3 | V1 | wake pin unreliable | not V1 |
| RESET_N does not wake from deep sleep | V1 | | not V1 |
| Wake from sleep resets the system controller and stops the crystals | V1 | LPXOSC/XOSC stop after sleep | not V1 |
| Clock monitor | V1 | false switching | not used |
| LPOSC calibration glitches | V1 | wake-timer jitter | not enabled; the wake timer uses LPXOSC |
| FRCOSC calibration from the radio clock | V1 | wrong frequency | FRC calibrated from LPXOSC |
| Clock-source switch enables XOSC/LPXOSC | V1 | crystal oscillator starts on its pins | no runtime switching; use `wtimer*_setclksrc` (safe sequences); write WTCFG in the documented order |
| Current spike after entering standby | V1 | needs 7 NOPs | libmf `enter_standby()` handles it |
| CPU clock below 10 kHz | V1 | malfunction | never run the CPU from LPOSC/LPXOSC directly |
| Temperature sensor | V1, V1C | wrong reading unless converted in standby | `ADCCLKSRC = 0x30`, convert in standby |
| Power-on ramp / RESET_N during ramp | V1, V1C | | board level |
| Timer clear-on-read precedence | V1, V1C | a flag set during the read can be lost | re-check status after clearing |
| **GPADC missing codes at mid-scale** | **V1, V1C, V2** | some ADC codes never appear | **applies here**: the battery voltage's last digit is only a hint; four-channel averaging; for accuracy use a per-board two-point calibration |

When something smells like silicon, grep the errata text for the peripheral name before inventing a workaround.
