/*******************************************************************************
 * File: fuzz_pmbus.c
 * 
 * Description: AFL++ fuzz harness for PMBus command parsing
 *              Part of: AI-Enhanced Fuzzing for Embedded Power Systems
 *              
 * Harness notes:
 * - This harness is a synthetic demo harness (host-side) used to exercise the pipeline.
 * - It is NOT a claim of real vulnerabilities in any vendor firmware.
 *
 * Build with AFL++:
 *   afl-gcc -o fuzz_pmbus fuzz_pmbus.c mock_hal.c -I../data/firmware/nvidia_pdb
 *   
 * Run:
 *   afl-fuzz -i seeds/pmbus -o findings -t 1000 ./fuzz_pmbus @@
 *
 * Copyright 2025 - Thesis Research
 ******************************************************************************/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>

/*******************************************************************************
 * Mock HAL types (since we don't have real Cypress HAL on host)
 ******************************************************************************/
typedef uint32_t cy_en_scb_i2c_status_t;
#define CY_SCB_I2C_SUCCESS 0
#define CY_SCB_I2C_BAD_PARAM 1

/*******************************************************************************
 * PMBus Command Length Tables (extracted from firmware)
 * Format: [0] = write lengths, [1] = read lengths
 ******************************************************************************/
const uint8_t PMBus_Write_Read_Length[2][256] = {
    // Write command lengths (bytes including command)
    {
        0, 2, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // 0x00-0x0F
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // 0x10-0x1F
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // 0x20-0x2F
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // 0x30-0x3F
        0, 0, 0, 3, 3, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 3,  // 0x40-0x4F
        0, 3, 0, 0, 0, 3, 0, 3, 3, 3, 0, 0, 0, 0, 0, 0,  // 0x50-0x5F
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0,  // 0x60-0x6F
        0, 0, 0, 0, 0, 0, 0, 0, 2, 3, 2, 2, 2, 2, 2, 2,  // 0x70-0x7F
        2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // 0x80-0x8F
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // 0x90-0x9F
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // 0xA0-0xAF
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // 0xB0-0xBF
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // 0xC0-0xCF
        2, 2, 3, 3, 3, 3, 3, 3, 3, 3, 2, 3, 3, 2, 3, 3,  // 0xD0-0xDF
        3, 3, 3, 3, 2, 3, 3, 3, 3, 3, 0, 0, 1, 0, 0, 0,  // 0xE0-0xEF (0xEA=0 to prevent OTP write)
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0,  // 0xF0-0xFF
    },
    // Read command lengths
    {
        0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // 0x00-0x0F
        0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0,  // 0x10-0x1F
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // 0x20-0x2F
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // 0x30-0x3F
        0, 0, 0, 3, 3, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 3,  // 0x40-0x4F
        0, 3, 0, 0, 0, 3, 0, 3, 3, 3, 0, 0, 0, 0, 0, 0,  // 0x50-0x5F
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0,  // 0x60-0x6F
        0, 0, 0, 0, 0, 0, 0, 0, 2, 3, 2, 2, 2, 2, 2, 2,  // 0x70-0x7F
        2, 0, 0, 0, 0, 0, 7, 0, 3, 0, 0, 3, 3, 3, 3, 0,  // 0x80-0x8F
        0, 0, 0, 0, 0, 0, 0, 3, 2, 5, 9, 3, 0, 0, 0, 0,  // 0x90-0x9F
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // 0xA0-0xAF
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // 0xB0-0xBF
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // 0xC0-0xCF
        2, 2, 0, 3, 3, 3, 3, 3, 3, 3, 2, 3, 3, 2, 3, 3,  // 0xD0-0xDF
        3, 3, 3, 3, 2, 3, 3, 3, 3, 3, 0, 2, 0, 3, 4, 3,  // 0xE0-0xEF
        3, 3, 4, 3, 3, 3, 3, 3, 0, 3, 0, 0, 0, 0, 0, 0,  // 0xF0-0xFF
    }
};

/*******************************************************************************
 * PMBus Command Definitions
 ******************************************************************************/
#define CMD_OPERATION           0x01
#define CMD_CLEAR_FAULTS        0x03
#define CMD_CAPABILITY          0x19
#define CMD_VOUT_OV_WARN_LIMIT  0x42
#define CMD_VOUT_UV_WARN_LIMIT  0x43
#define CMD_STATUS_BYTE         0x78
#define CMD_STATUS_WORD         0x79
#define CMD_READ_VIN            0x88
#define CMD_READ_VOUT           0x8B
#define CMD_RESTART             0xEC
#define CMD_WRITE_OTP           0xEA  // DANGEROUS - disabled in table

/*******************************************************************************
 * Global State (simulated PMBus device)
 ******************************************************************************/
static uint8_t pmbus_registers[256][4];  // Register storage (max 4 bytes per reg)
static bool device_initialized = false;
static uint8_t operation_mode = 0x00;

/*******************************************************************************
 * Surface Check Points (demo-only)
 ******************************************************************************/
typedef struct {
    int buffer_overflow_attempts;
    int invalid_cmd_attempts;
    int otp_write_attempts;
    int boundary_violations;
} vuln_stats_t;

static vuln_stats_t stats = {0};

/*******************************************************************************
 * Initialize PMBus Device State
 ******************************************************************************/
void pmbus_init(void) {
    memset(pmbus_registers, 0, sizeof(pmbus_registers));
    
    // Set default register values (from XDP701 datasheet)
    pmbus_registers[CMD_CAPABILITY][0] = 0x30;  // Page, write protect, packet error check
    pmbus_registers[CMD_STATUS_BYTE][0] = 0x00;
    pmbus_registers[CMD_STATUS_WORD][0] = 0x00;
    pmbus_registers[CMD_STATUS_WORD][1] = 0x00;
    
    device_initialized = true;
}

/*******************************************************************************
 * PMBus Command Parser - PRIMARY FUZZ TARGET
 * 
 * This function parses and handles incoming PMBus commands.
 * FUZZING SURFACE (demo-only):
 *   - Buffer length validation
 *   - Command code validation
 *   - Data range validation
 *   - State-dependent command acceptance
 ******************************************************************************/
int pmbus_handle_command(const uint8_t* data, size_t len) {
    if (!device_initialized) {
        pmbus_init();
    }
    
    // Minimum packet: 1 byte (command only for send-byte)
    if (len < 1) {
        return -1;  // Invalid packet
    }
    
    uint8_t cmd = data[0];
    uint8_t expected_write_len = PMBus_Write_Read_Length[0][cmd];
    
    // BUG CHECK 1: Invalid command (length = 0 means unsupported)
    if (expected_write_len == 0) {
        stats.invalid_cmd_attempts++;
        
        // POTENTIAL BUG SURFACE: What if firmware doesn't check this?
        // Some implementations may process invalid commands anyway
        #ifdef ALLOW_INVALID_COMMANDS
        // Process anyway - dangerous!
        return 0;
        #else
        return -2;  // Invalid command
        #endif
    }
    
    // BUG CHECK 2: Buffer length mismatch
    // BUG SURFACE (demo-only): If len > expected, extra bytes may overflow
    if (len > expected_write_len) {
        stats.buffer_overflow_attempts++;
        
        // POTENTIAL OVERFLOW: Copy without bounds check
        #ifdef VULNERABLE_MEMCPY
        memcpy(pmbus_registers[cmd], &data[1], len - 1);  // OVERFLOW!
        #else
        // Safe: only copy expected length
        if (len > 1 && expected_write_len > 1) {
            size_t copy_len = expected_write_len - 1;
            if (copy_len > 4) copy_len = 4;  // Our register size limit
            memcpy(pmbus_registers[cmd], &data[1], copy_len);
        }
        #endif
    }
    
    // BUG CHECK 3: OTP Write Attempt (extremely dangerous)
    if (cmd == CMD_WRITE_OTP) {
        stats.otp_write_attempts++;
        // In real firmware, this could brick the device!
        // Our table has 0 for this command, but check anyway
        return -3;  // OTP write blocked
    }
    
    // BUG CHECK 4: Boundary value validation
    // VOLTAGE_LIMITS example:
    if (cmd == CMD_VOUT_OV_WARN_LIMIT || cmd == CMD_VOUT_UV_WARN_LIMIT) {
        if (len >= 3) {
            uint16_t value = (data[2] << 8) | data[1];
            
            // XDP701 valid range: 0x0000 - 0xFFFF but logical limits exist
            // Overvoltage warning should be > undervoltage
            if (cmd == CMD_VOUT_OV_WARN_LIMIT && value < 0x0100) {
                stats.boundary_violations++;
                // Allowing very low OV limit could cause spurious faults
            }
            if (cmd == CMD_VOUT_UV_WARN_LIMIT && value > 0xFF00) {
                stats.boundary_violations++;
                // UV limit too high - may never trigger fault protection
            }
        }
    }
    
    // Process valid command
    switch (cmd) {
        case CMD_OPERATION:
            if (len >= 2) {
                operation_mode = data[1];
            }
            break;
            
        case CMD_CLEAR_FAULTS:
            // Reset all status registers
            pmbus_registers[CMD_STATUS_BYTE][0] = 0x00;
            pmbus_registers[CMD_STATUS_WORD][0] = 0x00;
            pmbus_registers[CMD_STATUS_WORD][1] = 0x00;
            break;
            
        case CMD_RESTART:
            // Reset device - could cause issues if called during operation
            pmbus_init();
            break;
            
        default:
            // Store data in register
            if (len > 1 && expected_write_len > 1) {
                size_t copy_len = expected_write_len - 1;
                if (copy_len > 4) copy_len = 4;
                memcpy(pmbus_registers[cmd], &data[1], copy_len);
            }
            break;
    }
    
    return 0;  // Success
}

/*******************************************************************************
 * AFL++ Fuzz Target Entry Point
 * 
 * Uses standard file-input mode (compatible with afl-gcc)
 * For persistent mode, rebuild with afl-clang-fast
 ******************************************************************************/
int main(int argc, char** argv) {
    uint8_t buf[256];
    size_t len;
    
    if (argc < 2) {
        // Read from stdin if no file argument (for AFL++ stdin mode)
        len = fread(buf, 1, sizeof(buf), stdin);
    } else {
        FILE* f = fopen(argv[1], "rb");
        if (!f) {
            perror("fopen");
            return 1;
        }
        len = fread(buf, 1, sizeof(buf), f);
        fclose(f);
    }
    
    if (len > 0 && len < 256) {
        pmbus_handle_command(buf, len);
    }
    
    return 0;
}
