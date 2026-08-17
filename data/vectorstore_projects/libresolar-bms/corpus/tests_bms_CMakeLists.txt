# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})

project(bms_common_test)

# Ensure devicetree preprocessing can find project-local dt-bindings headers.
# Required by boards/native_sim.overlay which includes dt-bindings/bms_ic/bq769x2.h.
# Zephyr's dtc preprocessor honors DTC_INCLUDE_PATH.
list(APPEND DTC_INCLUDE_PATH "${CMAKE_CURRENT_LIST_DIR}/../../include")
list(APPEND DTC_INCLUDE_PATH "${CMAKE_CURRENT_LIST_DIR}/../../include/zephyr")

# Make project headers visible (e.g., <bms/bms.h>)
zephyr_include_directories(${CMAKE_CURRENT_LIST_DIR}/../../include)

FILE(GLOB app_sources src/*.c)
target_sources(app PRIVATE ${app_sources})

target_sources(app PRIVATE ../../app/src/bms_common.c)
