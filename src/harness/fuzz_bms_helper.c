#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>

#include "targets/bms-firmware/include/helper.h"

// AFL++ persistent harness style: read from file path argv[1]
int main(int argc, char** argv)
{
    if (argc < 2) {
        return 0;
    }

    // Simple byte-oriented parsing: use input bytes to drive lookups.
    // This is not a protocol harness; it is a deterministic UUT harness
    // for Zephyr-free evaluation (Option C).
    FILE* f = fopen(argv[1], "rb");
    if (!f) {
        return 0;
    }
    uint8_t buf[256];
    size_t n = fread(buf, 1, sizeof(buf), f);
    fclose(f);

    if (n < 8) {
        return 0;
    }

    float a[8];
    float b[8];
    for (int i = 0; i < 8; i++) {
        a[i] = (float)buf[i];
        b[i] = (float)buf[i + 8];
    }

    // value_a derived from later bytes
    float value_a = (float)((buf[16] << 8) | buf[17]);

    (void)interpolate(a, b, 8, value_a);
    (void)byte2bitstr(buf[18]);
    (void)is_empty(buf, n);

    return 0;
}
