#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>

// Build the BMS state machine on host with a minimal shim.
#define HOST_FUZZ 1
#include "src/harness/targets/libresolar_bms/bms_host_shim.h"

// Pull in unit-under-test implementation directly (AFL-instrumented)
#include "targets/bms-firmware/app/src/bms_common.c"

static uint32_t rd_u32(const uint8_t *p) {
    return ((uint32_t)p[0]) | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

int main(int argc, char **argv) {
    (void)argc; (void)argv;

    // AFL++ persistent mode; if not present, just run once on stdin.
    #ifdef __AFL_INIT
    __AFL_INIT();
    #endif

    while (1) {
        uint8_t buf[256];
        size_t n = fread(buf, 1, sizeof(buf), stdin);
        if (n == 0) break;

        struct bms_context bms;
        memset(&bms, 0, sizeof(bms));
        bms_init_config(&bms, (enum bms_cell_type)(buf[2] % 3), 10.0f);

        bms.state = (enum bms_state)(buf[0] % 5);
        bms.chg_enable = (buf[1] & 1) != 0;
        bms.dis_enable = (buf[1] & 2) != 0;

        bms.ic_data.error_flags = rd_u32(buf + 4);
        bms.ic_data.cell_voltage_avg = (float)(rd_u32(buf + 8) % 5000) / 1000.0f;
        bms.ic_data.current = (float)((int32_t)(rd_u32(buf + 12) % 10001) - 5000) / 1000.0f;

        // Drive the UUT
        bms_state_machine(&bms);
        bms_state_machine(&bms);
    }

    return 0;
}
