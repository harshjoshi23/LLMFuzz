/*******************************************************************************
 * File: fuzz_shm_tb.c
 *
 * AFL++ fuzz harness for mtb-mw-pctrl-svc shared memory triple buffer.
 *
 * Target sources:
 *   third_party/mtb-mw-pctrl-svc/asset/shared_memory/source/
 *     - cy_ppca_shm_common.c
 *     - cy_ppca_shm_pool.c
 *     - cy_ppca_shm_tb.c
 *
 * Entrypoints:
 *   - Cy_PPCA_SharedMem_TB_Init
 *   - Cy_PPCA_SharedMem_TB_GetWriteBuf
 *   - Cy_PPCA_SharedMem_TB_UpdateWriteBuf
 *   - Cy_PPCA_SharedMem_TB_GetReadBuf
 *
 * Harness model:
 *   - Command stream controlling init/write/update/read cycles.
 *   - Includes invalid sizes and odd operation ordering.
 *
 * Scenario evidence:
 *   Emits "SCENARIO <id>" lines to $THESIS_ARTIFACTS_DIR/scenario_events.log.
 *******************************************************************************/

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>  // read() for AFL++ stdin fuzzing macros

/* Detect whether we are running under real AFL instrumentation.
 * afl-clang-fast pre-defines __AFL_LOOP; plain gcc does not.
 * We check BEFORE providing our own fallback definitions.          */
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

#ifndef __STATIC_INLINE
#define __STATIC_INLINE static inline
#endif

#ifndef CY_ALIGN
#define CY_ALIGN(x) __attribute__((aligned(x)))
#endif

#ifndef __GNUC__
#define __GNUC__ 1
#endif

#ifndef CONFIG_USE_MEMORY_POOL
#define CONFIG_USE_MEMORY_POOL 1
#endif
#ifndef CONFIG_SHARED_MEM_POOL_SIZE
#define CONFIG_SHARED_MEM_POOL_SIZE 16384
#endif

#include "cy_ppca_shm_pool.h"
#include "cy_ppca_shm_tb.h"

// Include implementations directly for a single TU build.
#include "cy_ppca_shm_common.c"
#include "cy_ppca_shm_pool.c"
#include "cy_ppca_shm_tb.c"

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

static uint32_t rd_u32(const uint8_t *p) {
    return ((uint32_t)p[0]) | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

enum {
    OP_INIT   = 0x01,
    OP_WRITE  = 0x02,
    OP_UPDATE = 0x03,
    OP_READ   = 0x04,
    OP_RESET  = 0x05
};

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

int main(int argc, char **argv) {
    /* If a file argument is given, load it for offline replay (gcov coverage).
     * Otherwise, AFL macros provide the testcase buffer as usual.               */
    if (argc >= 2) {
        load_replay_file(argv[1]);
    }

    __AFL_INIT();
    __AFL_FUZZ_INIT();

    // Multi-instance TB blocks to increase state coverage.
    // Selecting different blocks helps hit more control-flow paths (e.g., new_data toggles).
    enum { TB_COUNT = 4 };
    CY_ALIGN(4) static volatile cy_ppca_shm_tb_blk_t tb_blks[TB_COUNT];
    CY_ALIGN(4) static uint32_t scratch[512];

    uint32_t cur_size[TB_COUNT] = {0};
    int initialized[TB_COUNT] = {0};

    // When running under AFL++ instrumentation, __AFL_LOOP() enables persistent
    // mode.  For gcovr replay (outside AFL), run exactly one iteration.
#if _HARNESS_UNDER_AFL
    while (__AFL_LOOP(1000)) {
#else
    for (int __replay_once = 0; __replay_once < 1; __replay_once++) {
#endif
        /* Use replay buffer if loaded from file, otherwise AFL shared mem */
        unsigned char *buf = _replay_buf ? _replay_buf : __AFL_FUZZ_TESTCASE_BUF;
        unsigned int   len = _replay_buf ? (unsigned int)_replay_len : __AFL_FUZZ_TESTCASE_LEN;

        memset((void *)tb_blks, 0, sizeof(tb_blks));
        memset((void *)scratch, 0, sizeof(scratch));
        memset((void *)cur_size, 0, sizeof(cur_size));
        memset((void *)initialized, 0, sizeof(initialized));
        _shared_mem_pool_init();
        write_scenario_event("tb_iter_start");

        if (len < 5) {
            write_scenario_event("tb_short_input");
            continue;
        }

        const uint8_t *p = (const uint8_t *)buf;
        size_t remaining = (size_t)len;

        while (remaining >= 5) {
            uint8_t op = *p++;
            uint32_t arg = rd_u32(p);
            p += 4;
            remaining -= 5;

            uint32_t idx = (arg >> 24) & 0x3u;
            volatile cy_ppca_shm_tb_blk_t *tb = &tb_blks[idx];

            switch (op) {
                case OP_INIT: {
                    uint32_t sz = (arg & 0x7FFu); // 0..2047
                    if ((arg & 0x80000000u) == 0) {
                        sz &= ~3u; // mostly aligned
                    }
                    if (sz == 0 && (arg & 0x10000u)) sz = 4;

                    Cy_PPCA_SharedMem_TB_Init(tb, sz);
                    initialized[idx] = 1;
                    cur_size[idx] = sz;
                    write_scenario_event((sz % 4 == 0) ? "tb_init_aligned" : "tb_init_unaligned");
                    break;
                }

                case OP_WRITE: {
                    if (!initialized[idx]) {
                        write_scenario_event("tb_write_before_init");
                        break;
                    }
                    void *w = Cy_PPCA_SharedMem_TB_GetWriteBuf(tb);
                    if (!w) {
                        write_scenario_event("tb_get_write_null");
                        break;
                    }

                    uint32_t sz = cur_size[idx];
                    if (sz == 0) {
                        write_scenario_event("tb_write_size0");
                        break;
                    }

                    // pattern fill
                    uint32_t pattern = arg;
                    for (size_t i = 0; i < (sizeof(scratch)/sizeof(scratch[0])); i++) {
                        scratch[i] = pattern ^ (uint32_t)i;
                    }

                    // Copy min(sz, scratch bytes)
                    size_t max_bytes = sizeof(scratch);
                    size_t use_bytes = sz;
                    if (use_bytes > max_bytes) use_bytes = max_bytes;

                    // occasionally write only part / overflow request intention (but we clamp to avoid OOB in harness)
                    if (arg & 0x40000000u) {
                        if (use_bytes >= 8) use_bytes -= 4;
                    }

                    memcpy(w, scratch, use_bytes);
                    write_scenario_event("tb_write_buf");
                    break;
                }

                case OP_UPDATE: {
                    if (!initialized[idx]) {
                        write_scenario_event("tb_update_before_init");
                        break;
                    }
                    Cy_PPCA_SharedMem_TB_UpdateWriteBuf(tb);
                    write_scenario_event("tb_update_write");
                    break;
                }

                case OP_READ: {
                    if (!initialized[idx]) {
                        write_scenario_event("tb_read_before_init");
                        break;
                    }
                    void *r = Cy_PPCA_SharedMem_TB_GetReadBuf(tb);
                    if (!r) {
                        write_scenario_event("tb_get_read_null");
                        break;
                    }

                    uint32_t sz = cur_size[idx];
                    if (sz == 0) {
                        write_scenario_event("tb_read_size0");
                        break;
                    }

                    size_t max_bytes = sizeof(scratch);
                    size_t use_bytes = sz;
                    if (use_bytes > max_bytes) use_bytes = max_bytes;
                    memcpy(scratch, r, use_bytes);
                    write_scenario_event("tb_read_buf");
                    break;
                }

                case OP_RESET: {
                    memset((void *)tb, 0, sizeof(*tb));
                    _shared_mem_pool_init();
                    initialized[idx] = 0;
                    cur_size[idx] = 0;
                    write_scenario_event("tb_reset");
                    break;
                }

                default:
                    write_scenario_event("tb_op_unknown");
                    break;
            }
        }

        write_scenario_event("tb_iter_done");
    }
#ifdef __AFL_LOOP
    /* end persistent loop */
#else
    /* end single-iteration replay loop */
#endif

    free(_replay_buf);
    return 0;
}
