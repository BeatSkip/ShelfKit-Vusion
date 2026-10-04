/**
 * @file main.c
 * @brief ShelfKit tag (Vusion): polls the hub every SHELF_POLL_INTERVAL_S seconds
 *
 * Every poll is a reliable request (see shared/firmware/shelflink): the tag
 * sends POLL, the radio drops back into receive mode by itself, and the hub's
 * POLL_RSP is the acknowledgement. Without one the poll is retried with a
 * jittered back-off, up to SL_MAX_ATTEMPTS transmissions. Results and link
 * statistics are logged on UART0 TX (PB4, 38400 8N1): green LED = poll
 * acknowledged, red LED = poll failed.
 */

#include <ax8052f143.h>
#include <libmftypes.h>
#include <libmfwtimer.h>
#include "axradio.h"
#include "shelfhw.h"
#include "shelflink.h"
#include "shelfmsg.h"
#include "shelf_config.h"
#include "pwr.h"

static struct wtimer_desc __xdata poll_timer;
static uint8_t __xdata poll_payload[SM_POLL_LEN];
static uint8_t __xdata last_attempts;
static int8_t __xdata last_hub_rssi;
static uint16_t __xdata polls_done;

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

static void on_done(const struct sl_done __xdata *done)
{
    uint8_t attempts = done->attempts;
    const struct sl_rx __xdata *rsp = done->rsp;

    polls_done++;
    last_attempts = attempts;
    shelfhw_led(SHELFHW_LED_GREEN, 0);
    shelfhw_led(SHELFHW_LED_RED, 0);

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
        shelfhw_led(SHELFHW_LED_GREEN, 1);
    } else {
        log_puts("poll FAILED after ");
        log_dec(attempts);
        log_puts(" attempts");
        log_nl();
        shelfhw_led(SHELFHW_LED_RED, 1);
    }

    if (polls_done % SHELF_STATS_EVERY == 0)
        log_stats();
}

static void poll_cb(struct wtimer_desc __xdata *desc)
{
    uint16_t up = (uint16_t)(wtimer0_curtime() / SHELFHW_TICKS_PER_S);

    /* Periodic, anchored to the previous expiry so the interval does not drift */
    desc->time += (uint32_t)SHELF_POLL_INTERVAL_S * SHELFHW_TICKS_PER_S;
    wtimer0_addabsolute(desc);

    poll_payload[SM_POLL_UPTIME_LO] = (uint8_t)up;
    poll_payload[SM_POLL_UPTIME_HI] = (uint8_t)(up >> 8);
    poll_payload[SM_POLL_ATTEMPTS] = last_attempts;
    poll_payload[SM_POLL_RSSI] = (uint8_t)last_hub_rssi;

    if (sl_send(SL_NODE_HUB, SL_T_POLL, poll_payload, SM_POLL_LEN) != SL_OK)
        log_puts("poll skipped, previous still in flight\r\n");
}

void main(void)
{
    uint8_t r;

    shelfhw_init();
#if SHELF_POWER_LINES
    pwr_init();
    pwr_on();
#endif
    log_puts("\r\n*** ShelfKit tag, node ");
    log_hex16(SHELF_NODE_ID);
    log_puts(" net ");
    log_hex8(SHELF_NET_ID);
    log_nl();

    r = sl_init(SHELF_NODE_ID, SHELF_NET_ID, 0, on_done);
    if (r != AXRADIO_ERR_NOERROR) {
        log_puts("radio init failed, err=");
        log_dec(r);
        log_nl();
        shelfhw_led(SHELFHW_LED_RED, 1);
        for (;;)
            shelfhw_poll();
    }
    log_puts("radio ok, pll rng=");
    log_dec(axradio_get_pllrange());
    log_puts(", polling every ");
    log_dec(SHELF_POLL_INTERVAL_S);
    log_puts(" s");
    log_nl();
    shelfhw_led(SHELFHW_LED_BLUE, 1);

    poll_timer.handler = poll_cb;
    poll_timer.time = SHELFHW_TICKS_PER_S;
    wtimer0_addrelative(&poll_timer);

    for (;;)
        shelfhw_poll();
}
