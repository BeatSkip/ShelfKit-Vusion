/**
 * @file shelfmsg.h
 * @brief Application payloads carried by shelflink, shared by Hub and tag
 *
 * POLL (tag -> hub), SM_POLL_LEN bytes:
 *   [0..1] tag uptime in seconds, little endian (wraps after 18 h)
 *   [2]    attempts the previous poll needed (0 = none yet)
 *   [3]    RSSI in dBm (signed) of the hub's previous answer, 0 = none yet
 *   [4..5] supply voltage, volts*256
 *   [6..17] only on a poll started by an NFC tap (and the first after a reset): firmware
 *          version, build, power stats and how the last panel refresh went
 *
 * POLL_RSP (hub -> tag), SM_RSP_LEN bytes:
 *   [0]    command for the tag, SM_CMD_*
 *   [1]    RSSI in dBm (signed) the hub measured on this poll
 */

#ifndef SHELFMSG_H
#define SHELFMSG_H

#define SM_POLL_LEN         6
#define SM_POLL_UPTIME_LO   0
#define SM_POLL_UPTIME_HI   1
#define SM_POLL_ATTEMPTS    2
#define SM_POLL_RSSI        3
/* supply voltage in volts*256 (3.00 V -> 0x0300), measured by the tag at each poll */
#define SM_POLL_VDD_LO      4
#define SM_POLL_VDD_HI      5

/* Extended POLL, sent only for a poll the user started by tapping the tag with a phone
 * (len SM_POLL_EXT_LEN): which firmware this tag runs and its latest power figures. A
 * normal poll stays SM_POLL_LEN bytes - nothing extra goes over the air on the idle fleet. */
#define SM_POLL_EXT_LEN     15
#define SM_POLL_FW_MAJOR    6
#define SM_POLL_FW_MINOR    7
#define SM_POLL_FW_PATCH    8
#define SM_POLL_FW_BUILD_LO 9       /* build counter, little endian */
#define SM_POLL_FW_BUILD_HI 10
#define SM_POLL_AVG_UA_LO   11      /* average current since boot, microamps */
#define SM_POLL_AVG_UA_HI   12
#define SM_POLL_LIFE_D_LO   13      /* estimated battery life in days (CR2450), 0xFFFF = n/a */
#define SM_POLL_LIFE_D_HI   14
/* From 1.1.0-51 (len SM_POLL_EXT2_LEN): the last image refresh since boot. Older tags send
 * SM_POLL_EXT_LEN bytes and the hub prints these only when they are there. */
#define SM_POLL_EXT2_LEN    18
#define SM_POLL_IMG_ST      15      /* EPD_BUSY_*: 0 none, 1 done, 2 timeout; 0xFF = no image yet */
#define SM_POLL_IMG_DS_LO   16      /* how long that refresh took, in 0.1 s */
#define SM_POLL_IMG_DS_HI   17

#define SM_RSP_LEN          3
#define SM_RSP_CMD          0
#define SM_RSP_RSSI         1
/* The hub may ask for a longer gap before the next check-in, in 10 s units
 * (0 = none). This is the "AP instruction" half of the adaptive backoff. */
#define SM_RSP_DELAY        2

#define SM_CMD_NONE         0
/* The hub has something for this tag: keep the receiver open. Without it the
 * tag closes its listening window after a short grace, which is most of the
 * power saving on an idle fleet. */
#define SM_CMD_DATA         0x01

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
 * Compressed planes (ECO chain coding, Documentation/ECO-ESL-ImageCompression.pdf;
 * encoder ShelfKit-Server/shelfkit/eco.py, decoder Vusion/src/eco_rx.c). Either
 * plane may come compressed instead of as CHUNKs; the order stays BW, then RED.
 *
 *   ZCHUNK : [1] plane, [2..3] offset in the compressed file (LE), [4..] data
 *   ZEND   : [1] plane, [2..3] compressed length (LE) - the tag decodes the file
 *            straight into the panel (~0.5 s, it answers nothing meanwhile)
 *
 * A compressed plane may be at most SM_ECO_MAX bytes (the tag's buffer); the
 * server sends larger ones (dithered photos) as plain CHUNKs.
 */
#define SM_OP_IMG_ZCHUNK    11
#define SM_OP_IMG_ZEND      12
#define SM_ECO_MAX          2560

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

/*
 * SPI flash read-back (hub -> tag, tag -> hub), one request and a stream of
 * replies. Used to inspect a tag without opening it: the identity record, the
 * OTA header, whatever is actually on the chip.
 *
 *   request  [0] SM_OP_FLASH_DUMP, [1..3] address (LE 24), [4..5] length (LE)
 *   reply    [0] SM_OP_FLASH_DATA, [1..3] address (LE 24), [4] n, [5..] n bytes
 *
 * Replies are DATA frames sent back to the hub, which prints them as hex on its
 * UART; Tooling/flash-read.py puts them back together. One request covers at
 * most SM_DUMP_MAX bytes - the host splits bigger reads.
 */
#define SM_OP_FLASH_DUMP    9
#define SM_OP_FLASH_DATA    10
#define SM_DUMP_HDR         5       /* opcode + 3 address + n */
#define SM_DUMP_CHUNK       26      /* SL_MAX_PAYLOAD - SM_DUMP_HDR */
#define SM_DUMP_MAX         4096

/*
 * Check-in interval (hub -> tag), one DATA frame:
 *   [0]  SM_OP_SET_POLL, [1..2] idle interval in seconds (LE), SM_POLL_S_MIN..65535
 *
 * How often the tag polls when nothing else is going on. The tag stores it in the
 * configuration sector of its SPI flash (shelf_id.h), so it survives resets and
 * firmware updates, and uses it from its next check-in on. The burst rate while data
 * is queued, the back-off after failed polls and the weak-link limit stay as they are.
 */
#define SM_OP_SET_POLL      13
#define SM_POLL_S_MIN       30

#endif /* SHELFMSG_H */
