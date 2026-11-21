#include "sl_proto.h"

#define SL_PEERS 8

static struct {
    uint16_t src;
    uint8_t seq;
    uint8_t used;
} __xdata peers[SL_PEERS];
static uint8_t __xdata peer_next;

uint8_t sl_frame_build(uint8_t __xdata *buf, uint8_t type, uint8_t flags, uint16_t src,
                       uint8_t seq, const uint8_t __xdata *payload, uint8_t len)
{
    uint8_t i;

    if (len > SL_MAX_PAYLOAD)
        return 0;
    buf[0] = (uint8_t)((SL_VERSION << 4) | (type & 0x0F));
    buf[1] = flags;
    buf[2] = (uint8_t)src;
    buf[3] = (uint8_t)(src >> 8);
    buf[4] = seq;
    for (i = 0; i < len; i++)
        buf[SL_HDR_LEN + i] = payload[i];
    return (uint8_t)(SL_HDR_LEN + len);
}

uint8_t sl_frame_parse(const uint8_t __xdata *buf, uint8_t len, struct sl_rx __xdata *out)
{
    uint8_t type;

    if (len < SL_HDR_LEN || len > SL_HDR_LEN + SL_MAX_PAYLOAD)
        return 0;
    if ((buf[0] >> 4) != SL_VERSION)
        return 0;
    type = buf[0] & 0x0F;
    if (type < SL_T_POLL || type > SL_T_ACK)
        return 0;
    out->type = type;
    out->flags = buf[1];
    out->src = (uint16_t)buf[2] | ((uint16_t)buf[3] << 8);
    out->seq = buf[4];
    out->len = (uint8_t)(len - SL_HDR_LEN);
    out->payload = &buf[SL_HDR_LEN];
    return 1;
}

uint8_t sl_dedupe(uint16_t src, uint8_t seq)
{
    uint8_t i;

    for (i = 0; i < SL_PEERS; i++) {
        if (peers[i].used && peers[i].src == src) {
            if (peers[i].seq == seq)
                return 1;
            peers[i].seq = seq;
            return 0;
        }
    }
    /* unknown source: take the next slot round-robin */
    peers[peer_next].src = src;
    peers[peer_next].seq = seq;
    peers[peer_next].used = 1;
    peer_next = (uint8_t)((peer_next + 1) % SL_PEERS);
    return 0;
}

void sl_dedupe_reset(void)
{
    uint8_t i;

    for (i = 0; i < SL_PEERS; i++)
        peers[i].used = 0;
    peer_next = 0;
}
