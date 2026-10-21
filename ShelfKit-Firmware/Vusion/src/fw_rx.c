/**
 * @file fw_rx.c
 * @brief Firmware receiver, see fw_rx.h and Documentation/ota-update.md
 *
 * The tag is the only part that knows the SPI flash layout (shelfota.h) and the
 * CRC; the bootloader merely re-checks them before it programs the application.
 *
 * BEGIN erases the header sector (dropping any previous, unconsumed update) and
 * every sector the image will need, so no chunk ever has to erase. That erase
 * happens inside BEGIN, i.e. right after the link layer acknowledged that frame,
 * which is why the host waits a moment before the first chunk.
 *
 * END commits only if every byte arrived and the CRC matches: the header - magic
 * included - is written last, in one 16-byte page program. A transfer that is
 * interrupted anywhere leaves no magic behind, so the bootloader keeps booting
 * the application that is still in flash.
 *
 * There is no data buffer: chunks are written straight through to the flash and
 * folded into the CRC as they arrive.
 */

#include <libmf.h>
#include <libmfwtimer.h>

#include "flash.h"
#include "fw_rx.h"
#include "shelfhw.h"
#include "shelf_id.h"
#include "shelfmsg.h"
#include "shelfota.h"
#include "spi.h"

#define FW_TIMEOUT_TICKS   (10u * SHELFHW_TICKS_PER_S)

static uint8_t __xdata active;
static uint16_t __xdata total;      /* image length the host announced */
static uint16_t __xdata got;        /* bytes written so far */
static uint16_t __xdata crc_calc;
static uint16_t __xdata crc_want;
static uint16_t __xdata last_rx;
static uint16_t __xdata id;

static const uint8_t __xdata * __xdata msg;
static uint8_t __xdata msg_len;

/* Back to the reset vector: the bootloader's jump when it is installed, the
 * application's own when it is not. Internal RAM is too tight for anything
 * fancier, and this is exactly what a reset is. */
static void cpu_reset(void)
{
    __asm
    ljmp    0x0000
    __endasm;
}

static void abort_transfer(void)
{
    active = 0;
}

static uint16_t __xdata sectors;
static uint16_t __xdata sector_i;
static uint8_t __xdata header[OTA_HDR_BYTES];
static uint16_t __xdata off;
static uint8_t __xdata n;

static void on_begin(void)
{

    total = (uint16_t)msg[1] | ((uint16_t)msg[2] << 8);
    crc_want = (uint16_t)msg[3] | ((uint16_t)msg[4] << 8);
    if (total < 4 || total > OTA_MAX_IMAGE) {
        log_puts("fw bad len\r\n");
        abort_transfer();
        return;
    }

    log_puts("fw begin len=");
    log_dec(total);
    log_puts(" crc=");
    log_hex16(crc_want);
    log_nl();

    spi_init();
    extflash_release_powerdown();
    /* the old update (if any) goes first: from here on there is no magic, so a
     * crash mid-transfer can never make the bootloader flash half an image */
    extflash_erase(OTA_HDR_ADDR, (uint16_t)OTA_SECTOR);
    sectors = ota_sectors_for(total);
    for (sector_i = 0; sector_i < sectors; sector_i++)
        extflash_erase(OTA_IMAGE_ADDR + (uint32_t)sector_i * OTA_SECTOR, (uint16_t)OTA_SECTOR);

    crc_calc = OTA_CRC_INIT;
    got = 0;
    active = 1;
}

static void on_chunk(void)
{
    off = (uint16_t)msg[1] | ((uint16_t)msg[2] << 8);
    n = (uint8_t)(msg_len - SM_FW_HDR);

    if (!active || n == 0)
        return;
    if (off != got || (uint16_t)(got + n) > total) {
        /* a repeat of an earlier chunk (lost ACK) or a gap: the CRC at END
         * decides, so just ignore it */
        return;
    }
    extflash_write(OTA_IMAGE_ADDR + got, msg + SM_FW_HDR, n);
    crc_calc = ota_crc16(msg + SM_FW_HDR, n, crc_calc);
    got += n;
}

static void on_end(void)
{
    if (!active) {
        log_puts("fw end, not active\r\n");
        return;
    }
    if (got != total) {
        log_puts("fw short got=");
        log_dec(got);
        log_puts("/");
        log_dec(total);
        log_nl();
        abort_transfer();
        return;
    }
    if (crc_calc != crc_want) {
        log_puts("fw crc bad ");
        log_hex16(crc_calc);
        log_puts("/");
        log_hex16(crc_want);
        log_nl();
        abort_transfer();
        return;
    }

    ota_header_build(header, total, crc_want);
    extflash_write(OTA_HDR_ADDR, header, OTA_HDR_BYTES);
    log_puts("fw stored, resetting\r\n");
    /* the radio/flash are done: reset into the bootloader, which finds the magic */
    cpu_reset();
}

uint8_t fw_rx_data(const uint8_t __xdata *payload, uint8_t len)
{
    if (len < 1)
        return 0;
    msg = payload;
    msg_len = len;

    switch (payload[0]) {
    case SM_OP_FW_BEGIN:
        if (len < 5)
            return 1;
        on_begin();
        break;
    case SM_OP_FW_CHUNK:
        if (len <= SM_FW_HDR)
            return 1;
        on_chunk();
        break;
    case SM_OP_FW_END:
        on_end();
        break;
    case SM_OP_WIPE:
        log_puts("factory reset\r\n");
        (void)shelf_id_factory_reset();
        cpu_reset();
        break;
    case SM_OP_SET_ID:
        if (len < 3)
            return 1;
        id = (uint16_t)msg[1] | ((uint16_t)msg[2] << 8);
        if (shelf_id_assign(id)) {
            log_puts("id set ");
            log_hex16(id);
            log_nl();
        } else {
            log_puts("id set FAILED\r\n");
        }
        break;
    default:
        return 0;
    }
    last_rx = (uint16_t)wtimer0_curtime();
    return 1;
}

uint8_t fw_rx_active(void)
{
    if (active && (uint16_t)((uint16_t)wtimer0_curtime() - last_rx) > FW_TIMEOUT_TICKS)
        abort_transfer();
    return active;
}
