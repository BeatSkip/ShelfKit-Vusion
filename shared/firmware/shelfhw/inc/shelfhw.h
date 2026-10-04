/**
 * @file shelfhw.h
 * @brief Board bring-up shared by the Hub and Vusion firmware
 *
 * One call (shelfhw_init) puts the AX8052F143 into the state the radio engine
 * and the wake-up timers expect, without disturbing the other chips on the
 * tag: the SPI chip selects are parked high, the LEDs are driven off and the
 * UART0 TX debug log is started.
 *
 * Pin ownership (see shared/documentation/signal-list.md):
 *   PB4            UART0 TX debug log (38400 8N1)
 *   PB0/6/7, PC4   LEDs
 *   PA1/PB1/PC0    chip selects of EPD / NFC / flash, parked high
 *   PB2/PB3/PB5    never touched here (EPD BUSY, boot/NFC FD, EPD RST/UART RX)
 */

#ifndef SHELFHW_H
#define SHELFHW_H

#include <ax8052f143.h>
#include <libmftypes.h>

/* wtimer0 runs from the LPOSC at 640 Hz; this is the engine's time base and
 * the one shelflink uses for its timeouts. */
#define SHELFHW_TICKS_PER_S     640u
#define SHELFHW_MS_TO_TICKS(ms) ((uint16_t)(((uint32_t)(ms) * 64u + 50u) / 100u))

/* LED polarity. 1 = driving the pin high lights the LED. The boot demo
 * assumes this; if the LEDs turn out to be inverted, define it as 0 for the
 * whole project (the pin map in the README says "active low"). */
#ifndef SHELFHW_LED_ACTIVE_HIGH
#define SHELFHW_LED_ACTIVE_HIGH 1
#endif

#define SHELFHW_LED_WHITE   0
#define SHELFHW_LED_BLUE    1
#define SHELFHW_LED_GREEN   2
#define SHELFHW_LED_RED     3

/* Clocks, wake-up timers, pins, UART log, interrupts. Call once from main(). */
void shelfhw_init(void);

/* One turn of the main loop: runs the due wtimer callbacks (this is where the
 * radio engine delivers its events), then sleeps until the next interrupt. */
void shelfhw_poll(void);

void shelfhw_led(uint8_t led, uint8_t on);
void shelfhw_led_toggle(uint8_t led);

/* 16-bit pseudo-random value for retry jitter and initial sequence numbers. */
uint16_t shelfhw_random(void);

/* UART0 TX debug log. */
void log_putc(uint8_t c);
void log_puts(const char *s);
void log_hex8(uint8_t v);
void log_hex16(uint16_t v);
void log_dec(uint16_t v);
void log_sdec(int16_t v);
void log_nl(void);

#endif /* SHELFHW_H */
