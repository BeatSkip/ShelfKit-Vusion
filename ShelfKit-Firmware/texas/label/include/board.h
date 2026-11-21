/**
 * @file board.h
 * @brief Pins and panel of a CC2510 tag - PLACEHOLDERS until a tag model is chosen
 *
 * Nothing here comes from a real board yet. Every value marked TODO(board) has to be
 * measured on the tag (continuity to the CC2510 pins, the panel's FPC, the flash chip)
 * before a driver relies on it. Port 1 pin n is written P1_n.
 */

#ifndef BOARD_H
#define BOARD_H

#define BOARD_NAME          "generic CC2510 tag (placeholder)"

/* Status LED, if the tag has one. TODO(board) */
#define BOARD_LED_PORT      P1
#define BOARD_LED_DIR       P1DIR
#define BOARD_LED_BIT       0x01        /* P1_0 */

/* E-paper panel. TODO(board): size, colours, controller and every pin */
#define BOARD_EPD_WIDTH     152
#define BOARD_EPD_HEIGHT    296
#define BOARD_EPD_COLOURS   3           /* black / white / red */
/* BOARD_EPD_CS, _DC, _RST, _BUSY, _SCK, _MOSI: TODO(board) */

/* SPI flash for images. TODO(board): present? which USART, which CS pin */
/* BOARD_FLASH_CS: TODO(board) */

/* NFC. TODO(board): present? */
#define BOARD_HAS_NFC       0

#endif /* BOARD_H */
