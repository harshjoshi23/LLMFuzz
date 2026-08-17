/*******************************************************************************
 * File: fuzz_basic_sched.c
 *
 * Description:
 *   Host-side AFL++ fuzz harness for mtb-mw-pctrl-svc basic scheduler (SVCS).
 *
 * Target:
 *   third_party/mtb-mw-pctrl-svc/asset/svcs/source/basic_sched.c
 *
 * Approach:
 *   Decode fuzz bytes into a stream of scheduler operations:
 *   init, add tasks, enable/disable/kick, tick isr, dispatch.
 *
 * Notes:
 *   - Uses host stubs for cy_device/cy_sysint/cmsis.
 *   - Emits scenario evidence to $THESIS_ARTIFACTS_DIR if set.
 *******************************************************************************/

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h> // read() for AFL++ __AFL_FUZZ_TESTCASE_LEN

#ifdef __AFL_LOOP
#define _HARNESS_UNDER_AFL 1
#else
#define _HARNESS_UNDER_AFL 0
#endif

#ifndef __AFL_INIT
#define __AFL_INIT() do {} while (0)
#endif
#ifndef __AFL_FUZZ_INIT
#define __AFL_FUZZ_INIT() do {} while (0)
#endif
#ifndef __AFL_FUZZ_TESTCASE_BUF
static unsigned char _dummy_buf[1];
#define __AFL_FUZZ_TESTCASE_BUF _dummy_buf
#endif
#ifndef __AFL_FUZZ_TESTCASE_LEN
#define __AFL_FUZZ_TESTCASE_LEN 0u
#endif
#ifndef __AFL_LOOP
#define __AFL_LOOP(x) 1
#endif

// Ensure our host-side stubs win include resolution.
// IMPORTANT: basic_sched.c does NOT include cy_utils.h, but uses MISRA macros.
// So we pass them via compiler -D flags (see build script/manifest).
#include "cmsis_compiler.h"
#include "cmsis_device_stubs.h"

#include "basic_sched.h"

static void write_scenario_event(const char *scenario_id) {
    const char *dir = getenv("THESIS_ARTIFACTS_DIR");
    if (!dir || !*dir) return;

    char path[1024];
    snprintf(path, sizeof(path), "%s/scenario_events.log", dir);
    FILE *f = fopen(path, "a");
    if (!f) return;

    fprintf(f, "SCENARIO %s\n", scenario_id);
    fclose(f);
}

static uint8_t rd_u8(const uint8_t **p, size_t *n) {
    if (*n == 0) return 0;
    uint8_t v = **p;
    (*p)++;
    (*n)--;
    return v;
}

static uint32_t rd_u32(const uint8_t **p, size_t *n) {
    uint32_t v = 0;
    for (int i = 0; i < 4; i++) {
        v |= ((uint32_t)rd_u8(p, n)) << (8 * i);
    }
    return v;
}

static void task_fn(void *arg) {
    // Cheap side effect to keep compiler from optimizing away task execution.
    volatile uint32_t *x = (volatile uint32_t *)arg;
    if (x) *x = (*x) + 1u;
}

int main(int argc, char **argv) {
    (void)argc; (void)argv;

    __AFL_INIT();
    __AFL_FUZZ_INIT();

    volatile uint32_t task_counters[SVC_SCHED_MAX_TASKS];
    for (size_t i = 0; i < SVC_SCHED_MAX_TASKS; i++) task_counters[i] = 0;

#if _HARNESS_UNDER_AFL
    while (__AFL_LOOP(1000)) {
#else
    for (int once = 0; once < 1; once++) {
#endif
        const uint8_t *p = (const uint8_t *)__AFL_FUZZ_TESTCASE_BUF;
        size_t n = (size_t)__AFL_FUZZ_TESTCASE_LEN;

        if (n < 1) {
            write_scenario_event("short_input");
            continue;
        }

        // Op stream. Each op starts with an opcode byte.
        // 0x00: init(tick_hz=u32)
        // 0x01: add_periodic(period_ticks=u32, prio=u8)
        // 0x02: add_oneshot(delay_ticks=u32, prio=u8)
        // 0x03: enable(task_id=u8)
        // 0x04: disable(task_id=u8)
        // 0x05: kick(task_id=u8)
        // 0x06: tick_isr(reps=u8)
        // 0x07: dispatch(reps=u8)
        // 0x08: ms_to_ticks(ms=u32)
        // 0x09: us_to_ticks(us=u32)

        for (int opcount = 0; opcount < 64 && n > 0; opcount++) {
            uint8_t op = rd_u8(&p, &n);

            switch (op) {
                case 0: {
                    uint32_t tick_hz = rd_u32(&p, &n);
                    // Keep reasonable to avoid long loops.
                    tick_hz = (tick_hz % 100000u) + 1u;
                    bool ok = svc_sched_init(tick_hz);
                    write_scenario_event(ok ? "sched_init_ok" : "sched_init_fail");
                    break;
                }
                case 1: {
                    uint32_t period = rd_u32(&p, &n);
                    uint8_t prio = rd_u8(&p, &n);
                    period = (period % 10000u) + 1u;
                    svc_task_id_t id = svc_sched_add_periodic_ticks(task_fn, (void *)&task_counters[prio % SVC_SCHED_MAX_TASKS], period, prio);
                    write_scenario_event((id >= 0) ? "add_periodic_ok" : "add_periodic_fail");
                    break;
                }
                case 2: {
                    uint32_t delay = rd_u32(&p, &n);
                    uint8_t prio = rd_u8(&p, &n);
                    delay = (delay % 10000u) + 1u;
                    svc_task_id_t id = svc_sched_add_oneshot_ticks(task_fn, (void *)&task_counters[prio % SVC_SCHED_MAX_TASKS], delay, prio);
                    write_scenario_event((id >= 0) ? "add_oneshot_ok" : "add_oneshot_fail");
                    break;
                }
                case 3: {
                    uint8_t id = rd_u8(&p, &n);
                    svc_sched_enable((svc_task_id_t)(id % SVC_SCHED_MAX_TASKS));
                    write_scenario_event("enable");
                    break;
                }
                case 4: {
                    uint8_t id = rd_u8(&p, &n);
                    svc_sched_disable((svc_task_id_t)(id % SVC_SCHED_MAX_TASKS));
                    write_scenario_event("disable");
                    break;
                }
                case 5: {
                    uint8_t id = rd_u8(&p, &n);
                    svc_sched_kick((svc_task_id_t)(id % SVC_SCHED_MAX_TASKS));
                    write_scenario_event("kick");
                    break;
                }
                case 6: {
                    uint8_t reps = rd_u8(&p, &n);
                    reps = (uint8_t)(reps % 32u);
                    for (uint8_t i = 0; i < reps; i++) svc_sched_tick_isr();
                    write_scenario_event("tick");
                    break;
                }
                case 7: {
                    uint8_t reps = rd_u8(&p, &n);
                    reps = (uint8_t)(reps % 32u);
                    for (uint8_t i = 0; i < reps; i++) svc_sched_dispatch();
                    write_scenario_event("dispatch");
                    break;
                }
                case 8: {
                    uint32_t ms = rd_u32(&p, &n);
                    (void)svc_sched_ms_to_ticks(ms);
                    write_scenario_event("ms_to_ticks");
                    break;
                }
                case 9: {
                    uint32_t us = rd_u32(&p, &n);
                    (void)svc_sched_us_to_ticks(us);
                    write_scenario_event("us_to_ticks");
                    write_scenario_event("us_to_ticks");
                    break;
                }
                default:
                    // Ignore unknown opcodes to keep the harness robust.
                    write_scenario_event("unknown_op");
                    break;
            }
        }

        write_scenario_event("iter_done");
    }

    return 0;
}
