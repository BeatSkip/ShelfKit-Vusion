/**
 * @file libmftypes.h
 * @brief Stand-in for the Axsem libmf type header, so the portable shared code builds here
 *
 * Shared/firmware/shelflink/inc/shelflink.h includes <libmftypes.h> for uint8_t and friends,
 * and the shared headers use SDCC's 8051 memory-space keywords. On a Cortex-M there is one
 * flat address space, so they mean nothing and are defined away.
 */

#ifndef LIBMFTYPES_H
#define LIBMFTYPES_H

#include <stdint.h>

#define __xdata
#define __data
#define __idata
#define __pdata
#define __code

#endif /* LIBMFTYPES_H */
