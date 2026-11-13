# Interrupts, GPIO and peripherals

Sources: AND9349/D, ax8052.h, project code. For bit tables grep `vendor/AX8052-programming-manual-AND9349.txt`
for `Register: <NAME>`.

## Interrupt vectors

Vector address = `0x0003 + 8*n`. SDCC: `void isr(void) __interrupt(INT_x)`. **The prototype must be visible in
the file that contains `main()`.**

| n | `INT_*` (ax8052.h) | Source | Enable bit | Priority bit |
|---|---|---|---|---|
| 0 | `INT_EXTERNAL0` | EXTIRQ0 pin (PB0 or PC0 by PINSEL) | `IE_0` | `IP_0` |
| 1 | `INT_WAKEUPTIMER` | wake-up timer (owned by libmf `wtimer_irq`) | `IE_1` | `IP_1` |
| 2 | `INT_EXTERNAL1` | EXTIRQ1 pin (**PB3** default, or PC4) | `IE_2` | `IP_2` |
| 3 | `INT_GPIO` | port change (`INTCHGx` / `PINCHGx`) | `IE_3` | `IP_3` |
| 4 | `INT_RADIO` | AX5043 IRQ (owned by `axradio_isr`) | `IE_4` | `IP_4` |
| 5 | `INT_CLOCKMGMT` | oscillator calibration and clock monitor | `IE_5` | `IP_5` |
| 6 | `INT_POWERMGMT` | brown-out | `IE_6` | `IP_6` |
| 7 | `INT_TIMER0` | timer 0 | `EIE_0` | `EIP_0` |
| 8 | `INT_TIMER1` | timer 1 | `EIE_1` | `EIP_1` |
| 9 | `INT_TIMER2` | timer 2 | `EIE_2` | `EIP_2` |
| 10 | `INT_SPI0` | SPI master/slave | `EIE_3` | `EIP_3` |
| 11 | `INT_UART0` | UART0 | `EIE_4` | `EIP_4` |
| 12 | `INT_UART1` | UART1 | `EIE_5` | `EIP_5` |
| 13 | `INT_GPADC` | ADC | `EIE_6` | `EIP_6` |
| 14 | `INT_DMA` | DMA | `EIE_7` | `EIP_7` |
| 15 | `INT_OUTPUTCOMP0` | OC0 | `E2IE_0` | `E2IP_0` |
| 16 | `INT_OUTPUTCOMP1` | OC1 | `E2IE_1` | `E2IP_1` |
| 17 | `INT_INPUTCAPT0` | IC0 | `E2IE_2` | `E2IP_2` |
| 18 | `INT_INPUTCAPT1` | IC1 | `E2IE_3` | `E2IP_3` |
| 19 | (RNG, vector 0x009B) | random number generator | `E2IE_4` | |
| 20 | (AES, vector 0x00A3) | AES | `E2IE_5` | |
| 21 | `INT_DEBUGLINK` | DebugLink | `E2IE_6` | |

- `IE` (0xA8): bit 7 = `EA` (global enable). `EIE` = 0x98, `E2IE` = 0xA0. Priorities: `IP` 0xB8, `EIP` 0xB0, `E2IP`.
- Two priority levels. A high-priority ISR can interrupt a low one. Latency is at least 5 cycles.
- The **interrupt flag lives in the peripheral** (e.g. `WTSTAT`, `U0STATUS`, `PINCHGx`, radio `IRQREQUEST`). Most are cleared by reading or servicing the source, not by the CPU. An unserviced level source re-enters the ISR forever.
- Project state at runtime: `IE = 0x40` (power management), then `EA = 1`. `IE_1` is enabled by the wtimer code, `IE_4` by the radio code, `IE_2`/`IE_3` by the NFC code. Re-establish all of these after a Sleep wake.
- ISR register use and the libmf rules are in sdcc-8051-c-asm.md.

## GPIO

Ports A, B, C (8, 8, 5 pins on the F143 package) plus port R (the internal radio interface pins PR0-PR7).

| DIRx bit | PORTx bit | Pin |
|---|---|---|
| 0 | 0 | input, high-Z |
| 0 | 1 | input with **pull-up** |
| 1 | v | output driving v |

- **Read pins from `PINx`**, not `PORTx`. `PORTx` is the output and pull-up latch.
- `ANALOGA` disables Port A's digital input buffers. Use it for the analog pins and for unused Port A pins to save current. Here `ANALOGA = 0x18` (PA3/PA4, the LPXOSC crystal).
- `GPIOENABLE` (X 0x700C): 0 freezes every pin at its last state. It is cleared on deep-sleep entry and by `enter_sleep_cont()`, so set it to 1 after configuring pins at boot and after every wake.
- Alternate functions: `PALTA` / `PALTB` / `PALTC` select peripheral outputs. `PINSEL` selects which pin feeds a peripheral input (e.g. EXTIRQ0 on PB0 or PC0, EXTIRQ1 on PB3 or PC4). Leave `PALTRADIO = 0x00` (radio pass-through) as config.c sets it.
- Port A is **not 5 V tolerant**.
- Pin change: `INTCHGx` enables the per-pin change interrupt. `PINCHGx` latches that a pin changed (check its clear semantics under `Register: PINCHGA` in AND9349 before relying on it). Together they raise `INT_GPIO` (IE_3) and can wake **Standby and Sleep**. Deep sleep is woken only by PB3 going low.
- `EXTIRQ`: two fields, one per external interrupt. Modes: 00 high level, 01 low level, 10 rising edge, 11 falling edge. For EXTIRQ1 the field is **bits 5:4**, so `11` = falling edge, on PB3 by default (the NFC field-detect).
- Default (generic) pin roles from the datasheet, used when the matching peripheral is enabled:

| Pins | Role |
|---|---|
| PA0/PA1 | XOSC crystal |
| PA3/PA4 | LPXOSC crystal |
| PB4/PB5 | U0TX/U0RX |
| PC0-PC3 | SPI SSEL/SCK/MOSI/MISO |
| PB6/PB7 | DBG_DATA/DBG_CLK (when the debugger is enabled) |
| PR0 | RSEL |
| PR1 | RSYSCLK |
| PR2 | RCLK |
| PR3 | RMISO |
| PR4 | RMOSI |
| PR5 | RIRQ |

  The ShelfKit board assignment is in board-vusion.md.
- Port R (the radio interface) on the F143:
  - Datasheet setup: `PORTR = 0xCB`, `DIRR = 0x15`. This project uses `PORTR = 0x0B`, `DIRR = 0x15`.
  - Don't leave pull-ups on PR6/PR7. `axradio_setup_pincfg2()` does `PORTR &= 0x3F`.
  - The libmf deep-sleep wake sets `PORTR = 0xEB`, so call pincfg2 again afterwards.

## UART0 / UART1

- Clocked from a timer (`uart_timer0_baud(CLKSRC_FRCOSC, 115200, 20000000)` here, or `uart0_init(timernr, wl, stop)`).
- Registers:
  - `U0MODE`: word length, stop bits, baud generator.
  - `U0CTRL`: TX/RX interrupt enables; **bit 3 = U0TXIE**.
  - `U0STATUS`, `U0SHREG`.
- Baud: 115200 from 20 MHz rounds the timer reload to 11, about 113.6 kbaud (1.4 % low). The bootloader uses 38400 with the same rounding. Both ends must agree.
- **Leaving U0TXIE set blocks Sleep** through libmf's TX-busy veto (see clocks-power.md).
- UART0 RX on **PB5 is also the panel reset**. Turning RX on drives that line, so the board uses TX-only logging plus a separate host RX path (`host_rx_init`) where needed.
- Sleep resets the UART. Re-initialise it after a wake (`log_uart_start()`).

## SPI

- Hardware SPI0 (`SPMODE`, `SPCLKSRC`, `SPSHREG`, `SPSTATUS`) on PC0-PC3.
- The tag drives the panel, flash and NFC on PC1/PC2/PC3 with separate chip selects (PA1, PC0, PB1).
- The NFC chip (FM11NT081DS) only works in SPI **mode 1** and needs at least 100 µs after CS. The project bit-bangs it and reads MISO from `PINC`.
- **Turn the hardware SPI off before jumping to the bootloader** (OTA reset path).

## Timers 0/1/2, input capture, output compare

- 16-bit timers with selectable clock (`TxCLKSRC`), mode (`TxMODE`), status (`TxSTATUS`) and counter (`TxCNT`). One of them is used as the UART baud generator.
- OC0/OC1 do PWM. IC0/IC1 capture edges.
- **Errata**: timer clear-on-read precedence (V1/V1C).

## ADC (GPADC)

- 4 channels.
  - Config: `ADCCHxCONFIG`, `ADCCONV`, `ADCCLKSRC`.
  - Results: `ADCCHxVAL0/1` (X 0x7020+).
  - Interrupt: `INT_GPADC`.
- VDD measurement here uses 4 channels configured `0xD9` and averages them.
- **Erratum on all revisions: missing codes at mid-scale.** Only the last digit of the voltage is a hint. Exact values need a two-point per-board calibration.
- V1/V1C erratum: convert the temperature sensor in standby (`ADCCLKSRC = 0x30`).

## Other peripherals

- **DMA**: two channels, can move radio FIFO data (`RADIOFDATAADDR` / `RADIOFSTATADDR` point at FDATA 0x005 / FSTAT 0x004). Not used here.
- **AES** engine and a true **RNG**. Not used: `shelfhw_random()` is a software PRNG seeded from wtimer0.
  - RNG registers: `RNGMODE` 0x7080, `RNGBYTE` 0x7081, `RNGCLKSRC0/1` 0x7082/3 (clock sources FRCOSC/LPOSC/**XOSC**... never pick XOSC here).
  - AES registers: `AESMODE` 0x7090, `AESCONFIG` 0x7091, `AESKEYADDR` 0x7092/3, `AESINADDR` 0x7094/5, `AESOUTADDR` 0x7096/7, `AESCURBLOCK` 0x7098. The engine works on XRAM buffers by address.
  - Library: `libmfcrypto` (`aes128_setup`, `aes_keyexp`, `aes_encrypt`, `aes_decrypt`, DES). The prebuilt `Shared/lib/libmfcrypto.lib` is already on the library path. Its headers are in `Shared/sdk/libmfcrypto/include` (`libmfaes.h`, `libmfcrypto.h`, `ax8052crypto.h`), which is **not** on the include path yet. Add it to `includes` in `sdcc-project.json` to use it.
  - Details: `vendor/AX8052-crypto-programming-manual.txt`, `vendor/LibMFCrypto-user-manual.txt`.
- **DebugLink** UART-over-debug-pins. Its buffer vetoes Sleep while TX data is pending.

## Radio interface registers (MCU side)

`RADIOACC`, `RADIOADDR`, `RADIODATA`, `RADIOSTAT`, `RADIOMUX`, `RADIOFDATAADDR`, `RADIOFSTATADDR`.

- `RADIOMUX` bits:
  - 2:0 RADIOSYSCLK routing
  - 3 RADIOIRQ
  - 5:4 RADIOCLK
  - 6 RADIOSPI
- F143 values: `RADIOACC = 0x00`, `RADIOMUX = 0x07`, FDATA 0x005, FSTAT 0x004. `ax5043_comminit()` / `axradio_commsleepexit()` set these.
- Sleep resets them. Before restoring, any radio register access fails silently (reads return garbage, writes go nowhere).
