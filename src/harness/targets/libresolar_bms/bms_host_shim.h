#pragma once

/*
 * Host-fuzz shim for LibreSolar bms-firmware app/src/bms_common.c.
 *
 * Purpose:
 * - Provide a minimal, Zephyr-free type surface for compiling the state machine
 *   logic on host with AFL++ (afl-clang-fast).
 * - This intentionally models only the fields and constants actually touched
 *   by bms_common.c.
 */

#include <stdint.h>
#include <stdbool.h>

// ---------------- minimal logging shim ----------------
#ifndef CONFIG_LOG_DEFAULT_LEVEL
#define CONFIG_LOG_DEFAULT_LEVEL 0
#endif
#define LOG_MODULE_REGISTER(name, level)
#define LOG_INF(fmt, ...) do { (void)0; } while (0)

// ---------------- minimal helper utilities ----------------
#ifndef __weak
#define __weak
#endif

#ifndef CLAMP
#define CLAMP(val, lo, hi) ((val) < (lo) ? (lo) : ((val) > (hi) ? (hi) : (val)))
#endif
#ifndef BIT
#define BIT(n) (1U << (n))
#endif

// ---------------- Battery cell types ----------------
enum bms_cell_type {
    CELL_TYPE_LFP,
    CELL_TYPE_NMC,
    CELL_TYPE_LTO,
};

// ---------------- BMS states ----------------
enum bms_state {
    BMS_STATE_OFF,
    BMS_STATE_CHG,
    BMS_STATE_DIS,
    BMS_STATE_NORMAL,
    BMS_STATE_SHUTDOWN,
};

// ---------------- Error flags (names used by bms_common.c) ----------------
// Values don’t need to match hardware; they must be consistent bitmasks.
#define BMS_ERR_CELL_OVERVOLTAGE  BIT(0)
#define BMS_ERR_CELL_UNDERVOLTAGE BIT(1)
#define BMS_ERR_CHG_OVERCURRENT   BIT(2)
#define BMS_ERR_DIS_OVERCURRENT   BIT(3)
#define BMS_ERR_SHORT_CIRCUIT     BIT(4)
#define BMS_ERR_OPEN_WIRE         BIT(5)
#define BMS_ERR_CHG_UNDERTEMP     BIT(6)
#define BMS_ERR_CHG_OVERTEMP      BIT(7)
#define BMS_ERR_DIS_UNDERTEMP     BIT(8)
#define BMS_ERR_DIS_OVERTEMP      BIT(9)
#define BMS_ERR_INT_OVERTEMP      BIT(10)
#define BMS_ERR_CELL_FAILURE      BIT(11)
#define BMS_ERR_CHG_OFF           BIT(12)
#define BMS_ERR_DIS_OFF           BIT(13)

// Switch constants used by bms_common.c
#define BMS_SWITCH_CHG BIT(0)
#define BMS_SWITCH_DIS BIT(1)

#define BMS_ERR_ALL (~0u)
struct bms_ic_conf {
    // balancing
    bool auto_balancing;
    int bal_idle_delay;
    float bal_idle_current;
    float bal_cell_voltage_diff;
    float bal_cell_voltage_min;

    // current limits
    float dis_oc_limit;
    float chg_oc_limit;
    int dis_oc_delay_ms;
    int chg_oc_delay_ms;
    float dis_sc_limit;
    int dis_sc_delay_us;

    // temperature limits
    float dis_ot_limit;
    float dis_ut_limit;
    float chg_ot_limit;
    float chg_ut_limit;
    float temp_limit_hyst;

    // voltage limits
    float cell_ov_limit;
    float cell_ov_reset;
    float cell_uv_limit;
    float cell_uv_reset;
    float cell_chg_voltage_limit;
    float cell_dis_voltage_limit;
    int cell_ov_delay_ms;
    int cell_uv_delay_ms;

    // alerts
    uint32_t alert_mask;
};

struct bms_ic_data {
    uint32_t error_flags;
    float cell_voltage_avg;
    float cell_voltage_min;
    float cell_voltage_max;
    float current;
};

// Forward-declare device (opaque for host fuzzing)
struct device { int dummy; };

// ---------------- Minimal bms_context ----------------
#define NUM_OCV_POINTS 21

struct bms_context {
    const struct device *ic_dev;

    struct bms_ic_conf ic_conf;
    struct bms_ic_data ic_data;

    enum bms_state state;

    // user controls / derived state
    bool chg_enable;
    bool dis_enable;
    bool full;
    bool empty;

    // SOC model
    float soc;
    float nominal_capacity_Ah;
    const float *ocv_points;
    const float *soc_points;
};

#define BMS_ERR_ALL (~0u)
// State machine entrypoint (defined in bms_common.c)
void bms_state_machine(struct bms_context *bms);

// Helpers defined in bms_common.c (need prototypes to avoid implicit decl)
bool bms_chg_allowed(struct bms_context *bms);
bool bms_dis_allowed(struct bms_context *bms);

// SOC helper hook (not required by bms_common.c, but used by other modules)
void bms_soc_update(struct bms_context *bms);

// bms_init_config is defined in bms_common.c (UUT).
void bms_init_config(struct bms_context *bms, enum bms_cell_type type, float nominal_capacity_Ah);

// Driver call stub used by bms_common.c
static inline int bms_ic_set_switches(const struct device *dev, uint32_t sw, bool en) {
    (void)dev; (void)sw; (void)en;
    return 0;
}
