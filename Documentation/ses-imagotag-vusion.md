# Vusion 2.6" tag — context

**Device:** SES-imagotag Vusion 2.6" BWR shelf label (UU340), battery powered.
**MCU:** Axsem AX8052F143 — 8051 core + AX5043 sub-GHz radio, 26 MHz. 256 B IRAM, 8 KB XRAM, 59,389 B code space, ~150 B of stack left.
**Panel:** Good Display GDEW026Z39 — 296×152 native, black/white/red, IL0373, SPI, OTP waveform. Driven rotated (152 wide × 296 tall) as two 5,624-byte planes.
**Also on board:** NFC (FM11NT081DS), SPI NOR flash.
**Toolchain:** SDCC 3.6.0 (`-mmcs51 --model-small`), VS Code + SDCC-MDF extension. Flashed over the AX8052 UART bootloader at 38400 8N1 (BOOT pin held by the adapter's DTR).
**Firmware:** polls a hub every 60 s on 868.3 MHz (network id 0x5A, hub node 0x0001) with reliable, retried frames, then sleeps for the rest of the minute (radio in `AXRADIO_MODE_OFF`, 3 s listening window after each poll); an image arrives in 28-byte chunks straight into the panel controller (no frame buffer in RAM), then a ~15 s full refresh and deep sleep.

**Gotchas:**
- PA5 (transistor U4) is the panel supply, **active low** — without it the panel accepts a frame and never refreshes.
- Panel reset shares PB5 with UART0 RX; enabling RX kills the reset line.
- Panel BUSY is **active low** on this board.
- LEDs PB0/PB7/PB6/PC4 (white/blue/green/red): pulse only, never hold on.
- Internal RAM is full — buffers go in `__xdata`.
- SPI flash (128 KiB class): sector 0 holds an OTA header, sector 1 the identity record, sector 2 is reserved, image from sector 3. The tag wipes 0–3..11 on first boot when no identity parses, so a used tag starts clean.


i have a custom bootloader that allows me to flash the firmware for this board over serial. i want to change the bootloader so i can also flash firmware over the air without any hardware interaction. i was thinking to add functionality to the regular firmware that runs on it to receive new firmware over the air, write it into the spi nor flash and then trigger a reboot into the bootloader. the bootloader checks if a new firmware package is staged in the spi nor flash and if so, flashes the main firmware. i would like to do it this way to keep the bootloader size minimal. is this a good way of working? or would you recommend a different scheme. i would like to also keep the current uart flashing capabilities intact