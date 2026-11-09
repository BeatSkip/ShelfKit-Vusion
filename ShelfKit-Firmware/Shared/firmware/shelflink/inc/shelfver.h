/**
 * @file shelfver.h
 * @brief Firmware version, stamped in by Tooling/build-all.py
 *
 * build-all.py reads ShelfKit-Firmware/version.json and passes SHELF_FW_MAJOR, _MINOR,
 * _PATCH and SHELF_FW_BUILD (the running build counter) as -D defines to every target.
 * The zeros below only apply to a build made some other way (the VS Code extension), so
 * such a firmware reports itself as 0.0.0 build 0 and is easy to tell apart.
 *
 * The numbers are also stored as a constant in code space, shelf_fw_info[], so a tool can read
 * them out of a .hex file without running anything:
 *   'S' 'K' 'F' 'W', major, minor, patch, build (LE, 2 bytes), check
 * where check makes the sum of all ten bytes 0 mod 256. build-all.py verifies it after every
 * build; ShelfKit-Server/shelfkit/firmware.py reads it. Keep the layout in sync with both.
 */

#ifndef SHELFVER_H
#define SHELFVER_H

#ifndef SHELF_FW_MAJOR
#define SHELF_FW_MAJOR  0
#endif
#ifndef SHELF_FW_MINOR
#define SHELF_FW_MINOR  0
#endif
#ifndef SHELF_FW_PATCH
#define SHELF_FW_PATCH  0
#endif
#ifndef SHELF_FW_BUILD
#define SHELF_FW_BUILD  0       /* 16 bits on the wire */
#endif

#define SHELF_FW_INFO_LEN   10
#define SHELF_FW_INFO_MAJOR 4   /* offsets into shelf_fw_info[] */
#define SHELF_FW_INFO_MINOR 5
#define SHELF_FW_INFO_PATCH 6
#define SHELF_FW_INFO_BLO   7
#define SHELF_FW_INFO_BHI   8

extern const __code unsigned char shelf_fw_info[SHELF_FW_INFO_LEN];

#endif /* SHELFVER_H */
