/**
 * @file zbs243.h
 * @brief The ZBS243 special function registers the skeleton relies on
 *
 * The ZBS243 has no public datasheet; what is known about it comes from reverse engineering
 * (Dmitry Grinberg's work, used by the OpenEPaperLink and openESL firmware). Only the
 * standard 8051 core registers are declared here, because their addresses are fixed by the
 * 8051 architecture. The chip-specific ones - pin direction and function, clock speed,
 * watchdog, radio, SPI, the info page - are TODO(soc): take their addresses from a verified
 * source (the zbs243 headers of those projects) before a driver uses them.
 */

#ifndef ZBS243_H
#define ZBS243_H

/* 8051 core: the port latches */
__sfr __at (0x80) P0;
__sfr __at (0x90) P1;
__sfr __at (0xA0) P2;

/* TODO(soc): P0DIR / P1DIR / P2DIR, the pin function selects, the clock speed register,
 * the watchdog. Until the watchdog is known, assume the boot ROM may leave it running. */

#endif /* ZBS243_H */
