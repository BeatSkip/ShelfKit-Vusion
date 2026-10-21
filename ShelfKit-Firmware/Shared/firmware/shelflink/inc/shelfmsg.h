/**
 * @file shelfmsg.h
 * @brief Application payloads carried by shelflink, shared by Hub and tag
 *
 * POLL (tag -> hub), SM_POLL_LEN bytes:
 *   [0..1] tag uptime in seconds, little endian (wraps after 18 h)
 *   [2]    attempts the previous poll needed (0 = none yet)
 *   [3]    RSSI in dBm (signed) of the hub's previous answer, 0 = none yet
 *
 * POLL_RSP (hub -> tag), SM_RSP_LEN bytes:
 *   [0]    command for the tag, SM_CMD_*
 *   [1]    RSSI in dBm (signed) the hub measured on this poll
 */

#ifndef SHELFMSG_H
#define SHELFMSG_H

#define SM_POLL_LEN         4
#define SM_POLL_UPTIME_LO   0
#define SM_POLL_UPTIME_HI   1
#define SM_POLL_ATTEMPTS    2
#define SM_POLL_RSSI        3

#define SM_RSP_LEN          2
#define SM_RSP_CMD          0
#define SM_RSP_RSSI         1

#define SM_CMD_NONE         0

/*
 * Image transfer (hub -> tag), carried in DATA frames. The tag streams the
 * chunks straight into the e-paper controller, so nothing is buffered and the
 * chunks must arrive in order (the hub waits for each ACK before the next).
 *
 *   [0]  opcode
 *   BEGIN  : (no more bytes)  wakes the panel, ready for plane 0
 *   CHUNK  : [1] plane (SM_PLANE_*), [2..3] offset in the plane (LE),
 *            [4..] data, 1..SM_IMG_CHUNK bytes
 *   END    : refreshes the panel if both planes arrived complete
 *
 * Planes are in the epd.h framebuffer format, plane 0 (black/white) first.
 */
#define SM_OP_IMG_BEGIN     1
#define SM_OP_IMG_CHUNK     2
#define SM_OP_IMG_END       3

#define SM_PLANE_BW         0
#define SM_PLANE_RED        1

#define SM_IMG_HDR          4
#define SM_IMG_CHUNK        28      /* SL_MAX_PAYLOAD - SM_IMG_HDR */

/*
 * Firmware update (hub -> tag), also carried in DATA frames, one frame per
 * chunk and in order (the hub waits for each ACK as it does for images).
 * The tag writes the chunks into its SPI flash and only commits them, with a
 * magic sequence the bootloader looks for, once the whole image and its CRC
 * have arrived.
 *
 *   [0]  opcode
 *   BEGIN : [1..2] image length (LE), [3..4] CRC-16 of the image (LE)
 *   CHUNK : [1..2] offset into the image (LE), [3..] data, 1..SM_FW_CHUNK bytes
 *   END   : (no more bytes) verify, commit the header and reset into the
 *           bootloader, which flashes the image and clears the magic
 *
 * Layout in the SPI flash and the CRC definition: shelfota.h.
 */
#define SM_OP_FW_BEGIN      4
#define SM_OP_FW_CHUNK      5
#define SM_OP_FW_END        6

#define SM_FW_HDR           3
#define SM_FW_CHUNK         28      /* SL_MAX_PAYLOAD - SM_FW_HDR */

/*
 * Identity assignment (hub -> tag), one DATA frame:
 *   [0]  SM_OP_SET_ID, [1..2] node id (LE)
 *
 * The tag stores it, reads it back, then moves its radio address to it, so from
 * the next poll on the hub sees the new id. The net id is not on the wire: every
 * tag in a fleet shares the built-in one.
 */
#define SM_OP_SET_ID        7

/*
 * Factory reset (hub -> tag), one DATA frame: [0] SM_OP_WIPE.
 * Erases every flash sector the firmware owns and resets, so the tag comes back
 * with a fresh random id and no pending image. Nothing else is sent with it.
 */
#define SM_OP_WIPE          8

#endif /* SHELFMSG_H */
