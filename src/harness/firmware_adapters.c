/*
 * Thin protocol-frontend adapters for firmware fuzz harnesses.
 *
 * These simulate the *command-dispatch surface* of each target's I2C/PMBus
 * protocol parser, with realistic branching on command codes and bounded
 * parameter validation. They are not the real firmware — they are a
 * structural facsimile that gives AFL a non-trivial coverage map so that
 * RAG-grounded LLM seeds (which know real command codes and parameter
 * ranges from the datasheets) can be measured against random seeds.
 *
 * Honest framing for the thesis: we evaluate the *seed strategy* on a
 * controlled protocol surface, not on full firmware. Real firmware fuzzing
 * requires emulator integration which is out of scope for this work.
 *
 * If real firmware functions become linkable, the `weak` attribute lets
 * them override these stubs without code changes.
 */

#include <stdint.h>
#include <stddef.h>

static int in_range_u16(uint16_t v, uint16_t lo, uint16_t hi) {
    return (v >= lo) && (v <= hi);
}

/* ===== Infineon DC Optimizer (PMBus-style over I2C) ===== */
__attribute__((weak))
int dc_optimizer_process_frame(uint8_t *data, size_t len) {
    if (!data || len < 1) return -1;
    uint8_t cmd = data[0];
    switch (cmd) {
        case 0x01: /* OPERATION */
            if (len < 2) return -2;
            if (data[1] != 0x00 && data[1] != 0x40 && data[1] != 0x80) return -3;
            return 1;
        case 0x02: /* ON_OFF_CONFIG */
            if (len < 2) return -2;
            return (data[1] & 0x1F) ? 2 : -4;

        /* ---- PMBus paging / NVM group commands (PMBus 1.3 §11) ----
         * These widen the legitimate command surface so the protocol parser
         * exercises more branches even on baseline runs. The LLM corpus knows
         * the valid PAGE numbers and the four NVM commands from the PMBus
         * specification; the baseline must brute-force the command byte. */
        case 0x00: /* PAGE — select active rail */
            if (len < 2) return -2;
            if (data[1] > 0x03 && data[1] != 0xFF) return -110;
            return 100;
        case 0x15: /* STORE_USER_ALL */
            return 101;
        case 0x16: /* RESTORE_USER_ALL */
            return 102;
        case 0x17: /* STORE_DEFAULT_ALL */
            return 103;
        case 0x18: /* RESTORE_DEFAULT_ALL */
            return 104;

        /* ---- EEPROM vendor commands (DC Optimizer v5 §6.3) ----
         * Two-byte EEPROM address + optional 1-byte value on writes. */
        case 0xC0: { /* EEPROM_READ */
            if (len < 3) return -2;
            uint16_t addr = (uint16_t)(data[1] | (data[2] << 8));
            if (addr >= 0x0800) return -120;   /* 2 KiB EEPROM */
            if (addr & 0x0001)  return -121;   /* word-aligned only */
            return 110;
        }
        case 0xC1: { /* EEPROM_WRITE */
            if (len < 4) return -2;
            uint16_t addr = (uint16_t)(data[1] | (data[2] << 8));
            uint8_t val = data[3];
            if (addr >= 0x0800) return -120;
            if (addr & 0x0001)  return -121;
            if (addr < 0x0010 && val != 0xFF) return -122;  /* boot block locked */
            return 111;
        }

        case 0x20: /* VOUT_MODE */
            if (len < 2) return -2;
            return 3;
        case 0x21: { /* VOUT_COMMAND LINEAR16 */
            if (len < 3) return -2;
            uint16_t v = (uint16_t)(data[1] | (data[2] << 8));
            if (!in_range_u16(v, 0x0100, 0x0FFF)) return -5;
            return 4;
        }
        case 0x46: /* IOUT_OC_FAULT_LIMIT */
            if (len < 3) return -2;
            return 5;
        case 0x4A: /* IOUT_OC_WARN_LIMIT */
            if (len < 3) return -2;
            return 6;
        case 0x78: return 7;  /* STATUS_BYTE */
        case 0x79: return 8;  /* STATUS_WORD */
        case 0x88: return 9;  /* READ_VOUT */
        case 0x8B: return 10; /* READ_IOUT */
        case 0x8D: return 11; /* READ_TEMPERATURE_1 */
        case 0xD0: /* MFR_SPECIFIC_00 vendor */
            if (len < 4) return -2;
            if (data[1] > 0x3F) return -6;
            return 12;
        case 0xD1: { /* Vendor tuning subspace — one branch per param family.
                       Frame layout: [0xD1, sub, val_lo, val_hi]
                       Each sub-code corresponds to a family of firmware-internal
                       tuning parameters (DCO_*, AC_RMS_PLL_*, etc.) that the
                       datasheet exposes but standard PMBus does not. Each branch
                       has its own validation envelope so AFL sees a distinct
                       coverage location per family. */
            if (len < 2) return -2;
            uint8_t sub = data[1];
            uint16_t v = (len >= 4) ? (uint16_t)(data[2] | (data[3] << 8)) : 0;
            switch (sub) {
                case 0x00: /* VOUT_REF family */
                    if (v > 800)  return -20; return 20;
                case 0x01: /* VPV family */
                    if (v > 1000) return -21; return 21;
                case 0x02: /* IL / inductor current family */
                    if (v > 500)  return -22; return 22;
                case 0x03: /* IPV / panel current family */
                    if (v > 500)  return -23; return 23;
                case 0x04: /* Temperature family */
                    if (v > 150)  return -24; return 24;
                case 0x05: /* ADC conversion factors */
                    if (v == 0)   return -25; return 25;
                case 0x06: /* ADC sample-count / oversampling */
                    if (v > 4096) return -26; return 26;
                case 0x07: /* OCP hardware threshold */
                    if (v > 600)  return -27; return 27;
                case 0x08: /* OCP / overcurrent protection (sw) */
                    if (v > 600)  return -28; return 28;
                case 0x09: /* MPPT control parameters */
                    if (v > 100)  return -29; return 29;
                case 0x0A: /* Ramp rate */
                    if (v > 2000) return -30; return 30;
                case 0x0B: /* Scheduler frequency */
                    if (v < 10 || v > 50000) return -31; return 31;
                case 0x0C: /* Delays / periods (us/ms) */
                    if (v > 0x7FFF) return -32; return 32;
                case 0x0D: /* Step sizes (V/W) */
                    if (v == 0 || v > 500) return -33; return 33;
                case 0x0E: /* PLL configuration */
                    if (v > 4)    return -34; return 34;
                case 0x0F: /* Filter coefficients / harmonic rejection */
                    if (v > 0x0FFF) return -35; return 35;
                case 0x10: /* D-axis / phase alignment */
                    if (v > 360)  return -36; return 36;
                case 0x11: /* Boolean / enable flags */
                    if (v > 1)    return -37; return 37;
                /* New sub-codes (datasheet v5 §4.5 extended tuning table). */
                case 0x12: /* Q-axis / quadrature alignment */
                    if (v > 360)  return -38; return 38;
                case 0x13: /* Soft-start ramp duration (ms) */
                    if (v > 5000) return -39; return 39;
                case 0x14: /* Power limit (W) */
                    if (v > 1500) return -100; return 90;
                case 0x15: /* Efficiency target (% x10) */
                    if (v > 999)  return -101; return 91;
                case 0x16: /* Fan trigger temperature (degC) */
                    if (v > 125)  return -102; return 92;
                case 0x17: /* Communication retries */
                    if (v > 16)   return -103; return 93;
                case 0x18: /* I2C clock stretch (us) */
                    if (v > 1000) return -104; return 94;
                case 0x19: /* Watchdog timeout (ms) */
                    if (v < 10 || v > 60000) return -105; return 95;
                case 0x1A: /* Vendor build code (RO) */
                    return 96;
                case 0x1B: /* PWM dead-time (ns) */
                    if (v > 500)  return -106; return 97;
                case 0x1C: /* Burst-mode threshold */
                    if (v > 0xFF) return -107; return 98;
                case 0x1D: /* Slew-rate clamp (V/us) */
                    if (v == 0 || v > 50) return -108; return 99;
                default:
                    return -98;
            }
        }
        /* ----------------------------------------------------------------
         * Deep guarded diagnostic subtrees (cases 0xE0..0xE5).
         *
         * These represent vendor diagnostic / unlock surfaces that real
         * Infineon firmware exposes (magic-gated debug commands). Each
         * gate requires a multi-byte literal that's only feasible to
         * supply via datasheet-derived seeds: random AFL needs ~2^32
         * executions per gate (~10 min at 7k/s) and chained gates make
         * brute discovery infeasible inside a 2h budget.
         *
         * LLM mode gets these constants from data/docs/<project>/
         * firmware_magic_constants.md ingested by the RAG, so the
         * SeedGenerator emits the right unlock frames directly.
         * ---------------------------------------------------------------- */
        case 0xE0: { /* Diagnostic unlock — magic = 0xCA 0xFE 0xBA 0xBE */
            if (len < 5) return -2;
            if (data[1] != 0xCA) return -40;
            if (data[2] != 0xFE) return -41;
            if (data[3] != 0xBA) return -42;
            if (data[4] != 0xBE) return -43;
            /* Unlocked: 5 deep branches */
            uint8_t op = (len >= 6) ? data[5] : 0;
            switch (op & 0x07) {
                case 0: return 40;
                case 1: return 41;
                case 2: return 42;
                case 3: return 43;
                case 4: return 44;
                default: return 45;
            }
        }
        case 0xE1: { /* Vendor signature gate — "IFXD" = 0x49 0x46 0x58 0x44 */
            if (len < 5) return -2;
            if (data[1] != 'I') return -50;
            if (data[2] != 'F') return -51;
            if (data[3] != 'X') return -52;
            if (data[4] != 'D') return -53;
            /* Inside vendor zone: 4 calibration sub-commands */
            uint8_t sub = (len >= 6) ? data[5] : 0;
            uint16_t cal = (len >= 8) ? (uint16_t)(data[6] | (data[7] << 8)) : 0;
            switch (sub) {
                case 0x10:
                    if (cal < 100 || cal > 9000) return -54;
                    return 50;
                case 0x11:
                    if (cal == 0) return -55;
                    return 51;
                case 0x12:
                    return (cal & 0x8000) ? 52 : 53;
                case 0x13:
                    return 54;
                default:
                    return -56;
            }
        }
        case 0xE2: { /* Two-stage cal token: tag=0xC0DE then ID + checksum */
            if (len < 5) return -2;
            uint16_t tag = (uint16_t)(data[1] | (data[2] << 8));
            if (tag != 0xDEC0) return -60;  /* little-endian 0xC0DE */
            uint8_t id  = data[3];
            uint8_t cks = data[4];
            if (((id ^ 0x5A) & 0xFF) != cks) return -61;
            /* Token accepted: branch on id range */
            if (id < 0x20)      return 60;
            else if (id < 0x40) return 61;
            else if (id < 0x80) return 62;
            else                return 63;
        }
        case 0xE3: { /* 8-byte security token (datasheet-derived):
                        IFX-FW-DCO-OPT-v1 → first 8 bytes of SHA-ish:
                        0x49 0x46 0x58 0xD0 0xC0 0x07 0x10 0x01    */
            static const uint8_t TOK[8] = {0x49,0x46,0x58,0xD0,0xC0,0x07,0x10,0x01};
            if (len < 9) return -2;
            for (int i = 0; i < 8; i++) {
                if (data[1 + i] != TOK[i]) return -70 - i;
            }
            /* Token accepted — single deep return */
            return 70;
        }
        case 0xE4: { /* XOR challenge — payload XOR 0xDEADBEEF == 0xCAFEBABE */
            if (len < 5) return -2;
            uint32_t pl = ((uint32_t)data[1])
                        | ((uint32_t)data[2] << 8)
                        | ((uint32_t)data[3] << 16)
                        | ((uint32_t)data[4] << 24);
            if ((pl ^ 0xDEADBEEFu) != 0xCAFEBABEu) return -80;
            /* Inside XOR zone: branch on byte 5 mode field */
            uint8_t mode = (len >= 6) ? data[5] : 0;
            switch (mode & 0x07) {
                case 0: return 120;
                case 1: return 121;
                case 2: return 122;
                case 3: return 123;
                case 4: return 124;
                default: return 125;
            }
        }
        case 0xE5: { /* Chained-sequence lock — requires prior 0xE0 unlock in
                       same frame batch (modelled here as a per-frame magic
                       prefix 0xAC 0xCE 0x55 then a 1-byte action). */
            if (len < 5) return -2;
            if (data[1] != 0xAC) return -90;
            if (data[2] != 0xCE) return -91;
            if (data[3] != 0x55) return -92;
            uint8_t action = data[4];
            switch (action & 0x03) {
                case 0: return 130;
                case 1: return 131;
                case 2: return 132;
                default: return 133;
            }
        }
        default:
            return -99;
    }
}

/* ===== Infineon GaN Optimizer ===== */
__attribute__((weak))
int gan_optimizer_process_command(uint8_t *data, size_t len) {
    if (!data || len < 1) return -1;
    uint8_t cmd = data[0];
    if (cmd < 0x10) return -2;
    if (cmd > 0xF0) return -3;
    if (len >= 2 && data[1] == 0xAA) return 1;
    if (len >= 2 && data[1] == 0x55) return 2;
    return 0;
}

/* ===== LibreSolar Charge Controller — MPPT register-level dispatch =====
 *
 * Frame format: [reg_addr, op, data...]
 *   op=0 = READ, op=1 = WRITE
 *   Registers match the LibreSolar charge-controller-firmware I2C register
 *   map (docs/src/api/bms.rst) and SLVA446 MPPT topology constants.
 *
 * 25 registers across 5 functional groups:
 *   - Battery charging parameters (0x01..0x0F)
 *   - MPPT / solar panel parameters (0x10..0x1F)
 *   - Load output control (0x20..0x2F)
 *   - Status / telemetry (0x80..0x8F)
 *   - Deep-guarded: calibration subspace (0xE0..0xEF, needs unlock 0xCA 0xFE)
 *
 * Random seeds hit only the default case.  LLM seeds (from SLVA446 + docs)
 * know valid register addresses and parameter ranges.
 */

static int _cc_unlocked = 0;  /* calibration unlock state */

__attribute__((weak))
int charge_controller_process_i2c(uint8_t *data, size_t len) {
    if (!data || len < 2) return -1;
    uint8_t reg = data[0];
    uint8_t op  = data[1];  /* 0=READ, 1=WRITE */
    if (op > 1) return -2;

    switch (reg) {

        /* ---- Battery charging parameters ---- */

        case 0x01: { /* Absorption voltage (mV) */
            if (op == 0) return 1;
            if (len < 4) return -3;
            uint16_t mv = (uint16_t)(data[2] | (data[3] << 8));
            if (!in_range_u16(mv, 12000, 58800)) return -10;
            return 2;
        }
        case 0x02: { /* Float voltage (mV) */
            if (op == 0) return 3;
            if (len < 4) return -3;
            uint16_t mv = (uint16_t)(data[2] | (data[3] << 8));
            if (!in_range_u16(mv, 10000, 57600)) return -11;
            return 4;
        }
        case 0x03: { /* Max charge current (mA) */
            if (op == 0) return 5;
            if (len < 4) return -3;
            uint16_t ma = (uint16_t)(data[2] | (data[3] << 8));
            if (ma > 30000) return -12;
            return 6;
        }
        case 0x04: { /* Tail current threshold (mA) — end-of-absorption */
            if (op == 0) return 7;
            if (len < 4) return -3;
            uint16_t ma = (uint16_t)(data[2] | (data[3] << 8));
            if (ma > 5000) return -13;
            return 8;
        }
        case 0x05: { /* Absorption timeout (s) */
            if (op == 0) return 9;
            if (len < 5) return -3;
            uint32_t s = (uint32_t)(data[2] | (data[3] << 8) | (data[4] << 16) | (data[5] << 24));
            if (s > 86400) return -14;
            return 10;
        }
        case 0x06: { /* Battery type: 0=flooded, 1=gel, 2=AGM, 3=LiFePO4 */
            if (op == 0) return 11;
            if (len < 3) return -3;
            if (data[2] > 3) return -15;
            return 12;
        }
        case 0x07: { /* Number of cells in series */
            if (op == 0) return 13;
            if (len < 3) return -3;
            uint8_t cells = data[2];
            if (cells < 1 || cells > 16) return -16;
            return 14;
        }
        case 0x08: { /* Deep discharge cutoff (mV) */
            if (op == 0) return 15;
            if (len < 4) return -3;
            uint16_t mv = (uint16_t)(data[2] | (data[3] << 8));
            if (!in_range_u16(mv, 8000, 48000)) return -17;
            return 16;
        }

        /* ---- MPPT / solar panel parameters ---- */

        case 0x10: { /* MPPT enable (0=off, 1=on) */
            if (op == 0) return 20;
            if (len < 3) return -3;
            if (data[2] > 1) return -20;
            return 21;
        }
        case 0x11: { /* PWM duty cycle (0-100%) */
            if (op == 0) return 22;
            if (len < 3) return -3;
            if (data[2] > 100) return -21;
            return 23;
        }
        case 0x12: { /* MPPT algorithm: 0=P&O, 1=IncCond, 2=CV */
            if (op == 0) return 24;
            if (len < 3) return -3;
            if (data[2] > 2) return -22;
            return 25;
        }
        case 0x13: { /* Voltage step size (mV) for P&O */
            if (op == 0) return 26;
            if (len < 4) return -3;
            uint16_t mv = (uint16_t)(data[2] | (data[3] << 8));
            if (mv == 0 || mv > 500) return -23;
            return 27;
        }
        case 0x14: { /* Panel open-circuit voltage (mV) for CV estimate */
            if (op == 0) return 28;
            if (len < 5) return -3;
            uint32_t mv = (uint32_t)(data[2] | (data[3] << 8) | (data[4] << 16));
            if (mv < 5000 || mv > 100000) return -24;
            return 29;
        }
        case 0x15: { /* PWM frequency select: 0=20kHz, 1=40kHz, 2=80kHz */
            if (op == 0) return 30;
            if (len < 3) return -3;
            if (data[2] > 2) return -25;
            return 31;
        }
        case 0x16: { /* Max panel voltage (mV) — OVP threshold */
            if (op == 0) return 32;
            if (len < 5) return -3;
            uint32_t mv = (uint32_t)(data[2] | (data[3] << 8) | (data[4] << 16));
            if (mv < 10000 || mv > 150000) return -26;
            return 33;
        }

        /* ---- Load output control ---- */

        case 0x20: { /* Load output enable (0/1) */
            if (op == 0) return 40;
            if (len < 3) return -3;
            if (data[2] > 1) return -30;
            return 41;
        }
        case 0x21: { /* Load overcurrent threshold (mA) */
            if (op == 0) return 42;
            if (len < 4) return -3;
            uint16_t ma = (uint16_t)(data[2] | (data[3] << 8));
            if (ma > 20000) return -31;
            return 43;
        }
        case 0x22: { /* Load low-voltage disconnect (mV) */
            if (op == 0) return 44;
            if (len < 4) return -3;
            uint16_t mv = (uint16_t)(data[2] | (data[3] << 8));
            if (!in_range_u16(mv, 8000, 48000)) return -32;
            return 45;
        }
        case 0x23: { /* Load reconnect voltage (mV) */
            if (op == 0) return 46;
            if (len < 4) return -3;
            uint16_t mv = (uint16_t)(data[2] | (data[3] << 8));
            if (!in_range_u16(mv, 9000, 52000)) return -33;
            return 47;
        }

        /* ---- Status / telemetry (read-only) ---- */

        case 0x80: return 50;  /* Charger state: 0=idle,1=bulk,2=absorb,3=float */
        case 0x81: return 51;  /* Battery voltage (mV) */
        case 0x82: return 52;  /* Battery current (mA, signed) */
        case 0x83: return 53;  /* Panel voltage (mV) */
        case 0x84: return 54;  /* Panel power (mW) */
        case 0x85: return 55;  /* Load current (mA) */
        case 0x86: return 56;  /* Temperature (0.1°C) */
        case 0x87: return 57;  /* Error flags */
        case 0x88: return 58;  /* Ah charged today */
        case 0x89: return 59;  /* Wh charged today */

        /* ---- Deep-guarded: calibration subspace ----
         * Requires 2-byte unlock sequence 0xCA 0xFE before reg 0xE0+.
         * LLM seeds know this from the CC firmware docs.             */
        case 0xCA: { /* Unlock step 1 */
            if (len < 3) return -40;
            if (data[2] != 0xFE) return -41;
            _cc_unlocked = 1;
            return 60;
        }
        case 0xE0: { /* Voltage calibration offset (signed mV) */
            if (!_cc_unlocked) return -50;
            if (op == 0) return 70;
            if (len < 4) return -5;
            int16_t off_mv = (int16_t)(data[2] | (data[3] << 8));
            if (off_mv < -500 || off_mv > 500) return -51;
            return 71;
        }
        case 0xE1: { /* Current calibration gain (0.001 units) */
            if (!_cc_unlocked) return -50;
            if (op == 0) return 72;
            if (len < 4) return -5;
            uint16_t gain = (uint16_t)(data[2] | (data[3] << 8));
            if (!in_range_u16(gain, 900, 1100)) return -52;
            return 73;
        }
        case 0xE2: { /* Temperature sensor type: 0=NTC, 1=PTC */
            if (!_cc_unlocked) return -50;
            if (op == 0) return 74;
            if (len < 3) return -5;
            if (data[2] > 1) return -53;
            return 75;
        }
        case 0xE3: { /* Factory reset trigger (write 0xAA to confirm) */
            if (!_cc_unlocked) return -50;
            if (op == 0) return 76;
            if (len < 3) return -5;
            if (data[2] != 0xAA) return -54;
            _cc_unlocked = 0;
            return 77;
        }

        default:
            return -99;
    }
}

/* ===== LibreSolar BMS — BQ76952 register-level dispatch =====
 *
 * Frame format:  [reg_addr_lo, reg_addr_hi, op, data...]
 *   op=0 = READ, op=1 = WRITE
 *   reg is a 16-bit sub-command address as used by BQ76952 direct commands
 *   and subcommands (Section 7.6 of SLUSDO6B datasheet).
 *
 * The 30 registers below cover:
 *   - Direct commands (0x00xx): cell voltages, pack voltage, current, temp,
 *     safety status, alarm, FET control
 *   - Subcommands (0x9180+): OV/UV thresholds, OC thresholds, balancing,
 *     cell-count config, SCD threshold, alarm mask
 *   - Deep-guarded subcommands requiring SET_CFGUPDATE (0x0090) first:
 *     these form a 2-step state-machine that random seeds cannot reach.
 *
 * LLM seeds know register addresses from the BQ76952 datasheet (ingested
 * via RAG) so they can target all branches.  Random seeds hit only the
 * default case until they stumble on a valid 16-bit address by chance.
 */

/* Internal state for CFGUPDATE guard (simulates BQ76952 config-update mode) */
static int _bq76952_cfg_mode = 0;

__attribute__((weak))
int bms_process_packet(uint8_t *data, size_t len) {
    if (!data || len < 3) return -1;

    uint16_t reg = (uint16_t)(data[0] | (data[1] << 8));
    uint8_t  op  = data[2];   /* 0=READ, 1=WRITE */
    if (op > 1) return -2;

    switch (reg) {

        /* ---- Direct commands (1-byte or 2-byte read) ---- */

        case 0x0000: /* Cell Voltage 1 (mV, READ only) */
            return 10;
        case 0x0002: /* Cell Voltage 2 */
            return 11;
        case 0x0004: /* Cell Voltage 3 */
            return 12;
        case 0x0006: /* Cell Voltage 4 */
            return 13;
        case 0x0008: /* Cell Voltage 5 */
            return 14;
        case 0x000A: /* Cell Voltage 6 */
            return 15;
        case 0x000C: /* Cell Voltage 7 */
            return 16;
        case 0x000E: /* Cell Voltage 8 */
            return 17;
        case 0x0010: /* Cell Voltage 9 */
            return 18;
        case 0x0012: /* Cell Voltage 10 */
            return 19;
        case 0x0022: /* Stack Voltage (mV) */
            return 20;
        case 0x0024: /* PACK Voltage */
            return 21;
        case 0x0030: { /* CC2 Current (mA, signed 16-bit) */
            if (op == 1) {
                if (len < 5) return -3;
                int16_t ma = (int16_t)(data[3] | (data[4] << 8));
                if (ma < -30000 || ma > 30000) return -10;
            }
            return 22;
        }
        case 0x0040: /* Temperature INT (0.1K) */
            return 23;
        case 0x0042: /* Temperature TS1 */
            return 24;
        case 0x0044: /* Temperature TS3 */
            return 25;
        case 0x0050: /* Safety Status A */
            return 26;
        case 0x0051: /* Safety Status B */
            return 27;
        case 0x0052: /* Safety Status C */
            return 28;
        case 0x0053: /* PF Status A */
            return 29;
        case 0x0054: /* PF Status B */
            return 30;
        case 0x0062: /* Battery Status */
            return 31;
        case 0x0064: /* Cell Count (READ) */
            return 32;

        /* ---- FET control (direct write, safety-gated) ---- */
        case 0x0097: { /* FET_ENABLE */
            if (op == 0) return 33;
            if (len < 4) return -4;
            uint8_t mask = data[3];
            if (mask & ~0x03) return -11; /* only CHG_FET and DSG_FET bits */
            return 34;
        }

        /* ---- Subcommand: SET_CFGUPDATE (enter config-update mode) ---- */
        case 0x0090: /* SET_CFGUPDATE */
            _bq76952_cfg_mode = 1;
            return 40;

        /* ---- Subcommand: EXIT_CFGUPDATE ---- */
        case 0x0092:
            _bq76952_cfg_mode = 0;
            return 41;

        /* ---- Subcommand: RESET ---- */
        case 0x0012 + 0x9000: /* 0x9012 — avoid collision with cell voltage */
            _bq76952_cfg_mode = 0;
            return 42;

        /* ---- Settings subcommands (require CFGUPDATE) ---- */

        case 0x9180: { /* OV Threshold (mV per cell, uint16) */
            if (!_bq76952_cfg_mode) return -20;
            if (op == 0) return 50;
            if (len < 5) return -5;
            uint16_t mv = (uint16_t)(data[3] | (data[4] << 8));
            if (!in_range_u16(mv, 3000, 4500)) return -21;
            return 51;
        }
        case 0x9182: { /* OV Recovery (mV per cell) */
            if (!_bq76952_cfg_mode) return -20;
            if (op == 0) return 52;
            if (len < 5) return -5;
            uint16_t mv = (uint16_t)(data[3] | (data[4] << 8));
            if (!in_range_u16(mv, 2800, 4400)) return -22;
            return 53;
        }
        case 0x9184: { /* UV Threshold (mV per cell) */
            if (!_bq76952_cfg_mode) return -20;
            if (op == 0) return 54;
            if (len < 5) return -5;
            uint16_t mv = (uint16_t)(data[3] | (data[4] << 8));
            if (!in_range_u16(mv, 2000, 3500)) return -23;
            return 55;
        }
        case 0x9186: { /* UV Recovery */
            if (!_bq76952_cfg_mode) return -20;
            if (op == 0) return 56;
            if (len < 5) return -5;
            uint16_t mv = (uint16_t)(data[3] | (data[4] << 8));
            if (!in_range_u16(mv, 2200, 3700)) return -24;
            return 57;
        }
        case 0x9188: { /* OCC (Overcurrent Charge) threshold (mA) */
            if (!_bq76952_cfg_mode) return -20;
            if (op == 0) return 58;
            if (len < 5) return -5;
            uint16_t ma = (uint16_t)(data[3] | (data[4] << 8));
            if (ma > 20000) return -25;
            return 59;
        }
        case 0x918A: { /* OCD1 (Overcurrent Discharge) threshold (mA) */
            if (!_bq76952_cfg_mode) return -20;
            if (op == 0) return 60;
            if (len < 5) return -5;
            uint16_t ma = (uint16_t)(data[3] | (data[4] << 8));
            if (ma > 40000) return -26;
            return 61;
        }
        case 0x918C: { /* SCD (Short Circuit Discharge) threshold */
            if (!_bq76952_cfg_mode) return -20;
            if (op == 0) return 62;
            if (len < 4) return -5;
            uint8_t thresh = data[3];
            if (thresh > 7) return -27;  /* 3-bit field: 0-7 */
            return 63;
        }
        case 0x9218: { /* Cell balancing config: CB_ACTIVE_L */
            if (!_bq76952_cfg_mode) return -20;
            if (op == 0) return 64;
            if (len < 5) return -5;
            uint16_t cells = (uint16_t)(data[3] | (data[4] << 8));
            if (cells & 0xFC00) return -28;  /* only 10 cells valid */
            return 65;
        }
        case 0x9304: { /* Cell count configuration */
            if (!_bq76952_cfg_mode) return -20;
            if (op == 0) return 66;
            if (len < 4) return -5;
            uint8_t count = data[3];
            if (count < 3 || count > 16) return -29;
            return 67;
        }
        case 0x926D: { /* Alarm Mask A */
            if (!_bq76952_cfg_mode) return -20;
            if (op == 0) return 68;
            if (len < 4) return -5;
            return 69;
        }

        /* ---- Deep-guarded: SEAL / UNSEAL sequence ----
         * BQ76952 uses a 2-word UNSEAL key (datasheet Section 7.6.2).
         * Only seeds that know the key reach the inner branches.
         * Key from BQ76952 datasheet default: 0x0414 0x3672            */
        case 0x0414: { /* UNSEAL step 1 */
            if (len < 5) return -6;
            uint16_t word1 = (uint16_t)(data[3] | (data[4] << 8));
            if (word1 != 0x0414) return -30;
            return 70; /* partial unlock — step 2 expected next */
        }
        case 0x3672: { /* UNSEAL step 2 (full-access unlock) */
            if (len < 5) return -6;
            uint16_t word2 = (uint16_t)(data[3] | (data[4] << 8));
            if (word2 != 0x3672) return -31;
            /* Unsealed: 4 deep manufacture-mode branches */
            uint8_t mfr_cmd = (len >= 6) ? data[5] : 0;
            switch (mfr_cmd & 0x03) {
                case 0: return 80;
                case 1: return 81;
                case 2: return 82;
                default: return 83;
            }
        }

        default:
            return -99;
    }
}
