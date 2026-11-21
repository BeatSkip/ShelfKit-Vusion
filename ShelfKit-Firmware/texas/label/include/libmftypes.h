/**
 * @file libmftypes.h
 * @brief Stand-in for the Axsem libmf type header, so the portable shared code builds here
 *
 * common/shelflink/inc/shelflink.h includes <libmftypes.h> for uint8_t and friends.
 * On the Axsem tags that comes from libmf; the CC2510 has no libmf, so this project's own
 * include folder answers instead. SDCC keeps __xdata / __code as they are: the CC2510 is an
 * 8051 too, with its 4 KB of RAM mapped as XDATA at 0xF000.
 */

#ifndef LIBMFTYPES_H
#define LIBMFTYPES_H

#include <stdint.h>

#endif /* LIBMFTYPES_H */
