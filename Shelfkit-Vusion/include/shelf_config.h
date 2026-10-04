#ifndef SHELF_CONFIG_H
#define SHELF_CONFIG_H

/* Radio identity of this node. The three bytes on air are
 * {node id low, node id high, network id}; both ends must use the same network id.
 * Give every tag its own node id (0x0100 and up). */
#define SHELF_NODE_ID       0x0100u
#define SHELF_NET_ID        0x5A

/* Seconds between polls. Short while bringing the link up; keep the 1 % duty
 * cycle of the 868.3 MHz sub-band in mind when going lower. */
#define SHELF_POLL_INTERVAL_S   5

/* Print the link statistics every this many polls */
#define SHELF_STATS_EVERY       10

/* 1 = drive the unidentified transistor lines PA2/PA5 on (see src/pwr.h) before the radio
 * starts. Left off by default; try it if the range turns out poor. */
#define SHELF_POWER_LINES   0

#endif /* SHELF_CONFIG_H */
