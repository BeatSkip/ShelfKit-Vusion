/* Unit test for the shelflink state machine (shelflink.c) on the SDCC
 * simulator, run by tooling/test_shelflink.py. The radio engine, the wake-up
 * timers and the random source are replaced by stubs, so the test drives the
 * protocol by hand: "receive" frames, "fire" timers, inspect what was sent.
 * check() stores 1 / 0xEE per check in results[]. */

#include <libmftypes.h>
#include <libmfwtimer.h>
#include "axradio.h"
#include "shelfhw.h"
#include "shelflink.h"
#include "sl_proto.h"

#define NET 0x5A
#define TAG 0x0100u

uint8_t __xdata results[64];
uint8_t __xdata nfail;
static uint8_t __xdata t;

static void check(uint8_t ok) { results[t++] = ok ? 1 : 0xEE; if (!ok) nfail++; }

void done(void) { for (;;) ; }

/* â”€â”€ stubs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */

static uint8_t __xdata tx_count;
static uint8_t __xdata tx_result;
static uint8_t __xdata tx_addr[3];
static uint8_t __xdata tx_frame[SL_HDR_LEN + SL_MAX_PAYLOAD];
static uint8_t __xdata tx_len;
static struct wtimer_desc __xdata *armed;
static uint16_t __xdata armed_ticks;
static uint16_t __xdata rnd;

uint8_t axradio_init(void) { return AXRADIO_ERR_NOERROR; }
uint8_t axradio_set_mode(uint8_t m) { return m == AXRADIO_MODE_ASYNC_RECEIVE ? AXRADIO_ERR_NOERROR : AXRADIO_ERR_INVALID; }
void axradio_set_local_address(const struct axradio_address_mask __genericaddr *a) { a; }
__reentrantb void axradio_setup_pincfg2(void) __reentrant {}

uint8_t axradio_transmit(const struct axradio_address __genericaddr *addr, const uint8_t __genericaddr *pkt, uint16_t len)
{
    uint8_t i;

    tx_count++;
    for (i = 0; i < 3; i++)
        tx_addr[i] = addr->addr[i];
    for (i = 0; i < len; i++)
        tx_frame[i] = pkt[i];
    tx_len = (uint8_t)len;
    return tx_result;
}

__reentrantb void wtimer0_addrelative(struct wtimer_desc __xdata *d) __reentrant { armed = d; armed_ticks = (uint16_t)d->time; }
__reentrantb uint8_t wtimer_remove(struct wtimer_desc __xdata *d) __reentrant { if (armed == d) { armed = 0; return 1; } return 0; }
uint16_t shelfhw_random(void) { rnd += 0x1357; return rnd; }
/* the headers declare these vector handlers; the real ones live in the engine and in libmf */
void axradio_isr(void) __interrupt INT_RADIO {}
void wtimer_irq(void) __interrupt(1) {}

static void fire_timer(void)
{
    struct wtimer_desc __xdata *d = armed;

    armed = 0;
    d->handler(d);
}

/* â”€â”€ helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */

static struct axradio_status __xdata st;
static uint8_t __xdata rxbuf[SL_HDR_LEN + SL_MAX_PAYLOAD];

static void deliver(uint8_t type, uint16_t src, uint8_t seq, uint8_t flags, const uint8_t __xdata *pl, uint8_t len)
{
    uint8_t n = sl_frame_build(rxbuf, type, flags, src, seq, pl, len);

    st.status = AXRADIO_STAT_RECEIVE;
    st.error = AXRADIO_ERR_NOERROR;
    st.u.rx.pktdata = rxbuf;
    st.u.rx.pktlen = n;
    st.u.rx.phy.rssi = -70;
    axradio_statuschange(&st);
}

static uint8_t __xdata rx_calls, rx_dup_seen, rx_type, done_calls, done_result, done_attempts;
static uint8_t __xdata done_has_rsp;
static uint16_t __xdata rx_src;
static uint8_t __xdata reply_payload[2];

static void on_rx(const struct sl_rx __xdata *rx)
{
    rx_calls++;
    rx_dup_seen = rx->dup;
    rx_type = rx->type;
    rx_src = rx->src;
    if (rx->type == SL_T_POLL) {
        reply_payload[0] = 0;
        reply_payload[1] = 0x42;
        sl_reply(rx, SL_T_POLL_RSP, reply_payload, 2);
    }
}

static void on_done(const struct sl_done __xdata *d)
{
    done_calls++;
    done_result = d->result;
    done_attempts = d->attempts;
    done_has_rsp = d->rsp != 0;
}

static uint8_t __xdata payload[4];

void main(void)
{
    uint8_t i, seq;

    /* â”€â”€ initiator (tag) â”€â”€ */
    check(sl_init(TAG, NET, on_rx, on_done) == AXRADIO_ERR_NOERROR);

    /* 1. clean exchange */
    payload[0] = 1;
    check(sl_send(SL_NODE_HUB, SL_T_POLL, payload, 4) == SL_OK);
    check(tx_count == 1 && sl_busy());
    check(tx_addr[0] == 0x01 && tx_addr[1] == 0x00 && tx_addr[2] == NET);
    check(tx_len == SL_HDR_LEN + 4 && (tx_frame[0] & 0x0F) == SL_T_POLL && !(tx_frame[1] & SL_F_RETRY));
    check(tx_frame[2] == 0x00 && tx_frame[3] == 0x01);          /* source = 0x0100 */
    seq = tx_frame[4];
    check(armed != 0);
    check(sl_send(SL_NODE_HUB, SL_T_POLL, payload, 4) == SL_ERR_BUSY);
    deliver(SL_T_POLL_RSP, SL_NODE_HUB, seq, 0, reply_payload, 2);
    check(done_calls == 1 && done_result == SL_OK && done_attempts == 1 && done_has_rsp);
    check(!sl_busy() && armed == 0);
    check(sl_stats.tx_req == 1 && sl_stats.tx_ok == 1 && sl_stats.tx_att == 1);

    /* 2. no answer at all: SL_MAX_ATTEMPTS transmissions, then give up */
    tx_count = 0;
    check(sl_send(SL_NODE_HUB, SL_T_POLL, payload, 4) == SL_OK);
    seq = tx_frame[4];
    for (i = 1; i < SL_MAX_ATTEMPTS; i++) {
        fire_timer();                       /* response window over -> back-off */
        check(tx_count == i && armed != 0);
        fire_timer();                       /* back-off over -> retry */
        check(tx_count == i + 1 && (tx_frame[1] & SL_F_RETRY) && tx_frame[4] == seq);
    }
    check(done_calls == 1);
    fire_timer();                           /* last window over */
    check(done_calls == 2 && done_result == SL_ERR_NORESPONSE && done_attempts == SL_MAX_ATTEMPTS && !done_has_rsp);
    check(!sl_busy() && armed == 0 && tx_count == SL_MAX_ATTEMPTS);
    check(sl_stats.tx_fail == 1);

    /* 3. wrong sequence number / wrong source are not answers */
    check(sl_send(SL_NODE_HUB, SL_T_POLL, payload, 4) == SL_OK);
    seq = tx_frame[4];
    deliver(SL_T_POLL_RSP, SL_NODE_HUB, (uint8_t)(seq + 1), 0, reply_payload, 2);
    deliver(SL_T_POLL_RSP, 0x0200u, seq, 0, reply_payload, 2);
    check(sl_busy() && done_calls == 2 && sl_stats.rx_stray == 2);

    /* 4. a late answer to the first transmission, while backing off, still counts */
    fire_timer();
    check(sl_busy());
    deliver(SL_T_POLL_RSP, SL_NODE_HUB, seq, 0, reply_payload, 2);
    check(done_calls == 3 && done_result == SL_OK && armed == 0 && !sl_busy());

    /* 5. the engine refuses the transmission: counted, and retried like a lost one */
    tx_result = AXRADIO_ERR_BUSY;
    tx_count = 0;
    check(sl_send(SL_NODE_HUB, SL_T_POLL, payload, 4) == SL_OK);
    check(sl_stats.tx_err == 1 && sl_busy() && armed != 0);
    fire_timer();
    fire_timer();
    check(tx_count == 2 && sl_stats.tx_err == 2);
    tx_result = AXRADIO_ERR_NOERROR;
    seq = tx_frame[4];
    deliver(SL_T_POLL_RSP, SL_NODE_HUB, seq, 0, reply_payload, 2);
    check(done_calls == 4 && done_result == SL_OK && done_attempts == 2);

    /* 6. garbage is counted and ignored */
    st.status = AXRADIO_STAT_RECEIVE;
    st.error = AXRADIO_ERR_NOERROR;
    st.u.rx.pktdata = rxbuf;
    st.u.rx.pktlen = 3;
    axradio_statuschange(&st);
    check(sl_stats.rx_bad == 1);

    /* â”€â”€ responder (hub) â”€â”€ */
    check(sl_init(SL_NODE_HUB, NET, on_rx, 0) == AXRADIO_ERR_NOERROR);
    tx_count = 0;
    rx_calls = 0;

    /* 7. POLL: handler runs once and answers to the sender with the same seq */
    deliver(SL_T_POLL, TAG, 0x31, 0, payload, 4);
    check(rx_calls == 1 && !rx_dup_seen && rx_type == SL_T_POLL && rx_src == TAG);
    check(tx_count == 1 && (tx_frame[0] & 0x0F) == SL_T_POLL_RSP && tx_frame[4] == 0x31);
    check(tx_addr[0] == 0x00 && tx_addr[1] == 0x01 && tx_addr[2] == NET);   /* to the tag, 0x0100 */

    /* 8. the tag retries (its answer got lost): handler sees it flagged as duplicate, still answered */
    deliver(SL_T_POLL, TAG, 0x31, SL_F_RETRY, payload, 4);
    check(rx_calls == 2 && rx_dup_seen == 1 && tx_count == 2);

    /* 9. DATA is acknowledged automatically; a duplicate is acknowledged but not delivered */
    tx_count = 0;
    rx_calls = 0;
    deliver(SL_T_DATA, TAG, 0x50, 0, payload, 3);
    check(tx_count == 1 && (tx_frame[0] & 0x0F) == SL_T_ACK && tx_frame[4] == 0x50 && tx_len == SL_HDR_LEN);
    check(rx_calls == 1 && rx_type == SL_T_DATA);
    deliver(SL_T_DATA, TAG, 0x50, SL_F_RETRY, payload, 3);
    check(tx_count == 2 && rx_calls == 1);
    deliver(SL_T_DATA, TAG, 0x51, 0, payload, 3);
    check(tx_count == 3 && rx_calls == 2);

    done();
}
