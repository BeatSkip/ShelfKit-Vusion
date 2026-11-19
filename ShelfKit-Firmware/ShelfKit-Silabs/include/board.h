/**
 * @file board.h
 * @brief Pins and panel of an EFR32FG22 tag - PLACEHOLDERS until a tag model is chosen
 *
 * Nothing here comes from a real board yet. Every value marked TODO(board) has to be
 * measured on the tag before a driver relies on it. Pins are written as port + pin
 * (gpioPortA = 0, B = 1, C = 2, D = 3), the way emlib's GPIO_PinModeSet() takes them.
 */

#ifndef BOARD_H
#define BOARD_H

#define BOARD_NAME          "generic EFR32FG22 tag (placeholder)"

/* Status LED, if the tag has one. TODO(board) */
#define BOARD_LED_PORT      0           /* port A */
#define BOARD_LED_PIN       4

/* E-paper panel. TODO(board): size, colours, controller and every pin */
#define BOARD_EPD_WIDTH     152
#define BOARD_EPD_HEIGHT    296
#define BOARD_EPD_COLOURS   3           /* black / white / red */
/* BOARD_EPD_CS, _DC, _RST, _BUSY, _SCK, _MOSI: TODO(board) */

/* SPI flash for images. TODO(board): present? which USART, which CS pin */

/* NFC. TODO(board): present? */
#define BOARD_HAS_NFC       0

#endif /* BOARD_H */
