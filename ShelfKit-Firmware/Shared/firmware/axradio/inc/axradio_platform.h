/**
 * @file axradio_platform.h
 * @brief Glue between the vendor radio engine (easyax5043.c) and the application
 *
 * Replaces the vendor misc.h of the AX-RadioLab template, keeping only what the
 * engine needs: two byte-order helper structs and the two hooks that switch the
 * radio interrupt at the MCU pin. The hooks are implemented in the shelfhw component.
 */

#ifndef AXRADIO_PLATFORM_H
#define AXRADIO_PLATFORM_H

#include "axradio.h"

struct u32endian {
	uint8_t b0;
	uint8_t b1;
	uint8_t b2;
	uint8_t b3;
};

struct u16endian {
	uint8_t b0;
	uint8_t b1;
};

extern void enable_radio_interrupt_in_mcu_pin(void);
extern void disable_radio_interrupt_in_mcu_pin(void);

#endif /* AXRADIO_PLATFORM_H */
