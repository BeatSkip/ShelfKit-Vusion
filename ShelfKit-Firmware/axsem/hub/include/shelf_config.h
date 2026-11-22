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

/* 1 = reset the panel over SPI: epd_open() clears and sets RST_N, bit 0 of the IL0373's
 * panel setting (PSR, 0x00), which resets every register like the RST pin does. For a hub
 * whose PB5-RST trace is cut, so the RST pin never moves. Because only the RST pin wakes the
 * IL0373 from deep sleep (DSLP 0x07), the hub then never sends DSLP: it ends a refresh with
 * power off (POF 0x02) and cuts the panel rail. The rail is no longer cycled as a reset. The
 * panel's RST input must sit high (pulled up on the board, not floating) for this to work.
 * Only used with HUB_EPD_RST_PULSE 0. */
#ifndef HUB_EPD_SOFT_RESET
#define HUB_EPD_SOFT_RESET  1
#endif

/* The green activity flashes (a tag polled, an image is starting). 1 = on at boot; the host
 * turns them off and on with "G0" / "G1" (the server's Settings > General > Hub LED). The
 * blue boot pulse and the red fatal-error blink are not affected. */
#ifndef SHELF_HUB_LED
#define SHELF_HUB_LED       1
#endif

#endif /* SHELF_CONFIG_H */
