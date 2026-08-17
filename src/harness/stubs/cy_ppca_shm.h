#ifndef CY_PPCA_SHM_H
#define CY_PPCA_SHM_H

// Host-side minimal shared-memory stub types needed by ppca_wdt.h.

#include <stdint.h>

typedef enum {
    CY_PPCA_CORE_0 = 0,
    CY_PPCA_CORE_1 = 1,
} cy_en_ppca_core_t;

#endif /* CY_PPCA_SHM_H */
