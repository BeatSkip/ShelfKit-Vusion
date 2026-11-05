# Vusion tag power deep-dive (CR2450)

Status: **model only, nothing measured yet.** Currents below are datasheet-class
estimates (AX5043 RX ~11 mA, TX 15 dBm ~54.6 mA, MCU active ~4 mA, sleep ~3 uA).
Step 0 is to meter a real tag; every ranking below should be re-run with measured
numbers. Usable capacity assumed 620 mAh x 0.85 = 527 mAh (CR2450 datasheets:
Panasonic/Energizer ~620 mAh at 15k/2.0 V cutoff, Jauch 610 mAh; max pulse 15-50 mA,
max continuous 3-4 mA, cold and high-pulse loads reduce delivered capacity).

## Where the energy goes (baseline: 120 s poll, 700 ms grace, 15 dBm, 2 updates/day)

Per poll about 8.1 mAs:

| Part | mAs | Share |
|---|---|---|
| Receive grace window 0.7 s @ 11 mA | 7.70 | ~95% |
| TX 3 ms @ 54.6 mA | 0.16 | 2% |
| Wake + register re-init 12 ms | 0.10 | 1% |
| RSP wait | 0.09 | 1% |
| MCU/logging | 0.02 | <1% |

Daily: polls 1.61 mAh + image updates 2 x 0.12 + sleep 0.07 => ~275 days (~9 months).

## Options, ranked (from a simple per-poll charge model)

| # | Option | Life (months) | Effort | Risk |
|---|---|---|---|---|
| 1 | Drop grace window when RSP says no data (sleep immediately) | 9 -> ~45 | small (tag `on_done`/`listen_cb`) | RSP loss => missed hub command until next poll; keep short grace only after a failed RSP |
| 2 | Trim grace 700 -> 250 ms (fallback if #1 too bold) | 9 -> 18.5 | trivial (`SHELF_LISTEN_GRACE_MS`) | hub latency must be under 250 ms |
| 3 | Poll interval 120 -> 300 s (adaptive backoff exists) | 9 -> 18 (alone) | config | slower response to queued data; pre-arm (`Q`) mitigates |
| 4 | Poll 600 s | 9 -> 27 | config | latency 10 min |
| 5 | #1 + 300 s poll + 10 dBm | ~50 | small | range margin; check RSSI first |
| 6 | Cache radio calibration across wakes (skip VCO ranging) | +<1% after #1; ~3% | medium | DEEPSLEEP loses regs; see deepsleep-debugging-fix.md |
| 7 | TX 15 -> 10 dBm | ~0% at baseline, ~+3% after #1 | trivial | range |
| 8 | Shorter image transfers (skip all-white red plane, compression) | update cost 0.12 -> ~0.07 mAh: +5% at 2/day, large at 10+/day | medium | protocol change |
| 9 | Limit update frequency | 2 -> 10 updates/day costs 9 -> 6 months | policy | none |

Key insight: the listen grace dominates until it is cut. After #1, the remaining budget
is ~0.07 mAh/day for polls, so sleep floor, image updates and TX/wake overhead become the
levers (options 6-9), and CR2450 self-discharge (<1%/yr) and cold-temperature capacity loss
matter more than any firmware tweak.

## Recommended order
1. Meter one tag (shunt + scope or PPK2): confirm sleep current, wake/re-init time, RX current, grace window charge.
2. Do #1 (or #2), then #3 via adaptive backoff, then #5.
3. Re-measure; only then consider #6-#8.

## Caveats
- All figures are modelled; wide error bars until metered. Datasheet PDF text shows micro as "m": values were interpreted as uA/us.
- 868 MHz sub-band duty-cycle limit (1%) is not a constraint at these rates (3 ms TX per poll).
- Cold (-20 C) reduces CR2450 delivered capacity noticeably, especially under 50 mA TX pulses; consider a bulk capacitor if brown-outs appear.
