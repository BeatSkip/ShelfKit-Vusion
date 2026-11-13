# AX5043 radio

Sources: AND9347/D (AX5043 Programming Manual), the AX5043 datasheets, ax5043.h, ax8052f143.h,
`Shared/firmware/axradio/`. Grep `vendor/AX5043-programming-manual-AND9347.txt` for any register name: the
"Register Details" part has a bit table per register.

## How the MCU reaches the radio

- On the F143 the AX5043 sits behind an internal SPI. The **interface hardware maps its registers into X space**:
  - `0x4000 + reg` gives a blocking access. The CPU stalls until the SPI transfer is done.
  - `0x5000 + reg` gives a non-blocking write.
  - The header names are `AX5043_<REG>` (SFRX) in `ax8052f143.h`, e.g. `AX5043_PWRMODE` at 0x4002.
- libmf `radio_write8(addr, d)` is a macro on the F143: `*(volatile __xdata uint8_t *)((addr & 0xFFF) | 0x4000) = d`. The `AX5043_REG_*` constants in `ax5043.h` use a `0xF` prefix for long-address registers (e.g. `AX5043_REG_IFFREQ1 = 0xF100`). The mask drops it, so `0xF100` lands at X 0x4100.
- Multi-byte registers are **big-endian** in the radio's address order (e.g. FREQA3 at the lowest address). Use `radio_write16/24/32`, or write each byte, in the order the generated `config.c` does.
- The interface only works while `RADIOMUX` / `RADIOACC` are set up (`ax5043_comminit()`, or `axradio_commsleepexit()` after an MCU Sleep). After an MCU Sleep they are reset, and register accesses silently fail.
- The radio IRQ reaches the MCU as `INT_RADIO` (4), enable `IE_4`. The engine's `axradio_isr` owns it. Radio-side interrupt sources are enabled in `IRQMASK1:0` and read in `IRQREQUEST1:0`.

## Radio power modes (`PWRMODE` register 0x002, bits 3:0)

| Bits | Name | Typical I | Notes |
|---|---|---|---|
| 0000 | POWERDOWN | 400 nA | Registers kept, FIFO **lost** (powered down; read FIFOSTAT as 0) |
| 0001 | DEEPSLEEP | 50 nA | **All registers lost.** Woken by pulling SEL low, then wait for MISO high |
| 0101 | STANDBY | ~230 µA | Crystal oscillator on |
| 0111 | FIFOON | ~310 µA | Crystal + FIFO on (to read or write the FIFO without RF) |
| 1000 | SYNTHRX | ~5 mA | Synthesizer running, RX |
| 1001 | FULLRX | 7-11 mA | Receiver running |
| 1011 | WORRX | ~500 nA avg | Wake-on-radio: periodic autonomous listen |
| 1100 | SYNTHTX | ~5 mA | Synthesizer running, TX |
| 1101 | FULLTX | 6-70 mA | Transmitter (the current depends on output power) |

- Bit 7 of PWRMODE is **RST**: setting it and then clearing it resets the chip. Other bits enable the reference and the XO (see `Register: PWRMODE`).
- The F143 datasheet gives TX ≈ 48 mA at 16 dBm and RX ≈ 9.5 mA at 868 MHz. Its TX current table: 15 dBm 54.6 mA, 10 dBm 21.3 mA, 0 dBm 7.5 mA.
- Timings: crystal start ~0.5-3 ms (`XTALSTATUS` bit 0, or the `IRQMXTALREADY` interrupt), synthesizer settle ~40 µs, RX→TX 62 µs, TX→RX 200 µs.
- **Deep sleep** (libmf): use `ax5043_enter_deepsleep()` and `ax5043_wakeup_deepsleep()` (returns nonzero on failure). After waking:
  1. Restore the communication setup.
  2. Reprogram every register (`ax5043_set_registers()` and the mode registers).
  3. Re-range or restore the VCO (`axradio_phy_chanpllrng`).
  4. Write the frequency again.

  The project engine does this in `axradio_set_mode` from `AXRADIO_MODE_DEEPSLEEP`, with the `PLLLOOP = 0x89` fix, and `shelfhw_radio_wake()` retries 8×.
- The MCU and radio states are independent. A radio left in FULLRX while the MCU sleeps costs ~10 mA. MCU sleep does not touch the radio's state, but the MCU loses its interface to it (see above).

## Bring-up / programming flow (AND9347 "Programming the Chip")

1. **Reset**: SEL high for ≥1 µs, then low; wait until MISO goes high. Set, then clear, `PWRMODE.RST`. (libmf `ax5043_reset()`; it returns nonzero if the chip doesn't answer. Check `SILICONREVISION` (reg 0x000) = 0x51 (`01010001` in AND9347's register table), and the `SCRATCH` (reg 0x001) read/write test.)
2. `PWRMODE = POWERDOWN`.
3. Program the parameters: the AX-RadioLAB generated `ax5043_set_registers()` plus the `_tx` / `_rx` variants.
4. **Auto-range the VCO**:
   1. Set PWRMODE to STANDBY and wait for the crystal.
   2. Write FREQA.
   3. Set VCORA (start from a known value, or 8; never <6).
   4. Set `PLLRANGINGA.RNGSTART`.
   5. Wait until RNGSTART clears (or `IRQMPLLRNGDONE`).
   6. Check `RNGERR`, then go back to POWERDOWN.

   Re-range when the frequency moves more than **5 MHz (868/915)** or **2.5 MHz (433)**. Each chip must be ranged individually. The engine stores the result per channel in `axradio_phy_chanpllrng[]` and reuses it.

### Transmit

1. `PWRMODE = FULLTX`. This enables the FIFO in the TX direction. The synthesizer is not started yet.
2. Wait for `POWSTAT.SVMODEM` (modem regulator ready) before writing the FIFO.
3. Write the preamble chunk(s) and the packet chunk(s) to the FIFO.
4. Wait for the crystal to run.
5. **Commit**: `FIFOSTAT = 0x04`. The radio then starts the synthesizer (`TMGTXBOOST` / `TMGTXSETTLE`) and sends the preamble and packet. The PA ramps over about one bit (longer with `MODCFGA.SLOWRAMP`).
6. Stay in FULLTX until done. Poll `RADIOSTATE` until it reads Idle (0000), or use `IRQMRADIOCTRL` with `RADIOEVENTMASK0.REVMDONE`.
7. Go back to POWERDOWN (or RX).

- **Never go FULLRX → FULLTX directly**: the FIFO may not be released. Pass through an intermediate state (e.g. SYNTHTX). The engine handles this.

### Receive

- `PWRMODE = FULLRX`. The synthesizer settles (`TMGRXBOOST` / `TMGRXSETTLE`), then AGC, then preamble search: PREAMBLE1 → PREAMBLE2 → PREAMBLE3 → PACKET states, each with its own `RXPARAMSETS` loop bandwidths.
- Packets and metadata appear in the FIFO. Empty the FIFO before going to POWERDOWN.
- **WOR** (`WORRX`): the radio wakes from its LPOSC (640 Hz/10 kHz, period `WAKEUPFREQ`), checks RSSI against `RSSIABSTHR`/`BGNDRSSITHR`, looks for a preamble within `TMGRXPREAMBLE1`, and goes back down if it finds none. The MCU can sleep until `IRQMFIFONOTEMPTY`. In WOR, use `IRQREQUEST0` bit 0 rather than `FIFOSTAT` (FIFOSTAT reads 0 when the FIFO is powered down).
- Radio LPOSC calibration against the crystal: `LPOSCCONFIG` (CALIBR/CALIBF), `LPOSCREF`, `LPOSCKFILT`, `LPOSCFREQ`. It is opportunistic: it calibrates whenever the XO runs.

## FIFO

- 256 bytes, shared by TX and RX. It has a read pointer, a write pointer and a write-ahead pointer: writes are only visible after **COMMIT**, and can be discarded with ROLLBACK.
- `FIFOSTAT` read bits:

  | Bit | Meaning |
  |---|---|
  | 0 | EMPTY |
  | 1 | FULL |
  | 2 | UNDER |
  | 3 | OVER |
  | 4 | count > FIFOTHRESH |
  | 5 | free > FIFOTHRESH |
  | 7 | AUTO COMMIT (RW) |

- `FIFOSTAT` write commands (bits 5:0):

  | Value | Command |
  |---|---|
  | 0x00 | nop |
  | 0x02 | clear error flags |
  | **0x03** | **clear data and flags** |
  | **0x04** | **commit** |
  | 0x05 | rollback |

- `FIFODATA` (0x029) is the data port. `FIFOCOUNT1:0` and `FIFOFREE1:0` give the levels. `FIFOTHRESH1:0` sets the threshold for the THRCNT/THRFREE interrupts.
- libmf `ax5043_writefifo(ptr, len)` / `ax5043_readfifo(ptr, len)` move bytes in bulk.

### Chunk format

Each FIFO record starts with a header byte. The top 3 bits give the length class, the low 5 bits the type.

| Top bits | Payload length |
|---|---|
| 000 | no payload |
| 001 | 1 byte |
| 010 | 2 bytes |
| 011 | 3 bytes |
| 100, 101, 110 | invalid |
| 111 | variable: the next byte is the length (the length byte is part of the header and not counted in it) |

Check against the table below: RSSI 0x31 = `001` + 1 byte; FREQOFFS 0x52 = `010` + 2 bytes; TIMER 0x70 = `011` + 3 bytes; DATA 0xE1 = `111` + length.

| Header | Name | Dir | Payload |
|---|---|---|---|
| 0x00 | NOP | both | - |
| 0x31 | RSSI | RX | 1 B, same encoding as the RSSI register (the engine subtracts `axradio_phy_rssioffset`) |
| 0x3C | TXCTRL | TX | 1 B: change PA/antenna settings mid-stream |
| 0x52 | FREQOFFS | RX | 2 B frequency offset |
| 0x55 | ANTRSSI2 | RX | 2 B (antenna diversity RSSI) |
| 0x62 | REPEATDATA | TX | 3 B: flags, count, byte; repeats a byte N times (preambles) |
| 0x70 | TIMER | RX | 3 B timestamp |
| 0x73 | RFFREQOFFS | RX | 3 B RF frequency offset |
| 0x74 | DATARATE | RX | 3 B data-rate offset |
| 0x75 | ANTRSSI3 | RX | 3 B |
| 0xE1 | DATA | both | variable: length byte, flags byte, payload |
| 0xFD | TXPWR | TX | variable: length byte, then the TX power coefficients |

- **DATA flags (TX)**:

  | Flag | Meaning |
  |---|---|
  | UNENC | bypass the encoder |
  | RAW | bypass the framing |
  | NOCRC | don't append a CRC |
  | RESIDUE | last byte is partial |
  | PKTEND | end of packet |
  | PKTSTART | start of packet |

  A packet may be split over several DATA chunks: PKTSTART on the first, PKTEND on the last.
- **DATA flags (RX)**:

  | Flag | Meaning |
  |---|---|
  | ABORT | the packet was aborted |
  | SIZEFAIL | the packet failed the size check |
  | ADDRFAIL | the address didn't match |
  | CRCFAIL | the CRC failed |
  | RESIDUE / PKTEND / PKTSTART | as in TX |

  **On PKTSTART, discard any partial packet you were assembling.**
- `PKTSTOREFLAGS` (0x232) chooses which metadata chunks are stored (timer, frequency offset, RF offset, data rate, RSSI, CRC bytes, antenna RSSI).
- `PKTACCEPTFLAGS` decides whether bad packets (CRC, size, address, abort) are delivered with flags or silently dropped.

## Framing and PHY in this project (config.c, generated by AX-RadioLAB)

- Carrier: `axradio_phy_chanfreq[0] = 0x21656a57`. FREQ = f / f_xtal × 2^24 with f_xtal = 26 MHz, which gives **868.3 MHz**. One channel.
- `MODULATION = 0x08` (FSK). Bit rate about 100 kbit/s (`Documentation/wireless-link.md`).
- `FEC = 0x13`: convolutional FEC on, which requires HDLC flags as the preamble. Preamble byte `0x7E`.
- `FRAMING = 0x24`: FRMMODE = 010 (HDLC), CRCMODE = 010 (CRC-16).
- Sync word `CC AA CC AA`, 32 bits.
- `ENCODING = 0x00`.
- `PINFUNCSYSCLK/DCLK/DATA = 0x01`; `PINFUNCANTSEL/PWRAMP = 0x82`.
- MAC (engine):
  - 4-byte MAC header: length byte, 3-byte destination address at position 1.
  - No source address.
  - Hardware address filter: 3 bytes, mask FF FF FF = node id lo, node id hi, net id 0x5A.
  - CRC-16 in hardware.
- `axradio_phy_maxfreqoffset = 33618` (internal units). `rssioffset = 64`. `channelbusy = -85 dBm` (LBT is off).
- **Regenerate config.c with AX-RadioLAB, don't hand-edit the register list**: the values interlock (IF, decimation, data-rate, AFC limits, timing gains). Changing the bit rate, deviation or frequency by hand almost always breaks RX sensitivity.
- Frequency conversions: `axradio_conv_freq_fromhz` / `_tohz`. Time conversions: `axradio_conv_timeinterval_totimer0` (wtimer0 ticks).

## Register groups (where to look in AND9347)

| Group | Registers |
|---|---|
| Status, test, power | `SILICONREVISION`, `SCRATCH`, `PWRMODE`, `POWSTAT`, `POWSTICKYSTAT`, `POWIRQMASK` |
| Interrupts | `IRQMASK1:0`, `RADIOEVENTMASK1:0`, `IRQINVERSION1:0`, `IRQREQUEST1:0`, `RADIOEVENTREQ1:0` |
| Modulation, framing | `MODULATION`, `ENCODING`, `FRAMING`, `CRCINIT3:0`, `FEC`, `FECSYNC`, `FECSTATUS` |
| State | `RADIOSTATE`, `XTALSTATUS` |
| Pin functions | `PINSTATE`, `PINFUNCSYSCLK`, `PINFUNCDCLK`, `PINFUNCDATA`, `PINFUNCIRQ`, `PINFUNCANTSEL`, `PINFUNCPWRAMP`, `PWRAMP` |
| FIFO | `FIFOSTAT`, `FIFODATA`, `FIFOCOUNT`, `FIFOFREE`, `FIFOTHRESH` |
| Synthesizer | `PLLLOOP`, `PLLCPI`, `PLLVCODIV`, `PLLRANGINGA/B`, `FREQA3:0`, `FREQB3:0`, `PLLLOOPBOOST`, `PLLCPIBOOST` |
| Signal strength | `RSSI`, `BGNDRSSI`, `DIVERSITY`, `AGCCOUNTER` |
| Receiver tracking | `TRKDATARATE`, `TRKAMPL`, `TRKPHASE`, `TRKRFFREQ`, `TRKFREQ`, `TRKFSKDEMOD`, `TRKAFSKDEMOD` |
| Timers, wake-up | `TIMER2:0`, `WAKEUPTIMER`, `WAKEUP`, `WAKEUPFREQ`, `WAKEUPXOEARLY` |
| Receiver parameters | `IFFREQ`, `DECIMATION`, `RXDATARATE`, `MAXDROFFSET`, `MAXRFOFFSET`, `FSKDMAX/MIN`, `AFSK*`, `AMPLFILTER`, `FREQUENCYLEAK`, `RXPARAMSETS`, `RXPARAMCURSET`, and the per-set `AGCGAINx`, `AGCTARGETx`, `TIMEGAINx`, `DRGAINx`, `PHASEGAINx`, `FREQUENCYGAINA-Dx`, `AMPLITUDEGAINx`, `FREQDEVx`, `FOURFSKx`, `BBOFFSRESx` |
| Transmitter | `MODCFGF`, `FSKDEV2:0`, `MODCFGA`, `TXRATE2:0`, `TXPWRCOEFFA-E` |
| PLL, crystal | `PLLVCOI`, `PLLVCOIR`, `PLLLOCKDET`, `PLLRNGCLK`, `XTALCAP`, `XTALOSC`, `XTALAMPL` |
| Baseband | `BBTUNE`, `BBOFFSCAP` |
| Packet format | `PKTADDRCFG`, `PKTLENCFG`, `PKTLENOFFSET`, `PKTMAXLEN`, `PKTADDR3:0`, `PKTADDRMASK3:0` |
| Pattern match | `MATCH0PAT`, `MATCH0LEN`, `MATCH0MIN/MAX`, `MATCH1*` |
| Packet controller timing | `TMGTXBOOST`, `TMGTXSETTLE`, `TMGRXBOOST`, `TMGRXSETTLE`, `TMGRXOFFSACQ`, `TMGRXCOARSEAGC`, `TMGRXAGC`, `TMGRXRSSI`, `TMGRXPREAMBLE1-3`, `RSSIREFERENCE`, `RSSIABSTHR`, `BGNDRSSIGAIN`, `BGNDRSSITHR`, `PKTCHUNKSIZE`, `PKTMISCFLAGS`, `PKTSTOREFLAGS`, `PKTACCEPTFLAGS` |
| GPADC | `GPADCCTRL`, `GPADCPERIOD`, `GPADC13VALUE` |
| LPOSC | `LPOSCCONFIG`, `LPOSCSTATUS`, `LPOSCKFILT`, `LPOSCREF`, `LPOSCFREQ`, `LPOSCPER` |
| DAC | `DACVALUE`, `DACCONFIG` |
| Performance tuning (the 0xF00+ registers) | the values AX-RadioLAB sets, e.g. `0xF10` XTAL, `0xF11`, `0xF1C`, `0xF21`-`0xF23`, `0xF26`, `0xF30`-`0xF35`, `0xF44`, `0xF72`. **Set exactly as generated** |

`RADIOSTATE` values:

| Value | State |
|---|---|
| 0000 | Idle |
| 0001 | Powerdown |
| 0100 | Tx PLL settings |
| 0110 | Tx |
| 0111 | Tx tail |
| 1000 | Rx PLL settings |
| 1001 | Rx antenna selection |
| 1100 | Rx preamble 1 |
| 1101 | Rx preamble 2 |
| 1110 | Rx preamble 3 |
| 1111 | Rx |

`IRQMASK` bits:

| Bit | Interrupt |
|---|---|
| 0 | FIFONOTEMPTY |
| 1 | FIFONOTFULL |
| 2 | FIFOTHRCNT |
| 3 | FIFOTHRFREE |
| 4 | FIFOERROR |
| 5 | PLLUNLOCK |
| 6 | RADIOCTRL |
| 7 | POWER |
| 8 | XTALREADY |
| 9 | WAKEUPTIMER |
| 10 | LPOSC |
| 11 | GPADC |
| 12 | PLLRNGDONE |

`POWSTAT` bits, from 0 up: SVIO, SBEVMODEM, SBEVANA, SVMODEM, SVANA, SVREF, SREF, SSUM. Check the bit position in the register table before relying on it: the PDF table extracted with shifted columns.

## Debug hooks in this repo

`axradio_dbg_snapshot()` (easyax5043.c) logs PWRMODE, POWSTAT, PLLLOOP, PLLRANGINGA and FREQA after a wake. It is the first thing to look at when "the radio wakes but nobody hears it".

Symptoms and their usual causes:

| Symptom | Usual causes |
|---|---|
| Wrong frequency after deep sleep | FREQA not rewritten, or PLLLOOP selecting FREQB |
| No TX | radio IRQ (IE_4) disabled, RADIOMUX lost, crystal never ready |
| RX hears nothing | pull-ups left on PR6/PR7, ranging failed (`AXRADIO_ERR_RANGING`) |
