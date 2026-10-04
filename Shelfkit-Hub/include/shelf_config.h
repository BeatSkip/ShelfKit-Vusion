#ifndef SHELF_CONFIG_H
#define SHELF_CONFIG_H

/* Radio identity of this node. The three bytes on air are
 * {node id low, node id high, network id}; both ends must use the same network id. */
#define SHELF_NODE_ID       0x0001u     /* the hub is always SL_NODE_HUB */
#define SHELF_NET_ID        0x5A

/* 1 = drive the unidentified transistor lines PA2/PA5 on (see src/pwr.h) before the radio
 * starts. Left off by default; try it if the range turns out poor. */
#define SHELF_POWER_LINES   0

#endif /* SHELF_CONFIG_H */
