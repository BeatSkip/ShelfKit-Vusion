/**
 * @file cc2510.h
 * @brief The few CC2510 special function registers the skeleton touches
 *
 * Addresses from the CC2510Fx/CC2511Fx datasheet (SWRS055), "SFR overview". Add the rest
 * (radio, timers, USART, DMA) as the drivers arrive, or replace this with TI's ioCC2510.h.
 */

#ifndef CC2510_H
#define CC2510_H

__sfr __at (0x80) P0;
__sfr __at (0x90) P1;
__sfr __at (0xA0) P2;
__sfr __at (0xFD) P0DIR;
__sfr __at (0xFE) P1DIR;
__sfr __at (0xFF) P2DIR;
__sfr __at (0xF3) P0SEL;
__sfr __at (0xF4) P1SEL;
__sfr __at (0xF5) P2SEL;

__sfr __at (0xBE) SLEEP;        /* bit 2 OSC_PD, bit 6 XOSC_STB, bits 1:0 MODE */
__sfr __at (0xC6) CLKCON;       /* bit 7 OSC32K, bit 6 OSC, bits 5:3 TICKSPD, 2:0 CLKSPD */
__sfr __at (0xC9) WDCTL;

#define SLEEP_OSC_PD    0x04
#define SLEEP_XOSC_STB  0x40
#define CLKCON_OSC      0x40

#endif /* CC2510_H */
