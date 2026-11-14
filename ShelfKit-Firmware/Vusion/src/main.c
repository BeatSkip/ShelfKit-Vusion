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
#include "shelfver.h"
#include "shelf_config.h"
#include "fw_rx.h"
#include "img_rx.h"
#include "pwr.h"
#include "shelf_id.h"
#include "nfc_cfg.h"

static struct wtimer_desc __xdata poll_timer;
static uint8_t __xdata poll_payload[SM_POLL_EXT2_LEN];
static uint8_t __xdata poll_len;
/* the poll for a tap carries the firmware version and the power figures; it stays set until
 * one such poll was acknowledged, so the 5 s follow-up repeats it if the first was lost */
static uint8_t __xdata nfc_info;
static uint8_t __xdata last_attempts;
static int8_t __xdata last_hub_rssi;
static uint16_t __xdata polls_done;
/* the power summary's arithmetic, kept in XRAM: the tag has no internal RAM to
 * spare for 32-bit locals. pow_total_ms holds seconds inside pow_update() and is reused
 * as scratch by poll_cb(). */
static uint32_t __xdata pow_awake_ms, pow_radio_ms, pow_asleep_s, pow_total_ms, pow_ua;
static uint32_t __xdata pow_t, pow_q;   /* scratch: a span in ticks, and what it was scaled to */
static uint32_t __xdata pow_uas;        /* charge since boot: 0.1 mA * ticks, then uA*s */
/* work that must not run while the receiver is on: done by listen_cb() once it is parked */
static uint8_t __xdata stats_due;
static uint8_t __xdata fail_led_due;
static uint16_t __xdata node_id;   /* from the SPI flash record, see shelf_id.c */
#if SHELF_NFC_POLL
/* A reader gives one or two edges per visit. A line that is floating or held can
 * produce hundreds, so the feature protects the battery by itself: after this many
 * events in one poll cycle it stops reacting until listen_cb() resets the count. */
#define SHELF_NFC_BURST_MAX  3
static uint8_t __xdata nfc_burst;
/* A pin that is stuck or floating re-triggers every poll cycle, which an in-cycle burst limit
 * cannot stop: the tag polled every 1.8 s for minutes on hardware with the rail off. So also
 * count consecutive cycles that were started by an NFC event; after SHELF_NFC_CHAIN_MAX of
 * them the feature is suspended for SHELF_NFC_HOLDOFF_POLLS normal poll cycles (~1 h). A real
 * phone visit is one or two cycles. */
#define SHELF_NFC_CHAIN_MAX     4
#define SHELF_NFC_HOLDOFF_POLLS 30
static uint8_t __xdata nfc_src;         /* what woke it: 1 irq, 2 port-change wake */
static uint8_t __xdata nfc_seen;        /* an NFC event started this cycle */
static uint8_t __xdata nfc_chain;       /* consecutive such cycles */
static uint8_t __xdata nfc_hold;        /* cycles left with the feature suspended */
/* A tap is the user asking for a refresh, but the hub's queue is armed only for the poll
 * *after* one that found it busy or empty. So a tap polls at once and once more 5 s later:
 * a second chance for the server to have the transfer ready, paid only on a tap. */
#define SHELF_NFC_FOLLOW_S      5
static uint8_t __xdata nfc_follow;      /* the follow-up poll after a tap is still due */
static uint8_t __xdata nfc_fu;          /* this cycle is a follow-up: not a new trigger */
#endif
static struct wtimer_desc __xdata listen_timer;
static uint8_t __xdata radio_asleep;

/* Adaptive check-in (openepaperlink-style backoff): the configured interval is
 * only the starting point. `fails` counts consecutive unanswered polls and
 * `poll_due_s` is what is left of the current - possibly much longer - gap,
 * because one wake-up-timer arm only reaches ~100 s. */
static uint16_t __xdata fails;
static uint32_t __xdata poll_due_s;
static uint32_t __xdata ap_delay_s;     /* delay the hub asked for, seconds */
/* burst polling: the last reply said "data follows" (data_pending), how many polls
 * in a row did (active_polls), and how many cool-down polls are left after it */
static uint8_t __xdata data_pending;
static uint8_t __xdata active_polls;
static uint8_t __xdata cooldown_left;

/* Arm the next check-in `seconds` from now, capped to one timer arm. */
static void arm_poll(uint32_t seconds) __reentrant
{
    uint32_t arm = (seconds > SHELF_POLL_ARM_MAX_S) ? SHELF_POLL_ARM_MAX_S : seconds;

    if (!arm)
        arm = 1;
    poll_due_s = seconds;
    wtimer0_remove(&poll_timer);
    poll_timer.time = arm * SHELFHW_TICKS_PER_S;
    wtimer0_addrelative(&poll_timer);
}

/* How long to wait before the next check-in, from the last result. */
static uint32_t next_interval(void) __reentrant
{
    uint32_t interval = SHELF_POLL_INTERVAL_S;
    uint32_t uptime_s = wtimer0_curtime() / SHELFHW_TICKS_PER_S;

    if (fails) {
        if (fails >= SHELF_FAIL_TO_HOUR) {
            /* no hub for a long time: hourly, then two-hourly, then daily */
            if (uptime_s >= 2UL * 86400UL)
                interval = SHELF_LOST_2DAY_S;
            else if (uptime_s >= 86400UL)
                interval = SHELF_LOST_DAY_S;
            else
                interval = SHELF_LOST_HOUR_S;
        } else {
            /* 2x, 4x, 8x ... capped at 10 min */
            uint8_t shift = (fails > 6) ? 6 : (uint8_t)fails;
            interval = (uint32_t)SHELF_POLL_INTERVAL_S << shift;
            if (interval > SHELF_POLL_MAX_S)
                interval = SHELF_POLL_MAX_S;
        }
#if SHELF_NFC_POLL
    } else if (nfc_follow) {
        interval = SHELF_NFC_FOLLOW_S;     /* a tap: one more try shortly, whatever the reply said */
        nfc_follow = 0;
        nfc_fu = 1;
#endif
    } else if (data_pending && active_polls < SHELF_ACTIVE_MAX_POLLS) {
        /* the hub is feeding this tag: come back soon for the next item */
        interval = SHELF_POLL_ACTIVE_S;
    } else if (cooldown_left) {
        /* data just ended: drop to a slow rate, then to idle */
        cooldown_left--;
        interval = SHELF_POLL_COOLDOWN_S;
        if (interval > shelf_cfg_poll_s())      /* never slower than the idle rate itself */
            interval = shelf_cfg_poll_s();
    } else {
        /* The idle rate: what the server configured (SM_OP_SET_POLL, kept in the SPI
         * flash, see shelf_id.h) or the default SHELF_POLL_IDLE_S. Asked for on every
         * arm, so a change takes effect with the very next interval. */
        interval = shelf_cfg_poll_s();
        /* the hub hears us badly: retrying costs more than waiting */
        if (last_hub_rssi < SHELF_WEAK_RSSI_DBM && interval < SHELF_POLL_MAX_S)
            interval = SHELF_POLL_MAX_S;
    }

    if (ap_delay_s > interval)          /* the hub asked for a longer gap */
        interval = ap_delay_s;
    return interval;
}

/* pow_q = pow_t wake-up-timer ticks in milliseconds (1000/512 = 125/64, 1000/640 = 125/80) */
static void pow_ms(void)
{
    pow_q = pow_t * 125u / (SHELFHW_TICKS_PER_S / 8u);
}

/* The software ammeter's numbers, refreshed from the counters (currents: shelf_config.h).
 *
 * The currents of the active states are summed as ticks * 0.1 mA, which stays inside 32
 * bits for a day of receiver time, and only then turned into uA*s. Standby goes in at
 * 0.1 mA (85 uA in the datasheet): it only happens while the receiver is on, so it is a
 * rounding error next to that. Sleep and the transmitter bursts are added in uA*s directly.
 * The average is charge / uptime in seconds; the old sum in uA*ms wrapped after 16 days
 * asleep, and from then on the average came out far too low. Everything is file-scope
 * XRAM: a local or a parameter here costs internal RAM the tag does not have. */
static void pow_update(void)
{
    pow_t = shelfhw_radio_on_ticks();
    pow_ms();
    pow_radio_ms = pow_q;
    pow_uas = pow_t * (SHELF_PWR_RADIO_UA / 100u)
            + img_rx_panel_ticks() * (SHELF_PWR_PANEL_UA / 100u);

    pow_t = shelfhw_awake_ticks();
    pow_ms();
    pow_awake_ms = pow_q;
    pow_uas += pow_t * (SHELF_PWR_MCU_UA / 100u);
    pow_t += shelfhw_standby_ticks();               /* every tick not spent in Sleep */
    pow_uas += shelfhw_standby_ticks();             /* Standby at 0.1 mA */

    pow_asleep_s = shelfhw_asleep_s();
    pow_uas = pow_uas / SHELFHW_TICKS_PER_S * 100u
            + pow_asleep_s * SHELF_PWR_SLEEP_UA
            + sl_tx_frames * SHELF_PWR_TX_UAS;

    pow_total_ms = pow_t / SHELFHW_TICKS_PER_S + pow_asleep_s;      /* uptime, in seconds */
    pow_ua = pow_total_ms ? pow_uas / pow_total_ms : 0;
}

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

    /* Software ammeter: awake/radio in ms, asleep in s, counted since boot. pow_update()
     * multiplies them - and the standby time, the frames sent and the panel's refresh
     * time - by the currents in shelf_config.h. */
    pow_update();

    log_puts("pow awake=");
    log_dec32(pow_awake_ms);
    log_puts("ms radio=");
    log_dec32(pow_radio_ms);
    log_puts("ms asleep=");
    log_dec32(pow_asleep_s);
    log_puts("s avg=");
    log_dec32(pow_ua);
    log_puts("uA");
    if (pow_ua) {
        /* 620 mAh CR2450 -> 620000 uAh; days = 620000 / uA / 24 */
        log_puts(" life=");
        log_dec32(25833u / pow_ua);
        log_puts("d");
    }
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
    /* Held back by on_done() until here: both used to run with the receiver on, which made
     * a 50 ms LED pulse or a statistics line cost several times what it does now. */
    if (fail_led_due) {
        fail_led_due = 0;
        shelfhw_led_pulse(SHELFHW_LED_RED, SHELFHW_LED_PULSE_MS);
    }
    if (stats_due) {
        stats_due = 0;
        log_stats();
    }
#if SHELF_NFC_POLL
    nfc_burst = 0;              /* new cycle: a reader is welcome again */
    if (nfc_seen) {
        if (nfc_chain < 255)
            nfc_chain++;
    } else if (!nfc_fu) {
        nfc_chain = 0;          /* a follow-up poll keeps the chain, a quiet cycle ends it */
    }
    nfc_seen = 0;
    nfc_fu = 0;
    if (nfc_chain >= SHELF_NFC_CHAIN_MAX) {
        nfc_chain = 0;
        nfc_hold = SHELF_NFC_HOLDOFF_POLLS;
        log_puts("nfc storm: pin keeps triggering, off for a while\r\n");
    }
    if (nfc_hold)
        nfc_hold--;             /* suspended: not armed, so neither the interrupt nor the wake */
    else if (shelfhw_nfc_level())
        shelfhw_nfc_arm();      /* one shot: ready for the next reader (pin idle high) */
#endif
#else
    (void)desc;
#endif
}

/* on_done's working values live in XRAM: the tag's internal RAM is full to the byte, and
 * a single extra local here is enough to make the link fail ("11 consecutive bytes in
 * internal RAM for area OSEG"). */
static uint8_t __xdata rsp_ok;          /* this poll got a full reply */
static uint8_t __xdata rsp_data;        /* ... and it says data follows */
static uint16_t __xdata listen_ms;
#define RSP  (done->rsp)

#if SHELF_RADIO_SLEEP
/* The radio is not needed for the next seconds (the panel is refreshing): park it now
 * rather than at the end of a listening window. poll_cb() wakes it for the next poll. */
void tag_radio_park(void)
{
    wtimer0_remove(&listen_timer);
    if (!radio_asleep) {
        log_puts("sleep\r\n");
        shelfhw_radio_sleep();
        radio_asleep = 1;
    }
}
#else
void tag_radio_park(void) {}
#endif

static void on_done(const struct sl_done __xdata *done)
{
    /* a frame from the flash read-back: handled there, and not a poll result */
    if (fw_dump_done(done->result))
        return;

    polls_done++;
    last_attempts = done->attempts;
    rsp_ok = (done->result == SL_OK && RSP->len >= SM_RSP_LEN);
    rsp_data = (rsp_ok && RSP->payload[SM_RSP_CMD] == SM_CMD_DATA);

    /* The normal case is silent: green means "an image is starting" now, and a
     * per-poll flash (or a latched level) kept an LED lit almost permanently,
     * which is exactly the heat that shows up on the panel. */
    if (done->result == SL_OK) {
        fails = 0;
        nfc_info = 0;      /* the hub has the version now */
        log_puts("poll ok att=");
        log_dec(done->attempts);
        log_puts(" rssi=");
        log_sdec(RSP->rssi);
        if (rsp_ok) {
            last_hub_rssi = (int8_t)RSP->payload[SM_RSP_RSSI];
            ap_delay_s = (uint32_t)RSP->payload[SM_RSP_DELAY] * 10UL;
            log_puts(" hubrssi=");
            log_sdec(last_hub_rssi);
        } else {
            ap_delay_s = 0;
        }
        log_nl();
        if (rsp_data) {
            data_pending = 1;
            if (active_polls < 255)
                active_polls++;
            cooldown_left = SHELF_COOLDOWN_POLLS;
        } else {
            data_pending = 0;
            active_polls = 0;
        }
    } else {
        data_pending = 0;
        active_polls = 0;
        if (fails != 0xFFFF)
            fails++;
        log_puts("poll FAILED after ");
        log_dec(done->attempts);
        log_puts(" attempts");
        log_nl();
#if SHELF_RADIO_SLEEP
        fail_led_due = 1;       /* red = poll failed, shown once the receiver is off */
#else
        shelfhw_led_pulse(SHELFHW_LED_RED, SHELFHW_LED_PULSE_MS);
#endif
    }

    if (polls_done % SHELF_STATS_EVERY == 0) {
#if SHELF_RADIO_SLEEP
        stats_due = 1;          /* printed by listen_cb() once the radio is parked */
#else
        log_stats();
#endif
    }

#if SHELF_RADIO_SLEEP
    /* Re-arm the listening window from the reply in BOTH cases, so "data follows"
     * and "nothing queued" differ only in how long it stays open. Re-arming only
     * in the quiet case left a pre-armed poll running on the timer that was armed
     * before the poll was even sent - and on hardware that polled fine, was told
     * cmd=01, and then never received the first frame of the push. */
    {
        if (data_pending)
            listen_ms = (uint16_t)SHELF_LISTEN_WINDOW_S * 1000u;
        else if (rsp_ok)
            listen_ms = SHELF_LISTEN_QUIET_MS;     /* the hub said nothing follows */
        else
            listen_ms = SHELF_LISTEN_GRACE_MS;     /* no usable reply: be patient */

        wtimer0_remove(&listen_timer);
        /* ms -> ticks in 16 bits: ms * tps / 1000 = (ms/8) * (tps/8) * 2 / 31.25, i.e.
         * within ~1 % and never above 40000 - 32-bit maths here costs internal RAM the
         * tag does not have */
        listen_timer.time = (uint16_t)(((listen_ms >> 3) * (SHELFHW_TICKS_PER_S >> 3) * 2u) / 31u);
        if (!listen_timer.time)
            listen_timer.time = 1;          /* sleep on the next tick, not never */
        wtimer0_addrelative(&listen_timer);
    }
#endif

    arm_poll(next_interval());
}
#undef RSP

static void on_rx(const struct sl_rx __xdata *rx)
{
    if (rx->type != SL_T_DATA)
        return;
    /* A push that started after the poll reply (the server sends when it sees the
     * poll, so CMD_DATA was not set): the hub is feeding us, so poll again soon
     * instead of waiting out the idle gap armed a moment ago. Once per burst. */
    if (!data_pending) {
        data_pending = 1;
        active_polls = 0;
        cooldown_left = SHELF_COOLDOWN_POLLS;
        arm_poll(SHELF_POLL_ACTIVE_S);
    }
    /* image opcodes are below SM_OP_FW_BEGIN, plus the compressed-plane pair */
    if (rx->len && rx->payload[0] >= SM_OP_FW_BEGIN
        && rx->payload[0] != SM_OP_IMG_ZCHUNK && rx->payload[0] != SM_OP_IMG_ZEND)
        (void)fw_rx_data(rx->payload, rx->len);
    else
        (void)img_rx_data(rx->payload, rx->len);
}

static void poll_cb(struct wtimer_desc __xdata *desc)
{
    uint16_t up = (uint16_t)(wtimer0_curtime() / SHELFHW_TICKS_PER_S);

    (void)desc;

    /* A backoff longer than one timer arm: wake just to step the countdown, and arm
     * only what is LEFT. Arming the full cap again here is how a 120 s interval became
     * 200 s (100 + 100 instead of 100 + 20) - invisible at 60 s, where this never ran. */
    if (poll_due_s > SHELF_POLL_ARM_MAX_S) {
        poll_due_s -= SHELF_POLL_ARM_MAX_S;     /* the arm that just elapsed */
        arm_poll(poll_due_s);                   /* arms min(remaining, cap) */
        return;
    }
    poll_due_s = 0;
    img_rx_idle();                  /* a panel left powered is put to sleep here */

    /* a transfer or a read-back owns the link: try again shortly */
    if (img_rx_active() || fw_rx_active() || fw_dump_active()) {
        arm_poll(SHELF_POLL_ACTIVE_S);
        return;
    }

    /* The battery voltage, taken BEFORE the receiver wakes. A CR2450 has ~10-20 ohm of
     * internal resistance, so with the receiver on (~12 mA with the CPU) it reads
     * 150-250 mV low - a full cell showed 2.75 V, which the server's curve calls half
     * empty. Here the cell has rested since the last poll and only the CPU is running. */
    {
        uint16_t vdd = shelfhw_measure_vdd();
        poll_payload[SM_POLL_VDD_LO] = (uint8_t)vdd;
        poll_payload[SM_POLL_VDD_HI] = (uint8_t)(vdd >> 8);
    }

#if SHELF_RADIO_SLEEP
    /* wake the radio for this poll and open the listening window */
    if (radio_asleep) {
        log_puts("wake\r\n");
        if (shelfhw_radio_wake() != AXRADIO_ERR_NOERROR) {
            /* still asleep as far as the engine knows: try again next time */
            log_puts("radio wake failed\r\n");
            fails++;
            arm_poll(SHELF_POLL_INTERVAL_S);
            return;
        }
        radio_asleep = 0;
        {
            uint8_t __xdata snap[8];
            uint8_t i;

            axradio_dbg_snapshot(snap);
            log_puts("radio");
            for (i = 0; i < 8; i++) {
                log_puts(" ");
                log_hex8(snap[i]);
            }
            log_nl();
        }
    }
    listen_timer.time = (uint32_t)SHELF_LISTEN_WINDOW_S * SHELFHW_TICKS_PER_S;
    wtimer0_addrelative(&listen_timer);
#endif

    poll_payload[SM_POLL_UPTIME_LO] = (uint8_t)up;
    poll_payload[SM_POLL_UPTIME_HI] = (uint8_t)(up >> 8);
    poll_payload[SM_POLL_ATTEMPTS] = last_attempts;
    poll_payload[SM_POLL_RSSI] = (uint8_t)last_hub_rssi;

    poll_len = SM_POLL_LEN;
    if (nfc_info) {
        /* only for the first poll after a reset and a poll the user started with a tap:
         * which firmware this is and how the battery is doing. Nothing extra goes over
         * the air on a normal poll. */
        pow_update();
        /* the same bytes a tool reads from the .hex: one source of truth */
        poll_payload[SM_POLL_FW_MAJOR] = shelf_fw_info[SHELF_FW_INFO_MAJOR];
        poll_payload[SM_POLL_FW_MINOR] = shelf_fw_info[SHELF_FW_INFO_MINOR];
        poll_payload[SM_POLL_FW_PATCH] = shelf_fw_info[SHELF_FW_INFO_PATCH];
        poll_payload[SM_POLL_FW_BUILD_LO] = shelf_fw_info[SHELF_FW_INFO_BLO];
        poll_payload[SM_POLL_FW_BUILD_HI] = shelf_fw_info[SHELF_FW_INFO_BHI];
        if (pow_ua > 0xFFFFUL)
            pow_ua = 0xFFFFUL;
        poll_payload[SM_POLL_AVG_UA_LO] = (uint8_t)pow_ua;
        poll_payload[SM_POLL_AVG_UA_HI] = (uint8_t)(pow_ua >> 8);
        pow_total_ms = pow_ua ? 25833UL / pow_ua : 0xFFFFUL;   /* days on a 620 mAh cell */
        if (pow_total_ms > 0xFFFFUL)
            pow_total_ms = 0xFFFFUL;
        poll_payload[SM_POLL_LIFE_D_LO] = (uint8_t)pow_total_ms;
        poll_payload[SM_POLL_LIFE_D_HI] = (uint8_t)(pow_total_ms >> 8);
        /* how the last refresh went: "busy=1 14.6s" without a serial cable */
        poll_payload[SM_POLL_IMG_ST] = img_rx_last_status();
        poll_payload[SM_POLL_IMG_DS_LO] = (uint8_t)img_rx_last_ds();
        poll_payload[SM_POLL_IMG_DS_HI] = (uint8_t)(img_rx_last_ds() >> 8);
        poll_len = SM_POLL_EXT2_LEN;
    }
    if (sl_send(SL_NODE_HUB, SL_T_POLL, poll_payload, poll_len) != SL_OK) {
        log_puts("poll skipped, previous still in flight\r\n");
        arm_poll(SHELF_POLL_INTERVAL_S);   /* no callback will come, re-arm here */
    }
    /* on success the link's on_done() arms the next check-in */
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
    shelf_cfg_boot();               /* the stored check-in interval, if there is one */

#if SHELF_NFC_PROBE
    /* Read-only: the UID and the configuration area, for when this work resumes. */
    nfc_probe();
#endif
#if SHELF_NFC_POLL && SHELF_NFC_RAIL_HOLD
    extflash_power_up();        /* and leave it up: the NFC chip needs VCC to drive FD */
#endif
#if SHELF_NFC_POLL
    /* The NFC chip's field-detect pin has to be selected before the interrupt on
     * PB3 can ever see a reader; the SPI bus is up by now. */
    nfc_cfg_fd();
#endif

    log_puts("\r\n*** ShelfKit tag, node ");
    log_hex16(node_id);
    log_puts(" net ");
    log_hex8(SHELF_NET_ID);
    log_puts(" dump=1");
    log_puts(" fw=");
    log_dec(SHELF_FW_MAJOR);
    log_puts(".");
    log_dec(SHELF_FW_MINOR);
    log_puts(".");
    log_dec(SHELF_FW_PATCH);
    log_puts("-");
    log_dec(SHELF_FW_BUILD);
    log_nl();

    r = sl_init(node_id, SHELF_NET_ID, on_rx, on_done);
    if (r != AXRADIO_ERR_NOERROR) {
        log_puts("radio init failed, err=");
        log_dec(r);
        log_nl();
        shelfhw_fatal(SHELFHW_LED_RED);
    }
#if SHELF_NFC_POLL
    log_puts("nfc fd pin=");
    log_dec((uint8_t)(shelfhw_nfc_level() & 1u));
    log_puts(" extirq=");
    log_hex8(shelfhw_nfc_extirq());
    log_nl();
#endif
    log_puts("radio ok, pll rng=");
    log_dec(axradio_get_pllrange());
    log_puts(", polling every ");
    log_dec(shelf_cfg_poll_s());
    log_puts(" s");
    log_nl();
    shelfhw_log_boot_done();
    shelfhw_led_pulse(SHELFHW_LED_BLUE, SHELFHW_LED_BOOT_PULSE_MS);

    poll_timer.handler = poll_cb;
    /* The first poll after any reset - power-up, OTA update, watchdog - carries the firmware
     * version, so the server knows what every tag runs without a tap. It repeats until the hub
     * acknowledges one, like a tap's. (Its avg/life figures cover only the boot seconds.) */
    nfc_info = 1;
    arm_poll(1);                    /* first check-in one second after boot */

    /* armed by poll_cb, not before: an un-armed descriptor is simply not linked */
    listen_timer.handler = listen_cb;

    /* While an image or a firmware image arrives the tag must hear every frame,
     * so no standby */
    for (;;) {
#if SHELF_NFC_POLL
        nfc_src = shelfhw_nfc_take();
        if (nfc_src) {
            if (nfc_burst < SHELF_NFC_BURST_MAX) {
                nfc_burst++;
                nfc_seen = 1;
                nfc_info = 1;           /* this poll carries version + power stats */
                nfc_follow = 1;         /* and once more 5 s after the tap */
                /* A reader appeared. The LED is the point: on a battery board with no
                 * serial attached it is the only way to see that the field-detect line
                 * works. Then poll while the phone is still there. */
                shelfhw_led_pulse(SHELFHW_LED_BLUE, SHELFHW_LED_PULSE_MS);
                log_puts(nfc_src == 2 ? "nfc field (wake) pb3=" : "nfc field (irq) pb3=");
                log_dec((uint16_t)(shelfhw_nfc_level() & 1u));
                log_nl();
                arm_poll(1);
            } else if (nfc_burst == SHELF_NFC_BURST_MAX) {
                nfc_burst++;    /* one line, then silence until the next poll */
                log_puts("nfc noisy, ignoring until next poll\r\n");
            }
        }
#endif
        if (fw_dump_active())
            fw_dump_step();
        if ((img_rx_active() && !img_rx_refreshing()) || fw_rx_active() || fw_dump_active())
            shelfhw_poll_awake();
        else
            shelfhw_poll();
    }
}
