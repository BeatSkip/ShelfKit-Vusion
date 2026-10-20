/**
 * @file img_rx.c
 * @brief Image receiver, see img_rx.h
 *
 * The panel controller is the frame buffer: BEGIN powers the panel rail, resets the
 * panel and selects the black/white plane, every CHUNK is shifted out as it arrives,
 * and END refreshes. The hub ACKs each frame before this code runs, so BEGIN (panel
 * reset) and END (refresh, ~15 s) block the main loop; the host waits for them.
 *
 * END logs what the panel did: "img done busy=1 14.6s" means the IL0373 really ran a
 * refresh waveform. busy=0 means it never reacted (no supply, no reset pulse), busy=2
 * means the waveform was still running when the wait ran out - in that last case the
 * panel is deliberately left powered instead of being put to sleep mid-refresh.
 */

#include <libmf.h>
#include <libmfwtimer.h>
#include "epd.h"
#include "pwr.h"
#include "shelfhw.h"
#include "shelfmsg.h"
#include "spi.h"
#include "img_rx.h"

#define IMG_TIMEOUT_TICKS   (10u * SHELFHW_TICKS_PER_S)

static uint8_t __xdata active;
static uint8_t __xdata plane;
static uint16_t __xdata expect;        /* next offset in the current plane */
static uint16_t __xdata last_rx;      /* low 16 bits of wtimer0: wraps after 102 s, the timeout is 10 s */

static uint8_t __xdata dbg_chunks;

static void abort_transfer(void)
{
    active = 0;
}

/* The panel is not on the always-on rail: transistor U4 (PA5, see pwr.h) gates
 * it, and the boot demo that is proven on this board drives that line on before
 * it touches the panel. The tag firmware used to leave PA5 floating, so the
 * IL0373 received a full init sequence and a complete frame with no supply
 * behind it and the refresh did nothing at all. */
static void panel_power_on(void)
{
    uint8_t i;

    pwr_init();             /* PA5 becomes an output, driven off */
    pwr_on();               /* ... then to its on level (low) */
    for (i = 0; i < 100; i++)   /* let the rail ramp before the reset pulse */
        delay(1000);
}

static void on_begin(void)
{
    log_puts("img begin\r\n");
    /* Green = "an image is starting". One short flash: the white LED used to be
     * held on for the whole transfer (minutes), which warmed the panel and
     * showed up on the frame. */
    shelfhw_led_pulse(SHELFHW_LED_GREEN, SHELFHW_LED_PULSE_MS);
    panel_power_on();
    spi_init();
    dbg_chunks = 0;
    epd_open();
    epd_stream_begin(0x10);
    plane = SM_PLANE_BW;
    expect = 0;
    active = 1;
    log_puts("img panel open\r\n");
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
    if (dbg_chunks < 3) {
        dbg_chunks++;
        log_puts("chunk plane=");
        log_dec(msg[1]);
        log_puts(" off=");
        log_dec(off);
        log_puts(" n=");
        log_dec(n);
        log_puts(" active=");
        log_dec(active);
        log_nl();
    }
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
    uint8_t st;
    uint16_t t0, dt;

    if (active && plane == SM_PLANE_RED && expect == EPD_PLANE_BYTES) {
        log_puts("img refresh\r\n");
        t0 = (uint16_t)wtimer0_curtime();
        st = epd_refresh();
        dt = (uint16_t)((uint16_t)wtimer0_curtime() - t0);
        log_puts("img done busy=");
        log_dec(st);
        log_puts(" ");
        log_dec((uint16_t)(dt / SHELFHW_TICKS_PER_S));
        log_putc('.');
        log_dec((uint16_t)(((uint16_t)(dt % SHELFHW_TICKS_PER_S)) * 10u / SHELFHW_TICKS_PER_S));
        log_puts("s\r\n");
        /* Only power the panel down once it says it is finished: cutting the
         * rail (or sending POF) in the middle of a waveform leaves the old
         * image on the glass. A panel still busy is left to complete. */
        if (st == EPD_BUSY_DONE) {
            epd_sleep();
            /* The glass holds the image without power. Leaving the rail (PA5)
             * driven on costs current for nothing until the next image. */
            pwr_off();
        }
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
