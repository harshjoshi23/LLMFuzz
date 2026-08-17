// Persistent AFL++ harness for TARGET_REF_OPTI_80V20A_GaN firmware protocol
// Drives command frames into the GaN optimizer firmware adapter

#include <stdint.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>

#ifndef MAX_INPUT
#define MAX_INPUT 4096
#endif

// Adapter implemented in build integration layer
extern int gan_optimizer_process_command(uint8_t *data, size_t len);

int main(void)
{
    static uint8_t buf[MAX_INPUT];

    while (__AFL_LOOP(1000)) {

        ssize_t len = read(0, buf, sizeof(buf));
        if (len <= 0) continue;

        size_t cmds = buf[0] % 64;
        if (cmds == 0) cmds = 1;

        for (size_t i = 0; i < cmds; i++) {

            uint8_t frame[32];
            size_t frame_len = (buf[(i+1)%len] % 16) + 2;

            for (size_t j = 0; j < frame_len; j++)
                frame[j] = buf[(i+j)%len];

            gan_optimizer_process_command(frame, frame_len);
        }
    }

    return 0;
}
