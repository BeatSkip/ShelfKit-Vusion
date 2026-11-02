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

#define NFC_REG_CFG     0x0D        /* NFC configuration register */
#define NFC_CFG_FD      0x03        /* bits 5:4 = 00: field detect */

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

static uint8_t __xdata nfc_uid[9];  /* SN0..2, BCC0, SN3..6, BCC1 */
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

/* SPI command encoding (datasheet table 4-4): the first byte is the command, the
 * register address lives in its low four bits -
 *
 *   write register  000_0_<reg>
 *   read register   001_0_<reg>
 *   write EEPROM    010_<A9:A8>
 *   read EEPROM     011_<A9:A8>
 *
 * The I2C-style 16-bit address (0xFF, 0xF0|reg) tried before is not understood by the
 * ...DS part, which is why every register read returned 0xff while EEPROM reads worked. */
#define NFC_CMD_WR_REG  0x00
#define NFC_CMD_RD_REG  0x20

static uint8_t nfc_reg_read(uint8_t reg)
{
    uint8_t v;

    NFC_CS = 0;
    delay(NFC_WAKE_US);
    (void)nfc_bb_xfer((uint8_t)(NFC_CMD_RD_REG | (reg & 0x0F)));
    v = nfc_bb_xfer(0x00);
    NFC_CS = 1;
    delay(NFC_RESET_US);
    return v;
}

static void nfc_reg_write(uint8_t reg, uint8_t val)
{
    NFC_CS = 0;
    delay(NFC_WAKE_US);
    (void)nfc_bb_xfer((uint8_t)(NFC_CMD_WR_REG | (reg & 0x0F)));
    (void)nfc_bb_xfer(val);
    NFC_CS = 1;
    delay(NFC_RESET_US);
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

void nfc_cfg_fd(void)
{
    uint8_t before, after;

    extflash_power_up();
    nfc_bb_init();
    before = nfc_reg_read(NFC_REG_CFG);
    nfc_reg_write(NFC_REG_CFG, (uint8_t)((before & (uint8_t)~0x30) | NFC_CFG_FD));
    after = nfc_reg_read(NFC_REG_CFG);
    nfc_bb_release();
    extflash_power_down();

    log_puts("nfc cfg ");
    log_hex8(before);
    log_puts(" -> ");
    log_hex8(after);
    log_puts((after & 0x30) == 0 ? " fd" : " fd?");
    log_nl();
}
