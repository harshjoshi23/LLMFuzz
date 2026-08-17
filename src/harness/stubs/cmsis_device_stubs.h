#ifndef CMSIS_DEVICE_STUBS_H
#define CMSIS_DEVICE_STUBS_H

// Host-side CMSIS device/IRQ/SysTick stubs for building asset/svcs on Linux.

#include <stdint.h>

#ifndef __WEAK
#define __WEAK __attribute__((weak))
#endif

// SysTick stubs used by basic_sched.c
#ifndef SysTick_LOAD_RELOAD_Msk
#define SysTick_LOAD_RELOAD_Msk (0x00FFFFFFu)
#endif

// SystemCoreClock is a global variable in CMSIS; basic_sched.c declares it as extern.
static uint32_t SystemCoreClock = 48000000u;

static inline uint32_t SysTick_Config(uint32_t ticks)
{
    (void)ticks;
    return 0u; // success
}

// NVIC stubs used by ppca_wdt.c
static inline void NVIC_EnableIRQ(int irq)
{
    (void)irq;
}

// Device IRQn used by ppca_wdt.c
#ifndef srss_interrupt_mcwdt_0_IRQn
#define srss_interrupt_mcwdt_0_IRQn (0)
#endif

// MCWDT register access macro used by ppca_wdt.c reset path
// Provide a writable dummy.
static volatile uint32_t _alan_mcwdt_ctl_dummy = 0;
#ifndef MCWDT_CTL
#define MCWDT_CTL(hw) (_alan_mcwdt_ctl_dummy)
#endif

// ---------- DWT / DCB register stubs (used by dwt_profiling.h) ----------

// DWT stub structure
typedef struct {
    volatile uint32_t CTRL;
    uint32_t _reserved0[5];
    volatile uint32_t CYCCNT;
} _alan_DWT_Type;

static _alan_DWT_Type _alan_dwt_inst = {0};
#ifndef DWT
#define DWT (&_alan_dwt_inst)
#endif

#ifndef DWT_CTRL_CYCCNTENA_Msk
#define DWT_CTRL_CYCCNTENA_Msk (1u << 0)
#endif

// DCB stub structure
typedef struct {
    volatile uint32_t DEMCR;
} _alan_DCB_Type;

static _alan_DCB_Type _alan_dcb_inst = {0};
#ifndef DCB
#define DCB (&_alan_dcb_inst)
#endif

#ifndef DCB_DEMCR_TRCENA_Msk
#define DCB_DEMCR_TRCENA_Msk (1u << 24)
#endif

// Barrier stubs used by dwt_profiling.h inline functions
#ifndef __DSB
#define __DSB() do {} while (0)
#endif

#ifndef __ISB
#define __ISB() do {} while (0)
#endif

#endif /* CMSIS_DEVICE_STUBS_H */
