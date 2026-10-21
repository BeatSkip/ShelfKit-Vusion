/**
 * @file shelf_id.c
 * @brief The tag's wireless identity: stored in SPI flash, see shelf_id.h
 *
 * One sector, one 10-byte record, erased before every write. A write is only
 * accepted after reading it back, so a tag never starts using an id it would
 * lose on the next reset.
 *
 * The random id at first boot is what keeps two fresh tags apart: with a fixed
 * "unassigned" value they would both poll as the same source and neither the hub
 * nor the server could tell them apart, nor address one of them. A 16-bit random
 * id on the production net makes that collision a ~1-in-65536 event instead of
 * a certainty, and the tag keeps it until something assigns a proper one.
 */

#include <libmf.h>
#include "flash.h"
#include "shelf_config.h"
#include "shelf_id.h"
#include "shelfhw.h"
#include "shelfid.h"
#include "shelflink.h"
#include "shelfota.h"
#include "spi.h"

static uint8_t __xdata rec[SHELFID_BYTES];
static uint16_t __xdata id;
static uint8_t __xdata flags;

/* Sectors the OTA image window spans; above 0xA700 nothing is ever written. */
#define WIPE_IMAGE_SECTORS  ((uint16_t)((OTA_MAX_IMAGE + OTA_SECTOR - 1) / OTA_SECTOR))

/* The flash only belongs to this firmware once it holds an identity record.
 * Anything else may be left over from another firmware on a used tag: a stale
 * OTA marker at 0x0000 (which would make the bootloader overwrite this very
 * application on the next reset), an old image, a previous owner's data.
 * So the first boot wipes every sector this firmware owns before writing its
 * own record - the identity sector included, since its content is exactly what
 * we have just decided not to trust. */
static void wipe_owned_sectors(void) __reentrant
{
    uint16_t i;

    extflash_erase(OTA_HDR_ADDR, (uint16_t)OTA_SECTOR);
    extflash_erase(OTA_RESERVED_ADDR, (uint16_t)OTA_SECTOR);
    for (i = 0; i < WIPE_IMAGE_SECTORS; i++)
        extflash_erase(OTA_IMAGE_ADDR + (uint32_t)i * OTA_SECTOR, (uint16_t)OTA_SECTOR);
    extflash_erase(SHELFID_ADDR, (uint16_t)SHELFID_SECTOR);
}

static void store(uint16_t node_id, uint8_t set_flags) __reentrant
{
    shelfid_build(rec, node_id, set_flags);
    extflash_erase(SHELFID_ADDR, (uint16_t)SHELFID_SECTOR);
    extflash_write(SHELFID_ADDR, rec, SHELFID_BYTES);
}

uint16_t shelf_id_boot(void) __reentrant
{
    spi_init();
    extflash_release_powerdown();
    extflash_read(SHELFID_ADDR, rec, SHELFID_BYTES);

    if (shelfid_parse(rec, &id, &flags)) {
        log_puts(flags & SHELFID_FLAG_ASSIGNED ? "id " : "id? ");
        log_hex16(id);
        log_nl();
        return id;
    }

#if SHELF_WIPE_FIRST_BOOT
    /* an unreadable record means this flash is not ours yet: start from a
     * known-empty state instead of inheriting someone else's */
    wipe_owned_sectors();
    log_puts("flash wiped\r\n");
#endif

    /* nothing stored yet (or unreadable): pick one and keep it */
    do {
        id = shelfhw_random();
    } while (id < 2 || id == SL_NODE_HUB);
    store(id, 0);
    log_puts("id? ");
    log_hex16(id);
    log_puts(" new\r\n");
    return id;
}

uint8_t shelf_id_factory_reset(void) __reentrant
{
    spi_init();
    extflash_release_powerdown();
    wipe_owned_sectors();
    return 1;
}

uint8_t shelf_id_assign(uint16_t node_id) __reentrant
{
    if (node_id < 2 || node_id == SL_NODE_HUB)
        return 0;

    store(node_id, SHELFID_FLAG_ASSIGNED);

    extflash_read(SHELFID_ADDR, rec, SHELFID_BYTES);
    if (!shelfid_parse(rec, &id, &flags) || id != node_id)
        return 0;

    /* the record is on flash and verified: point the radio at it */
    sl_set_local(id, SHELF_NET_ID);
    return 1;
}
