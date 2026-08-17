#ifndef CY_PDL_H
#define CY_PDL_H

// Host-side stub for Cypress/Infineon PDL.
// Provides minimal types/macros used by mtb-mw-pctrl-svc asset/svcs.

#include <stdint.h>

// Common frequency macro used by ppca_wdt.h conversions.
#ifndef CY_SYSCLK_ILO_FREQ
#define CY_SYSCLK_ILO_FREQ (32000u)
#endif

// Basic assert used by service code.
#ifndef CY_ASSERT
#include <assert.h>
#define CY_ASSERT(x) assert(x)
#endif

// __weak attribute used by stack_mon.c
#ifndef __weak
#define __weak __attribute__((weak))
#endif

// Interrupt controller stubs
typedef struct {
    uint32_t intrSrc;
    uint32_t intrPriority;
} cy_stc_sysint_t;

static inline int Cy_SysInt_Init(const cy_stc_sysint_t* cfg, void (*isr)(void))
{
    (void)cfg;
    (void)isr;
    return 0;
}

// Reset reason stubs
#define CY_SYSLIB_RESET_SWWDT0 (1u)
static inline uint32_t Cy_SysLib_GetResetReason(void) { return 0u; }
static inline void Cy_SysLib_ClearResetReason(void) {}

// NOTE: ppca_wdt.h includes cy_ppca_shm.h for cy_en_ppca_core_t

// MCWDT types + constants used by ppca_wdt.c
typedef enum {
    CY_MCWDT_MODE_NONE = 0,
} cy_en_mcwdtmode_t;

typedef enum {
    CY_MCWDT_LOWER_LIMIT_MODE_NOTHING = 0,
} cy_en_mcwdt_lower_limit_t;

typedef struct {
    uint32_t c0Match;
    uint32_t c1Match;
    uint32_t c0Mode;
    uint32_t c1Mode;
    uint32_t c2ToggleBit;
    uint32_t c2Mode;
    int c0ClearOnMatch;
    int c1ClearOnMatch;
    int c0c1Cascade;
    int c1c2Cascade;
    uint32_t c0LowerLimitMode;
    uint32_t c1LowerLimitMode;
    uint32_t c0LowerLimit;
    uint32_t c1LowerLimit;
} cy_stc_mcwdt_config_t;

#define CY_MCWDT_CTR0 (1u << 0)
#define CY_MCWDT_CTR1 (1u << 1)

#define CY_MCWDT_COUNTER0 (0u)
#define CY_MCWDT_COUNTER1 (1u)

// Register mask stubs referenced by ppca_wdt.c
#define MCWDT_STRUCT_MCWDT_CTL_WDT_RESET0_Msk (1u << 0)
#define MCWDT_STRUCT_MCWDT_CTL_WDT_RESET1_Msk (1u << 1)

// Hardware base pointer placeholder + default symbol used in ppca_wdt.h
#ifndef MCWDT_STRUCT0
#define MCWDT_STRUCT0 ((void*)0)
#endif

static inline void Cy_MCWDT_Unlock(void* hw) { (void)hw; }
static inline void Cy_MCWDT_Lock(void* hw) { (void)hw; }
static inline void Cy_MCWDT_Init(void* hw, const cy_stc_mcwdt_config_t* cfg) { (void)hw; (void)cfg; }
static inline void Cy_MCWDT_ClearInterrupt(void* hw, uint32_t mask) { (void)hw; (void)mask; }
static inline void Cy_MCWDT_SetInterruptMask(void* hw, uint32_t mask) { (void)hw; (void)mask; }
static inline uint32_t Cy_MCWDT_GetInterruptStatus(void* hw) { (void)hw; return 0u; }
static inline uint32_t Cy_MCWDT_GetInterruptMask(void* hw) { (void)hw; return 0xffffffffu; }
static inline void Cy_MCWDT_SetMode(void* hw, uint32_t ctr, cy_en_mcwdtmode_t mode) { (void)hw; (void)ctr; (void)mode; }
static inline void Cy_MCWDT_SetMatch(void* hw, uint32_t ctr, uint32_t match, uint32_t ignoreBits) { (void)hw; (void)ctr; (void)match; (void)ignoreBits; }
static inline void Cy_MCWDT_Enable(void* hw, uint32_t ctrMask, uint16_t delayUs) { (void)hw; (void)ctrMask; (void)delayUs; }

#endif /* CY_PDL_H */
