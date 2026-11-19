/**
 * @file eco_rx.h
 * @brief ECO (chain code) decoder for one compressed panel plane, see eco_rx.c
 */
#ifndef ECO_RX_H
#define ECO_RX_H

#include <libmftypes.h>
#include "shelfmsg.h"

/* The compressed file of the plane being received (img_rx.c fills it). */
extern uint8_t __xdata eco_buf[SM_ECO_MAX];
/* Its length in bytes; set before eco_decode(). A global, not a parameter: the
 * tag's internal RAM has no room for one more overlaid local. */
extern uint16_t __xdata eco_len;

/* Decode eco_buf into the panel: the caller has already selected the plane with
 * epd_stream_begin(). Writes all EPD_PLANE_BYTES bytes. 1 = ok, 0 = bad file
 * (what reached the panel by then is garbage; the image will be "incomplete"). */
uint8_t eco_decode(void);

#endif /* ECO_RX_H */
