# The ShelfKit boards: Vusion 2.6" tag and hub

Sources: `Documentation/signal-list.md`, `ses-imagotag-vusion.md`, `pa2-pa5-findings.md`, `nfc-field-detect.md`,
`wireless-link.md`, `ota-update.md`, `power-*.md`, `ShelfKit-Firmware/*/README.md`, `Tooling/README.md`.
The project docs are the record of what was measured on hardware. When this file and a doc disagree, read the doc
and the code. When a doc and the code disagree, the code (and `shelf_config.h`) is what runs.

## Hardware

- SES-imagotag Vusion 2.6" BWR label, variant UU340. CR2450 coin cell (nominal 620 mAh).
- **AX8052F143** with the radio crystal at 26 MHz and a 32.768 kHz crystal on PA3/PA4.
- Good Display **GDEW026Z39** e-paper panel: 296×152, black/white/red, IL0373 controller, SPI, OTP waveform. It is driven rotated, 152 wide × 296 tall, as two 5,624-byte planes, streamed (it doesn't fit in XRAM).
- **NFC**: FM11NT081DS. It only works in SPI mode 1, and its field-detect (FD) output is configured in its EEPROM.
- **SPI NOR flash** (AT25XE011-class, about 128 KiB):
  - sector 0: the OTA header ("SKFW")
  - sector 1: the identity record
  - sector 2: reserved
  - from sector 3: the image

  On first boot with no valid identity, the firmware wipes sectors 0-11.
- The hub is the **same hardware** running `Vusion-Hub/`: always listening, UART line protocol at 115200 to the host (`ShelfKit-Server`).

## Pin map (authoritative: `Documentation/signal-list.md`)

| Pin | Function | Notes |
|---|---|---|
| PA0 | panel D/C | **also the MCU XOSC pin**: never enable XOSC |
| PA1 | SPI CS, panel | **also XOSC**. `turn_off_xosc()` toggles PA0/PA1 briefly (no SPI clock, so the panel ignores it) |
| PA2 | transistor U5 | active high, no pull, a load on the supply. **Parked low** |
| PA3 / PA4 | 32.768 kHz crystal (LPXOSC) | `ANALOGA = 0x18` |
| PA5 | transistor U4: **panel / flash / NFC rail, active low**, external pull-up | Without it the panel takes a frame but never refreshes, the flash reads 0xFF, and NFC is dead. Holding it low costs current (rail loads plus fighting the pull-up) |
| PB0 | white LED | pulse only |
| PB1 | SPI CS, NFC | |
| PB2 | panel BUSY | **active low** on this board |
| PB3 | **BOOT strap** and **NFC field-detect** | EXTIRQ1 default pin; falling edge = `EXTIRQ` bits 5:4 = 11. The serial adapter's **DTR** is wired here, so test NFC behaviour with the adapter removed. Deep-sleep wake pin |
| PB4 | UART0 TX | log at 115200 (bootloader 38400) |
| PB5 | UART0 RX **and panel RESET** | enabling UART RX kills the panel reset |
| PB6 | green LED | also DBG_DATA |
| PB7 | blue LED | also DBG_CLK |
| PC0 | SPI CS, flash | |
| PC1 / PC2 / PC3 | SPI SCLK / MOSI / MISO | shared by panel, flash and NFC. The NFC is bit-banged in mode 1, MISO read from `PINC` |
| PC4 | red LED | |
| PR0-PR7 | internal radio interface | `PORTR = 0x0B`, `DIRR = 0x15`. No pull-ups on PR6/PR7 |

- **LEDs** sit behind the e-paper glass, and a lit LED warms the panel. **Pulses only** (`shelfhw_led_pulse`), never a held level. Polarity is not fully settled: the pin map says active low, the firmware has `SHELFHW_LED_ACTIVE_HIGH`.
- LED codes: blue = NFC wake / OTA programming, green = OTA done, red = poll failed or OTA gave up. The first 500 ms after power-on are dark (bootloader).

## Firmware layout

```
ShelfKit-Firmware/
  Vusion/        tag app      src/{main,board,epd,flash,spi,pwr,img_rx,eco_rx,fw_rx,nfc_cfg,shelf_id}.c, include/shelf_config.h
  Vusion-Hub/    hub app      src/{main,board,epd,flash,spi,pwr,img_rx}.c, include/shelf_config.h
  Bootloader/    serial + OTA bootloader at 0xD800 (src/main.c, src/crtstart.asm)
  Shared/
    firmware/axradio  shelfhw  shelflink  shelfota  shelfid   (shared sources, inc/ per module)
    sdk/libmf, sdk/libaxdvk2 ...   vendor SDK (only libmf/include and libaxdvk2/include on the include path)
    lib/*.lib                      prebuilt libmf etc. (patched libmf.lib)
    boards/axsem-8051.json         board def: id axsem-8052f143, 26 MHz, iram 256, xram 8192, code 59389, --model-small
  Tooling/  build-all.py  axsem-flasher.py  ota-send.py  flash-read.py  set-id.py
```

- Each target is a self-contained SDCC-MDF project (`sdcc-project.json`). Open the **target folder** in VS Code and press Ctrl+Shift+B. Paths to `../Shared` are relative.
- Code that a second target needs belongs in `Shared/firmware/`. Board- or panel-specific code stays in the target's `src/`.

## Memory map of a tag

| Range | Contents |
|---|---|
| 0x0000 | `ljmp 0xD838`: the bootloader entry (when the full image or the bootloader is installed) |
| 0x0003 … ~0x9FF5 | application (about 41 KB of 59,389). Interrupt vectors at 0x0003+8n are the **application's** |
| 0xD7FE-0xD7FF | application entry vector (low byte first), written by the flasher merge or by OTA |
| 0xD800-0xFA6F | bootloader (8,819 B). Its CRC covers 0xD800-0xFBFF |
| last 1 KB page | factory calibration |

- An app-only hex (`vusion-*.hex`) contains its own `ljmp <entry>` at 0x0000. **Sent through the flash-resident bootloader (the normal serial path), that's harmless.** The bootloader intercepts every HEX write to 0x0000-0x0002, decodes the `ljmp`/`ajmp` target and stores it at `jmp_vector` 0xD7FE instead (`Bootloader/src/main.c` ~line 217, the AND9331 design). The reset vector stays the bootloader's, so OTA keeps working. Only written by other means (a debug adapter onto an erased chip) would the app's `ljmp` land at 0x0000, so that the bootloader never runs. The full image (`vusion-full-*.hex`) exists for that case: a blank chip that has neither.
- AND9331's **power-fail-safe erase order** (the `K` command):
  1. Erase page 1.
  2. Write a jump to the bootloader at the start of page 1.
  3. Erase page 0.
  4. Write the bootloader reset vector at 0x0000.
  5. Erase the remaining application pages.

  After every step the chip still boots into the bootloader. Keep this property in any change to the bootloader or the OTA programming path. The bootloader also refuses to erase below a minimum VDDIO (`BOOTLDR_MINVDD`) and uses no interrupts (polled UART), so the application owns the whole vector table.
- Bootloader on every reset:
  1. Rewrites ports and directions.
  2. Forces XOSC on (that's why the app turns it off).
  3. Runs 128 FRC calibration cycles.
  4. Opens the UART at 38400 and prints a banner.
  5. Powers the flash rail and checks for an OTA image (programs it if valid, with blue/green/red LEDs).
  6. Jumps to the vector with SP = 7.

  It does **not** know about `enter_sleep_cont`. That is the main suspect for "never wakes from Sleep".
- The application resets into the bootloader with `ljmp 0x0000` (OTA). **Turn the hardware SPI off first.**

## Build, flash, update

- **Test builds**: `python ShelfKit-Firmware/Tooling/build-all.py --no-record` (add `--targets vusion`, `--define NAME=VALUE`, `--version x.y.z`). Output goes to `Release/` as `<target>-latest.hex` + `.map`, with code and XRAM sizes in the summary. **Don't restore `version.json` / `build-log.md` from git.** Recorded builds (without `--no-record`) bump the version and log a row; do that only when the user asks for a recorded build.
- **Serial flash (user rule)**: `python ShelfKit-Firmware/Tooling/axsem-flasher.py Release/vusion-latest.hex -p COM4` (or the port the user names; COM3/COM4 are the tag and the hub). **App-only `vusion-*.hex`, never `vusion-full-*.hex`** over the serial port, unless the user explicitly asks. The repo READMEs suggest the full image; the user's rule wins, and it's also the safe choice (the vector redirect above). The full image would try to rewrite the bootloader region, which a running bootloader cannot program safely.
  - The flasher holds PB3 low via DTR at reset (the "SW5" of AND9331). The bootloader then stays in its command loop instead of starting the app. The flasher sends `?` (banner "AX8052 Bootloader V1.1"), `K` erase, the hex lines and `R` run. The READMEs call this the "mask-ROM" bootloader; the banner and the redirect logic say it's the flash-resident one at 0xD800.
- **OTA**: `Tooling/ota-send.py` or the server's Reflash button. The tag receives FW_BEGIN/CHUNK/END into the SPI flash, commits the header and resets. The bootloader verifies the CRC and programs. The OTA window is about 43 KB, and an image must not contain a bootloader.
- Logs: the tag at 115200 on PB4 (`[ t ] message` lines), the bootloader at 38400. With the serial adapter attached, DTR sits on PB3 (BOOT and NFC).

## Runtime behaviour of the tag (default config)

- Polls the hub (node 0x0001, net 0x5A) on 868.3 MHz.
  - Interval: every 120 s by default; 30 s while the hub says "data follows" (max 20 polls); cool-down at 180 s for 3 polls; then 300 s idle; up to 600 s on a weak link (hub RSSI below -95 dBm); hourly or two-hourly when the hub is lost.
- Frame: length, 3-byte address (dest lo, dest hi, net), payload `[ver|type][flags][src lo][src hi][seq][data 0..32]`.
  - Types: 1 POLL, 2 POLL_RSP, 3 DATA, 4 ACK.
  - The initiator retries up to 4 times with a 60 ms response window and random backoff.
- Between polls the radio is in **AX5043 deep sleep** (`SHELF_RADIO_DEEPSLEEP 1`) and the MCU in **Standby** in practice (`SHELF_MCU_SLEEP 1`, but `SHELF_FIX_UART_SLEEP 0` keeps libmf from choosing Sleep). Baseline = build B.
- A listen window of 2 s after a poll, closed immediately when there is nothing.
- NFC tap → PB3 falling edge → wake → poll (`SHELF_NFC_POLL 1`, `SHELF_NFC_RAIL_HOLD 1` keeps PA5 on so the NFC chip is powered, which costs current).
- Battery reading: 4 ADC channels averaged, sent in POLL as volts×256. The server stores the history in `ShelfKit-Server/data/shelfkit.db`.

## Known traps (collected)

1. XOSC forced on with no crystal (bootloader and old app) → fast battery drain. The app calls `turn_off_xosc()`.
2. `U0TXIE` left set by `log_putc` → no Sleep ever (silent fallback to Standby).
3. Writing `PCON` after a software reset → SWRESET re-fires → boot loop.
4. Sleep wake restarts through the bootloader → state lost and pins frozen. Unresolved.
5. After deep sleep the radio lost FREQA → `PLLLOOP = 0x89` fix. Wake retries needed.
6. `PORTR` left at 0xEB (pull-ups on PR6/PR7) after a libmf deep-sleep wake → call `axradio_setup_pincfg2()`.
7. Radio IRQ (`IE_4`) and `RADIOMUX` not restored after MCU Sleep → TX stalls.
8. Standby wake needs `IE_1` (wake timer), not the demo's `IE_3`.
9. Panel needs PA5 low (rail on) and BUSY is active low. PB5 RX vs panel reset.
10. NFC FD pin floats or oscillates when its rail is off. The FD source is set in the NFC EEPROM (0x38C fdp_conf, 0x391 WIP_FD), not in a register.
11. The serial adapter's DTR on PB3 makes NFC/boot tests with the adapter attached misleading.
12. IRAM full: new state goes in `__xdata`. Watch the stack headroom (~140 B).
13. The wake timer prescaler was off by one step on hardware (6 gave ~1024 Hz). Prescaler 7 = 512 Hz is measured.
14. ADC missing codes: treat the last voltage digit as noise.
15. Comments around `SHELF_XTAL_OFF` still describe OSCFORCERUN bit 2 as "the 26 MHz crystal". That is wrong: it is the MCU XOSC.
