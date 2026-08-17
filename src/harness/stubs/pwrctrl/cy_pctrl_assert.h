#ifndef CY_PCTRL_ASSERT_H
#define CY_PCTRL_ASSERT_H

// Host-side stub for pwrctrl assert helper used by block code.

#include "cy_pctrl_log.h"
#include "cy_assert.h"

#ifdef __cplusplus
extern "C" {
#endif

static inline void cy_pctrl_assert_msg(int assertion,
                                      CY_PCTRL_LOG_FACILITY_T facility,
                                      CY_PCTRL_LOG_LEVEL_T level,
                                      const char* fmt, ...) {
  (void)facility; (void)level; (void)fmt;
  if (!assertion) {
    CY_ASSERT(0);
  }
}

#ifdef __cplusplus
}
#endif

#endif /* CY_PCTRL_ASSERT_H */
