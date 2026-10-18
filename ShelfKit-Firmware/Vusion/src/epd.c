/**
 * @file epd.c
 * @brief Minimal IL0373 / GDEW026Z39 (152x296 BWR) e-paper driver
 *
 * Init sequence is byte-for-byte the sequence proven on this exact panel
 * on the SES-Imagotag tag, from three independent implementations:
 *   - andrei-tatar/imagotag-hack  firmware/src/display/epd.c  (8051, CC2510 tag)
 *   - angrymew/firmware-cc2510    src/display/epd.c           (identical)
 *   - michaelkamprath/ePaperDriverLib (GDEW026Z39 configuration)
 * See GDEW026Z39-init-reference.md in the repo root for the full notes.
 *
 *   BTST 0x06 = 0x17,0x17,0x17      booster soft start
 *   PON  0x04                        power on, wait BUSY
 *   PSR  0x00 = 0x0F                 LUT from OTP, BWR format
 *   TRES 0x61 = 0x98,0x01,0x28       resolution 152 x 296 (3 bytes)
 *   CDI  0x50 = 0x77                 VCOM and data interval
 *
 * No LUT tables are uploaded (OTP LUT), no PWR/PLL/VCM_DC commands -
 * those belong to other IL0373 panels, not the Z39.
 *
 * Refresh: 0x10 = black/white plane, 0x13 = red plane (5624 bytes each),
 * 0x12 = refresh. Bit value 0 = ink, 1 = white in both planes.
 */

#include "epd.h"
#include "spi.h"
#include "board.h"

/* ── low level ────────────────────────────────────────────────────────── */

static void epd_cmd(uint8_t cmd)
{
    EPD_DC = 0;
    spi_select(SPI_DEV_EPD);
    spi_transfer(cmd);
    spi_deselect(SPI_DEV_EPD);
    EPD_DC = 1;
}

static void epd_data(uint8_t data)
{
    spi_select(SPI_DEV_EPD);
    spi_transfer(data);
    spi_deselect(SPI_DEV_EPD);
}

/* libmf's delay() takes microseconds and tops out at ~65 ms per call. */
static void epd_delay_ms(uint16_t ms)
{
    while (ms--)
        delay(1000);
}

/* Send a command that makes the panel busy and wait it out. Polarity-agnostic and
 * bounded, like the boot demo that is proven on this hardware: the idle level is
 * sampled before the command, then BUSY must leave it (up to start_ms) and come
 * back (up to done_ms). An unbounded wait here hangs the whole tag, which then
 * stops acknowledging the image frames that follow BEGIN.
 *
 * The return value says what the panel did, which is the difference between
 * "refreshed" and "never had power" and is logged by the caller:
 *   0 = BUSY never left idle, the panel did not react at all
 *   1 = BUSY pulsed and came back, the command really ran
 *   2 = BUSY stayed asserted, the wait ran out (long refresh, do not power off) */
static uint8_t epd_cmd_wait(uint8_t cmd, uint16_t start_ms, uint16_t done_ms)
{
    uint8_t idle = EPD_BUSY;
    uint16_t t;

    epd_cmd(cmd);
    for (t = start_ms; EPD_BUSY == idle; t--) {
        if (!t)
            return EPD_BUSY_NONE;
        delay(1000);
    }
    for (t = done_ms; EPD_BUSY != idle; t--) {
        if (!t)
            return EPD_BUSY_TIMEOUT;
        delay(1000);
    }
    return EPD_BUSY_DONE;
}

/* ── public API ───────────────────────────────────────────────────────── */

void epd_open(void)
{
    /* Control pins: DC out, RST out, BUSY in. CS (PA1) is set up by
     * spi_init(). NOTE: RST shares PB5 with the UART RX function - the
     * UART must not be enabled while the panel is being driven (the boot
     * demo in main.c therefore does not init UART0). */
    DIRA |= 0x01;                       /* DC on PA0, output */
    DIRB |= 0x20;                       /* RST on PB5, output */
    DIRB &= (uint8_t)~0x04;             /* BUSY on PB2, input */
    EPD_DC = 1;
    EPD_RST = 1;

    /* Hardware reset: 100 ms low, then 100 ms settle */
    EPD_RST = 0;
    epd_delay_ms(100);
    EPD_RST = 1;
    epd_delay_ms(100);

    /* Booster soft start */
    epd_cmd(0x06);
    epd_data(0x17);
    epd_data(0x17);
    epd_data(0x17);

    /* Power on, then wait for the booster */
    (void)epd_cmd_wait(0x04, 300, 2500);

    /* Panel setting: LUT from OTP, BWR format */
    epd_cmd(0x00);
    epd_data(0x0F);

    /* Resolution: 152 (wide) x 296 (tall) - the proven 3-byte form */
    epd_cmd(0x61);
    epd_data((uint8_t)EPD_W);           /* 0x98 */
    epd_data((uint8_t)(EPD_H >> 8));    /* 0x01 */
    epd_data((uint8_t)EPD_H);           /* 0x28 */

    /* VCOM and data interval */
    epd_cmd(0x50);
    epd_data(0x77);
}

void epd_init(void)
{
    epd_open();

    /* Start with a clean white screen */
    epd_clear(0xFF, 0xFF);
}

void epd_stream_begin(uint8_t cmd)
{
    epd_cmd(cmd);
}

void epd_stream_write(const uint8_t __xdata *data, uint8_t len)
{
    spi_select(SPI_DEV_EPD);
    while (len--)
        spi_transfer(*data++);
    spi_deselect(SPI_DEV_EPD);
}

void epd_sleep(void)
{
    (void)epd_cmd_wait(0x02, 500, 2500);    /* power off */
    epd_cmd(0x07);                          /* deep sleep */
    epd_data(0xA5);
}

void epd_upload(uint8_t cmd, const uint8_t *plane, uint16_t len)
{
    epd_cmd(cmd);
    spi_select(SPI_DEV_EPD);
    while (len--)
        spi_transfer(*plane++);
    spi_deselect(SPI_DEV_EPD);
}

uint8_t epd_refresh(void)
{
    /* A BWR refresh takes ~15 s at room temperature and distinctly longer when
     * the panel is cold, so the ceiling has to be generous: giving up early is
     * not just a lost wait, the caller would then power the panel off in the
     * middle of the waveform and the glass would keep the old image. 60000 is
     * the largest value the uint16_t parameter can express; libmf's delay() is
     * only roughly calibrated, so treat it as "up to a minute, and bounded". */
    return epd_cmd_wait(0x12, 3000, 60000);     /* display refresh */
}

void epd_clear(uint8_t bw_byte, uint8_t red_byte)
{
    uint16_t i;

    epd_cmd(0x10);                      /* black/white plane */
    spi_select(SPI_DEV_EPD);
    for (i = 0; i < EPD_PLANE_BYTES; i++)
        spi_transfer(bw_byte);
    spi_deselect(SPI_DEV_EPD);

    epd_cmd(0x13);                      /* red plane */
    spi_select(SPI_DEV_EPD);
    for (i = 0; i < EPD_PLANE_BYTES; i++)
        spi_transfer(red_byte);
    spi_deselect(SPI_DEV_EPD);

    (void)epd_refresh();
}

void epd_display(const uint8_t *bw_plane, const uint8_t *red_plane)
{
    epd_upload(0x10, bw_plane, EPD_PLANE_BYTES);
    epd_upload(0x13, red_plane, EPD_PLANE_BYTES);
    (void)epd_refresh();
}
