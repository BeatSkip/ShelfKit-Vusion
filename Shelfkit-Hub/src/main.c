/**
 * @file main.c
 * @brief ShelfKit hub: always listening, answers tag polls
 *
 * The radio runs in always-on receive mode (see shared/firmware/shelflink).
 * Every POLL a tag sends is answered with a POLL_RSP carrying the RSSI the hub
 * measured, which doubles as the tag's acknowledgement. Each frame is logged
 * on UART0 TX (PB4, 38400 8N1); the green LED toggles per valid frame.
 *
 * The answer goes out before anything is logged - the tag only waits
 * SL_RSP_TIMEOUT_MS for it.
 */

#include <ax8052f143.h>
#include <libmftypes.h>
#include "axradio.h"
#include "shelfhw.h"
#include "shelflink.h"
#include "shelfmsg.h"
#include "shelf_config.h"
#include "pwr.h"

static uint8_t __xdata rsp[SM_RSP_LEN];

static void log_rx(const struct sl_rx __xdata *rx)
{
    log_puts(rx->type == SL_T_POLL ? "POLL" : "DATA");
    log_puts(" src=");
    log_hex16(rx->src);
    log_puts(" seq=");
    log_hex8(rx->seq);
    log_puts(" rssi=");
    log_sdec(rx->rssi);
    if (rx->flags & SL_F_RETRY)
        log_puts(" retry");
    if (rx->dup)
        log_puts(" dup");
    if (rx->type == SL_T_POLL && rx->len >= SM_POLL_LEN) {
        log_puts(" up=");
        log_dec((uint16_t)rx->payload[SM_POLL_UPTIME_LO] |
                ((uint16_t)rx->payload[SM_POLL_UPTIME_HI] << 8));
        log_puts("s att=");
        log_dec(rx->payload[SM_POLL_ATTEMPTS]);
        log_puts(" hubrssi=");
        log_sdec((int8_t)rx->payload[SM_POLL_RSSI]);
    }
    log_nl();
}

static void on_rx(const struct sl_rx __xdata *rx)
{
    if (rx->type == SL_T_POLL) {
        rsp[SM_RSP_CMD] = SM_CMD_NONE;
        rsp[SM_RSP_RSSI] = (uint8_t)(int8_t)rx->rssi;
        sl_reply(rx, SL_T_POLL_RSP, rsp, SM_RSP_LEN);
    }
    shelfhw_led_toggle(SHELFHW_LED_GREEN);
    log_rx(rx);
}

void main(void)
{
    uint8_t r;

    shelfhw_init();
#if SHELF_POWER_LINES
    pwr_init();
    pwr_on();
#endif
    log_puts("\r\n*** ShelfKit hub, node ");
    log_hex16(SHELF_NODE_ID);
    log_puts(" net ");
    log_hex8(SHELF_NET_ID);
    log_nl();

    r = sl_init(SHELF_NODE_ID, SHELF_NET_ID, on_rx, 0);
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
    log_puts(", listening");
    log_nl();
    shelfhw_led(SHELFHW_LED_BLUE, 1);

    for (;;)
        shelfhw_poll();
}
