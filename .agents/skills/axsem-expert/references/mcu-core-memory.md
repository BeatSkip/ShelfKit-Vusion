# AX8052 core, memory map and flash

Sources: AND9349/D (AX8052 Programming Manual), AX8052F143 datasheet, SDK headers. Grep
`vendor/AX8052-programming-manual-AND9349.txt` for bit tables.

## Core

- **8052 instruction set**, same opcodes as the original MCS-51. It is pipelined: roughly **one clock per instruction byte**, so up to 20 MIPS at 20 MHz. Cycle counts from classic 8051 books (12 clocks per machine cycle) do **not** apply. Software delay loops must be calibrated against this core and the selected clock.
- **Dual data pointers**: `DPTR0` (DPL/DPH) and `DPTR1` (DPL1/DPH1), selected by `DPS` bit 0. SDCC's library memcpy and friends may use them. If you touch DPS in assembly, save and restore it.
- 4 register banks R0-R7 at IRAM 0x00-0x1F, bit-addressable RAM at 0x20-0x2F, `PSW`, `ACC`, `B`, `SP`. Standard.
- Interrupt latency is at least 5 cycles. Two priority levels. See interrupts-gpio-peripherals.md.

## Address spaces

| Space | Range | Contents | C qualifier |
|---|---|---|---|
| IRAM direct | 0x00-0x7F | registers, bits, `__data` variables | `__data` |
| IRAM indirect | 0x80-0xFF | `__idata`, **the stack** | `__idata` |
| SFR | 0x80-0xFF (direct only) | core and peripheral SFRs | `__sfr`, via the `SFR()` macros in ax8052.h |
| CODE | 0x0000-0xFFFF | 64 KB flash | `__code` |
| XDATA | 0x0000-0x1FFF | **8 KB XRAM**, two 4 KB halves (kept or not in Sleep per `PCON` XRAMKEEP bits 3:2) | `__xdata` |
| XDATA | 0x3F80-0x3FFF | SFRs mirrored in X space (the `X`-prefixed names, e.g. `XPCON`) | |
| XDATA | 0x4000-0x4FFF | **AX5043 registers, blocking access** | `AX5043_*` SFRX names |
| XDATA | 0x5000-0x5FFF | AX5043 registers, non-blocking write aliases (`*NB`) | |
| XDATA | 0x7000-0x7FFF | MCU extended registers (XREG): GPIO alt functions, ADC values, oscillator config, radio interface... | SFRX names |
| XDATA | upper area | flash mirrored into X space (readable with `movx`) | |

- `CODECONFIG` (SFR 0x97): bit 7 CACHE, bits 6:5 prefetch, bit 4 INVLD, bit 3 **XRAML8** (maps XRAM into code space 0x0000-0x1FFF, for running code from RAM). Leave it at its defaults unless you really mean it.
- Access an XREG either through its SFRX name from the header (`GPIOENABLE = 1;`) or through a `__xdata` pointer. Each access is a `movx`, which is slower than a direct SFR.
- The full name/address list is in [register-index.md](register-index.md).

## Memory budget (this project)

`Shared/boards/axsem-8051.json`: `--model-small`, `--iram-size 256`, `--xram-size 8192`, `--code-size 59389`.

- **IRAM**: full. SDCC places `__data` variables, overlay segments and bit variables there, and the **stack grows up from the end of them to 0xFF**. The tag has about 137-154 B of stack left. Every nested call costs 2 B, and every ISR costs its pushes (up to ~13 B for a bank-0 ISR that calls a function). Running out corrupts silently.
- libmf's `enter_sleep_cont()` stores its resume marker and SP at the top of IRAM (0xFD-0xFF). With a full IRAM the stack can collide with it.
- **XRAM**: about 7 KB used on the tag. A full BWR frame (2 × 5,624 B) does not fit, so the panel image is streamed.
- **CODE**: the application must stay below **0xD800** (bootloader) minus the jump vector at 0xD7FE. The OTA window is about 43 KB. Current tag image is about 41 KB. `build-all.py` prints sizes.
- To see the allocation: the `build/*.mem` file shows the IRAM map and stack start; `.map` shows the segments; `.rst`/`.lst` show the generated assembly.

## Startup sequence

1. Reset → 0x0000. On the tags this is the **bootloader's** `ljmp 0xD838` (see board-vusion.md). The bootloader runs its own startup and then jumps to the application entry stored at 0xD7FE.
2. Application: SDCC `crtstart` → `_sdcc_external_startup()` (if defined; runs **before** globals are initialised; return nonzero to skip the init) → static init → `main()`.
3. libmf wants clocks and wake-up timers configured very early (`wtimer0_setclksrc` etc. "from `_sdcc_external_startup`"). This project does it in `shelfhw_init()` instead.
4. Recommended init order (vendor templates):
   1. Set `DIRx` / `PORTx` / `ANALOGA` to a safe state.
   2. `flash_apply_calibration()`.
   3. Radio: `ax5043_reset()` on cold start, `ax5043_comminit()` on a warm start or wake.
   4. `GPIOENABLE = 1`.
   5. Set up clocks, wtimers and the UART.
   6. Enable interrupts, then `EA = 1`.
5. Distinguish the start cause with `PCON`: bit 7 BROWNOUT, bit 6 WAKEUP (woken from sleep), bit 5 WDTRESET, bit 4 SWRESET. These are read-only flags. **Never write PCON back** with bit 4 set. `SILICONREV` gives 0x8E (V1), 0x8F (V1C), 0x90 (V2). These tags are V2.

## Flash (program memory)

- 64 KB in **64 pages of 1 KB**. Writes are **16-bit words**: write the even address, then the odd one. A page erase sets it to 0xFF.
- The **last page holds factory calibration**. Call `flash_apply_calibration()` early at every start, and never erase that page.
- Unlock: write `0x41` then `0x78` to `NVKEY` within 16 cycles (libmf `flash_unlock()`; `flash_lock()` afterwards).
- Commands go through `NVSTATUS`/`NVADDR`/`NVDATA`:
  - 0x10: bulk erase
  - 0x20: page erase
  - 0x30: word write
  - 0x34: protect bits

  Protect bits can only be cleared by a bulk erase, and only the debugger or ROM bootloader can recover from that.
- libmf: `flash_unlock`, `flash_lock`, `flash_wait(timeout)`, `flash_pageerase(pgaddr)`, `flash_write(waddr, wdata)`, `flash_read(raddr)`. Each returns <0 on error.
- The CPU stalls while the flash is busy. Don't erase pages from timing-critical code, or while the radio needs FIFO service mid-packet.
- The application cannot rewrite the bootloader region safely. OTA is done by the bootloader itself from the SPI flash (see board-vusion.md and `Documentation/ota-update.md`).

## Debug interface

- DebugLink uses dedicated pins `DBG_EN`, plus PB6/PB7 as DBG_DATA/DBG_CLK when debug is enabled. On this board PB6/PB7 are the green and blue LEDs.
- `enter_sleep()` / `enter_deepsleep()` behave differently with the debugger attached. The libmf versions handle it.
- `DebugLink` has its own interrupt (21) and buffer. libmf's `dbglink_*` adds a sleep veto while TX data is pending.
