/**
 * @file shelf_id.h
 * @brief The tag's own wireless identity: where it is stored and when it changes
 */

#ifndef SHELF_ID_H
#define SHELF_ID_H

#include <libmftypes.h>

/**
 * The id this tag should run with. Reads the SPI flash record; when there is
 * none (brand new tag, or a record that failed its CRC) it generates a random
 * id and stores that, flagged as not yet assigned, so it stays stable across
 * resets and updates.
 */
uint16_t shelf_id_boot(void) __reentrant;

/**
 * Erase every SPI flash sector this firmware owns (OTA header, identity,
 * reserved, the whole image window). The next boot then finds no identity, so
 * it generates a random id and starts from a clean slate.
 */
uint8_t shelf_id_factory_reset(void) __reentrant;

/**
 * Take an id handed to the tag over the air: store it, read it back to verify,
 * then re-point the radio's address at it. Returns 1 only when all three
 * happened, so the tag never reports an id it would not survive a reset with.
 */
uint8_t shelf_id_assign(uint16_t node_id) __reentrant;

/*
 * Configuration record: SPI flash sector 2 (OTA_RESERVED_ADDR, 0x002000), which neither
 * a firmware update nor an id change touches. A factory reset erases it.
 *     0..3   magic "SKCF"
 *     4      format version (1)
 *     5..6   idle check-in interval in seconds, little endian
 *     7      zero
 *     8..9   CRC-16 (the OTA one) of bytes 0..7
 * A missing or damaged record means "use the built-in default" (SHELF_POLL_IDLE_S).
 */

/** Read the configuration record. Call once at boot, after shelf_id_boot(). */
void shelf_cfg_boot(void) __reentrant;

/** The idle check-in interval in seconds: the stored one, or the default. */
uint16_t shelf_cfg_poll_s(void);

/**
 * Store a new idle interval (SM_OP_SET_POLL), read it back, and only then start using
 * it. Returns 1 when the tag now runs with it and will still have it after a reset.
 */
uint8_t shelf_cfg_set_poll(uint16_t seconds) __reentrant;

#endif /* SHELF_ID_H */
