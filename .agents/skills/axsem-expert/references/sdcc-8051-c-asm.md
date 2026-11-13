# C and assembly for the 8051 with SDCC

Sources:

- SDCC user manual (`vendor/SDCC-user-manual.txt`): §3.5 named address spaces, §3.6 parameters and locals, §3.7 overlaying, §3.8 ISRs, §3.9 critical sections and semaphores, §3.10 register banks, §3.11 inline assembler, §4.1.5 assembler interfacing, §4.1.4 startup, plus the efficiency tips.
- General 8051 practice (Keil C51 primer and others).

**The project uses SDCC 3.6.0**, while the bundled manual is newer. Syntax like `__asm__("...")`, `__critical`, `__interrupt(n)` and `__using(n)` exists in 3.6. The C2x additions do not.

## The machine model in one paragraph

The 8051 is an 8-bit accumulator machine. Its registers are R0-R7 (4 banks), A, B, DPTR, PSW and SP. It has separate address spaces, and **the stack lives in 256 bytes of internal RAM** shared with every global and local variable in the small model. Pointers can be 1 byte (`__data` / `__idata`), 2 bytes (`__xdata` / `__code`) or 3 bytes (generic, with a tag byte). Arithmetic on 16- or 32-bit values is a chain of 8-bit ops, and `*`, `/`, `%` on them are library calls. The C language's int promotion therefore costs real code on every expression.

## Named address spaces (SDCC mcs51)

| Qualifier | Where | Access | Use |
|---|---|---|---|
| `__data` / `__near` | IRAM 0x00-0x7F | direct, fastest | small hot variables, loop counters (default in the small model) |
| `__idata` | IRAM 0x00-0xFF | indirect via R0/R1 | rarely; shares space with the stack |
| `__pdata` | one 256 B page of XRAM | `movx @Ri` | not used here |
| `__xdata` / `__far` | XRAM 0x0000-0xFFFF | `movx @dptr` | **all buffers, structs, arrays, wtimer descriptors** |
| `__code` | flash | `movc` | constant tables (`const __code uint8_t t[] = {...}`) |
| `__bit` | bit space 0x20-0x2F | `setb` / `clr` / `jb` | boolean flags (fast, atomic) |
| `__sfr` / `__sbit` / `__sfr16` / `__sfr32` | SFR space | direct | via the `SFR()` / `SBIT()` macros of ax8052.h |
| `__at(addr)` | absolute placement | | memory-mapped I/O. **No storage is reserved**, so overlaps are your problem |

- SDCC normally puts an initialised file-scope `const` in code space, but write `__code` explicitly: that guarantees it stays out of RAM and lets pointers to it be `__code` instead of generic. Confirm in the `.map` file.
- Initialised `__xdata` variables are copied from flash at startup (code size). `--no-xinit-opt` changes how.
- `volatile __xdata __at(0x....) uint8_t REG;` is the form for memory-mapped registers. The `SFRX()` macro does this.

## Pointers

- **Unqualified pointers are 3-byte generic pointers.** The tag byte is: 0x00 xdata, 0x40 idata, 0x60 pdata, 0x80 code. Every dereference calls `__gptrget` / `__gptrput`, which is slow and big.
- Declare the target space: `__xdata uint8_t *p` (2 B, `movx`), `__code const uint8_t *t` (2 B, `movc`), `__data uint8_t *q` (1 B). The pointer's own location is a second qualifier: `__xdata uint8_t * __data p` means "pointer stored in IRAM, pointing to XRAM".
- libmf APIs that take `__genericaddr` pointers accept anything. That convenience costs speed.
- Function pointers are 2 bytes (code addresses). **A function called through a pointer with two or more parameters must be `__reentrant`**: only the first parameter goes in registers, the rest would land in a static area the caller can't know.

## Parameters, locals, reentrancy, overlaying

- By default (non-reentrant), locals and parameters are **statically allocated** in `__data` (small model), effectively `static`. That makes functions **non-reentrant**: recursion breaks, and calling the same function from main and from an ISR corrupts its variables.
- `__reentrant` (or `--stack-auto`, `#pragma stackauto`) puts parameters and locals on the IRAM stack. The stack is tiny here, so use it **sparingly**, and only where required (ISR-shared helpers, multi-argument function pointers, the libmf callback typedefs).
- **Overlaying**: for non-reentrant **leaf** functions (they call nothing), SDCC overlays their locals and parameters in a shared segment to save IRAM. A function called from an ISR **must not be overlaid** with main-line functions, so put `#pragma nooverlay` before it (wrapped in `#pragma save` / `#pragma restore`) or make it `__reentrant`. Inline asm that calls C functions can fool the overlay analysis; use `nooverlay` there too.
- Functions that use 16/32-bit `*` `/` `%` are never overlaid. Those helpers are non-reentrant library routines unless `--int-long-reent` is used, so **don't do 16/32-bit multiply or divide in an ISR**.
- Calling convention:

  | Value | Registers |
  |---|---|
  | 1 byte | DPL |
  | 2 bytes | DPL (LSB), DPH |
  | 3 bytes (generic pointer) | DPL, DPH, B (tag) |
  | 4 bytes | DPL, DPH, B, ACC |

  The first non-bit, non-struct parameter is passed this way, and the return value too. Other parameters go to `_<func>_PARM_<n>` (non-reentrant) or on the stack (reentrant, pushed right to left; the callee uses `_bp`). The first 8 bit parameters go in bit space. The **caller saves** R0-R7 around calls (unless `callee_saves` / `__naked`).
- `#pragma callee_saves f1,f2`: the caller doesn't save registers around these functions, so they must preserve R0-R7 themselves. libmf declares this for `enter_*`, `wtimer_standby` and `radio_read*/write*`. **Anything replacing them must honour it.**

## Interrupt service routines

```c
void radio_isr(void) __interrupt(INT_RADIO);          /* prototype visible in main.c! */
void radio_isr(void) __interrupt(INT_RADIO) { ... }    /* optional: __using(1) */
```

- **The ISR prototype must be visible in the file containing `main()`**, or the vector isn't generated.
- Without `__using` (or with `__using(0)`): the ISR saves only the registers it uses. If it calls any function, it saves the **whole bank 0** (≈8 pushes + ACC, B, DPL, DPH, PSW). Keep ISRs leaf-only when possible.
- With `__using(n)`: the ISR switches to bank n and saves only ACC, B, DPTR and PSW. **Never share a bank between a high- and a low-priority ISR.** Calling functions from it costs a bank save. Banks 1-3 occupy IRAM 0x08-0x1F, which SDCC otherwise uses for data, so this costs IRAM.
- `#pragma exclude acc,b,dpl,dph` and `__naked` remove the prologue and epilogue: hand-written ISRs only.
- **Keep ISRs short.** Set a flag or queue a `wtimer_add_callback()` and do the work in the main loop. That is the libmf pattern.
- **Stack**: every ISR invocation pushes the return address (2 B) plus saved registers on top of whatever main is using. Worst case = deepest main call chain + every priority level's ISR. With ~140 B free that is not a lot.

## Shared data and atomicity

- Variables written in an ISR and read elsewhere (or the reverse) must be **`volatile`**.
- **Non-atomic accesses**: any 16/32-bit variable; `flags |= 0x80` on an `__xdata` byte (read, modify, write via `movx`); `counter += 8` even in `__data`. Protect them:

```c
__critical { snapshot = shared16; }        /* saves EA, clears it, restores it */
/* or mask just that source: */
IE_4 = 0; snapshot = shared16; IE_4 = 1;
```

- `__critical` functions or blocks save the EA state and restore it, and they nest (1 byte of stack each). Keep critical sections short (latency, jitter).
- `__bit` variables in bit space give atomic `setb` / `clr`. The pattern `if (lockbit) { lockbit = 0; ... lockbit = 1; }` compiles to the atomic `jbc` (test-and-clear) instruction, which is a semaphore without disabling interrupts.
- Reading a multi-byte **hardware** counter: use the latch registers the peripheral provides (e.g. reading `WTCNTA0` latches the rest), or read twice until stable.

## Writing efficient C for the 8051 (SDCC)

1. **Use `uint8_t` wherever the range allows**; `int` is 16-bit and costs double. Prefer **unsigned**: signed compares, shifts and divides need extra code.
2. **Defeat int promotion** with casts: `if (head != (uint8_t)(tail - 1))`. Without the cast, the comparison is done in 16 bits.
3. Loop counters as local `uint8_t`. Count **down to zero** (`do { } while (--i);` compiles to `djnz`).
4. Avoid `*`, `/`, `%` on 16/32-bit values in hot paths and ISRs. Use shifts and masks for powers of two. 8×8 multiply (`mul ab`) and 8/8 divide (`div ab`) are single instructions.
5. Avoid floating point entirely (huge library, slow).
6. Avoid generic pointers, and avoid passing structs by value (structs go in memory, not registers). Pass `__xdata` pointers.
7. Prefer arrays indexed by `uint8_t` with a 256-byte alignment trick, or keep buffers ≤256 B, so index arithmetic stays 8-bit.
8. Globals in `__data` are faster than in `__xdata`, but IRAM is full here. Put **only** the hottest small variables in `__data` and everything else in `__xdata`.
9. `switch` on dense small values becomes a jump table. Sparse cases become compare chains: order the common cases first.
10. Don't jump into loops. Keep functions small and local. Read the generated `.asm`/`.lst` (in `build/`) to see what the compiler did. That is the only reliable feedback.
11. `--opt-code-size` trades speed for size. `--stack-size n` makes the linker check for headroom. Check `.mem` after every change that adds variables.
12. String literals and `printf` are expensive. The project has `log_puts`, `log_hex8/16` and `log_dec`. Use them, not `printf`.

## Startup customisation

- `unsigned char _sdcc_external_startup(void)` runs **before** globals are initialised (no initialised globals yet!). Use it for watchdog, clocks, XRAM enables. Returning nonzero skips the static init.
- libmf hooks its sleep-continue resume into startup: `enter_sleep_cont()` calls `_sdcc_external_startup()` again after wake.
- The bootloader uses a custom `crtstart.asm`. It declares the `VECTOR`, `HOME`, `UART0S0`, `WTCANSLP*` and `WTSTDBY*` areas libmf expects, and ends with `ljmp _bootloader` (there is no `main`).
- Linker placement flags look like `-Wl-bVECTOR=0x0000 -Wl-bHOME=0xd800`. `--code-size` checks the limit (last one wins).

## Inline assembly

```c
__asm
    mov  a, _counter      ; C globals have a leading underscore
    add  a, #1
    mov  _counter, a
__endasm;
/* or (SDCC >= 3.2): __asm__("nop"); */
```

- One instruction per line. In a macro, end each line with `\` **and** keep the newlines (each instruction on its own line in the output).
- The compiler doesn't analyse the asm. **Save and restore every register you touch** that the surrounding C might hold: R0-R7, A, B, DPTR, PSW, DPS. Prefer whole functions in asm over fragments mid-function.
- Local labels: `00001$:` (numeric, `$` suffix); they are scoped between non-local labels. Don't use `:` or quote characters inside asm comments.
- Parameters: the first one is in DPL/DPH/B/A; others in `_func_PARM_n` (declare them `.globl` in `.area OSEG` for a pure-asm function). Return in DPL/DPH/B/A.
- `__naked` functions get no prologue or epilogue. You write the `ret` / `reti` yourself.
- Assemble a standalone file with `sdas8051 -plosgff file.asm` (the project uses `-plosgffw`) and link the `.rel`.
- Useful idioms:
  - `jbc bit, label`: atomic test-and-clear.
  - `djnz Rn, label`: count-down loop.
  - `movx @dptr, a` / `movx a, @dptr`: XRAM, radio registers, XREGs.
  - `movc a, @a+dptr`: table lookup in code.
  - `mov dps, #1`: switch to DPTR1 (restore afterwards!).
  - `cpl` / `setb` / `clr` on SFR bits.
  - A `nop` after writing standby to PCON.
- Cycle timing on the AX8052 is **not** classic 12-clock. Calibrate busy-waits against a timer (wtimer0 ticks, or a hardware timer) instead of counting instructions.

## Classic 8051 pitfalls checklist

- [ ] ISR prototype in main.c; ISR does no 16/32-bit mul/div; it calls only reentrant or `nooverlay` functions.
- [ ] Shared variables `volatile`; multi-byte or RMW accesses inside `__critical` / masked.
- [ ] No large locals: anything above a few bytes is static `__xdata`.
- [ ] No recursion. No `__reentrant` without need.
- [ ] Multi-parameter function-pointer targets are `__reentrant`.
- [ ] Explicit pointer spaces in hot code; `__code` for constant tables.
- [ ] Casts to keep 8-bit arithmetic 8-bit; unsigned by default.
- [ ] Checked `.mem` (stack headroom) and code size after the change.
- [ ] Interrupt flags cleared at the source; no level source left asserted.
- [ ] Interrupt enables, `GPIOENABLE` and peripherals re-established after every power transition that resets them.
