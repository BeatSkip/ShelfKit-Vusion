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

#endif
