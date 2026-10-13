/**
 * @file img_rx.c
 * @brief Image receiver, see img_rx.h
 *
 * The panel controller is the frame buffer: BEGIN opens the panel and selects the
 * black/white plane, every CHUNK is shifted out as it arrives, and END refreshes.
 * The hub ACKs each frame before this code runs, so BEGIN (panel reset) and END
 * (refresh, ~15 s) block the main loop; the host waits for them.
 */

#include <libmfwtimer.h>
#include "epd.h"
#include "shelfhw.h"
#include "shelfmsg.h"
#include "spi.h"
#include "img_rx.h"

#define IMG_TIMEOUT_TICKS   (10u * SHELFHW_TICKS_PER_S)

static uint8_t __xdata active;
static uint8_t __xdata plane;
static uint16_t __xdata expect;        /* next offset in the current plane */
static uint16_t __xdata last_rx;      /* low 16 bits of wtimer0: wraps after 102 s, the timeout is 10 s */

static void abort_transfer(void)
{
    active = 0;
    shelfhw_led(SHELFHW_LED_WHITE, 0);
}

static void on_begin(void)
{
    log_puts("img begin\r\n");
    spi_init();
    epd_open();
    epd_stream_begin(0x10);
    plane = SM_PLANE_BW;
    expect = 0;
    active = 1;
    shelfhw_led(SHELFHW_LED_WHITE, 1);
}

/* Internal RAM is nearly full on the tag: the message and the working values live in XRAM */
static const uint8_t __xdata * __xdata msg;
static uint8_t __xdata msg_len;
static uint8_t __xdata n;
static uint16_t __xdata off;

static void on_chunk(void)
{
    n = (uint8_t)(msg_len - SM_IMG_HDR);
    off = (uint16_t)msg[2] | ((uint16_t)msg[3] << 8);
    if (!active || n == 0)
        return;

    if (msg[1] != plane) {
        /* Only the step from a complete black/white plane to the red one is valid */
        if (plane != SM_PLANE_BW || msg[1] != SM_PLANE_RED || expect != EPD_PLANE_BYTES)
            return;
        epd_stream_begin(0x13);
        plane = SM_PLANE_RED;
        expect = 0;
    }

    /* A repeat of an earlier chunk (lost ACK) or a gap: ignore, END will tell */
    if (off != expect || expect + n > EPD_PLANE_BYTES)
        return;

    epd_stream_write(msg + SM_IMG_HDR, n);
    expect += n;
}

static void on_end(void)
{
    if (active && plane == SM_PLANE_RED && expect == EPD_PLANE_BYTES) {
        log_puts("img refresh\r\n");
        epd_refresh();
        epd_sleep();
        log_puts("img done\r\n");
    } else {
        log_puts("img incomplete, plane=");
        log_dec(plane);
        log_puts(" at=");
        log_dec(expect);
        log_nl();
    }
    abort_transfer();
}

uint8_t img_rx_data(const uint8_t __xdata *payload, uint8_t len)
{
    if (len < 1)
        return 0;
    msg = payload;
    msg_len = len;

    switch (payload[0]) {
    case SM_OP_IMG_BEGIN:
        on_begin();
        break;
    case SM_OP_IMG_CHUNK:
        if (len <= SM_IMG_HDR)
            return 1;
        on_chunk();
        break;
    case SM_OP_IMG_END:
        on_end();
        break;
    default:
        return 0;
    }
    last_rx = (uint16_t)wtimer0_curtime();
    return 1;
}

uint8_t img_rx_active(void)
{
    if (active && (uint16_t)((uint16_t)wtimer0_curtime() - last_rx) > IMG_TIMEOUT_TICKS)
        abort_transfer();
    return active;
}
