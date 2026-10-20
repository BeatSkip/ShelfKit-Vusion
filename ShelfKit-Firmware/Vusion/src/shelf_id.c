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
