/**
 * @file shelfhw.h
 * @brief Board bring-up shared by the Hub and Vusion firmware
 *
 * One call (shelfhw_init) puts the AX8052F143 into the state the radio engine
 * and the wake-up timers expect, without disturbing the other chips on the
 * tag: the SPI chip selects are parked high, the LEDs are driven off and the
 * UART0 TX debug log is started.
 *
 * Pin ownership (see Documentation/signal-list.md):
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

/* Every LED indication is a short, self-terminating flash - never a level. The
 * LEDs sit directly behind the e-paper glass, so a lit one warms the panel and
 * that shows up as a blob on the image. Keep every pulse at half a second or
 * less; these two are the only durations the firmwares use. */
#define SHELFHW_LED_PULSE_MS        50u     /* routine event (announce, start) */
#define SHELFHW_LED_BOOT_PULSE_MS  250u     /* one-off "I am up" flash        */

/* Clocks, wake-up timers, pins, UART log, interrupts. Call once from main(). */
void shelfhw_init(void);

/* One turn of the main loop: runs the due wtimer callbacks (this is where the
 * radio engine delivers its events), then sleeps until the next interrupt. */
void shelfhw_poll(void);

/* Same as shelfhw_poll() but never enters standby, so the caller can poll
 * host_rx_getc() between calls. For the always-powered hub only. */
void shelfhw_poll_awake(void);

/* Put the radio (and, by default, the 26 MHz crystal it shares with the MCU)
 * into its lowest-power state for the gap between polls; wake it again before
 * talking. Both are idempotent. Build with -DSHELF_XTAL_OFF=0 to keep the
 * crystal running if a radio mode change turns out to need it. */
#ifndef SHELF_XTAL_OFF
#define SHELF_XTAL_OFF 0
#endif
void shelfhw_radio_sleep(void);
void shelfhw_radio_wake(void);

/* Host command input on UART0 RX (PB5). Hub only: on the tag PB5 is the EPD
 * reset line. Polled, there is no interrupt and no buffer beyond the UART's own
 * holding register - the host protocol is line based with a checksum. */
void host_rx_init(void);
int16_t host_rx_getc(void);     /* byte 0..255, or -1 if none waiting */

/* Drive an LED level directly. Only for exceptional use - every indication must
 * go through shelfhw_led_pulse(), because a level that is not cleared within a
 * fraction of a second is what heats the panel behind the LEDs. */
void shelfhw_led(uint8_t led, uint8_t on);

/* Light led for ms, then switch it off again. Blocking on purpose: it is the
 * only way to guarantee an LED is never left on. ms = 0 is treated as 1.
 * Use this for every indication - a plain shelfhw_led(led, 1) that is not
 * followed by an immediate off bakes the panel behind it. */
void shelfhw_led_pulse(uint8_t led, uint16_t ms);

/* Unrecoverable error: repeat a short pulse on led and never return. Used
 * instead of latching an LED on, for the same heat reason. */
void shelfhw_fatal(uint8_t led);

/* 16-bit pseudo-random value for retry jitter and initial sequence numbers. */
uint16_t shelfhw_random(void);

/* Supply voltage in volts*256 (3.00 V -> 0x0300). The AXSEM bootloader's ADC
 * recipe, averaged over four channels that all sample VDD, so no pin is spent:
 * it is the battery the tag reports in every poll. */
uint16_t shelfhw_measure_vdd(void) __reentrant;

/* UART0 TX debug log. */
void log_putc(uint8_t c);
void log_puts(const char *s);
void log_hex8(uint8_t v);
void log_hex16(uint16_t v);
void log_dec(uint16_t v);
void log_sdec(int16_t v);
void log_nl(void);

#endif /* SHELFHW_H */
