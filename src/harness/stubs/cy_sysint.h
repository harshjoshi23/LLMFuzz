#ifndef CY_SYSINT_H
#define CY_SYSINT_H

// Host-side stub for PDL sysint vector API used by SVCS basic scheduler.

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifndef SysTick_IRQn
#define SysTick_IRQn (15)
#endif

typedef void (*cy_israddress)(void);

static inline cy_israddress Cy_SysInt_SetVector(int irqn, cy_israddress handler)
{
    (void)irqn;
    return handler;
}

#ifdef __cplusplus
}
#endif

#endif /* CY_SYSINT_H */
