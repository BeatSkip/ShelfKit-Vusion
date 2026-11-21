;--------------------------------------------------------------------------
;  crtstart.asm - C run-time: startup
;
;  Copyright (C) 2004, Erik Petrich
;
;  This library is free software; you can redistribute it and/or modify it
;  under the terms of the GNU General Public License as published by the
;  Free Software Foundation; either version 2.1, or (at your option) any
;  later version.
;
;  This library is distributed in the hope that it will be useful,
;  but WITHOUT ANY WARRANTY; without even the implied warranty of
;  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
;  GNU General Public License for more details.
;
;  You should have received a copy of the GNU General Public License
;  along with this library; see the file COPYING. If not, write to the
;  Free Software Foundation, 51 Franklin Street, Fifth Floor, Boston,
;   MA 02110-1301, USA.
;
;  As a special exception, if you link this library with other files,
;  some of which are compiled with SDCC, to produce an executable,
;  this library does not by itself cause the resulting executable to
;  be covered by the GNU General Public License. This exception does
;  not however invalidate any other reasons why the executable file
;  might be covered by the GNU General Public License.
;--------------------------------------------------------------------------

	.area HOME    (CODE)
	.area GSINIT0 (CODE)
	.area GSINIT1 (CODE)
	.area GSINIT2 (CODE)
	.area GSINIT3 (CODE)
	.area GSINIT4 (CODE)
	.area GSINIT5 (CODE)
	.area GSINIT  (CODE)
	.area GSFINAL (CODE)
	.area CSEG    (CODE)
	.area CONST   (CODE)
    .area UART0S0 (CODE)
    .area UART0S1 (CODE)
    .area UART0S2 (CODE)
    .area UART0S3 (CODE)
    .area UART0S4 (CODE)
    .area UART0S5 (CODE)
    .area WTCANSLP0 (CODE)
    .area WTCANSLP1 (CODE)
    .area WTCANSLP2 (CODE)
    .area WTSTDBY0 (CODE)
    .area WTSTDBY1 (CODE)
    .area WTSTDBY2 (CODE)

 	.area VECTOR  (CODE)
	.globl __interrupt_vect
__interrupt_vect:
	ljmp	__sdcc_gsinit_startup

	.globl __sdcc_gsinit_startup
	.globl __start__stack
	.globl _jmp_vector

	.area GSINIT0 (CODE)

	nop
; The entry address must not move: every installed tag has `ljmp 0xD838` at
; 0x0000 in its page 0, and erase_app()/OTA rewrite that jump from this label.
; Check `__sdcc_gsinit_startup` in the map after every change here.
__sdcc_gsinit_startup::
;
; Wake from MCU Sleep: hand over to the application at once, touching nothing.
;
; Sleep restarts the CPU at 0x0000, i.e. here. libmf's enter_sleep_cont()
; expects to land in the application's own startup, which finds its marker
; (0xBE at IRAM 0xFF, 0x37 at 0xFE) and resumes where the application went to
; sleep. The normal path below breaks that: it overwrites the application's
; IRAM (its variables and this bootloader's stack share 0x08-0x7F), runs with
; the pins frozen (GPIOENABLE stays 0 after Sleep and is never set here), forces
; the XOSC on, and run_application() resets CLKCON/WTCFGB/IE to reset values.
; It also drops into the command loop when an NFC tap (PB3 low) woke the tag.
;
; So: PCON.WAKEUP set AND the marker present -> jump through jmp_vector exactly
; as a chip without a bootloader would. Requiring the marker as well means a
; stale WAKEUP flag can never make an OTA reset (PCON.SWRESET) skip the update:
; the application clears the marker before it resets. Only A, R0-R2 and DPTR
; are used; the application's startup sets SP itself.
	mov	a,0x87			; PCON
	anl	a,#0x40			; WAKEUP: last start was a wake from (deep) sleep
	jz	00010$
	mov	r0,#0xff
	cjne	@r0,#0xBE,00010$	; libmf REGTABLE_SIG0
	dec	r0
	cjne	@r0,#0x37,00010$	; libmf REGTABLE_SIG1
	mov	dptr,#_jmp_vector	; application entry, low byte first
	clr	a
	movc	a,@a+dptr
	mov	r1,a
	mov	a,#1
	movc	a,@a+dptr
	mov	r2,a
	anl	a,r1
	cpl	a
	jz	00010$			; 0xFFFF: no application, normal boot
	mov	dpl,r1
	mov	dph,r2
	clr	a
	jmp	@a+dptr
00010$:
	mov	sp,#__start__stack - 1

	.area GSINIT2 (CODE)

	lcall	__sdcc_external_startup
	mov	a,dpl
	jz	__sdcc_init_data
	ljmp	__sdcc_program_startup
__sdcc_init_data:

	.area GSFINAL (CODE)
__sdcc_program_startup:
	ljmp	_bootloader

	.area	SSEG	(DATA)
__start__stack:
	.ds	1
