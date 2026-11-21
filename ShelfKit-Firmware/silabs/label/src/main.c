/**
 * @file main.c
 * @brief ShelfKit tag firmware for Silicon Labs EFR32FG22 tags - SKELETON
 *
 * What it does today: builds a ShelfLink POLL frame with the shared protocol code
 * (common/shelflink/sl_proto.c) in a loop, which proves the shared code compiles
 * and links for this chip.
 *
 * Not there yet: clocks and GPIO (the Gecko SDK's emlib: CMU, GPIO), the radio (RAIL, 2.4 GHz
 * - a different band from the Axsem tags, so it needs a 2.4 GHz hub of its own), the panel
 * driver, the SPI flash, EM2 sleep, OTA and the ID record. See ../README.md.
 */

#include <libmftypes.h>
#include "board.h"
#include "shelflink.h"
#include "shelfmsg.h"
#include "shelfver.h"
#include "sl_proto.h"

static uint8_t frame[SL_HDR_LEN + SL_MAX_PAYLOAD];
static uint8_t payload[2];

int main(void)
{
    uint8_t seq = 0;

    /* TODO(sdk): CHIP_Init(), CMU clocks, GPIO for BOARD_LED_PORT/BOARD_LED_PIN */
    for (;;) {
        /* the version travels in the poll, as on the Axsem tags */
        payload[0] = shelf_fw_info[SHELF_FW_INFO_MAJOR];
        payload[1] = shelf_fw_info[SHELF_FW_INFO_MINOR];
        (void)sl_frame_build(frame, SL_T_POLL, 0, 0xFFFE, seq++, payload, sizeof payload);
        /* TODO(radio): hand frame[] to RAIL and wait for the POLL_RSP */
        for (volatile uint32_t i = 0; i < 1000000u; i++)
            ;
    }
}
