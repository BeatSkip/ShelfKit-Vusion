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
 * Take an id handed to the tag over the air: store it, read it back to verify,
 * then re-point the radio's address at it. Returns 1 only when all three
 * happened, so the tag never reports an id it would not survive a reset with.
 */
uint8_t shelf_id_assign(uint16_t node_id) __reentrant;

#endif /* SHELF_ID_H */
