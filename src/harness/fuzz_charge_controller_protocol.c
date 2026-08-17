// Persistent AFL++ harness for LibreSolar charge controller — MPPT register surface.
//
// Input format (TLV stream):
//   buf[0]      = N (number of frames, capped at 32)
//   then repeating: [len_byte][len_byte bytes of frame]
//
// Each frame: [reg_addr, op, data...]
//   op=0 READ (2 bytes minimum), op=1 WRITE (3+ bytes depending on register).
// The dispatch in firmware_adapters.c covers 25 registers across 5 groups:
//   battery charging, MPPT, load output, status telemetry, calibration.

#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>

#define MAX_INPUT 4096

extern int charge_controller_process_i2c(uint8_t *data, size_t len);

int main(void) {

    static uint8_t buf[MAX_INPUT];

    while (__AFL_LOOP(1000)) {

        ssize_t total = read(0, buf, sizeof(buf));
        if (total <= 1) continue;

        size_t n = (buf[0] % 32);
        if (n == 0) n = 1;

        size_t off = 1;
        for (size_t i = 0; i < n; i++) {
            if (off >= (size_t)total) break;
            size_t plen = buf[off++];
            if (plen < 2) plen = 2;   /* need at least reg, op */
            if (plen > 16) plen = 16;
            if (off + plen > (size_t)total) plen = (size_t)total - off;
            if (plen < 2) break;
            charge_controller_process_i2c(&buf[off], plen);
            off += plen;
        }
    }

    return 0;
}
