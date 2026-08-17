/*******************************************************************************
 * File: fuzz_i2c_slave.c
 * 
 * Description: AFL++ fuzz harness for I2C Slave RX buffer parsing
 *              Part of: AI-Enhanced Fuzzing for Embedded Power Systems
 *              
 * Target: nvidia_pdb firmware - I2C slave command handler
 * 
 * Harness notes:
 * - This harness is a synthetic demo harness (host-side) used to exercise the pipeline.
 * - It is NOT a claim of real vulnerabilities in any vendor firmware.
 * - The term "vulnerability" below refers to fuzzing surfaces / test checkpoints.
 *
 * Build with AFL++:
 *   afl-gcc -o fuzz_i2c fuzz_i2c_slave.c -I../data/firmware/nvidia_pdb
 *   
 * Run:
 *   afl-fuzz -i seeds/i2c -o findings -t 1000 ./fuzz_i2c @@
 *
 * Copyright 2025 - Thesis Research
 ******************************************************************************/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>

/*******************************************************************************
 * Protocol Constants (from firmware)
 ******************************************************************************/
#define SL_RX_BUFFER_SIZE    3
#define SL_TX_BUFFER_SIZE    3

#define PACKET_SOP           0x01
#define PACKET_EOP           0x17

#define STS_CMD_DONE         0x00
#define STS_CMD_FAIL         0xFF

#define PACKET_SOP_POS       0
#define PACKET_CMD_POS       1
#define PACKET_STS_POS       1
#define PACKET_EOP_POS       2

/*******************************************************************************
 * I2C Slave State
 ******************************************************************************/
typedef enum {
    I2C_STATE_IDLE,
    I2C_STATE_RECEIVING,
    I2C_STATE_PROCESSING,
    I2C_STATE_RESPONDING
} i2c_state_t;

typedef struct {
    uint8_t rx_buffer[SL_RX_BUFFER_SIZE];
    uint8_t tx_buffer[SL_TX_BUFFER_SIZE];
    size_t rx_count;
    i2c_state_t state;
    bool write_complete;
    bool read_complete;
} i2c_slave_context_t;

static i2c_slave_context_t i2c_ctx = {0};

/*******************************************************************************
 * Surface tracking counters (demo-only)
 ******************************************************************************/
typedef struct {
    int malformed_packets;
    int buffer_overflows;
    int invalid_sop_eop;
    int state_violations;
    int unexpected_commands;
} i2c_vuln_stats_t;

static i2c_vuln_stats_t stats = {0};

/*******************************************************************************
 * Simulated GPIO State (for LED control commands)
 ******************************************************************************/
static uint8_t led_state = 0;

/*******************************************************************************
 * I2C Slave Initialization
 ******************************************************************************/
void i2c_slave_init(void) {
    memset(&i2c_ctx, 0, sizeof(i2c_ctx));
    i2c_ctx.state = I2C_STATE_IDLE;
    i2c_ctx.tx_buffer[PACKET_STS_POS] = STS_CMD_FAIL;  // Default fail status
}

/*******************************************************************************
 * Process Received I2C Data - FUZZ TARGET
 * 
 * FUZZING SURFACE (demo-only):
 *   - SOP/EOP validation (missing checks allow protocol bypass)
 *   - Buffer bounds (write beyond rx_buffer)
 *   - Command execution without full packet
 *   - State machine confusion
 ******************************************************************************/
int i2c_process_write(const uint8_t* data, size_t len) {
    // Initialize on first use
    if (i2c_ctx.state == I2C_STATE_IDLE) {
        i2c_slave_init();
    }
    
    /***************************************************************************
     * SURFACE CHECK 1: Buffer Overflow
     * 
     * The real firmware has a fixed 3-byte buffer. What happens with more?
     **************************************************************************/
    if (len > SL_RX_BUFFER_SIZE) {
        stats.buffer_overflows++;
        
        #ifdef VULNERABLE_I2C_BUFFER
        // DANGEROUS: Copy all data regardless of buffer size
        memcpy(i2c_ctx.rx_buffer, data, len);  // OVERFLOW!
        #else
        // Safe: Only copy what fits
        memcpy(i2c_ctx.rx_buffer, data, SL_RX_BUFFER_SIZE);
        #endif
        
        i2c_ctx.rx_count = SL_RX_BUFFER_SIZE;
    } else {
        memcpy(i2c_ctx.rx_buffer, data, len);
        i2c_ctx.rx_count = len;
    }
    
    /***************************************************************************
     * SURFACE CHECK 2: Protocol Format Validation
     * 
     * Does firmware require valid SOP/EOP? If not, attackers can bypass.
     **************************************************************************/
    if (len >= 3) {
        // Full packet - check SOP/EOP
        if (i2c_ctx.rx_buffer[PACKET_SOP_POS] != PACKET_SOP) {
            stats.invalid_sop_eop++;
            
            #ifdef STRICT_PROTOCOL
            return -1;  // Reject invalid SOP
            #else
            // WARNING: Processing anyway - potential bug surface
            #endif
        }
        
        if (i2c_ctx.rx_buffer[PACKET_EOP_POS] != PACKET_EOP) {
            stats.invalid_sop_eop++;
            
            #ifdef STRICT_PROTOCOL
            return -2;  // Reject invalid EOP
            #else
            // WARNING: Processing anyway - potential bug surface
            #endif
        }
    } else {
        stats.malformed_packets++;
        
        #ifdef REQUIRE_FULL_PACKET
        return -3;  // Incomplete packet
        #else
        // WARNING: Processing partial packet - dangerous!
        #endif
    }
    
    /***************************************************************************
     * SURFACE CHECK 3: Command Execution
     * 
     * Real firmware: SlaveExecuteCommand writes to GPIO based on rx_buffer[1]
     * What if rx_buffer[1] contains unexpected values?
     **************************************************************************/
    if (i2c_ctx.rx_count >= 2) {
        uint8_t cmd = i2c_ctx.rx_buffer[PACKET_CMD_POS];
        
        // The firmware directly uses this as GPIO output!
        // Cy_GPIO_Write(CYBSP_USER_LED_PORT, CYBSP_USER_LED_PIN, cmd);
        
        // Simulate command execution
        if (cmd != 0x00 && cmd != 0x01) {
            // Unexpected command value (LED should be 0 or 1)
            stats.unexpected_commands++;
            
            #ifdef STRICT_COMMAND_VALIDATION
            return -4;  // Invalid command value
            #else
            // WARNING: Executing with arbitrary value!
            led_state = cmd;
            #endif
        } else {
            led_state = cmd;
        }
        
        // Set success status
        i2c_ctx.tx_buffer[PACKET_STS_POS] = STS_CMD_DONE;
    }
    
    i2c_ctx.write_complete = true;
    return 0;
}

/*******************************************************************************
 * I2C Event Handler - SECONDARY FUZZ TARGET
 * 
 * Simulates the HandleEventsSlave callback that gets triggered on I2C events
 ******************************************************************************/
int i2c_handle_event(uint32_t event) {
    #define I2C_SLAVE_WR_CMPLT_EVENT  0x01
    #define I2C_SLAVE_RD_CMPLT_EVENT  0x02
    #define I2C_SLAVE_ERR_EVENT       0x04
    
    /***************************************************************************
     * SURFACE CHECK 4: Event Handling Race Conditions
     **************************************************************************/
    switch (event) {
        case I2C_SLAVE_WR_CMPLT_EVENT:
            if (i2c_ctx.state != I2C_STATE_RECEIVING) {
                stats.state_violations++;
                // State machine confusion - processing write in wrong state
            }
            i2c_ctx.state = I2C_STATE_PROCESSING;
            // Execute command based on received data
            break;
            
        case I2C_SLAVE_RD_CMPLT_EVENT:
            if (i2c_ctx.state != I2C_STATE_RESPONDING) {
                stats.state_violations++;
            }
            i2c_ctx.state = I2C_STATE_IDLE;
            break;
            
        case I2C_SLAVE_ERR_EVENT:
            // Error handling - reset to safe state
            i2c_slave_init();
            break;
            
        default:
            // Unknown event - should we process?
            stats.state_violations++;
            
            #ifdef HANDLE_UNKNOWN_EVENTS
            return -1;
            #endif
            break;
    }
    
    return 0;
}

/*******************************************************************************
 * Multi-Transaction Sequence Handler - ADVANCED FUZZ TARGET
 * 
 * Tests sequences of I2C transactions for stateful bugs
 ******************************************************************************/
int i2c_process_sequence(const uint8_t* data, size_t len) {
    size_t offset = 0;
    int transaction_count = 0;
    
    // Process multiple 3-byte transactions
    while (offset + 3 <= len) {
        int result = i2c_process_write(&data[offset], 3);
        
        if (result < 0) {
            // Transaction failed, but continue to find more bugs
        }
        
        offset += 3;
        transaction_count++;
        
        // Limit iterations to prevent timeout
        if (transaction_count > 100) {
            break;
        }
    }
    
    // Handle trailing bytes (partial transaction)
    if (offset < len) {
        stats.malformed_packets++;
        i2c_process_write(&data[offset], len - offset);
    }
    
    return transaction_count;
}

/*******************************************************************************
 * AFL++ Entry Point (Standard file-input mode)
 ******************************************************************************/
int main(int argc, char** argv) {
    uint8_t buf[1024];
    size_t len;
    
    if (argc < 2) {
        // Read from stdin for AFL++ stdin mode
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
    
    // Reset state and process
    i2c_slave_init();
    
    if (len > 0 && len < 1024) {
        i2c_process_sequence(buf, len);
    }
    
    return 0;
}
