# Register index (generated)

Generated from `ShelfKit-Firmware/Shared/sdk/libmf/include/ax8052.h`, `ax8052f143.h` and `ax5043.h`.
Names are the C identifiers you use in code (`#include <ax8052f143.h>`). Bit layouts are NOT here;
grep the vendor text (`references/vendor/`) or the topic references for those.

Kinds: `SFR` = direct SFR (0x80-0xFF, `mov` direct), `SBIT` = bit-addressable SFR bit,
`SFR16/32` = multi-byte SFR (little endian, `E` = big endian pair), `SFRX` = X-space register
(`movx`, `__xdata` pointer). X-space map: 0x7000-0x7FFF MCU XREGs, 0x4000-0x4FFF AX5043 (blocking),
0x5000-0x5FFF AX5043 (non-blocking write; the `NB` names).

## AX8052 core SFRs (direct, 0x80-0xFF)

| Name | Kind | Address | Description |
|---|---|---|---|
| `PORTA` | SFR | 0x80 | Port A Output |
| `SP` | SFR | 0x81 | Stack Pointer |
| `DPL` | SFR | 0x82 | Data Pointer 0 Low Byte |
| `DPTR0` | SFR16 | 0x82 | Data Pointer 0 |
| `DPH` | SFR | 0x83 | Data Pointer 0 High Byte |
| `DPL1` | SFR | 0x84 | Data Pointer 1 Low Byte |
| `DPTR1` | SFR16 | 0x84 | Data Pointer 1 |
| `DPH1` | SFR | 0x85 | Data Pointer 1 High Byte |
| `DPS` | SFR | 0x86 | Data Pointer Select |
| `PCON` | SFR | 0x87 | Power Mode Control |
| `PORTB` | SFR | 0x88 | Port B Output |
| `DIRA` | SFR | 0x89 | Port A Direction |
| `DIRB` | SFR | 0x8A | Port B Direction |
| `DIRC` | SFR | 0x8B | Port C Direction |
| `PORTR` | SFR | 0x8C | Port R Output |
| `PINR` | SFR | 0x8D | Port R Input |
| `DIRR` | SFR | 0x8E | Port R Direction |
| `PORTC` | SFR | 0x90 | Port C Output |
| `NVSTATUS` | SFR | 0x91 | Non-Volatile Memory Command / Status |
| `NVADDR` | SFR16 | 0x92 | Non-Volatile Memory Address |
| `NVADDR0` | SFR | 0x92 | Non-Volatile Memory Address Low Byte |
| `NVADDR1` | SFR | 0x93 | Non-Volatile Memory Address High Byte |
| `NVDATA` | SFR16 | 0x94 | Non-Volatile Memory Data |
| `NVDATA0` | SFR | 0x94 | Non-Volatile Memory Data Low Byte |
| `NVDATA1` | SFR | 0x95 | Non-Volatile Memory Data High Byte |
| `NVKEY` | SFR | 0x96 | Non-Volatile Memory Write/Erase Key |
| `CODECONFIG` | SFR | 0x97 | Code Space Configuration |
| `EIE` | SFR | 0x98 | Extended Interrupt Enable |
| `T0MODE` | SFR | 0x99 | Timer 0 Mode |
| `T0CLKSRC` | SFR | 0x9A | Timer 0 Clock Source |
| `T0STATUS` | SFR | 0x9B | Timer 0 Status |
| `T0CNT` | SFR16 | 0x9C | Timer 0 Count |
| `T0CNT0` | SFR | 0x9C | Timer 0 Count Low Byte |
| `T0CNT1` | SFR | 0x9D | Timer 0 Count High Byte |
| `T0PERIOD` | SFR16 | 0x9E | Timer 0 Period |
| `T0PERIOD0` | SFR | 0x9E | Timer 0 Period Low Byte |
| `T0PERIOD1` | SFR | 0x9F | Timer 0 Period High Byte |
| `E2IE` | SFR | 0xA0 | 2nd Extended Interrupt Enable |
| `T1MODE` | SFR | 0xA1 | Timer 1 Mode |
| `T1CLKSRC` | SFR | 0xA2 | Timer 1 Clock Source |
| `T1STATUS` | SFR | 0xA3 | Timer 1 Status |
| `T1CNT` | SFR16 | 0xA4 | Timer 1 Count |
| `T1CNT0` | SFR | 0xA4 | Timer 1 Count Low Byte |
| `T1CNT1` | SFR | 0xA5 | Timer 1 Count High Byte |
| `T1PERIOD` | SFR16 | 0xA6 | Timer 1 Period |
| `T1PERIOD0` | SFR | 0xA6 | Timer 1 Period Low Byte |
| `T1PERIOD1` | SFR | 0xA7 | Timer 1 Period High Byte |
| `IE` | SFR | 0xA8 | Interrupt Enable |
| `T2MODE` | SFR | 0xA9 | Timer 2 Mode |
| `T2CLKSRC` | SFR | 0xAA | Timer 2 Clock Source |
| `T2STATUS` | SFR | 0xAB | Timer 2 Status |
| `T2CNT` | SFR16 | 0xAC | Timer 2 Count |
| `T2CNT0` | SFR | 0xAC | Timer 2 Count Low Byte |
| `T2CNT1` | SFR | 0xAD | Timer 2 Count High Byte |
| `T2PERIOD` | SFR16 | 0xAE | Timer 2 Period |
| `T2PERIOD0` | SFR | 0xAE | Timer 2 Period Low Byte |
| `T2PERIOD1` | SFR | 0xAF | Timer 2 Period High Byte |
| `EIP` | SFR | 0xB0 | Extended Interrupt Priority |
| `RADIOACC` | SFR | 0xB1 | Radio Controller Access Mode |
| `RADIOADDR1` | SFR | 0xB2 | Radio Register Address High Byte |
| `RADIOADDR0` | SFR | 0xB3 | Radio Register Address Low Byte |
| `RADIODATA3` | SFR | 0xB4 | Radio Register Data 3 |
| `RADIODATA2` | SFR | 0xB5 | Radio Register Data 2 |
| `RADIODATA1` | SFR | 0xB6 | Radio Register Data 1 |
| `RADIODATA0` | SFR | 0xB7 | Radio Register Data 0 |
| `IP` | SFR | 0xB8 | Interrupt Priority |
| `OC0MODE` | SFR | 0xB9 | Output Compare 0 Mode |
| `OC0PIN` | SFR | 0xBA | Output Compare 0 Pin Configuration |
| `OC0STATUS` | SFR | 0xBB | Output Compare 0 Status |
| `OC0COMP` | SFR16 | 0xBC | Output Compare 0 |
| `OC0COMP0` | SFR | 0xBC | Output Compare 0 Low Byte |
| `OC0COMP1` | SFR | 0xBD | Output Compare 0 High Byte |
| `RADIOSTAT` | SFR16 | 0xBE | Radio Access Status |
| `RADIOSTAT0` | SFR | 0xBE | Radio Access Status Low Byte |
| `RADIOSTAT1` | SFR | 0xBF | Radio Access Status High Byte |
| `E2IP` | SFR | 0xC0 | 2nd Extended Interrupt Priority |
| `OC1MODE` | SFR | 0xC1 | Output Compare 1 Mode |
| `OC1PIN` | SFR | 0xC2 | Output Compare 1 Pin Configuration |
| `OC1STATUS` | SFR | 0xC3 | Output Compare 1 Status |
| `OC1COMP` | SFR16 | 0xC4 | Output Compare 1 |
| `OC1COMP0` | SFR | 0xC4 | Output Compare 1 Low Byte |
| `OC1COMP1` | SFR | 0xC5 | Output Compare 1 High Byte |
| `CLKCON` | SFR | 0xC6 | Clock Control |
| `CLKSTAT` | SFR | 0xC7 | Clock Status |
| `PINA` | SFR | 0xC8 | Port A Input |
| `ADCCONV` | SFR | 0xC9 | ADC Conversion Source |
| `ADCCH0CONFIG` | SFR | 0xCA | ADC Channel 0 Configuration |
| `ADCCH1CONFIG` | SFR | 0xCB | ADC Channel 1 Configuration |
| `IC0MODE` | SFR | 0xCC | Input Capture 0 Mode |
| `IC0STATUS` | SFR | 0xCD | Input Capture 0 Status |
| `IC0CAPT` | SFR16 | 0xCE | Input Capture 0 |
| `IC0CAPT0` | SFR | 0xCE | Input Capture 0 Low Byte |
| `IC0CAPT1` | SFR | 0xCF | Input Capture 0 High Byte |
| `PSW` | SFR | 0xD0 | Program Status Word |
| `ADCCLKSRC` | SFR | 0xD1 | ADC Clock Source |
| `ADCCH2CONFIG` | SFR | 0xD2 | ADC Channel 2 Configuration |
| `ADCCH3CONFIG` | SFR | 0xD3 | ADC Channel 3 Configuration |
| `IC1MODE` | SFR | 0xD4 | Input Capture 1 Mode |
| `IC1STATUS` | SFR | 0xD5 | Input Capture 1 Status |
| `IC1CAPT` | SFR16 | 0xD6 | Input Capture 1 |
| `IC1CAPT0` | SFR | 0xD6 | Input Capture 1 Low Byte |
| `IC1CAPT1` | SFR | 0xD7 | Input Capture 1 High Byte |
| `XPAGE` | SFR | 0xD9 | Memory Page Select |
| `_XPAGE` | SFR | 0xD9 | Memory Page Select, SDCC name |
| `WDTCFG` | SFR | 0xDA | Watchdog Configuration |
| `WDTRESET` | SFR | 0xDB | Watchdog Reset |
| `SPMODE` | SFR | 0xDC | SPI Mode |
| `SPSTATUS` | SFR | 0xDD | SPI Status |
| `SPSHREG` | SFR | 0xDE | SPI Shift Register |
| `SPCLKSRC` | SFR | 0xDF | SPI Clock Source |
| `ACC` | SFR | 0xE0 | Accumulator |
| `ANALOGCOMP` | SFR | 0xE1 | Analog Comparators |
| `DBGLNKSTAT` | SFR | 0xE2 | Debug Link Status |
| `DBGLNKBUF` | SFR | 0xE3 | Debug Link Buffer |
| `U0CTRL` | SFR | 0xE4 | UART 0 Control |
| `U0STATUS` | SFR | 0xE5 | UART 0 Status |
| `U0SHREG` | SFR | 0xE6 | UART 0 Shift Register |
| `U0MODE` | SFR | 0xE7 | UART 0 Mode |
| `PINB` | SFR | 0xE8 | Port B Input |
| `WTIRQEN` | SFR | 0xE9 | Wakeup Timer Interrupt Enable |
| `WTSTAT` | SFR | 0xEA | Wakeup Timer Status |
| `WTCNTR1` | SFR | 0xEB | Wakeup Counter High Byte Latch |
| `U1CTRL` | SFR | 0xEC | UART 1 Control |
| `U1STATUS` | SFR | 0xED | UART 1 Status |
| `U1SHREG` | SFR | 0xEE | UART 1 Shift Register |
| `U1MODE` | SFR | 0xEF | UART 1 Mode |
| `B` | SFR | 0xF0 | B Register |
| `WTCFGA` | SFR | 0xF1 | Wakeup Timer A Configuration |
| `WTCNTA` | SFR16 | 0xF2 | Wakeup Counter A |
| `WTCNTA0` | SFR | 0xF2 | Wakeup Counter A Low Byte |
| `WTCNTA1` | SFR | 0xF3 | Wakeup Counter A High Byte |
| `WTEVTA` | SFR16 | 0xF4 | Wakeup Event A |
| `WTEVTA0` | SFR | 0xF4 | Wakeup Event A Low Byte |
| `WTEVTA1` | SFR | 0xF5 | Wakeup Event A High Byte |
| `WTEVTB` | SFR16 | 0xF6 | Wakeup Event B |
| `WTEVTB0` | SFR | 0xF6 | Wakeup Event B Low Byte |
| `WTEVTB1` | SFR | 0xF7 | Wakeup Event B High Byte |
| `PINC` | SFR | 0xF8 | Port C Input |
| `WTCFGB` | SFR | 0xF9 | Wakeup Timer B Configuration |
| `WTCNTB` | SFR16 | 0xFA | Wakeup Counter B |
| `WTCNTB0` | SFR | 0xFA | Wakeup Counter B Low Byte |
| `WTCNTB1` | SFR | 0xFB | Wakeup Counter B High Byte |
| `WTEVTC` | SFR16 | 0xFC | Wakeup Event C |
| `WTEVTC0` | SFR | 0xFC | Wakeup Event C Low Byte |
| `WTEVTC1` | SFR | 0xFD | Wakeup Event C High Byte |
| `WTEVTD` | SFR16 | 0xFE | Wakeup Event D |
| `WTEVTD0` | SFR | 0xFE | Wakeup Event D Low Byte |
| `WTEVTD1` | SFR | 0xFF | Wakeup Event D High Byte |
| `XDPTR0` | SFR16LEX | 0x3F82 | Data Pointer 0 |
| `XDPTR1` | SFR16LEX | 0x3F84 | Data Pointer 1 |
| `XNVADDR` | SFR16LEX | 0x3F92 | Non-Volatile Memory Address |
| `XNVDATA` | SFR16LEX | 0x3F94 | Non-Volatile Memory Data |
| `XT0CNT` | SFR16LEX | 0x3F9C | Timer 0 Count |
| `XT0PERIOD` | SFR16LEX | 0x3F9E | Timer 0 Period |
| `XT1CNT` | SFR16LEX | 0x3FA4 | Timer 1 Count |
| `XT1PERIOD` | SFR16LEX | 0x3FA6 | Timer 1 Period |
| `XT2CNT` | SFR16LEX | 0x3FAC | Timer 2 Count |
| `XT2PERIOD` | SFR16LEX | 0x3FAE | Timer 2 Period |
| `XOC0COMP` | SFR16LEX | 0x3FBC | Output Compare 0 |
| `XRADIOSTAT` | SFR16LEX | 0x3FBE | Radio Access Status |
| `XOC1COMP` | SFR16LEX | 0x3FC4 | Output Compare 1 |
| `XIC0CAPT` | SFR16LEX | 0x3FCE | Input Capture 0 |
| `XIC1CAPT` | SFR16LEX | 0x3FD6 | Input Capture 1 |
| `XWTCNTA` | SFR16LEX | 0x3FF2 | Wakeup Counter A |
| `XWTEVTA` | SFR16LEX | 0x3FF4 | Wakeup Event A |
| `XWTEVTB` | SFR16LEX | 0x3FF6 | Wakeup Event B |
| `XWTCNTB` | SFR16LEX | 0x3FFA | Wakeup Counter B |
| `XWTEVTC` | SFR16LEX | 0x3FFC | Wakeup Event C |
| `XWTEVTD` | SFR16LEX | 0x3FFE | Wakeup Event D |
| `DMA0ADDR` | SFR16LEX | 0x7010 | DMA Channel 0 Address |
| `DMA1ADDR` | SFR16LEX | 0x7012 | DMA Channel 1 Address |
| `ADCCH0VAL` | SFR16LEX | 0x7020 | ADC Channel 0 |
| `ADCCH1VAL` | SFR16LEX | 0x7022 | ADC Channel 1 |
| `ADCCH2VAL` | SFR16LEX | 0x7024 | ADC Channel 2 |
| `ADCCH3VAL` | SFR16LEX | 0x7026 | ADC Channel 3 |
| `RADIOFDATAADDR` | SFR16LEX | 0x7040 | Radio FIFO Data Register Address |
| `RADIOFSTATADDR` | SFR16LEX | 0x7042 | Radio FIFO Status Register Address |
| `LPOSCKFILT` | SFR16LEX | 0x7062 | Low Power Oscillator Calibration Filter Constant |
| `LPOSCREF` | SFR16LEX | 0x7064 | Low Power Oscillator Reference Frequency |
| `LPOSCFREQ` | SFR16LEX | 0x7066 | Low Power Oscillator Frequency Tuning |
| `LPOSCPER` | SFR16LEX | 0x7068 | Low Power Oscillator Period |
| `FRCOSCKFILT` | SFR16LEX | 0x7072 | Fast RC Oscillator Calibration Filter Constant |
| `FRCOSCREF` | SFR16LEX | 0x7074 | Fast RC Oscillator Reference Frequency |
| `FRCOSCFREQ` | SFR16LEX | 0x7076 | Fast RC Oscillator Frequency Tuning |
| `FRCOSCPER` | SFR16LEX | 0x7078 | Fast RC Oscillator Period |
| `RADIOADDR` | SFR16E | 0xB2B3 | Radio Register Address |
| `RADIODATA` | SFR32E | 0xB4B5B6B7 | Radio Register Data |

## AX8052 X-space registers (XREG, movx)

| Name | Kind | Address | Description |
|---|---|---|---|
| `XPORTA` | SFRX | 0x3F80 | Port A Output |
| `XPCON` | SFRX | 0x3F87 | Power Mode Control |
| `XPORTB` | SFRX | 0x3F88 | Port B Output |
| `XDIRA` | SFRX | 0x3F89 | Port A Direction |
| `XDIRB` | SFRX | 0x3F8A | Port B Direction |
| `XDIRC` | SFRX | 0x3F8B | Port C Direction |
| `XPORTR` | SFRX | 0x3F8C | Port R Output |
| `XPINR` | SFRX | 0x3F8D | Port R Input |
| `XDIRR` | SFRX | 0x3F8E | Port R Direction |
| `XPORTC` | SFRX | 0x3F90 | Port C Output |
| `XNVSTATUS` | SFRX | 0x3F91 | Non-Volatile Memory Command / Status |
| `XNVADDR0` | SFRX | 0x3F92 | Non-Volatile Memory Address Low Byte |
| `XNVADDR1` | SFRX | 0x3F93 | Non-Volatile Memory Address High Byte |
| `XNVDATA0` | SFRX | 0x3F94 | Non-Volatile Memory Data Low Byte |
| `XNVDATA1` | SFRX | 0x3F95 | Non-Volatile Memory Data High Byte |
| `XNVKEY` | SFRX | 0x3F96 | Non-Volatile Memory Write/Erase Key |
| `XCODECONFIG` | SFRX | 0x3F97 | Code Space Configuration |
| `XT0MODE` | SFRX | 0x3F99 | Timer 0 Mode |
| `XT0CLKSRC` | SFRX | 0x3F9A | Timer 0 Clock Source |
| `XT0STATUS` | SFRX | 0x3F9B | Timer 0 Status |
| `XT0CNT0` | SFRX | 0x3F9C | Timer 0 Count Low Byte |
| `XT0CNT1` | SFRX | 0x3F9D | Timer 0 Count High Byte |
| `XT0PERIOD0` | SFRX | 0x3F9E | Timer 0 Period Low Byte |
| `XT0PERIOD1` | SFRX | 0x3F9F | Timer 0 Period High Byte |
| `XT1MODE` | SFRX | 0x3FA1 | Timer 1 Mode |
| `XT1CLKSRC` | SFRX | 0x3FA2 | Timer 1 Clock Source |
| `XT1STATUS` | SFRX | 0x3FA3 | Timer 1 Status |
| `XT1CNT0` | SFRX | 0x3FA4 | Timer 1 Count Low Byte |
| `XT1CNT1` | SFRX | 0x3FA5 | Timer 1 Count High Byte |
| `XT1PERIOD0` | SFRX | 0x3FA6 | Timer 1 Period Low Byte |
| `XT1PERIOD1` | SFRX | 0x3FA7 | Timer 1 Period High Byte |
| `XIE` | SFRX | 0x3FA8 | Interrupt Enable |
| `XT2MODE` | SFRX | 0x3FA9 | Timer 2 Mode |
| `XT2CLKSRC` | SFRX | 0x3FAA | Timer 2 Clock Source |
| `XT2STATUS` | SFRX | 0x3FAB | Timer 2 Status |
| `XT2CNT0` | SFRX | 0x3FAC | Timer 2 Count Low Byte |
| `XT2CNT1` | SFRX | 0x3FAD | Timer 2 Count High Byte |
| `XT2PERIOD0` | SFRX | 0x3FAE | Timer 2 Period Low Byte |
| `XT2PERIOD1` | SFRX | 0x3FAF | Timer 2 Period High Byte |
| `XRADIOACC` | SFRX | 0x3FB1 | Radio Controller Access Mode |
| `XRADIOADDR1` | SFRX | 0x3FB2 | Radio Register Address High Byte |
| `XRADIOADDR0` | SFRX | 0x3FB3 | Radio Register Address Low Byte |
| `XRADIODATA3` | SFRX | 0x3FB4 | Radio Register Data 3 |
| `XRADIODATA2` | SFRX | 0x3FB5 | Radio Register Data 2 |
| `XRADIODATA1` | SFRX | 0x3FB6 | Radio Register Data 1 |
| `XRADIODATA0` | SFRX | 0x3FB7 | Radio Register Data 0 |
| `XIP` | SFRX | 0x3FB8 | Interrupt Priority |
| `XOC0MODE` | SFRX | 0x3FB9 | Output Compare 0 Mode |
| `XOC0PIN` | SFRX | 0x3FBA | Output Compare 0 Pin Configuration |
| `XOC0STATUS` | SFRX | 0x3FBB | Output Compare 0 Status |
| `XOC0COMP0` | SFRX | 0x3FBC | Output Compare 0 Low Byte |
| `XOC0COMP1` | SFRX | 0x3FBD | Output Compare 0 High Byte |
| `XRADIOSTAT0` | SFRX | 0x3FBE | Radio Access Status Low Byte |
| `XRADIOSTAT1` | SFRX | 0x3FBF | Radio Access Status High Byte |
| `XOC1MODE` | SFRX | 0x3FC1 | Output Compare 1 Mode |
| `XOC1PIN` | SFRX | 0x3FC2 | Output Compare 1 Pin Configuration |
| `XOC1STATUS` | SFRX | 0x3FC3 | Output Compare 1 Status |
| `XOC1COMP0` | SFRX | 0x3FC4 | Output Compare 1 Low Byte |
| `XOC1COMP1` | SFRX | 0x3FC5 | Output Compare 1 High Byte |
| `XCLKCON` | SFRX | 0x3FC6 | Clock Control |
| `XCLKSTAT` | SFRX | 0x3FC7 | Clock Status |
| `XPINA` | SFRX | 0x3FC8 | Port A Input |
| `XADCCONV` | SFRX | 0x3FC9 | ADC Conversion Source |
| `XADCCH0CONFIG` | SFRX | 0x3FCA | ADC Channel 0 Configuration |
| `XADCCH1CONFIG` | SFRX | 0x3FCB | ADC Channel 1 Configuration |
| `XIC0MODE` | SFRX | 0x3FCC | Input Capture 0 Mode |
| `XIC0STATUS` | SFRX | 0x3FCD | Input Capture 0 Status |
| `XIC0CAPT0` | SFRX | 0x3FCE | Input Capture 0 Low Byte |
| `XIC0CAPT1` | SFRX | 0x3FCF | Input Capture 0 High Byte |
| `XADCCLKSRC` | SFRX | 0x3FD1 | ADC Clock Source |
| `XADCCH2CONFIG` | SFRX | 0x3FD2 | ADC Channel 2 Configuration |
| `XADCCH3CONFIG` | SFRX | 0x3FD3 | ADC Channel 3 Configuration |
| `XIC1MODE` | SFRX | 0x3FD4 | Input Capture 1 Mode |
| `XIC1STATUS` | SFRX | 0x3FD5 | Input Capture 1 Status |
| `XIC1CAPT0` | SFRX | 0x3FD6 | Input Capture 1 Low Byte |
| `XIC1CAPT1` | SFRX | 0x3FD7 | Input Capture 1 High Byte |
| `XWDTCFG` | SFRX | 0x3FDA | Watchdog Configuration |
| `XWDTRESET` | SFRX | 0x3FDB | Watchdog Reset |
| `XSPMODE` | SFRX | 0x3FDC | SPI Mode |
| `XSPSTATUS` | SFRX | 0x3FDD | SPI Status |
| `XSPSHREG` | SFRX | 0x3FDE | SPI Shift Register |
| `XSPCLKSRC` | SFRX | 0x3FDF | SPI Clock Source |
| `XANALOGCOMP` | SFRX | 0x3FE1 | Analog Comparators |
| `XDBGLNKSTAT` | SFRX | 0x3FE2 | Debug Link Status |
| `XDBGLNKBUF` | SFRX | 0x3FE3 | Debug Link Buffer |
| `XU0CTRL` | SFRX | 0x3FE4 | UART 0 Control |
| `XU0STATUS` | SFRX | 0x3FE5 | UART 0 Status |
| `XU0SHREG` | SFRX | 0x3FE6 | UART 0 Shift Register |
| `XU0MODE` | SFRX | 0x3FE7 | UART 0 Mode |
| `XPINB` | SFRX | 0x3FE8 | Port B Input |
| `XWTIRQEN` | SFRX | 0x3FE9 | Wakeup Timer Interrupt Enable |
| `XWTSTAT` | SFRX | 0x3FEA | Wakeup Timer Status |
| `XWTCNTR1` | SFRX | 0x3FEB | Wakeup Counter High Byte Latch |
| `XU1CTRL` | SFRX | 0x3FEC | UART 1 Control |
| `XU1STATUS` | SFRX | 0x3FED | UART 1 Status |
| `XU1SHREG` | SFRX | 0x3FEE | UART 1 Shift Register |
| `XU1MODE` | SFRX | 0x3FEF | UART 1 Mode |
| `XWTCFGA` | SFRX | 0x3FF1 | Wakeup Timer A Configuration |
| `XWTCNTA0` | SFRX | 0x3FF2 | Wakeup Counter A Low Byte |
| `XWTCNTA1` | SFRX | 0x3FF3 | Wakeup Counter A High Byte |
| `XWTEVTA0` | SFRX | 0x3FF4 | Wakeup Event A Low Byte |
| `XWTEVTA1` | SFRX | 0x3FF5 | Wakeup Event A High Byte |
| `XWTEVTB0` | SFRX | 0x3FF6 | Wakeup Event B Low Byte |
| `XWTEVTB1` | SFRX | 0x3FF7 | Wakeup Event B High Byte |
| `XPINC` | SFRX | 0x3FF8 | Port C Input |
| `XWTCFGB` | SFRX | 0x3FF9 | Wakeup Timer B Configuration |
| `XWTCNTB0` | SFRX | 0x3FFA | Wakeup Counter B Low Byte |
| `XWTCNTB1` | SFRX | 0x3FFB | Wakeup Counter B High Byte |
| `XWTEVTC0` | SFRX | 0x3FFC | Wakeup Event C Low Byte |
| `XWTEVTC1` | SFRX | 0x3FFD | Wakeup Event C High Byte |
| `XWTEVTD0` | SFRX | 0x3FFE | Wakeup Event D Low Byte |
| `XWTEVTD1` | SFRX | 0x3FFF | Wakeup Event D High Byte |
| `INTCHGA` | SFRX | 0x7000 | Port A Interrupt on Change |
| `INTCHGB` | SFRX | 0x7001 | Port B Interrupt on Change |
| `INTCHGC` | SFRX | 0x7002 | Port C Interrupt on Change |
| `EXTIRQ` | SFRX | 0x7003 | External IRQ Configuration |
| `PINCHGA` | SFRX | 0x7004 | Port A Level Change |
| `PINCHGB` | SFRX | 0x7005 | Port B Level Change |
| `PINCHGC` | SFRX | 0x7006 | Port C Level Change |
| `ANALOGA` | SFRX | 0x7007 | Port A Analog Mode |
| `PALTA` | SFRX | 0x7008 | Port A Alternate Function |
| `PALTB` | SFRX | 0x7009 | Port B Alternate Function |
| `PALTC` | SFRX | 0x700A | Port C Alternate Function |
| `PINSEL` | SFRX | 0x700B | Port Input Selection |
| `GPIOENABLE` | SFRX | 0x700C | GPIO Port Enable |
| `DMA0ADDR0` | SFRX | 0x7010 | DMA Channel 0 Address Low Byte |
| `DMA0ADDR1` | SFRX | 0x7011 | DMA Channel 0 Address High Byte |
| `DMA1ADDR0` | SFRX | 0x7012 | DMA Channel 1 Address Low Byte |
| `DMA1ADDR1` | SFRX | 0x7013 | DMA Channel 1 Address High Byte |
| `DMA0CONFIG` | SFRX | 0x7014 | DMA Channel 0 Configuration |
| `DMA1CONFIG` | SFRX | 0x7015 | DMA Channel 1 Configuration |
| `ADCCH0VAL0` | SFRX | 0x7020 | ADC Channel 0 Low Byte |
| `ADCCH0VAL1` | SFRX | 0x7021 | ADC Channel 0 High Byte |
| `ADCCH1VAL0` | SFRX | 0x7022 | ADC Channel 1 Low Byte |
| `ADCCH1VAL1` | SFRX | 0x7023 | ADC Channel 1 High Byte |
| `ADCCH2VAL0` | SFRX | 0x7024 | ADC Channel 2 Low Byte |
| `ADCCH2VAL1` | SFRX | 0x7025 | ADC Channel 2 High Byte |
| `ADCCH3VAL0` | SFRX | 0x7026 | ADC Channel 3 Low Byte |
| `ADCCH3VAL1` | SFRX | 0x7027 | ADC Channel 3 High Byte |
| `ADCTUNE0` | SFRX | 0x7028 | ADC Tuning 0 |
| `ADCTUNE1` | SFRX | 0x7029 | ADC Tuning 1 |
| `ADCTUNE2` | SFRX | 0x702A | ADC Tuning 2 |
| `RADIOFDATAADDR0` | SFRX | 0x7040 | Radio FIFO Data Register Address Low Byte |
| `RADIOFDATAADDR1` | SFRX | 0x7041 | Radio FIFO Data Register Address High Byte |
| `RADIOFSTATADDR0` | SFRX | 0x7042 | Radio FIFO Status Register Address Low Byte |
| `RADIOFSTATADDR1` | SFRX | 0x7043 | Radio FIFO Status Register Address High Byte |
| `RADIOMUX` | SFRX | 0x7044 | Radio Multiplexer Control |
| `PALTRADIO` | SFRX | 0x7046 | Port Radio Alternate Function |
| `OSCFORCERUN` | SFRX | 0x7050 | Oscillator Run Force |
| `OSCRUN` | SFRX | 0x7051 | Oscillator Run Status |
| `OSCREADY` | SFRX | 0x7052 | Oscillator Ready Status |
| `OSCCALIB` | SFRX | 0x7053 | Oscillator Calibration Interrupt / Status |
| `LPXOSCGM` | SFRX | 0x7054 | Low Power Crystal Oscillator Transconductance |
| `LPOSCCONFIG` | SFRX | 0x7060 | Low Power Oscillator Calibration Configuration |
| `LPOSCKFILT0` | SFRX | 0x7062 | Low Power Oscillator Calibration Filter Constant Low Byte |
| `LPOSCKFILT1` | SFRX | 0x7063 | Low Power Oscillator Calibration Filter Constant High Byte |
| `LPOSCREF0` | SFRX | 0x7064 | Low Power Oscillator Reference Frequency Low Byte |
| `LPOSCREF1` | SFRX | 0x7065 | Low Power Oscillator Reference Frequency High Byte |
| `LPOSCFREQ0` | SFRX | 0x7066 | Low Power Oscillator Frequency Tuning Low Byte |
| `LPOSCFREQ1` | SFRX | 0x7067 | Low Power Oscillator Frequency Tuning High Byte |
| `LPOSCPER0` | SFRX | 0x7068 | Low Power Oscillator Period Low Byte |
| `LPOSCPER1` | SFRX | 0x7069 | Low Power Oscillator Period High Byte |
| `FRCOSCCONFIG` | SFRX | 0x7070 | Fast RC Oscillator Calibration Configuration |
| `FRCOSCCTRL` | SFRX | 0x7071 | Fast RC Oscillator Control |
| `FRCOSCKFILT0` | SFRX | 0x7072 | Fast RC Oscillator Calibration Filter Constant Low Byte |
| `FRCOSCKFILT1` | SFRX | 0x7073 | Fast RC Oscillator Calibration Filter Constant High Byte |
| `FRCOSCREF0` | SFRX | 0x7074 | Fast RC Oscillator Reference Frequency Low Byte |
| `FRCOSCREF1` | SFRX | 0x7075 | Fast RC Oscillator Reference Frequency High Byte |
| `FRCOSCFREQ0` | SFRX | 0x7076 | Fast RC Oscillator Frequency Tuning Low Byte |
| `FRCOSCFREQ1` | SFRX | 0x7077 | Fast RC Oscillator Frequency Tuning High Byte |
| `FRCOSCPER0` | SFRX | 0x7078 | Fast RC Oscillator Period Low Byte |
| `FRCOSCPER1` | SFRX | 0x7079 | Fast RC Oscillator Period High Byte |
| `SCRATCH0` | SFRX | 0x7084 | Scratch Register 0 |
| `SCRATCH1` | SFRX | 0x7085 | Scratch Register 1 |
| `SCRATCH2` | SFRX | 0x7086 | Scratch Register 2 |
| `SCRATCH3` | SFRX | 0x7087 | Scratch Register 3 |
| `SILICONREV` | SFRX | 0x7F00 | Silicon Revision |
| `MISCCTRL` | SFRX | 0x7F01 | Miscellaneous Control |
| `XTALOSC` | SFRX | 0x7F18 | Crystal Oscillator Configuration |
| `XTALAMPL` | SFRX | 0x7F19 | Crystal Oscillator Amplitude Control |
| `XTALREADY` | SFRX | 0x7F1A | Crystal Oscillator Ready Mode |

## Bit-addressable SFR bits (SBIT)

| Name | SFR | Bit | Description |
|---|---|---|---|
| `ACC_0` | 0xE0 | 0 | Accumulator bit 0 |
| `ACC_1` | 0xE0 | 1 | Accumulator bit 1 |
| `ACC_2` | 0xE0 | 2 | Accumulator bit 2 |
| `ACC_3` | 0xE0 | 3 | Accumulator bit 3 |
| `ACC_4` | 0xE0 | 4 | Accumulator bit 4 |
| `ACC_5` | 0xE0 | 5 | Accumulator bit 5 |
| `ACC_6` | 0xE0 | 6 | Accumulator bit 6 |
| `ACC_7` | 0xE0 | 7 | Accumulator bit 7 |
| `B_0` | 0xF0 | 0 | Register B bit 0 |
| `B_1` | 0xF0 | 1 | Register B bit 1 |
| `B_2` | 0xF0 | 2 | Register B bit 2 |
| `B_3` | 0xF0 | 3 | Register B bit 3 |
| `B_4` | 0xF0 | 4 | Register B bit 4 |
| `B_5` | 0xF0 | 5 | Register B bit 5 |
| `B_6` | 0xF0 | 6 | Register B bit 6 |
| `B_7` | 0xF0 | 7 | Register B bit 7 |
| `E2IE_0` | 0xA0 | 0 | Output Compare 0 Interrupt Enable |
| `E2IE_1` | 0xA0 | 1 | Output Compare 1 Interrupt Enable |
| `E2IE_2` | 0xA0 | 2 | Input Capture 0 Interrupt Enable |
| `E2IE_3` | 0xA0 | 3 | Input Capture 1 Interrupt Enable |
| `E2IE_4` | 0xA0 | 4 |  |
| `E2IE_5` | 0xA0 | 5 |  |
| `E2IE_6` | 0xA0 | 6 | DebugLink Interrupt Enable |
| `E2IE_7` | 0xA0 | 7 |  |
| `E2IP_0` | 0xC0 | 0 | Output Compare 0 Interrupt Priority |
| `E2IP_1` | 0xC0 | 1 | Output Compare 1 Interrupt Priority |
| `E2IP_2` | 0xC0 | 2 | Input Capture 0 Interrupt Priority |
| `E2IP_3` | 0xC0 | 3 | Input Capture 1 Interrupt Priority |
| `E2IP_4` | 0xC0 | 4 |  |
| `E2IP_5` | 0xC0 | 5 |  |
| `E2IP_6` | 0xC0 | 6 | DebugLink Interrupt Priority |
| `E2IP_7` | 0xC0 | 7 |  |
| `EIE_0` | 0x98 | 0 | Timer 0 Interrupt Enable |
| `EIE_1` | 0x98 | 1 | Timer 1 Interrupt Enable |
| `EIE_2` | 0x98 | 2 | Timer 2 Interrupt Enable |
| `EIE_3` | 0x98 | 3 | SPI 0 Interrupt Enable |
| `EIE_4` | 0x98 | 4 | UART 0 Interrupt Enable |
| `EIE_5` | 0x98 | 5 | UART 1 Interrupt Enable |
| `EIE_6` | 0x98 | 6 | GPADC Interrupt Enable |
| `EIE_7` | 0x98 | 7 | DMA Interrupt Enable |
| `EIP_0` | 0xB0 | 0 | Timer 0 Interrupt Priority |
| `EIP_1` | 0xB0 | 1 | Timer 1 Interrupt Priority |
| `EIP_2` | 0xB0 | 2 | Timer 2 Interrupt Priority |
| `EIP_3` | 0xB0 | 3 | SPI 0 Interrupt Priority |
| `EIP_4` | 0xB0 | 4 | UART 0 Interrupt Priority |
| `EIP_5` | 0xB0 | 5 | UART 1 Interrupt Priority |
| `EIP_6` | 0xB0 | 6 | GPADC Interrupt Priority |
| `EIP_7` | 0xB0 | 7 | DMA Interrupt Priority |
| `IE_0` | 0xA8 | 0 | External 0 Interrupt Enable |
| `IE_1` | 0xA8 | 1 | Wakeup Timer Interrupt Enable |
| `IE_2` | 0xA8 | 2 | External 1 Interrupt Enable |
| `IE_3` | 0xA8 | 3 | GPIO Interrupt Enable |
| `IE_4` | 0xA8 | 4 | Radio Interrupt Enable |
| `IE_5` | 0xA8 | 5 | Clock Management Interrupt Enable |
| `IE_6` | 0xA8 | 6 | Power Management Interrupt Enable |
| `IE_7` | 0xA8 | 7 | Global Interrupt Enable |
| `EA` | 0xA8 | 7 | Global Interrupt Enable |
| `IP_0` | 0xB8 | 0 | External 0 Interrupt Priority |
| `IP_1` | 0xB8 | 1 | Wakeup Timer Interrupt Priority |
| `IP_2` | 0xB8 | 2 | External 1 Interrupt Priority |
| `IP_3` | 0xB8 | 3 | GPIO Interrupt Priority |
| `IP_4` | 0xB8 | 4 | Radio Interrupt Priority |
| `IP_5` | 0xB8 | 5 | Clock Management Interrupt Priority |
| `IP_6` | 0xB8 | 6 | Power Management Interrupt Priority |
| `IP_7` | 0xB8 | 7 |  |
| `P` | 0xD0 | 0 | Parity Flag |
| `F1` | 0xD0 | 1 | User-Defined Flag |
| `OV` | 0xD0 | 2 | Overflow Flag |
| `RS0` | 0xD0 | 3 | Register Bank Select 0 |
| `RS1` | 0xD0 | 4 | Register Bank Select 1 |
| `F0` | 0xD0 | 5 | User-Defined Flag |
| `AC` | 0xD0 | 6 | Auxiliary Carry Flag |
| `CY` | 0xD0 | 7 | Carry Flag |
| `PINA_0` | 0xC8 | 0 |  |
| `PINA_1` | 0xC8 | 1 |  |
| `PINA_2` | 0xC8 | 2 |  |
| `PINA_3` | 0xC8 | 3 |  |
| `PINA_4` | 0xC8 | 4 |  |
| `PINA_5` | 0xC8 | 5 |  |
| `PINA_6` | 0xC8 | 6 |  |
| `PINA_7` | 0xC8 | 7 |  |
| `PINB_0` | 0xE8 | 0 |  |
| `PINB_1` | 0xE8 | 1 |  |
| `PINB_2` | 0xE8 | 2 |  |
| `PINB_3` | 0xE8 | 3 |  |
| `PINB_4` | 0xE8 | 4 |  |
| `PINB_5` | 0xE8 | 5 |  |
| `PINB_6` | 0xE8 | 6 |  |
| `PINB_7` | 0xE8 | 7 |  |
| `PINC_0` | 0xF8 | 0 |  |
| `PINC_1` | 0xF8 | 1 |  |
| `PINC_2` | 0xF8 | 2 |  |
| `PINC_3` | 0xF8 | 3 |  |
| `PINC_4` | 0xF8 | 4 |  |
| `PINC_5` | 0xF8 | 5 |  |
| `PINC_6` | 0xF8 | 6 |  |
| `PINC_7` | 0xF8 | 7 |  |
| `PORTA_0` | 0x80 | 0 |  |
| `PORTA_1` | 0x80 | 1 |  |
| `PORTA_2` | 0x80 | 2 |  |
| `PORTA_3` | 0x80 | 3 |  |
| `PORTA_4` | 0x80 | 4 |  |
| `PORTA_5` | 0x80 | 5 |  |
| `PORTA_6` | 0x80 | 6 |  |
| `PORTA_7` | 0x80 | 7 |  |
| `PORTB_0` | 0x88 | 0 |  |
| `PORTB_1` | 0x88 | 1 |  |
| `PORTB_2` | 0x88 | 2 |  |
| `PORTB_3` | 0x88 | 3 |  |
| `PORTB_4` | 0x88 | 4 |  |
| `PORTB_5` | 0x88 | 5 |  |
| `PORTB_6` | 0x88 | 6 |  |
| `PORTB_7` | 0x88 | 7 |  |
| `PORTC_0` | 0x90 | 0 |  |
| `PORTC_1` | 0x90 | 1 |  |
| `PORTC_2` | 0x90 | 2 |  |
| `PORTC_3` | 0x90 | 3 |  |
| `PORTC_4` | 0x90 | 4 |  |
| `PORTC_5` | 0x90 | 5 |  |
| `PORTC_6` | 0x90 | 6 |  |
| `PORTC_7` | 0x90 | 7 |  |

## AX5043 registers as seen from the AX8052F143 (X space 0x4000-0x4FFF, blocking)

| Name | Kind | Address | Description |
|---|---|---|---|
| `AX5043_SILICONREVISION` | SFRX | 0x4000 | Silicon Revision |
| `AX5043_SCRATCH` | SFRX | 0x4001 | Scratch |
| `AX5043_PWRMODE` | SFRX | 0x4002 | Power Mode |
| `AX5043_POWSTAT` | SFRX | 0x4003 | Power Management Status |
| `AX5043_POWSTICKYSTAT` | SFRX | 0x4004 | Power Management Sticky Status |
| `AX5043_POWIRQMASK` | SFRX | 0x4005 | Power Management Interrupt Mask |
| `AX5043_IRQMASK1` | SFRX | 0x4006 | IRQ Mask 1 |
| `AX5043_IRQMASK0` | SFRX | 0x4007 | IRQ Mask 0 |
| `AX5043_RADIOEVENTMASK1` | SFRX | 0x4008 | Radio Event Mask 1 |
| `AX5043_RADIOEVENTMASK0` | SFRX | 0x4009 | Radio Event Mask 0 |
| `AX5043_IRQINVERSION1` | SFRX | 0x400A | IRQ Inversion 1 |
| `AX5043_IRQINVERSION0` | SFRX | 0x400B | IRQ Inversion 0 |
| `AX5043_IRQREQUEST1` | SFRX | 0x400C | IRQ Request 1 |
| `AX5043_IRQREQUEST0` | SFRX | 0x400D | IRQ Request 0 |
| `AX5043_RADIOEVENTREQ1` | SFRX | 0x400E | Radio Event Request 1 |
| `AX5043_RADIOEVENTREQ0` | SFRX | 0x400F | Radio Event Request 0 |
| `AX5043_MODULATION` | SFRX | 0x4010 | Modulation |
| `AX5043_ENCODING` | SFRX | 0x4011 | Encoding |
| `AX5043_FRAMING` | SFRX | 0x4012 | Framing Mode |
| `AX5043_CRCINIT3` | SFRX | 0x4014 | CRC Initial Value 3 |
| `AX5043_CRCINIT2` | SFRX | 0x4015 | CRC Initial Value 2 |
| `AX5043_CRCINIT1` | SFRX | 0x4016 | CRC Initial Value 1 |
| `AX5043_CRCINIT0` | SFRX | 0x4017 | CRC Initial Value 0 |
| `AX5043_FEC` | SFRX | 0x4018 | Forward Error Correction |
| `AX5043_FECSYNC` | SFRX | 0x4019 | Forward Error Correction Sync Threshold |
| `AX5043_FECSTATUS` | SFRX | 0x401A | Forward Error Correction Status |
| `AX5043_RADIOSTATE` | SFRX | 0x401C | Radio Controller State |
| `AX5043_XTALSTATUS` | SFRX | 0x401D | Crystal Oscillator Status |
| `AX5043_PINSTATE` | SFRX | 0x4020 | Pin State |
| `AX5043_PINFUNCSYSCLK` | SFRX | 0x4021 | Pin Function SYSCLK |
| `AX5043_PINFUNCDCLK` | SFRX | 0x4022 | Pin Function DCLK |
| `AX5043_PINFUNCDATA` | SFRX | 0x4023 | Pin Function DATA |
| `AX5043_PINFUNCIRQ` | SFRX | 0x4024 | Pin Function IRQ |
| `AX5043_PINFUNCANTSEL` | SFRX | 0x4025 | Pin Function ANTSEL |
| `AX5043_PINFUNCPWRAMP` | SFRX | 0x4026 | Pin Function PWRAMP |
| `AX5043_PWRAMP` | SFRX | 0x4027 | PWRAMP Control |
| `AX5043_FIFOSTAT` | SFRX | 0x4028 | FIFO Control |
| `AX5043_FIFODATA` | SFRX | 0x4029 | FIFO Data |
| `AX5043_FIFOCOUNT1` | SFRX | 0x402A | Number of Words currently in FIFO 1 |
| `AX5043_FIFOCOUNT0` | SFRX | 0x402B | Number of Words currently in FIFO 0 |
| `AX5043_FIFOFREE1` | SFRX | 0x402C | Number of Words that can be written to FIFO 1 |
| `AX5043_FIFOFREE0` | SFRX | 0x402D | Number of Words that can be written to FIFO 0 |
| `AX5043_FIFOTHRESH1` | SFRX | 0x402E | FIFO Threshold 1 |
| `AX5043_FIFOTHRESH0` | SFRX | 0x402F | FIFO Threshold 0 |
| `AX5043_PLLLOOP` | SFRX | 0x4030 | PLL Loop Filter Settings |
| `AX5043_PLLCPI` | SFRX | 0x4031 | PLL Charge Pump Current |
| `AX5043_PLLVCODIV` | SFRX | 0x4032 | PLL Divider Settings |
| `AX5043_PLLRANGINGA` | SFRX | 0x4033 | PLL Autoranging A |
| `AX5043_FREQA3` | SFRX | 0x4034 | Frequency A 3 |
| `AX5043_FREQA2` | SFRX | 0x4035 | Frequency A 2 |
| `AX5043_FREQA1` | SFRX | 0x4036 | Frequency A 1 |
| `AX5043_FREQA0` | SFRX | 0x4037 | Frequency A 0 |
| `AX5043_PLLLOOPBOOST` | SFRX | 0x4038 | PLL Loop Filter Settings (Boosted) |
| `AX5043_PLLCPIBOOST` | SFRX | 0x4039 | PLL Charge Pump Current (Boosted) |
| `AX5043_PLLRANGINGB` | SFRX | 0x403B | PLL Autoranging B |
| `AX5043_FREQB3` | SFRX | 0x403C | Frequency B 3 |
| `AX5043_FREQB2` | SFRX | 0x403D | Frequency B 2 |
| `AX5043_FREQB1` | SFRX | 0x403E | Frequency B 1 |
| `AX5043_FREQB0` | SFRX | 0x403F | Frequency B 0 |
| `AX5043_RSSI` | SFRX | 0x4040 | Received Signal Strength Indicator |
| `AX5043_BGNDRSSI` | SFRX | 0x4041 | Background RSSI |
| `AX5043_DIVERSITY` | SFRX | 0x4042 | Antenna Diversity Configuration |
| `AX5043_AGCCOUNTER` | SFRX | 0x4043 | AGC Counter |
| `AX5043_TRKDATARATE2` | SFRX | 0x4045 | Datarate Tracking 2 |
| `AX5043_TRKDATARATE1` | SFRX | 0x4046 | Datarate Tracking 1 |
| `AX5043_TRKDATARATE0` | SFRX | 0x4047 | Datarate Tracking 0 |
| `AX5043_TRKAMPLITUDE1` | SFRX | 0x4048 | Amplitude Tracking 1 |
| `AX5043_TRKAMPLITUDE0` | SFRX | 0x4049 | Amplitude Tracking 0 |
| `AX5043_TRKPHASE1` | SFRX | 0x404A | Phase Tracking 1 |
| `AX5043_TRKPHASE0` | SFRX | 0x404B | Phase Tracking 0 |
| `AX5043_TRKRFFREQ2` | SFRX | 0x404D | RF Frequency Tracking 2 |
| `AX5043_TRKRFFREQ1` | SFRX | 0x404E | RF Frequency Tracking 1 |
| `AX5043_TRKRFFREQ0` | SFRX | 0x404F | RF Frequency Tracking 0 |
| `AX5043_TRKFREQ1` | SFRX | 0x4050 | Frequency Tracking 1 |
| `AX5043_TRKFREQ0` | SFRX | 0x4051 | Frequency Tracking 0 |
| `AX5043_TRKFSKDEMOD1` | SFRX | 0x4052 | FSK Demodulator Tracking 1 |
| `AX5043_TRKFSKDEMOD0` | SFRX | 0x4053 | FSK Demodulator Tracking 0 |
| `AX5043_TRKAFSKDEMOD1` | SFRX | 0x4054 | AFSK Demodulator Tracking 1 |
| `AX5043_TRKAFSKDEMOD0` | SFRX | 0x4055 | AFSK Demodulator Tracking 0 |
| `AX5043_TIMER2` | SFRX | 0x4059 | 1MHz Timer 2 |
| `AX5043_TIMER1` | SFRX | 0x405A | 1MHz Timer 1 |
| `AX5043_TIMER0` | SFRX | 0x405B | 1MHz Timer 0 |
| `AX5043_WAKEUPTIMER1` | SFRX | 0x4068 | Wakeup Timer 1 |
| `AX5043_WAKEUPTIMER0` | SFRX | 0x4069 | Wakeup Timer 0 |
| `AX5043_WAKEUP1` | SFRX | 0x406A | Wakeup Time 1 |
| `AX5043_WAKEUP0` | SFRX | 0x406B | Wakeup Time 0 |
| `AX5043_WAKEUPFREQ1` | SFRX | 0x406C | Wakeup Frequency 1 |
| `AX5043_WAKEUPFREQ0` | SFRX | 0x406D | Wakeup Frequency 0 |
| `AX5043_WAKEUPXOEARLY` | SFRX | 0x406E | Wakeup Crystal Oscillator Early |
| `AX5043_IFFREQ1` | SFRX | 0x4100 | 2nd LO / IF Frequency 1 |
| `AX5043_IFFREQ0` | SFRX | 0x4101 | 2nd LO / IF Frequency 0 |
| `AX5043_DECIMATION` | SFRX | 0x4102 | Decimation Factor |
| `AX5043_RXDATARATE2` | SFRX | 0x4103 | Receiver Datarate 2 |
| `AX5043_RXDATARATE1` | SFRX | 0x4104 | Receiver Datarate 1 |
| `AX5043_RXDATARATE0` | SFRX | 0x4105 | Receiver Datarate 0 |
| `AX5043_MAXDROFFSET2` | SFRX | 0x4106 | Maximum Receiver Datarate Offset 2 |
| `AX5043_MAXDROFFSET1` | SFRX | 0x4107 | Maximum Receiver Datarate Offset 1 |
| `AX5043_MAXDROFFSET0` | SFRX | 0x4108 | Maximum Receiver Datarate Offset 0 |
| `AX5043_MAXRFOFFSET2` | SFRX | 0x4109 | Maximum Receiver RF Offset 2 |
| `AX5043_MAXRFOFFSET1` | SFRX | 0x410A | Maximum Receiver RF Offset 1 |
| `AX5043_MAXRFOFFSET0` | SFRX | 0x410B | Maximum Receiver RF Offset 0 |
| `AX5043_FSKDMAX1` | SFRX | 0x410C | Four FSK Rx Maximum Deviation 1 |
| `AX5043_FSKDMAX0` | SFRX | 0x410D | Four FSK Rx Maximum Deviation 0 |
| `AX5043_FSKDMIN1` | SFRX | 0x410E | Four FSK Rx Minimum Deviation 1 |
| `AX5043_FSKDMIN0` | SFRX | 0x410F | Four FSK Rx Minimum Deviation 0 |
| `AX5043_AFSKSPACE1` | SFRX | 0x4110 | AFSK Space (0) Frequency 1 |
| `AX5043_AFSKSPACE0` | SFRX | 0x4111 | AFSK Space (0) Frequency 0 |
| `AX5043_AFSKMARK1` | SFRX | 0x4112 | AFSK Mark (1) Frequency 1 |
| `AX5043_AFSKMARK0` | SFRX | 0x4113 | AFSK Mark (1) Frequency 0 |
| `AX5043_AFSKCTRL` | SFRX | 0x4114 | AFSK Control |
| `AX5043_AMPLFILTER` | SFRX | 0x4115 | Amplitude Filter |
| `AX5043_FREQUENCYLEAK` | SFRX | 0x4116 | Baseband Frequency Recovery Loop Leakiness |
| `AX5043_RXPARAMSETS_V1` | SFRX | 0x4116 | Receiver Parameter Set Indirection |
| `AX5043_RXPARAMCURSET_V1` | SFRX | 0x4117 | Receiver Parameter Current Set |
| `AX5043_RXPARAMSETS` | SFRX | 0x4117 | Receiver Parameter Set Indirection |
| `AX5043_RXPARAMCURSET` | SFRX | 0x4118 | Receiver Parameter Current Set |
| `AX5043_AGCGAIN0` | SFRX | 0x4120 | AGC Speed |
| `AX5043_AGCGAIN0_V1` | SFRX | 0x4120 | AGC Speed |
| `AX5043_AGCTARGET0` | SFRX | 0x4121 | AGC Target |
| `AX5043_AGCTARGET0_V1` | SFRX | 0x4121 | AGC Target |
| `AX5043_AGCAHYST0` | SFRX | 0x4122 | AGC Analog Hysteresis |
| `AX5043_TIMEGAIN0_V1` | SFRX | 0x4122 | Time Estimator Bandwidth |
| `AX5043_AGCMINMAX0` | SFRX | 0x4123 | AGC Analog Update Behaviour |
| `AX5043_DRGAIN0_V1` | SFRX | 0x4123 | Data Rate Estimator Bandwidth |
| `AX5043_PHASEGAIN0_V1` | SFRX | 0x4124 | Phase Estimator Bandwidth |
| `AX5043_TIMEGAIN0` | SFRX | 0x4124 | Time Estimator Bandwidth |
| `AX5043_DRGAIN0` | SFRX | 0x4125 | Data Rate Estimator Bandwidth |
| `AX5043_FREQUENCYGAINA0_V1` | SFRX | 0x4125 | Frequency Estimator Bandwidth A |
| `AX5043_FREQUENCYGAINB0_V1` | SFRX | 0x4126 | Frequency Estimator Bandwidth B |
| `AX5043_PHASEGAIN0` | SFRX | 0x4126 | Phase Estimator Bandwidth |
| `AX5043_FREQUENCYGAINA0` | SFRX | 0x4127 | Frequency Estimator Bandwidth A |
| `AX5043_FREQUENCYGAINC0_V1` | SFRX | 0x4127 | Frequency Estimator Bandwidth C |
| `AX5043_FREQUENCYGAINB0` | SFRX | 0x4128 | Frequency Estimator Bandwidth B |
| `AX5043_FREQUENCYGAIND0_V1` | SFRX | 0x4128 | Frequency Estimator Bandwidth D |
| `AX5043_AMPLITUDEGAIN0_V1` | SFRX | 0x4129 | Amplitude Estimator Bandwidth |
| `AX5043_FREQUENCYGAINC0` | SFRX | 0x4129 | Frequency Estimator Bandwidth C |
| `AX5043_FREQDEV10_V1` | SFRX | 0x412A | Receiver Frequency Deviation 1 |
| `AX5043_FREQUENCYGAIND0` | SFRX | 0x412A | Frequency Estimator Bandwidth D |
| `AX5043_AMPLITUDEGAIN0` | SFRX | 0x412B | Amplitude Estimator Bandwidth |
| `AX5043_FREQDEV00_V1` | SFRX | 0x412B | Receiver Frequency Deviation 0 |
| `AX5043_FOURFSK0_V1` | SFRX | 0x412C | Four FSK Control |
| `AX5043_FREQDEV10` | SFRX | 0x412C | Receiver Frequency Deviation 1 |
| `AX5043_BBOFFSRES0_V1` | SFRX | 0x412D | Baseband Offset Compensation Resistors |
| `AX5043_FREQDEV00` | SFRX | 0x412D | Receiver Frequency Deviation 0 |
| `AX5043_AGCGAIN1_V1` | SFRX | 0x412E | AGC Speed |
| `AX5043_FOURFSK0` | SFRX | 0x412E | Four FSK Control |
| `AX5043_AGCTARGET1_V1` | SFRX | 0x412F | AGC Target |
| `AX5043_BBOFFSRES0` | SFRX | 0x412F | Baseband Offset Compensation Resistors |
| `AX5043_AGCGAIN1` | SFRX | 0x4130 | AGC Speed |
| `AX5043_TIMEGAIN1_V1` | SFRX | 0x4130 | Time Estimator Bandwidth |
| `AX5043_AGCTARGET1` | SFRX | 0x4131 | AGC Target |
| `AX5043_DRGAIN1_V1` | SFRX | 0x4131 | Data Rate Estimator Bandwidth |
| `AX5043_AGCAHYST1` | SFRX | 0x4132 | AGC Analog Hysteresis |
| `AX5043_PHASEGAIN1_V1` | SFRX | 0x4132 | Phase Estimator Bandwidth |
| `AX5043_AGCMINMAX1` | SFRX | 0x4133 | AGC Analog Update Behaviour |
| `AX5043_FREQUENCYGAINA1_V1` | SFRX | 0x4133 | Frequency Estimator Bandwidth A |
| `AX5043_FREQUENCYGAINB1_V1` | SFRX | 0x4134 | Frequency Estimator Bandwidth B |
| `AX5043_TIMEGAIN1` | SFRX | 0x4134 | Time Estimator Bandwidth |
| `AX5043_DRGAIN1` | SFRX | 0x4135 | Data Rate Estimator Bandwidth |
| `AX5043_FREQUENCYGAINC1_V1` | SFRX | 0x4135 | Frequency Estimator Bandwidth C |
| `AX5043_FREQUENCYGAIND1_V1` | SFRX | 0x4136 | Frequency Estimator Bandwidth D |
| `AX5043_PHASEGAIN1` | SFRX | 0x4136 | Phase Estimator Bandwidth |
| `AX5043_AMPLITUDEGAIN1_V1` | SFRX | 0x4137 | Amplitude Estimator Bandwidth |
| `AX5043_FREQUENCYGAINA1` | SFRX | 0x4137 | Frequency Estimator Bandwidth A |
| `AX5043_FREQDEV11_V1` | SFRX | 0x4138 | Receiver Frequency Deviation 1 |
| `AX5043_FREQUENCYGAINB1` | SFRX | 0x4138 | Frequency Estimator Bandwidth B |
| `AX5043_FREQDEV01_V1` | SFRX | 0x4139 | Receiver Frequency Deviation 0 |
| `AX5043_FREQUENCYGAINC1` | SFRX | 0x4139 | Frequency Estimator Bandwidth C |
| `AX5043_FOURFSK1_V1` | SFRX | 0x413A | Four FSK Control |
| `AX5043_FREQUENCYGAIND1` | SFRX | 0x413A | Frequency Estimator Bandwidth D |
| `AX5043_AMPLITUDEGAIN1` | SFRX | 0x413B | Amplitude Estimator Bandwidth |
| `AX5043_BBOFFSRES1_V1` | SFRX | 0x413B | Baseband Offset Compensation Resistors |
| `AX5043_AGCGAIN2_V1` | SFRX | 0x413C | AGC Speed |
| `AX5043_FREQDEV11` | SFRX | 0x413C | Receiver Frequency Deviation 1 |
| `AX5043_AGCTARGET2_V1` | SFRX | 0x413D | AGC Target |
| `AX5043_FREQDEV01` | SFRX | 0x413D | Receiver Frequency Deviation 0 |
| `AX5043_FOURFSK1` | SFRX | 0x413E | Four FSK Control |
| `AX5043_TIMEGAIN2_V1` | SFRX | 0x413E | Time Estimator Bandwidth |
| `AX5043_BBOFFSRES1` | SFRX | 0x413F | Baseband Offset Compensation Resistors |
| `AX5043_DRGAIN2_V1` | SFRX | 0x413F | Data Rate Estimator Bandwidth |
| `AX5043_AGCGAIN2` | SFRX | 0x4140 | AGC Speed |
| `AX5043_PHASEGAIN2_V1` | SFRX | 0x4140 | Phase Estimator Bandwidth |
| `AX5043_AGCTARGET2` | SFRX | 0x4141 | AGC Target |
| `AX5043_FREQUENCYGAINA2_V1` | SFRX | 0x4141 | Frequency Estimator Bandwidth A |
| `AX5043_AGCAHYST2` | SFRX | 0x4142 | AGC Analog Hysteresis |
| `AX5043_FREQUENCYGAINB2_V1` | SFRX | 0x4142 | Frequency Estimator Bandwidth B |
| `AX5043_AGCMINMAX2` | SFRX | 0x4143 | AGC Analog Update Behaviour |
| `AX5043_FREQUENCYGAINC2_V1` | SFRX | 0x4143 | Frequency Estimator Bandwidth C |
| `AX5043_FREQUENCYGAIND2_V1` | SFRX | 0x4144 | Frequency Estimator Bandwidth D |
| `AX5043_TIMEGAIN2` | SFRX | 0x4144 | Time Estimator Bandwidth |
| `AX5043_AMPLITUDEGAIN2_V1` | SFRX | 0x4145 | Amplitude Estimator Bandwidth |
| `AX5043_DRGAIN2` | SFRX | 0x4145 | Data Rate Estimator Bandwidth |
| `AX5043_FREQDEV12_V1` | SFRX | 0x4146 | Receiver Frequency Deviation 1 |
| `AX5043_PHASEGAIN2` | SFRX | 0x4146 | Phase Estimator Bandwidth |
| `AX5043_FREQDEV02_V1` | SFRX | 0x4147 | Receiver Frequency Deviation 0 |
| `AX5043_FREQUENCYGAINA2` | SFRX | 0x4147 | Frequency Estimator Bandwidth A |
| `AX5043_FOURFSK2_V1` | SFRX | 0x4148 | Four FSK Control |
| `AX5043_FREQUENCYGAINB2` | SFRX | 0x4148 | Frequency Estimator Bandwidth B |
| `AX5043_BBOFFSRES2_V1` | SFRX | 0x4149 | Baseband Offset Compensation Resistors |
| `AX5043_FREQUENCYGAINC2` | SFRX | 0x4149 | Frequency Estimator Bandwidth C |
| `AX5043_AGCGAIN3_V1` | SFRX | 0x414A | AGC Speed |
| `AX5043_FREQUENCYGAIND2` | SFRX | 0x414A | Frequency Estimator Bandwidth D |
| `AX5043_AGCTARGET3_V1` | SFRX | 0x414B | AGC Target |
| `AX5043_AMPLITUDEGAIN2` | SFRX | 0x414B | Amplitude Estimator Bandwidth |
| `AX5043_FREQDEV12` | SFRX | 0x414C | Receiver Frequency Deviation 1 |
| `AX5043_TIMEGAIN3_V1` | SFRX | 0x414C | Time Estimator Bandwidth |
| `AX5043_DRGAIN3_V1` | SFRX | 0x414D | Data Rate Estimator Bandwidth |
| `AX5043_FREQDEV02` | SFRX | 0x414D | Receiver Frequency Deviation 0 |
| `AX5043_FOURFSK2` | SFRX | 0x414E | Four FSK Control |
| `AX5043_PHASEGAIN3_V1` | SFRX | 0x414E | Phase Estimator Bandwidth |
| `AX5043_BBOFFSRES2` | SFRX | 0x414F | Baseband Offset Compensation Resistors |
| `AX5043_FREQUENCYGAINA3_V1` | SFRX | 0x414F | Frequency Estimator Bandwidth A |
| `AX5043_AGCGAIN3` | SFRX | 0x4150 | AGC Speed |
| `AX5043_FREQUENCYGAINB3_V1` | SFRX | 0x4150 | Frequency Estimator Bandwidth B |
| `AX5043_AGCTARGET3` | SFRX | 0x4151 | AGC Target |
| `AX5043_FREQUENCYGAINC3_V1` | SFRX | 0x4151 | Frequency Estimator Bandwidth C |
| `AX5043_AGCAHYST3` | SFRX | 0x4152 | AGC Analog Hysteresis |
| `AX5043_FREQUENCYGAIND3_V1` | SFRX | 0x4152 | Frequency Estimator Bandwidth D |
| `AX5043_AGCMINMAX3` | SFRX | 0x4153 | AGC Analog Update Behaviour |
| `AX5043_AMPLITUDEGAIN3_V1` | SFRX | 0x4153 | Amplitude Estimator Bandwidth |
| `AX5043_FREQDEV13_V1` | SFRX | 0x4154 | Receiver Frequency Deviation 1 |
| `AX5043_TIMEGAIN3` | SFRX | 0x4154 | Time Estimator Bandwidth |
| `AX5043_DRGAIN3` | SFRX | 0x4155 | Data Rate Estimator Bandwidth |
| `AX5043_FREQDEV03_V1` | SFRX | 0x4155 | Receiver Frequency Deviation 0 |
| `AX5043_FOURFSK3_V1` | SFRX | 0x4156 | Four FSK Control |
| `AX5043_PHASEGAIN3` | SFRX | 0x4156 | Phase Estimator Bandwidth |
| `AX5043_BBOFFSRES3_V1` | SFRX | 0x4157 | Baseband Offset Compensation Resistors |
| `AX5043_FREQUENCYGAINA3` | SFRX | 0x4157 | Frequency Estimator Bandwidth A |
| `AX5043_FREQUENCYGAINB3` | SFRX | 0x4158 | Frequency Estimator Bandwidth B |
| `AX5043_FREQUENCYGAINC3` | SFRX | 0x4159 | Frequency Estimator Bandwidth C |
| `AX5043_FREQUENCYGAIND3` | SFRX | 0x415A | Frequency Estimator Bandwidth D |
| `AX5043_AMPLITUDEGAIN3` | SFRX | 0x415B | Amplitude Estimator Bandwidth |
| `AX5043_FREQDEV13` | SFRX | 0x415C | Receiver Frequency Deviation 1 |
| `AX5043_FREQDEV03` | SFRX | 0x415D | Receiver Frequency Deviation 0 |
| `AX5043_FOURFSK3` | SFRX | 0x415E | Four FSK Control |
| `AX5043_BBOFFSRES3` | SFRX | 0x415F | Baseband Offset Compensation Resistors |
| `AX5043_MODCFGF` | SFRX | 0x4160 | Modulator Configuration F |
| `AX5043_FSKDEV2` | SFRX | 0x4161 | FSK Deviation 2 |
| `AX5043_FSKDEV1` | SFRX | 0x4162 | FSK Deviation 1 |
| `AX5043_FSKDEV0` | SFRX | 0x4163 | FSK Deviation 0 |
| `AX5043_MODCFGA` | SFRX | 0x4164 | Modulator Configuration A |
| `AX5043_TXRATE2` | SFRX | 0x4165 | Transmitter Bitrate 2 |
| `AX5043_TXRATE1` | SFRX | 0x4166 | Transmitter Bitrate 1 |
| `AX5043_TXRATE0` | SFRX | 0x4167 | Transmitter Bitrate 0 |
| `AX5043_TXPWRCOEFFA1` | SFRX | 0x4168 | Transmitter Predistortion Coefficient A 1 |
| `AX5043_TXPWRCOEFFA0` | SFRX | 0x4169 | Transmitter Predistortion Coefficient A 0 |
| `AX5043_TXPWRCOEFFB1` | SFRX | 0x416A | Transmitter Predistortion Coefficient B 1 |
| `AX5043_TXPWRCOEFFB0` | SFRX | 0x416B | Transmitter Predistortion Coefficient B 0 |
| `AX5043_TXPWRCOEFFC1` | SFRX | 0x416C | Transmitter Predistortion Coefficient C 1 |
| `AX5043_TXPWRCOEFFC0` | SFRX | 0x416D | Transmitter Predistortion Coefficient C 0 |
| `AX5043_TXPWRCOEFFD1` | SFRX | 0x416E | Transmitter Predistortion Coefficient D 1 |
| `AX5043_TXPWRCOEFFD0` | SFRX | 0x416F | Transmitter Predistortion Coefficient D 0 |
| `AX5043_TXPWRCOEFFE1` | SFRX | 0x4170 | Transmitter Predistortion Coefficient E 1 |
| `AX5043_TXPWRCOEFFE0` | SFRX | 0x4171 | Transmitter Predistortion Coefficient E 0 |
| `AX5043_PLLVCOI` | SFRX | 0x4180 | PLL VCO Current |
| `AX5043_PLLVCOIR` | SFRX | 0x4181 | PLL VCO Current Readback |
| `AX5043_PLLLOCKDET` | SFRX | 0x4182 | PLL Lock Detect Delay |
| `AX5043_PLLRNGCLK` | SFRX | 0x4183 | PLL Autoranging Clock |
| `AX5043_XTALCAP` | SFRX | 0x4184 | Crystal Oscillator Load Capacitance |
| `AX5043_BBTUNE` | SFRX | 0x4188 | Baseband Tuning |
| `AX5043_BBOFFSCAP` | SFRX | 0x4189 | Baseband Offset Compensation Capacitors |
| `AX5043_PKTADDRCFG` | SFRX | 0x4200 | Packet Address Config |
| `AX5043_PKTADDRCFG_V1` | SFRX | 0x4201 | Packet Address Config |
| `AX5043_PKTLENCFG` | SFRX | 0x4201 | Packet Length Configuration |
| `AX5043_PKTADDR1_V1` | SFRX | 0x4202 | Packet Address 1 |
| `AX5043_PKTLENOFFSET` | SFRX | 0x4202 | Packet Length Offset |
| `AX5043_PKTADDR0_V1` | SFRX | 0x4203 | Packet Address 0 |
| `AX5043_PKTMAXLEN` | SFRX | 0x4203 | Packet Maximum Length |
| `AX5043_PKTADDR3` | SFRX | 0x4204 | Packet Address 3 |
| `AX5043_PKTADDRMASK1_V1` | SFRX | 0x4204 | Packet Address Mask 1 |
| `AX5043_PKTADDR2` | SFRX | 0x4205 | Packet Address 2 |
| `AX5043_PKTADDRMASK0_V1` | SFRX | 0x4205 | Packet Address Mask 0 |
| `AX5043_PKTADDR1` | SFRX | 0x4206 | Packet Address 1 |
| `AX5043_PKTLENCFG_V1` | SFRX | 0x4206 | Packet Length Configuration |
| `AX5043_PKTADDR0` | SFRX | 0x4207 | Packet Address 0 |
| `AX5043_PKTLENOFFSET_V1` | SFRX | 0x4207 | Packet Length Offset |
| `AX5043_PKTADDRMASK3` | SFRX | 0x4208 | Packet Address Mask 3 |
| `AX5043_PKTMAXLEN_V1` | SFRX | 0x4208 | Packet Maximum Length |
| `AX5043_PKTADDRMASK2` | SFRX | 0x4209 | Packet Address Mask 2 |
| `AX5043_PKTADDRMASK1` | SFRX | 0x420A | Packet Address Mask 1 |
| `AX5043_PKTADDRMASK0` | SFRX | 0x420B | Packet Address Mask 0 |
| `AX5043_MATCH0PAT3` | SFRX | 0x4210 | Pattern Match Unit 0, Pattern 3 |
| `AX5043_MATCH0PAT2` | SFRX | 0x4211 | Pattern Match Unit 0, Pattern 2 |
| `AX5043_MATCH0PAT1` | SFRX | 0x4212 | Pattern Match Unit 0, Pattern 1 |
| `AX5043_MATCH0PAT0` | SFRX | 0x4213 | Pattern Match Unit 0, Pattern 0 |
| `AX5043_MATCH0LEN` | SFRX | 0x4214 | Pattern Match Unit 0, Pattern Length |
| `AX5043_MATCH0MIN` | SFRX | 0x4215 | Pattern Match Unit 0, Minimum Match |
| `AX5043_MATCH0MAX` | SFRX | 0x4216 | Pattern Match Unit 0, Maximum Match |
| `AX5043_MATCH1PAT1` | SFRX | 0x4218 | Pattern Match Unit 1, Pattern 1 |
| `AX5043_MATCH1PAT0` | SFRX | 0x4219 | Pattern Match Unit 1, Pattern 0 |
| `AX5043_MATCH1LEN` | SFRX | 0x421C | Pattern Match Unit 1, Pattern Length |
| `AX5043_MATCH1MIN` | SFRX | 0x421D | Pattern Match Unit 1, Minimum Match |
| `AX5043_MATCH1MAX` | SFRX | 0x421E | Pattern Match Unit 1, Maximum Match |
| `AX5043_TMGTXBOOST` | SFRX | 0x4220 | Transmit PLL Boost Time |
| `AX5043_TMGTXSETTLE` | SFRX | 0x4221 | Transmit PLL (post Boost) Settling Time |
| `AX5043_TMGRXBOOST` | SFRX | 0x4223 | Receive PLL Boost Time |
| `AX5043_TMGRXSETTLE` | SFRX | 0x4224 | Receive PLL (post Boost) Settling Time |
| `AX5043_TMGRXOFFSACQ` | SFRX | 0x4225 | Receive Baseband DC Offset Acquisition Time |
| `AX5043_TMGRXCOARSEAGC` | SFRX | 0x4226 | Receive Coarse AGC Time |
| `AX5043_TMGRXAGC` | SFRX | 0x4227 | Receiver AGC Settling Time |
| `AX5043_TMGRXRSSI` | SFRX | 0x4228 | Receiver RSSI Settling Time |
| `AX5043_TMGRXPREAMBLE1` | SFRX | 0x4229 | Receiver Preamble 1 Timeout |
| `AX5043_TMGRXPREAMBLE2` | SFRX | 0x422A | Receiver Preamble 2 Timeout |
| `AX5043_TMGRXPREAMBLE3` | SFRX | 0x422B | Receiver Preamble 3 Timeout |
| `AX5043_RSSIREFERENCE` | SFRX | 0x422C | RSSI Offset |
| `AX5043_RSSIABSTHR` | SFRX | 0x422D | RSSI Absolute Threshold |
| `AX5043_BGNDRSSIGAIN` | SFRX | 0x422E | Background RSSI Averaging Time Constant |
| `AX5043_BGNDRSSITHR` | SFRX | 0x422F | Background RSSI Relative Threshold |
| `AX5043_PKTCHUNKSIZE` | SFRX | 0x4230 | Packet Chunk Size |
| `AX5043_PKTMISCFLAGS` | SFRX | 0x4231 | Packet Controller Miscellaneous Flags |
| `AX5043_PKTSTOREFLAGS` | SFRX | 0x4232 | Packet Controller Store Flags |
| `AX5043_PKTACCEPTFLAGS` | SFRX | 0x4233 | Packet Controller Accept Flags |
| `AX5043_GPADCCTRL` | SFRX | 0x4300 | General Purpose ADC Control |
| `AX5043_GPADCPERIOD` | SFRX | 0x4301 | GPADC Sampling Period |
| `AX5043_GPADC13VALUE1` | SFRX | 0x4308 | GPADC13 Value 1 |
| `AX5043_GPADC13VALUE0` | SFRX | 0x4309 | GPADC13 Value 0 |
| `AX5043_LPOSCCONFIG` | SFRX | 0x4310 | Low Power Oscillator Calibration Configuration |
| `AX5043_LPOSCSTATUS` | SFRX | 0x4311 | Low Power Oscillator Calibration Status |
| `AX5043_LPOSCKFILT1` | SFRX | 0x4312 | Low Power Oscillator Calibration Filter Constant High Byte |
| `AX5043_LPOSCKFILT0` | SFRX | 0x4313 | Low Power Oscillator Calibration Filter Constant Low Byte |
| `AX5043_LPOSCREF1` | SFRX | 0x4314 | Low Power Oscillator Reference Frequency High Byte |
| `AX5043_LPOSCREF0` | SFRX | 0x4315 | Low Power Oscillator Reference Frequency Low Byte |
| `AX5043_LPOSCFREQ1` | SFRX | 0x4316 | Low Power Oscillator Frequency Tuning High Byte |
| `AX5043_LPOSCFREQ0` | SFRX | 0x4317 | Low Power Oscillator Frequency Tuning Low Byte |
| `AX5043_LPOSCPER1` | SFRX | 0x4318 | Low Power Oscillator Period High Byte |
| `AX5043_LPOSCPER0` | SFRX | 0x4319 | Low Power Oscillator Period Low Byte |
| `AX5043_DACVALUE1` | SFRX | 0x4330 | DAC Value 1 |
| `AX5043_DACVALUE0` | SFRX | 0x4331 | DAC Value 0 |
| `AX5043_DACCONFIG` | SFRX | 0x4332 | DAC Configuration |
| `AX5043_0xF00` | SFRX | 0x4F00 |  |
| `AX5043_POWCTRL1` | SFRX | 0x4F08 | Power Control 1 |
| `AX5043_0xF0C` | SFRX | 0x4F0C |  |
| `AX5043_REF` | SFRX | 0x4F0D | Reference |
| `AX5043_XTALOSC` | SFRX | 0x4F10 | Crystal Oscillator Control |
| `AX5043_XTALAMPL` | SFRX | 0x4F11 | Crystal Oscillator Amplitude Control |
| `AX5043_0xF18` | SFRX | 0x4F18 |  |
| `AX5043_0xF1C` | SFRX | 0x4F1C |  |
| `AX5043_0xF21` | SFRX | 0x4F21 |  |
| `AX5043_0xF22` | SFRX | 0x4F22 |  |
| `AX5043_0xF23` | SFRX | 0x4F23 |  |
| `AX5043_0xF26` | SFRX | 0x4F26 |  |
| `AX5043_0xF30` | SFRX | 0x4F30 |  |
| `AX5043_0xF31` | SFRX | 0x4F31 |  |
| `AX5043_0xF32` | SFRX | 0x4F32 |  |
| `AX5043_0xF33` | SFRX | 0x4F33 |  |
| `AX5043_0xF34` | SFRX | 0x4F34 |  |
| `AX5043_0xF35` | SFRX | 0x4F35 |  |
| `AX5043_0xF44` | SFRX | 0x4F44 |  |
| `AX5043_MODCFGP` | SFRX | 0x4F5F | Modulator Configuration P |

Non-blocking aliases (0x5000-0x5FFF): a write returns immediately; reading them is not meaningful.
Use only where the code already does (e.g. `radio_write8nb`) and never for FIFO data or PWRMODE sequencing.

## AX5043 non-blocking aliases

| Name | Kind | Address | Description |
|---|---|---|---|
| `AX5043_SILICONREVISIONNB` | SFRX | 0x5000 | Silicon Revision, Non-Blocking |
| `AX5043_SCRATCHNB` | SFRX | 0x5001 | Scratch, Non-Blocking |
| `AX5043_PWRMODENB` | SFRX | 0x5002 | Power Mode, Non-Blocking |
| `AX5043_POWSTATNB` | SFRX | 0x5003 | Power Management Status, Non-Blocking |
| `AX5043_POWSTICKYSTATNB` | SFRX | 0x5004 | Power Management Sticky Status, Non-Blocking |
| `AX5043_POWIRQMASKNB` | SFRX | 0x5005 | Power Management Interrupt Mask, Non-Blocking |
| `AX5043_IRQMASK1NB` | SFRX | 0x5006 | IRQ Mask 1, Non-Blocking |
| `AX5043_IRQMASK0NB` | SFRX | 0x5007 | IRQ Mask 0, Non-Blocking |
| `AX5043_RADIOEVENTMASK1NB` | SFRX | 0x5008 | Radio Event Mask 1, Non-Blocking |
| `AX5043_RADIOEVENTMASK0NB` | SFRX | 0x5009 | Radio Event Mask 0, Non-Blocking |
| `AX5043_IRQINVERSION1NB` | SFRX | 0x500A | IRQ Inversion 1, Non-Blocking |
| `AX5043_IRQINVERSION0NB` | SFRX | 0x500B | IRQ Inversion 0, Non-Blocking |
| `AX5043_IRQREQUEST1NB` | SFRX | 0x500C | IRQ Request 1, Non-Blocking |
| `AX5043_IRQREQUEST0NB` | SFRX | 0x500D | IRQ Request 0, Non-Blocking |
| `AX5043_RADIOEVENTREQ1NB` | SFRX | 0x500E | Radio Event Request 1, Non-Blocking |
| `AX5043_RADIOEVENTREQ0NB` | SFRX | 0x500F | Radio Event Request 0, Non-Blocking |
| `AX5043_MODULATIONNB` | SFRX | 0x5010 | Modulation, Non-Blocking |
| `AX5043_ENCODINGNB` | SFRX | 0x5011 | Encoding, Non-Blocking |
| `AX5043_FRAMINGNB` | SFRX | 0x5012 | Framing Mode, Non-Blocking |
| `AX5043_CRCINIT3NB` | SFRX | 0x5014 | CRC Initial Value 3, Non-Blocking |
| `AX5043_CRCINIT2NB` | SFRX | 0x5015 | CRC Initial Value 2, Non-Blocking |
| `AX5043_CRCINIT1NB` | SFRX | 0x5016 | CRC Initial Value 1, Non-Blocking |
| `AX5043_CRCINIT0NB` | SFRX | 0x5017 | CRC Initial Value 0, Non-Blocking |
| `AX5043_FECNB` | SFRX | 0x5018 | Forward Error Correction, Non-Blocking |
| `AX5043_FECSYNCNB` | SFRX | 0x5019 | Forward Error Correction Sync Threshold, Non-Blocking |
| `AX5043_FECSTATUSNB` | SFRX | 0x501A | Forward Error Correction Status, Non-Blocking |
| `AX5043_RADIOSTATENB` | SFRX | 0x501C | Radio Controller State, Non-Blocking |
| `AX5043_XTALSTATUSNB` | SFRX | 0x501D | Crystal Oscillator Status, Non-Blocking |
| `AX5043_PINSTATENB` | SFRX | 0x5020 | Pin State, Non-Blocking |
| `AX5043_PINFUNCSYSCLKNB` | SFRX | 0x5021 | Pin Function SYSCLK, Non-Blocking |
| `AX5043_PINFUNCDCLKNB` | SFRX | 0x5022 | Pin Function DCLK, Non-Blocking |
| `AX5043_PINFUNCDATANB` | SFRX | 0x5023 | Pin Function DATA, Non-Blocking |
| `AX5043_PINFUNCIRQNB` | SFRX | 0x5024 | Pin Function IRQ, Non-Blocking |
| `AX5043_PINFUNCANTSELNB` | SFRX | 0x5025 | Pin Function ANTSEL, Non-Blocking |
| `AX5043_PINFUNCPWRAMPNB` | SFRX | 0x5026 | Pin Function PWRAMP, Non-Blocking |
| `AX5043_PWRAMPNB` | SFRX | 0x5027 | PWRAMP Control, Non-Blocking |
| `AX5043_FIFOSTATNB` | SFRX | 0x5028 | FIFO Control, Non-Blocking |
| `AX5043_FIFODATANB` | SFRX | 0x5029 | FIFO Data, Non-Blocking |
| `AX5043_FIFOCOUNT1NB` | SFRX | 0x502A | Number of Words currently in FIFO 1, Non-Blocking |
| `AX5043_FIFOCOUNT0NB` | SFRX | 0x502B | Number of Words currently in FIFO 0, Non-Blocking |
| `AX5043_FIFOFREE1NB` | SFRX | 0x502C | Number of Words that can be written to FIFO 1, Non-Blocking |
| `AX5043_FIFOFREE0NB` | SFRX | 0x502D | Number of Words that can be written to FIFO 0, Non-Blocking |
| `AX5043_FIFOTHRESH1NB` | SFRX | 0x502E | FIFO Threshold 1, Non-Blocking |
| `AX5043_FIFOTHRESH0NB` | SFRX | 0x502F | FIFO Threshold 0, Non-Blocking |
| `AX5043_PLLLOOPNB` | SFRX | 0x5030 | PLL Loop Filter Settings, Non-Blocking |
| `AX5043_PLLCPINB` | SFRX | 0x5031 | PLL Charge Pump Current, Non-Blocking |
| `AX5043_PLLVCODIVNB` | SFRX | 0x5032 | PLL Divider Settings, Non-Blocking |
| `AX5043_PLLRANGINGANB` | SFRX | 0x5033 | PLL Autoranging A, Non-Blocking |
| `AX5043_FREQA3NB` | SFRX | 0x5034 | Frequency A 3, Non-Blocking |
| `AX5043_FREQA2NB` | SFRX | 0x5035 | Frequency A 2, Non-Blocking |
| `AX5043_FREQA1NB` | SFRX | 0x5036 | Frequency A 1, Non-Blocking |
| `AX5043_FREQA0NB` | SFRX | 0x5037 | Frequency A 0, Non-Blocking |
| `AX5043_PLLLOOPBOOSTNB` | SFRX | 0x5038 | PLL Loop Filter Settings (Boosted), Non-Blocking |
| `AX5043_PLLCPIBOOSTNB` | SFRX | 0x5039 | PLL Charge Pump Current (Boosted), Non-Blocking |
| `AX5043_PLLRANGINGBNB` | SFRX | 0x503B | PLL Autoranging B, Non-Blocking |
| `AX5043_FREQB3NB` | SFRX | 0x503C | Frequency B 3, Non-Blocking |
| `AX5043_FREQB2NB` | SFRX | 0x503D | Frequency B 2, Non-Blocking |
| `AX5043_FREQB1NB` | SFRX | 0x503E | Frequency B 1, Non-Blocking |
| `AX5043_FREQB0NB` | SFRX | 0x503F | Frequency B 0, Non-Blocking |
| `AX5043_RSSINB` | SFRX | 0x5040 | Received Signal Strength Indicator, Non-Blocking |
| `AX5043_BGNDRSSINB` | SFRX | 0x5041 | Background RSSI, Non-Blocking |
| `AX5043_DIVERSITYNB` | SFRX | 0x5042 | Antenna Diversity Configuration, Non-Blocking |
| `AX5043_AGCCOUNTERNB` | SFRX | 0x5043 | AGC Counter, Non-Blocking |
| `AX5043_TRKDATARATE2NB` | SFRX | 0x5045 | Datarate Tracking 2, Non-Blocking |
| `AX5043_TRKDATARATE1NB` | SFRX | 0x5046 | Datarate Tracking 1, Non-Blocking |
| `AX5043_TRKDATARATE0NB` | SFRX | 0x5047 | Datarate Tracking 0, Non-Blocking |
| `AX5043_TRKAMPLITUDE1NB` | SFRX | 0x5048 | Amplitude Tracking 1, Non-Blocking |
| `AX5043_TRKAMPLITUDE0NB` | SFRX | 0x5049 | Amplitude Tracking 0, Non-Blocking |
| `AX5043_TRKPHASE1NB` | SFRX | 0x504A | Phase Tracking 1, Non-Blocking |
| `AX5043_TRKPHASE0NB` | SFRX | 0x504B | Phase Tracking 0, Non-Blocking |
| `AX5043_TRKRFFREQ2NB` | SFRX | 0x504D | RF Frequency Tracking 2, Non-Blocking |
| `AX5043_TRKRFFREQ1NB` | SFRX | 0x504E | RF Frequency Tracking 1, Non-Blocking |
| `AX5043_TRKRFFREQ0NB` | SFRX | 0x504F | RF Frequency Tracking 0, Non-Blocking |
| `AX5043_TRKFREQ1NB` | SFRX | 0x5050 | Frequency Tracking 1, Non-Blocking |
| `AX5043_TRKFREQ0NB` | SFRX | 0x5051 | Frequency Tracking 0, Non-Blocking |
| `AX5043_TRKFSKDEMOD1NB` | SFRX | 0x5052 | FSK Demodulator Tracking 1, Non-Blocking |
| `AX5043_TRKFSKDEMOD0NB` | SFRX | 0x5053 | FSK Demodulator Tracking 0, Non-Blocking |
| `AX5043_TRKAFSKDEMOD1NB` | SFRX | 0x5054 | AFSK Demodulator Tracking 1, Non-Blocking |
| `AX5043_TRKAFSKDEMOD0NB` | SFRX | 0x5055 | AFSK Demodulator Tracking 0, Non-Blocking |
| `AX5043_TIMER2NB` | SFRX | 0x5059 | 1MHz Timer 2, Non-Blocking |
| `AX5043_TIMER1NB` | SFRX | 0x505A | 1MHz Timer 1, Non-Blocking |
| `AX5043_TIMER0NB` | SFRX | 0x505B | 1MHz Timer 0, Non-Blocking |
| `AX5043_WAKEUPTIMER1NB` | SFRX | 0x5068 | Wakeup Timer 1, Non-Blocking |
| `AX5043_WAKEUPTIMER0NB` | SFRX | 0x5069 | Wakeup Timer 0, Non-Blocking |
| `AX5043_WAKEUP1NB` | SFRX | 0x506A | Wakeup Time 1, Non-Blocking |
| `AX5043_WAKEUP0NB` | SFRX | 0x506B | Wakeup Time 0, Non-Blocking |
| `AX5043_WAKEUPFREQ1NB` | SFRX | 0x506C | Wakeup Frequency 1, Non-Blocking |
| `AX5043_WAKEUPFREQ0NB` | SFRX | 0x506D | Wakeup Frequency 0, Non-Blocking |
| `AX5043_WAKEUPXOEARLYNB` | SFRX | 0x506E | Wakeup Crystal Oscillator Early, Non-Blocking |
| `AX5043_IFFREQ1NB` | SFRX | 0x5100 | 2nd LO / IF Frequency 1, Non-Blocking |
| `AX5043_IFFREQ0NB` | SFRX | 0x5101 | 2nd LO / IF Frequency 0, Non-Blocking |
| `AX5043_DECIMATIONNB` | SFRX | 0x5102 | Decimation Factor , Non-Blocking |
| `AX5043_RXDATARATE2NB` | SFRX | 0x5103 | Receiver Datarate 2, Non-Blocking |
| `AX5043_RXDATARATE1NB` | SFRX | 0x5104 | Receiver Datarate 1, Non-Blocking |
| `AX5043_RXDATARATE0NB` | SFRX | 0x5105 | Receiver Datarate 0, Non-Blocking |
| `AX5043_MAXDROFFSET2NB` | SFRX | 0x5106 | Maximum Receiver Datarate Offset 2, Non-Blocking |
| `AX5043_MAXDROFFSET1NB` | SFRX | 0x5107 | Maximum Receiver Datarate Offset 1, Non-Blocking |
| `AX5043_MAXDROFFSET0NB` | SFRX | 0x5108 | Maximum Receiver Datarate Offset 0, Non-Blocking |
| `AX5043_MAXRFOFFSET2NB` | SFRX | 0x5109 | Maximum Receiver RF Offset 2, Non-Blocking |
| `AX5043_MAXRFOFFSET1NB` | SFRX | 0x510A | Maximum Receiver RF Offset 1, Non-Blocking |
| `AX5043_MAXRFOFFSET0NB` | SFRX | 0x510B | Maximum Receiver RF Offset 0, Non-Blocking |
| `AX5043_FSKDMAX1NB` | SFRX | 0x510C | Four FSK Rx Maximum Deviation 1, Non-Blocking |
| `AX5043_FSKDMAX0NB` | SFRX | 0x510D | Four FSK Rx Maximum Deviation 0, Non-Blocking |
| `AX5043_FSKDMIN1NB` | SFRX | 0x510E | Four FSK Rx Minimum Deviation 1, Non-Blocking |
| `AX5043_FSKDMIN0NB` | SFRX | 0x510F | Four FSK Rx Minimum Deviation 0, Non-Blocking |
| `AX5043_AFSKSPACE1NB` | SFRX | 0x5110 | AFSK Space (0) Frequency 1, Non-Blocking |
| `AX5043_AFSKSPACE0NB` | SFRX | 0x5111 | AFSK Space (0) Frequency 0, Non-Blocking |
| `AX5043_AFSKMARK1NB` | SFRX | 0x5112 | AFSK Mark (1) Frequency 1, Non-Blocking |
| `AX5043_AFSKMARK0NB` | SFRX | 0x5113 | AFSK Mark (1) Frequency 0, Non-Blocking |
| `AX5043_AFSKCTRLNB` | SFRX | 0x5114 | AFSK Control, Non-Blocking |
| `AX5043_AMPLFILTERNB` | SFRX | 0x5115 | Amplitude Filter, Non-Blocking |
| `AX5043_FREQUENCYLEAKNB` | SFRX | 0x5116 | Baseband Frequency Recovery Loop Leakiness, Non-Blocking |
| `AX5043_RXPARAMSETSNB_V1` | SFRX | 0x5116 | Receiver Parameter Set Indirection, Non-Blocking |
| `AX5043_RXPARAMCURSETNB_V1` | SFRX | 0x5117 | Receiver Parameter Current Set, Non-Blocking |
| `AX5043_RXPARAMSETSNB` | SFRX | 0x5117 | Receiver Parameter Set Indirection, Non-Blocking |
| `AX5043_RXPARAMCURSETNB` | SFRX | 0x5118 | Receiver Parameter Current Set, Non-Blocking |
| `AX5043_AGCGAIN0NB` | SFRX | 0x5120 | AGC Speed, Non-Blocking |
| `AX5043_AGCGAIN0NB_V1` | SFRX | 0x5120 | AGC Speed, Non-Blocking |
| `AX5043_AGCTARGET0NB` | SFRX | 0x5121 | AGC Target, Non-Blocking |
| `AX5043_AGCTARGET0NB_V1` | SFRX | 0x5121 | AGC Target, Non-Blocking |
| `AX5043_AGCAHYST0NB` | SFRX | 0x5122 | AGC Analog Hysteresis, Non-Blocking |
| `AX5043_TIMEGAIN0NB_V1` | SFRX | 0x5122 | Time Estimator Bandwidth, Non-Blocking |
| `AX5043_AGCMINMAX0NB` | SFRX | 0x5123 | AGC Analog Update Behaviour, Non-Blocking |
| `AX5043_DRGAIN0NB_V1` | SFRX | 0x5123 | Data Rate Estimator Bandwidth, Non-Blocking |
| `AX5043_PHASEGAIN0NB_V1` | SFRX | 0x5124 | Phase Estimator Bandwidth, Non-Blocking |
| `AX5043_TIMEGAIN0NB` | SFRX | 0x5124 | Time Estimator Bandwidth, Non-Blocking |
| `AX5043_DRGAIN0NB` | SFRX | 0x5125 | Data Rate Estimator Bandwidth, Non-Blocking |
| `AX5043_FREQUENCYGAINA0NB_V1` | SFRX | 0x5125 | Frequency Estimator Bandwidth A, Non-Blocking |
| `AX5043_FREQUENCYGAINB0NB_V1` | SFRX | 0x5126 | Frequency Estimator Bandwidth B, Non-Blocking |
| `AX5043_PHASEGAIN0NB` | SFRX | 0x5126 | Phase Estimator Bandwidth, Non-Blocking |
| `AX5043_FREQUENCYGAINA0NB` | SFRX | 0x5127 | Frequency Estimator Bandwidth A, Non-Blocking |
| `AX5043_FREQUENCYGAINC0NB_V1` | SFRX | 0x5127 | Frequency Estimator Bandwidth C, Non-Blocking |
| `AX5043_FREQUENCYGAINB0NB` | SFRX | 0x5128 | Frequency Estimator Bandwidth B, Non-Blocking |
| `AX5043_FREQUENCYGAIND0NB_V1` | SFRX | 0x5128 | Frequency Estimator Bandwidth D, Non-Blocking |
| `AX5043_AMPLITUDEGAIN0NB_V1` | SFRX | 0x5129 | Amplitude Estimator Bandwidth, Non-Blocking |
| `AX5043_FREQUENCYGAINC0NB` | SFRX | 0x5129 | Frequency Estimator Bandwidth C, Non-Blocking |
| `AX5043_FREQDEV10NB_V1` | SFRX | 0x512A | Receiver Frequency Deviation 1, Non-Blocking |
| `AX5043_FREQUENCYGAIND0NB` | SFRX | 0x512A | Frequency Estimator Bandwidth D, Non-Blocking |
| `AX5043_AMPLITUDEGAIN0NB` | SFRX | 0x512B | Amplitude Estimator Bandwidth, Non-Blocking |
| `AX5043_FREQDEV00NB_V1` | SFRX | 0x512B | Receiver Frequency Deviation 0, Non-Blocking |
| `AX5043_FOURFSK0NB_V1` | SFRX | 0x512C | Four FSK Control, Non-Blocking |
| `AX5043_FREQDEV10NB` | SFRX | 0x512C | Receiver Frequency Deviation 1, Non-Blocking |
| `AX5043_BBOFFSRES0NB_V1` | SFRX | 0x512D | Baseband Offset Compensation Resistors, Non-Blocking |
| `AX5043_FREQDEV00NB` | SFRX | 0x512D | Receiver Frequency Deviation 0, Non-Blocking |
| `AX5043_AGCGAIN1NB_V1` | SFRX | 0x512E | AGC Speed, Non-Blocking |
| `AX5043_FOURFSK0NB` | SFRX | 0x512E | Four FSK Control, Non-Blocking |
| `AX5043_AGCTARGET1NB_V1` | SFRX | 0x512F | AGC Target, Non-Blocking |
| `AX5043_BBOFFSRES0NB` | SFRX | 0x512F | Baseband Offset Compensation Resistors, Non-Blocking |
| `AX5043_AGCGAIN1NB` | SFRX | 0x5130 | AGC Speed, Non-Blocking |
| `AX5043_TIMEGAIN1NB_V1` | SFRX | 0x5130 | Time Estimator Bandwidth, Non-Blocking |
| `AX5043_AGCTARGET1NB` | SFRX | 0x5131 | AGC Target, Non-Blocking |
| `AX5043_DRGAIN1NB_V1` | SFRX | 0x5131 | Data Rate Estimator Bandwidth, Non-Blocking |
| `AX5043_AGCAHYST1NB` | SFRX | 0x5132 | AGC Analog Hysteresis, Non-Blocking |
| `AX5043_PHASEGAIN1NB_V1` | SFRX | 0x5132 | Phase Estimator Bandwidth, Non-Blocking |
| `AX5043_AGCMINMAX1NB` | SFRX | 0x5133 | AGC Analog Update Behaviour, Non-Blocking |
| `AX5043_FREQUENCYGAINA1NB_V1` | SFRX | 0x5133 | Frequency Estimator Bandwidth A, Non-Blocking |
| `AX5043_FREQUENCYGAINB1NB_V1` | SFRX | 0x5134 | Frequency Estimator Bandwidth B, Non-Blocking |
| `AX5043_TIMEGAIN1NB` | SFRX | 0x5134 | Time Estimator Bandwidth, Non-Blocking |
| `AX5043_DRGAIN1NB` | SFRX | 0x5135 | Data Rate Estimator Bandwidth, Non-Blocking |
| `AX5043_FREQUENCYGAINC1NB_V1` | SFRX | 0x5135 | Frequency Estimator Bandwidth C, Non-Blocking |
| `AX5043_FREQUENCYGAIND1NB_V1` | SFRX | 0x5136 | Frequency Estimator Bandwidth D, Non-Blocking |
| `AX5043_PHASEGAIN1NB` | SFRX | 0x5136 | Phase Estimator Bandwidth, Non-Blocking |
| `AX5043_AMPLITUDEGAIN1NB_V1` | SFRX | 0x5137 | Amplitude Estimator Bandwidth, Non-Blocking |
| `AX5043_FREQUENCYGAINA1NB` | SFRX | 0x5137 | Frequency Estimator Bandwidth A, Non-Blocking |
| `AX5043_FREQDEV11NB_V1` | SFRX | 0x5138 | Receiver Frequency Deviation 1, Non-Blocking |
| `AX5043_FREQUENCYGAINB1NB` | SFRX | 0x5138 | Frequency Estimator Bandwidth B, Non-Blocking |
| `AX5043_FREQDEV01NB_V1` | SFRX | 0x5139 | Receiver Frequency Deviation 0, Non-Blocking |
| `AX5043_FREQUENCYGAINC1NB` | SFRX | 0x5139 | Frequency Estimator Bandwidth C, Non-Blocking |
| `AX5043_FOURFSK1NB_V1` | SFRX | 0x513A | Four FSK Control, Non-Blocking |
| `AX5043_FREQUENCYGAIND1NB` | SFRX | 0x513A | Frequency Estimator Bandwidth D, Non-Blocking |
| `AX5043_AMPLITUDEGAIN1NB` | SFRX | 0x513B | Amplitude Estimator Bandwidth, Non-Blocking |
| `AX5043_BBOFFSRES1NB_V1` | SFRX | 0x513B | Baseband Offset Compensation Resistors, Non-Blocking |
| `AX5043_AGCGAIN2NB_V1` | SFRX | 0x513C | AGC Speed, Non-Blocking |
| `AX5043_FREQDEV11NB` | SFRX | 0x513C | Receiver Frequency Deviation 1, Non-Blocking |
| `AX5043_AGCTARGET2NB_V1` | SFRX | 0x513D | AGC Target, Non-Blocking |
| `AX5043_FREQDEV01NB` | SFRX | 0x513D | Receiver Frequency Deviation 0, Non-Blocking |
| `AX5043_FOURFSK1NB` | SFRX | 0x513E | Four FSK Control, Non-Blocking |
| `AX5043_TIMEGAIN2NB_V1` | SFRX | 0x513E | Time Estimator Bandwidth, Non-Blocking |
| `AX5043_BBOFFSRES1NB` | SFRX | 0x513F | Baseband Offset Compensation Resistors, Non-Blocking |
| `AX5043_DRGAIN2NB_V1` | SFRX | 0x513F | Data Rate Estimator Bandwidth, Non-Blocking |
| `AX5043_AGCGAIN2NB` | SFRX | 0x5140 | AGC Speed, Non-Blocking |
| `AX5043_PHASEGAIN2NB_V1` | SFRX | 0x5140 | Phase Estimator Bandwidth, Non-Blocking |
| `AX5043_AGCTARGET2NB` | SFRX | 0x5141 | AGC Target, Non-Blocking |
| `AX5043_FREQUENCYGAINA2NB_V1` | SFRX | 0x5141 | Frequency Estimator Bandwidth A, Non-Blocking |
| `AX5043_AGCAHYST2NB` | SFRX | 0x5142 | AGC Analog Hysteresis, Non-Blocking |
| `AX5043_FREQUENCYGAINB2NB_V1` | SFRX | 0x5142 | Frequency Estimator Bandwidth B, Non-Blocking |
| `AX5043_AGCMINMAX2NB` | SFRX | 0x5143 | AGC Analog Update Behaviour, Non-Blocking |
| `AX5043_FREQUENCYGAINC2NB_V1` | SFRX | 0x5143 | Frequency Estimator Bandwidth C, Non-Blocking |
| `AX5043_FREQUENCYGAIND2NB_V1` | SFRX | 0x5144 | Frequency Estimator Bandwidth D, Non-Blocking |
| `AX5043_TIMEGAIN2NB` | SFRX | 0x5144 | Time Estimator Bandwidth, Non-Blocking |
| `AX5043_AMPLITUDEGAIN2NB_V1` | SFRX | 0x5145 | Amplitude Estimator Bandwidth, Non-Blocking |
| `AX5043_DRGAIN2NB` | SFRX | 0x5145 | Data Rate Estimator Bandwidth, Non-Blocking |
| `AX5043_FREQDEV12NB_V1` | SFRX | 0x5146 | Receiver Frequency Deviation 1, Non-Blocking |
| `AX5043_PHASEGAIN2NB` | SFRX | 0x5146 | Phase Estimator Bandwidth, Non-Blocking |
| `AX5043_FREQDEV02NB_V1` | SFRX | 0x5147 | Receiver Frequency Deviation 0, Non-Blocking |
| `AX5043_FREQUENCYGAINA2NB` | SFRX | 0x5147 | Frequency Estimator Bandwidth A, Non-Blocking |
| `AX5043_FOURFSK2NB_V1` | SFRX | 0x5148 | Four FSK Control, Non-Blocking |
| `AX5043_FREQUENCYGAINB2NB` | SFRX | 0x5148 | Frequency Estimator Bandwidth B, Non-Blocking |
| `AX5043_BBOFFSRES2NB_V1` | SFRX | 0x5149 | Baseband Offset Compensation Resistors, Non-Blocking |
| `AX5043_FREQUENCYGAINC2NB` | SFRX | 0x5149 | Frequency Estimator Bandwidth C, Non-Blocking |
| `AX5043_AGCGAIN3NB_V1` | SFRX | 0x514A | AGC Speed, Non-Blocking |
| `AX5043_FREQUENCYGAIND2NB` | SFRX | 0x514A | Frequency Estimator Bandwidth D, Non-Blocking |
| `AX5043_AGCTARGET3NB_V1` | SFRX | 0x514B | AGC Target, Non-Blocking |
| `AX5043_AMPLITUDEGAIN2NB` | SFRX | 0x514B | Amplitude Estimator Bandwidth, Non-Blocking |
| `AX5043_FREQDEV12NB` | SFRX | 0x514C | Receiver Frequency Deviation 1, Non-Blocking |
| `AX5043_TIMEGAIN3NB_V1` | SFRX | 0x514C | Time Estimator Bandwidth, Non-Blocking |
| `AX5043_DRGAIN3NB_V1` | SFRX | 0x514D | Data Rate Estimator Bandwidth, Non-Blocking |
| `AX5043_FREQDEV02NB` | SFRX | 0x514D | Receiver Frequency Deviation 0, Non-Blocking |
| `AX5043_FOURFSK2NB` | SFRX | 0x514E | Four FSK Control, Non-Blocking |
| `AX5043_PHASEGAIN3NB_V1` | SFRX | 0x514E | Phase Estimator Bandwidth, Non-Blocking |
| `AX5043_BBOFFSRES2NB` | SFRX | 0x514F | Baseband Offset Compensation Resistors, Non-Blocking |
| `AX5043_FREQUENCYGAINA3NB_V1` | SFRX | 0x514F | Frequency Estimator Bandwidth A, Non-Blocking |
| `AX5043_AGCGAIN3NB` | SFRX | 0x5150 | AGC Speed, Non-Blocking |
| `AX5043_FREQUENCYGAINB3NB_V1` | SFRX | 0x5150 | Frequency Estimator Bandwidth B, Non-Blocking |
| `AX5043_AGCTARGET3NB` | SFRX | 0x5151 | AGC Target, Non-Blocking |
| `AX5043_FREQUENCYGAINC3NB_V1` | SFRX | 0x5151 | Frequency Estimator Bandwidth C, Non-Blocking |
| `AX5043_AGCAHYST3NB` | SFRX | 0x5152 | AGC Analog Hysteresis, Non-Blocking |
| `AX5043_FREQUENCYGAIND3NB_V1` | SFRX | 0x5152 | Frequency Estimator Bandwidth D, Non-Blocking |
| `AX5043_AGCMINMAX3NB` | SFRX | 0x5153 | AGC Analog Update Behaviour, Non-Blocking |
| `AX5043_AMPLITUDEGAIN3NB_V1` | SFRX | 0x5153 | Amplitude Estimator Bandwidth, Non-Blocking |
| `AX5043_FREQDEV13NB_V1` | SFRX | 0x5154 | Receiver Frequency Deviation 1, Non-Blocking |
| `AX5043_TIMEGAIN3NB` | SFRX | 0x5154 | Time Estimator Bandwidth, Non-Blocking |
| `AX5043_DRGAIN3NB` | SFRX | 0x5155 | Data Rate Estimator Bandwidth, Non-Blocking |
| `AX5043_FREQDEV03NB_V1` | SFRX | 0x5155 | Receiver Frequency Deviation 0, Non-Blocking |
| `AX5043_FOURFSK3NB_V1` | SFRX | 0x5156 | Four FSK Control, Non-Blocking |
| `AX5043_PHASEGAIN3NB` | SFRX | 0x5156 | Phase Estimator Bandwidth, Non-Blocking |
| `AX5043_BBOFFSRES3NB_V1` | SFRX | 0x5157 | Baseband Offset Compensation Resistors, Non-Blocking |
| `AX5043_FREQUENCYGAINA3NB` | SFRX | 0x5157 | Frequency Estimator Bandwidth A, Non-Blocking |
| `AX5043_FREQUENCYGAINB3NB` | SFRX | 0x5158 | Frequency Estimator Bandwidth B, Non-Blocking |
| `AX5043_FREQUENCYGAINC3NB` | SFRX | 0x5159 | Frequency Estimator Bandwidth C, Non-Blocking |
| `AX5043_FREQUENCYGAIND3NB` | SFRX | 0x515A | Frequency Estimator Bandwidth D, Non-Blocking |
| `AX5043_AMPLITUDEGAIN3NB` | SFRX | 0x515B | Amplitude Estimator Bandwidth, Non-Blocking |
| `AX5043_FREQDEV13NB` | SFRX | 0x515C | Receiver Frequency Deviation 1, Non-Blocking |
| `AX5043_FREQDEV03NB` | SFRX | 0x515D | Receiver Frequency Deviation 0, Non-Blocking |
| `AX5043_FOURFSK3NB` | SFRX | 0x515E | Four FSK Control, Non-Blocking |
| `AX5043_BBOFFSRES3NB` | SFRX | 0x515F | Baseband Offset Compensation Resistors, Non-Blocking |
| `AX5043_MODCFGFNB` | SFRX | 0x5160 | Modulator Configuration F, Non-Blocking |
| `AX5043_FSKDEV2NB` | SFRX | 0x5161 | FSK Deviation 2, Non-Blocking |
| `AX5043_FSKDEV1NB` | SFRX | 0x5162 | FSK Deviation 1, Non-Blocking |
| `AX5043_FSKDEV0NB` | SFRX | 0x5163 | FSK Deviation 0, Non-Blocking |
| `AX5043_MODCFGANB` | SFRX | 0x5164 | Modulator Configuration A, Non-Blocking |
| `AX5043_TXRATE2NB` | SFRX | 0x5165 | Transmitter Bitrate 2, Non-Blocking |
| `AX5043_TXRATE1NB` | SFRX | 0x5166 | Transmitter Bitrate 1, Non-Blocking |
| `AX5043_TXRATE0NB` | SFRX | 0x5167 | Transmitter Bitrate 0, Non-Blocking |
| `AX5043_TXPWRCOEFFA1NB` | SFRX | 0x5168 | Transmitter Predistortion Coefficient A 1, Non-Blocking |
| `AX5043_TXPWRCOEFFA0NB` | SFRX | 0x5169 | Transmitter Predistortion Coefficient A 0, Non-Blocking |
| `AX5043_TXPWRCOEFFB1NB` | SFRX | 0x516A | Transmitter Predistortion Coefficient B 1, Non-Blocking |
| `AX5043_TXPWRCOEFFB0NB` | SFRX | 0x516B | Transmitter Predistortion Coefficient B 0, Non-Blocking |
| `AX5043_TXPWRCOEFFC1NB` | SFRX | 0x516C | Transmitter Predistortion Coefficient C 1, Non-Blocking |
| `AX5043_TXPWRCOEFFC0NB` | SFRX | 0x516D | Transmitter Predistortion Coefficient C 0, Non-Blocking |
| `AX5043_TXPWRCOEFFD1NB` | SFRX | 0x516E | Transmitter Predistortion Coefficient D 1, Non-Blocking |
| `AX5043_TXPWRCOEFFD0NB` | SFRX | 0x516F | Transmitter Predistortion Coefficient D 0, Non-Blocking |
| `AX5043_TXPWRCOEFFE1NB` | SFRX | 0x5170 | Transmitter Predistortion Coefficient E 1, Non-Blocking |
| `AX5043_TXPWRCOEFFE0NB` | SFRX | 0x5171 | Transmitter Predistortion Coefficient E 0, Non-Blocking |
| `AX5043_PLLVCOINB` | SFRX | 0x5180 | PLL VCO Current, Non-Blocking |
| `AX5043_PLLVCOIRNB` | SFRX | 0x5181 | PLL VCO Current Readback, Non-Blocking |
| `AX5043_PLLLOCKDETNB` | SFRX | 0x5182 | PLL Lock Detect Delay, Non-Blocking |
| `AX5043_PLLRNGCLKNB` | SFRX | 0x5183 | PLL Autoranging Clock, Non-Blocking |
| `AX5043_XTALCAPNB` | SFRX | 0x5184 | Crystal Oscillator Load Capacitance, Non-Blocking |
| `AX5043_BBTUNENB` | SFRX | 0x5188 | Baseband Tuning, Non-Blocking |
| `AX5043_BBOFFSCAPNB` | SFRX | 0x5189 | Baseband Offset Compensation Capacitors, Non-Blocking |
| `AX5043_PKTADDRCFGNB` | SFRX | 0x5200 | Packet Address Config, Non-Blocking |
| `AX5043_PKTADDRCFGNB_V1` | SFRX | 0x5201 | Packet Address Config, Non-Blocking |
| `AX5043_PKTLENCFGNB` | SFRX | 0x5201 | Packet Length Configuration, Non-Blocking |
| `AX5043_PKTADDR1NB_V1` | SFRX | 0x5202 | Packet Address 1, Non-Blocking |
| `AX5043_PKTLENOFFSETNB` | SFRX | 0x5202 | Packet Length Offset, Non-Blocking |
| `AX5043_PKTADDR0NB_V1` | SFRX | 0x5203 | Packet Address 0, Non-Blocking |
| `AX5043_PKTMAXLENNB` | SFRX | 0x5203 | Packet Maximum Length, Non-Blocking |
| `AX5043_PKTADDR3NB` | SFRX | 0x5204 | Packet Address 3, Non-Blocking |
| `AX5043_PKTADDRMASK1NB_V1` | SFRX | 0x5204 | Packet Address Mask 1, Non-Blocking |
| `AX5043_PKTADDR2NB` | SFRX | 0x5205 | Packet Address 2, Non-Blocking |
| `AX5043_PKTADDRMASK0NB_V1` | SFRX | 0x5205 | Packet Address Mask 0, Non-Blocking |
| `AX5043_PKTADDR1NB` | SFRX | 0x5206 | Packet Address 1, Non-Blocking |
| `AX5043_PKTLENCFGNB_V1` | SFRX | 0x5206 | Packet Length Configuration, Non-Blocking |
| `AX5043_PKTADDR0NB` | SFRX | 0x5207 | Packet Address 0, Non-Blocking |
| `AX5043_PKTLENOFFSETNB_V1` | SFRX | 0x5207 | Packet Length Offset, Non-Blocking |
| `AX5043_PKTADDRMASK3NB` | SFRX | 0x5208 | Packet Address Mask 3, Non-Blocking |
| `AX5043_PKTMAXLENNB_V1` | SFRX | 0x5208 | Packet Maximum Length, Non-Blocking |
| `AX5043_PKTADDRMASK2NB` | SFRX | 0x5209 | Packet Address Mask 2, Non-Blocking |
| `AX5043_PKTADDRMASK1NB` | SFRX | 0x520A | Packet Address Mask 1, Non-Blocking |
| `AX5043_PKTADDRMASK0NB` | SFRX | 0x520B | Packet Address Mask 0, Non-Blocking |
| `AX5043_MATCH0PAT3NB` | SFRX | 0x5210 | Pattern Match Unit 0, Pattern 3, Non-Blocking |
| `AX5043_MATCH0PAT2NB` | SFRX | 0x5211 | Pattern Match Unit 0, Pattern 2, Non-Blocking |
| `AX5043_MATCH0PAT1NB` | SFRX | 0x5212 | Pattern Match Unit 0, Pattern 1, Non-Blocking |
| `AX5043_MATCH0PAT0NB` | SFRX | 0x5213 | Pattern Match Unit 0, Pattern 0, Non-Blocking |
| `AX5043_MATCH0LENNB` | SFRX | 0x5214 | Pattern Match Unit 0, Pattern Length, Non-Blocking |
| `AX5043_MATCH0MINNB` | SFRX | 0x5215 | Pattern Match Unit 0, Minimum Match, Non-Blocking |
| `AX5043_MATCH0MAXNB` | SFRX | 0x5216 | Pattern Match Unit 0, Maximum Match, Non-Blocking |
| `AX5043_MATCH1PAT1NB` | SFRX | 0x5218 | Pattern Match Unit 1, Pattern 1, Non-Blocking |
| `AX5043_MATCH1PAT0NB` | SFRX | 0x5219 | Pattern Match Unit 1, Pattern 0, Non-Blocking |
| `AX5043_MATCH1LENNB` | SFRX | 0x521C | Pattern Match Unit 1, Pattern Length, Non-Blocking |
| `AX5043_MATCH1MINNB` | SFRX | 0x521D | Pattern Match Unit 1, Minimum Match, Non-Blocking |
| `AX5043_MATCH1MAXNB` | SFRX | 0x521E | Pattern Match Unit 1, Maximum Match, Non-Blocking |
| `AX5043_TMGTXBOOSTNB` | SFRX | 0x5220 | Transmit PLL Boost Time, Non-Blocking |
| `AX5043_TMGTXSETTLENB` | SFRX | 0x5221 | Transmit PLL (post Boost) Settling Time, Non-Blocking |
| `AX5043_TMGRXBOOSTNB` | SFRX | 0x5223 | Receive PLL Boost Time, Non-Blocking |
| `AX5043_TMGRXSETTLENB` | SFRX | 0x5224 | Receive PLL (post Boost) Settling Time, Non-Blocking |
| `AX5043_TMGRXOFFSACQNB` | SFRX | 0x5225 | Receive Baseband DC Offset Acquisition Time, Non-Blocking |
| `AX5043_TMGRXCOARSEAGCNB` | SFRX | 0x5226 | Receive Coarse AGC Time, Non-Blocking |
| `AX5043_TMGRXAGCNB` | SFRX | 0x5227 | Receiver AGC Settling Time, Non-Blocking |
| `AX5043_TMGRXRSSINB` | SFRX | 0x5228 | Receiver RSSI Settling Time, Non-Blocking |
| `AX5043_TMGRXPREAMBLE1NB` | SFRX | 0x5229 | Receiver Preamble 1 Timeout, Non-Blocking |
| `AX5043_TMGRXPREAMBLE2NB` | SFRX | 0x522A | Receiver Preamble 2 Timeout, Non-Blocking |
| `AX5043_TMGRXPREAMBLE3NB` | SFRX | 0x522B | Receiver Preamble 3 Timeout, Non-Blocking |
| `AX5043_RSSIREFERENCENB` | SFRX | 0x522C | RSSI Offset, Non-Blocking |
| `AX5043_RSSIABSTHRNB` | SFRX | 0x522D | RSSI Absolute Threshold, Non-Blocking |
| `AX5043_BGNDRSSIGAINNB` | SFRX | 0x522E | Background RSSI Averaging Time Constant, Non-Blocking |
| `AX5043_BGNDRSSITHRNB` | SFRX | 0x522F | Background RSSI Relative Threshold, Non-Blocking |
| `AX5043_PKTCHUNKSIZENB` | SFRX | 0x5230 | Packet Chunk Size, Non-Blocking |
| `AX5043_PKTMISCFLAGSNB` | SFRX | 0x5231 | Packet Controller Miscellaneous Flags, Non-Blocking |
| `AX5043_PKTSTOREFLAGSNB` | SFRX | 0x5232 | Packet Controller Store Flags, Non-Blocking |
| `AX5043_PKTACCEPTFLAGSNB` | SFRX | 0x5233 | Packet Controller Accept Flags, Non-Blocking |
| `AX5043_GPADCCTRLNB` | SFRX | 0x5300 | General Purpose ADC Control, Non-Blocking |
| `AX5043_GPADCPERIODNB` | SFRX | 0x5301 | GPADC Sampling Period, Non-Blocking |
| `AX5043_GPADC13VALUE1NB` | SFRX | 0x5308 | GPADC13 Value 1, Non-Blocking |
| `AX5043_GPADC13VALUE0NB` | SFRX | 0x5309 | GPADC13 Value 0, Non-Blocking |
| `AX5043_LPOSCCONFIGNB` | SFRX | 0x5310 | Low Power Oscillator Calibration Configuration, Non-Blocking |
| `AX5043_LPOSCSTATUSNB` | SFRX | 0x5311 | Low Power Oscillator Calibration Status, Non-Blocking |
| `AX5043_LPOSCKFILT1NB` | SFRX | 0x5312 | Low Power Oscillator Calibration Filter Constant High Byte, Non-Blocking |
| `AX5043_LPOSCKFILT0NB` | SFRX | 0x5313 | Low Power Oscillator Calibration Filter Constant Low Byte, Non-Blocking |
| `AX5043_LPOSCREF1NB` | SFRX | 0x5314 | Low Power Oscillator Reference Frequency High Byte, Non-Blocking |
| `AX5043_LPOSCREF0NB` | SFRX | 0x5315 | Low Power Oscillator Reference Frequency Low Byte, Non-Blocking |
| `AX5043_LPOSCFREQ1NB` | SFRX | 0x5316 | Low Power Oscillator Frequency Tuning High Byte, Non-Blocking |
| `AX5043_LPOSCFREQ0NB` | SFRX | 0x5317 | Low Power Oscillator Frequency Tuning Low Byte, Non-Blocking |
| `AX5043_LPOSCPER1NB` | SFRX | 0x5318 | Low Power Oscillator Period High Byte, Non-Blocking |
| `AX5043_LPOSCPER0NB` | SFRX | 0x5319 | Low Power Oscillator Period Low Byte, Non-Blocking |
| `AX5043_DACVALUE1NB` | SFRX | 0x5330 | DAC Value 1, Non-Blocking |
| `AX5043_DACVALUE0NB` | SFRX | 0x5331 | DAC Value 0, Non-Blocking |
| `AX5043_DACCONFIGNB` | SFRX | 0x5332 | DAC Configuration, Non-Blocking |
| `AX5043_0xF00NB` | SFRX | 0x5F00 |  |
| `AX5043_POWCTRL1NB` | SFRX | 0x5F08 | Power Control 1, Non-Blocking |
| `AX5043_0xF0CNB` | SFRX | 0x5F0C |  |
| `AX5043_REFNB` | SFRX | 0x5F0D | Reference, Non-Blocking |
| `AX5043_XTALOSCNB` | SFRX | 0x5F10 | Crystal Oscillator Control, Non-Blocking |
| `AX5043_XTALAMPLNB` | SFRX | 0x5F11 | Crystal Oscillator Amplitude Control, Non-Blocking |
| `AX5043_0xF18NB` | SFRX | 0x5F18 |  |
| `AX5043_0xF1CNB` | SFRX | 0x5F1C |  |
| `AX5043_0xF21NB` | SFRX | 0x5F21 |  |
| `AX5043_0xF22NB` | SFRX | 0x5F22 |  |
| `AX5043_0xF23NB` | SFRX | 0x5F23 |  |
| `AX5043_0xF26NB` | SFRX | 0x5F26 |  |
| `AX5043_0xF30NB` | SFRX | 0x5F30 |  |
| `AX5043_0xF31NB` | SFRX | 0x5F31 |  |
| `AX5043_0xF32NB` | SFRX | 0x5F32 |  |
| `AX5043_0xF33NB` | SFRX | 0x5F33 |  |
| `AX5043_0xF34NB` | SFRX | 0x5F34 |  |
| `AX5043_0xF35NB` | SFRX | 0x5F35 |  |
| `AX5043_0xF44NB` | SFRX | 0x5F44 |  |
| `AX5043_MODCFGPNB` | SFRX | 0x5F5F | Modulator Configuration P, Non-Blocking |

## AX5043 `AX5043_REG_*` constants (ax5043.h, for radio_read8/radio_write8)

`radio_write8(addr, d)` on the F143 is `*(volatile __xdata uint8_t *)((addr & 0xFFF) | 0x4000) = d`.
So `0xF100` (IFFREQ1) lands at X 0x4100. The `0xF` prefix only marks long-address registers.

| Constant | Value | X address | Description |
|---|---|---|---|
| `AX5043_REG_SILICONREVISION` | 0x0000 | 0x4000 | Silicon Revision |
| `AX5043_REG_SCRATCH` | 0x0001 | 0x4001 | Scratch |
| `AX5043_REG_PWRMODE` | 0x0002 | 0x4002 | Power Mode |
| `AX5043_REG_POWSTAT` | 0x0003 | 0x4003 | Power Management Status |
| `AX5043_REG_POWSTICKYSTAT` | 0x0004 | 0x4004 | Power Management Sticky Status |
| `AX5043_REG_POWIRQMASK` | 0x0005 | 0x4005 | Power Management Interrupt Mask |
| `AX5043_REG_IRQMASK1` | 0x0006 | 0x4006 | IRQ Mask 1 |
| `AX5043_REG_IRQMASK0` | 0x0007 | 0x4007 | IRQ Mask 0 |
| `AX5043_REG_RADIOEVENTMASK1` | 0x0008 | 0x4008 | Radio Event Mask 1 |
| `AX5043_REG_RADIOEVENTMASK0` | 0x0009 | 0x4009 | Radio Event Mask 0 |
| `AX5043_REG_IRQINVERSION1` | 0x000A | 0x400A | IRQ Inversion 1 |
| `AX5043_REG_IRQINVERSION0` | 0x000B | 0x400B | IRQ Inversion 0 |
| `AX5043_REG_IRQREQUEST1` | 0x000C | 0x400C | IRQ Request 1 |
| `AX5043_REG_IRQREQUEST0` | 0x000D | 0x400D | IRQ Request 0 |
| `AX5043_REG_RADIOEVENTREQ1` | 0x000E | 0x400E | Radio Event Request 1 |
| `AX5043_REG_RADIOEVENTREQ0` | 0x000F | 0x400F | Radio Event Request 0 |
| `AX5043_REG_MODULATION` | 0x0010 | 0x4010 | Modulation |
| `AX5043_REG_ENCODING` | 0x0011 | 0x4011 | Encoding |
| `AX5043_REG_FRAMING` | 0x0012 | 0x4012 | Framing Mode |
| `AX5043_REG_CRCINIT3` | 0x0014 | 0x4014 | CRC Initial Value 3 |
| `AX5043_REG_CRCINIT2` | 0x0015 | 0x4015 | CRC Initial Value 2 |
| `AX5043_REG_CRCINIT1` | 0x0016 | 0x4016 | CRC Initial Value 1 |
| `AX5043_REG_CRCINIT0` | 0x0017 | 0x4017 | CRC Initial Value 0 |
| `AX5043_REG_FEC` | 0x0018 | 0x4018 | Forward Error Correction |
| `AX5043_REG_FECSYNC` | 0x0019 | 0x4019 | Forward Error Correction Sync Threshold |
| `AX5043_REG_FECSTATUS` | 0x001A | 0x401A | Forward Error Correction Status |
| `AX5043_REG_RADIOSTATE` | 0x001C | 0x401C | Radio Controller State |
| `AX5043_REG_XTALSTATUS` | 0x001D | 0x401D | Crystal Oscillator Status |
| `AX5043_REG_PINSTATE` | 0x0020 | 0x4020 | Pin State |
| `AX5043_REG_PINFUNCSYSCLK` | 0x0021 | 0x4021 | Pin Function SYSCLK |
| `AX5043_REG_PINFUNCDCLK` | 0x0022 | 0x4022 | Pin Function DCLK |
| `AX5043_REG_PINFUNCDATA` | 0x0023 | 0x4023 | Pin Function DATA |
| `AX5043_REG_PINFUNCIRQ` | 0x0024 | 0x4024 | Pin Function IRQ |
| `AX5043_REG_PINFUNCANTSEL` | 0x0025 | 0x4025 | Pin Function ANTSEL |
| `AX5043_REG_PINFUNCPWRAMP` | 0x0026 | 0x4026 | Pin Function PWRAMP |
| `AX5043_REG_PWRAMP` | 0x0027 | 0x4027 | PWRAMP Control |
| `AX5043_REG_FIFOSTAT` | 0x0028 | 0x4028 | FIFO Control |
| `AX5043_REG_FIFODATA` | 0x0029 | 0x4029 | FIFO Data |
| `AX5043_REG_FIFOCOUNT1` | 0x002A | 0x402A | Number of Words currently in FIFO 1 |
| `AX5043_REG_FIFOCOUNT0` | 0x002B | 0x402B | Number of Words currently in FIFO 0 |
| `AX5043_REG_FIFOFREE1` | 0x002C | 0x402C | Number of Words that can be written to FIFO 1 |
| `AX5043_REG_FIFOFREE0` | 0x002D | 0x402D | Number of Words that can be written to FIFO 0 |
| `AX5043_REG_FIFOTHRESH1` | 0x002E | 0x402E | FIFO Threshold 1 |
| `AX5043_REG_FIFOTHRESH0` | 0x002F | 0x402F | FIFO Threshold 0 |
| `AX5043_REG_PLLLOOP` | 0x0030 | 0x4030 | PLL Loop Filter Settings |
| `AX5043_REG_PLLCPI` | 0x0031 | 0x4031 | PLL Charge Pump Current |
| `AX5043_REG_PLLVCODIV` | 0x0032 | 0x4032 | PLL Divider Settings |
| `AX5043_REG_PLLRANGINGA` | 0x0033 | 0x4033 | PLL Autoranging A |
| `AX5043_REG_FREQA3` | 0x0034 | 0x4034 | Frequency A 3 |
| `AX5043_REG_FREQA2` | 0x0035 | 0x4035 | Frequency A 2 |
| `AX5043_REG_FREQA1` | 0x0036 | 0x4036 | Frequency A 1 |
| `AX5043_REG_FREQA0` | 0x0037 | 0x4037 | Frequency A 0 |
| `AX5043_REG_PLLLOOPBOOST` | 0x0038 | 0x4038 | PLL Loop Filter Settings (Boosted) |
| `AX5043_REG_PLLCPIBOOST` | 0x0039 | 0x4039 | PLL Charge Pump Current (Boosted) |
| `AX5043_REG_PLLRANGINGB` | 0x003B | 0x403B | PLL Autoranging B |
| `AX5043_REG_FREQB3` | 0x003C | 0x403C | Frequency B 3 |
| `AX5043_REG_FREQB2` | 0x003D | 0x403D | Frequency B 2 |
| `AX5043_REG_FREQB1` | 0x003E | 0x403E | Frequency B 1 |
| `AX5043_REG_FREQB0` | 0x003F | 0x403F | Frequency B 0 |
| `AX5043_REG_RSSI` | 0x0040 | 0x4040 | Received Signal Strength Indicator |
| `AX5043_REG_BGNDRSSI` | 0x0041 | 0x4041 | Background RSSI |
| `AX5043_REG_DIVERSITY` | 0x0042 | 0x4042 | Antenna Diversity Configuration |
| `AX5043_REG_AGCCOUNTER` | 0x0043 | 0x4043 | AGC Counter |
| `AX5043_REG_TRKDATARATE2` | 0x0045 | 0x4045 | Datarate Tracking 2 |
| `AX5043_REG_TRKDATARATE1` | 0x0046 | 0x4046 | Datarate Tracking 1 |
| `AX5043_REG_TRKDATARATE0` | 0x0047 | 0x4047 | Datarate Tracking 0 |
| `AX5043_REG_TRKAMPLITUDE1` | 0x0048 | 0x4048 | Amplitude Tracking 1 |
| `AX5043_REG_TRKAMPLITUDE0` | 0x0049 | 0x4049 | Amplitude Tracking 0 |
| `AX5043_REG_TRKPHASE1` | 0x004A | 0x404A | Phase Tracking 1 |
| `AX5043_REG_TRKPHASE0` | 0x004B | 0x404B | Phase Tracking 0 |
| `AX5043_REG_TRKRFFREQ2` | 0x004D | 0x404D | RF Frequency Tracking 2 |
| `AX5043_REG_TRKRFFREQ1` | 0x004E | 0x404E | RF Frequency Tracking 1 |
| `AX5043_REG_TRKRFFREQ0` | 0x004F | 0x404F | RF Frequency Tracking 0 |
| `AX5043_REG_TRKFREQ1` | 0x0050 | 0x4050 | Frequency Tracking 1 |
| `AX5043_REG_TRKFREQ0` | 0x0051 | 0x4051 | Frequency Tracking 0 |
| `AX5043_REG_TRKFSKDEMOD1` | 0x0052 | 0x4052 | FSK Demodulator Tracking 1 |
| `AX5043_REG_TRKFSKDEMOD0` | 0x0053 | 0x4053 | FSK Demodulator Tracking 0 |
| `AX5043_REG_TRKAFSKDEMOD1` | 0x0054 | 0x4054 | AFSK Demodulator Tracking 1 |
| `AX5043_REG_TRKAFSKDEMOD0` | 0x0055 | 0x4055 | AFSK Demodulator Tracking 0 |
| `AX5043_REG_TIMER2` | 0x0059 | 0x4059 | 1MHz Timer 2 |
| `AX5043_REG_TIMER1` | 0x005A | 0x405A | 1MHz Timer 1 |
| `AX5043_REG_TIMER0` | 0x005B | 0x405B | 1MHz Timer 0 |
| `AX5043_REG_WAKEUPTIMER1` | 0x0068 | 0x4068 | Wakeup Timer 1 |
| `AX5043_REG_WAKEUPTIMER0` | 0x0069 | 0x4069 | Wakeup Timer 0 |
| `AX5043_REG_WAKEUP1` | 0x006A | 0x406A | Wakeup Time 1 |
| `AX5043_REG_WAKEUP0` | 0x006B | 0x406B | Wakeup Time 0 |
| `AX5043_REG_WAKEUPFREQ1` | 0x006C | 0x406C | Wakeup Frequency 1 |
| `AX5043_REG_WAKEUPFREQ0` | 0x006D | 0x406D | Wakeup Frequency 0 |
| `AX5043_REG_WAKEUPXOEARLY` | 0x006E | 0x406E | Wakeup Crystal Oscillator Early |
| `AX5043_REG_IFFREQ1` | 0xF100 | 0x4100 | 2nd LO / IF Frequency 1 |
| `AX5043_REG_IFFREQ0` | 0xF101 | 0x4101 | 2nd LO / IF Frequency 0 |
| `AX5043_REG_DECIMATION` | 0xF102 | 0x4102 | Decimation Factor |
| `AX5043_REG_RXDATARATE2` | 0xF103 | 0x4103 | Receiver Datarate 2 |
| `AX5043_REG_RXDATARATE1` | 0xF104 | 0x4104 | Receiver Datarate 1 |
| `AX5043_REG_RXDATARATE0` | 0xF105 | 0x4105 | Receiver Datarate 0 |
| `AX5043_REG_MAXDROFFSET2` | 0xF106 | 0x4106 | Maximum Receiver Datarate Offset 2 |
| `AX5043_REG_MAXDROFFSET1` | 0xF107 | 0x4107 | Maximum Receiver Datarate Offset 1 |
| `AX5043_REG_MAXDROFFSET0` | 0xF108 | 0x4108 | Maximum Receiver Datarate Offset 0 |
| `AX5043_REG_MAXRFOFFSET2` | 0xF109 | 0x4109 | Maximum Receiver RF Offset 2 |
| `AX5043_REG_MAXRFOFFSET1` | 0xF10A | 0x410A | Maximum Receiver RF Offset 1 |
| `AX5043_REG_MAXRFOFFSET0` | 0xF10B | 0x410B | Maximum Receiver RF Offset 0 |
| `AX5043_REG_FSKDMAX1` | 0xF10C | 0x410C | Four FSK Rx Maximum Deviation 1 |
| `AX5043_REG_FSKDMAX0` | 0xF10D | 0x410D | Four FSK Rx Maximum Deviation 0 |
| `AX5043_REG_FSKDMIN1` | 0xF10E | 0x410E | Four FSK Rx Minimum Deviation 1 |
| `AX5043_REG_FSKDMIN0` | 0xF10F | 0x410F | Four FSK Rx Minimum Deviation 0 |
| `AX5043_REG_AFSKSPACE1` | 0xF110 | 0x4110 | AFSK Space (0) Frequency 1 |
| `AX5043_REG_AFSKSPACE0` | 0xF111 | 0x4111 | AFSK Space (0) Frequency 0 |
| `AX5043_REG_AFSKMARK1` | 0xF112 | 0x4112 | AFSK Mark (1) Frequency 1 |
| `AX5043_REG_AFSKMARK0` | 0xF113 | 0x4113 | AFSK Mark (1) Frequency 0 |
| `AX5043_REG_AFSKCTRL` | 0xF114 | 0x4114 | AFSK Control |
| `AX5043_REG_AMPLFILTER` | 0xF115 | 0x4115 | Amplitude Filter |
| `AX5043_REG_FREQUENCYLEAK` | 0xF116 | 0x4116 | Baseband Frequency Recovery Loop Leakiness |
| `AX5043_REG_RXPARAMSETS` | 0xF117 | 0x4117 | Receiver Parameter Set Indirection |
| `AX5043_REG_RXPARAMCURSET` | 0xF118 | 0x4118 | Receiver Parameter Current Set |
| `AX5043_REG_AGCGAIN0` | 0xF120 | 0x4120 | AGC Speed |
| `AX5043_REG_AGCTARGET0` | 0xF121 | 0x4121 | AGC Target |
| `AX5043_REG_AGCAHYST0` | 0xF122 | 0x4122 | AGC Analog Hysteresis |
| `AX5043_REG_AGCMINMAX0` | 0xF123 | 0x4123 | AGC Analog Update Behaviour |
| `AX5043_REG_TIMEGAIN0` | 0xF124 | 0x4124 | Time Estimator Bandwidth |
| `AX5043_REG_DRGAIN0` | 0xF125 | 0x4125 | Data Rate Estimator Bandwidth |
| `AX5043_REG_PHASEGAIN0` | 0xF126 | 0x4126 | Phase Estimator Bandwidth |
| `AX5043_REG_FREQUENCYGAINA0` | 0xF127 | 0x4127 | Frequency Estimator Bandwidth A |
| `AX5043_REG_FREQUENCYGAINB0` | 0xF128 | 0x4128 | Frequency Estimator Bandwidth B |
| `AX5043_REG_FREQUENCYGAINC0` | 0xF129 | 0x4129 | Frequency Estimator Bandwidth C |
| `AX5043_REG_FREQUENCYGAIND0` | 0xF12A | 0x412A | Frequency Estimator Bandwidth D |
| `AX5043_REG_AMPLITUDEGAIN0` | 0xF12B | 0x412B | Amplitude Estimator Bandwidth |
| `AX5043_REG_FREQDEV10` | 0xF12C | 0x412C | Receiver Frequency Deviation 1 |
| `AX5043_REG_FREQDEV00` | 0xF12D | 0x412D | Receiver Frequency Deviation 0 |
| `AX5043_REG_FOURFSK0` | 0xF12E | 0x412E | Four FSK Control |
| `AX5043_REG_BBOFFSRES0` | 0xF12F | 0x412F | Baseband Offset Compensation Resistors |
| `AX5043_REG_AGCGAIN1` | 0xF130 | 0x4130 | AGC Speed |
| `AX5043_REG_AGCTARGET1` | 0xF131 | 0x4131 | AGC Target |
| `AX5043_REG_AGCAHYST1` | 0xF132 | 0x4132 | AGC Analog Hysteresis |
| `AX5043_REG_AGCMINMAX1` | 0xF133 | 0x4133 | AGC Analog Update Behaviour |
| `AX5043_REG_TIMEGAIN1` | 0xF134 | 0x4134 | Time Estimator Bandwidth |
| `AX5043_REG_DRGAIN1` | 0xF135 | 0x4135 | Data Rate Estimator Bandwidth |
| `AX5043_REG_PHASEGAIN1` | 0xF136 | 0x4136 | Phase Estimator Bandwidth |
| `AX5043_REG_FREQUENCYGAINA1` | 0xF137 | 0x4137 | Frequency Estimator Bandwidth A |
| `AX5043_REG_FREQUENCYGAINB1` | 0xF138 | 0x4138 | Frequency Estimator Bandwidth B |
| `AX5043_REG_FREQUENCYGAINC1` | 0xF139 | 0x4139 | Frequency Estimator Bandwidth C |
| `AX5043_REG_FREQUENCYGAIND1` | 0xF13A | 0x413A | Frequency Estimator Bandwidth D |
| `AX5043_REG_AMPLITUDEGAIN1` | 0xF13B | 0x413B | Amplitude Estimator Bandwidth |
| `AX5043_REG_FREQDEV11` | 0xF13C | 0x413C | Receiver Frequency Deviation 1 |
| `AX5043_REG_FREQDEV01` | 0xF13D | 0x413D | Receiver Frequency Deviation 0 |
| `AX5043_REG_FOURFSK1` | 0xF13E | 0x413E | Four FSK Control |
| `AX5043_REG_BBOFFSRES1` | 0xF13F | 0x413F | Baseband Offset Compensation Resistors |
| `AX5043_REG_AGCGAIN2` | 0xF140 | 0x4140 | AGC Speed |
| `AX5043_REG_AGCTARGET2` | 0xF141 | 0x4141 | AGC Target |
| `AX5043_REG_AGCAHYST2` | 0xF142 | 0x4142 | AGC Analog Hysteresis |
| `AX5043_REG_AGCMINMAX2` | 0xF143 | 0x4143 | AGC Analog Update Behaviour |
| `AX5043_REG_TIMEGAIN2` | 0xF144 | 0x4144 | Time Estimator Bandwidth |
| `AX5043_REG_DRGAIN2` | 0xF145 | 0x4145 | Data Rate Estimator Bandwidth |
| `AX5043_REG_PHASEGAIN2` | 0xF146 | 0x4146 | Phase Estimator Bandwidth |
| `AX5043_REG_FREQUENCYGAINA2` | 0xF147 | 0x4147 | Frequency Estimator Bandwidth A |
| `AX5043_REG_FREQUENCYGAINB2` | 0xF148 | 0x4148 | Frequency Estimator Bandwidth B |
| `AX5043_REG_FREQUENCYGAINC2` | 0xF149 | 0x4149 | Frequency Estimator Bandwidth C |
| `AX5043_REG_FREQUENCYGAIND2` | 0xF14A | 0x414A | Frequency Estimator Bandwidth D |
| `AX5043_REG_AMPLITUDEGAIN2` | 0xF14B | 0x414B | Amplitude Estimator Bandwidth |
| `AX5043_REG_FREQDEV12` | 0xF14C | 0x414C | Receiver Frequency Deviation 1 |
| `AX5043_REG_FREQDEV02` | 0xF14D | 0x414D | Receiver Frequency Deviation 0 |
| `AX5043_REG_FOURFSK2` | 0xF14E | 0x414E | Four FSK Control |
| `AX5043_REG_BBOFFSRES2` | 0xF14F | 0x414F | Baseband Offset Compensation Resistors |
| `AX5043_REG_AGCGAIN3` | 0xF150 | 0x4150 | AGC Speed |
| `AX5043_REG_AGCTARGET3` | 0xF151 | 0x4151 | AGC Target |
| `AX5043_REG_AGCAHYST3` | 0xF152 | 0x4152 | AGC Analog Hysteresis |
| `AX5043_REG_AGCMINMAX3` | 0xF153 | 0x4153 | AGC Analog Update Behaviour |
| `AX5043_REG_TIMEGAIN3` | 0xF154 | 0x4154 | Time Estimator Bandwidth |
| `AX5043_REG_DRGAIN3` | 0xF155 | 0x4155 | Data Rate Estimator Bandwidth |
| `AX5043_REG_PHASEGAIN3` | 0xF156 | 0x4156 | Phase Estimator Bandwidth |
| `AX5043_REG_FREQUENCYGAINA3` | 0xF157 | 0x4157 | Frequency Estimator Bandwidth A |
| `AX5043_REG_FREQUENCYGAINB3` | 0xF158 | 0x4158 | Frequency Estimator Bandwidth B |
| `AX5043_REG_FREQUENCYGAINC3` | 0xF159 | 0x4159 | Frequency Estimator Bandwidth C |
| `AX5043_REG_FREQUENCYGAIND3` | 0xF15A | 0x415A | Frequency Estimator Bandwidth D |
| `AX5043_REG_AMPLITUDEGAIN3` | 0xF15B | 0x415B | Amplitude Estimator Bandwidth |
| `AX5043_REG_FREQDEV13` | 0xF15C | 0x415C | Receiver Frequency Deviation 1 |
| `AX5043_REG_FREQDEV03` | 0xF15D | 0x415D | Receiver Frequency Deviation 0 |
| `AX5043_REG_FOURFSK3` | 0xF15E | 0x415E | Four FSK Control |
| `AX5043_REG_BBOFFSRES3` | 0xF15F | 0x415F | Baseband Offset Compensation Resistors |
| `AX5043_REG_MODCFGF` | 0xF160 | 0x4160 | Modulator Configuration F |
| `AX5043_REG_FSKDEV2` | 0xF161 | 0x4161 | FSK Deviation 2 |
| `AX5043_REG_FSKDEV1` | 0xF162 | 0x4162 | FSK Deviation 1 |
| `AX5043_REG_FSKDEV0` | 0xF163 | 0x4163 | FSK Deviation 0 |
| `AX5043_REG_MODCFGA` | 0xF164 | 0x4164 | Modulator Configuration A |
| `AX5043_REG_TXRATE2` | 0xF165 | 0x4165 | Transmitter Bitrate 2 |
| `AX5043_REG_TXRATE1` | 0xF166 | 0x4166 | Transmitter Bitrate 1 |
| `AX5043_REG_TXRATE0` | 0xF167 | 0x4167 | Transmitter Bitrate 0 |
| `AX5043_REG_TXPWRCOEFFA1` | 0xF168 | 0x4168 | Transmitter Predistortion Coefficient A 1 |
| `AX5043_REG_TXPWRCOEFFA0` | 0xF169 | 0x4169 | Transmitter Predistortion Coefficient A 0 |
| `AX5043_REG_TXPWRCOEFFB1` | 0xF16A | 0x416A | Transmitter Predistortion Coefficient B 1 |
| `AX5043_REG_TXPWRCOEFFB0` | 0xF16B | 0x416B | Transmitter Predistortion Coefficient B 0 |
| `AX5043_REG_TXPWRCOEFFC1` | 0xF16C | 0x416C | Transmitter Predistortion Coefficient C 1 |
| `AX5043_REG_TXPWRCOEFFC0` | 0xF16D | 0x416D | Transmitter Predistortion Coefficient C 0 |
| `AX5043_REG_TXPWRCOEFFD1` | 0xF16E | 0x416E | Transmitter Predistortion Coefficient D 1 |
| `AX5043_REG_TXPWRCOEFFD0` | 0xF16F | 0x416F | Transmitter Predistortion Coefficient D 0 |
| `AX5043_REG_TXPWRCOEFFE1` | 0xF170 | 0x4170 | Transmitter Predistortion Coefficient E 1 |
| `AX5043_REG_TXPWRCOEFFE0` | 0xF171 | 0x4171 | Transmitter Predistortion Coefficient E 0 |
| `AX5043_REG_PLLVCOI` | 0xF180 | 0x4180 | PLL VCO Current |
| `AX5043_REG_PLLVCOIR` | 0xF181 | 0x4181 | PLL VCO Current Readback |
| `AX5043_REG_PLLLOCKDET` | 0xF182 | 0x4182 | PLL Lock Detect Delay |
| `AX5043_REG_PLLRNGCLK` | 0xF183 | 0x4183 | PLL Autoranging Clock |
| `AX5043_REG_XTALCAP` | 0xF184 | 0x4184 | Crystal Oscillator Load Capacitance |
| `AX5043_REG_BBTUNE` | 0xF188 | 0x4188 | Baseband Tuning |
| `AX5043_REG_BBOFFSCAP` | 0xF189 | 0x4189 | Baseband Offset Compensation Capacitors |
| `AX5043_REG_PKTADDRCFG` | 0xF200 | 0x4200 | Packet Address Config |
| `AX5043_REG_PKTLENCFG` | 0xF201 | 0x4201 | Packet Length Configuration |
| `AX5043_REG_PKTLENOFFSET` | 0xF202 | 0x4202 | Packet Length Offset |
| `AX5043_REG_PKTMAXLEN` | 0xF203 | 0x4203 | Packet Maximum Length |
| `AX5043_REG_PKTADDR3` | 0xF204 | 0x4204 | Packet Address 3 |
| `AX5043_REG_PKTADDR2` | 0xF205 | 0x4205 | Packet Address 2 |
| `AX5043_REG_PKTADDR1` | 0xF206 | 0x4206 | Packet Address 1 |
| `AX5043_REG_PKTADDR0` | 0xF207 | 0x4207 | Packet Address 0 |
| `AX5043_REG_PKTADDRMASK3` | 0xF208 | 0x4208 | Packet Address Mask 3 |
| `AX5043_REG_PKTADDRMASK2` | 0xF209 | 0x4209 | Packet Address Mask 2 |
| `AX5043_REG_PKTADDRMASK1` | 0xF20A | 0x420A | Packet Address Mask 1 |
| `AX5043_REG_PKTADDRMASK0` | 0xF20B | 0x420B | Packet Address Mask 0 |
| `AX5043_REG_MATCH0PAT3` | 0xF210 | 0x4210 | Pattern Match Unit 0, Pattern 3 |
| `AX5043_REG_MATCH0PAT2` | 0xF211 | 0x4211 | Pattern Match Unit 0, Pattern 2 |
| `AX5043_REG_MATCH0PAT1` | 0xF212 | 0x4212 | Pattern Match Unit 0, Pattern 1 |
| `AX5043_REG_MATCH0PAT0` | 0xF213 | 0x4213 | Pattern Match Unit 0, Pattern 0 |
| `AX5043_REG_MATCH0LEN` | 0xF214 | 0x4214 | Pattern Match Unit 0, Pattern Length |
| `AX5043_REG_MATCH0MIN` | 0xF215 | 0x4215 | Pattern Match Unit 0, Minimum Match |
| `AX5043_REG_MATCH0MAX` | 0xF216 | 0x4216 | Pattern Match Unit 0, Maximum Match |
| `AX5043_REG_MATCH1PAT1` | 0xF218 | 0x4218 | Pattern Match Unit 1, Pattern 1 |
| `AX5043_REG_MATCH1PAT0` | 0xF219 | 0x4219 | Pattern Match Unit 1, Pattern 0 |
| `AX5043_REG_MATCH1LEN` | 0xF21C | 0x421C | Pattern Match Unit 1, Pattern Length |
| `AX5043_REG_MATCH1MIN` | 0xF21D | 0x421D | Pattern Match Unit 1, Minimum Match |
| `AX5043_REG_MATCH1MAX` | 0xF21E | 0x421E | Pattern Match Unit 1, Maximum Match |
| `AX5043_REG_TMGTXBOOST` | 0xF220 | 0x4220 | Transmit PLL Boost Time |
| `AX5043_REG_TMGTXSETTLE` | 0xF221 | 0x4221 | Transmit PLL (post Boost) Settling Time |
| `AX5043_REG_TMGRXBOOST` | 0xF223 | 0x4223 | Receive PLL Boost Time |
| `AX5043_REG_TMGRXSETTLE` | 0xF224 | 0x4224 | Receive PLL (post Boost) Settling Time |
| `AX5043_REG_TMGRXOFFSACQ` | 0xF225 | 0x4225 | Receive Baseband DC Offset Acquisition Time |
| `AX5043_REG_TMGRXCOARSEAGC` | 0xF226 | 0x4226 | Receive Coarse AGC Time |
| `AX5043_REG_TMGRXAGC` | 0xF227 | 0x4227 | Receiver AGC Settling Time |
| `AX5043_REG_TMGRXRSSI` | 0xF228 | 0x4228 | Receiver RSSI Settling Time |
| `AX5043_REG_TMGRXPREAMBLE1` | 0xF229 | 0x4229 | Receiver Preamble 1 Timeout |
| `AX5043_REG_TMGRXPREAMBLE2` | 0xF22A | 0x422A | Receiver Preamble 2 Timeout |
| `AX5043_REG_TMGRXPREAMBLE3` | 0xF22B | 0x422B | Receiver Preamble 3 Timeout |
| `AX5043_REG_RSSIREFERENCE` | 0xF22C | 0x422C | RSSI Offset |
| `AX5043_REG_RSSIABSTHR` | 0xF22D | 0x422D | RSSI Absolute Threshold |
| `AX5043_REG_BGNDRSSIGAIN` | 0xF22E | 0x422E | Background RSSI Averaging Time Constant |
| `AX5043_REG_BGNDRSSITHR` | 0xF22F | 0x422F | Background RSSI Relative Threshold |
| `AX5043_REG_PKTCHUNKSIZE` | 0xF230 | 0x4230 | Packet Chunk Size |
| `AX5043_REG_PKTMISCFLAGS` | 0xF231 | 0x4231 | Packet Controller Miscellaneous Flags |
| `AX5043_REG_PKTSTOREFLAGS` | 0xF232 | 0x4232 | Packet Controller Store Flags |
| `AX5043_REG_PKTACCEPTFLAGS` | 0xF233 | 0x4233 | Packet Controller Accept Flags |
| `AX5043_REG_GPADCCTRL` | 0xF300 | 0x4300 | General Purpose ADC Control |
| `AX5043_REG_GPADCPERIOD` | 0xF301 | 0x4301 | GPADC Sampling Period |
| `AX5043_REG_GPADC13VALUE1` | 0xF308 | 0x4308 | GPADC13 Value 1 |
| `AX5043_REG_GPADC13VALUE0` | 0xF309 | 0x4309 | GPADC13 Value 0 |
| `AX5043_REG_LPOSCCONFIG` | 0xF310 | 0x4310 | Low Power Oscillator Calibration Configuration |
| `AX5043_REG_LPOSCSTATUS` | 0xF311 | 0x4311 | Low Power Oscillator Calibration Status |
| `AX5043_REG_LPOSCKFILT1` | 0xF312 | 0x4312 | Low Power Oscillator Calibration Filter Constant High Byte |
| `AX5043_REG_LPOSCKFILT0` | 0xF313 | 0x4313 | Low Power Oscillator Calibration Filter Constant Low Byte |
| `AX5043_REG_LPOSCREF1` | 0xF314 | 0x4314 | Low Power Oscillator Reference Frequency High Byte |
| `AX5043_REG_LPOSCREF0` | 0xF315 | 0x4315 | Low Power Oscillator Reference Frequency Low Byte |
| `AX5043_REG_LPOSCFREQ1` | 0xF316 | 0x4316 | Low Power Oscillator Frequency Tuning High Byte |
| `AX5043_REG_LPOSCFREQ0` | 0xF317 | 0x4317 | Low Power Oscillator Frequency Tuning Low Byte |
| `AX5043_REG_LPOSCPER1` | 0xF318 | 0x4318 | Low Power Oscillator Period High Byte |
| `AX5043_REG_LPOSCPER0` | 0xF319 | 0x4319 | Low Power Oscillator Period Low Byte |
| `AX5043_REG_DACVALUE1` | 0xF330 | 0x4330 | DAC Value 1 |
| `AX5043_REG_DACVALUE0` | 0xF331 | 0x4331 | DAC Value 0 |
| `AX5043_REG_DACCONFIG` | 0xF332 | 0x4332 | DAC Configuration |
| `AX5043_REG_0xF00` | 0xFF00 | 0x4F00 |  |
| `AX5043_REG_POWCTRL1` | 0xFF08 | 0x4F08 | Power Control 1 |
| `AX5043_REG_0xF0C` | 0xFF0C | 0x4F0C |  |
| `AX5043_REG_REF` | 0xFF0D | 0x4F0D | Reference |
| `AX5043_REG_XTALOSC` | 0xFF10 | 0x4F10 | Crystal Oscillator Control |
| `AX5043_REG_XTALAMPL` | 0xFF11 | 0x4F11 | Crystal Oscillator Amplitude Control |
| `AX5043_REG_0xF18` | 0xFF18 | 0x4F18 |  |
| `AX5043_REG_0xF1C` | 0xFF1C | 0x4F1C |  |
| `AX5043_REG_0xF21` | 0xFF21 | 0x4F21 |  |
| `AX5043_REG_0xF22` | 0xFF22 | 0x4F22 |  |
| `AX5043_REG_0xF23` | 0xFF23 | 0x4F23 |  |
| `AX5043_REG_0xF26` | 0xFF26 | 0x4F26 |  |
| `AX5043_REG_0xF30` | 0xFF30 | 0x4F30 |  |
| `AX5043_REG_0xF31` | 0xFF31 | 0x4F31 |  |
| `AX5043_REG_0xF32` | 0xFF32 | 0x4F32 |  |
| `AX5043_REG_0xF33` | 0xFF33 | 0x4F33 |  |
| `AX5043_REG_0xF34` | 0xFF34 | 0x4F34 |  |
| `AX5043_REG_0xF35` | 0xFF35 | 0x4F35 |  |
| `AX5043_REG_0xF44` | 0xFF44 | 0x4F44 |  |
| `AX5043_REG_MODCFGP` | 0xFF5F | 0x4F5F | Modulator Configuration P |

