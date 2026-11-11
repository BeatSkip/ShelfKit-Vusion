/**
 * @file nfc_cfg.c
 * @brief FM11NT081DS: bit-banged mode-1 contact interface, UID self-test, FD setup
 *
 * The NFC chip's SPI slave only speaks **mode 1** (CPOL=0, CPHA=1) or 3, while the
 * AX8052's SPI unit is set up for mode 0 because that is what the IL0373 panel on the
 * same bus needs - and the mode bits of SPMODE are not documented. A mode-0 master
 * talking to a mode-1 slave is a timing race, so this drives SCK/MOSI as GPIO and reads
 * MISO from PINC, then hands the bus back to the hardware SPI.
 *
 * Pin control follows the AX8052F143 datasheet (figure 10, "Port Pin Schematic"): with
 * DIRx.y = 1 the PALTx.y bit selects the peripheral output (1) or the PORT register (0),
 * so clearing the PALTC bits routes SCK/MOSI to the GPIO. MISO must be read from PINC -
 * PORTC is the output latch and only holds the pull-up bit for an input.
 *
 * Protocol (FM11NT081D technical manual 4.2.2/4.2.6): SSN low wakes the chip (>= 100 us
 * of preparation), then a command byte and an address byte. "Read EEPROM" is 011_000xx
 * where xx are A9:A8, the next byte is A7:A0, and the pointer auto-increments.
 *
 * The EEPROM read and the bit-banging are ported from the earlier ShelfKit firmware,
 * where they were verified on this board; the register access below is the one part
 * that is still inferred.
 */
#include <ax8052f143.h>
#include <libmftypes.h>
#include "board.h"
#include "spi.h"
#include "flash.h"
#include "shelfhw.h"
#include "shelf_config.h"
#include "nfc_cfg.h"

#define NFC_SCK         SPI_SCK     /* PC1 */
#define NFC_MOSI        SPI_MOSI    /* PC2 */
#define NFC_MISO        PINC_3      /* PC3 - read the pin, not the latch */
#define NFC_CS          CS_NFC      /* PB1 */

#define NFC_PALT_MASK   0x0E        /* PC1, PC2, PC3 alternate-function bits */
#define NFC_OUT_MASK    0x06        /* PC1 (SCK), PC2 (MOSI) */
#define NFC_MISO_MASK   0x08        /* PC3 */

#define NFC_CMD_READ_EE 0x60        /* 011_000xx, xx = A9:A8 */
#define NFC_WAKE_US     200         /* >= 100 us of power-up preparation */
#define NFC_RESET_US    2           /* SSN high >= 50 ns resets the SPI port */


static uint8_t nfc_paltc;           /* PALTC before the pads were taken */

static void nfc_bb_init(void)
{
    DIRA |= 0x02;                   /* EPD CS on PA1 */
    DIRB |= 0x02;                   /* NFC CS on PB1 */
    DIRC |= 0x01;                   /* FLASH CS on PC0 */
    CS_EPD   = 1;
    CS_FLASH = 1;
    NFC_CS   = 1;

    SPCLKSRC = 0x07;                /* SPI clock off */
    SPMODE   = 0x00;                /* SPI master off */
    nfc_paltc = PALTC;
    PALTC &= (uint8_t)~NFC_PALT_MASK;

    DIRC |= NFC_OUT_MASK;
    DIRC &= (uint8_t)~NFC_MISO_MASK;
    NFC_SCK  = 0;                   /* mode 1: the clock idles low */
    NFC_MOSI = 0;
    PORTC |= NFC_MISO_MASK;         /* input: PORT bit = pull-up on */
}

static void nfc_bb_release(void)
{
    PALTC = nfc_paltc;              /* pads back to the SPI peripheral */
    spi_init();                     /* and the hardware SPI back on for the panel */
}

static void nfc_bb_delay(void)
{
    volatile uint8_t i;

    for (i = 4; i; i--)
        ;
}

static uint8_t nfc_bb_xfer(uint8_t out)
{
    uint8_t in = 0;
    uint8_t i;

    for (i = 0; i < 8; i++) {
        /* Mode 1: MOSI changes while the clock is low and the chip samples it on the
         * falling edge; the chip shifts MISO out on the rising edge, so sample it
         * while the clock is high. */
        NFC_MOSI = (out & 0x80) ? 1 : 0;
        out = (uint8_t)(out << 1);
        nfc_bb_delay();

        NFC_SCK = 1;
        nfc_bb_delay();

        in = (uint8_t)(in << 1);
        if (NFC_MISO)
            in |= 0x01;

        NFC_SCK = 0;
        nfc_bb_delay();
    }
    return in;
}

#if SHELF_NFC_PROBE
static uint8_t __xdata nfc_uid[9];  /* SN0..2, BCC0, SN3..6, BCC1 */
#endif
/* One read command reaches 256 bytes (A9:A8 are in the command byte), so a block is
 * read in one go into this buffer; the addresses are file scope because the tag has no
 * internal RAM for a parameter block. */
static uint16_t __xdata nfc_addr;
static uint8_t __xdata nfc_len;
static uint8_t __xdata nfc_buf[64];

/* Read nfc_len bytes at nfc_addr into nfc_buf. No arguments: see above. */
static void nfc_read_block(void)
{
    uint8_t i;

    NFC_CS = 0;
    delay(NFC_WAKE_US);             /* the chip needs time to come up */

    (void)nfc_bb_xfer((uint8_t)(NFC_CMD_READ_EE | ((nfc_addr >> 8) & 0x03)));
    (void)nfc_bb_xfer((uint8_t)nfc_addr);
    for (i = 0; i < nfc_len; i++)
        nfc_buf[i] = nfc_bb_xfer(0x00);

    NFC_CS = 1;
    delay(NFC_RESET_US);
}

/* The boot-time probe is a development aid behind SHELF_NFC_PROBE. Compiled out with the
 * switch off: it was ~390 bytes of an image that has to fit the OTA window. */
#if SHELF_NFC_PROBE
static void nfc_dump(const char *what)
{
    uint8_t i;

    log_puts("nfc ");
    log_puts(what);
    log_puts(" ");
    for (i = 0; i < nfc_len; i++) {
        log_hex8(nfc_buf[i]);
        log_puts(" ");
    }
    log_nl();
}

void nfc_probe(void)
{
    uint8_t i, bcc0, bcc1;

    extflash_power_up();            /* the chip shares the flash's switched rail */
    nfc_bb_init();
    nfc_addr = 0x000;
    nfc_len = 9;
    nfc_read_block();
    {
        uint8_t i;
        for (i = 0; i < 9; i++)
            nfc_uid[i] = nfc_buf[i];
    }
    /* The FD/WP selection is a configuration byte, not a register of the FIFO bank:
     * dump the configuration-looking areas so the byte can be identified instead of
     * guessed. Read-only, so it is safe on every boot while this is being worked out. */
    nfc_addr = 0x00C;
    nfc_len = 8;                    /* capability container */
    nfc_read_block();
    nfc_dump("cc ");
    nfc_addr = 0x35C;
    nfc_len = 64;                   /* last 64 bytes of the 924-byte EEPROM */
    nfc_read_block();
    nfc_dump("tail");
    nfc_bb_release();
    extflash_power_down();

    log_puts("nfc uid ");
    for (i = 0; i < 9; i++) {
        log_hex8(nfc_uid[i]);
        log_puts(i == 8 ? "" : " ");
    }
    /* ISO/IEC 14443-3 check bytes next to the UID: BCC0 covers the cascade tag */
    bcc0 = (uint8_t)(0x88 ^ nfc_uid[0] ^ nfc_uid[1] ^ nfc_uid[2]);
    bcc1 = (uint8_t)(nfc_uid[4] ^ nfc_uid[5] ^ nfc_uid[6] ^ nfc_uid[7]);
    log_puts((nfc_uid[3] == bcc0 && nfc_uid[8] == bcc1) ? " ok" : " bad");
    log_nl();
}
#endif /* SHELF_NFC_PROBE */

/* ── the FD pin is configured in EEPROM (FM11NT081D datasheet) ──────────────────────────
 *   0x38C (page E3h) bits 1:0  fdp_conf: 00 no FD, 01 first SoF, 10 tag selected,
 *                              11 field present (factory default, what the tag wants)
 *   0x391 (REGU_CFG) bit 7     WIP_FD pin function: 0 = FD (default), 1 = EEPROM-write flag
 * Both load at power-up. There is no register to write (the 0x0D "NFC_CFG" of Fudan's I2C
 * driver does not exist on this part). An EEPROM write needs the enable sequence CE 55 +
 * SSN high, the write command within ~0.7 ms, then SSN high for ~10 ms. */
#define NFC_EE_E3       0x38C
#define NFC_EE_E4       0x390
#define NFC_CMD_WRITE_EE 0x40       /* 010_000xx */
#define NFC_FDP_FIELD   0x03

static uint8_t __xdata nfc_ee[8];   /* 0x38C..0x393: pages E3h and E4h */

static void nfc_ee_read(void)
{
    nfc_addr = NFC_EE_E3;
    nfc_len = 8;
    nfc_read_block();
    {
        static uint8_t __xdata i;

        for (i = 0; i < 8; i++)
            nfc_ee[i] = nfc_buf[i];
    }
}

/* write one 4-byte page (src = nfc_ee + off) at addr */
static void nfc_ee_write_page(uint16_t addr, uint8_t off)
{
    static uint8_t __xdata i;

    NFC_CS = 0;
    delay(NFC_WAKE_US);
    (void)nfc_bb_xfer(0xCE);        /* write enable */
    (void)nfc_bb_xfer(0x55);
    NFC_CS = 1;
    delay(20);
    NFC_CS = 0;
    delay(30);
    (void)nfc_bb_xfer((uint8_t)(NFC_CMD_WRITE_EE | ((addr >> 8) & 0x03)));
    (void)nfc_bb_xfer((uint8_t)addr);
    for (i = 0; i < 4; i++)
        (void)nfc_bb_xfer(nfc_ee[off + i]);
    NFC_CS = 1;                     /* SSN high starts the erase/write: ~10 ms */
    for (i = 0; i < 20; i++)
        delay(1000);
}

/* ── what a phone finds when it reads the tag ─────────────────────────────────────────────
 * The chip is an NFC Forum Type 2 tag: the capability container (E1 ..) sits at 0x00C and the
 * TLV area with the NDEF message starts at 0x010. SHELF_NFC_URL "" keeps that message empty
 * (03 00 FE): the phone sees a tag and nothing to open. With a URL it is one URI record
 * (03 len D1 01 len+1 55 00 <url> FE). Only differing pages are written, so after the first
 * boot this is one read. Pages are 4 bytes; file-scope variables because there is no spare
 * internal RAM. */
#define NFC_EE_USER     0x010
#define NFC_URL_LEN     (sizeof(SHELF_NFC_URL) - 1)
#define NFC_NDEF_LEN    (NFC_URL_LEN ? NFC_URL_LEN + 8 : 3)
typedef char nfc_url_fits[(NFC_URL_LEN <= 48) ? 1 : -1];

static const char __code nfc_url[] = SHELF_NFC_URL;
static uint8_t __xdata nfc_i;
static uint8_t __xdata nfc_page;
static uint8_t __xdata nfc_state;   /* 0 ok, 1 written, 2 failed, 3 no Type 2 header */

/* wanted byte nfc_i of the NDEF TLV (bytes past its end: the old content is kept) */
static uint8_t nfc_ndef_byte(void)
{
    if (nfc_i >= NFC_NDEF_LEN)
        return nfc_buf[nfc_i];
    if (!NFC_URL_LEN)
        return nfc_i == 0 ? 0x03 : (nfc_i == 1 ? 0x00 : 0xFE);
    if (nfc_i >= 7 && nfc_i < 7 + NFC_URL_LEN)
        return (uint8_t)nfc_url[nfc_i - 7];
    switch (nfc_i) {
    case 0:  return 0x03;
    case 1:  return (uint8_t)(NFC_URL_LEN + 5);
    case 2:  return 0xD1;
    case 3:  return 0x01;
    case 4:  return (uint8_t)(NFC_URL_LEN + 1);
    case 5:  return 0x55;               /* 'U' */
    case 6:  return 0x00;               /* no abbreviated prefix: the URL is written in full */
    default: return 0xFE;               /* terminator */
    }
}

/* nfc_buf holds the area as read; 1 = some byte up to the TLV's end differs */
static uint8_t nfc_ndef_differs(void)
{
    for (nfc_i = 0; nfc_i < NFC_NDEF_LEN; nfc_i++)
        if (nfc_buf[nfc_i] != nfc_ndef_byte())
            return 1;
    return 0;
}

static void nfc_ndef_sync(void)
{
    nfc_addr = 0x00C;
    nfc_len = 4;
    nfc_read_block();
    if (nfc_buf[0] != 0xE1) {       /* not a Type 2 capability container: leave it alone */
        nfc_state = 3;
        return;
    }
    nfc_state = 0;
    nfc_addr = NFC_EE_USER;
    nfc_len = (uint8_t)((NFC_NDEF_LEN + 3) & 0xFC);
    nfc_read_block();
    if (!nfc_ndef_differs())
        return;
    nfc_state = 1;
    for (nfc_page = 0; nfc_page < nfc_len; nfc_page += 4) {
        for (nfc_i = nfc_page; nfc_i < nfc_page + 4; nfc_i++)
            nfc_ee[nfc_i - nfc_page] = nfc_ndef_byte();
        nfc_ee_write_page(NFC_EE_USER + nfc_page, 0);
    }
    nfc_addr = NFC_EE_USER;
    nfc_len = (uint8_t)((NFC_NDEF_LEN + 3) & 0xFC);
    nfc_read_block();
    if (nfc_ndef_differs())
        nfc_state = 2;
}

void nfc_cfg_fd(void)
{
    static uint8_t __xdata wrote, ok;

    extflash_power_up();
    nfc_bb_init();
#if SHELF_NFC_NDEF_SYNC
    nfc_ndef_sync();
    log_puts("nfc ndef ");
    log_puts(nfc_state == 0 ? "ok" : (nfc_state == 1 ? "written" :
             (nfc_state == 2 ? "WRITE FAILED" : "skipped, no type 2 header")));
    log_nl();
#endif
    nfc_ee_read();
    wrote = 0;
    if ((nfc_ee[0] & 0x03) != NFC_FDP_FIELD && !(nfc_ee[4] & 0x40)) {   /* CFGLOCK clear */
        nfc_ee[0] = (uint8_t)((nfc_ee[0] & 0xFC) | NFC_FDP_FIELD);
        nfc_ee_write_page(NFC_EE_E3, 0);
        wrote = 1;
    }
    if ((nfc_ee[5] & 0x80) && !(nfc_ee[4] & 0x40)) {
        nfc_ee[5] = (uint8_t)(nfc_ee[5] & 0x7F);
        nfc_ee_write_page(NFC_EE_E4, 4);
        wrote = 1;
    }
    nfc_ee_read();                  /* what the chip will load at its next power-up */
    ok = (uint8_t)((nfc_ee[0] & 0x03) == NFC_FDP_FIELD && !(nfc_ee[5] & 0x80));
    nfc_bb_release();
    extflash_power_down();

    log_puts("nfc fd cfg ");
    log_hex8(nfc_ee[0]);
    log_puts(" ");
    log_hex8(nfc_ee[5]);
    log_puts(wrote ? " written" : "");
    log_puts(ok ? " ok" : " NOT field-detect (locked?)");
    log_nl();
}
