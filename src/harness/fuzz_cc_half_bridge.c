/*
 * AFL++ source-level harness for LibreSolar charge-controller: half_bridge PWM logic.
 *
 * UUT: targets/charge-controller-firmware/app/src/half_bridge.c
 * Why: has a UNIT_TEST implementation path with dummy registers and real arithmetic/clamp logic.
 *
 * Build defines:
 *   -DUNIT_TEST=1 -DBOARD_HAS_DCDC=1
 */

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Minimal Zephyr DT macros used at top of file.
// half_bridge.c includes board.h which uses DT_HAS_COMPAT_STATUS_OKAY().
#ifndef DT_HAS_COMPAT_STATUS_OKAY
#define DT_HAS_COMPAT_STATUS_OKAY(x) 1
#endif
#ifndef DT_DRV_COMPAT
#define DT_DRV_COMPAT half_bridge
#endif
#ifndef DT_REG_ADDR
#define DT_REG_ADDR(x) 0
#endif
#ifndef DT_PARENT
#define DT_PARENT(x) 0
#endif
#ifndef DT_DRV_INST
#define DT_DRV_INST(x) 0
#endif

// Provide stubs for headers included by half_bridge.c
// (board.h / mcu.h are used for board-level constants; UNIT_TEST branch doesn't use them.)

// Include the real target code directly
#include "../../targets/charge-controller-firmware/app/src/half_bridge.c"

static uint32_t rd_u32(const uint8_t *p) {
    return ((uint32_t)p[0]) | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

int main(int argc, char **argv) {
    if (argc < 2) return 0;
    const char *path = argv[1];
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    uint8_t buf[64];
    size_t n = fread(buf, 1, sizeof(buf), f);
    fclose(f);
    if (n < 16) return 0;

    int freq_kHz = (int)(rd_u32(buf + 0) % 200) + 1;          // 1..200
    int deadtime_ns = (int)(rd_u32(buf + 4) % 2000);          // 0..1999
    float min_duty = (float)(buf[8] % 100) / 100.0f;          // 0..0.99
    float max_duty = (float)(buf[9] % 100) / 100.0f;          // 0..0.99
    if (max_duty < min_duty) { float t=min_duty; min_duty=max_duty; max_duty=t; }

    half_bridge_init(freq_kHz, deadtime_ns, min_duty, max_duty);

    // drive a few duty updates
    for (int i = 0; i < 4; i++) {
        float duty = (float)(buf[10 + i] % 101) / 100.0f; // 0..1
        half_bridge_set_duty_cycle(duty);
        (void)half_bridge_get_duty_cycle();
        if (buf[14] & (1u << i)) {
            half_bridge_start();
        } else {
            half_bridge_stop();
        }
        (void)half_bridge_enabled();
    }

    return 0;
}
