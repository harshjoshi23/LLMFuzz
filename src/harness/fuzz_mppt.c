#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "mppt_pno.h"

// Simple AFL harness for MPPT algorithm

int main(int argc, char **argv)
{
    uint8_t buf[32];
    size_t len = fread(buf, 1, sizeof(buf), stdin);

    if (len < sizeof(float) * 2)
        return 0;

    float voltage;
    float current;
    memcpy(&voltage, buf, sizeof(float));
    memcpy(&current, buf + sizeof(float), sizeof(float));

    mppt_context_t ctx;
    memset(&ctx, 0, sizeof(ctx));

    MpptInit_pno(&ctx);

    float duty = 0.0f;

    Mppt_pno_noinline(&ctx, voltage, current, &duty);

    return 0;
}
