/*
 * Axsem AX8052 Bootloader
 */

#include <ax8052.h>
#include <libmftypes.h>
#include <libmfuart.h>
#include <libmfuart0.h>
#include <libmfflash.h>
#include <libmfcrc.h>
#include "shelfota.h"

/*
 * Configure whether the FRC Oscillator (which is used for Baud Rate Generation)
 * should be slaved to a 32kHz watch crystal on the LPXOSC Pins
 */
#define BOOTLDR_CALFRCOSC    1

/*
 * Configure whether the baud rate clock (16*baud rate) should be output on PA0
 */
#define BOOTLDR_BAUDCLKPA0   0

/*
 * Configure the minimum VDD voltage to start erasing the FLASH
 */
#define BOOTLDR_MINVDD       (uint16_t)(2.5*256)

extern void _sdcc_gsinit_startup(void);

#define bootloader_reset_vector() ((uint16_t)_sdcc_gsinit_startup)
#define bootloader_reset_vector_hi() ((uint8_t)(bootloader_reset_vector() >> 8))
#define bootloader_reset_vector_lo() ((uint8_t)bootloader_reset_vector())

/* The application's entry vector, in the two bytes just below the bootloader.
 * Written from the image's own reset jump when an application is flashed, read
 * back by run_application() to jump into it. It must stay immediately below
 * HOME (see -Wl-bHOME in sdcc-project.json). */
const __code __at(0xd7fe) uint16_t jmp_vector;
__xdata uint8_t orig_jmp_vector[3];
__xdata uint8_t orig_jmp_vector_mask;
__xdata uint8_t line_buffer[260];

static void run_application(void)
{
    OSCFORCERUN = 0x00;
    FRCOSCCONFIG = 0x01;
    WTCFGB = 0x0F;
    IE = EIE = E2IE = 0;
    CLKCON = 0x08;
    __asm
    mov     dptr,#_jmp_vector
    movx    a,@dptr
    inc     dptr
    mov     r0,a
    movx    a,@dptr
    mov     dph,a
    mov     dpl,r0
    clr     a
    mov     _SP,#7
    jmp     @a+dptr
    __endasm;
}

static int8_t waitflash(uint16_t timeout)
{
    uint8_t cnth = timeout >> 8;
    uint8_t cntl = timeout;
    ++cnth;
    ++cntl;
    do {
        do {
            uint8_t st = NVSTATUS;
            if (!(st & 2))
                return -2;
            if (!(st & 1))
                return 0;
            uart0_poll();
            --cntl;
        }
        while (cntl);
        --cnth;
    }
    while (cnth);
    return -1;
}

static char getch(void)
{
    while (!uart0_rxcount()) {
        if (uart0_poll())
            continue;
        enter_standby();
    }
    return uart0_rx();
}

static uint16_t measurevdd(void)
{
    uint16_t vdd;
    ADCCLKSRC = 0x30;
    ADCCONV = 0x01;
    while (ADCCLKSRC & 0x80) {
        uart0_poll();
    }
    ADCCLKSRC = 0x07;
    vdd = (ADCCH0VAL >> 2) + (ADCCH1VAL >> 2) + (ADCCH2VAL >> 2) + (ADCCH3VAL >> 2);
    /* vdd = vdd * 10 / 2^8 */
    vdd >>= 5;
    vdd += vdd >> 2;
    vdd -= 9 << 7;
    return vdd;
}

static int8_t erase_page_write_resetvec(void)
{
    int8_t st;
    // erase page
    if (measurevdd() < BOOTLDR_MINVDD)
        return -4;
    NVADDR0 = 0x00;
    NVSTATUS = 0x20;
    st = waitflash(65535);
    if (st)
        return st;
    // write jump to reset vector into page
    if (measurevdd() < BOOTLDR_MINVDD)
        return -4;
    NVADDR0 = 0x02;
    NVDATA0 = bootloader_reset_vector_lo();
    NVDATA1 = 0xff;
    NVSTATUS = 0x30;
    st = waitflash(128);
    if (st)
        return st;
    NVADDR0 = 0x00;
    NVDATA0 = 0x02;
    NVDATA1 = bootloader_reset_vector_hi();
    NVSTATUS = 0x30;
    st = waitflash(128);
    if (st)
        return st;
    {
        const __code uint8_t *pmem = (const __code uint8_t *)(((uint16_t)NVADDR1) << 8);
        if (*pmem++ != 0x02)
            return -3;
        if (*pmem++ != bootloader_reset_vector_hi())
            return -3;
        if (*pmem++ != bootloader_reset_vector_lo())
            return -3;
    }
    return 0;
}

static int8_t erase_app(void)
{
    int8_t st;
    uint8_t pg;
    orig_jmp_vector_mask = 0;
    flash_unlock();
    NVADDR1 = 0x04;
    st = erase_page_write_resetvec();
    if (st)
        goto ferr;
    NVADDR1 = 0x00;
    st = erase_page_write_resetvec();
    if (st)
        goto ferr;
    // erase all pages starting from 1 up to the boot loader
    pg = 0x04;
    NVADDR0 = 0x00;
    do {
        NVADDR1 = pg;
        NVSTATUS = 0x20;
        st = waitflash(65535);
        if (st)
            goto ferr;
        pg += 4;
    } while (pg != bootloader_reset_vector_hi());
    flash_lock();
    return 0;
ferr:
    flash_lock();
    return st;
}

static int8_t check_app_erased(void)
{
    const __code uint8_t *pmem = 0;
    if (*pmem++ != 0x02)
        return -3;
    if (*pmem++ != bootloader_reset_vector_hi())
        return -3;
    if (*pmem++ != bootloader_reset_vector_lo())
        return -3;
    do {
        if (*pmem++ != 0xFF)
            return -1;
    } while ((uint8_t)(((uint16_t)pmem) >> 8) != bootloader_reset_vector_hi());
    return 0;
}

static int8_t flash_line(void)
{
    __xdata uint8_t *lb;
    uint16_t addr;
    uint8_t cnt = line_buffer[0];
    int8_t st;
    if (!cnt)
        return 0;
    addr = line_buffer[1];
    addr <<= 8;
    addr |= line_buffer[2];
    lb = &line_buffer[4];
    flash_unlock();
    do {
        if (addr < 3) {
            orig_jmp_vector[(uint8_t)addr] = *lb++;
            orig_jmp_vector_mask |= 1 << (uint8_t)addr;
            ++addr;
            if (3 & (uint8_t)~orig_jmp_vector_mask)
                continue;
            if (!((orig_jmp_vector[0] ^ 0x01) & 0x0F)) {
                NVDATA0 = orig_jmp_vector[1];
                NVDATA1 = orig_jmp_vector[0] >> 5;
            } else if (!(7 & (uint8_t)~orig_jmp_vector_mask) && !(0xEF & (0x02 ^ orig_jmp_vector[0]))) {
                NVDATA0 = orig_jmp_vector[2];
                NVDATA1 = orig_jmp_vector[1];
            } else {
                continue;
            }
            NVADDR0 = (uint16_t)&jmp_vector;
            NVADDR1 = ((uint16_t)&jmp_vector) >> 8;
            NVSTATUS = 0x30;
            st = waitflash(128);
            if (st) {
                flash_lock();
                return st;
            }
            if (((uint16_t)NVDATA1) ^ NVDATA0 ^ jmp_vector)
                goto cmperr;
            continue;
        }
        NVADDR0 = (uint8_t)addr & (uint8_t)~1;
        NVADDR1 = addr >> 8;
        if ((uint8_t)(addr >> 8) >= bootloader_reset_vector_hi())
            goto cmperr;
        if (addr & 1) {
            NVDATA0 = 0xff;
            NVDATA1 = *lb++;
            NVSTATUS = 0x30;
            st = waitflash(128);
            if (st)
                goto ferr;
            if (NVDATA1 != *(const __code uint8_t *)addr)
                goto cmperr;
            ++addr;
            continue;
        }
        if (!(cnt & (uint8_t)~1)) {
            NVDATA0 = *lb++;
            NVDATA1 = 0xff;
            NVSTATUS = 0x30;
            st = waitflash(128);
            if (st)
                goto ferr;
            if (NVDATA0 != *(const __code uint8_t *)addr)
                goto cmperr;
            ++addr;
            continue;
        }
        NVDATA0 = *lb++;
        NVDATA1 = *lb++;
        NVSTATUS = 0x30;
        st = waitflash(128);
        if (st)
            goto ferr;
        if (NVDATA0 != *(const __code uint8_t *)addr)
            goto cmperr;
        ++addr;
        if (NVDATA1 != *(const __code uint8_t *)addr)
            goto cmperr;
        ++addr;
        --cnt;
    } while (--cnt);
    flash_lock();
    st = 0;
    for (;;) {
        char ch = getch();
        switch (ch) {
        case '\n':
        case '\r':
            return st;

        case ' ':
        case '\t':
            break;

        default:
            st = -7;
            break;
        }
    }

cmperr:
    flash_lock();
    return -6;

ferr:
    flash_lock();
    return st;
}

static int8_t parse_ihex(void)
{
    uint16_t i = 0;
    uint8_t s = 0;
    do {
        uint8_t val = 0;
        uint8_t cnt = 2;
        do {
            uint8_t ch = getch();
            val <<= 4;
            ch -= '0';
            if (ch < 10) {
                val |= ch;
                continue;
            }
            ch -= ('A' - '0');
            if (ch < 6) {
                val |= ch + 10;
                continue;
            }
            ch -= ('a' - 'A');
            if (ch < 6) {
                val |= ch + 10;
                continue;
            }
            return -3;
        } while (--cnt);
        line_buffer[i++] = val;
        s += val;
    } while (i < 5 + line_buffer[0]);
    if (s)
        return -4;
    if (line_buffer[3])
        return (line_buffer[3] == 1) ? 0 : -5;
    return flash_line();
}

static void write_banner(void)
{
    static const char __code uart_banner[] = "AX8052 Bootloader V1.1 Checksum 0x";
    static const char __code uart_crlf[] = "\r\n";
    uint16_t crc = crc_crc16((const __code uint8_t *)(((uint16_t)bootloader_reset_vector_hi()) << 8),
                             ((uint16_t)(uint8_t)(0xfc - bootloader_reset_vector_hi())) << 8, 0xffff);
    uart0_writestr(uart_banner);
    uart0_writehex16(crc, 4, WRNUM_PADZERO);
    uart0_writestr(uart_crlf);
}


/* ── OTA update from the tag's SPI flash ──────────────────────────────────────
 *
 * The application is the only part that transfers and stores a new firmware; it
 * leaves a magic sequence and a CRC in sector 0 of the SPI flash and resets. All
 * this side does is: notice the magic, verify the CRC *before* it destroys the
 * application, program the image, and erase the magic so the update runs once.
 *
 * Deliberately bit-banged and buffer-at-a-time: no SPI driver, no radio, and no
 * second copy of anything the serial path already has. It costs ~0.5 KB, which
 * is why the bootloader now sits at 0xE000 instead of 0xE400 (see -Wl-bHOME).
 */
#define OTA_CHUNK   32

static uint8_t __xdata ota_buf[OTA_CHUNK];

static uint8_t ota_spi(uint8_t out)
{
    /* The hardware SPI master, exactly as the application drives it (its
     * spi.c): mode 0, MSB first, one byte per SPSHREG write, ready when
     * SPSTATUS bit 0 sets. A bit-banged version read 0x000000 for the JEDEC
     * id on hardware while this one reads 0x1F4200, so the bit-bang was the
     * broken part, not the flash. */
    SPSHREG = out;
    while (!(SPSTATUS & 0x01))
        ;
    return SPSHREG;
}

static void ota_spi_begin(void)
{
    /* A soft reset (ljmp 0x0000) does not reset the peripherals, so start from
     * a known SPI state instead of inheriting the application's. */
    SPMODE = 0x00;                  /* make sure any previous master is off */
    SPCLKSRC = 0xD8;                /* FRC-derived, slow: the app's setting */
    DIRC |= 0x07;                   /* CS, SCK, MOSI out ... */
    DIRC &= (uint8_t)~0x08;         /* ... MISO in */
    PORTC_0 = 1;                    /* flash CS idle high */
    /* The shared bus has three chips on it. The vendor startup drives PB1 (NFC
     * CS) LOW, so the NFC chip would answer on MISO while the flash is being
     * read; PA1 (EPD CS) is left floating. Park both high first. */
    DIRA |= 0x02;
    PORTA_1 = 1;
    DIRB |= 0x02;
    PORTB_1 = 1;
    SPMODE = 0x01;                  /* master, mode 0, MSB first */
    (void)SPSHREG;                  /* clear any pending flag */
}

static void ota_flash_read(uint32_t addr, uint8_t *buf, uint8_t len)
{
    uint8_t i;

    PORTC_0 = 0;
    ota_spi(0x03);
    ota_spi((uint8_t)(addr >> 16));
    ota_spi((uint8_t)(addr >> 8));
    ota_spi((uint8_t)addr);
    for (i = 0; i < len; i++)
        buf[i] = ota_spi(0x00);
    PORTC_0 = 1;
}

static void ota_flash_wait(void)
{
    uint8_t status;

    do {
        PORTC_0 = 0;
        ota_spi(0x05);              /* read status */
        status = ota_spi(0x00);
        PORTC_0 = 1;
    } while (status & 0x01);        /* write/erase in progress */
}

static void ota_flash_erase_header(void)
{
    ota_flash_wait();
    PORTC_0 = 0;
    ota_spi(0x06);                  /* write enable */
    PORTC_0 = 1;
    PORTC_0 = 0;
    ota_spi(0x20);                  /* 4 KiB sector erase at 0 */
    ota_spi(0x00);
    ota_spi(0x00);
    ota_spi(0x00);
    PORTC_0 = 1;
    ota_flash_wait();
}

static uint16_t __xdata ota_len;
static uint16_t __xdata ota_crc;

/* LEDs (active high): PB0 white, PB7 blue, PB6 green, PC4 red. Nothing is
 * lit on a normal boot - only an update gets an indication. */
#define LED_WHITE   0
#define LED_BLUE    1
#define LED_GREEN   2
#define LED_RED     3

static void led_set(uint8_t led, uint8_t on)
{
    switch (led) {
    case LED_WHITE: PORTB_0 = on; break;
    case LED_BLUE:  PORTB_7 = on; break;
    case LED_GREEN: PORTB_6 = on; break;
    default:        PORTC_4 = on; break;
    }
}

/* Self-terminating on purpose: an LED left lit behind the e-paper glass warms
 * the panel into a visible blob, so every indication is on, wait, off. */
static void led_pulse(uint8_t led, uint16_t ms)
{
    led_set(led, 1);
    while (ms--)
        delay(1000);            /* libmf delay() is microseconds-ish */
    led_set(led, 0);
}

static void led_init(void)
{
    PORTB &= (uint8_t)~0xC1;    /* latch off while still inputs ... */
    PORTC &= (uint8_t)~0x10;
    DIRB |= 0xC1;               /* ... then drive PB0/PB6/PB7 and PC4 */
    DIRC |= 0x10;
}

/* Power the SPI flash's switched rail (PA5, transistor U4, active low) before
 * the first read. At power-up the rail is off, and an unpowered flash reads back
 * as all 0xFF - which the bootloader would take for "no update pending" and the
 * application would take for a blank identity. */
static void ota_power_up(void)
{
    uint16_t i;

    ANALOGA &= (uint8_t)~0x20;  /* PA5 must be digital to drive the rail (startup
                                 * sets ANALOGA = 0x3F, i.e. PA0..PA5 analog) */
    DIRA |= 0x20;               /* PA5 becomes an output */
    PORTA_5 = 0;                /* U4 active low: rail on */
    for (i = 0; i < 0x2000; i++) /* ~4 ms settle: the app uses 5 ms and works */
        ;
}

/* 1 when the SPI flash holds a committed image whose header checks out.
 * Logs the JEDEC id and the four header bytes it actually read, so a tag that
 * "does not see the update" can be told apart from one that cannot read the
 * flash at all. */
static uint8_t ota_pending(void)
{
    uint8_t header[OTA_HDR_BYTES];
    uint8_t id[3];
    uint8_t tries;

    ota_power_up();
    ota_spi_begin();

    PORTC_0 = 0;
    ota_spi(0x9F);                       /* JEDEC id */
    id[0] = ota_spi(0x00);
    id[1] = ota_spi(0x00);
    id[2] = ota_spi(0x00);
    PORTC_0 = 1;
    uart0_writestr("OTA jedec ");
    uart0_writehex16(((uint16_t)id[0] << 8) | id[1], 4, WRNUM_PADZERO);
    uart0_writehex16((uint16_t)id[2], 2, WRNUM_PADZERO);
    uart0_writestr("\r\n");

    for (tries = 0; tries < 3; tries++) {
        ota_flash_read(OTA_HDR_ADDR, header, OTA_HDR_BYTES);
        uart0_writestr("OTA hdr ");
        uart0_writehex16(((uint16_t)header[0] << 8) | header[1], 4, WRNUM_PADZERO);
        uart0_writehex16(((uint16_t)header[2] << 8) | header[3], 4, WRNUM_PADZERO);
        uart0_writestr("\r\n");
        if (ota_header_parse(header, &ota_len, &ota_crc)) {
            uart0_writestr("OTA image len=");
            uart0_writenum16(ota_len, 1, 0);
            uart0_writestr(" crc=");
            uart0_writehex16(ota_crc, 4, WRNUM_PADZERO);
            uart0_writestr("\r\n");
            return 1;
        }
        delay(2000);
    }
    uart0_writestr("OTA none
");
    return 0;
}

/* Verify, erase, program, clear the magic. 0 = the application was replaced. */
static int8_t ota_program(void)
{
    uint8_t i, n;
    uint16_t crc, off, word;
    int8_t st;

    /* 1. the CRC first: a corrupt image must never cost the working firmware */
    crc = OTA_CRC_INIT;
    for (off = 0; off < ota_len; off += OTA_CHUNK) {
        n = (uint8_t)(((uint16_t)(ota_len - off) < OTA_CHUNK) ? (ota_len - off) : OTA_CHUNK);
        ota_flash_read(OTA_IMAGE_ADDR + off, ota_buf, n);
        crc = ota_crc16(ota_buf, n, crc);
    }
    if (crc != ota_crc) {
        uart0_writestr("OTA ERR crc\r\n");
        ota_flash_erase_header();
        return -1;
    }

    /* 2. the entry vector: the image's reset jump is 02 hi lo, and
     * run_application() jumps through jmp_vector (low byte first) */
    ota_flash_read(OTA_IMAGE_ADDR, ota_buf, 3);
    if (ota_buf[0] != 0x02) {
        uart0_writestr("OTA ERR entry\r\n");
        ota_flash_erase_header();
        return -2;
    }

    st = erase_app();
    if (st) {
        uart0_writestr("OTA ERR erase\r\n");
        return st;
    }

    flash_unlock();
    NVADDR0 = (uint16_t)&jmp_vector;
    NVADDR1 = ((uint16_t)&jmp_vector) >> 8;
    NVDATA0 = ota_buf[2];
    NVDATA1 = ota_buf[1];
    NVSTATUS = 0x30;
    st = waitflash(128);
    if (st) {
        flash_lock();
        return st;
    }

    /* 3. the image itself, 32-byte words at a time. Addresses 0..2 are the
     * bootloader's own reset vector: skipped. The word at 2 keeps its low byte
     * (0xFF programs nothing) and carries image byte 3 in its high byte. */
    for (off = 0; off < ota_len; off += OTA_CHUNK) {
        n = (uint8_t)(((uint16_t)(ota_len - off) < OTA_CHUNK) ? (ota_len - off) : OTA_CHUNK);
        ota_flash_read(OTA_IMAGE_ADDR + off, ota_buf, n);
        for (i = 0; i < n; i += 2) {
            word = (uint16_t)(off + i);
            if (word < 2)
                continue;
            NVADDR0 = (uint8_t)word;
            NVADDR1 = (uint8_t)(word >> 8);
            NVDATA0 = (word == 2) ? 0xFF : ota_buf[i];
            NVDATA1 = (uint8_t)((i + 1 < n) ? ota_buf[i + 1] : 0xFF);
            NVSTATUS = 0x30;
            st = waitflash(128);
            if (st) {
                flash_lock();
                return st;
            }
        }
    }
    flash_lock();

    /* 4. the magic goes last: the update must not run twice */
    ota_flash_erase_header();
    uart0_writestr("OTA ok, booting\r\n");
    return 0;
}

uint8_t _sdcc_external_startup(void)
{
    DPS = 0x00;
    ANALOGA = 0x3F;
    PORTA = 0xC0;
    DIRA = 0x00;
    PORTB = 0xFC;
    DIRB = 0x13;
    PALTB = 0x10;
    PORTC = 0xF3;
    DIRC = 0x0F;
    PORTR = 0xFF;
    DIRR = 0x15;
    RADIOMUX = 0x47;
    RADIOACC = 0x00;
    return 0;
}

#if defined(SDCC)
extern uint8_t _start__stack[];
#endif

void bootloader(void)
{
    static const char __code uart_errunknowncmd[] = "ERR-Unknown Command\r\n";
    static const char __code uart_errflashtimeout[] = "ERR-FLASH Timeout\r\n";
    static const char __code uart_errflashlock[] = "ERR-FLASH Locked\r\n";
    static const char __code uart_errflashvector[] = "ERR-FLASH Vector\r\n";
    static const char __code uart_errflashvdd[] = "ERR-VDD low\r\n";
    static const char __code uart_okflasherase[] = "OK-FLASH Erase\r\n";
    static const char __code uart_okflasherasecheck[] = "OK-FLASH Erase Check\r\n";
    static const char __code uart_errflasherasecheck[] = "ERR-FLASH not Erased\r\n";
    static const char __code uart_okrunapp[] = "OK-Running Application\r\n";
    static const char __code uart_errrunapp[] = "ERR-no Application\r\n";
    static const char __code uart_errhexinvalidchar[] = "ERR-Invalid Hex Character\r\n";
    static const char __code uart_errhexchksum[] = "ERR-Hex Checksum Error\r\n";
    static const char __code uart_errhexrectype[] = "ERR-Unknown Record Type ignored\r\n";
    static const char __code uart_errhexflashwrite[] = "ERR-FLASH write error\r\n";
    static const char __code uart_errhexgarbagechar[] = "ERR-Garbage Characters ignored\r\n";
    static const char __code uart_vdd1[] = "VDD ";
    static const char __code uart_vdd2[] = "V\r\n";

#if !defined(SDCC) && !defined(__ICC8051__)
    _sdcc_external_startup();
#endif

#if defined(SDCC)
    __asm
    .area   HOME    (CODE)
    .area   UART0S0 (CODE)
    .area   UART0S1 (CODE)
    .area   UART0S2 (CODE)
    .area   UART0S3 (CODE)
    .area   UART0S4 (CODE)
    .area   UART0S5 (CODE)
    .area   WTCANSLP0 (CODE)
    .area   WTCANSLP1 (CODE)
    .area   WTCANSLP2 (CODE)
    .area   WTSTDBY0 (CODE)
    .area   WTSTDBY1 (CODE)
    .area   WTSTDBY2 (CODE)
    .area   SSEG (DATA)
__start__stack:
    .ds     1
    .area   CSEG (CODE)
    G$_start__stack$0$0 = __start__stack
    .globl  G$_start__stack$0$0
    __endasm;
#endif

    led_init();                 /* all off: a normal boot shows nothing */
    flash_apply_calibration();
    CLKCON = 0x00;

#if BOOTLDR_CALFRCOSC
    // slave FRC Oscillator to LPX oscillator
    FRCOSCREF = 19531;
    FRCOSCKFILT = 2800; /* theoretical maximum is 71582 */
    LPXOSCGM = 0x90;
    OSCFORCERUN |= 0x04;
    FRCOSCCONFIG = (6 << 3) | CLKSRC_LPXOSC;
    // force ready logic
    WTCFGB = (1 << 3) | CLKSRC_LPXOSC;
    // wait for a couple of calibration cycles to get close to the desired frequency
    {
        uint8_t i = 128;
        PORTC_3 = 1;
        OSCCALIB = 0x01;
        IE_5 = 1;
        do {
            for (;;) {
                uint8_t oc = OSCCALIB;
                if (oc & 0x40)
                    break;
                enter_standby();
            }
            FRCOSCFREQ1;
        } while (--i);
        IE_5 = 0;
        OSCCALIB = 0x00;
        PORTC_3 = 0;
    }
#endif

    ADCCH0CONFIG = 0xD9;
    ADCCH1CONFIG = 0xD9;
    ADCCH2CONFIG = 0xD9;
    ADCCH3CONFIG = 0xD9;

    orig_jmp_vector_mask = 0;

    uart_timer0_baud(CLKSRC_FRCOSC, 38400, 20000000);
    uart0_init(0, 8, 1);

#if BOOTLDR_BAUDCLKPA0
    // for debugging, output the baud rate clock at PA0
    PALTA |= 0x01;
    DIRA |= 0x01;
#endif

    /* Apply a pending OTA image *before* booting: the application writes the
     * magic into SPI flash and resets, so this has to run on every reset - not
     * only when the boot button (SW5) is held. It used to sit after the
     * auto-run below, which meant a normal reset jumped straight into the old
     * application and never looked at the update at all. */
    if (ota_pending()) {
        led_pulse(LED_BLUE, 500);   /* a new image is found: flashing it */
        if (ota_program() == 0) {
            led_pulse(LED_GREEN, 500);
            /* fall through: jmp_vector now points into the new application */
        } else {
            led_pulse(LED_RED, 500);
        }
    }

    /* Start the application if it looks valid and button SW5 is not pressed.
     * Wait for the UART to drain first: the application re-initialises it right
     * away, which would cut the diagnostics off mid-line. */
    if (PINB & 0x08 && jmp_vector != 0xFFFF) {
        while (0x44 & (uint8_t)~U0STATUS);
        run_application();
    }

    write_banner();

    for (;;) {
        char ch = getch();
        switch (ch) {
        case ' ':
        case '\r':
        case '\n':
            break;

        case '?':
            uart0_wait_txfree(63);
            write_banner();
            break;

        case 'K':
        {
            int8_t st = erase_app();
            if (!st)
                st = check_app_erased();
            uart0_wait_txfree(63);
            switch (st) {
            case 0:
                uart0_writestr(uart_okflasherase);
                break;

            case -2:
                uart0_writestr(uart_errflashlock);
                break;

            case -3:
                uart0_writestr(uart_errflashvector);
                break;

            case -4:
                uart0_writestr(uart_errflashvdd);
                break;

            default:
                uart0_writestr(uart_errflashtimeout);
                break;
            }
            break;
        }

        case 'Z':
        {
            int8_t st = check_app_erased();
            uart0_wait_txfree(63);
            switch (st) {
            case 0:
                uart0_writestr(uart_okflasherasecheck);
                break;

            case -3:
                uart0_writestr(uart_errflashvector);
                break;

            default:
                uart0_writestr(uart_errflasherasecheck);
                break;
            }
            break;
        }

        case 'R':
        {
            uart0_wait_txfree(63);
            if (jmp_vector == 0xFFFF) {
                uart0_writestr(uart_errrunapp);
                break;
            }
            uart0_writestr(uart_okrunapp);
            uart0_wait_txfree(63);
            // wait until U0TXEMPTY and U0TXIDLE are both set
            while (0x44 & (uint8_t)~U0STATUS);
            run_application();
            break;
        }

        case ':':
        {
            int8_t st = parse_ihex();
            if (!st)
                break;
            uart0_wait_txfree(63);
            switch (st) {
            case -2:
                uart0_writestr(uart_errflashlock);
                break;

            case -3:
                uart0_writestr(uart_errhexinvalidchar);
                break;

            case -4:
                uart0_writestr(uart_errhexchksum);
                break;

            case -5:
                uart0_writestr(uart_errhexrectype);
                break;

            case -6:
                uart0_writestr(uart_errhexflashwrite);
                break;

            case -7:
                uart0_writestr(uart_errhexgarbagechar);
                break;

            default:
                uart0_writestr(uart_errflashtimeout);
                break;
            }
            break;
        }

        case 'V':
        {
            uint16_t vdd = measurevdd();
            uart0_wait_txfree(63);
            uart0_writestr(uart_vdd1);
            uart0_writenum16(vdd >> 8, 1, 0);
            uart0_tx('.');
            vdd &= 0xff;
            vdd *= 100;
            uart0_writenum16(vdd >> 8, 2, WRNUM_PADZERO);
            uart0_writestr(uart_vdd2);
            break;
        }

        default:
            // clear UART buffer
            uart0_rxadvance(uart0_rxcount());
            uart0_wait_txfree(63);
            uart0_writestr(uart_errunknowncmd);
            break;
        }
    }
}
