// Persistent AFL++ harness for Infineon DC Optimizer protocol surface.
//
// Input format (TLV stream — keeps the seed-encoder and AFL byte-flip
// mutator both productive):
//   buf[0]      = N (number of frames, capped at 32)
//   then repeating: [len_byte][len_byte bytes of frame]
//
// This replaces the previous circular-buffer multiplexer which made
// structured seeds collide with themselves (frame[0] == steps byte).
// With TLV, one seed can cleanly exercise multiple command branches
// per __AFL_LOOP iteration without aliasing.

#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>

#ifndef MAX_INPUT
#define MAX_INPUT 4096
#endif

extern int dc_optimizer_process_frame(uint8_t *data, size_t len);

int main(void) {

    static uint8_t buf[MAX_INPUT];

    while (__AFL_LOOP(1000)) {

        ssize_t total = read(0, buf, sizeof(buf));
        if (total <= 1) continue;

        size_t n_frames = (buf[0] % 32);
        if (n_frames == 0) n_frames = 1;

        size_t off = 1;
        for (size_t i = 0; i < n_frames; i++) {
            if (off >= (size_t)total) break;
            size_t flen = buf[off++];
            if (flen == 0) flen = 1;
            if (flen > 32) flen = 32;
            if (off + flen > (size_t)total) flen = (size_t)total - off;
            if (flen == 0) break;
            dc_optimizer_process_frame(&buf[off], flen);
            off += flen;
        }
    }

    return 0;
}
