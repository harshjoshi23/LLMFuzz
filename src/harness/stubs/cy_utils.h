#ifndef CY_UTILS_H
#define CY_UTILS_H

// Host-side stub. Provide only macros used by shared_memory headers.

#ifndef CY_ALIGN
#define CY_ALIGN(x) __attribute__((aligned(x)))
#endif

#ifndef CY_SECTION
#define CY_SECTION(name) __attribute__((section(name)))
#endif

#ifndef CY_MISRA_DEVIATE_BLOCK_START
#define CY_MISRA_DEVIATE_BLOCK_START(...)
#endif
#ifndef CY_MISRA_BLOCK_END
#define CY_MISRA_BLOCK_END(...)
#endif
#ifndef CY_MISRA_DEVIATE_LINE
#define CY_MISRA_DEVIATE_LINE(...)
#endif

#endif /* CY_UTILS_H */
