/**
 * @file pwr.c
 * @brief Control of the transistor-driven lines PA2 (U5) and PA5 (U4)
 *
 * Pins are only touched when their PWR_USE_x define is 1; untouched pins
 * keep whatever function they had before. On/off levels per pin come from
 * the PWR_x_ACTIVE_HIGH defines in pwr.h.
 */

#include "pwr.h"

/* Bit mask of the selected pins in PORTA/DIRA */
static uint8_t pwr_mask(void)
{
    uint8_t m = 0;
#if PWR_USE_U4
    m |= 0x20;                  /* PA5 */
#endif
#if PWR_USE_U5
    m |= 0x04;                  /* PA2 */
#endif
    return m;
}

/* PORTA bits that mean "on" for each selected pin */
static uint8_t pwr_on_level(void)
{
    uint8_t l = 0;
#if PWR_USE_U4
    if (PWR_U4_ACTIVE_HIGH)
        l |= 0x20;
#endif
#if PWR_USE_U5
    if (PWR_U5_ACTIVE_HIGH)
        l |= 0x04;
#endif
    return l;
}

void pwr_park_u5(void)
{
    /* PA2 has no pull resistor: released, it holds a stray level and can leave U5 on.
     * The vendor start-up leaves it an analog input, which is why a normal boot is
     * fine, but nothing guarantees that after a wake. Output low = U5 off. */
    ANALOGA &= (uint8_t)~0x04;
    PORTA &= (uint8_t)~0x04;
    DIRA |= 0x04;
}

void pwr_init(void)
{
    pwr_park_u5();
    DIRA |= pwr_mask();         /* selected pins become outputs */
    pwr_off();
}

void pwr_on(void)
{
    uint8_t m = pwr_mask();
    PORTA = (uint8_t)((PORTA & (uint8_t)~m) | pwr_on_level());
}

void pwr_off(void)
{
    uint8_t m = pwr_mask();
    /* off level per pin = complement of its on level, within the mask */
    PORTA = (uint8_t)((PORTA & (uint8_t)~m) | ((uint8_t)~pwr_on_level() & m));
}
