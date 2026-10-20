#ifndef SHELF_CONFIG_H
#define SHELF_CONFIG_H

/* Radio identity. The on-air address is {node id low, node id high, net id}; the
 * net id is the fleet-wide constant below, and the node id is NOT built in: it is
 * read from the tag's SPI flash (src/shelf_id.c), which is what lets one firmware
 * image fit the whole fleet. A brand new tag generates a random id at first boot
 * and keeps it; the server can assign a proper one at any time with
 * Tooling/set-id.py, and the id survives firmware updates. */
#define SHELF_NET_ID        0x5A

/* Seconds between polls. Short while bringing the link up; keep the 1 % duty
 * cycle of the 868.3 MHz sub-band in mind when going lower. */
#define SHELF_POLL_INTERVAL_S   5

/* Print the link statistics every this many polls */
#define SHELF_STATS_EVERY       10

/* 1 = drive the unidentified transistor lines PA2/PA5 on (see src/pwr.h) before the radio
 * starts. Left off by default; try it if the range turns out poor.
 * This is about the radio only: the e-paper supply is transistor U4 on PA5, and
 * src/img_rx.c drives it on itself around every image (independent of this switch). */
#define SHELF_POWER_LINES   0

#endif /* SHELF_CONFIG_H */
