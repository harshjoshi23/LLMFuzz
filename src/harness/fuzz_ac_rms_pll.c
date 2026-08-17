#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "ac_rms_pll_1ph.h"

int main(int argc, char **argv)
{
    uint8_t buf[32];
    size_t len = fread(buf, 1, sizeof(buf), stdin);

    if (len < sizeof(float) * 2)
        return 0;

    float alpha;
    float beta;

    memcpy(&alpha, buf, sizeof(float));
    memcpy(&beta, buf + sizeof(float), sizeof(float));

    ac_rms_pll_context_t ctx;
    memset(&ctx, 0, sizeof(ctx));

    AcRmsPllInit_1ph(&ctx);

    float rms = 0.0f;

    AcRmsPll_1ph_noinline(&ctx, alpha, beta, &rms);

    return 0;
}
