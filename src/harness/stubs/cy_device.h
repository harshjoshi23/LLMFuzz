#ifndef CY_DEVICE_H
#define CY_DEVICE_H

// Host-side stub. Real definitions are target-specific.

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#include "cy_utils.h"

// Provide SysTick constants and stubs expected by basic_sched.
#ifndef SysTick_LOAD_RELOAD_Msk
#define SysTick_LOAD_RELOAD_Msk (0x00FFFFFFu)
#endif

static inline uint32_t SysTick_Config(uint32_t ticks)
{
    (void)ticks;
    return 0u;
}

// Provide SystemCoreClock backing symbol (basic_sched declares extern).
// Keep it writable so tests can adjust it if needed.
uint32_t SystemCoreClock = 48000000u;

#endif /* CY_DEVICE_H */
