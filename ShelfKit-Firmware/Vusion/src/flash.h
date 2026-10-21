/**
 * @file flash.h
 * @brief Minimal SPI NOR flash driver for the tag's serial flash
 *
 * The tag carries a (suspected) 1 Mbit = 128 KiB SPI NOR flash on PC0
 * (CS), sharing the SPI bus with the NFC chip and the e-paper panel.
 * Commands are the standard 25-series set (0x03 read, 0x9F JEDEC ID,
 * 0xAB release from power-down).
 */

#ifndef FLASH_DRIVER_H
#define FLASH_DRIVER_H

#include <ax8052f143.h>
#include <libmftypes.h>

/* Total size to dump. Adjust after checking the JEDEC ID capacity byte:
 *   0x13 = 512 kbit, 0x14 = 1 Mbit, 0x15 = 2 Mbit, 0x16 = 4 Mbit ... */
#define FLASH_SIZE 0x14000UL   /* 128 KiB */

/* Send 0xAB: wakes the chip if a previous firmware left it in deep
 * power-down. Harmless when the chip is already awake. */
void extflash_release_powerdown(void);

/* Read the 3-byte JEDEC ID (manufacturer, memory type, capacity). */
void extflash_read_jedec_id(uint8_t id[3]);

/* Read len bytes from addr into buf using command 0x03. */
void extflash_read(uint32_t addr, uint8_t *buf, uint16_t len);

/* Block until the chip's write/erase in progress bit clears. Returns 1 when it
 * did, 0 on timeout (~0.5 s): a chip that never answers must not hang the tag. */
uint8_t extflash_wait_ready(void) __reentrant;

/* Program len bytes at addr (0x02 page program). Splits at the chip's 256-byte
 * page boundaries by itself, so callers only have to erase first.
 * Returns 1 on success, 0 if the chip stayed busy. */
uint8_t extflash_write(uint32_t addr, const uint8_t *buf, uint16_t len) __reentrant;

/* Erase the 4 KiB sectors covering [addr, addr+len). addr must be aligned.
 * Returns 1 on success, 0 if the chip stayed busy. */
uint8_t extflash_erase(uint32_t addr, uint16_t len) __reentrant;

#endif /* FLASH_DRIVER_H */
