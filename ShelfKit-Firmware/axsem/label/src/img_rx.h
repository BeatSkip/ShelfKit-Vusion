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

/* 1 while the panel's refresh waveform is running (the radio is parked and the MCU
 * may sleep: main() polls with shelfhw_poll() instead of shelfhw_poll_awake()). */
uint8_t img_rx_refreshing(void);

/* Wake-up-timer ticks spent in refresh waveforms since boot (the panel supply is the
 * load then, not the MCU or the radio): an input of the power estimate in main.c. */
uint32_t img_rx_panel_ticks(void);

/** How the last refresh since boot ended (EPD_BUSY_*, 0xFF = none yet) and its length in
 *  0.1 s, for the extended poll. */
uint8_t img_rx_last_status(void);
uint16_t img_rx_last_ds(void);

/* Called once per poll: a panel that was left powered (a refresh that never reported
 * done, a transfer that was abandoned) is put to sleep and its rail cut. */
void img_rx_idle(void);

/* Implemented in main.c: park the radio (deep sleep) and cancel the listen window. */
void tag_radio_park(void);

#endif /* IMG_RX_H */
