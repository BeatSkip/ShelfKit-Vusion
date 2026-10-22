# Tag identity

A tag's wireless node id is **data, not part of the firmware image** — otherwise
one image could not fit the whole fleet, which is what the OTA update is for.

## Where it lives

SPI flash sector 1, in the gap the OTA update never touches:

| SPI offset | Contents | Erased by |
|---|---|---|
| `0x000000` | OTA header (magic, length, CRC) | app on `BEGIN`, bootloader after flashing |
| `0x001000` | **identity record**: magic `SKID`, version, flags, node id (LE), CRC-16 | only when the id is (re)assigned |
| `0x002000` | reserved for future persistent storage — deliberately empty, never touched | — |
| `0x003000` | OTA image | app on `BEGIN` |

The record is checked by its own CRC. A torn write, or a flash sector that never
held a record, is treated as "no identity" rather than trusted.

## The flash's switched rail

The SPI flash is not on plain VDD: it sits on a rail switched by PA5 (transistor
U4, active low) that only the panel power sequence brings up. Left off, the chip
reads back as all `0xFF`, which looks exactly like a blank identity and a missing
OTA header. Both firmwares now power the rail before every flash access:

- the **application** calls `extflash_power_up()`/`_down()` around boot, assign,
  factory reset, flash read-back and an OTA transfer (`SHELF_FLASH_POWER_ON`);
- the **bootloader** drives PA5 low before it reads the OTA header, or it would
  see `0xFF` and skip the update.

Two consequences of getting this wrong, both seen on hardware:

1. every reset regenerates the identity (the record reads blank) and
2. a pushed OTA never applies (the bootloader reads a blank header).

As a safety net, the boot now probes the flash first (`flash jedec XXYYZZ` on the
log). If the chip does not answer, the tag does **not** wipe or store anything - a
dead flash is not an empty one, and wiping here would destroy a pending update -
it just runs on a volatile id for that session and logs `flash dead`.

## What happens to a used tag's flash

A tag whose SPI flash still holds someone else's data is not trusted: when no
identity record parses (a blank sector, a torn write, or a flash from another
firmware), the first boot **erases every sector this firmware owns** before it
generates the random id (`SHELF_WIPE_FIRST_BOOT` in `shelf_config.h`, ~0.5 s once):

| sector | why it has to go |
|---|---|
| `0x0000` OTA header | a leftover magic here would make the bootloader overwrite this application on the next reset |
| `0x1000` identity | its contents are exactly what was just judged untrusted |
| `0x2000` reserved | future storage, unknown content |
| `0x3000`+ image window | a stale image nobody will ever want |

Sectors above the image window are left alone: they are not this firmware's.

## Life of an id

1. **First boot** (`shelf_id.c`): no usable record → a random 16-bit id is picked
   from `shelfhw_random()`, stored with the `assigned` flag clear, and used. The
   log says `id? 3F2A new`; a record from a previous boot says `id 0100`.
2. **First connection**: the tag polls normally, so the hub prints
   `POLL src=3f2a …` and the server sees it like any other tag.
3. **Assignment**: `Tooling/set-id.py 3F2A 0100` sends one DATA frame
   (`SM_OP_SET_ID`). The tag writes the record, **reads it back to verify**, and
   only then re-points the radio's hardware address (`sl_set_local`), so the next
   poll carries the new id. A tag never reports an id it would not survive a reset
   with.
4. **Firmware update**: the image sector erase starts at `0x3000` and the
   bootloader only writes internal flash, so the record and the id are untouched.

## Why random instead of 0

**The id must survive a reboot**, so the boot path is deliberately suspicious of
its own reading: the record is read twice (with a delay, since the first read after
power-up can come back bad) before the flash is declared untrusted, and a blank
sector — nothing written yet — is not a reason to wipe 13 sectors. Getting that wrong
was visible on hardware as an id that "reverted": a failed parse at boot led to a
fresh id, the random source was seeded with a timer that had not moved yet, so it
drew the *same* value every time, and overwrote the id that had just been assigned.

The random source now mixes the trimmed 20 MHz FRC frequency the boot calibration
measured (chip-specific) with timer jitter, so two tags - and two boots - differ.

`id 0` is a valid, *specific* address — not a broadcast — so every unprovisioned
tag would poll as the same source. The hub could not tell them apart, and a
`SET_ID` frame to `0x0000` would be accepted by all of them.

A random id makes that a birthday problem instead of a certainty: 1 in 65,536 per
pair (~2 % with 50 unprovisioned tags in range, ~7 % with 100). If two tags do
collide, the server sees one source polling with the same id twice, and assigning
each of them a proper id still works because both accept the frame — so treat a
duplicate as "assign the next one first".

## Inspecting it

`Tooling/flash-read.py` reads back what is actually on the chip, so a "the id does
not stick" report can be settled with evidence instead of guesswork: it prints the
identity record (`id`, `assigned`/`random`, CRC ok or BAD), the OTA header (pending
update or blank, header CRC), and whether the reserved sector is in use, then saves
the raw bytes. Empty sectors read as `0xFF`, so `--range 0:0x3000` is a complete
picture of the metadata in one file.

## What is deliberately not here

- **No separate provisioning net.** The tag uses the production net from the
  start, so the hub needs no mode and nothing changes on the radio side (the net
  id is a byte in the packet's address field, matched by hardware — same
  frequency, same airtime).
- **Assignment is one frame, one tag at a time.** The server's Fleet drawer
  (**Wireless identity** → **Assign**, empty field = lowest free id) and
  `Tooling/set-id.py` both send the same `SM_OP_SET_ID` frame; neither batches.
- **No id change while a poll is in flight**: the assignment frame's ACK is sent
  by the link layer before the handler runs, exactly like image and OTA frames.
- **Untested on hardware**, like the OTA path it sits next to.
