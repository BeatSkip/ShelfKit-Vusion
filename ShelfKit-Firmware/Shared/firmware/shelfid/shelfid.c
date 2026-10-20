/**
 * @file shelfid.c
 * @brief The identity record: layout, packing and its CRC (see shelfid.h)
 *
 * Nothing here touches hardware - the same record could be read by a bootloader
 * or a production jig. The CRC is the OTA one (shelfota.h): one definition for
 * everything this firmware stores in the SPI flash.
 */

#include "shelfid.h"
#include "shelfota.h"

void shelfid_build(uint8_t *buf, uint16_t node_id, uint8_t flags) __reentrant
{
    uint16_t crc;

    buf[0] = SHELFID_MAGIC_0;
    buf[1] = SHELFID_MAGIC_1;
    buf[2] = SHELFID_MAGIC_2;
    buf[3] = SHELFID_MAGIC_3;
    buf[4] = SHELFID_VERSION;
    buf[5] = flags;
    buf[6] = (uint8_t)node_id;
    buf[7] = (uint8_t)(node_id >> 8);
    crc = ota_crc16(buf, 8, OTA_CRC_INIT);
    buf[8] = (uint8_t)crc;
    buf[9] = (uint8_t)(crc >> 8);
}

uint8_t shelfid_parse(const uint8_t *buf, uint16_t *node_id, uint8_t *flags) __reentrant
{
    uint16_t want, got;

    if (buf[0] != SHELFID_MAGIC_0 || buf[1] != SHELFID_MAGIC_1
        || buf[2] != SHELFID_MAGIC_2 || buf[3] != SHELFID_MAGIC_3)
        return 0;
    if (buf[4] != SHELFID_VERSION)
        return 0;
    want = (uint16_t)buf[8] | ((uint16_t)buf[9] << 8);
    got = ota_crc16(buf, 8, OTA_CRC_INIT);
    if (want != got)
        return 0;
    *node_id = (uint16_t)buf[6] | ((uint16_t)buf[7] << 8);
    *flags = buf[5];
    if (*node_id < 2)
        return 0;                   /* 0 and 1 (the hub) are not tag ids */
    return 1;
}
