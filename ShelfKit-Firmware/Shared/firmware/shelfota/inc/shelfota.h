/**
 * @file shelfota.h
 * @brief OTA firmware image layout in the tag's SPI flash, shared by app and bootloader
 *
 * The tag receives a new firmware as a contiguous binary and stores it in its SPI
 * NOR flash. The header sector carries a magic sequence and the metadata the
 * bootloader needs; the image itself starts at a 4 KiB boundary so that erasing
 * the header never touches the payload.
 *
 *   SPI offset 0x000000, sector 0 (4 KiB): header, 16 bytes used
 *     0..3   magic "SKFW"
 *     4      format version (OTA_VERSION)
 *     5      flags (OTA_FLAG_COMMITTED)
 *     6..7   image length in bytes, little endian
 *     8..9   CRC-16/CCITT of the image bytes, little endian
 *     10..11 CRC-16 of bytes 0..9
 *     12..15 zero
 *   SPI offset 0x001000, sector 1: the tag's identity record (shelfid.h) - not
 *                                 part of an update, and never erased by one
 *   SPI offset 0x002000, sector 2: reserved for future persistent storage (see
 *                                 OTA_RESERVED_ADDR); an update never touches it
 *   SPI offset 0x003000: the image, byte 0 = internal flash address 0
 *
 * The magic is written last (at END, after the CRC of the received image has
 * matched), so an interrupted transfer leaves no magic and the bootloader boots
 * the old application. The bootloader erases sector 0 after a successful flash,
 * which is what makes the update run exactly once.
 *
 * The image is the application's raw .hex turned into a binary: byte 0..2 are its
 * reset jump (0x02, entry hi, entry lo), which the bootloader moves into its
 * jump-vector slot instead of programming over its own reset vector.
 *
 * The CRC is CRC-16/CCITT (poly 0x1021, init 0xFFFF) over the image bytes only -
 * the header has its own CRC so a torn header is rejected rather than trusted.
 */

#ifndef SHELFOTA_H
#define SHELFOTA_H

#include <libmftypes.h>

#define OTA_MAGIC_0      'S'
#define OTA_MAGIC_1      'K'
#define OTA_MAGIC_2      'F'
#define OTA_MAGIC_3      'W'

#define OTA_VERSION         1
#define OTA_FLAG_COMMITTED  0x01

#define OTA_HDR_BYTES       16
#define OTA_HDR_ADDR        0x000000UL   /* SPI flash, sector 0 */
#define OTA_ID_ADDR         0x001000UL   /* SPI flash, sector 1: the identity record */
#define OTA_RESERVED_ADDR   0x002000UL   /* SPI flash, sector 2: kept free on purpose */
#define OTA_IMAGE_ADDR      0x003000UL   /* SPI flash: first sector after the fixed ones */
#define OTA_SECTOR          4096UL

/* Largest image we accept: the window between the last fixed sector (0x3000) and
 * the bootloader's jump vector (0xD7FE), i.e. 43,006 bytes, minus the two bytes the
 * vector occupies: 0xD7FE - 0x3000 = 0xA7FE, rounded down to a whole page of
 * slack. The tag's own application may be larger when flashed over the wire; as an
 * OTA image it has to fit here, so the build script warns when it does not. */
#define OTA_MAX_IMAGE       0xA7F0UL

#define OTA_CRC_INIT        0xFFFF

/** CRC-16/CCITT over a RAM buffer, continuing from @p crc (pass OTA_CRC_INIT). */
uint16_t ota_crc16(const uint8_t *data, uint16_t len, uint16_t crc) __reentrant;

/** Fill @p buf (OTA_HDR_BYTES) with a committed header. */
void ota_header_build(uint8_t *buf, uint16_t length, uint16_t crc) __reentrant;

/** Check a header's magic, version and own CRC; fills length/crc on success. */
uint8_t ota_header_parse(const uint8_t *buf, uint16_t *length, uint16_t *crc) __reentrant;

/** Bytes of SPI flash a sector-wise erase must cover for an image of @p length. */
uint16_t ota_sectors_for(uint16_t length) __reentrant;

#endif /* SHELFOTA_H */
