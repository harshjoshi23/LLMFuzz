/*
 * AFL++ source-level harness for Infineon OneEye sync protocol (from dc-optimizer repo).
 *
 * Target repo: targets/mtb-example-pwrlib-dc-optimizer
 * UUT: oneeye/oneeye_lib/ifx_oe_syncprotocol.c
 *
 * Rationale:
 * - Protocol framing/parsing/state machine style logic
 * - Portable C compared to the ModusToolbox-tied power-control code
 * - High value for robustness + fuzzing evaluation
 */

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

// Host fuzz build: avoid pulling in a hardware abstraction layer.
// The OneEye headers default to IFX_CFG_OE_AL_UC_NONE which errors in ifx_oe_al.h.
// We keep IFX_CFG_OE_AL_UC as NONE and enable IFX_CFG_OE_HOST_FUZZ (set in oneeye/Ifx_Cfg.h).

// oneeye headers use custom integer typedefs (uint8/uint16/...) and macros
#include "../../targets/mtb-example-pwrlib-dc-optimizer/oneeye/oneeye_lib/ifx_oe_cfg.h"
#include "../../targets/mtb-example-pwrlib-dc-optimizer/oneeye/oneeye_lib/ifx_oe_syncprotocol.h"

// Provide missing platform hooks if not provided by the selected config
#ifndef IFX_OE_ASSERT
#define IFX_OE_ASSERT(x) do { (void)sizeof(x); } while (0)
#endif

// -------------------------
// Minimal host DPipe
// -------------------------
// The sync protocol reads/writes bytes through a StdIf DPipe.
// For host fuzzing, we provide an in-memory DPipe:
// - read(): consumes from rx buffer
// - write(): appends to tx buffer

typedef struct {
    Ifx_Oe_StdIf_DPipe stdif;
    const uint8_t *rx;
    uint32_t rx_len;
    uint32_t rx_pos;
    uint8_t *tx;
    uint32_t tx_cap;
    uint32_t tx_len;
} FuzzDpipe;

static boolean fuzz_write(Ifx_Oe_StdIf_InterfaceDriver stdIf, void *data, Ifx_Oe_SizeT *count, Ifx_Oe_TickTime timeout)
{
    (void)timeout;
    FuzzDpipe *p = (FuzzDpipe *)stdIf;
    if (!p || !data || !count) {
        return FALSE;
    }

    uint32_t want = (uint32_t)(*count);
    uint32_t can = 0;
    if (p->tx_len < p->tx_cap) {
        can = p->tx_cap - p->tx_len;
    }
    uint32_t n = want < can ? want : can;
    if (n > 0) {
        memcpy(&p->tx[p->tx_len], data, n);
        p->tx_len += n;
    }
    *count = (Ifx_Oe_SizeT)n;
    return TRUE;
}

static boolean fuzz_read(Ifx_Oe_StdIf_InterfaceDriver stdIf, void *data, Ifx_Oe_SizeT *count, Ifx_Oe_TickTime timeout)
{
    (void)timeout;
    FuzzDpipe *p = (FuzzDpipe *)stdIf;
    if (!p || !data || !count) {
        return FALSE;
    }

    uint32_t want = (uint32_t)(*count);
    uint32_t avail = (p->rx_pos < p->rx_len) ? (p->rx_len - p->rx_pos) : 0;
    uint32_t n = want < avail ? want : avail;
    if (n > 0) {
        memcpy(data, &p->rx[p->rx_pos], n);
        p->rx_pos += n;
    }
    *count = (Ifx_Oe_SizeT)n;
    return TRUE;
}

static void fuzz_clear_rx(Ifx_Oe_StdIf_InterfaceDriver stdIf)
{
    FuzzDpipe *p = (FuzzDpipe *)stdIf;
    if (p) {
        p->rx_pos = p->rx_len;
    }
}

static void fuzz_clear_tx(Ifx_Oe_StdIf_InterfaceDriver stdIf)
{
    FuzzDpipe *p = (FuzzDpipe *)stdIf;
    if (p) {
        p->tx_len = 0;
    }
}

static sint32 fuzz_get_read_count(Ifx_Oe_StdIf_InterfaceDriver stdIf)
{
    FuzzDpipe *p = (FuzzDpipe *)stdIf;
    if (!p) {
        return 0;
    }
    if (p->rx_pos >= p->rx_len) {
        return 0;
    }
    return (sint32)(p->rx_len - p->rx_pos);
}

static sint32 fuzz_get_write_count(Ifx_Oe_StdIf_InterfaceDriver stdIf)
{
    FuzzDpipe *p = (FuzzDpipe *)stdIf;
    if (!p) {
        return 0;
    }
    return (sint32)p->tx_len;
}

static boolean fuzz_can_read_count(Ifx_Oe_StdIf_InterfaceDriver stdIf, Ifx_Oe_SizeT count, Ifx_Oe_TickTime timeout)
{
    (void)timeout;
    FuzzDpipe *p = (FuzzDpipe *)stdIf;
    if (!p) {
        return FALSE;
    }
    uint32_t avail = (p->rx_pos < p->rx_len) ? (p->rx_len - p->rx_pos) : 0;
    return (avail >= (uint32_t)count) ? TRUE : FALSE;
}

static boolean fuzz_can_write_count(Ifx_Oe_StdIf_InterfaceDriver stdIf, Ifx_Oe_SizeT count, Ifx_Oe_TickTime timeout)
{
    (void)timeout;
    FuzzDpipe *p = (FuzzDpipe *)stdIf;
    if (!p) {
        return FALSE;
    }
    uint32_t space = (p->tx_len < p->tx_cap) ? (p->tx_cap - p->tx_len) : 0;
    return (space >= (uint32_t)count) ? TRUE : FALSE;
}

static boolean fuzz_flush_tx(Ifx_Oe_StdIf_InterfaceDriver stdIf, Ifx_Oe_TickTime timeout)
{
    (void)timeout;
    (void)stdIf;
    return TRUE;
}

static Ifx_Oe_SizeT fuzz_get_tx_size(Ifx_Oe_StdIf_InterfaceDriver stdIf)
{
    FuzzDpipe *p = (FuzzDpipe *)stdIf;
    return p ? (Ifx_Oe_SizeT)p->tx_cap : 0;
}

static Ifx_Oe_SizeT fuzz_get_rx_size(Ifx_Oe_StdIf_InterfaceDriver stdIf)
{
    FuzzDpipe *p = (FuzzDpipe *)stdIf;
    return p ? (Ifx_Oe_SizeT)p->rx_len : 0;
}

static boolean fuzz_is_tx_empty(Ifx_Oe_StdIf_InterfaceDriver stdIf)
{
    FuzzDpipe *p = (FuzzDpipe *)stdIf;
    return (p && p->tx_len == 0) ? TRUE : FALSE;
}

static boolean fuzz_is_rx_empty(Ifx_Oe_StdIf_InterfaceDriver stdIf)
{
    FuzzDpipe *p = (FuzzDpipe *)stdIf;
    return (p && p->rx_pos >= p->rx_len) ? TRUE : FALSE;
}

static Ifx_Oe_SizeT fuzz_get_tx_elem_size(Ifx_Oe_StdIf_InterfaceDriver stdIf)
{
    (void)stdIf;
    return 1;
}

static Ifx_Oe_SizeT fuzz_get_rx_elem_size(Ifx_Oe_StdIf_InterfaceDriver stdIf)
{
    (void)stdIf;
    return 1;
}

static void fuzz_on_receive(Ifx_Oe_StdIf_InterfaceDriver stdIf) { (void)stdIf; }
static void fuzz_on_transmit(Ifx_Oe_StdIf_InterfaceDriver stdIf) { (void)stdIf; }
static void fuzz_on_error(Ifx_Oe_StdIf_InterfaceDriver stdIf) { (void)stdIf; }
static uint32 fuzz_get_send_count(Ifx_Oe_StdIf_InterfaceDriver stdIf) { (void)stdIf; return 0; }
static Ifx_Oe_TickTime fuzz_get_tx_timestamp(Ifx_Oe_StdIf_InterfaceDriver stdIf) { (void)stdIf; return Ifx_Oe_Time_0s; }
static void fuzz_reset_send_count(Ifx_Oe_StdIf_InterfaceDriver stdIf) { (void)stdIf; }

static void fuzz_dpipe_init(FuzzDpipe *p, const uint8_t *rx, uint32_t rx_len, uint8_t *tx, uint32_t tx_cap)
{
    memset(p, 0, sizeof(*p));
    Ifx_Oe_StdIf_DPipe_initStdIf(&p->stdif);

    p->rx = rx;
    p->rx_len = rx_len;
    p->rx_pos = 0;
    p->tx = tx;
    p->tx_cap = tx_cap;
    p->tx_len = 0;

    p->stdif.write = (Ifx_Oe_StdIf_DPipe_Write)&fuzz_write;
    p->stdif.read = (Ifx_Oe_StdIf_DPipe_Read)&fuzz_read;
    p->stdif.clearTx = (Ifx_Oe_StdIf_DPipe_ClearTx)&fuzz_clear_tx;
    p->stdif.clearRx = (Ifx_Oe_StdIf_DPipe_ClearRx)&fuzz_clear_rx;
    p->stdif.getReadCount = (Ifx_Oe_StdIf_DPipe_GetReadCount)&fuzz_get_read_count;
    p->stdif.getWriteCount = (Ifx_Oe_StdIf_DPipe_GetWriteCount)&fuzz_get_write_count;
    p->stdif.canReadCount = (Ifx_Oe_StdIf_DPipe_CanReadCount)&fuzz_can_read_count;
    p->stdif.canWriteCount = (Ifx_Oe_StdIf_DPipe_CanWriteCount)&fuzz_can_write_count;
    p->stdif.flushTx = (Ifx_Oe_StdIf_DPipe_FlushTx)&fuzz_flush_tx;
    p->stdif.getTxSize = (Ifx_Oe_StdIf_DPipe_GetTxSize)&fuzz_get_tx_size;
    p->stdif.getRxSize = (Ifx_Oe_StdIf_DPipe_GetRxSize)&fuzz_get_rx_size;
    p->stdif.isTxEmpty = (Ifx_Oe_StdIf_DPipe_IsTxEmpty)&fuzz_is_tx_empty;
    p->stdif.isRxEmpty = (Ifx_Oe_StdIf_DPipe_IsRxEmpty)&fuzz_is_rx_empty;
    p->stdif.getTxElementSize = (Ifx_Oe_StdIf_DPipe_GetTxElementSize)&fuzz_get_tx_elem_size;
    p->stdif.getRxElementSize = (Ifx_Oe_StdIf_DPipe_GetRxElementSize)&fuzz_get_rx_elem_size;
    p->stdif.onReceive = (Ifx_Oe_StdIf_DPipe_OnReceive)&fuzz_on_receive;
    p->stdif.onTransmit = (Ifx_Oe_StdIf_DPipe_OnTransmit)&fuzz_on_transmit;
    p->stdif.onError = (Ifx_Oe_StdIf_DPipe_OnError)&fuzz_on_error;
    p->stdif.getSendCount = (Ifx_Oe_StdIf_DPipe_GetSendCount)&fuzz_get_send_count;
    p->stdif.getTxTimeStamp = (Ifx_Oe_StdIf_DPipe_GetTxTimeStamp)&fuzz_get_tx_timestamp;
    p->stdif.resetSendCount = (Ifx_Oe_StdIf_DPipe_ResetSendCount)&fuzz_reset_send_count;
}

static size_t read_input(uint8_t *buf, size_t cap, int argc, char **argv) {
    if (argc >= 2 && argv[1] && argv[1][0]) {
        FILE *f = fopen(argv[1], "rb");
        if (!f) return 0;
        size_t n = fread(buf, 1, cap, f);
        fclose(f);
        return n;
    }
    return fread(buf, 1, cap, stdin);
}

static void scen_log(FILE *scen, const char *fmt, ...) {
    if (!scen) return;
    va_list ap;
    va_start(ap, fmt);
    vfprintf(scen, fmt, ap);
    va_end(ap);
    fputc('\n', scen);
    fflush(scen);
}

int main(int argc, char **argv)
{
    uint8_t buf[4096];
    size_t n = read_input(buf, sizeof(buf), argc, argv);

    if (n < 4) {
        return 0;
    }

    // Scenario telemetry (best-effort)
    FILE *scen = NULL;
    const char *scen_path = getenv("THESIS_SCENARIO_LOG");
    const char *art_dir = getenv("THESIS_ARTIFACTS_DIR");
    if (scen_path && scen_path[0]) {
        scen = fopen(scen_path, "a");
    } else if (art_dir && art_dir[0]) {
        char p[512];
        snprintf(p, sizeof(p), "%s/scenario_events.log", art_dir);
        scen = fopen(p, "a");
    }

    uint8_t tx[4096];
    FuzzDpipe dpipe;
    fuzz_dpipe_init(&dpipe, buf, (uint32_t)n, tx, (uint32_t)sizeof(tx));

    Ifx_Oe_SyncProtocol protocol;
    Ifx_Oe_SyncProtocol_Client client;

    Ifx_Oe_SyncProtocol_init(&protocol, 5 /*ms*/, &dpipe.stdif);

    (void)Ifx_Oe_SyncProtocol_addClient(
        &protocol,
        &client,
        (Ifx_Oe_SyncProtocol_Port)1,
        (Ifx_Oe_SyncProtocol_Port)2,
        IFX_OE_SYNCPROTOCOL_CORE_MESSAGE_PAYLOAD_MAX_LENGTH,
        Ifx_Oe_SyncProtocol_getFifoSize());

    // Input model: action stream.
    // With the host-fuzz time patches enabled (IFX_CFG_OE_HOST_FUZZ), execute() is bounded.
    //
    // Format (byte-oriented):
    // - buf[0] = action_count (1..31)
    // Each action i has header starting at off:
    // - kind (1 byte): 0=send, 1=tick_only, 2=reset
    // - msg_id (1 byte)
    // - payload_len (1 byte) capped to 32
    // - payload bytes...
    //
    // If the input asks for 0 actions, exit quickly.
    uint32_t actions = (uint32_t)(buf[0] & 0x1F);
    size_t off = 1;
    if (actions == 0) {
        if (scen) {
            scen_log(scen, "SCEN:oneeye:empty_actions n=%zu", n);
            fclose(scen);
        }
        Ifx_Oe_SyncProtocol_deinit(&protocol);
        return 0;
    }


    if (scen) {
        scen_log(scen, "SCEN:oneeye:init actions=%u n=%zu", actions, n);
    }

    for (uint32_t a = 0; a < actions && off + 3 < n; a++) {
        uint8_t kind = buf[off++];
        uint8_t msg_id_b = buf[off++];
        uint8_t payload_len_b = buf[off++];

        // Map any byte into 3-way action space.
        uint8_t k = (uint8_t)(kind % 3);

        uint32_t payload_len = (uint32_t)payload_len_b;
        if (payload_len > 32) payload_len = 32;
        if (off + payload_len > n) {
            payload_len = (uint32_t)(n - off);
        }

        if (k == 0) {
            // SEND
            Ifx_Oe_SyncProtocol_MessageId id = (Ifx_Oe_SyncProtocol_MessageId)(0x100 + msg_id_b);
            Ifx_Oe_SyncProtocol_Message *m = Ifx_Oe_SyncProtocol_setSendMessageBuffer(&client, id, payload_len);
            if (m && m->messagePayload && payload_len > 0) {
                memcpy(m->messagePayload, &buf[off], payload_len);
                (void)Ifx_Oe_SyncProtocol_updatePayloadLength(m, payload_len);
                Ifx_Oe_SyncProtocol_sendMessage(m);

                if (scen) {
                    scen_log(scen, "SCEN:oneeye:send step=%u id=0x%x len=%u", (unsigned)a, (unsigned)id, (unsigned)payload_len);
                }
            }
        } else if (k == 1) {
            // TICK_ONLY
            if (scen) {
                scen_log(scen, "SCEN:oneeye:tick_only step=%u", (unsigned)a);
            }
        } else {
            // RESET
            if (scen) {
                scen_log(scen, "SCEN:oneeye:reset step=%u", (unsigned)a);
            }
            Ifx_Oe_SyncProtocol_deinit(&protocol);
            Ifx_Oe_SyncProtocol_init(&protocol, 5 /*ms*/, &dpipe.stdif);
            (void)Ifx_Oe_SyncProtocol_addClient(
                &protocol,
                &client,
                (Ifx_Oe_SyncProtocol_Port)1,
                (Ifx_Oe_SyncProtocol_Port)2,
                IFX_OE_SYNCPROTOCOL_CORE_MESSAGE_PAYLOAD_MAX_LENGTH,
                Ifx_Oe_SyncProtocol_getFifoSize());
        }

        off += payload_len;

        // Execute a few ticks after each action to drive internal state.
        // IMPORTANT: Bound to keep exec/sec high and avoid harness hangs.
        for (int i = 0; i < 4; i++) {
            Ifx_Oe_SyncProtocol_execute(&protocol);
            if (dpipe.rx_pos >= dpipe.rx_len) {
                break;
            }
        }
    }

    // Final drain (bounded)
    for (int i = 0; i < 8; i++) {
        Ifx_Oe_SyncProtocol_execute(&protocol);
        if (dpipe.rx_pos >= dpipe.rx_len) {
            break;
        }
    }

    if (scen) {
        scen_log(scen, "SCEN:oneeye:done tx_len=%u rx_pos=%u", (unsigned)dpipe.tx_len, (unsigned)dpipe.rx_pos);
        fclose(scen);
    }

    Ifx_Oe_SyncProtocol_deinit(&protocol);
    return 0;
}
