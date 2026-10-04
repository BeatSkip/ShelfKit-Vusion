# Wireless link (868 MHz) — design, findings, status

Hub (`Shelfkit-Hub`) and tag (`Shelfkit-Vusion`) run on identical hardware and share all radio code in
`shared/firmware/`. This document records what was found, how the link works, what was verified on
hardware, and what is left.

## Status (2026-10-05)

Verified on two real boards (hub on COM4, tag on COM3, a few cm apart):

- Both boards detect the on-chip AX5043 radio (`pll rng=10`).
- The tag polls every ~5.6 s with the main loop in standby (see [Timing](#timing)); the hub answers each poll.
  14 consecutive polls: all acknowledged on the **first attempt**, RSSI −33…−38 dBm on both sides.
- 62 host-side unit checks pass on the SDCC simulator: `python tooling/test_shelflink.py`.

Not yet measured: packet loss over a long run, range, behaviour with retries (never needed so far),
the effect of the PA2/PA5 transistor lines on range, LED polarity.

## Findings

| # | Finding |
|---|---|
| 1 | The AX8052F143 has the **sub-GHz AX5043** radio on-chip, not a 2.4 GHz radio (the old READMEs say 2.4 GHz — wrong). |
| 2 | The generated `WirelessDemo/` is one-way (ASYNC_TRANSMIT master, ASYNC_RECEIVE slave), button-triggered, no ACK, and written for the Axsem *Minikit* (LED lib, COM0 display, button on PC4, whole-port writes). Its pin setup would clobber the tag's EPD/NFC/flash pins, so only the radio engine and PHY config were reused. |
| 3 | PHY (from `config.c`): 868.300 MHz, FSK, 25 kHz deviation, 100 kbit/s, 15 dBm, 26 MHz crystal, sync word `CC AA CC AA`, 3-byte hardware-filtered address, hardware CRC-16. |
| 4 | **SDCC-MDF links component libraries *after* `libmf.lib`**, so a component that calls libmf would fail. Therefore the shared code is added as plain `sources` entries (`../shared/firmware/<name>`) plus `includes`, not as `components`. |
| 5 | **`libmf.lib` as shipped makes the linker exit with status 1.** It was built with `--debug`, so 29 global debug labels (`C$libmftypes.h$351$4$73`, …) are defined by several modules. Any radio firmware links two of them → "Multiple definition", exit 1, which SDCC-MDF reports as a failed build (the `.ihx` is still written). Fixed by `tooling/patch_libmf_labels.py`, which renames the repeats in place (same length, archive offsets stay valid, idempotent). `shared/lib/libmf.lib` is committed-in-patched form. |
| 6 | The same label clash also hit the engine itself (inline `enter_critical()` from `libmftypes.h`); `easyax5043.c` now has local static copies of those helpers. |
| 7 | SDCC 3.6.0: function pointers with several arguments must be `__reentrant`; the shelflink "done" callback therefore takes one struct pointer. |
| 8 | **Standby needs the wake-up-timer interrupt enabled.** `wtimer_idle(WTFLAG_CANSTANDBY)` enters standby with `EA = 0`; standby only ends if the wake source's enable bit is set in `IE`. The demo uses `IE_3` — that is Timer 1 on the AX8052, not the wake-up timer. The wake-up timer is vector 1 → **`IE_1`**. Without it the tag slept forever after its first poll. Fixed in `shelfhw_poll()` (the radio interrupt, `IE_4`, is enabled by the engine). |
| 9 | Pin/clock facts used: UART0 TX on PB4 at 38400 (needs the FRC oscillator slaved to the 32 kHz LPXOSC, sequence copied from the existing demo); PB5 (EPD reset / UART RX) is never driven; chip selects PA1/PB1/PC0 are parked high at boot. |
| 10 | Loading the debug firmware shows `rssi≈−35 dBm` at a few cm — the receiver is not saturated and reception is clean at this distance. |

## Architecture

```
shared/firmware/
  axradio/    vendor radio engine (easyax5043.c, axradio.h) + PHY config (config.c) + axradio_platform.h glue
  shelfhw/    board bring-up, wake-up timers, LEDs, UART0 TX log (log_*), shelfhw_poll() main-loop step
  shelflink/  shelflink.c   acknowledged request/response state machine
              sl_proto.c    pure frame build/parse + duplicate filter (host-testable)
              shelfmsg.h    application payloads (POLL / POLL_RSP)
<target>/include/shelf_config.h   node id, network id, poll interval, SHELF_POWER_LINES
<target>/src/main.c               hub: listen + answer;  tag: periodic poll
```

Both projects list the three `shared/firmware/*` folders under `sources` and their `inc/` folders under
`includes` in `sdcc-project.json` (and in `.vscode/c_cpp_properties.json` for IntelliSense).

### Radio mode

Both nodes stay in `AXRADIO_MODE_ASYNC_RECEIVE` permanently. Calling `axradio_transmit()` from that mode
makes the engine switch to TX and fall back to RX when the packet is out, so a node hears the reply to its
own transmission with no mode juggling. Cost: the receiver is always on (fine for the hub; the tag will need
a low-power scheme later).

### Frame

Engine frame: length byte, 3-byte address, payload, CRC-16 (hardware).

```
address (3)   dest node id lo, dest node id hi, network id        (hardware filtered, mask FF FF FF)
payload:
  [0]     version (high nibble, =1) | type (low nibble)
  [1]     flags            bit0 = retry
  [2..3]  source node id, little endian
  [4]     sequence number
  [5..]   data, 0..32 bytes
```

Types: `1 POLL`, `2 POLL_RSP`, `3 DATA`, `4 ACK`. Hub node id is `0x0001`; tags use `0x0100` and up.
Network id `0x5A` (both ends must match).

### Reliability

- Initiator (`sl_send`): transmit, open a 60 ms response window, if nothing matching arrives wait a random
  5 + (0…20·attempt) ms and retransmit (same sequence number, retry flag set), up to 4 transmissions, then
  report `SL_ERR_NORESPONSE`. A response matches on source node **and** sequence number; a late answer to an
  earlier attempt still counts.
- A transmission refused by the engine is counted (`tx_err`) and handled like a lost one.
- Responder: DATA is acknowledged automatically (also duplicates, so a lost ACK is repaired) but delivered to
  the application once; POLL is delivered every time with `dup` set on repeats, and the application answers
  with `sl_reply()` quickly (the tag only waits 60 ms).
- Duplicate filter: last sequence number per source, 8 sources, round-robin eviction.
- Tunables (`-D` in `sdcc-project.json` `defines`): `SL_RSP_TIMEOUT_MS`, `SL_MAX_ATTEMPTS`, `SL_BACKOFF_MS`.
- Counters in `sl_stats`: `tx_req tx_att tx_ok tx_fail tx_err rx_ok rx_dup rx_bad rx_stray`.

### Application payloads (`shelfmsg.h`)

- POLL (tag→hub, 4 B): uptime s (u16 LE), attempts the previous poll needed, RSSI of the hub's previous answer (i8).
- POLL_RSP (hub→tag, 2 B): command (`SM_CMD_NONE` for now), RSSI the hub measured (i8).

### Timing

wtimer0 runs from the on-chip LPOSC, nominally 640 Hz. Measured poll interval is ~5.56 s for a nominal
5 s, i.e. the LPOSC runs ~10 % slow. Not a problem for polling; use the 32 kHz crystal (`LOWFREQ_QUARZ`
style, 8192 Hz) for anything time-critical. Wall-clock timestamps from the monitor are the reference.

## Debug output and tools

Both firmwares log on UART0 TX (PB4, 38400 8N1). LEDs: blue = radio up, green = poll ok / hub frame
toggle, red = poll failed or radio init failed (polarity unverified, see below).

Example (tag / hub):

```
poll ok att=1 rssi=-35 hubrssi=-36
POLL src=0100 seq=09 rssi=-36 up=6s att=1 hubrssi=-35
```

| Tool | Use |
|---|---|
| `tooling/monitor.py hub=COM4 tag=COM3 [--reset] [--log f] [--summary 60]` | Timestamped merged log of both boards plus a loss/attempt/RSSI summary. Holds DTR/RTS low so opening a port doesn't reset the tag. |
| `tooling/axsem-flasher.py <hex> -p COMx` | Flash over the AX8052 serial bootloader (works). |
| `tooling/test_shelflink.py` | Simulator unit tests (`sl_proto_test.c`: 22 checks, `shelflink_test.c`: 40 checks with stubbed radio/timers). |
| `tooling/patch_libmf_labels.py` | Re-apply the `libmf.lib` label fix if the library is ever rebuilt/restored. |

Build memory (SDCC 3.6.0): hub ≈ 36.7 KB, tag ≈ 37.1 KB of 59 389 B code; XRAM ≈ 1 KB of 8 KB;
**internal RAM is tight** — 139–140 B of stack left, "no spare internal RAM" on the tag. Watch this when
adding features (put buffers in `__xdata`).

Building: SDCC-MDF builds each target as before (open the target folder, Ctrl+Shift+B). The
`upload` section of `sdcc-project.json` already points at `axsem-flasher.py`, so *SDCC: Flash* uses it
(set `sdcc.comPort`). During this session builds were verified with an equivalent manual SDCC script;
**please run one real SDCC-MDF build per target** to confirm the extension accepts the `../shared/firmware`
source entries and no longer reports a failed link.

## Open questions / next steps

1. **Long-run loss test**: `python tooling/monitor.py hub=COM4 tag=COM3 --summary 60 --log run.txt` for hours;
   then repeat at distance / through walls. Expect near-0 % loss at short range; failures show up as
   `att=2+` or `FAILED`.
2. **PA2/PA5 transistor lines** are unidentified and off by default (`SHELF_POWER_LINES 0` in
   `shelf_config.h`). They may be an RF switch / PA supply; compare RSSI/range with them on.
3. **LED polarity**: the pin map says active low, the firmware assumes active high
   (`SHELFHW_LED_ACTIVE_HIGH`). Confirm which LED lights and flip the define if inverted.
4. **Clock**: switch wtimer0 to the 32 kHz crystal for accurate intervals.
5. **Tag power**: receiver is always on. Planned model is tag-initiated (wake, POLL, short RX window, sleep).
   Needs `MCU_SLEEP`-style deep sleep and radio power-down between polls.
6. **Duty cycle**: 868.3 MHz is in the 1 % sub-band. A ~14-byte frame at 100 kbit/s is only a few ms of air
   time (plus 112-bit preamble), so 5 s polling is far inside the limit, but retries and many tags must be budgeted.
7. **Hub RX→TX→RX turnaround** against the tag's 60 ms window has not been measured (works at 1 attempt so far).
8. Tag identity is a compile-time define; several tags need distinct `SHELF_NODE_ID` (0x0100+), and the hub
   must answer many sources (duplicate table holds 8).
9. READMEs (root and both targets) still say "2.4 GHz" and describe the old e-paper demo as `main.c`. The e-paper
   demo `main.c` was replaced (it is in git history, commit `69eb9fe`); the e-paper drivers are still in
   `Shelfkit-*/src` and compiled but unused by `main.c`.
10. Nothing is committed yet. `WirelessDemo/` is untracked and was left unmodified as the vendor reference.
    `tooling/__pycache__/` should be git-ignored.
