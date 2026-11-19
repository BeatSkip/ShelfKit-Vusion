#ifndef NFC_CFG_H
#define NFC_CFG_H

/* Make sure the FM11NT081D's WIP_FD pin is in field-detect mode.
 *
 * The pin function lives in the chip's EEPROM, not in a register: 0x38C bits 1:0
 * (fdp_conf, 11 = field present) and 0x391 bit 7 (WIP_FD, 0 = FD). nfc_cfg_fd() reads
 * both and rewrites them only if they differ (and the config is not locked); the chip
 * loads them at its next power-up. The result is logged. */
/* Bit-banged mode-1 transport, the UID self-test, and the FD configuration check. */
void nfc_probe(void);           /* read the UID and verify its check bytes */
void nfc_cfg_fd(void);          /* select field detect on the WIP_FD pin */

/* Raw EEPROM access for the server (SM_OP_NFC_WRITE, SM_OP_FLASH_DUMP + SM_DUMP_NFC).
 * Parameters are these globals, not arguments: there is no internal RAM to spare.
 *   nfc_read():  nfc_len (<= 64) bytes at nfc_addr into nfc_buf
 *   nfc_write(): nfc_len bytes (whole pages) from nfc_wsrc to nfc_addr (page aligned),
 *                then reads them back into nfc_buf; 1 = they match */
extern uint16_t __xdata nfc_addr;
extern uint8_t __xdata nfc_len;
extern uint8_t __xdata nfc_buf[64];
extern const uint8_t __xdata * __xdata nfc_wsrc;
void nfc_read(void);
uint8_t nfc_write(void);

#endif
