#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "filter_3p3z_df1_q23.h"

int main(int argc, char **argv)
{
    uint8_t buf[32];
    size_t len = fread(buf, 1, sizeof(buf), stdin);

    if (len < 6)
        return 0;

    int16_t in0;
    int16_t in1;

    memcpy(&in0, buf, sizeof(int16_t));
    memcpy(&in1, buf + sizeof(int16_t), sizeof(int16_t));

    filter_3p3z_context_df1_q23_t ctx;
    memset(&ctx, 0, sizeof(ctx));

    Filter3p3zInit_DF1_Q23(&ctx);

    int32_t out = 0;

    Filter3p3z_DF1_Q23_noinline(&ctx, in0, in1, &out);

    return 0;
}
