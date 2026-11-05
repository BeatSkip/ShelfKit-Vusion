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
#include "eco_rx.h"

/* The hub can be busy with another tag's poll or a retry for a few seconds, so a
 * short gap is normal mid-transfer. 10 s aborted a half-sent image when the link
 * hiccuped; 30 s still gives up on a link that has really gone away. */
#define IMG_TIMEOUT_TICKS   (30u * SHELFHW_TICKS_PER_S)

static uint8_t __xdata active;
static uint8_t __xdata plane;
static uint16_t __xdata expect;        /* next offset in the current plane */
static uint16_t __xdata last_rx;      /* low 16 bits of wtimer0: wraps after 102 s, the timeout is 10 s */

static uint8_t __xdata dbg_chunks;
static uint16_t __xdata zgot;          /* compressed bytes of this plane received in order */

/* The refresh runs from a 100 ms timer instead of a blocking wait: while the waveform
 * runs (12-15 s) the radio is parked and the MCU sleeps between ticks. The panel alone
 * draws ~8 mA; the receiver (10 mA) and a spinning MCU (4 mA) used to triple that. */
#define REFRESH_TICK        SHELFHW_MS_TO_TICKS(100)
#define REFRESH_START_N     30      /* 3 s for BUSY to leave idle */
#define REFRESH_DONE_N      600     /* 60 s for the waveform: cold panels are slow */
static uint8_t __xdata refreshing;
static uint8_t __xdata r_seen;      /* BUSY has left idle */
static uint8_t __xdata r_parked;
static uint8_t __xdata panel_up;    /* rail on / panel not yet in deep sleep */
static uint16_t __xdata r_n;
static uint16_t __xdata r_t0;
static uint16_t __xdata r_dt;
static struct wtimer_desc __xdata refresh_timer;

static void panel_off(void)
{
    epd_sleep();                /* POF, then deep sleep */
    pwr_off();                  /* and cut the rail: nothing leaks into the idle panel */
    panel_up = 0;
}

static void abort_transfer(void)
{
    active = 0;
    /* an abandoned or incomplete transfer used to leave the panel powered (booster on)
     * until the next image */
    if (panel_up && !refreshing)
        panel_off();
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
    if (refreshing)
        return;                 /* the panel is busy with the last image */
    log_puts("img begin\r\n");
    /* Green = "an image is starting". One short flash: the white LED used to be
     * held on for the whole transfer (minutes), which warmed the panel and
     * showed up on the frame. */
    shelfhw_led_pulse(SHELFHW_LED_GREEN, SHELFHW_LED_PULSE_MS);
    panel_power_on();
    panel_up = 1;
    spi_init();
    dbg_chunks = 0;
    epd_open();
    epd_stream_begin(0x10);
    plane = SM_PLANE_BW;
    expect = 0;
    zgot = 0;
    active = 1;
    log_puts("img panel open\r\n");
}

/* Internal RAM is nearly full on the tag: the message and the working values live in XRAM */
static const uint8_t __xdata * __xdata msg;
static uint8_t __xdata msg_len;
static uint8_t __xdata n;
static uint16_t __xdata off;

/* Move on to the red plane: only valid once the black/white one is complete */
static uint8_t to_plane(void)
{
    if (msg[1] == plane)
        return 1;
    if (plane != SM_PLANE_BW || msg[1] != SM_PLANE_RED || expect != EPD_PLANE_BYTES)
        return 0;
    epd_stream_begin(0x13);
    plane = SM_PLANE_RED;
    expect = 0;
    zgot = 0;
    return 1;
}

/* A piece of a compressed plane: collected in eco_buf, decoded at ZEND */
static void on_zchunk(void)
{
    if (!active || !to_plane() || expect)
        return;
    n = (uint8_t)(msg_len - SM_IMG_HDR);
    off = (uint16_t)msg[2] | ((uint16_t)msg[3] << 8);
    if (off != zgot || off + n > SM_ECO_MAX)
        return;                         /* a repeat (lost ACK), a gap, or too big */
    for (off = 0; off < n; off++)
        eco_buf[zgot + off] = msg[SM_IMG_HDR + off];
    zgot += n;
}

static void on_zend(void)
{
    if (!active || !to_plane() || expect)
        return;
    eco_len = (uint16_t)msg[2] | ((uint16_t)msg[3] << 8);
    if (eco_len != zgot) {
        log_puts("img zplane short\r\n");
        return;
    }
    r_t0 = (uint16_t)wtimer0_curtime();
    if (eco_decode()) {
        expect = EPD_PLANE_BYTES;       /* the whole plane went to the panel */
        r_dt = (uint16_t)((uint16_t)wtimer0_curtime() - r_t0);
        log_puts("img zplane ");
        log_dec(eco_len);
        log_puts("B ");
        log_dec((uint16_t)(r_dt / SHELFHW_TICKS_PER_S));     /* 16-bit maths only: */
        log_putc('.');                                       /* see refresh_done() */
        log_dec((uint16_t)(((uint16_t)(r_dt % SHELFHW_TICKS_PER_S)) * 10u / SHELFHW_TICKS_PER_S));
        log_puts("s\r\n");
    } else {
        log_puts("img zplane bad\r\n");
    }
    zgot = 0;
}

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

    if (!to_plane())
        return;

    /* A repeat of an earlier chunk (lost ACK) or a gap: ignore, END will tell */
    if (off != expect || expect + n > EPD_PLANE_BYTES)
        return;

    epd_stream_write(msg + SM_IMG_HDR, n);
    expect += n;
}

/* The waveform is over (or never started): report it, and power the panel down only
 * once it says it is finished - cutting the rail (or sending POF) in the middle of a
 * waveform leaves the old image on the glass. A panel still busy is left powered;
 * img_rx_idle() puts it to sleep at a later poll. */
static void refresh_done(uint8_t st)
{
    r_dt = (uint16_t)((uint16_t)wtimer0_curtime() - r_t0);
    log_puts("img done busy=");
    log_dec(st);
    log_puts(" ");
    log_dec((uint16_t)(r_dt / SHELFHW_TICKS_PER_S));
    log_putc('.');
    log_dec((uint16_t)(((uint16_t)(r_dt % SHELFHW_TICKS_PER_S)) * 10u / SHELFHW_TICKS_PER_S));
    log_puts("s\r\n");
    refreshing = 0;
    if (st == EPD_BUSY_DONE)
        panel_off();
}

static void refresh_cb(struct wtimer_desc __xdata *desc)
{
    if (!r_parked) {
        /* the radio is parked from here, not from the END callback: the acknowledgement
         * of END must have left before the receiver goes to deep sleep */
        r_parked = 1;
        tag_radio_park();
    }
    if (!r_seen) {
        if (epd_busy_active()) {
            r_seen = 1;
            r_n = 0;
        } else if (++r_n >= REFRESH_START_N) {
            refresh_done(EPD_BUSY_NONE);
            return;
        }
    } else if (!epd_busy_active()) {
        refresh_done(EPD_BUSY_DONE);
        return;
    } else if (++r_n >= REFRESH_DONE_N) {
        refresh_done(EPD_BUSY_TIMEOUT);
        return;
    }
    desc->time += REFRESH_TICK;
    wtimer0_addabsolute(desc);
}

static void on_end(void)
{
    if (active && plane == SM_PLANE_RED && expect == EPD_PLANE_BYTES) {
        log_puts("img refresh\r\n");
        r_t0 = (uint16_t)wtimer0_curtime();
        r_seen = 0;
        r_n = 0;
        r_parked = 0;
        refreshing = 1;
        epd_refresh_begin();
        refresh_timer.handler = refresh_cb;
        refresh_timer.time = REFRESH_TICK;
        wtimer0_addrelative(&refresh_timer);
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
    case SM_OP_IMG_ZCHUNK:
        if (len <= SM_IMG_HDR)
            return 1;
        on_zchunk();
        break;
    case SM_OP_IMG_ZEND:
        if (len < SM_IMG_HDR)
            return 1;
        on_zend();
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
    return active || refreshing;
}

uint8_t img_rx_refreshing(void)
{
    return refreshing;
}

void img_rx_idle(void)
{
    if (panel_up && !active && !refreshing)
        panel_off();
}
