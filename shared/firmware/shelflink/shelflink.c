/**
 * @file shelflink.c
 * @brief Acknowledged-message link layer, see shelflink.h
 */

#include <libmftypes.h>
#include <libmfwtimer.h>
#include "axradio.h"
#include "shelfhw.h"
#include "shelflink.h"
#include "sl_proto.h"

struct sl_stats __xdata sl_stats;

enum {
    ST_IDLE,        /* no request in flight                              */
    ST_WAIT,        /* transmitted, waiting for the response             */
    ST_BACKOFF      /* no response, waiting to retry                     */
};

static uint8_t __xdata state;
static uint8_t __xdata attempts;
static uint8_t __xdata seq;
static uint16_t __xdata node_id;
static uint8_t __xdata net_id;
static uint16_t __xdata req_dst;
static uint8_t __xdata req_len;
static uint8_t __xdata req_frame[SL_HDR_LEN + SL_MAX_PAYLOAD];
static uint8_t __xdata rsp_frame[SL_HDR_LEN + SL_MAX_PAYLOAD];
static struct sl_rx __xdata rx_info;
static struct wtimer_desc __xdata timer;
static sl_rx_handler on_rx;
static sl_done_handler on_done;

static void fill_addr(struct axradio_address __xdata *a, uint16_t dst)
{
    a->addr[0] = (uint8_t)dst;
    a->addr[1] = (uint8_t)(dst >> 8);
    a->addr[2] = net_id;
    a->addr[3] = 0;
    a->addr[4] = 0;
}

static uint8_t radio_send(uint16_t dst, const uint8_t __xdata *frame, uint8_t len)
{
    struct axradio_address __xdata a;

    fill_addr(&a, dst);
    return axradio_transmit(&a, frame, len);
}

static void arm_timer(uint16_t ticks)
{
    wtimer_remove(&timer);
    timer.time = ticks;
    wtimer0_addrelative(&timer);
}

static struct sl_done __xdata done_info;

static void finish(uint8_t result, const struct sl_rx __xdata *rsp)
{
    state = ST_IDLE;
    if (result == SL_OK)
        sl_stats.tx_ok++;
    else
        sl_stats.tx_fail++;
    done_info.result = result;
    done_info.attempts = attempts;
    done_info.rsp = rsp;
    if (on_done)
        on_done(&done_info);
}

/* Starts one transmission of the pending request and opens the response window. */
static void attempt(void)
{
    uint8_t r;

    attempts++;
    if (attempts > 1)
        req_frame[1] |= SL_F_RETRY;
    sl_stats.tx_att++;
    r = radio_send(req_dst, req_frame, req_len);
    if (r != AXRADIO_ERR_NOERROR)
        sl_stats.tx_err++;
    /* A refused transmission just burns the window and is retried like a lost one */
    state = ST_WAIT;
    arm_timer(SHELFHW_MS_TO_TICKS(SL_RSP_TIMEOUT_MS));
}

static void timer_cb(struct wtimer_desc __xdata *desc)
{
    uint16_t ms;

    (void)desc;
    if (state == ST_WAIT) {
        if (attempts >= SL_MAX_ATTEMPTS) {
            finish(SL_ERR_NORESPONSE, 0);
            return;
        }
        ms = 5 + (uint16_t)(shelfhw_random() % ((uint16_t)SL_BACKOFF_MS * attempts + 1));
        state = ST_BACKOFF;
        arm_timer(SHELFHW_MS_TO_TICKS(ms));
    } else if (state == ST_BACKOFF) {
        attempt();
    }
}

uint8_t sl_init(uint16_t id, uint8_t net, sl_rx_handler rx_handler, sl_done_handler done_handler)
{
    struct axradio_address_mask __xdata local;
    uint8_t r;

    node_id = id;
    net_id = net;
    on_rx = rx_handler;
    on_done = done_handler;
    state = ST_IDLE;
    seq = (uint8_t)shelfhw_random();
    timer.handler = timer_cb;
    sl_dedupe_reset();

    r = axradio_init();
    if (r != AXRADIO_ERR_NOERROR)
        return r;

    fill_addr((struct axradio_address __xdata *)&local, id);
    local.mask[0] = 0xFF;
    local.mask[1] = 0xFF;
    local.mask[2] = 0xFF;
    local.mask[3] = 0x00;
    local.mask[4] = 0x00;
    axradio_set_local_address(&local);

    r = axradio_set_mode(AXRADIO_MODE_ASYNC_RECEIVE);
    axradio_setup_pincfg2();
    return r;
}

uint8_t sl_busy(void)
{
    return state != ST_IDLE;
}

uint8_t sl_send(uint16_t dst, uint8_t type, const uint8_t __xdata *payload, uint8_t len)
{
    if (state != ST_IDLE)
        return SL_ERR_BUSY;
    if (type != SL_T_POLL && type != SL_T_DATA)
        return SL_ERR_INVALID;
    seq++;
    req_len = sl_frame_build(req_frame, type, 0, node_id, seq, payload, len);
    if (!req_len)
        return SL_ERR_INVALID;
    req_dst = dst;
    attempts = 0;
    sl_stats.tx_req++;
    attempt();
    return SL_OK;
}

uint8_t sl_reply(const struct sl_rx __xdata *to, uint8_t type, const uint8_t __xdata *payload, uint8_t len)
{
    uint8_t n = sl_frame_build(rsp_frame, type, 0, node_id, to->seq, payload, len);

    if (!n)
        return SL_ERR_INVALID;
    if (radio_send(to->src, rsp_frame, n) != AXRADIO_ERR_NOERROR) {
        sl_stats.tx_err++;
        return SL_ERR_RADIO;
    }
    return SL_OK;
}

static void handle_rx(struct axradio_status __xdata *st)
{
    if (!sl_frame_parse(st->u.rx.pktdata, (uint8_t)st->u.rx.pktlen, &rx_info)) {
        sl_stats.rx_bad++;
        return;
    }
    rx_info.rssi = st->u.rx.phy.rssi;
    rx_info.dup = 0;

    switch (rx_info.type) {
    case SL_T_POLL_RSP:
    case SL_T_ACK:
        if (state != ST_IDLE && rx_info.src == req_dst && rx_info.seq == seq) {
            wtimer_remove(&timer);
            sl_stats.rx_ok++;
            finish(SL_OK, &rx_info);
        } else {
            sl_stats.rx_stray++;
        }
        break;

    default:    /* POLL, DATA */
        sl_stats.rx_ok++;
        rx_info.dup = sl_dedupe(rx_info.src, rx_info.seq);
        if (rx_info.dup)
            sl_stats.rx_dup++;
        if (rx_info.type == SL_T_DATA) {
            /* Answered before the application sees it, duplicates included */
            sl_reply(&rx_info, SL_T_ACK, 0, 0);
            if (rx_info.dup)
                break;
        }
        if (on_rx)
            on_rx(&rx_info);
        break;
    }
}

/* Event sink the engine calls from the wtimer callback context */
void axradio_statuschange(struct axradio_status __xdata *st)
{
    if (st->status == AXRADIO_STAT_RECEIVE && st->error == AXRADIO_ERR_NOERROR)
        handle_rx(st);
}
