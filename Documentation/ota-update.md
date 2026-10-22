# Wireless firmware update (OTA)

A tag receives a new application over the wireless link, stores it in its own SPI
flash, resets, and the bootloader programs the application from that flash and
starts it. The transfer lives entirely in the application; the bootloader only
notices a magic sequence and copies — it has no radio code at all.

```
 host                         hub                          tag                    bootloader
 ────                         ───                          ───                    ──────────
 ota-send.py ── DATA frames ──► relay ──► POLL/DATA ──► write chunks to SPI flash
 (BEGIN/CHUNK/END)                                      check CRC, write header
                                                        with magic, reset ───────► magic? yes
                                                                                   parse header
                                                                                   verify CRC
                                                                                   erase application
                                                                                   program from flash
                                                                                   clear magic
                                                                                   jump into the app
```

Nothing about the hub changes: firmware frames are DATA frames like image chunks,
so the existing reliable relay (one frame in flight, ACK per frame) carries them.

## SPI flash layout — `ShelfKit-Firmware/Shared/firmware/shelfota/inc/shelfota.h`

| SPI offset | Contents |
|---|---|
| `0x000000` | header, 16 bytes used: magic `SKFW`, format version, flags, image length (LE), image CRC-16 (LE), header CRC-16 (LE) |
| `0x001000` | the tag's identity record - see [tag-identity.md](tag-identity.md); never erased by an update |
| `0x002000` | **reserved** for future persistent storage (`OTA_RESERVED_ADDR`); an update never touches it |
| `0x003000` | the image, byte 0 = internal flash address 0 |

A tag that has never seen this firmware may still carry a *valid* header from
something else, which would make the bootloader install that stale image at the next
reset. The first boot therefore erases the header sector (along with the identity,
the reserved sector and the whole image window) before it stores its own identity —
see [tag-identity.md](tag-identity.md#what-happens-to-a-used-tags-flash).

The bootloader checks sector 0 on **every reset**, before it does anything else
(including the auto-run of the application). Three things it needs for that check
to work, all of which were wrong at first:

1. **Order.** The auto-run used to come first, so a normal reset jumped into the
   old application and the update was only seen when the boot button (SW5/PB3) was
   held. The OTA check now runs before the auto-run.
2. **The flash rail** (PA5/U4) must be driven on, or the header reads back `0xFF`
   and looks like "no update". The bootloader drives it on and clears `ANALOGA`
   bit 5, since the vendor startup configures PA5 as an analog pin.
3. **The hardware SPI must be off.** The application resets with `ljmp 0x0000`,
   which does not reset peripherals, and it leaves the SPI master enabled
   (`SPMODE = 0x01`); the bootloader's bit-banged read then fights the SPI
   controller. `ota_spi_begin()` disables the SPI first.

See [tag-identity.md](tag-identity.md#the-flashs-switched-rail) for the rail.

The header lives in its own 4 KiB sector so erasing it never touches the image,
and the magic is written **last**, after the CRC of everything received has
matched. An interrupted transfer therefore leaves no magic and the bootloader
boots the application that is still there.

## Protocol — `shelfmsg.h`

| Payload | Meaning |
|---|---|
| `[4, len_lo, len_hi, crc_lo, crc_hi]` | `SM_OP_FW_BEGIN`: the tag erases the header sector and every sector the image needs |
| `[5, off_lo, off_hi, data…]` | `SM_OP_FW_CHUNK`: up to 28 bytes at that offset; accepted only when the offset is exactly what the tag already holds |
| `[6]` | `SM_OP_FW_END`: verify length + CRC, write the committed header, reset |

The CRC is CRC-16/CCITT (poly `0x1021`, init `0xFFFF`) over the image bytes, so
the sender, the tag and the bootloader share one definition (`ota_crc16`).

## Application side — `Vusion/src/fw_rx.c`

- No buffers: each chunk goes straight to the flash and is folded into the CRC.
- `BEGIN` erases up to ~0.3 s worth of sectors, so the sender waits before the
  first chunk; a repeated chunk (lost ACK) is ignored because offsets are absolute.
- `END` commits only when every byte arrived and the CRC matches, then jumps back
  to the reset vector — which is the bootloader's own vector when it is installed.
- A transfer that stalls for 10 s is abandoned (the radio has no such thing as a
  half-open connection).

## Bootloader side — `Bootloader/src/main.c`

Deliberately plain: bit-banged SPI, one 32-byte buffer, no radio.

1. Read the 16-byte header from SPI flash; parse magic, version, header CRC.
2. Verify the image CRC **before erasing anything** — a corrupt image must never
   cost the working firmware.
3. Take the image's first three bytes (`02 hi lo`), put `hi`/`lo` into the
   jump-vector slot at `0xD7FE` (low byte first, which is what `run_application()`
   reads), and skip those three bytes when programming.
4. `erase_app()`, then program the image 2 bytes at a time from address 2 upward
   (addresses 0–2 are the bootloader's own reset vector and stay untouched; the
   word at 2 carries a 0xFF that programs nothing).
5. Erase the SPI header sector — that is what makes the update run once.
6. Fall through to the normal path: `jmp_vector` is now valid, so the new
   application starts.

Serial flashing is unchanged, and it still works if the OTA image is broken.

## Memory map after this change

| Region | Range | Use |
|---|---|---|
| application | `0x0000–0xD7FD` | up to 55,038 B in flash; as an OTA image it must fit the `0x3000–0xD7FE` window, i.e. 43,006 B |
| jump vector | `0xD7FE–0xD7FF` | the application entry, written when one is flashed |
| bootloader | `0xD800–0xFBFF` | 9,216 B region, 8,314 B used, 902 B free |
| reserved | `0xFC00–0xFFFF` | not in the bootloader's CRC range; nothing links into it |

The bootloader moved from `0xE400` to `0xD800` for this feature: at `0xE400` it had
109 bytes free, the OTA path needed ~2.3 KB (bit-bang SPI, the program loop, and
SDCC's reentrant support for the shared CRC/header code).

A tag that has no bootloader yet gets one with the merged HEX from
`build-all.py` (`vusion-full-*.hex`), which contains both images and already has the
application's entry in the jump-vector slot — see
[ShelfKit-Firmware/Bootloader/README.md](../ShelfKit-Firmware/Bootloader/README.md#installing-the-bootloader-and-the-application-at-once).

### The reset vector is part of the bootloader

The bootloader only runs if `0x0000` holds `ljmp 0xD838`. That is what
`Release/vusion-full-*.hex` writes, together with the application entry at
`0xD7FE`. Flashing the application hex on its own puts `ljmp 0x021B` at `0x0000`,
which starts the application directly: the OTA image is stored in SPI flash and
never applied, because nothing ever looks at it. The build script's "Tag:" line
always names the full image.

### Indications

The bootloader shows nothing on a normal boot (the LEDs are driven off before
anything else, so a stray level from the application cannot leave one lit behind
the panel). Only an update is indicated, all with 500 ms pulses:

| LED | when |
|---|---|
| blue | a committed image was found and is being programmed |
| green | programming finished, the new application is about to boot |
| red | programming failed (`OTA ERR crc` / `entry` / `erase`), the old app still boots |

### Which firmware is on the board

Both boards print a capability marker at the end of their boot banner:
`*** ShelfKit hub, node 0001 net 5a dump=1`. `dump=1` means the build can forward tag
DATA payloads, which the flash read-back needs; a hub without it will relay the frames
but drop their bytes, and the server says so rather than showing an empty dump.

## Using it

From the server: **Fleet** → click the tag → **Firmware update** → pick the HEX → **Reflash**.

From a shell:

```
python ShelfKit-Firmware/Tooling/build-all.py                  # Release/vusion-<date>-<hash>.hex
python ShelfKit-Firmware/Tooling/ota-send.py Release/vusion-…​.hex --addr 0100 -p COM4
```

`ota-send.py` converts the Intel HEX to the binary the tag wants (gap-filling with
0xFF), prints the entry address and CRC, then sends BEGIN, 1451 chunks and END.
A 40 KB image is ~2 minutes at the current radio settings. The tag's log shows
`fw begin len=… crc=…`, then `fw stored, resetting`, and after the reboot the
bootloader prints `OTA image len=… crc=…` and `OTA ok, booting`.

`--dry-run` parses and checksums without touching the radio — worth doing before
every real transfer. It also refuses an image that would not fit the window
(`0x3000–0xD7FE`, 43,006 bytes).

### Headroom

The image window is 43,006 bytes and the application is now **31,694**, so there are
**11,312 bytes** free. Until recently there were 64: `src/epd_image.c` — a
compiled-in boot logo worth 11,248 bytes — was linked into both radio images while
nothing referenced it any more (the boot demo it belonged to was replaced by the
shelf-link main). It was deleted from both targets, which also shrank the hub from
37,775 to 26,210 bytes.

### The reset vector is part of the bootloader

The bootloader only runs if `0x0000` holds `ljmp 0xD838`. That is what
`Release/vusion-full-*.hex` writes, together with the application entry at
`0xD7FE`. Flashing the application hex on its own puts `ljmp 0x021B` at `0x0000`,
which starts the application directly: the OTA image is stored in SPI flash and
never applied, because nothing ever looks at it. The build script's "Tag:" line
always names the full image.

### Indications

The bootloader shows nothing on a normal boot (the LEDs are driven off before
anything else, so a stray level from the application cannot leave one lit behind
the panel). Only an update is indicated, all with 500 ms pulses:

| LED | when |
|---|---|
| blue | a committed image was found and is being programmed |
| green | programming finished, the new application is about to boot |
| red | programming failed (`OTA ERR crc` / `entry` / `erase`), the old app still boots |

### Which firmware is on the board

Both boards print a capability marker at the end of their boot banner:
`*** ShelfKit hub, node 0001 net 5a dump=1`. `dump=1` means the build can forward tag
DATA payloads, which the flash read-back needs; a hub without it will relay the frames
but drop their bytes, and the server says so rather than showing an empty dump.

## Using it

From the server: **Fleet** → click the tag → **Firmware update** → pick the HEX → **Reflash**.

From a shell:

```
python ShelfKit-Firmware/Tooling/build-all.py                  # Release/vusion-<date>-<hash>.hex
python ShelfKit-Firmware/Tooling/ota-send.py Release/vusion-…​.hex --addr 0100 -p COM4
```

`ota-send.py` converts the Intel HEX to the binary the tag wants (gap-filling with
0xFF), prints the entry address and CRC, then sends BEGIN, 1451 chunks and END.
A 40 KB image is ~2 minutes at the current radio settings. The tag's log shows
`fw begin len=… crc=…`, then `fw stored, resetting`, and after the reboot the
bootloader prints `OTA image len=… crc=…` and `OTA ok, booting`.

`--dry-run` parses and checksums without touching the radio — worth doing before
every real transfer. It also refuses an image that would not fit the window
(`0x3000–0xD7FE`, 43,006 bytes).

### Headroom

The image window is 43,006 bytes and the application is 42,117, so there are
**889 bytes** left (635 under the sender's 0xA700 cap). That is thin — the next
feature that needs a kilobyte will not fit in an OTA image even though it fits in
the tag's flash.

The cheapest way to buy space back, when it comes to that: `src/epd_image.c` is a
compile-time boot picture worth **11,248 bytes** of the image (two 5,624-byte
planes, `_epd_image_bw` at `0x7158` and `_epd_image_red` at `0x8750` in the current
map). Painting it from the panel's own default, or storing it in the SPI flash,
would free a quarter of the window. Trimming the bootloader or moving it up
(`0xD7FE` → `0xD9FE`) only buys ~512 B and shrinks it to a few hundred spare.

## Not verified on hardware yet

- The whole path is untested on a real tag: no transfer has been sent, no image
  flashed. The build is verified (all three targets, sizes above) and the host
  tool's parser and CRC are verified (check value `0x29B1`), but that is all.
- `run_application()` reads the jump vector with `MOVX`, i.e. through the external
  data space, while the vector is written as flash. This is the reference
  bootloader's own mechanism; it needs to be confirmed on the chip before anything
  relies on it.
- Erase/program timings of the actual SPI flash part, and whether the 2-minute
  transfer holds up over the air, are unknown.

## Known gaps

- **No target identity in the image.** The sender only checks that the file starts
  with a reset jump and fits; `ota-send.py` would happily accept a hub image for a
  tag. A build-time marker byte in the header would fix that.
- No resume (BEGIN always erases), no rollback to the previous image, no signature.
- No progress feedback from the tag during the transfer beyond per-frame ACKs.
