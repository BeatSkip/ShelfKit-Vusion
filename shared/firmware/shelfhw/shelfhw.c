/**
 * @file shelfhw.c
 * @brief Board bring-up shared by the Hub and Vusion firmware
 *
 * The clock and radio-pin sequences follow the AX-RadioLab SLAVE template
 * (WirelessDemo/SLAVE/main.c); the Minikit specifics (LED/button pins, COM0
 * display, whole-port writes) are replaced by read-modify-write accesses that
 * leave the tag's e-paper, NFC and flash pins alone.
 */

#include <ax8052f143.h>
#include <libmf.h>
#include <libmftypes.h>
#include <libmfflash.h>
#include <libmfwtimer.h>
#include <libmfuart.h>
#include <libmfuart0.h>
#include "axradio.h"
#include "shelfhw.h"

/* ── interrupt hooks the radio engine calls ──────────────────────────── */

void enable_radio_interrupt_in_mcu_pin(void)
{
    IE_4 = 1;
}

void disable_radio_interrupt_in_mcu_pin(void)
{
    IE_4 = 0;
}

/* Power management interrupt, as in the vendor template: on a brown-out
 * freeze the pins and halt instead of running on a collapsing supply. */
static void pwrmgmt_irq(void) __interrupt(INT_POWERMGMT)
{
    uint8_t pc = PCON;

    if (!(pc & 0x80))
        return;

    GPIOENABLE = 0;
    IE = EIE = E2IE = 0;

    for (;;)
        PCON |= 0x01;
}

/* ── LEDs ─────────────────────────────────────────────────────────────── */

static void led_write(uint8_t led, uint8_t on)
{
    uint8_t level = SHELFHW_LED_ACTIVE_HIGH ? on : (uint8_t)!on;

    switch (led) {
    case SHELFHW_LED_WHITE:
        PORTB = level ? (PORTB | 0x01) : (PORTB & (uint8_t)~0x01);
        break;
    case SHELFHW_LED_BLUE:
        PORTB = level ? (PORTB | 0x80) : (PORTB & (uint8_t)~0x80);
        break;
    case SHELFHW_LED_GREEN:
        PORTB = level ? (PORTB | 0x40) : (PORTB & (uint8_t)~0x40);
        break;
    default:
        PORTC = level ? (PORTC | 0x10) : (PORTC & (uint8_t)~0x10);
        break;
    }
}

static uint8_t led_is_on(uint8_t led)
{
    uint8_t level;

    switch (led) {
    case SHELFHW_LED_WHITE: level = PORTB & 0x01; break;
    case SHELFHW_LED_BLUE:  level = PORTB & 0x80; break;
    case SHELFHW_LED_GREEN: level = PORTB & 0x40; break;
    default:                level = PORTC & 0x10; break;
    }
    return SHELFHW_LED_ACTIVE_HIGH ? (level != 0) : (level == 0);
}

void shelfhw_led(uint8_t led, uint8_t on)
{
    led_write(led, on);
}

void shelfhw_led_toggle(uint8_t led)
{
    led_write(led, (uint8_t)!led_is_on(led));
}

/* ── pseudo-random numbers ────────────────────────────────────────────── */

static uint16_t rnd_state;

uint16_t shelfhw_random(void)
{
    uint16_t x = rnd_state ^ (uint16_t)wtimer0_curtime();

    if (!x)
        x = 0xACE1u;
    x ^= (uint16_t)(x << 7);
    x ^= (uint16_t)(x >> 9);
    x ^= (uint16_t)(x << 8);
    rnd_state = x;
    return x;
}

/* ── UART0 TX log (register level, avoids the libmf FIFO tables) ─────── */

void log_putc(uint8_t c)
{
    while (!(U0STATUS & 0x04))      /* wait for U0TXEMPTY */
        ;
    U0SHREG = c;
    U0CTRL |= 0x08;                 /* arm the TX-done flag, like iocore */
}

void log_puts(const char *s)
{
    while (*s)
        log_putc((uint8_t)*s++);
}

static void log_nibble(uint8_t n)
{
    log_putc((uint8_t)(n < 10 ? '0' + n : 'a' + n - 10));
}

void log_hex8(uint8_t v)
{
    log_nibble((uint8_t)(v >> 4));
    log_nibble((uint8_t)(v & 0x0F));
}

void log_hex16(uint16_t v)
{
    log_hex8((uint8_t)(v >> 8));
    log_hex8((uint8_t)v);
}

void log_dec(uint16_t v)
{
    char buf[5];
    uint8_t n = 0;

    do {
        buf[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v);
    while (n)
        log_putc((uint8_t)buf[--n]);
}

void log_sdec(int16_t v)
{
    if (v < 0) {
        log_putc('-');
        log_dec((uint16_t)(-v));
    } else {
        log_dec((uint16_t)v);
    }
}

void log_nl(void)
{
    log_putc('\r');
    log_putc('\n');
}

/* ── bring-up ─────────────────────────────────────────────────────────── */

void shelfhw_init(void)
{
    uint8_t i;

    /* PA3/PA4 carry the 32 kHz LPXOSC crystal */
    ANALOGA |= 0x18;

    /* Park the chip selects of EPD (PA1), NFC (PB1) and flash (PC0) high */
    PORTA |= 0x02;
    PORTB |= 0x02;
    PORTC |= 0x01;
    DIRA |= 0x02;
    DIRB |= 0x02;
    DIRC |= 0x01;

    /* LEDs (PB0, PB6, PB7, PC4): outputs, off */
    DIRB |= 0xC1;
    DIRC |= 0x10;
    led_write(SHELFHW_LED_WHITE, 0);
    led_write(SHELFHW_LED_BLUE, 0);
    led_write(SHELFHW_LED_GREEN, 0);
    led_write(SHELFHW_LED_RED, 0);

    /* Link to the on-chip AX5043 */
    PORTR = 0x0B;
    DIRR = 0x15;
    axradio_setup_pincfg1();

    /* UART0 TX on PB4. RX stays disabled so PB5 (EPD reset) is untouched. */
    PALTB |= 0x10;
    DIRB |= 0x10;
    PORTB |= 0x10;

    DPS = 0;
    GPIOENABLE = 1;

    flash_apply_calibration();
    CLKCON = 0x00;

    /* 20 MHz FRC oscillator slaved to the 32 kHz LPXOSC crystal - the AXSEM
     * bootloader's sequence, needed for an exact 38400 baud. */
    FRCOSCREF = 19531;
    FRCOSCKFILT = 2800;
    LPXOSCGM = 0x90;
    OSCFORCERUN |= 0x04;
    FRCOSCCONFIG = (6 << 3) | CLKSRC_LPXOSC;
    WTCFGB = (1 << 3) | CLKSRC_LPXOSC;
    i = 128;
    OSCCALIB = 0x01;
    IE_5 = 1;
    do {
        while (!(OSCCALIB & 0x40))
            enter_standby();
        (void)FRCOSCFREQ1;
    } while (--i);
    IE_5 = 0;
    OSCCALIB = 0x00;

    /* Wake-up timers as the radio engine expects them */
    LPOSCCONFIG = 0x09;
    wtimer0_setclksrc(CLKSRC_LPOSC, 0x01);
    wtimer1_setclksrc(CLKSRC_FRCOSC, 7);
    wtimer_init();

    uart_timer0_baud(CLKSRC_FRCOSC, 38400, 20000000);
    uart0_init(0, 8, 1);

    IE = 0x40;
    EIE = 0x00;
    E2IE = 0x00;
    EA = 1;

    rnd_state = (uint16_t)wtimer0_curtime();
}

void shelfhw_poll(void)
{
    wtimer_runcallbacks();
    EA = 0;
    IE_1 = 1;                       /* wake-up timer (vector 1) ends the standby; no ISR runs, EA is off */
    wtimer_idle(WTFLAG_CANSTANDBY);
    IE_1 = 0;
    EA = 1;
}
