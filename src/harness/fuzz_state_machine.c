/*******************************************************************************
 * File: fuzz_state_machine.c
 * 
 * Description: AFL++ fuzz harness for SystemControl state machine
 *              Part of: AI-Enhanced Fuzzing for Embedded Power Systems
 *              
 * Target: nvidia_pdb firmware - Power conversion state machine
 * 
 * Harness notes:
 * - This harness is a synthetic demo harness (host-side) used to exercise the pipeline.
 * - It is NOT a claim of real vulnerabilities in any vendor firmware.
 * - Any mentions of "vulnerability" are pedagogical markers for fuzzing surfaces.
 *
 * Build with AFL++:
 *   afl-gcc -o fuzz_state fuzz_state_machine.c -I../data/firmware/nvidia_pdb
 *   
 * Run:
 *   afl-fuzz -i seeds/state -o findings -t 1000 ./fuzz_state @@
 *
 * Copyright 2025 - Thesis Research
 ******************************************************************************/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <math.h>

/*******************************************************************************
 * State Machine States (from SystemControl.h)
 ******************************************************************************/
typedef enum {
    STATE_INIT = 0,
    STATE_WAIT_FOR_DISCHARGE = 1,
    STATE_CHECK_INTERLOCK = 2,
    STATE_ENABLE_INTERLOCK = 3,
    STATE_VERIFY_INTERLOCK = 4,
    STATE_CHECK_INPUT_VOLTAGE = 5,
    STATE_ENABLE_HOTSWAP = 6,
    STATE_CHECK_PGOOD = 7,
    STATE_ENABLE_PRECHARGE = 8,
    STATE_VERIFY_PRECHARGE = 9,
    STATE_ENABLE_OUTPUT_PRECHARGE = 10,
    STATE_ENABLE_VDRV = 11,
    STATE_CHECK_VDRV = 12,
    STATE_WAIT_SEC_MOSFET = 13,
    STATE_DCX_PRIM_SOFT_START = 14,
    STATE_CKECK_VOUT_ONCE = 15,
    STATE_DCX_SEC_SOFT_START = 16,
    STATE_CKECK_VOUT_TWICE = 17,
    STATE_RUN = 42,
    
    // Power-down states
    STATE_POWERDOWN_INIT = 50,
    STATE_DISABLE_SEC_MOSFET = 51,
    STATE_DISABLE_VDRV_SEC = 52,
    STATE_SOFT_OFF_CONVERTER = 53,
    STATE_DISABLE_PRECHARGE = 54,
    STATE_DISCHARGE_DC_LINK = 55,
    STATE_OFF = 56,
    
    // Error states
    STATE_ERROR = 100
} SystemState_t;

/*******************************************************************************
 * Configuration Limits (from _CONFIGURATION.h)
 ******************************************************************************/
#define INPUT_VOLTAGE_MIN    36.0f
#define INPUT_VOLTAGE_MAX    60.0f
#define OUTPUT_VOLTAGE_MIN   11.5f
#define OUTPUT_VOLTAGE_MAX   12.5f
#define INTERLOCK_CURRENT_VERIFY_MIN  0.01f
#define INTERLOCK_CURRENT_VERIFY_MAX  0.2f

/*******************************************************************************
 * Simulated Hardware State
 ******************************************************************************/
typedef struct {
    // ADC readings (controlled by fuzzer)
    float vin;
    float vout;
    float vdrv_a;
    float vdrv_b;
    float i_interlock;
    
    // GPIO states
    uint8_t en_interlock;
    uint8_t en_12v_precharge;
    uint8_t mcu_en_vdrv_a;
    uint8_t mcu_en_vdrv_b;
    uint8_t hotswap_pos_ctrl_en;
    uint8_t en_discharge_ctrl_n;
    uint8_t hotswap_pgood;
    
    // System state
    SystemState_t state;
    bool error;
    bool powerdown;
    uint16_t delay_counter;
    float vin_before_turn_on;
} hw_state_t;

static hw_state_t hw = {0};

/*******************************************************************************
 * Coverage / surface tracking counters (demo-only)
 ******************************************************************************/
typedef struct {
    int invalid_transitions;
    int unsafe_voltage_conditions;
    int timing_violations;
    int gpio_conflicts;
    int critical_state_errors;
} state_vuln_stats_t;

static state_vuln_stats_t stats = {0};

/*******************************************************************************
 * Valid State Transitions Matrix
 * 
 * Defines which state transitions are valid. Invalid transitions may indicate
 * vulnerabilities or attack vectors.
 ******************************************************************************/
static const bool valid_transitions[101][101] = {
    // Each row is "from state", column is "to state"
    // Only valid transitions are marked true
    [STATE_INIT] = {
        [STATE_WAIT_FOR_DISCHARGE] = true,
        [STATE_ERROR] = true,
    },
    [STATE_WAIT_FOR_DISCHARGE] = {
        [STATE_CHECK_INTERLOCK] = true,
        [STATE_ERROR] = true,
    },
    [STATE_CHECK_INTERLOCK] = {
        [STATE_ENABLE_INTERLOCK] = true,
        [STATE_ERROR] = true,
    },
    [STATE_ENABLE_INTERLOCK] = {
        [STATE_VERIFY_INTERLOCK] = true,
        [STATE_ERROR] = true,
    },
    [STATE_VERIFY_INTERLOCK] = {
        [STATE_CHECK_INPUT_VOLTAGE] = true,
        [STATE_ERROR] = true,
    },
    [STATE_CHECK_INPUT_VOLTAGE] = {
        [STATE_ENABLE_HOTSWAP] = true,
        [STATE_ERROR] = true,
    },
    [STATE_ENABLE_HOTSWAP] = {
        [STATE_CHECK_PGOOD] = true,
        [STATE_ERROR] = true,
    },
    [STATE_CHECK_PGOOD] = {
        [STATE_ENABLE_PRECHARGE] = true,
        [STATE_POWERDOWN_INIT] = true,
        [STATE_ERROR] = true,
    },
    [STATE_ENABLE_PRECHARGE] = {
        [STATE_VERIFY_PRECHARGE] = true,
        [STATE_ERROR] = true,
    },
    [STATE_VERIFY_PRECHARGE] = {
        [STATE_ENABLE_VDRV] = true,
        [STATE_POWERDOWN_INIT] = true,
        [STATE_ERROR] = true,
    },
    [STATE_RUN] = {
        [STATE_POWERDOWN_INIT] = true,
        [STATE_ERROR] = true,
    },
    // Add more as needed...
};

/*******************************************************************************
 * Initialize Hardware State
 ******************************************************************************/
void hw_init(void) {
    memset(&hw, 0, sizeof(hw));
    hw.state = STATE_INIT;
    hw.vin = 48.0f;  // Default nominal voltage
    hw.vout = 0.0f;
    hw.en_discharge_ctrl_n = 1;  // Discharge active (active low)
}

/*******************************************************************************
 * Parse Fuzz Input into Hardware State
 * 
 * Input format (variable length):
 *   Byte 0: Target state (forces transition)
 *   Byte 1-2: VIN value (fixed point 8.8)
 *   Byte 3-4: VOUT value (fixed point 8.8)
 *   Byte 5: GPIO inputs (bitfield)
 *   Byte 6: Delay counter value
 *   Byte 7+: Sequence of state commands
 ******************************************************************************/
void parse_fuzz_input(const uint8_t* data, size_t len) {
    if (len < 1) return;
    
    // Byte 0: Set initial state
    uint8_t target_state = data[0];
    if (target_state <= STATE_OFF || target_state == STATE_RUN) {
        hw.state = (SystemState_t)target_state;
    }
    
    // Byte 1-2: VIN (fixed point)
    if (len >= 3) {
        uint16_t vin_raw = (data[2] << 8) | data[1];
        hw.vin = (float)vin_raw / 256.0f;  // 0-255.99 volt range
    }
    
    // Byte 3-4: VOUT
    if (len >= 5) {
        uint16_t vout_raw = (data[4] << 8) | data[3];
        hw.vout = (float)vout_raw / 256.0f;
    }
    
    // Byte 5: GPIO inputs
    if (len >= 6) {
        hw.hotswap_pgood = (data[5] >> 0) & 1;
        hw.en_discharge_ctrl_n = (data[5] >> 1) & 1;
    }
    
    // Byte 6: Delay counter
    if (len >= 7) {
        hw.delay_counter = data[6];
    }
    
    // Byte 7: Interlock current
    if (len >= 8) {
        hw.i_interlock = (float)data[7] / 1000.0f;  // 0-0.255 A
    }
}

/*
 * State Machine Step - MAIN FUZZ TARGET
 *
 * FUZZING SURFACE (demo-only):
 *   - Invalid state transitions (skip safety checks)
 *   - Voltage condition violations (safety-critical conditions)
 *   - Timing attacks (bypass delay requirements)
 *   - GPIO conflicts (simultaneous conflicting outputs)
 */
int run_state_machine_step(void) {
    SystemState_t prev_state = hw.state;
    
    /***************************************************************************
     * Surface check (demo-only): Output voltage dropout in running states
     * This models the kind of safety invariant real firmware would enforce.
     **************************************************************************/
    if (hw.state >= STATE_VERIFY_PRECHARGE && hw.state < STATE_POWERDOWN_INIT) {
        if (hw.vout < 10.0f) {
            // Voltage dropout detected!
            hw.state = STATE_POWERDOWN_INIT;
            hw.error = true;
            stats.unsafe_voltage_conditions++;
            return -1;
        }
    }
    
    switch (hw.state) {
        case STATE_INIT:
            // Reset all GPIO to safe state
            hw.en_interlock = 0;
            hw.en_12v_precharge = 0;
            hw.mcu_en_vdrv_a = 0;
            hw.mcu_en_vdrv_b = 0;
            hw.hotswap_pos_ctrl_en = 0;
            hw.en_discharge_ctrl_n = 1;  // Enable discharge
            hw.delay_counter = 0;
            hw.vin_before_turn_on = 0;
            hw.state = STATE_WAIT_FOR_DISCHARGE;
            break;
            
        case STATE_WAIT_FOR_DISCHARGE:
            hw.delay_counter++;
            if (hw.delay_counter > 10) {
                hw.state = STATE_CHECK_INTERLOCK;
                hw.en_discharge_ctrl_n = 0;  // Stop discharge
                hw.delay_counter = 0;
            }
            break;
            
        case STATE_CHECK_INTERLOCK:
            /***********************************************************************
             * Surface note (demo-only): What if i_interlock is negative (ADC glitch)?
             ***********************************************************************/
            if (hw.i_interlock < 0.05f) {
                hw.state = STATE_ENABLE_INTERLOCK;
            } else {
                // STUCK: Current too high, interlock may be stuck
                stats.timing_violations++;
            }
            break;
            
        case STATE_ENABLE_INTERLOCK:
            hw.en_interlock = 1;
            hw.state = STATE_VERIFY_INTERLOCK;
            break;
            
        case STATE_VERIFY_INTERLOCK:
            /***********************************************************************
             * Surface note (demo-only): Missing timeout could hang forever
             ***********************************************************************/
            if (hw.i_interlock > INTERLOCK_CURRENT_VERIFY_MIN && 
                hw.i_interlock < INTERLOCK_CURRENT_VERIFY_MAX) {
                hw.state = STATE_CHECK_INPUT_VOLTAGE;
            } else {
                // Not in range - no error handling in original code!
                stats.timing_violations++;
            }
            break;
            
        case STATE_CHECK_INPUT_VOLTAGE:
            /***********************************************************************
             * Surface note (demo-only): IIR filter with attacker-controlled VIN
             * Malformed voltage readings could bypass checks
             ***********************************************************************/
            if (hw.vin > INPUT_VOLTAGE_MIN && hw.vin < INPUT_VOLTAGE_MAX) {
                hw.delay_counter++;
            } else {
                hw.delay_counter = 0;
            }
            
            if (hw.delay_counter > 10) {
                hw.state = STATE_ENABLE_HOTSWAP;
                hw.delay_counter = 0;
            }
            
            // IIR filter: vin_before_turn_on = 0.5*vin + 0.5*vin_before_turn_on
            hw.vin_before_turn_on = 0.5f * hw.vin + 0.5f * hw.vin_before_turn_on;
            break;
            
        case STATE_ENABLE_HOTSWAP:
            hw.hotswap_pos_ctrl_en = 1;
            hw.state = STATE_CHECK_PGOOD;
            break;
            
        case STATE_CHECK_PGOOD:
            /***********************************************************************
             * Surface note (demo-only): Missing timeout if PGOOD never asserts
             ***********************************************************************/
            if (hw.hotswap_pgood == 1) {
                hw.state = STATE_ENABLE_PRECHARGE;
            } else {
                stats.timing_violations++;
            }
            break;
            
        case STATE_ENABLE_PRECHARGE:
            hw.en_12v_precharge = 1;
            hw.state = STATE_VERIFY_PRECHARGE;
            break;
            
        case STATE_VERIFY_PRECHARGE:
            /***********************************************************************
             * Surface note (demo-only): Hardcoded voltage threshold
             * What if OUTPUT_VOLTAGE_MIN - 0.5 < 0?
             ***********************************************************************/
            if (hw.vout > (OUTPUT_VOLTAGE_MIN - 0.5f)) {
                hw.state = STATE_ENABLE_VDRV;
            } else {
                // Could hang forever - no timeout!
                stats.timing_violations++;
            }
            break;
            
        case STATE_ENABLE_VDRV:
            hw.mcu_en_vdrv_a = 1;
            hw.mcu_en_vdrv_b = 1;
            
            /***********************************************************************
             * GPIO CONFLICT CHECK: Are both VDRV and DISCHARGE on?
             ***********************************************************************/
            if (hw.en_discharge_ctrl_n == 1 && hw.mcu_en_vdrv_a == 1) {
                stats.gpio_conflicts++;
                // This would damage hardware!
            }
            
            hw.state = STATE_CHECK_VDRV;
            break;
            
        case STATE_RUN:
            // Normal operation - monitor for faults
            if (hw.vout < OUTPUT_VOLTAGE_MIN || hw.vout > OUTPUT_VOLTAGE_MAX) {
                stats.unsafe_voltage_conditions++;
                hw.state = STATE_POWERDOWN_INIT;
            }
            break;
            
        case STATE_POWERDOWN_INIT:
            // Start shutdown sequence
            hw.state = STATE_DISABLE_SEC_MOSFET;
            break;
            
        default:
            // Unknown state - should never happen
            stats.invalid_transitions++;
            hw.state = STATE_ERROR;
            break;
    }
    
    /***************************************************************************
     * TRANSITION VALIDATION
     **************************************************************************/
    if (prev_state < 101 && hw.state < 101) {
        if (!valid_transitions[prev_state][hw.state]) {
            // Invalid transition detected!
            stats.invalid_transitions++;
            
            #ifdef STRICT_TRANSITIONS
            hw.state = STATE_ERROR;
            return -2;
            #endif
        }
    }
    
    return 0;
}

/*******************************************************************************
 * Scenario events (thesis-critical)
 ******************************************************************************/
static void _emit_scenario(const char* scenario_id) {
    const char* dir = getenv("THESIS_ARTIFACTS_DIR");
    if (!dir || !*dir) {
        return;
    }
    char path[1024];
    snprintf(path, sizeof(path), "%s/scenario_events.log", dir);
    FILE* f = fopen(path, "a");
    if (!f) {
        return;
    }
    fprintf(f, "SCENARIO %s\n", scenario_id);
    fclose(f);
}

/*******************************************************************************
 * Run Multiple State Machine Steps (multi-sequence framing v1)
 *
 * Input framing: [u16_le len][len bytes payload] ... ; len==0 stops.
 * Each frame sets/perturbs inputs and advances the state machine without reset.
 ******************************************************************************/
int run_state_sequence(const uint8_t* data, size_t len) {
    size_t pos = 0;
    int total_steps = 0;

    while (pos + 2 <= len) {
        uint16_t flen = (uint16_t)data[pos] | ((uint16_t)data[pos + 1] << 8);
        pos += 2;
        if (flen == 0) {
            break;
        }
        if (pos + flen > len) {
            break;
        }

        const uint8_t* frame = &data[pos];
        pos += flen;

        if (flen < 1) {
            continue;
        }

        uint8_t op = frame[0];
        const uint8_t* fdata = frame + 1;
        size_t flen2 = flen - 1;

        switch (op % 6) {
            case 0:
                // Initialize from bytes (re-using existing parser)
                parse_fuzz_input(fdata, flen2);
                _emit_scenario("startup");
                break;
            case 1:
                // Perturb ADC readings deterministically
                if (flen2 >= 1) {
                    uint8_t modifier = fdata[0];
                    hw.vin += ((float)(modifier & 0x0F) - 8.0f) * 0.5f;
                    hw.vout += ((float)((modifier >> 4) & 0x0F) - 8.0f) * 0.1f;
                    hw.i_interlock = (float)(modifier & 0x1F) / 100.0f;
                    hw.hotswap_pgood = (modifier >> 7) & 1;
                }
                break;
            case 2:
                // Force a fault-like condition proxy (unsafe voltage)
                hw.vout = OUTPUT_VOLTAGE_MAX + 10.0f;
                _emit_scenario("fault");
                break;
            case 3:
                // Clear/normalize condition
                hw.vout = OUTPUT_VOLTAGE_TARGET;
                break;
            case 4:
                // Run multiple state machine steps
                {
                    int k = 1;
                    if (flen2 >= 1) {
                        k = 1 + (fdata[0] % 10);
                    }
                    for (int i = 0; i < k; i++) {
                        (void)run_state_machine_step();
                        total_steps++;
                    }
                }
                break;
            case 5:
                // Directly nudge state
                if (flen2 >= 1) {
                    uint8_t st = fdata[0];
                    hw.state = st % 101;
                }
                break;
        }

        // Always advance at least one step per frame to preserve ordering semantics
        if (op % 6 != 4) {
            (void)run_state_machine_step();
            total_steps++;
        }

        if (hw.state == STATE_RUN) {
            _emit_scenario("startup");
        }
        if (hw.state == STATE_ERROR) {
            _emit_scenario("fault");
        }
    }

    return total_steps;
}

/*******************************************************************************
 * AFL++ Entry Point (Standard file-input mode)
 ******************************************************************************/
int main(int argc, char** argv) {
    uint8_t buf[1024];
    size_t len;
    
    if (argc < 2) {
        // Read from stdin for AFL++ stdin mode
        len = fread(buf, 1, sizeof(buf), stdin);
    } else {
        FILE* f = fopen(argv[1], "rb");
        if (!f) {
            perror("fopen");
            return 1;
        }
        len = fread(buf, 1, sizeof(buf), f);
        fclose(f);
    }
    
    // Reset hardware state
    hw_init();
    memset(&stats, 0, sizeof(stats));

    // If set, write scenario_events.log under this directory.
    // The CLI sets this to results/<run_id>/artifacts.
    // NOTE: AFL++ executes the harness; we rely on env propagation.

    if (len > 0 && len < 1024) {
        run_state_sequence(buf, len);
    }
    
    return 0;
}
