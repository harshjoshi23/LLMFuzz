#ifndef CMSIS_COMPILER_H
#define CMSIS_COMPILER_H

// Minimal host-side stubs for CMSIS compiler helpers.
// Enough to satisfy shared_memory headers when fuzzing on host.
//
// NOTE:
// The SVC shared_memory mutex implementation expects ARM-exclusive primitives
// (LDREX/STREX) and barrier ops. On host we approximate these as non-atomic ops.
// This is fine for single-threaded fuzzing and keeps behavior deterministic.

#ifndef __STATIC_INLINE
#define __STATIC_INLINE static inline
#endif

#ifndef __DMB
#define __DMB() do {} while (0)
#endif

#ifndef __CLREX
#define __CLREX() do {} while (0)
#endif

#ifndef __LDREXW
#define __LDREXW(ptr) (*(volatile unsigned int *)(ptr))
#endif

#ifndef __STREXW
#define __STREXW(val, ptr) ((*(volatile unsigned int *)(ptr) = (unsigned int)(val)), 0u)
#endif

// SCnSCB is used only behind CY_DEVICE_PSC3_P8 guards; provide a dummy to avoid
// accidental compile failures if macros are enabled.
#ifndef SCnSCB
typedef struct { volatile unsigned int ACTLR; } _alan_scnscb_t;
static _alan_scnscb_t _alan_scnscb_dummy = {0};
#define SCnSCB (&_alan_scnscb_dummy)
#endif

#endif /* CMSIS_COMPILER_H */
