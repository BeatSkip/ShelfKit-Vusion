/**
 * @file shelfota.c
 * @brief OTA header packing and the CRC, see shelfota.h
 *
 * Deliberately hardware-free and small: the same code runs in the tag (which
 * builds a header after receiving an image) and in the bootloader (which parses
 * it before touching the application). Keeping the CRC here also means both ends
 * agree on it by construction rather than by copy-paste.
 */

#include "shelfota.h"

uint16_t ota_crc16(const uint8_t *data, uint16_t len, uint16_t crc) __reentrant
{
    while (len--) {
        uint8_t bit;
        crc ^= (uint16_t)(*data++) << 8;
        for (bit = 0; bit < 8; bit++)
            crc = (crc & 0x8000u) ? (uint16_t)((crc << 1) ^ 0x1021u) : (uint16_t)(crc << 1);
    }
    return crc;
}

void ota_header_build(uint8_t *buf, uint16_t length, uint16_t crc) __reentrant
{
    uint8_t i;

    buf[0] = OTA_MAGIC_0;
    buf[1] = OTA_MAGIC_1;
    buf[2] = OTA_MAGIC_2;
    buf[3] = OTA_MAGIC_3;
    buf[4] = OTA_VERSION;
    buf[5] = OTA_FLAG_COMMITTED;
    buf[6] = (uint8_t)length;
    buf[7] = (uint8_t)(length >> 8);
    buf[8] = (uint8_t)crc;
    buf[9] = (uint8_t)(crc >> 8);
    crc = ota_crc16(buf, 10, OTA_CRC_INIT);
    buf[10] = (uint8_t)crc;
    buf[11] = (uint8_t)(crc >> 8);
    for (i = 12; i < OTA_HDR_BYTES; i++)
        buf[i] = 0;
}

uint8_t ota_header_parse(const uint8_t *buf, uint16_t *length, uint16_t *crc) __reentrant
{
    uint16_t want, got;

    if (buf[0] != OTA_MAGIC_0 || buf[1] != OTA_MAGIC_1
        || buf[2] != OTA_MAGIC_2 || buf[3] != OTA_MAGIC_3)
        return 0;
    if (buf[4] != OTA_VERSION || !(buf[5] & OTA_FLAG_COMMITTED))
        return 0;
    want = (uint16_t)buf[10] | ((uint16_t)buf[11] << 8);
    got = ota_crc16(buf, 10, OTA_CRC_INIT);
    if (want != got)
        return 0;
    *length = (uint16_t)buf[6] | ((uint16_t)buf[7] << 8);
    *crc = (uint16_t)buf[8] | ((uint16_t)buf[9] << 8);
    if (*length < 4 || *length > OTA_MAX_IMAGE)
        return 0;
    return 1;
}

uint16_t ota_sectors_for(uint16_t length) __reentrant
{
    return (uint16_t)((length + (uint16_t)OTA_SECTOR - 1) / (uint16_t)OTA_SECTOR);
}
