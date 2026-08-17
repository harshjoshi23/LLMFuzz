/*******************************************************************************
 * Baseline fuzz target to validate AFL setup can reach high coverage.
 *
 * This is NOT SVC-specific. It is a controlled target with many input-dependent
 * branches so we can confirm that AFL + instrumentation + environment is healthy.
 *
 * Build:
 *   afl-clang-fast -O2 -o build/baseline/fuzz_baseline src/harness/fuzz_baseline.c
 *
 * Run:
 *   afl-fuzz -D -p explore -i seeds/baseline -o results/afl_sessions/baseline -- build/baseline/fuzz_baseline @@
 *******************************************************************************/

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

static uint32_t h32(const uint8_t *p, size_t n) {
    uint32_t h = 2166136261u;
    for (size_t i = 0; i < n; i++) {
        h ^= p[i];
        h *= 16777619u;
    }
    return h;
}

static int parse_u32le(const uint8_t *p, size_t n, size_t off, uint32_t *out) {
    if (off + 4 > n) return 0;
    *out = (uint32_t)p[off] | ((uint32_t)p[off + 1] << 8) | ((uint32_t)p[off + 2] << 16) | ((uint32_t)p[off + 3] << 24);
    return 1;
}

int main(int argc, char **argv) {
    (void)argc;

    if (!argv[1]) return 0;
    FILE *f = fopen(argv[1], "rb");
    if (!f) return 0;

    uint8_t buf[4096];
    size_t n = fread(buf, 1, sizeof(buf), f);
    fclose(f);

    // Many small, independent branches.
    if (n > 0 && buf[0] == 'A') {
        if (n > 1 && buf[1] == 'F') {
            if (n > 2 && buf[2] == 'L') {
                if (n > 3 && buf[3] == '+') {
                    if (n > 4 && buf[4] == '+') {
                        volatile int hit = 1;
                        (void)hit;
                    }
                }
            }
        }
    }

    // Structured branch set based on opcode stream.
    uint32_t acc = 0;
    for (size_t i = 0; i + 5 <= n && i < 256; i += 5) {
        uint8_t op = buf[i];
        uint32_t arg = 0;
        (void)parse_u32le(buf, n, i + 1, &arg);

        switch (op % 8) {
            case 0: acc ^= (arg + 0x11111111u); break;
            case 1: acc += (arg ^ 0x22222222u); break;
            case 2: acc = (acc << 1) | (acc >> 31); break;
            case 3: acc -= (arg | 0x33333333u); break;
            case 4: acc *= (arg % 17u) + 1u; break;
            case 5: acc ^= h32(buf, n) ^ arg; break;
            case 6: acc += (uint32_t)memcmp(buf, "HELLO", (n >= 5) ? 5 : n); break;
            case 7: acc ^= (uint32_t)n; break;
        }

        // Deep nested thresholds
        if ((acc & 0xFFu) == 0x42u) {
            if ((acc & 0xFF00u) == 0xAB00u) {
                if ((acc % 1337u) == 0u) {
                    volatile int deep = 7;
                    (void)deep;
                }
            }
        }
    }

    // Final hash-trigger branches.
    uint32_t hh = h32(buf, n);
    if ((hh & 0xFFFFu) == 0xBEEFu) {
        if (n > 32 && memmem(buf, n, "MAGIC", 5) != NULL) {
            volatile int hit2 = 2;
            (void)hit2;
        }
    }

    return 0;
}
