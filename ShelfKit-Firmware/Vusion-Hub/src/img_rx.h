/**
 * @file img_rx.h
 * @brief Receives an image from the hub (SM_OP_IMG_* in shelfmsg.h) straight into the e-paper
 */

#ifndef IMG_RX_H
#define IMG_RX_H

#include <libmftypes.h>

/* Feeds one DATA payload from the hub. Returns 1 if it was an image message. */
uint8_t img_rx_data(const uint8_t __xdata *payload, uint8_t len);

/* 1 while a transfer is running (and the last piece arrived less than ~10 s ago).
 * The tag keeps its own polls quiet meanwhile so they do not collide with the hub. */
uint8_t img_rx_active(void);

#endif /* IMG_RX_H */
