/*
 * fuzz_svcs.c
 *
 * AFL++ fuzz harness for mtb-mw-pctrl-svc asset/svcs modules:
 *   - basic scheduler (basic_sched.c)
 *   - stack monitor (stack_mon.c)
 *   - ppca watchdog (ppca_wdt.c)
 *   - dwt profiling (dwt_profiling.c)
 *
 * This is a HOST-SIDE harness.
 * It uses lightweight stubs for PDL/IRQ functions under src/harness/stubs.
 *
 * Input modes:
 *   - AFL:  reads from stdin (afl-fuzz default)
 *   - gcov: reads from argv[1] file (for corpus replay coverage)
 */

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

// Optional scenario telemetry:
// If THESIS_SCENARIO_LOG is set, append one-line events to that path.
static FILE* g_scenario_fp = NULL;
static void scenario_log(const char* ev) {
    const char* path = getenv("THESIS_SCENARIO_LOG");
    if (!path || !*path) return;
    if (!g_scenario_fp) {
        g_scenario_fp = fopen(path, "a");
        if (!g_scenario_fp) return;
        setvbuf(g_scenario_fp, NULL, _IOLBF, 0);
    }
    fprintf(g_scenario_fp, "%s\n", ev);
}

#ifdef __AFL_LOOP
  // real AFL
#else
  #define __AFL_LOOP(x) (1)
#endif

#ifndef __AFL_INIT
  #define __AFL_INIT() do {} while (0)
#endif

#define MAX_INPUT (4096)

static uint8_t* g_buf;

static uint32_t rd_u32(const uint8_t* p) {
    return ((uint32_t)p[0]) | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

// Minimal task fn used by scheduler.
static void task_fn(void* arg) { (void)arg; }

// ---- Include the SVC service sources directly for deterministic linking ----
// Provide host/compiler macros expected by vendor code.
#ifndef __ARMCC_VERSION
  // vendor stack_mon.c has branches for ARMCC/IAR; host builds fall in GCC branch
#endif

// basic_sched needs cy_device.h; we already have stub in src/harness/stubs
// Provide extra CMSIS device stubs for SysTick/NVIC symbols.
#include "cmsis_device_stubs.h"

#include "basic_sched.h"
#include "stack_mon.h"
#include "ppca_wdt.h"
#include "dwt_profiling.h"

// Pull in implementations (compile as part of harness TU)
#include "basic_sched.c"
#include "stack_mon.c"
#include "ppca_wdt.c"
#include "dwt_profiling.c"

// Provide missing linker symbols expected by stack_mon.h
unsigned int __INITIAL_SP = 0;
unsigned int __STACK_LIMIT = 0;

// Provide ppca_wdt globals declared in ppca_wdt.h
volatile uint32_t CORE0_WATCH = 0;
volatile uint32_t CORE1_WATCH = 0;
volatile uint32_t PREV_CORE0_WATCH = 0;
volatile uint32_t PREV_CORE1_WATCH = 0;
volatile uint32_t WDT_RESET_STATUS = 0;
volatile uint32_t CORE0_WDT_RESET_COUNT = 0;
volatile uint32_t CORE1_WDT_RESET_COUNT = 0;

// Provide missing IRQ intrinsics used by stack_mon.c on host.
void __disable_irq(void) {}

/* ---------- file-based replay helper (for gcov / non-AFL runs) ---------- */
static unsigned char *_replay_buf = NULL;
static size_t         _replay_len = 0;

static void load_replay_file(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); exit(1); }
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    rewind(f);
    if (sz <= 0) { fclose(f); return; }
    _replay_buf = (unsigned char *)malloc((size_t)sz);
    if (!_replay_buf) { fclose(f); return; }
    _replay_len = fread(_replay_buf, 1, (size_t)sz, f);
    fclose(f);
}

int main(int argc, char **argv)
{
    /* If invoked with a file path, load it (gcov replay mode) */
    if (argc >= 2) {
        load_replay_file(argv[1]);
    }

    __AFL_INIT();

    g_buf = (uint8_t*)malloc(MAX_INPUT);
    if (!g_buf) return 1;

    while (__AFL_LOOP(1000)) {
        ssize_t n;
        if (_replay_buf) {
            /* gcov replay: copy file contents into g_buf */
            n = (ssize_t)(_replay_len > MAX_INPUT ? MAX_INPUT : _replay_len);
            memcpy(g_buf, _replay_buf, (size_t)n);
        } else {
            /* AFL mode: read from stdin */
            n = read(0, g_buf, MAX_INPUT);
        }
        if (n <= 0) break;

        const uint8_t* p = g_buf;
        size_t left = (size_t)n;

        // Command stream:
        //  [op:1][len:1][payload:len]...
        // ops:
        //  0x01: scheduler init
        //  0x02: add one-shot (ms)
        //  0x03: add periodic (ms)
        //  0x04: enable task
        //  0x05: disable task
        //  0x06: remove task
        //  0x07: scheduler run ticks (u32)
        //  0x10: stack_mon init
        //  0x11: stack_mon update
        //  0x20: wdt init
        //  0x21: wdt enable
        //  0x22: wdt reconfigure
        //  0x23: wdt handler
        //  0x24: wdt check reset reason
        //  0x25: wdt clear reset reason
        //  0x30: dwt start/stop using globals

        // stack region for stack monitor (we map STACK_TOP/STACK_LIMIT onto this)
        static uint32_t stack_region[256];
        static int stack_inited = 0;

        // Make stack_mon.h macros point to our host memory region.
        // stack_mon expects:
        //   STACK_LIMIT = &__STACK_LIMIT (bottom)
        //   STACK_TOP   = &__INITIAL_SP (top)
        __STACK_LIMIT = (unsigned int)(uintptr_t)&stack_region[0];
        __INITIAL_SP  = (unsigned int)(uintptr_t)&stack_region[(sizeof(stack_region)/sizeof(stack_region[0]))];

        // init stack fill word pattern
        if (!stack_inited) {
            for (size_t i = 0; i < (sizeof(stack_region)/sizeof(stack_region[0])); i++) {
                stack_region[i] = 0xA5A5A5A5u;
            }
            stack_inited = 1;
        }

        while (left >= 2) {
            uint8_t op = p[0];
            uint8_t len = p[1];
            p += 2; left -= 2;
            if (len > left) break;

            const uint8_t* payload = p;
            p += len; left -= len;

            switch (op) {
                case 0x01: {
                    scenario_log("sched_init_ok");
                    // 1kHz tick; SysTick_Config is stubbed on host
                    (void)svc_sched_init(1000u);
                    break;
                }
                case 0x02: {
                    if (len < 2) break;
                    scenario_log("add_oneshot_ok");
                    uint32_t ms = (uint32_t)payload[0] | ((uint32_t)payload[1] << 8);
                    (void)svc_sched_add_oneshot_ms(task_fn, NULL, ms, (uint8_t)(ms & 0xFF));
                    break;
                }
                case 0x03: {
                    if (len < 2) break;
                    scenario_log("add_periodic_ok");
                    uint32_t ms = (uint32_t)payload[0] | ((uint32_t)payload[1] << 8);
                    (void)svc_sched_add_periodic_ms(task_fn, NULL, ms, (uint8_t)(ms & 0xFF));
                    break;
                }
                case 0x04: {
                    if (len < 1) break;
                    svc_sched_enable((svc_task_id_t)payload[0]);
                    break;
                }
                case 0x05: {
                    if (len < 1) break;
                    svc_sched_disable((svc_task_id_t)payload[0]);
                    break;
                }
                case 0x06: {
                    if (len < 1) break;
                    // No explicit remove API in this version; disable instead.
                    svc_sched_disable((svc_task_id_t)payload[0]);
                    break;
                }
                case 0x07: {
                    if (len < 4) break;
                    scenario_log("tick");
                    scenario_log("dispatch");
                    uint32_t ticks = rd_u32(payload);
                    // clamp to keep runs bounded
                    ticks &= 0x3FFu;
                    for (uint32_t i = 0; i < ticks; i++) {
                        svc_sched_tick_isr();
                        svc_sched_dispatch();
                    }
                    break;
                }
                case 0x10: {
                    svc_stack_mon_init();
                    break;
                }
                case 0x11: {
                    (void)svc_stack_mon_update();
                    break;
                }
                case 0x20: {
                    // core0_us,u8 core0_mode, core1_us,u8 core1_mode
                    if (len < 10) break;
                    uint32_t c0 = rd_u32(&payload[0]);
                    uint32_t c1 = rd_u32(&payload[5]);
                    ppca_wdt_init(c0, (ppca_wdt_mode_t)payload[4], NULL, c1, (ppca_wdt_mode_t)payload[9], NULL);
                    break;
                }
                case 0x21: {
                    ppca_wdt_enable();
                    break;
                }
                case 0x22: {
                    if (len < 5) break;
                    cy_en_ppca_core_t core = (cy_en_ppca_core_t)(payload[0] & 1u);
                    uint32_t us = rd_u32(&payload[1]);
                    ppca_wdt_reconfigure(core, us);
                    break;
                }
                case 0x23: {
                    ppca_wdt_handler();
                    break;
                }
                case 0x24: {
                    (void)ppca_wdt_check_restart_reason();
                    break;
                }
                case 0x25: {
                    ppca_wdt_clear_restart_reason();
                    break;
                }
                case 0x30: {
                    // touch globals in dwt_profiling
                    dwt_start_count ^= 0x1234u;
                    dwt_stop_count ^= 0x5678u;
                    // exercise inline DWT profile functions (uses stubbed DWT/DCB regs)
                    svc_dwt_profile_init();
                    svc_dwt_profile_start();
                    svc_dwt_profile_stop();
                    svc_dwt_profile_reset_cyccnt();
                    (void)svc_dwt_profile_read();
                    break;
                }
                case 0x31: {
                    // kick a scheduler task (makes it immediately due)
                    if (len < 1) break;
                    svc_sched_kick((svc_task_id_t)payload[0]);
                    break;
                }
                case 0x32: {
                    // wdt reset (main-core side: checks WATCH counters)
                    ppca_wdt_reset();
                    break;
                }
                case 0x33: {
                    // exercise time-conversion helpers + stack total
                    if (len >= 4) {
                        uint32_t v = rd_u32(payload);
                        (void)svc_sched_ms_to_ticks(v);
                        (void)svc_sched_us_to_ticks(v);
                    }
                    (void)svc_stack_mon_get_total();
                    (void)svc_sched_now();
                    break;
                }
                case 0x34: {
                    // add periodic task in TICKS
                    if (len < 5) break;
                    uint32_t ticks = rd_u32(payload);
                    (void)svc_sched_add_periodic_ticks(task_fn, NULL, ticks, payload[4]);
                    break;
                }
                case 0x35: {
                    // add oneshot task in TICKS
                    if (len < 5) break;
                    uint32_t ticks = rd_u32(payload);
                    (void)svc_sched_add_oneshot_ticks(task_fn, NULL, ticks, payload[4]);
                    break;
                }
                default:
                    break;
            }
        }

        /* In file-replay mode, run exactly once */
        if (_replay_buf) break;
    }

    free(g_buf);
    return 0;
}
