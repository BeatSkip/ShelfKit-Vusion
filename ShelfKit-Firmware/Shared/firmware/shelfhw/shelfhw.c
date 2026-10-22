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
#include "shelf_config.h"   /* the per-target power switches live here */
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

void shelfhw_led(uint8_t led, uint8_t on)
{
    led_write(led, on);
}

/* Blocking, self-terminating indication. That is deliberate: the LEDs sit
 * behind the e-paper glass and a lit one warms the panel into a visible blob,
 * so the only safe way to drive them is on, wait, off - a level that some
 * later code forgets to clear is exactly what this file must not allow. */
void shelfhw_led_pulse(uint8_t led, uint16_t ms)
{
    if (!ms)
        ms = 1;                     /* a 0 here would wrap into a 65 s pulse */
    shelfhw_led(led, 1);
    while (ms--)
        delay(1000);                /* libmf delay() is microseconds-ish */
    shelfhw_led(led, 0);
}

void shelfhw_fatal(uint8_t led)
{
    uint16_t i;

    for (;;) {
        shelfhw_led_pulse(led, SHELFHW_LED_PULSE_MS);
        /* Roughly a second of visible off-time. A busy wait on purpose: this
         * is the "flash me again" state, and it must never end up as a lit
         * LED sitting there cooking the panel. */
        for (i = 0; i < 2000; i++)
            delay(1000);
    }
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
    /* Keep both XRAM halves across Sleep, or the tag loses its whole state on the
     * first sleep. Only the low nibble is kept: PCON.SWRESET reads back 1 after a
     * software reset, and writing that bit back re-arms the reset (that mistake
     * boot-looped the tag; never write PCON from the poll path). */
    PCON = (uint8_t)((PCON & 0x0C) | 0x0C);
    OSCFORCERUN |= 0x08;            /* force the 32 kHz LPX crystal (wake timer) */
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
#if SHELF_WAKE_LPXOSC
    /* 32.768 kHz / 64 = 512 Hz. Prescaler 6 measured ~1024 Hz on hardware
     * (60 counted seconds in 30 real ones), i.e. one divider step lower, which
     * halved every interval and timeout; 7 is the step that matches
     * SHELFHW_TICKS_PER_S. */
    wtimer0_setclksrc(CLKSRC_LPXOSC, 7);
#else
    wtimer0_setclksrc(CLKSRC_LPOSC, 0x01); /* internal RC at 640 Hz */
#endif
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

void shelfhw_poll_awake(void)
{
    wtimer_runcallbacks();
}

void host_rx_init(void)
{
    DIRB &= (uint8_t)~0x20;         /* PB5 input ... */
    PORTB |= 0x20;                  /* ... with pull-up, UART0 RX is enabled by uart0_init() */
}

int16_t host_rx_getc(void)
{
    uint8_t c;

    if (!(U0STATUS & 0x01))
        return -1;
    c = U0SHREG;
    U0CTRL |= 0x04;                 /* re-arm the RX flag, like iocore */
    return c;
}

/* ── radio power ──────────────────────────────────────────────────────────
 *
 * Between polls nothing has to be heard: the hub only ever answers a POLL, and
 * an image or firmware transfer cannot start until one has arrived. So the
 * transceiver goes to its deep-sleep mode for the gap, which is worth more than
 * everything else on the board together (a listening AX5043 is ~10 mA, the rest
 * of the tag is microamps).
 *
 * If SHELF_XTAL_OFF is set the 26 MHz crystal is released too: it is shared with
 * the transceiver and only forced on for radio work. Waking re-forces it and
 * gives it a few milliseconds to settle before the radio is asked to receive.
 */
uint16_t shelfhw_measure_vdd(void) __reentrant
{
    uint16_t vdd;

    /* Never write PCON here. This runs on every poll, and PCON.SWRESET (bit 4)
     * reads back 1 after a software reset, so writing the register back re-arms
     * the reset that just happened: the tag rebooted on the first poll after every
     * OTA and looked exactly like a boot loop, while a hardware reset was fine. */

    ADCCH0CONFIG = 0xD9;        /* all four channels sample VDD */
    ADCCH1CONFIG = 0xD9;
    ADCCH2CONFIG = 0xD9;
    ADCCH3CONFIG = 0xD9;
    ADCCLKSRC = 0x30;           /* start one conversion sweep */
    ADCCONV = 0x01;
    while (ADCCLKSRC & 0x80)    /* wait for it to finish */
        ;
    ADCCLKSRC = 0x07;
    vdd = (ADCCH0VAL >> 2) + (ADCCH1VAL >> 2) + (ADCCH2VAL >> 2) + (ADCCH3VAL >> 2);
    /* average -> volts * 256 */
    vdd >>= 5;
    vdd += vdd >> 2;
    vdd -= 9 << 7;
    return vdd;
}

void shelfhw_radio_sleep(void)
{
#if SHELF_RADIO_DEEPSLEEP
    /* The AX5043's own deep sleep: the 26 MHz XTAL stops, which is the ~1 mA
     * saving. The MCU runs from the internal FRC (CLKCON = 0 = FRCOSC), so it
     * keeps executing; the engine wakes the transceiver with the 0xAB wake
     * protocol from axradio_set_mode(ASYNC_RECEIVE) -- see shelfhw_radio_wake(). */
    (void)axradio_set_mode(AXRADIO_MODE_DEEPSLEEP);
#else
    /* AXRADIO_MODE_OFF = ax5043_off(): receiver, synth and baseband down, XTAL
     * kept running (PWRSTATE_XTAL_ON + POWERDOWN). Reliable, but pays ~1 mA. */
    (void)axradio_set_mode(AXRADIO_MODE_OFF);
#endif
#if SHELF_XTAL_OFF
    OSCFORCERUN &= (uint8_t)~0x04;  /* stop forcing the 26 MHz crystal */
#endif
}

void shelfhw_radio_wake(void)
{
#if SHELF_XTAL_OFF
    uint8_t n = 20;

    OSCFORCERUN |= 0x04;            /* crystal on ... */
    while (n--)                     /* ... and let it settle (~2 ms) */
        delay(100);
#endif
    (void)axradio_set_mode(AXRADIO_MODE_ASYNC_RECEIVE);
}

void shelfhw_poll(void)
{
    wtimer_runcallbacks();
    EA = 0;
    IE_1 = 1;                       /* wake-up timer (vector 1) ends the idle; no ISR runs, EA is off */
#if SHELF_MCU_SLEEP
    /* Sleep is 85 uA -> ~1.5 uA. CANSLEEPCONT makes libmf save SP + a signature so
     * the startup returns here instead of restarting at 0x0000; CANSLEEP is the
     * plain restarting sleep as a fallback, and CANSTANDBY is the last resort
     * when wtimer_cansleep() says a wake-up is too close. */
    wtimer_idle(WTFLAG_CANSLEEPCONT | WTFLAG_CANSLEEP | WTFLAG_CANSTANDBY);
#else
    wtimer_idle(WTFLAG_CANSTANDBY);
#endif
    IE_1 = 0;
    EA = 1;
}
