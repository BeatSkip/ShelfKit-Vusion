# Bootloader — the AXSEM serial bootloader (V1.1)

The flash-resident serial bootloader: it speaks the AX8052 bootloader protocol on UART0 (38400 8N1)
so an application can be uploaded as Intel HEX without a debug adapter, and it jumps to the
application at reset when one is installed.

**This is a 1-to-1 conversion** of Axsem's `ax8052_serialbootloader_v1.1` reference project (the
Code::Blocks + SDCC one parked in the repo-root `bootloader/` folder) into the SDCC-MDF workflow the
rest of this repository uses. The behaviour, the protocol, the strings and the layout are unchanged —
no functionality was added, removed or "improved".

## What it does

```
reset ─► 0x0000: ljmp 0xE438 ─► startup ─► bootloader()
                                            │
   SW5 not pressed and a valid app vector ──┴─► jump to the app at the vector in 0xE3FE
   otherwise: UART0 command loop at 38400 8N1
```

| Command | Effect |
|---|---|
| `?` | print the banner again (`AX8052 Bootloader V1.1 Checksum 0x…`) |
| `K` | erase the application area, then re-install the jump vector and verify it |
| `Z` | check that the application area is erased |
| `R` | run the application (refuses with `ERR-no Application` if the vector is `0xFFFF`) |
| `:` … | parse one Intel HEX record and program it (`ERR-…` lines on any failure) |
| `V` | measure and print VDD |

The banner's checksum is a CRC-16 over the bootloader's own flash pages, so it changes whenever this
image changes.

## Memory layout — the part that matters

The reference project's placement is reproduced with two project flags in `sdcc-project.json`:

```json
"flags": ["--code-size", "65536", "-Wl-bVECTOR=0x0000", "-Wl-bHOME=0xd800"]
```

| Symbol | Address | Why |
|---|---|---|
| `__interrupt_vect` | `0x0000` | the reset vector, `ljmp __sdcc_gsinit_startup` — three bytes of the VECTOR area |
| `__sdcc_gsinit_startup` | `0x0D838` | high byte **0xD8** is what the erase loop and the banner CRC calculate from |
| `_bootloader` | `0x0E204` | entered from the startup, because `crtstart.asm` ends with `ljmp _bootloader` (there is no `main`) |
| `_jmp_vector` | `0x0D7FE` | the application's entry address (low byte first), in the two bytes just below the bootloader; written at run time, never baked into the image |
| code end | `0x0F876` | 902 bytes short of the top page; the CRC covers `0xD800 … 0xFBFF` (9 KiB) |

Verified after the conversion with the real toolchain: `--code-size 65536` wins over the board's
59389-byte app limit (the last `-C` wins), the image is 205 hex records from `0x0000` to `0xFB92`,
`_jmp_vector` is *absent* from the image (so the slot stays `0xFF` until an app is flashed), and the
first record is `:0300000002E438…` — the reset jump to the startup. 428 B of XRAM, and 902 B free in the region.

## Sources

| File | Contents |
|---|---|
| `src/main.c` | the reference `main.c`, unchanged: command loop, Intel HEX parser, flash page erase/write, VDD measurement, `_sdcc_external_startup` pin setup |
| `src/crtstart.asm` | the reference startup, unchanged: declares the `VECTOR`/`HOME`/`UART0S0…`/`WTCANSLP…`/`WTSTDBY…` areas libmf expects, sets the stack, calls `_sdcc_external_startup`, then `ljmp _bootloader` |
| `include/` | project-local headers (empty, on the include path) |

Both are compiled exactly as they were: the `.c` with `sdcc`, the `.asm` with `sdas8051 -plosgffw`
(the extension routes `.asm` there itself, so no special configuration is needed).

## What changed from the Code::Blocks project

| Reference (`.cbp`) | Here |
|---|---|
| `-mmcs51 --model-small --verbose` | `board` (`axsem-8052f143`) supplies the CPU, model, IRAM/XRAM sizes |
| `--xram-size 8192 --iram-size 256 --code-size 65536` | the board supplies the first two; `--code-size 65536` moved to `build.flags` |
| `-Wl-bVECTOR=0x0000 -Wl-bHOME=0xe400` | the same, in `build.flags` |
| `-llibmf` | `libraries: ["../Shared/lib"]` — the linker pulls only what is referenced |
| include paths from the Code::Blocks install | `include` + `../Shared/sdk/libmf/include` |
| output `bin/Release/bootloader.hex` | `build/bootloader.hex` (`build.output_name`) |
| manual compiler/assembler/linker steps | *SDCC: Build* — **Ctrl+Shift+B** |

The `.sdcc/` board cache that came with the skeleton was removed; the board definition is read from
`../Shared/boards` like every other target.

## Building and flashing

Open **this folder** in VS Code, **Ctrl+Shift+B**, output in `build/`. Or by hand from here:

```powershell
$flags = @('-mmcs51','--model-small','--iram-size','256','--xram-size','8192','--code-size','65536',
           '-Wl-bVECTOR=0x0000','-Wl-bHOME=0xe400','-Iinclude','-I../Shared/sdk/libmf/include')
& 'C:\Program Files\SDCC\bin\sdcc.exe' @flags -c src/main.c -o build/main.rel
& 'C:\Program Files\SDCC\bin\sdas8051.exe' -plosgffw build/crtstart.rel src/crtstart.asm
& 'C:\Program Files\SDCC\bin\sdcc.exe' @flags build/crtstart.rel build/main.rel `
    ../Shared/lib/libmf.lib -o build/bootloader.hex
```

*SDCC: Flash* runs [`../Tooling/axsem-flasher.py`](../Tooling/axsem-flasher.py), which talks to
the **mask-ROM** bootloader selected by the BOOT pin (DTR on the adapter) — that is the only thing that
can write the `0xE400` region, since a flash-resident bootloader cannot erase itself while it runs.
Once this image is in place, applications can be uploaded over UART0 without touching the BOOT pin.

## Wireless update (OTA)

This is the bootloader's other job now, and it is deliberately as small as it can
be: bit-banged SPI, one 32-byte buffer, no radio code. If the tag's SPI flash holds
the magic sequence the application stored there, the bootloader verifies the image
CRC, programs it over the application, clears the magic and starts it. The full
design — flash layout, header, CRC, ordering rules and why it is safe — is in
[Documentation/ota-update.md](../../Documentation/ota-update.md).

Serial flashing is untouched and still works when an OTA image is broken: a bad CRC
clears the magic and drops into the command loop instead of destroying anything.

## Deliberately not done yet

- **The application region.** The erase loop steps 1 KB pages from `0x0400` up to the
  bootloader's page, so everything below the bootloader (including the page at `0x0400`) goes.
- **How an update is initiated over serial.** The reference needs SW5 (`PINB & 0x08`) held low at
  reset; the wireless path needs no button, but there is no software "enter the bootloader" command.
- **Whole-image verification on the serial path.** OTA images get a CRC; an Intel HEX file sent over
  the wire is still only checked record by record.
- **`run_application()` and the jump vector** need a hardware check: it reads the vector with `MOVX`
  while the vector is stored in flash (see the OTA document's open questions).
