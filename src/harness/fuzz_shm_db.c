/*******************************************************************************
 * File: fuzz_shm_db.c
 *
 * AFL++ fuzz harness for mtb-mw-pctrl-svc shared memory double buffer.
 *
 * Target sources:
 *   third_party/mtb-mw-pctrl-svc/asset/shared_memory/source/
 *     - cy_ppca_shm_common.c
 *     - cy_ppca_shm_pool.c
 *     - cy_ppca_shm_db.c
 *
 * Entrypoints:
 *   - Cy_PPCA_SharedMem_DB_Init
 *   - Cy_PPCA_SharedMem_DB_Write
 *   - Cy_PPCA_SharedMem_DB_Read
 *
 * Harness model:
 *   - Command stream operating on a single DB block.
 *   - Exercises size alignment, write/read, flag flipping, and pool behavior.
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

// Force pool-backed configuration so DB init allocates buffers.
#ifndef CONFIG_USE_MEMORY_POOL
#define CONFIG_USE_MEMORY_POOL 1
#endif
#ifndef CONFIG_SHARED_MEM_POOL_SIZE
#define CONFIG_SHARED_MEM_POOL_SIZE 8192
#endif

#include "cy_ppca_shm_pool.h"
#include "cy_ppca_shm_db.h"

// Include implementations directly for a single TU build.
#include "cy_ppca_shm_common.c"
#include "cy_ppca_shm_pool.c"
#include "cy_ppca_shm_db.c"

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

// Opcodes
enum {
    OP_INIT  = 0x01,
    OP_WRITE = 0x02,
    OP_READ  = 0x03,
    OP_RESET = 0x04,
    OP_CORRUPT_FLAG = 0x05,
    OP_MULTI_INIT = 0x06
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

    // Shared objects.
    // Use multiple blocks to increase statefulness / branching.
    CY_ALIGN(4) static volatile cy_ppca_shm_db_blk_t db_blks[4];
    CY_ALIGN(4) static uint32_t scratch[256];

    // State
    uint32_t cur_size[4] = {0};
    uint8_t initialized[4] = {0};

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

        // Start each testcase from a clean-ish state.
        for (int i = 0; i < 4; i++) {
            initialized[i] = 0;
            cur_size[i] = 0;
            memset((void *)&db_blks[i], 0, sizeof(db_blks[i]));
        }
        memset((void *)scratch, 0, sizeof(scratch));
        _shared_mem_pool_init();
        write_scenario_event("db_iter_start");

        if (len < 5) {
            write_scenario_event("db_short_input");
            continue;
        }

        const uint8_t *p = (const uint8_t *)buf;
        size_t remaining = (size_t)len;

        // Consume command stream: [op][arg32]...
        while (remaining >= 5) {
            uint8_t op = *p++;
            uint32_t arg = rd_u32(p);
            p += 4;
            remaining -= 5;

            // Choose which DB block to act on.
            int bi = (int)((arg >> 29) & 0x3u);  // 0..3
            volatile cy_ppca_shm_db_blk_t *db_blk = &db_blks[bi];

            switch (op) {
                case OP_INIT: {
                    // Size must be multiple of 4. Deliberately allow non-multiple to test behavior.
                    uint32_t sz = (arg & 0x3FFu); // 0..1023
                    if ((arg & 0x80000000u) == 0) {
                        sz &= ~3u; // mostly aligned
                    }
                    // Avoid zero-size init too often; but still allow it sometimes.
                    if (sz == 0 && (arg & 0x10000u)) sz = 4;

                    Cy_PPCA_SharedMem_DB_Init(db_blk, sz);
                    cur_size[bi] = sz;
                    initialized[bi] = 1;
                    write_scenario_event((sz % 4 == 0) ? "db_init_aligned" : "db_init_unaligned");
                    break;
                }

                case OP_WRITE: {
                    if (!initialized[bi]) {
                        write_scenario_event("db_write_before_init");
                        break;
                    }

                    uint32_t sz = cur_size[bi];
                    if (sz == 0) {
                        write_scenario_event("db_write_size0");
                        break;
                    }

                    // Fill scratch with attacker-controlled pattern.
                    uint32_t pattern = arg;
                    for (size_t i = 0; i < (sizeof(scratch)/sizeof(scratch[0])); i++) {
                        scratch[i] = pattern + (uint32_t)i;
                    }

                    // Sometimes request a wrong size to exercise boundary behavior.
                    uint32_t use_sz = sz;
                    if (arg & 0x40000000u) {
                        use_sz = (sz >= 8) ? (sz - 4) : sz;
                    }
                    if (arg & 0x20000000u) {
                        use_sz = sz + 4;
                    }

                    Cy_PPCA_SharedMem_DB_Write(db_blk, scratch, use_sz);
                    write_scenario_event((use_sz == sz) ? "db_write_ok" : "db_write_size_mismatch");
                    break;
                }

                case OP_READ: {
                    if (!initialized[bi]) {
                        write_scenario_event("db_read_before_init");
                        break;
                    }

                    uint32_t sz = cur_size[bi];
                    if (sz == 0) {
                        write_scenario_event("db_read_size0");
                        break;
                    }

                    // Read back into scratch.
                    uint32_t use_sz = sz;
                    if (arg & 0x1) {
                        use_sz = (sz >= 8) ? (sz - 4) : sz;
                    }

                    Cy_PPCA_SharedMem_DB_Read(db_blk, scratch, use_sz);
                    write_scenario_event((use_sz == sz) ? "db_read_ok" : "db_read_size_mismatch");
                    break;
                }

                case OP_RESET: {
                    // Re-init pool and zero blocks to explore lifecycle.
                    for (int i = 0; i < 4; i++) {
                        memset((void *)&db_blks[i], 0, sizeof(db_blks[i]));
                        initialized[i] = 0;
                        cur_size[i] = 0;
                    }
                    _shared_mem_pool_init();
                    write_scenario_event("db_reset");
                    break;
                }

                case OP_CORRUPT_FLAG: {
                    if (!initialized[bi]) {
                        write_scenario_event("db_corrupt_before_init");
                        break;
                    }
                    // Flip / set arbitrary bits in the buf_flag to force alternate branches.
                    uint32_t *flagp = (uint32_t *)&db_blk->flag;
                    uint32_t v = *flagp;
                    if (arg & 1u) v ^= 1u;
                    if (arg & 2u) v ^= 0x80000000u;
                    if (arg & 4u) v = arg;  // occasionally smash
                    *flagp = v;
                    write_scenario_event("db_corrupt_flag");
                    break;
                }

                case OP_MULTI_INIT: {
                    // Re-init the selected block with a new size without clearing others.
                    uint32_t sz = (arg & 0x3FFu);
                    if ((arg & 0x80000000u) == 0) sz &= ~3u;
                    if (sz == 0) sz = 4;
                    Cy_PPCA_SharedMem_DB_Init(db_blk, sz);
                    cur_size[bi] = sz;
                    initialized[bi] = 1;
                    write_scenario_event("db_multi_init");
                    break;
                }

                default:
                    write_scenario_event("db_op_unknown");
                    break;
            }
        }

        write_scenario_event("db_iter_done");
    }
#ifdef __AFL_LOOP
    /* end persistent loop */
#else
    /* end single-iteration replay loop */
#endif

    free(_replay_buf);
    return 0;
}
