/**
 * @file main.c
 * @brief ShelfKit tag firmware for TI CC2510 tags - SKELETON
 *
 * What it does today: starts the 26 MHz crystal, blinks the placeholder LED and builds a
 * ShelfLink POLL frame with the shared protocol code (common/shelflink/sl_proto.c),
 * which proves the shared code compiles and links for this chip.
 *
 * Not there yet: the radio (the CC2510's 2.4 GHz transceiver - a different band from the
 * Axsem tags' sub-GHz AX5043, so it needs a 2.4 GHz hub of its own), the panel driver, the
 * SPI flash, sleep, OTA and the ID record. See ../README.md.
 */

#include <libmftypes.h>
#include "cc2510.h"
#include "board.h"
#include "shelflink.h"
#include "shelfmsg.h"
#include "shelfver.h"
#include "sl_proto.h"

static uint8_t __xdata frame[SL_HDR_LEN + SL_MAX_PAYLOAD];
static uint8_t __xdata payload[2];

static void clock_init(void)
{
    SLEEP &= (uint8_t)~SLEEP_OSC_PD;            /* power up the 26 MHz crystal oscillator */
    while (!(SLEEP & SLEEP_XOSC_STB))
        ;
    CLKCON &= (uint8_t)~(CLKCON_OSC | 0x3F);    /* run from it, full speed */
    while (CLKCON & CLKCON_OSC)
        ;
    SLEEP |= SLEEP_OSC_PD;                      /* the RC oscillator is no longer needed */
}

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

    clock_init();
    BOARD_LED_DIR |= BOARD_LED_BIT;

    for (;;) {
        /* the version travels in the poll, as on the Axsem tags */
        payload[0] = shelf_fw_info[SHELF_FW_INFO_MAJOR];
        payload[1] = shelf_fw_info[SHELF_FW_INFO_MINOR];
        (void)sl_frame_build(frame, SL_T_POLL, 0, 0xFFFE, seq++, payload, sizeof payload);
        /* TODO(radio): hand frame[] to the CC2510 radio and wait for the POLL_RSP */

        BOARD_LED_PORT ^= BOARD_LED_BIT;
        delay(400);
    }
}
