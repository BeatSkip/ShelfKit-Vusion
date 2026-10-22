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

/* shelfhw_random() is a xorshift seeded from the wake-up timer, and at boot that
 * timer has barely moved: every tag - and every boot - would draw the same
 * "random" id (0x8283 on this build). The one per-device number available is the
 * trimmed 20 MHz FRC frequency the calibration just measured, so it goes into the
 * mix, together with a little timer jitter. */
static uint16_t fresh_id(void) __reentrant
{
    uint16_t x;
    uint8_t i;

    delay(1000);                    /* let the wake-up timer move */
    x = (uint16_t)(wtimer0_curtime() ^ ((uint16_t)FRCOSCFREQ1 << 8));
    for (i = 0; i < 4; i++)
        x ^= shelfhw_random();
    if (x < 2 || x == SL_NODE_HUB)
        x = (uint16_t)(0x4100u | (x & 0x3Fu));   /* never 0, 1 or the hub */
    return x;
}

/* An erased sector reads as 0xFF; an all-0xFF record means "nothing here yet",
 * which is not the same as "something here that is broken". */
static uint8_t record_is_blank(void) __reentrant
{
    uint8_t i;

    for (i = 0; i < SHELFID_BYTES; i++)
        if (rec[i] != 0xFF)
            return 0;
    return 1;
}

static uint8_t store(uint16_t node_id, uint8_t set_flags) __reentrant
{
    shelfid_build(rec, node_id, set_flags);
    if (!extflash_erase(SHELFID_ADDR, (uint16_t)SHELFID_SECTOR))
        return 0;
    return extflash_write(SHELFID_ADDR, rec, SHELFID_BYTES);
}

uint16_t shelf_id_boot(void) __reentrant
{
    uint8_t flash_alive;

    extflash_power_up();
    spi_init();
    extflash_release_powerdown();
    delay(2000);                    /* tPUW / tRES1: the first read after power-up
                                     * or release-from-power-down can come back bad */

    {
        uint8_t jid[3];
        extflash_read_jedec_id(jid);
        flash_alive = (jid[0] != 0xFF || jid[1] != 0xFF || jid[2] != 0xFF) &&
                      (jid[0] != 0x00 || jid[1] != 0x00 || jid[2] != 0x00);
        log_puts("flash jedec ");
        log_hex8(jid[0]);
        log_hex8(jid[1]);
        log_hex8(jid[2]);
        log_nl();
    }

    extflash_read(SHELFID_ADDR, rec, SHELFID_BYTES);
    if (!shelfid_parse(rec, &id, &flags)) {
        delay(2000);                /* a single bad read must not cost the id */
        extflash_read(SHELFID_ADDR, rec, SHELFID_BYTES);
    }

    if (shelfid_parse(rec, &id, &flags)) {
        log_puts(flags & SHELFID_FLAG_ASSIGNED ? "id " : "id? ");
        log_hex16(id);
        log_nl();
        extflash_power_down();
        return id;
    }

    if (!flash_alive) {
        /* The chip is not answering. It is not "blank": a wipe or a store here
         * would either no-op or, worse, erase a pending OTA image. Keep the flash
         * untouched and run on a volatile id until the next reset. */
        id = fresh_id();
        log_puts("flash dead, id? ");
        log_hex16(id);
        log_puts(" new (volatile)\r\n");
        extflash_power_down();
        return id;
    }

#if SHELF_WIPE_FIRST_BOOT
    if (record_is_blank()) {
        /* nothing of ours and nothing of anyone else's: no need to erase 13
         * sectors on a factory-fresh tag */
        log_puts("flash blank\r\n");
    } else {
        /* a record that does not parse means this flash is not ours (used tag):
         * start from a known-empty state instead of inheriting the leftovers */
        wipe_owned_sectors();
        log_puts("flash wiped\r\n");
    }
#endif

    id = fresh_id();
    if (!store(id, 0))
        log_puts("id not stored, flash busy\r\n");
    log_puts("id? ");
    log_hex16(id);
    log_puts(" new\r\n");
    extflash_power_down();
    return id;
}

uint8_t shelf_id_factory_reset(void) __reentrant
{
    extflash_power_up();
    spi_init();
    extflash_release_powerdown();
    wipe_owned_sectors();
    extflash_power_down();
    return 1;
}

uint8_t shelf_id_assign(uint16_t node_id) __reentrant
{
    if (node_id < 2 || node_id == SL_NODE_HUB)
        return 0;

    extflash_power_up();
    spi_init();
    extflash_release_powerdown();

    if (!store(node_id, SHELFID_FLAG_ASSIGNED)) {
        log_puts("id set FAILED, flash busy\r\n");
        extflash_power_down();
        return 0;
    }

    extflash_read(SHELFID_ADDR, rec, SHELFID_BYTES);
    if (!shelfid_parse(rec, &id, &flags) || id != node_id) {
        /* reading back what is actually there is the whole difference between
         * "the write was lost" and "the record is unreadable" */
        log_puts("id set FAILED, read back ");
        log_hex16((uint16_t)rec[6] | ((uint16_t)rec[7] << 8));
        log_puts(" magic ");
        log_hex8(rec[0]);
        log_hex8(rec[1]);
        log_nl();
        extflash_power_down();
        return 0;
    }

    /* the record is on flash and verified: point the radio at it */
    sl_set_local(id, SHELF_NET_ID);
    extflash_power_down();
    return 1;
}
