/**
 * @file shelfid.h
 * @brief The tag's wireless identity record, shared by the tag firmware
 *
 * A tag's node id must survive firmware updates, so it cannot live in the
 * application image: one image has to fit every tag. It sits in its own SPI
 * flash sector instead, between the update header and the image, which nothing
 * else erases.
 *
 *   SPI offset 0x001000, sector 0 (4 KiB), 10 bytes used
 *     0..3   magic "SKID"
 *     4      format version
 *     5      flags: SHELFID_FLAG_ASSIGNED when the id came from the server,
 *            0 when it was generated at first boot
 *     6..7   node id, little endian
 *     8..9   CRC-16 of bytes 0..7
 *
 * A record that fails its CRC is treated as absent: the tag picks a new random
 * id rather than trusting half a record.
 */

#ifndef SHELFID_H
#define SHELFID_H

#include <libmftypes.h>

#define SHELFID_MAGIC_0     'S'
#define SHELFID_MAGIC_1     'K'
#define SHELFID_MAGIC_2     'I'
#define SHELFID_MAGIC_3     'D'

#define SHELFID_VERSION     1
#define SHELFID_FLAG_ASSIGNED 0x01

#define SHELFID_BYTES       10
#define SHELFID_ADDR        0x001000UL
#define SHELFID_SECTOR      4096UL

/** Fill a record for @p node_id. */
void shelfid_build(uint8_t *buf, uint16_t node_id, uint8_t flags) __reentrant;

/** Check magic, version and CRC; fills node_id/flags. 1 = usable record. */
uint8_t shelfid_parse(const uint8_t *buf, uint16_t *node_id, uint8_t *flags) __reentrant;

#endif /* SHELFID_H */
