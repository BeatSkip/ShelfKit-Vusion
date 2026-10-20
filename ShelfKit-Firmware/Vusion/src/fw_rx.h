/**
 * @file fw_rx.h
 * @brief Firmware receiver: stores an OTA image in the SPI flash
 */

#ifndef FW_RX_H
#define FW_RX_H

#include <libmftypes.h>

/**
 * Handle one DATA payload if it is a firmware opcode (SM_OP_FW_*).
 * Returns 1 when the payload was consumed, 0 when it is not ours.
 */
uint8_t fw_rx_data(const uint8_t __xdata *payload, uint8_t len);

/** 1 while a transfer is in progress (used to keep the tag awake). */
uint8_t fw_rx_active(void);

#endif /* FW_RX_H */
