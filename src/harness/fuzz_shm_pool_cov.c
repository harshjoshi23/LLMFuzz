/*******************************************************************************
 * File: fuzz_shm_pool_cov.c
 *
 * Description:
 *   Coverage replay harness for fuzz_shm_pool.
 *   Reads one testcase from stdin (or file argument) and exercises the same
 *   logic as fuzz_shm_pool.c but WITHOUT AFL macros, so gcov .gcda files are
 *   produced normally.
 *
 *   Build with:
 *     gcc -O0 -g --coverage -fprofile-arcs -ftest-coverage \
 *       -I src/harness/stubs \
 *       -I third_party/mtb-mw-pctrl-svc/asset/shared_memory/include \
 *       -I third_party/mtb-mw-pctrl-svc/asset/shared_memory \
 *       -I third_party/mtb-mw-pctrl-svc/asset/shared_memory/source \
 *       -o build/coverage_gcov/svc_shm_pool/fuzz_shm_pool_cov \
 *       src/harness/fuzz_shm_pool_cov.c
 *
 *   Run with:
 *     ./build/coverage_gcov/svc_shm_pool/fuzz_shm_pool_cov < testcase
 *     # or
 *     ./build/coverage_gcov/svc_shm_pool/fuzz_shm_pool_cov testcase
 ******************************************************************************/

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>

/* ---- platform stubs (same as fuzz_shm_pool.c) ---- */
#ifndef __STATIC_INLINE
#define __STATIC_INLINE static inline
#endif
#ifndef CY_ALIGN
#define CY_ALIGN(x) __attribute__((aligned(x)))
#endif

/* ---- SVC pool config ---- */
#define CONFIG_SHARED_MEM_POOL_SIZE 4096
#define CONFIG_USE_MEMORY_POOL      1

/* ---- Include pool header + implementation directly (same as fuzz_shm_pool.c) ---- */
#include "cy_ppca_shm_pool.h"
#include "cy_ppca_shm_common.c"
#include "cy_ppca_shm_pool.c"

/* ---- helpers ---- */
static inline uint32_t rd_u32(const uint8_t *p)
{
    return (uint32_t)p[0]
         | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16)
         | ((uint32_t)p[3] << 24);
}

/* ---- read testcase from file or stdin ---- */
static unsigned char *read_input(const char *path, size_t *out_len)
{
    FILE *f = path ? fopen(path, "rb") : stdin;
    if (!f) { perror(path); return NULL; }

    unsigned char *buf = NULL;
    size_t cap = 0, len = 0;
    unsigned char tmp[4096];
    size_t n;
    while ((n = fread(tmp, 1, sizeof(tmp), f)) > 0) {
        if (len + n > cap) {
            cap = (len + n) * 2;
            buf = realloc(buf, cap);
        }
        memcpy(buf + len, tmp, n);
        len += n;
    }
    if (path) fclose(f);
    *out_len = len;
    return buf;
}

/* ---- main ---- */
int main(int argc, char **argv)
{
    const char *path = (argc > 1) ? argv[1] : NULL;
    size_t len = 0;
    unsigned char *buf = read_input(path, &len);

    if (!buf || len == 0) {
        /* nothing to do */
        free(buf);
        return 0;
    }

    /* Init pool */
    _shared_mem_pool_init();

    if (len < 4) {
        /* short input */
        free(buf);
        return 0;
    }

    /* Same fuzz logic as fuzz_shm_pool.c main() */
    const uint8_t *p = (const uint8_t *)buf;
    size_t remaining = len;
    void *ptrs[32];
    size_t ptr_count = 0;
    memset(ptrs, 0, sizeof(ptrs));

    while (remaining >= 4 && ptr_count < 32) {
        uint32_t raw = rd_u32(p);
        p += 4;
        remaining -= 4;

        uint32_t sz = raw & 0x7FF;
        void *m = _shared_mem_pool_malloc((size_t)sz);
        if (m) {
            size_t w = sz;
            if (w > 16) w = 16;
            if (w > 0)
                memset(m, (int)(raw & 0xFF), w);
            ptrs[ptr_count++] = m;
        }

        /* Occasionally free based on input bit */
        if ((raw & 0x80000000u) && ptr_count > 0) {
            void *q = ptrs[ptr_count - 1];
            _shared_mem_pool_free(q);
            ptrs[ptr_count - 1] = NULL;
            ptr_count--;
        }
    }

    /* Free remaining */
    for (size_t i = 0; i < ptr_count; i++) {
        if (ptrs[i])
            _shared_mem_pool_free(ptrs[i]);
    }

    free(buf);
    return 0;
}
