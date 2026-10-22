#ifndef SHELF_CONFIG_H
#define SHELF_CONFIG_H

/* Radio identity. The on-air address is {node id low, node id high, net id}; the
 * net id is the fleet-wide constant below, and the node id is NOT built in: it is
 * read from the tag's SPI flash (src/shelf_id.c), which is what lets one firmware
 * image fit the whole fleet. A brand new tag generates a random id at first boot
 * and keeps it; the server can assign a proper one at any time with
 * Tooling/set-id.py, and the id survives firmware updates. */
#define SHELF_NET_ID        0x5A

/* 1 = put the transceiver into its deep-sleep mode between polls (and, with
 * SHELF_XTAL_OFF, stop forcing the 26 MHz crystal).
 *
 * OFF by default: on hardware a tag that entered the radio's deep sleep polled
 * once and then went silent, which points at the SYSCLK / pin-mux reconfiguration
 * `radio_enter_deepsleep()` does - the AX8052F143 takes its clock from that
 * domain. Enable one piece at a time when you can watch the tag:
 *   1. SHELF_RADIO_SLEEP 1, SHELF_XTAL_OFF 0   (radio only)
 *   2. then SHELF_XTAL_OFF 1 as well            (radio + crystal)
 * The tag logs "sleep" when it parks the radio and "wake" when it brings it back,
 * so a silent log after "sleep" means the chip itself stopped. */
#define SHELF_RADIO_SLEEP   1

/* 1 = park the radio in the AX5043's own deep sleep (XTAL stopped) instead of
 * PWRSTATE_XTAL_ON+POWERDOWN. That is the ~1 mA -> ~50 uA step, and the mode
 * that once left a tag polling once and dying; the wake path is
 * ax5043_wakeup_deepsleep() in the engine. Set 0 to fall back to the
 * crystal-on POWERDOWN that has been reliable. */
#define SHELF_RADIO_DEEPSLEEP 1

/* 1 = let the MCU enter Sleep (0.5-1.5 uA) instead of Standby (85 uA) between
 * wake-ups, using libmf's enter_sleep_cont() so execution resumes rather than
 * restarting at 0x0000.
 *
 * OFF: on hardware, after an OTA's PCON.SWRESET the tag restarted instead of
 * resuming - a boot loop every ~0.9 s until it was reset by hand - while a
 * hardware reset resumed normally. The MCU sleep is the only difference between
 * those two, so it stays off until the startup's resume path is understood. */
#define SHELF_MCU_SLEEP     0
#define SHELF_XTAL_OFF      1

/* Seconds between polls. 60 s is the practical ceiling: the wake-up timer counts
 * SHELFHW_TICKS_PER_S (640) per second in 16 bits, so anything above ~102 s
 * overflows. The 1 % duty cycle of the 868.3 MHz sub-band is not a concern at
 * this rate (a poll is a few milliseconds of air). */
#define SHELF_POLL_INTERVAL_S   60

/* How long the tag listens after each poll, in seconds. Everything the hub sends
 * (images, firmware, a new identity) follows a POLL, so this window is the only
 * time the tag can be reached. Longer = easier pushes, shorter = less RX time. */
#define SHELF_LISTEN_WINDOW_S   2
/* How long to keep listening after a reply that did *not* say data is coming:
 * long enough for a late frame, short enough not to hold the receiver open. */
#define SHELF_LISTEN_GRACE_MS   500

/* ── adaptive check-in (openepaperlink-style backoff) ─────────────────────
 * The base interval above is only a starting point. It stretches when the link
 * is weak, and collapses to hourly/daily when there is no hub at all, because a
 * tag out of range must not spend its battery retrying. */
#define SHELF_POLL_MAX_S        600      /* weak link: at most 10 min between polls */
#define SHELF_POLL_ARM_MAX_S    100      /* one wake-up-timer arm (16 bits @ 640 Hz) */
#define SHELF_WEAK_RSSI_DBM     (-95)    /* the hub hearing us below this = weak */
#define SHELF_FAIL_TO_HOUR      14       /* consecutive misses before the hourly step */
#define SHELF_LOST_HOUR_S       3600UL   /* no hub: once an hour ... */
#define SHELF_LOST_DAY_S        7200UL   /* ... every two hours after a day ... */
#define SHELF_LOST_2DAY_S       86400UL  /* ... once a day from the day after */

/* Print the link statistics every this many polls */
#define SHELF_STATS_EVERY       10

/* 1 = power the SPI flash's switched rail (PA5, transistor U4, active low) before
 * every flash access and drop it again after. The rail is only brought up by the
 * panel power sequence, so without this the flash reads back all 0xFF at boot:
 * the identity looks blank (regenerated every reset) and the bootloader sees no
 * OTA header. Set 0 only if a board turns out to power the flash from VDD. */
#define SHELF_FLASH_POWER_ON   1

/* 1 = on the very first boot (no identity record yet) wipe every SPI flash sector
 * the firmware owns before generating the random id. That clears leftovers from a
 * used tag - most importantly a stale OTA marker, which would otherwise make the
 * bootloader overwrite this application on the next reset. Costs ~0.5 s once. */
#define SHELF_WIPE_FIRST_BOOT   1

/* 1 = drive the unidentified transistor lines PA2/PA5 on (see src/pwr.h) before the radio
 * starts. Left off by default; try it if the range turns out poor.
 * This is about the radio only: the e-paper supply is transistor U4 on PA5, and
 * src/img_rx.c drives it on itself around every image (independent of this switch). */
#define SHELF_POWER_LINES   0

#endif /* SHELF_CONFIG_H */
