/**
 * @file fwinfo.c
 * @brief The build stamp as data, so the version can be read from a .hex file
 *
 * Same ten bytes as the Axsem firmware (axsem/shared/shelfhw/shelfhw.c, layout in
 * shelfver.h): 'S' 'K' 'F' 'W', major, minor, patch, build (LE), check. build-all.py
 * refuses an image that does not carry exactly the numbers it stamped.
 */

#include <libmftypes.h>
#include "shelfver.h"

#define FWI_SUM (0x53 + 0x4B + 0x46 + 0x57 + SHELF_FW_MAJOR + SHELF_FW_MINOR + SHELF_FW_PATCH \
                 + (SHELF_FW_BUILD & 0xFF) + ((SHELF_FW_BUILD >> 8) & 0xFF))

__attribute__((section(".fwinfo"), used))
const __code unsigned char shelf_fw_info[SHELF_FW_INFO_LEN] = {
    'S', 'K', 'F', 'W',
    SHELF_FW_MAJOR, SHELF_FW_MINOR, SHELF_FW_PATCH,
    (SHELF_FW_BUILD & 0xFF), ((SHELF_FW_BUILD >> 8) & 0xFF),
    (0x100 - (FWI_SUM & 0xFF)) & 0xFF
};
