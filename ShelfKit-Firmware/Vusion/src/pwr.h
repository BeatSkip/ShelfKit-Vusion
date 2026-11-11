/**
 * @file pwr.h
 * @brief Control of the transistor-driven lines PA2 (U5) and PA5 (U4)
 *
 * Measured on hardware (Documentation/pa2-pa5-findings.md):
 *
 *   PA5 -> U4  the e-paper panel supply, ACTIVE LOW. Has a strong external pull-up, so a
 *              released pin is "off". pwr_on()/pwr_off() drive it.
 *   PA2 -> U5  active HIGH, no pull-up: the pin floats and keeps whatever level it was
 *              last given. Driven high it loads the supply (about -75 mV on the bench
 *              rail) and nothing we use gets better, so the firmware only ever parks it
 *              LOW (pwr_park_u5(), called by pwr_init()). It is never switched on.
 *
 * Configure below which of the two pwr_on()/pwr_off() drive.
 */

#ifndef PWR_DRIVER_H
#define PWR_DRIVER_H

#include <ax8052f143.h>
#include <libmftypes.h>

/* Which transistors to drive: 1 = drive, 0 = leave the pin untouched */
#define PWR_USE_U4  1       /* PA5, transistor U4 */
#define PWR_USE_U5  0       /* PA2, transistor U5: keep 0 - U5 is parked off, not switched */

/* Polarity: 1 = the pin is driven HIGH to switch the transistor "on",
 * 0 = driven LOW for "on". If the load behaves inverted, flip these. */
#define PWR_U4_ACTIVE_HIGH  0
#define PWR_U5_ACTIVE_HIGH  1

/* Configure the selected pins as outputs, driving their OFF state, and park PA2 low. */
void pwr_init(void);

/* Drive PA2 (U5) to its off level (low) as an output, so it cannot float on. Safe to
 * call at any time; pwr_init() does it. */
void pwr_park_u5(void);

/* Switch all selected transistors on / off. */
void pwr_on(void);
void pwr_off(void);

/* The hub's copy also has pwr_pulse(); the tag never used it and needs the code space. */

#endif /* PWR_DRIVER_H */
