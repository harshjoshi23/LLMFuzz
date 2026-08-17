#ifndef MTB_MW_PCTRL_COMPILER_H__
#define MTB_MW_PCTRL_COMPILER_H__

// Host-side shim for mtb-mw-pctrl compiler abstractions.
// Critical goals:
// - Provide CMSIS-style FORCEINLINE macros
// - Provide float32_t when CMSIS DSP headers aren't present
// - Ensure basic fixed-width integer types are visible

#include <stdint.h>

typedef float float32_t;

#ifdef __cplusplus
extern "C" {
#endif

#ifndef __STATIC_FORCEINLINE
#define __STATIC_FORCEINLINE static inline __attribute__((always_inline))
#endif

#ifndef __STATIC_INLINE
#define __STATIC_INLINE static inline
#endif

#ifndef PWRLIB_INLINE
#define PWRLIB_INLINE __STATIC_FORCEINLINE
#endif

#ifndef PWRLIB_UNUSED
#define PWRLIB_UNUSED(x) ((void)(x))
#endif

#ifdef __cplusplus
}
#endif

#endif /* MTB_MW_PCTRL_COMPILER_H__ */
