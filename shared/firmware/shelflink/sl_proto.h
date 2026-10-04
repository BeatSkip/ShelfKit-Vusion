/**
 * @file sl_proto.h
 * @brief Pure frame and duplicate-filter logic of shelflink (no radio, no timers)
 */

#ifndef SL_PROTO_H
#define SL_PROTO_H

#include "shelflink.h"

/* Writes the header and payload into buf (SL_HDR_LEN + SL_MAX_PAYLOAD bytes at
 * most). Returns the frame length, 0 if the payload is too long. */
uint8_t sl_frame_build(uint8_t __xdata *buf, uint8_t type, uint8_t flags, uint16_t src,
                       uint8_t seq, const uint8_t __xdata *payload, uint8_t len);

/* Parses a received frame of len bytes. Returns 1 and fills out (dup and rssi
 * are left to the caller), or 0 for a short frame, wrong version or unknown type. */
uint8_t sl_frame_parse(const uint8_t __xdata *buf, uint8_t len, struct sl_rx __xdata *out);

/* Duplicate filter: remembers the last sequence number seen per source node.
 * Returns 1 if (src, seq) equals the last message from src, otherwise records
 * it and returns 0. */
uint8_t sl_dedupe(uint16_t src, uint8_t seq);

/* Forgets all sources. */
void sl_dedupe_reset(void);

#endif /* SL_PROTO_H */
