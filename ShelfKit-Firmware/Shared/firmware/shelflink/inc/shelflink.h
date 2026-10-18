/**
 * @file shelflink.h
 * @brief Small acknowledged-message link layer on top of the AX5043 radio engine
 *
 * Both roles run the radio in AXRADIO_MODE_ASYNC_RECEIVE: the receiver is
 * always on, and transmitting from that mode makes the engine switch to TX
 * and fall back to RX when the packet is out. A node therefore hears the
 * answer to its own transmission without any mode juggling.
 *
 * On air (inside the engine's own frame: length byte, 3 byte address, ... CRC-16):
 *
 *   MAC address (3)   dest id lo, dest id hi, network id    - hardware filtered
 *   [0]    version (high nibble) | type (low nibble)
 *   [1]    flags
 *   [2..3] source node id, little endian
 *   [4]    sequence number
 *   [5..]  payload, 0..SL_MAX_PAYLOAD bytes
 *
 * Reliability: sl_send() is the initiator side. It transmits, waits for the
 * matching response (same destination node, same sequence number) and retries
 * with a jittered back-off until SL_MAX_ATTEMPTS is used up. The response is a
 * SL_T_ACK for SL_T_DATA and the application's SL_T_POLL_RSP for SL_T_POLL.
 * The responder side drops duplicates (a retry of a message it already
 * answered) and answers DATA automatically.
 *
 * Everything runs in the main loop context (the engine delivers its events
 * through wtimer callbacks), so no locking is needed. Keep the main loop
 * calling shelfhw_poll() and answer requests quickly: the initiator's
 * response window is SL_RSP_TIMEOUT_MS.
 */

#ifndef SHELFLINK_H
#define SHELFLINK_H

#include <libmftypes.h>

#define SL_VERSION          1

#define SL_T_POLL           1   /* initiator -> responder, answered by POLL_RSP */
#define SL_T_POLL_RSP       2   /* response to POLL, application payload        */
#define SL_T_DATA           3   /* initiator -> responder, answered by ACK      */
#define SL_T_ACK            4   /* automatic response to DATA, no payload       */

#define SL_F_RETRY          0x01    /* this transmission is a retry */

#define SL_HDR_LEN          5
#define SL_MAX_PAYLOAD      32

#define SL_NODE_HUB         0x0001u

/* Tunables - override with -D in sdcc-project.json "defines". */
#ifndef SL_RSP_TIMEOUT_MS
#define SL_RSP_TIMEOUT_MS   60      /* from the start of a transmission */
#endif
#ifndef SL_MAX_ATTEMPTS
#define SL_MAX_ATTEMPTS     4
#endif
#ifndef SL_BACKOFF_MS
#define SL_BACKOFF_MS       20      /* random 0..(SL_BACKOFF_MS * attempt) added to a fixed 5 ms */
#endif

/* Result codes (the engine's AXRADIO_ERR_* are returned as-is by sl_init) */
#define SL_OK               0
#define SL_ERR_BUSY         1   /* a request is already in flight */
#define SL_ERR_INVALID      2
#define SL_ERR_RADIO        3   /* engine refused the transmission */
#define SL_ERR_NORESPONSE   4   /* retries exhausted */

struct sl_rx {
    uint8_t type;
    uint8_t flags;
    uint16_t src;
    uint8_t seq;
    uint8_t dup;                            /* retry of a message already seen */
    uint8_t len;
    int16_t rssi;                           /* dBm */
    const uint8_t __xdata *payload;         /* valid only during the callback */
};

struct sl_stats {
    uint16_t tx_req;        /* sl_send() calls accepted                     */
    uint16_t tx_att;        /* transmissions on air, retries included       */
    uint16_t tx_ok;         /* requests that got their response             */
    uint16_t tx_fail;       /* requests that ran out of attempts            */
    uint16_t tx_err;        /* engine refused a transmission                */
    uint16_t rx_ok;         /* valid frames for us                          */
    uint16_t rx_dup;        /* ... of which duplicates                      */
    uint16_t rx_bad;        /* too short / wrong version                    */
    uint16_t rx_stray;      /* responses nobody was waiting for             */
};

extern struct sl_stats __xdata sl_stats;

/* Request received (POLL or non-duplicate DATA). For a POLL the handler must
 * answer with sl_reply(); duplicates are flagged in rx->dup. */
typedef void (*sl_rx_handler)(const struct sl_rx __xdata *rx);

/* Outcome of a request started with sl_send(). */
struct sl_done {
    uint8_t result;                         /* SL_OK or SL_ERR_NORESPONSE          */
    uint8_t attempts;                       /* transmissions it took               */
    const struct sl_rx __xdata *rsp;        /* the response, 0 if there was none   */
};

typedef void (*sl_done_handler)(const struct sl_done __xdata *done);

/* Brings the radio up in always-listening mode and sets the local address.
 * Returns an AXRADIO_ERR_* value (0 = ok, AXRADIO_ERR_NOCHIP = radio not found). */
uint8_t sl_init(uint16_t node_id, uint8_t net_id, sl_rx_handler on_rx, sl_done_handler on_done);

/* Reliable send of one POLL or DATA message to node dst. */
uint8_t sl_send(uint16_t dst, uint8_t type, const uint8_t __xdata *payload, uint8_t len);

/* One-shot answer to a received request: same sequence number, sent to the requester. */
uint8_t sl_reply(const struct sl_rx __xdata *to, uint8_t type, const uint8_t __xdata *payload, uint8_t len);

/* 1 while a request started with sl_send() is still in flight. */
uint8_t sl_busy(void);

#endif /* SHELFLINK_H */
