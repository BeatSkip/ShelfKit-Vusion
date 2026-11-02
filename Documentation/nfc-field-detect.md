# NFC field detect on the tag

> **Status: parked.** `SHELF_NFC_POLL 0`, `SHELF_NFC_RAIL_HOLD 0`, `SHELF_NFC_PROBE 0`.
> Everything below is what was learned and what is left. The transport (bit-banged mode
> 1, UID read, register access) works and is kept; the unresolved part is physical - the
> field-detect line floats and oscillates whenever the NFC chip has no supply.


The tag can poll when a reader is held against the label: the NFC chip asserts a pin, the
AX8052 takes an interrupt, pulses the blue LED and checks in within a second instead of
waiting out the interval. This note records what is done in firmware, what the chip
requires, and what is still missing.

## The pin

`FM11NT0X1D` pin 10, **`WIP_FD`** - "The flag of EEPROM's write/erase by the contactless
interface, or the flag of field detection. **Low-effective**", type **OD** (open drain).

On this board it is wired to **PB3**, which doubles as the bootloader's BOOT strap (the
serial adapter's DTR). It is the same pin the tag firmware reads as `NFC_FD`.

Open drain means the pin can only pull low; the idle level comes from a pull-up, so the
firmware sets `DIRB` bit 3 = input and `PORTB` bit 3 = 1 (AND9349/D pin table: `0 1` is
"Z, Pull-Up"). With that, "a reader arrived" is a **falling edge**.

## Firmware side (done)

| piece | where |
|---|---|
| pin: PB3 input + weak pull-up | `shelfhw_init()` |
| falling edge: `EXTIRQ` bits 5:4 = 11, bit 6 = 0 (Port B.3), `IE.2` | `shelfhw_nfc_arm()` |
| handler: set a flag, disable `IE.2` (one shot) | `nfc_irq()`, vector `0x13` |
| on the flag: blue LED pulse, `nfc field` log, poll in 1 s | `main()` |
| re-arm after every poll | `listen_cb()` |

`EXTIRQ` is used rather than the pin-change interrupt because the latter fires on both
edges, and its change flag has no documented acknowledge on this part - the first attempt
re-fired continuously.

`SHELF_NFC_POLL 0` disables all of it and leaves PB3 untouched.

## Chip side

The pin is a dual-purpose output/input: out of reset it reports the EEPROM
write-in-progress flag (WIP), not a field. It has to be switched before the firmware's
falling-edge interrupt on PB3 can ever fire.

The register and value come from Fudan's own FM11NT081D driver:

```c
#define NFC_CFG  0x0D                  /* NFC configuration register */
fm11nt08_writereg(NFC_CFG, 0x03);      /* bits 5:4 = 00: field detect */
port_wkup_interrupt_init(fd_port_io, 1, ...);   /* falling edge */
```

### The bus was the real problem

Two earlier attempts read `ff` on every framing. Both causes were on the bus, not in the
register:

1. **The chip shares the switched rail with the serial flash** (PA5 / U4), and
   `shelf_id_boot()` leaves that rail off - so the chip was unpowered while being read.
   `nfc_probe()` now calls `extflash_power_up()` first and `extflash_power_down()` after.
2. **Mode 0 against a mode-1 slave.** The FM11NT081DS contact interface only implements
   mode 1 (CPOL=0, CPHA=1) or 3; the AX8052's SPI unit is mode 0 because the IL0373 panel
   on the same bus needs that. A mode-0 master timing into a mode-1 slave is a race, so
   `nfc_cfg.c` now **bit-bangs** SCK/MOSI and reads MISO from `PINC`, then hands the bus
   back with `spi_init()`. This is the approach the earlier ShelfKit firmware used, where
   it was verified against real tags on this board.

The third detail from that firmware: the chip needs **>= 100 us after SSN goes low** before
the first clock, which the hardware-SPI attempt never gave it.

`nfc_probe()` therefore reads the chip's **UID** from EEPROM address 0x000 (9 bytes: SN0-2,
BCC0, SN3-6, BCC1) and checks the two ISO/IEC 14443-3 check bytes:

```
nfc uid 04 A2 B3 19 C4 D5 E6 F7 8C ok
```

### The line oscillates when the chip is unpowered

On hardware the interrupt fires every ~250 ms with `EXTIRQ = 0x30` (bits 5:4 = `11`,
falling edge - so the mode is right) and the chip reporting `NFC_CFG = 0x00`, i.e. already
in field-detect mode. The line is therefore really changing: an unpowered open-drain
output behind a weak pull-up is a floating node, and this one oscillates.

**The chip is unpowered when the tag sleeps.** It shares the switched rail (PA5 / U4, and
`PWR_USE_U4` is 1, so the pin really is driven), and `shelf_id_boot()` turns it off - so
between polls the field-detect output has no supply and floats. `SHELF_NFC_RAIL_HOLD` (on)
keeps that rail up so the chip can actually drive the pin; the cost is the standby current
of everything else on it. Turn it off if that standby turns out to be too expensive, and
the feature then only works while something else happens to be holding the rail.

`nfc_cfg_fd()` writes nothing that matters - the chip needs no configuration. Three guards
keep a floating line from costing anything:

- `nfc_irq()` ignores anything that is not a low level (FD is active low);
- after `SHELF_NFC_BURST_MAX` (3) events in one poll cycle the tag logs
  `nfc noisy, ignoring until next poll` and stops reacting until `listen_cb()` resets the
  count, so a storm costs a handful of events per 120 s instead of 4 per second.

`ok` means the whole path works - rail, chip select, bit-banged mode 1, EEPROM read - which
is a far stronger signal than a register readback. `bad` or `ff ff ...` means it is still
not talking.

### The register command

The SPI command encoding is datasheet table 4-4: the first byte is the command and the
register address is its low four bits.

| operation | command byte |
|---|---|
| write register | `000_0_<reg>` |
| read register | `001_0_<reg>` |
| write EEPROM | `010_<A9:A8>` |
| read EEPROM | `011_<A9:A8>` |

EEPROM reads already worked with the `011_` form; register reads did not, because the
I2C driver's 16-bit address (`0xFF, 0xF0|reg`) is not what the `...DS` part expects - it
was answering `ff` to a command byte it does not implement. `nfc_reg_read()` /
`nfc_reg_write()` now use `0x20|reg` and `0x00|reg`.

The configuration block in EEPROM (pages `E3h`-`E6h`, bytes `0x38C`-`0x39B`) is a
different thing and is *not* where the pin is selected: its `ACCESS` byte (page `E4h`
byte 0, address `0x390`) holds PROT, CFGLOCK, NFC_CNT_EN and AUTHLIM, with bits 5:4
unused/other. The pin selection lives in the contact-interface register file, register
`NFC_CFG` = `0x0D`, bits 5:4 = `00` for field detect.

## Testing without a serial port

The blue LED is the indicator: one pulse per reader arrival, on a battery board with
nothing plugged in. With a serial adapter attached, DTR drives PB3, so anything observed
then is a property of the cable, not of the NFC chip.

## Resuming this work

The three switches in `shelf_config.h` and what each one costs:

| switch | on | off |
|---|---|---|
| `SHELF_NFC_POLL` | falling-edge interrupt on PB3, LED pulse, poll on arrival | PB3 untouched |
| `SHELF_NFC_RAIL_HOLD` | switched rail stays up so the chip can drive FD | rail cycles as before |
| `SHELF_NFC_PROBE` | UID + configuration dump at boot (read-only) | silent |

What is already known, so none of it is rediscovered:

1. **The bus works.** Bit-banged mode 1 on PC1/PC2/PC3, `PINC` for MISO, >=100 us after
   SSN low, command `011_<A9:A8>` + address for EEPROM. The UID reads with both ISO/IEC
   14443-3 check bytes correct.
2. **The command table** (datasheet 4-4): `000_0_<reg>` write register, `001_0_<reg>` read
   register, `010_` / `011_` EEPROM. The I2C driver's `0xFF, 0xF0|reg` is not understood by
   the `...DS` part - that was the `ff` on every register read.
3. **The chip needs no configuration.** `NFC_CFG` (0x0D) reads `0x00`, bits 5:4 = `00` =
   field detect, out of the box.
4. **`EXTIRQ` works**: bits 5:4 = `11` is a falling edge and its default pin is PB3.
5. **The blocker is electrical.** With the rail off the pin has only the AX8052's weak
   pull-up, and it oscillated at ~4 Hz; every edge also wakes the tag, which measured
   7.4 mA. Options for next time: hold the rail on (costs the standby of the flash and the
   panel's supply), add an external pull-up on PB3, or power the NFC chip from the
   unswitched rail.
6. **Test with the serial adapter removed.** Its DTR is on PB3 (the BOOT strap), so a tag
   on a cable is not measuring the NFC chip at all.
