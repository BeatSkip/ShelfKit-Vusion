/**
 * @file startup.c
 * @brief Cortex-M33 vector table and reset handler for the EFR32FG22
 *
 * Minimal on purpose: the first 16 system vectors, a catch-all for the device interrupts,
 * .data copied from flash and .bss cleared before main(). When the Gecko SDK is brought in,
 * its startup_efr32fg22.c (with the named device vectors) replaces this file.
 */

#include <stdint.h>

extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss, _estack;
extern int main(void);

void Reset_Handler(void);
void Default_Handler(void);

void Default_Handler(void)
{
    for (;;)
        ;
}

void NMI_Handler(void)        __attribute__((weak, alias("Default_Handler")));
void HardFault_Handler(void)  __attribute__((weak, alias("Default_Handler")));
void MemManage_Handler(void)  __attribute__((weak, alias("Default_Handler")));
void BusFault_Handler(void)   __attribute__((weak, alias("Default_Handler")));
void UsageFault_Handler(void) __attribute__((weak, alias("Default_Handler")));
void SecureFault_Handler(void) __attribute__((weak, alias("Default_Handler")));
void SVC_Handler(void)        __attribute__((weak, alias("Default_Handler")));
void DebugMon_Handler(void)   __attribute__((weak, alias("Default_Handler")));
void PendSV_Handler(void)     __attribute__((weak, alias("Default_Handler")));
void SysTick_Handler(void)    __attribute__((weak, alias("Default_Handler")));

#define DEVICE_IRQS 51          /* EFR32FG22: TODO(sdk) name them from startup_efr32fg22.c */

typedef void (*vector)(void);

__attribute__((section(".vectors"), used))
const vector vectors[16 + DEVICE_IRQS] = {
    (vector)(uintptr_t)&_estack,
    Reset_Handler,
    NMI_Handler,
    HardFault_Handler,
    MemManage_Handler,
    BusFault_Handler,
    UsageFault_Handler,
    SecureFault_Handler,
    0, 0, 0,
    SVC_Handler,
    DebugMon_Handler,
    0,
    PendSV_Handler,
    SysTick_Handler,
    [16 ... 16 + DEVICE_IRQS - 1] = Default_Handler,
};

void Reset_Handler(void)
{
    uint32_t *src = &_sidata;
    uint32_t *dst;

    for (dst = &_sdata; dst < &_edata;)
        *dst++ = *src++;
    for (dst = &_sbss; dst < &_ebss;)
        *dst++ = 0;

    /* the FPU is on the chip; let the code use it (CPACR: CP10 + CP11 full access) */
    *(volatile uint32_t *)0xE000ED88u |= (0xFu << 20);

    main();
    for (;;)
        ;
}
