#ifndef CY_RESULT_H
#define CY_RESULT_H

// Host-side stub for ModusToolbox cy_result.h.
// Enough for mtb-mw-pctrl host fuzz harness builds.

#include <stdint.h>

typedef uint32_t cy_rslt_t;

#ifndef CY_RSLT_SUCCESS
#define CY_RSLT_SUCCESS ((cy_rslt_t)0u)
#endif

#ifndef CY_RSLT_TYPE_ERROR
#define CY_RSLT_TYPE_ERROR (1u)
#endif

// Generic failure code (keep non-zero)
#ifndef CY_RSLT_ERROR
#define CY_RSLT_ERROR ((cy_rslt_t)0x80000000u)
#endif

#endif /* CY_RESULT_H */
