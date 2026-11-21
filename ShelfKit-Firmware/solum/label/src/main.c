/**
 * @file main.c
 * @brief ShelfKit label firmware for Solum labels with the ZBS243 - SKELETON
 *
 * What it does today: builds a ShelfLink POLL frame with the shared protocol code
 * (common/shelflink/sl_proto.c) and toggles the placeholder LED latch, which proves the
 * shared code compiles and links for this chip.
 *
 * Not there yet: the clock setup, pin directions and the watchdog (their registers are not
 * declared until their addresses are verified, see zbs243.h), the radio (the ZBS243's
 * 2.4 GHz 802.15.4 transceiver - a different band from the Axsem labels' sub-GHz AX5043, so
 * it needs a 2.4 GHz hub of its own), the panel driver, the SPI flash, sleep, OTA and the ID
 * record. See ../README.md.
 */

#include <libmftypes.h>
#include "zbs243.h"
#include "board.h"
#include "shelflink.h"
#include "shelfmsg.h"
#include "shelfver.h"
#include "sl_proto.h"

static uint8_t __xdata frame[SL_HDR_LEN + SL_MAX_PAYLOAD];
static uint8_t __xdata payload[2];

static void delay(uint16_t n)
{
    volatile uint16_t i;

    while (n--)
        for (i = 0; i < 500; i++)
            ;
}

void main(void)
{
    uint8_t seq = 0;

    /* TODO(soc): clock speed, pin directions, watchdog */

    for (;;) {
        /* the version travels in the poll, as on the Axsem labels */
        payload[0] = shelf_fw_info[SHELF_FW_INFO_MAJOR];
        payload[1] = shelf_fw_info[SHELF_FW_INFO_MINOR];
        (void)sl_frame_build(frame, SL_T_POLL, 0, 0xFFFE, seq++, payload, sizeof payload);
        /* TODO(radio): hand frame[] to the ZBS243 radio and wait for the POLL_RSP */

        BOARD_LED_PORT ^= BOARD_LED_BIT;    /* latch only: the pin is not set to output yet */
        delay(400);
    }
}
