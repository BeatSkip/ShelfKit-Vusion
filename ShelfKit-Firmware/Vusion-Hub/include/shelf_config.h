#ifndef SHELF_CONFIG_H
#define SHELF_CONFIG_H

/* Radio identity of this node. The three bytes on air are
 * {node id low, node id high, network id}; both ends must use the same network id. */
#define SHELF_NODE_ID       0x0001u     /* the hub is always SL_NODE_HUB */
#define SHELF_NET_ID        0x5A

/* 1 = switch the panel supply (U4 on PA5) on at boot and leave it on. It has NOTHING to do
 * with the radio: measured on hardware, PA5 only powers the e-paper panel, and PA2 (U5) is
 * never switched on (it is parked low at boot whatever this says). Leave it 0; the image
 * path powers the panel itself around each image. See Documentation/pa2-pa5-findings.md. */
#define SHELF_POWER_LINES   0

/* 1 = epd_open() pulses the panel RST line, which is PB5 - the same pin as the
 * host's serial RX. Then the panel's reset and the serial line are one wire: every
 * byte from the host resets the panel, and the pulse itself fights the USB-serial
 * adapter. 0 (default) leaves PB5 alone and resets the panel by cycling its rail.
 * If the picture is garbled or the panel stops mid-transfer, cut the trace between
 * PB5 and the panel's RST pin. */
#define HUB_EPD_RST_PULSE   0

#endif /* SHELF_CONFIG_H */
