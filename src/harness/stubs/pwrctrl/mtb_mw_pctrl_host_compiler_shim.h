#ifndef MTB_MW_PCTRL_HOST_COMPILER_SHIM_H
#define MTB_MW_PCTRL_HOST_COMPILER_SHIM_H

// Host-side compiler shim for mtb-mw-pctrl.
// The upstream library expects toolchain-provided macros (e.g. __STATIC_FORCEINLINE).

#ifndef __STATIC_FORCEINLINE
#define __STATIC_FORCEINLINE static inline __attribute__((always_inline))
#endif

#ifndef __STATIC_INLINE
#define __STATIC_INLINE static inline
#endif

#endif /* MTB_MW_PCTRL_HOST_COMPILER_SHIM_H */
