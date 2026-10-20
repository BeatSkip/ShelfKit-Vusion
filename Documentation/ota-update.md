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

## Using it

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
