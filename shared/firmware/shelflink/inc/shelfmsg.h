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

#endif /* SHELFMSG_H */
