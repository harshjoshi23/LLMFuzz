// Persistent AFL++ harness for LibreSolar BMS — BQ76952 register-level surface.
//
// Input format (TLV stream):
//   buf[0]      = N (number of frames, capped at 32)
//   then repeating: [len_byte][len_byte bytes of frame]
//
// Each frame is passed directly to bms_process_packet() which now implements
// the BQ76952 16-bit register-address dispatch (reg_lo, reg_hi, op, data...).
// Minimum useful frame is 3 bytes (reg_lo, reg_hi, op=READ).
// Write frames carry additional data bytes per the BQ76952 subcommand spec.

#include <stdint.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>

#ifndef MAX_INPUT
#define MAX_INPUT 4096
#endif

extern int bms_process_packet(uint8_t *data, size_t len);

int main(void)
{
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
            if (plen < 3) plen = 3;   /* need at least reg_lo, reg_hi, op */
            if (plen > 32) plen = 32;
            if (off + plen > (size_t)total) plen = (size_t)total - off;
            if (plen < 3) break;
            bms_process_packet(&buf[off], plen);
            off += plen;
        }
    }

    return 0;
}
