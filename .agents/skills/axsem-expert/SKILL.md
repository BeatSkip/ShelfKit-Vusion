---
name: ax8052-ax5043-firmware
description: Use for any firmware work on the AX8052F143 (Axsem/onsemi 8051 MCU with the integrated AX5043 sub-GHz radio). That covers ShelfKit-Firmware (Vusion tag, Vusion-Hub, Bootloader), SDCC/8051 C or assembly, libmf, the axradio/easyax5043 engine, AX5043 registers, the radio FIFO, power modes (standby, sleep, deep sleep), the wake-up timers, clocks and oscillators, GPIO, interrupts, flash/OTA, and battery or power debugging. Load it before writing, reviewing or debugging code for this chip, even for a small change.
---

# AX8052F143 + AX5043 firmware

The AX8052F143 is one die-package with two halves:

- **AX8052**: a single-cycle 8052-compatible MCU at up to 20 MIPS. It has 64 KB flash, 256 B IRAM, 8 KB XRAM and low-power oscillators, plus wake-up timers, UARTs, SPI, an ADC, AES, a random number generator, DMA and DebugLink.
- **AX5043**: a sub-GHz transceiver (27-1050 MHz). It is wired internally to the MCU and memory-mapped into X space at `0x4000`. Its 256-byte FIFO carries "chunks" (framed records), not raw bytes.

The two halves have **separate power states, clocks and resets**. Most bugs on this chip come from forgetting that one half lost its state while the other did not.

This repository (`ShelfKit-Firmware/`) runs it on reused SES-imagotag Vusion 2.6" e-paper shelf tags and on a hub with identical hardware. The toolchain is SDCC 3.6.0, `--model-small`, with the vendor library **libmf** and the AX-RadioLAB-generated engine **easyax5043** (`Shared/firmware/axradio`).

## How to use this skill

1. Read **Critical rules** below. Every one of them has cost real debugging time on this project.
2. Open the reference for the area you are touching:

| Working on | Read |
|---|---|
| Memory spaces, SFR/X space map, flash layout, code size, startup | [references/mcu-core-memory.md](references/mcu-core-memory.md) |
| Clocks, oscillators, power modes, sleep/standby, wake-up timers, watchdog | [references/clocks-power.md](references/clocks-power.md) |
| Interrupts, GPIO, pin change, EXTIRQ, UART, SPI, timers, ADC, flash writes | [references/interrupts-gpio-peripherals.md](references/interrupts-gpio-peripherals.md) |
| Anything radio: power modes, FIFO chunks, TX/RX flow, ranging, deep sleep, registers | [references/radio-ax5043.md](references/radio-ax5043.md) |
| libmf APIs, the wtimer scheduler, the axradio engine, config.c, ShelfLink | [references/libmf-axradio.md](references/libmf-axradio.md) |
| Writing C or assembly that SDCC compiles well and correctly for the 8051 | [references/sdcc-8051-c-asm.md](references/sdcc-8051-c-asm.md) |
| This board: pin map, rails, panel, NFC, LEDs, bootloader, build/flash workflow, known traps | [references/board-vusion.md](references/board-vusion.md) |
| Silicon errata and which ones matter here | [references/errata.md](references/errata.md) |
| A register's address or exact name | [references/register-index.md](references/register-index.md) (generated from the SDK headers) |

3. For bit-level detail not in the references, **grep the vendor text** in `references/vendor/` (see the next section). Do not guess register bit layouts. Read them.

## Vendor documentation (grep, don't read whole)

These are plain-text extractions of the PDFs in `Documentation/`. They are large (3-9k lines each), so search them with Grep and read around the hits.

| File | What it is | Grep for |
|---|---|---|
| `AX8052-programming-manual-AND9349.txt` | MCU register-level manual: every SFR/XREG with bit tables, power modes, oscillators, peripherals | `Register: <NAME>`, `Table <n>`, a register name |
| `AX8052F143-datasheet.txt` | Chip datasheet: pinout, electrical specs, current figures, the F143-specific radio interface | `RADIOMUX`, `Sleep`, `mA`, a pin name |
| `AX8052-errata.txt` | Silicon errata V1/V1C/V2 | erratum titles |
| `AX5043-programming-manual-AND9347.txt` | Radio programming manual: FIFO, chunk formats, programming flow, every register in detail | register name, `FIFO`, `chunk`, `PWRMODE` |
| `AX5043-datasheet-onsemi.txt` / `-axsem-v1.6a.txt` | Radio datasheet: specs, timing, current per mode, register summary | `Table`, `IDD`, `ms` |
| `LibMF-user-manual.txt` | The libmf API reference | function name in CAPS, e.g. `WTIMER_IDLE` |
| `AX-RadioLAB-user-manual.txt` | The tool that generates `config.c` / `easyax5043.c` | `mode`, `framing` |
| `AX8052-serial-bootloader-AND9331.txt` | The app note our bootloader is ported from: memory layout, reset-vector redirect, power-fail-safe erase order | `0xE7FE`, `Erase` |
| `AX8052-crypto-programming-manual.txt` | AES engine and true RNG registers (X 0x7080-0x7098) | `AESMODE`, `RNGMODE` |
| `LibMFCrypto-user-manual.txt` | libmfcrypto API: AES-128 setup/encrypt/decrypt, DES | `AES_ENCRYPT` |
| `board-*.txt` | Not the MCU: the NFC chip (FM11NT, English spec + Chinese datasheet with the EEPROM FD config), the GDEW026Z39 panel, the ECO image compression | register or command name |
| `SDCC-user-manual.txt` | Current SDCC manual. The project uses **3.6.0**, so newer features (e.g. `--std-sdcc2x` extras) may not exist | `__critical`, `nooverlay`, `__interrupt`, `reentrant` |

PDF extraction artefact: the micro sign is lost, so "230 A", "mA" or "ms" in a current or timing figure is often **µA / µs**. Sanity-check the magnitude against the tables in the references.

## Critical rules (read every time)

**Power and clocks**
1. **Never enable the MCU's XOSC** (`OSCFORCERUN` bit 2, or a clock source `CLKSRC_XOSC`). Its pins PA0/PA1 are the panel D/C and CS on this board, and there is no crystal there. Once started it keeps running (and draws current) until a reset or falling edges on its pins. The bootloader forces it on at every reset, so the app calls `turn_off_xosc()` (`SHELF_FIX_XOSC=1`). The radio's 26 MHz crystal is a *different* oscillator inside the AX5043.
2. **Never write `PCON` from a running path** (`PCON |= x` included). `PCON.SWRESET` (bit 4) reads back 1 after a software reset, and writing it back resets again, which boot-loops the tag. Only `shelfhw_init` writes it, masking to the low nibble. Enter low-power modes with libmf (`wtimer_idle`, `enter_standby`, `enter_sleep*`), which add the required NOP and debugger handling.
3. **Sleep and deep sleep restart the CPU at 0x0000**, which on these tags is the **bootloader**. MCU Sleep currently does not survive that path (open issue, see clocks-power.md). The baseline is **build "B": XOSC fix on, Sleep fix off, so the MCU idles in Standby**. Do not "fix" sleep by flipping `SHELF_FIX_UART_SLEEP` without the user asking.
4. After any MCU Sleep wake, peripherals are reset: `GPIOENABLE` is 0 (pins frozen), `IE` is cleared, the UART, `RADIOMUX` and the timers are gone. Restore them explicitly: `GPIOENABLE=1`, `IE`, UART, `axradio_commsleepexit()`, `axradio_setup_pincfg2()`.
5. Anything that keeps a `wtimer_cansleep()` veto alive (a UART TX interrupt flag, a DebugLink buffer, a wtimer1 event) silently turns every Sleep into Standby (~85 µA instead of ~1.5 µA). `log_putc` setting `U0TXIE` did exactly that.

**Radio**
6. The AX5043 has its own power state (`AX5043_PWRMODE`). Radio **deep sleep loses every register** (and the FIFO). After wake, the frequency, the PLL ranging and the pin functions must be reprogrammed. The engine's wake path writes `PLLLOOP = 0x89` so `axradio_set_channel` lands the frequency in FREQA. Retry the wake (up to 8x, about 4 ms apart).
7. Talk to the radio through libmf/axradio (`radio_read8/radio_write8`, `axradio_set_mode`, `axradio_transmit`). Don't hand-poke PWRMODE or the FIFO in application code. If you must, follow the programming-manual flow: STANDBY, wait for XTAL, FULLTX, check `POWSTAT.SVMODEM`, write chunks, COMMIT, wait for idle. Go **FULLRX → FULLTX through an intermediate state**. Re-range the VCO for jumps >5 MHz (868/915) or >2.5 MHz (433).
8. 868.3 MHz is a **1 % duty-cycle** sub-band (EU). Keep transmissions short and polls infrequent.

**Memory and compiler**
9. IRAM is full (about 140-150 B of stack headroom on the tag). New buffers, structs and anything larger than a few bytes go in `__xdata`. Prefer `uint8_t` everywhere. Avoid deep call chains and `__reentrant` locals (they live on the IRAM stack).
10. Functions called through a pointer with **two or more parameters must be `__reentrant`** (SDCC passes only the first parameter in registers). Functions called from an ISR must be reentrant or under `#pragma nooverlay`. Multi-byte variables shared with an ISR are `volatile` and accessed inside `__critical { }` (or with that interrupt masked).
11. An ISR's prototype must be visible in the file that contains `main()`, or SDCC won't put it in the vector table. Use the `INT_*` numbers from `ax8052.h`, e.g. `__interrupt(INT_RADIO)`.
12. Use explicit-space pointers (`__xdata uint8_t *`) instead of generic ones in hot paths. Generic pointers are 3 bytes and go through a library call on every access.

**Board**
13. PA5 (U4) is the panel, flash and NFC rail, **active low**. PB5 is both UART0 RX and the panel reset (enabling RX kills reset). PB3 is both the NFC field-detect and the **BOOT strap**: the serial adapter's DTR is on it. Panel BUSY is active low.
14. LEDs (PB0 white, PB7 blue, PB6 green, PC4 red) sit behind the e-paper glass. Use **pulses only, never hold one on**.

**Workflow (user rules)**
15. Test builds: `python ShelfKit-Firmware/Tooling/build-all.py ... --no-record`. Never restore `version.json` or `build-log.md` from git.
16. Serial flashing: flash the **app-only `Release/vusion-*.hex`** with `Tooling/axsem-flasher.py -p COMx`. **Never flash `vusion-full-*.hex` over serial** unless the user explicitly asks; the full image also targets the bootloader region. App-only is safe: the bootloader redirects the app's reset jump into its vector at 0xD7FE.
17. Commit only when the user asks.

## Workflow for a change

1. Find where the behaviour lives (target `src/`, or `Shared/firmware/{shelfhw,shelflink,shelfota,shelfid,axradio}`). Read the relevant project doc in `Documentation/` (power-findings, wireless-link, ota-update, nfc-field-detect, pa2-pa5-findings, deepsleep-debugging-fix). Several of them record hard-won hardware facts.
2. Check the memory cost. Build with `build-all.py --no-record` and read the printed sizes, or the `.mem`/`.map` in `build/`. Code limit 59,389 B (the bootloader sits at 0xD800); IRAM and stack are the real constraint.
3. Think through every power transition your change crosses: what each half (MCU, radio) loses and who restores it.
4. Verify on hardware with the serial log (115200 on the app, 38400 on the bootloader) when it touches power, radio or boot. State plainly what was and wasn't verified.
