/*
 * Copyright (c) The Libre Solar Project Contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef HELPER_H
#define HELPER_H

/**
 * @file
 * @brief General helper functions
 */

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#if defined(IFX_CFG_HOST_FUZZ) || defined(__INTELLISENSE__)
/*
 * Host-fuzz build: avoid pulling Zephyr headers.
 * Also used for VS Code Intellisense.
 */
#define LOG_DBG(...) ((void)0)
#define LOG_INF(...) ((void)0)
#define LOG_WRN(...) ((void)0)
#define LOG_ERR(...) ((void)0)
#define LOG_MODULE_REGISTER(...)
#else
#include <zephyr/logging/log.h>
#endif

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Interpolation in a look-up table. Values of a must be monotonically increasing/decreasing
 *
 * @returns interpolated value of array b at position value_a
 */
float interpolate(const float a[], const float b[], size_t size, float value_a);

/**
 * Convert byte to bit-string
 *
 * Attention: Uses static buffer, not thread-safe
 *
 * @returns pointer to bit-string (8 characters + null-byte)
 */
const char *byte2bitstr(uint8_t b);

/**
 * @brief Check if a buffer is entirely zeroed.
 *
 * @param buf A pointer to the buffer (uint8_t*) to be checked.
 * @param size The size of the buffer in bytes.
 * @returns true if the buffer is entirely zeroed, false if not.
 */
bool is_empty(uint8_t *buf, size_t size);

#ifdef __cplusplus
}
#endif

#endif /* HELPER_H */
