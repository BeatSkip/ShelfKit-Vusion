/**
 * @file main.c
 * @brief ShelfKit tag (Vusion): polls the hub every SHELF_POLL_INTERVAL_S seconds
 *
 * Every poll is a reliable request (see Shared/firmware/shelflink): the tag
 * sends POLL, the radio drops back into receive mode by itself, and the hub's
 * POLL_RSP is the acknowledgement. Without one the poll is retried with a
 * jittered back-off, up to SL_MAX_ATTEMPTS transmissions. Results and link
 * statistics are logged on UART0 TX (PB4, 38400 8N1): green LED = poll
 * acknowledged, red LED = poll failed. The tag always listens, so the hub can
 * push an image to it (see img_rx.c) after seeing a poll.
 */

#include <ax8052f143.h>
#include <libmftypes.h>
#include <libmfwtimer.h>
#include "axradio.h"
#include "shelfhw.h"
#include "shelflink.h"
#include "shelfmsg.h"
#include "shelf_config.h"
#include "fw_rx.h"
#include "img_rx.h"
#include "pwr.h"
#include "shelf_id.h"

static struct wtimer_desc __xdata poll_timer;
static uint8_t __xdata poll_payload[SM_POLL_LEN];
static uint8_t __xdata last_attempts;
static int8_t __xdata last_hub_rssi;
static uint16_t __xdata polls_done;
static uint16_t __xdata node_id;   /* from the SPI flash record, see shelf_id.c */
static struct wtimer_desc __xdata listen_timer;
static uint8_t __xdata radio_asleep;

static void log_stats(void)
{
    log_puts("stats req=");
    log_dec(sl_stats.tx_req);
    log_puts(" ok=");
    log_dec(sl_stats.tx_ok);
    log_puts(" fail=");
    log_dec(sl_stats.tx_fail);
    log_puts(" air=");
    log_dec(sl_stats.tx_att);
    log_puts(" err=");
    log_dec(sl_stats.tx_err);
    log_puts(" rxbad=");
    log_dec(sl_stats.rx_bad);
    log_puts(" stray=");
    log_dec(sl_stats.rx_stray);
    log_nl();
}

/* The listening window is over and nothing arrived: park the radio until the
 * next poll. Anything that has to reach the tag - an image, a new firmware, an
 * identity - arrives as DATA right after a POLL, so it lands inside the window. */
static void listen_cb(struct wtimer_desc __xdata *desc)
{
    (void)desc;
#if SHELF_RADIO_SLEEP
    if (img_rx_active() || fw_rx_active() || fw_dump_active()) {
        /* a transfer or a read-back is running: stay awake, and check again once
         * it should be over - the window re-arms itself instead of leaving the
         * radio on until the next poll (and never sleeps mid-read) */
        desc->time += (uint32_t)SHELF_LISTEN_WINDOW_S * SHELFHW_TICKS_PER_S;
        wtimer0_addabsolute(desc);
        return;
    }
    log_puts("sleep\r\n");
    shelfhw_radio_sleep();
    radio_asleep = 1;
#else
    (void)desc;
#endif
}

static void on_done(const struct sl_done __xdata *done)
{
    uint8_t attempts = done->attempts;
    const struct sl_rx __xdata *rsp = done->rsp;

    /* a frame from the flash read-back: handled there, and not a poll result */
    if (fw_dump_done(done->result))
        return;

    polls_done++;
    last_attempts = attempts;

    /* The normal case is silent: green means "an image is starting" now, and a
     * per-poll flash (or a latched level) kept an LED lit almost permanently,
     * which is exactly the heat that shows up on the panel. */
    if (done->result == SL_OK) {
        log_puts("poll ok att=");
        log_dec(attempts);
        log_puts(" rssi=");
        log_sdec(rsp->rssi);
        if (rsp->len >= SM_RSP_LEN) {
            last_hub_rssi = (int8_t)rsp->payload[SM_RSP_RSSI];
            log_puts(" hubrssi=");
            log_sdec(last_hub_rssi);
        }
        log_nl();
    } else {
        log_puts("poll FAILED after ");
        log_dec(attempts);
        log_puts(" attempts");
        log_nl();
        shelfhw_led_pulse(SHELFHW_LED_RED, SHELFHW_LED_PULSE_MS);
    }

    if (polls_done % SHELF_STATS_EVERY == 0)
        log_stats();
}

static void on_rx(const struct sl_rx __xdata *rx)
{
    if (rx->type != SL_T_DATA)
        return;
    /* firmware opcodes start at SM_OP_FW_BEGIN; image opcodes are below them */
    if (rx->len && rx->payload[0] >= SM_OP_FW_BEGIN)
        (void)fw_rx_data(rx->payload, rx->len);
    else
        (void)img_rx_data(rx->payload, rx->len);
}

static void poll_cb(struct wtimer_desc __xdata *desc)
{
    uint16_t up = (uint16_t)(wtimer0_curtime() / SHELFHW_TICKS_PER_S);

    /* Periodic, anchored to the previous expiry so the interval does not drift */
    desc->time += (uint32_t)SHELF_POLL_INTERVAL_S * SHELFHW_TICKS_PER_S;
    wtimer0_addabsolute(desc);

    /* a flash read-back owns the link: don't poll into the middle of it */
    if (img_rx_active() || fw_rx_active() || fw_dump_active())
        return;

#if SHELF_RADIO_SLEEP
    /* wake the radio for this poll and open the listening window */
    if (radio_asleep) {
        log_puts("wake\r\n");
        shelfhw_radio_wake();
        radio_asleep = 0;
    }
    listen_timer.time = (uint32_t)SHELF_LISTEN_WINDOW_S * SHELFHW_TICKS_PER_S;
    wtimer0_addrelative(&listen_timer);
#endif

    poll_payload[SM_POLL_UPTIME_LO] = (uint8_t)up;
    poll_payload[SM_POLL_UPTIME_HI] = (uint8_t)(up >> 8);
    poll_payload[SM_POLL_ATTEMPTS] = last_attempts;
    poll_payload[SM_POLL_RSSI] = (uint8_t)last_hub_rssi;
    {
        uint16_t vdd = shelfhw_measure_vdd();
        poll_payload[SM_POLL_VDD_LO] = (uint8_t)vdd;
        poll_payload[SM_POLL_VDD_HI] = (uint8_t)(vdd >> 8);
    }

    if (sl_send(SL_NODE_HUB, SL_T_POLL, poll_payload, SM_POLL_LEN) != SL_OK)
        log_puts("poll skipped, previous still in flight\r\n");
}

void main(void)
{
    uint8_t r;

    shelfhw_init();
    /* PA5 (U4, the panel supply) must be driven to its *off* level right away.
     * Left floating, the unpowered panel is back-powered through its SPI pins and
     * loads the bus the flash shares with it: reads still return sane data, but a
     * page program is not accepted (the identity write failed with "read back
     * ffff" until an image had been pushed, i.e. until pwr_init() had run). */
    pwr_init();
#if SHELF_POWER_LINES
    pwr_on();
#endif
    node_id = shelf_id_boot();

    log_puts("\r\n*** ShelfKit tag, node ");
    log_hex16(node_id);
    log_puts(" net ");
    log_hex8(SHELF_NET_ID);
    log_puts(" dump=1");
    log_nl();

    r = sl_init(node_id, SHELF_NET_ID, on_rx, on_done);
    if (r != AXRADIO_ERR_NOERROR) {
        log_puts("radio init failed, err=");
        log_dec(r);
        log_nl();
        shelfhw_fatal(SHELFHW_LED_RED);
    }
    log_puts("radio ok, pll rng=");
    log_dec(axradio_get_pllrange());
    log_puts(", polling every ");
    log_dec(SHELF_POLL_INTERVAL_S);
    log_puts(" s");
    log_nl();
    shelfhw_led_pulse(SHELFHW_LED_BLUE, SHELFHW_LED_BOOT_PULSE_MS);

    poll_timer.handler = poll_cb;
    poll_timer.time = SHELFHW_TICKS_PER_S;
    wtimer0_addabsolute(&poll_timer);

    /* armed by poll_cb, not before: an un-armed descriptor is simply not linked */
    listen_timer.handler = listen_cb;

    /* While an image or a firmware image arrives the tag must hear every frame,
     * so no standby */
    for (;;) {
        if (fw_dump_active())
            fw_dump_step();
        if (img_rx_active() || fw_rx_active() || fw_dump_active())
            shelfhw_poll_awake();
        else
            shelfhw_poll();
    }
}
