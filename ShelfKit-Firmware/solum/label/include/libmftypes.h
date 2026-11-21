/**
 * @file libmftypes.h
 * @brief Stand-in for the Axsem libmf type header, so the portable shared code builds here
 *
 * common/shelflink/inc/shelflink.h includes <libmftypes.h> for uint8_t and friends.
 * On the Axsem tags that comes from libmf; the ZBS243 has no libmf, so this project's own
 * include folder answers instead. SDCC keeps __xdata / __code as they are: the ZBS243 is an
 * 8051 too, with 8 KB of XRAM.
 */

#ifndef LIBMFTYPES_H
#define LIBMFTYPES_H

#include <stdint.h>

#endif /* LIBMFTYPES_H */
