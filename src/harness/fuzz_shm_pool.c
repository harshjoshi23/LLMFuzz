/*******************************************************************************
 * File: fuzz_shm_pool.c
 *
 * Description:
 *   AFL++ fuzz harness for mtb-mw-pctrl-svc shared memory pool allocator.
 *
 * Target:
 *   third_party/mtb-mw-pctrl-svc/asset/shared_memory/source/cy_ppca_shm_pool.c
 *
 * Entrypoints:
 *   - _shared_mem_pool_init
 *   - _shared_mem_pool_malloc
 *   - _shared_mem_pool_free
 *
 * Notes:
 *   - This is a host-side harness (no hardware).
 *   - We include the SVC template config and pool sources directly to keep
 *     linking simple and deterministic.
 *   - Harness emits scenario evidence to $THESIS_ARTIFACTS_DIR if set.
 *******************************************************************************/

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>  // read() for AFL++ stdin fuzzing macros

// AFL++ persistent mode macros are provided by afl-cc via <command-line> defines.
// For non-AFL builds (unit smoke), provide minimal fallbacks.
// Detect real AFL BEFORE providing fallbacks.
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

// Provide minimal platform stubs required by shared_memory headers.
// The upstream code expects CMSIS + Cypress device headers when building for target.
// For this host-side fuzz harness, we stub only what is needed.
#ifndef __STATIC_INLINE
#define __STATIC_INLINE static inline
#endif

#ifndef CY_ALIGN
#define CY_ALIGN(x) __attribute__((aligned(x)))
#endif

#ifndef CY_SECTION
#define CY_SECTION(name) __attribute__((section(name)))
#endif

// Avoid toolchain gating in cy_ppca_shm_common.h (it errors on unknown toolchain).
#ifndef __GNUC__
#define __GNUC__ 1
#endif

// Provide the config macros used by the shared_memory library.
// We choose a deterministic configuration for the allocator fuzz target.
// NOTE: the allocator code is compiled only when CONFIG_USE_MEMORY_POOL is 1.
#ifndef CONFIG_USE_MEMORY_POOL
#define CONFIG_USE_MEMORY_POOL 1
#endif

#ifndef CONFIG_SHARED_MEM_POOL_SIZE
#define CONFIG_SHARED_MEM_POOL_SIZE 4096
#endif

// Prevent inclusion failures for target-only headers.
// We add a local include path (see build command) that provides:
// - cmsis_compiler.h, cy_device.h, cy_utils.h, cy_ppca_shm_config.h

#include "cy_ppca_shm_pool.h"

// Entrypoints in mtb-mw-pctrl-svc are `shm_pool_*` (no leading underscore).
// Declare explicitly to satisfy C99+ compilers.
void shm_pool_init(void);
void* shm_pool_malloc(size_t size);
void shm_pool_free(void* ptr);

// Include implementation directly (keeps build simple; no separate lib build needed).
// We need both common.c (defines shared_mem_pool buffer) and pool.c (allocator).
#include "cy_ppca_shm_common.c"
#include "cy_ppca_shm_pool.c"

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
    if (argc >= 2) {
        load_replay_file(argv[1]);
    }

    __AFL_INIT();

    // Init pool once per process (allocator maintains static free list).
    shm_pool_init();
    write_scenario_event("shm_pool_init");

    __AFL_FUZZ_INIT();

#if _HARNESS_UNDER_AFL
    while (__AFL_LOOP(1000)) {
#else
    for (int __replay_once = 0; __replay_once < 1; __replay_once++) {
#endif
        unsigned char *buf = _replay_buf ? _replay_buf : __AFL_FUZZ_TESTCASE_BUF;
        unsigned int   len = _replay_buf ? (unsigned int)_replay_len : __AFL_FUZZ_TESTCASE_LEN;

        if (len < 4) {
            write_scenario_event("short_input");
            continue;
        }

        // Fuzz a simple sequence of allocations/frees.
        // Interpret the input as a stream of 4-byte sizes.
        const uint8_t *p = (const uint8_t *)buf;
        size_t remaining = (size_t)len;

        void *ptrs[32];
        size_t ptr_count = 0;
        memset(ptrs, 0, sizeof(ptrs));

        while (remaining >= 4 && ptr_count < 32) {
            uint32_t raw = rd_u32(p);
            p += 4;
            remaining -= 4;

            // Map to a size range (0..2048). Some 0 sizes exercise edge cases.
            uint32_t sz = raw & 0x7FF;

            void *m = shm_pool_malloc((size_t)sz);
            if (m) {
                write_scenario_event("alloc_ok");

                // Optionally touch memory to exercise block layout assumptions.
                // Only write a small prefix to avoid OOB on small allocations.
                size_t w = sz;
                if (w > 16) w = 16;
                if (w > 0) {
                    memset(m, (int)(raw & 0xFF), w);
                }

                ptrs[ptr_count++] = m;
            } else {
                write_scenario_event("alloc_null");
            }

            // Occasionally free immediately based on one input bit.
            if ((raw & 0x80000000u) && ptr_count > 0) {
                void *q = ptrs[ptr_count - 1];
                shm_pool_free(q);
                write_scenario_event("free_ok");
                ptrs[ptr_count - 1] = NULL;
                ptr_count--;
            }
        }

        // Free anything still allocated.
        for (size_t i = 0; i < ptr_count; i++) {
            if (ptrs[i]) {
                shm_pool_free(ptrs[i]);
                write_scenario_event("free_ok");
            }
        }

        write_scenario_event("iter_done");
    }

    free(_replay_buf);
    return 0;
}
