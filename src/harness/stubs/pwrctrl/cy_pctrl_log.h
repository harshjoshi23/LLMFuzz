#ifndef CY_PCTRL_LOG_H
#define CY_PCTRL_LOG_H

// Host-side minimal logging+assert stub for mtb-mw-pctrl fuzz harness builds.
// Upstream expects ModusToolbox platform headers; for fuzzing we no-op.

#include <stdint.h>
#include <stdarg.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
  CY_PCTRL_LOG_ERROR = 0,
  CY_PCTRL_LOG_WARNING,
  CY_PCTRL_LOG_NOTICE,
  CY_PCTRL_LOG_INFO,
  CY_PCTRL_LOG_DEBUG,
  CY_PCTRL_LOG_DEBUG1,
  CY_PCTRL_LOG_DEBUG2,
  CY_PCTRL_LOG_MAX
} CY_PCTRL_LOG_LEVEL_T;

typedef enum {
  CYLF_PCTRL_MIDDLEWARE = 0,
  CYLF_PCTRL_MAX
} CY_PCTRL_LOG_FACILITY_T;

static inline int cy_pctrl_log_msg(CY_PCTRL_LOG_FACILITY_T facility,
                                  CY_PCTRL_LOG_LEVEL_T level,
                                  const char* fmt, ...) {
  (void)facility; (void)level; (void)fmt;
  return 0;
}

static inline int cy_pctrl_log_msg_(CY_PCTRL_LOG_FACILITY_T facility,
                                   CY_PCTRL_LOG_LEVEL_T level,
                                   const char* fmt, ...) {
  (void)facility; (void)level; (void)fmt;
  return 0;
}

// Many block implementations call this directly.
static inline void cy_pctrl_assert_msg(int assertion,
                                      CY_PCTRL_LOG_FACILITY_T facility,
                                      CY_PCTRL_LOG_LEVEL_T level,
                                      const char* fmt, ...) {
  (void)facility; (void)level; (void)fmt;
  // Avoid aborting during fuzzing; treat as soft assert.
  // If you want hard-fail, change to: if (!assertion) __builtin_trap();
  (void)assertion;
}

#ifdef __cplusplus
}
#endif

#endif /* CY_PCTRL_LOG_H */
