/**
 * @file main.c
 * @brief ShelfKit hub: always listening, answers tag polls, forwards host data to tags
 *
 * The radio runs in always-on receive mode (see Shared/firmware/shelflink).
 * Every POLL a tag sends is answered with a POLL_RSP carrying the RSSI the hub
 * measured, which doubles as the tag's acknowledgement. Each frame is logged
 * on UART0 TX (PB4, 38400 8N1); the green LED toggles per valid frame. The
 * "POLL src=<addr> ..." line is the tag's announcement to the host.
 *
 * The host answers over UART0 RX (PB5) with line commands (see below) that make
 * the hub send a reliable DATA frame to a tag address - used to push images.
 * The main loop therefore never sleeps.
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
static uint8_t __xdata delay_hint;      /* 10 s units, 0 = no request */
/* Tags the host has data queued for: their next poll reply carries SM_CMD_DATA
 * so the tag keeps listening instead of closing its window after the grace. */
#define PREARM_SLOTS 4
static uint16_t __xdata prearmed[PREARM_SLOTS];

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
    if (rx->type == SL_T_DATA && rx->len > 0 && rx->payload[0] == SM_OP_FLASH_DATA) {
        /* a flash read-back frame from a tag: the host needs the bytes, and this
         * log is the only way back */
        uint8_t i;
        log_puts(" flash=");
        for (i = 1; i < rx->len; i++)
            log_hex8(rx->payload[i]);
    }
    /* 4-byte polls are the old firmware; 6-byte ones add the supply voltage.
     * Print each field only when the bytes are actually there. */
    if (rx->type == SL_T_POLL && rx->len >= 4) {
        log_puts(" up=");
        log_dec((uint16_t)rx->payload[SM_POLL_UPTIME_LO] |
                ((uint16_t)rx->payload[SM_POLL_UPTIME_HI] << 8));
        log_puts("s att=");
        log_dec(rx->payload[SM_POLL_ATTEMPTS]);
        log_puts(" hubrssi=");
        log_sdec((int8_t)rx->payload[SM_POLL_RSSI]);
        if (rx->len >= SM_POLL_LEN) {
            log_puts(" vdd=");
            log_hex16((uint16_t)rx->payload[SM_POLL_VDD_LO] |
                      ((uint16_t)rx->payload[SM_POLL_VDD_HI] << 8));
        }
    }
    log_nl();
}

/* ── host commands on UART0 RX ───────────────────────────────────────────
 *
 * One command per line, hex only, '\n' terminated ('\r' ignored):
 *   P                          -> "PONG"
 *   Q<hhhh>                    -> data is queued for tag hhhh: flag its next poll
 *   L<hh>                      -> ask every tag to wait hh*10 s before the next poll
 *   S<addr:4><payload...><chk:2>   reliable DATA frame to node addr
 *                              -> "SENT <addr> ok|fail att=N" when finished
 * chk makes the sum of all decoded bytes (addr, payload, chk) 0 mod 256. A bad
 * line is answered with "ERR <why>" and ignored; the host retries.
 */
/* A 'B' line carries up to BLK_MAX_FRAMES frames of SL_MAX_PAYLOAD bytes, each
 * prefixed with its length, plus address, count and checksum. */
#define BLK_MAX_FRAMES  8
#define BLK_MAX_BYTES   (3 + BLK_MAX_FRAMES * (1 + SL_MAX_PAYLOAD) + 1)
#define LINE_MAX        (1 + 2 * BLK_MAX_BYTES + 2)

static char __xdata line[LINE_MAX];
static uint16_t __xdata line_len;   /* a B line is >255 characters */
static uint8_t __xdata line_overflow;
static uint8_t __xdata cmd_buf[2 + SL_MAX_PAYLOAD + 1];
static uint16_t __xdata cmd_dst;

/* ── batched DATA ─────────────────────────────────────────────────────────
 * One 'B' line carries several frames and the hub sends them back to back,
 * waiting for each acknowledgement, then answers with a single SENT. That
 * removes the per-frame serial round-trip, which was ~41 of the 44 ms a frame
 * used to cost - the air only needs ~3 ms. */
static uint8_t __xdata blk_raw[BLK_MAX_BYTES];
static uint16_t __xdata blk_off[BLK_MAX_FRAMES];   /* byte offsets up to BLK_MAX_BYTES */
static uint8_t __xdata blk_len[BLK_MAX_FRAMES];
static uint8_t __xdata blk_n;
static uint8_t __xdata blk_i;
static uint8_t __xdata blk_active;
static uint8_t __xdata blk_att;
static uint16_t __xdata blk_dst;

static void batch_step(void);

static int8_t hexval(char c)
{
    if (c >= '0' && c <= '9')
        return (int8_t)(c - '0');
    if (c >= 'a' && c <= 'f')
        return (int8_t)(c - 'a' + 10);
    if (c >= 'A' && c <= 'F')
        return (int8_t)(c - 'A' + 10);
    return -1;
}

static void cmd_send(void)
{
    uint16_t digits = (uint16_t)(line_len - 1);
    uint16_t n, i;
    uint8_t sum = 0;
    uint16_t dst;
    int8_t hi, lo;

    if (digits < 6 || (digits & 1)) {
        log_puts("ERR len\r\n");
        return;
    }
    if (blk_active) {                   /* a batch owns the radio */
        log_puts("ERR busy\r\n");
        return;
    }
    n = (uint8_t)(digits / 2);
    if (n > sizeof(cmd_buf)) {
        log_puts("ERR len\r\n");
        return;
    }
    for (i = 0; i < n; i++) {
        hi = hexval(line[1 + 2 * i]);
        lo = hexval(line[2 + 2 * i]);
        if (hi < 0 || lo < 0) {
            log_puts("ERR hex\r\n");
            return;
        }
        cmd_buf[i] = (uint8_t)((hi << 4) | lo);
        sum += cmd_buf[i];
    }
    if (sum) {
        log_puts("ERR chk\r\n");
        return;
    }
    dst = (uint16_t)cmd_buf[0] | ((uint16_t)cmd_buf[1] << 8);
    if (dst == SHELF_NODE_ID || dst == 0) {
        log_puts("ERR addr\r\n");
        return;
    }
    switch (sl_send(dst, SL_T_DATA, cmd_buf + 2, (uint8_t)(n - 3))) {
    case SL_OK:
        cmd_dst = dst;
        break;
    case SL_ERR_BUSY:
        log_puts("ERR busy\r\n");
        break;
    default:
        log_puts("ERR send\r\n");
        break;
    }
}

/* Send the next frame of the batch, or finish it. Called when a batch starts, from
 * on_done() after each acknowledgement, and from the main loop while one is
 * still waiting for the radio. */
static void batch_step(void)
{
    uint8_t r;

    if (blk_i >= blk_n) {
        log_puts("SENT ");
        log_hex16(blk_dst);
        log_puts(" ok att=");
        log_dec(blk_att);
        log_nl();
        blk_active = 0;
        return;
    }
    r = sl_send(blk_dst, SL_T_DATA, &blk_raw[blk_off[blk_i]], blk_len[blk_i]);
    if (r == SL_ERR_BUSY)
        return;                     /* the main loop will try again */
    if (r != SL_OK) {
        log_puts("ERR send\r\n");
        blk_active = 0;
    }
}

static void cmd_batch(void)
{
    uint16_t digits = (uint16_t)(line_len - 1);
    uint16_t n, i, off = 3;
    uint8_t sum = 0;
    int8_t hi, lo;

    if (blk_active) {                   /* one batch at a time */
        log_puts("ERR busy\r\n");
        return;
    }
    if (digits < 8 || (digits & 1)) {
        log_puts("ERR len\r\n");
        return;
    }
    n = (uint16_t)(digits / 2);
    if (n > sizeof(blk_raw)) {
        log_puts("ERR len\r\n");
        return;
    }
    for (i = 0; i < n; i++) {
        hi = hexval(line[1 + 2 * i]);
        lo = hexval(line[2 + 2 * i]);
        if (hi < 0 || lo < 0) {
            log_puts("ERR hex\r\n");
            return;
        }
        blk_raw[i] = (uint8_t)((hi << 4) | lo);
        sum = (uint8_t)(sum + blk_raw[i]);
    }
    if (sum) {
        log_puts("ERR chk\r\n");
        return;
    }
    blk_dst = (uint16_t)blk_raw[0] | ((uint16_t)blk_raw[1] << 8);
    if (blk_dst == SHELF_NODE_ID || blk_dst == 0) {
        log_puts("ERR addr\r\n");
        return;
    }
    blk_n = blk_raw[2];
    if (blk_n == 0 || blk_n > BLK_MAX_FRAMES) {
        log_puts("ERR len\r\n");
        return;
    }
    for (i = 0; i < blk_n; i++) {
        uint8_t len;

        if (off >= n) {
            log_puts("ERR len\r\n");
            return;
        }
        len = blk_raw[off];
        if (len == 0 || len > SL_MAX_PAYLOAD ||
            (uint16_t)off + 1u + len > (uint16_t)(n - 1)) {
            log_puts("ERR len\r\n");
            return;
        }
        blk_len[i] = len;
        blk_off[i] = (uint16_t)(off + 1);
        off = (uint16_t)(off + 1 + len);
    }
    if (off != (uint16_t)(n - 1)) {      /* trailing bytes: the line is malformed */
        log_puts("ERR len\r\n");
        return;
    }
    blk_i = 0;
    blk_att = 0;
    blk_active = 1;
    batch_step();
}

/* Printed at boot and again for a V command: the host reads its capabilities
 * from this line, and the server may have started after the boot. */
static void log_banner(void)
{
    log_puts("*** ShelfKit hub, node ");
    log_hex16(SHELF_NODE_ID);
    log_puts(" net ");
    log_hex8(SHELF_NET_ID);
    log_puts(" dump=1 batch=1");
    log_nl();
}

static void host_line(void)
{
    if (line_overflow) {
        log_puts("ERR len\r\n");
    } else if (line_len) {
        if (line[0] == 'P')
            log_puts("PONG\r\n");
        else if (line[0] == 'V')
            log_banner();
        else if (line[0] == 'Q') {
            /* Q<hhhh>: the host has data for that tag; flag its next poll */
            int8_t a0 = (line_len >= 5) ? hexval(line[1]) : -1;
            int8_t a1 = (line_len >= 5) ? hexval(line[2]) : -1;
            int8_t a2 = (line_len >= 5) ? hexval(line[3]) : -1;
            int8_t a3 = (line_len >= 5) ? hexval(line[4]) : -1;
            if (a0 >= 0 && a1 >= 0 && a2 >= 0 && a3 >= 0) {
                uint16_t who = (uint16_t)((a0 << 12) | (a1 << 8) | (a2 << 4) | a3);
                uint8_t i;
                for (i = 0; i < PREARM_SLOTS; i++) {
                    if (prearmed[i] == 0 || prearmed[i] == who) {
                        prearmed[i] = who;
                        break;
                    }
                }
                /* Say when the slots are full: printing OK regardless made the
                 * host believe a tag was pre-armed when it was not, and its next
                 * poll then closed after the 500 ms grace. */
                if (i == PREARM_SLOTS) {
                    log_puts("ERR full\r\n");
                } else {
                    log_puts("OK data\r\n");
                }
            } else {
                log_puts("ERR hex\r\n");
            }
        }
        else if (line[0] == 'L') {
            /* L<hh>: ask every tag to wait hh*10 s longer before its next poll */
            int8_t hi = (line_len >= 3) ? hexval(line[1]) : -1;
            int8_t lo = (line_len >= 3) ? hexval(line[2]) : -1;
            if (hi >= 0 && lo >= 0) {
                delay_hint = (uint8_t)((hi << 4) | lo);
                log_puts("OK delay\r\n");
            } else {
                log_puts("ERR hex\r\n");
            }
        }
        else if (line[0] == 'S')
            cmd_send();
        else if (line[0] == 'B')
            cmd_batch();
        else
            log_puts("ERR cmd\r\n");
    }
    line_len = 0;
    line_overflow = 0;
}

static void host_poll(void)
{
    int16_t c;

    while ((c = host_rx_getc()) >= 0) {
        if (c == '\n') {
            host_line();
        } else if (c != '\r') {
            if (line_len < LINE_MAX)
                line[line_len++] = (char)c;
            else
                line_overflow = 1;
        }
    }
}

static void on_done(const struct sl_done __xdata *done)
{
    if (blk_active) {
        if (done->attempts > blk_att)
            blk_att = done->attempts;
        if (done->result != SL_OK) {
            /* Which frame of the batch was not acknowledged: without this the
             * only symptom is a whole batch failing, which says nothing about
             * whether it is the first frame (the tag is not listening yet) or a
             * later one (the window closed mid-transfer). */
            log_puts("BAT ");
            log_dec((uint8_t)(blk_i + 1));
            log_puts("/");
            log_dec(blk_n);
            log_puts(" no ack\r\n");
            log_puts("SENT ");
            log_hex16(blk_dst);
            log_puts(" fail att=");
            log_dec(blk_att);
            log_nl();
            blk_active = 0;
            return;
        }
        blk_i++;
        batch_step();
        return;
    }
    log_puts("SENT ");
    log_hex16(cmd_dst);
    log_puts(done->result == SL_OK ? " ok att=" : " fail att=");
    log_dec(done->attempts);
    log_nl();
}

static void on_rx(const struct sl_rx __xdata *rx)
{
    if (rx->type == SL_T_POLL) {
        uint8_t i;

        rsp[SM_RSP_CMD] = SM_CMD_NONE;
        /* The host queued something for this tag: say so in the reply, or the tag
         * closes its receiver after a 500 ms grace and the first frame of the
         * push has to win a race it usually loses. */
        for (i = 0; i < PREARM_SLOTS; i++) {
            if (prearmed[i] == rx->src) {
                prearmed[i] = 0;
                rsp[SM_RSP_CMD] = SM_CMD_DATA;
                break;
            }
        }
        rsp[SM_RSP_RSSI] = (uint8_t)(int8_t)rx->rssi;
        rsp[SM_RSP_DELAY] = delay_hint;
        sl_reply(rx, SL_T_POLL_RSP, rsp, SM_RSP_LEN);
        /* Which flag the tag was told: cmd=01 means "data follows, keep the
         * receiver open", 00 means "nothing queued, close after the grace". It
         * decides the whole push, so make it visible. */
        log_puts("RSP ");
        log_hex16(rx->src);
        log_puts(" cmd=");
        log_hex8(rsp[SM_RSP_CMD]);
        log_nl();
    }
    log_rx(rx);
    /* A tag announced itself: one short green flash. Deliberately not a
     * toggle - keeping the LED lit for the whole poll interval is what heated
     * the panel on the tag and made the frame look like a toggle here. */
    if (rx->type == SL_T_POLL)
        shelfhw_led_pulse(SHELFHW_LED_GREEN, SHELFHW_LED_PULSE_MS);
}

void main(void)
{
    uint8_t r;

    shelfhw_init();
#if SHELF_POWER_LINES
    pwr_init();
    pwr_on();
#endif
    log_puts("\r\n");
    /* dump=1: forwards tag DATA payloads (a flash read-back needs it)
     * batch=1: accepts a B line with several DATA frames (fast image pushes) */
    log_banner();

    r = sl_init(SHELF_NODE_ID, SHELF_NET_ID, on_rx, on_done);
    if (r != AXRADIO_ERR_NOERROR) {
        log_puts("radio init failed, err=");
        log_dec(r);
        log_nl();
        shelfhw_fatal(SHELFHW_LED_RED);
    }
    log_puts("radio ok, pll rng=");
    log_dec(axradio_get_pllrange());
    log_puts(", listening");
    log_nl();
    shelfhw_led_pulse(SHELFHW_LED_BLUE, SHELFHW_LED_BOOT_PULSE_MS);

    host_rx_init();
    for (;;) {
        shelfhw_poll_awake();
        host_poll();
        if (blk_active)
            batch_step();
    }
}
