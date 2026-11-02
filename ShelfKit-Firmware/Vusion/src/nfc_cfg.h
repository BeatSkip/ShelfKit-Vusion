#ifndef NFC_CFG_H
#define NFC_CFG_H

/* Configure the FM11NT081D's dual-purpose pin for field detect.
 *
 * The pin reports the EEPROM write-in-progress flag (WIP) out of reset; it has to
 * be switched to field detect before the tag's falling-edge interrupt on PB3 can
 * ever fire. Register and value come from Fudan's own FM11NT081D driver:
 *
 *   #define NFC_CFG 0x0D                  // NFC configuration register
 *   fm11nt08_writereg(NFC_CFG, 0x03);     // bits 5:4 = 00 -> field detect
 *
 * That driver is I2C; this board has the ...DS (SPI) part, so the framing below
 * is the register address carried over SPI the way the driver builds it
 * (0xFF, 0xF0|reg, data). The read-back is logged so a wrong framing shows up as
 * a value that never changes, rather than as silence. */
/* Bit-banged mode-1 transport, the UID self-test, and the FD register write. */
void nfc_probe(void);           /* read the UID and verify its check bytes */
void nfc_cfg_fd(void);          /* select field detect on the WIP_FD pin */

#endif
