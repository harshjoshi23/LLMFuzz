#ifndef CMSIS_COMPILER_H
#define CMSIS_COMPILER_H

// Host-side shim for CMSIS compiler intrinsics expected by mtb-mw-pctrl.

#ifndef __STATIC_FORCEINLINE
#define __STATIC_FORCEINLINE static inline __attribute__((always_inline))
#endif

#ifndef __STATIC_INLINE
#define __STATIC_INLINE static inline
#endif

#endif /* CMSIS_COMPILER_H */
