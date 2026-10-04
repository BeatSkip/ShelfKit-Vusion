/* Unit test for the pure logic of shelflink (sl_proto.c), run on the SDCC
 * simulator by tooling/test_shelflink.py. check() stores 1 / 0xEE per
 * check in results[]; the script stops the simulator in done() and reads it. */
#include <libmftypes.h>
#include "sl_proto.h"

uint8_t __xdata results[24];
uint8_t __xdata nfail;
static uint8_t __xdata t;
static uint8_t __xdata buf[SL_HDR_LEN + SL_MAX_PAYLOAD + 4];
static uint8_t __xdata pl[SL_MAX_PAYLOAD + 1];
static struct sl_rx __xdata rx;

static void check(uint8_t ok) { results[t++] = ok ? 1 : 0xEE; if (!ok) nfail++; }

void done(void) { for (;;) ; }

void main(void)
{
    uint8_t i, n;

    for (i = 0; i < sizeof(pl); i++) pl[i] = (uint8_t)(0xA0 + i);

    /* build / parse round trip */
    n = sl_frame_build(buf, SL_T_POLL, SL_F_RETRY, 0x1234, 0x77, pl, 4);
    check(n == SL_HDR_LEN + 4);
    check(buf[0] == 0x11 && buf[1] == 0x01 && buf[2] == 0x34 && buf[3] == 0x12 && buf[4] == 0x77);
    check(sl_frame_parse(buf, n, &rx));
    check(rx.type == SL_T_POLL && rx.flags == SL_F_RETRY && rx.src == 0x1234 && rx.seq == 0x77 && rx.len == 4);
    check(rx.payload[0] == 0xA0 && rx.payload[3] == 0xA3);

    /* empty and maximum payload */
    n = sl_frame_build(buf, SL_T_ACK, 0, 0x0001, 1, pl, 0);
    check(n == SL_HDR_LEN && sl_frame_parse(buf, n, &rx) && rx.type == SL_T_ACK && rx.len == 0);
    n = sl_frame_build(buf, SL_T_DATA, 0, 0x0100, 2, pl, SL_MAX_PAYLOAD);
    check(n == SL_HDR_LEN + SL_MAX_PAYLOAD && sl_frame_parse(buf, n, &rx) && rx.len == SL_MAX_PAYLOAD);
    check(sl_frame_build(buf, SL_T_DATA, 0, 1, 1, pl, SL_MAX_PAYLOAD + 1) == 0);

    /* rejects */
    n = sl_frame_build(buf, SL_T_POLL, 0, 1, 1, pl, 2);
    check(!sl_frame_parse(buf, SL_HDR_LEN - 1, &rx));
    check(!sl_frame_parse(buf, SL_HDR_LEN + SL_MAX_PAYLOAD + 1, &rx));
    buf[0] = 0x21; check(!sl_frame_parse(buf, n, &rx));      /* version 2 */
    buf[0] = 0x10; check(!sl_frame_parse(buf, n, &rx));      /* type 0    */
    buf[0] = 0x15; check(!sl_frame_parse(buf, n, &rx));      /* type 5    */

    /* duplicate filter */
    sl_dedupe_reset();
    check(sl_dedupe(1, 5) == 0);
    check(sl_dedupe(1, 5) == 1);
    check(sl_dedupe(1, 6) == 0);
    check(sl_dedupe(1, 5) == 0);          /* only the last seq counts */
    check(sl_dedupe(2, 5) == 0);          /* other source is independent */
    check(sl_dedupe(2, 5) == 1);
    sl_dedupe_reset();
    check(sl_dedupe(1, 6) == 0);
    for (i = 10; i < 17; i++) sl_dedupe(i, 1);   /* 7 more: table (8) is full */
    check(sl_dedupe(1, 6) == 1);          /* still remembered */
    sl_dedupe(99, 1);                     /* evicts the oldest slot (src 1) */
    check(sl_dedupe(1, 6) == 0);

    done();
}
