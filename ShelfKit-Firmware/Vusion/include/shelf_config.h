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

/* 1 = park the radio in the AX5043's own deep sleep (26 MHz crystal off, the
 * ~260 uA saving between polls). 0 = PWRSTATE_XTAL_ON + POWERDOWN.
 *
 * The first attempt failed because the wake waited *before* changing mode, so the
 * first frame after a sleep went out before the PLL had locked and the hub heard
 * nothing. shelfhw_radio_wake() now changes mode first and settles afterwards.
 * Set to 0 if a tag stops making its polls. */
#define SHELF_RADIO_DEEPSLEEP 1

/* 1 = let the MCU enter Sleep (~2 uA) instead of Standby (85 uA) between
 * wake-ups, using libmf's enter_sleep_cont() so execution resumes rather than
 * restarting at 0x0000.
 *
 * Set to 0 if the tag ever boot-loops: sleep takes the libmf path that ends in
 * `ljmp 0xE047` and relies on the startup's resume signature, which has not yet
 * been proven on this board. */
#define SHELF_MCU_SLEEP     1
/* 0 = leave the 26 MHz crystal force alone and let the radio engine manage it.
 * With RADIO_DEEPSLEEP off there is nothing to stop, and toggling the force was
 * part of the deep-sleep wake path that left the transmitter off-frequency. */
#define SHELF_XTAL_OFF      0

/* Seconds between polls. 60 s is the practical ceiling: the wake-up timer counts
 * SHELFHW_TICKS_PER_S (640) per second in 16 bits, so anything above ~102 s
 * overflows. The 1 % duty cycle of the 868.3 MHz sub-band is not a concern at
 * this rate (a poll is a few milliseconds of air). */
#define SHELF_POLL_INTERVAL_S   120

/* How long the tag listens after each poll, in seconds. Everything the hub sends
 * (images, firmware, a new identity) follows a POLL, so this window is the only
 * time the tag can be reached. Longer = easier pushes, shorter = less RX time. */
#define SHELF_LISTEN_WINDOW_S   2
/* How long to keep listening after a reply that did *not* say data is coming.
 * A push needs ~200 ms to render and start, so 700 ms is 3x margin; the receiver
 * is 9.5 mA and this window is almost the whole power budget, so it is sized to
 * the job rather than to a bad case. A miss costs one poll, not the push. */
#define SHELF_LISTEN_GRACE_MS   250
/* How long to keep listening after a reply that *did* arrive and said "nothing
 * queued": 0 parks the radio at once, the biggest battery saving there is.
 * It needs the host to pre-arm every push (hub `Q<id>`, which makes the reply say
 * "data follows"); ShelfKit-Server does that when a command is queued, when the hub
 * resets and after the hub display redraws. A push started only after the reply
 * (the old behaviour, or hubhost.py's `send` without a pre-arm) is missed; set this
 * to 250 to catch those again, at ~2.5x the poll cost. */
#define SHELF_LISTEN_QUIET_MS   0

/* 1 = a falling edge on PB3 (the NFC chip's field-detect output, shared with the
 * bootloader's BOOT strap) wakes the tag, flashes the blue LED and makes it poll: hold a
 * phone against the tag and it checks in within a second instead of waiting out the interval.
 *
 * Measured with the Shakedown firmware (Documentation/nfc-field-detect.md): idle HIGH, active
 * LOW, quiet with no phone, and a phone gives bursts of 1-30 ms low pulses for as long as it
 * is there - so the first edge is the event and SHELF_NFC_BURST_MAX limits the rest.
 * The chip's FD output mode lives in its EEPROM (0x38C fdp_conf = 11, 0x391 bit 7 = 0);
 * nfc_cfg_fd() checks it at boot and rewrites it only if it is wrong.
 * PB3 is also the bootloader's BOOT strap: with a phone in the field at reset the tag
 * enters the bootloader, and a serial adapter's DTR on PB3 fights the chip, so test with
 * the BOOT wire disconnected. */
#define SHELF_NFC_POLL          1
/* Only meaningful with SHELF_NFC_POLL. 1 = leave the switched rail (PA5 / U4) on, so the NFC
 * chip is powered and its open-drain output is actually driven. It costs the standby current
 * of the panel supply and the flash. 0 = the rail is driven off between uses (PA5 high, PA2
 * parked low): tried on hardware, PB3 then floats and re-triggers every cycle (a poll every
 * 1.8 s), so the storm guard suspends the feature - i.e. NFC does not work. Keep 1 until
 * there is a pull-up on PB3 or the chip is powered from an always-on rail. */
#define SHELF_NFC_RAIL_HOLD     1
/* 1 = read the NFC chip's UID and dump its configuration area at boot. Read-only. */
#define SHELF_NFC_PROBE         0

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

/* ── burst polling when the hub has data for us ───────────────────────────
 * A reply that says "data follows" means the hub is busy with this tag (a queue of
 * images, a firmware push), so the next check-in comes quickly. Once the hub goes
 * quiet the rate drops well below the old fixed 120 s: a short cool-down, then idle. */
#define SHELF_POLL_ACTIVE_S       30     /* while replies keep saying "data follows" */
#define SHELF_ACTIVE_MAX_POLLS    20     /* safety: ~10 min of burst, then cool down
                                          * (a stuck data flag must not drain the cell) */
#define SHELF_POLL_COOLDOWN_S     180    /* first quiet polls after data ... */
#define SHELF_COOLDOWN_POLLS      3      /* ... this many of them ... */
#define SHELF_POLL_IDLE_S         300    /* ... then the idle rate */

/* The tag is not wired to a serial adapter in service, so it prints nothing: SHELF_LOG_MUTE 1
 * (the default) starts the UART as usual and drops every character at once. That saves the
 * CPU time spent waiting for characters to leave (~87 us each at 115200, a few hundred per poll
 * cycle - an estimated ~0.6 uA of ~50). SHELF_LOG_UART 0 is NOT usable: with no UART start-up the
 * tag boots and polls, but breaks on the first NFC tap (tested on hardware, cause not found -
 * probably something that depends on the UART/timer 0 set-up or the memory layout it shifts).
 * To read the tag's log on a serial port while developing, build with
 *   build-all.py --define SHELF_LOG_MUTE=0 --out Release/debug-log */
#ifndef SHELF_LOG_UART
#define SHELF_LOG_UART          1
#endif
#ifndef SHELF_LOG_MUTE
#define SHELF_LOG_MUTE          0
#endif

/* Print the link statistics every this many polls */
#define SHELF_STATS_EVERY       2   /* one power summary every 2 polls */

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

/* 1 = switch the panel supply (U4 on PA5) on at boot and leave it on. It has NOTHING to do
 * with the radio: measured on hardware, PA5 only powers the e-paper panel, and PA2 (U5) is
 * never switched on (it is parked low at boot whatever this says). Leave it 0; the image
 * path powers the panel itself around each image. See Documentation/pa2-pa5-findings.md. */
#define SHELF_POWER_LINES   0

#endif /* SHELF_CONFIG_H */
