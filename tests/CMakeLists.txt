cmake_minimum_required(VERSION 3.22)
project(BQ76920_Bridge_Tests C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

enable_testing()

# Paths
set(UNITY_DIR ${CMAKE_CURRENT_SOURCE_DIR}/unity)
set(MOCK_DIR ${CMAKE_CURRENT_SOURCE_DIR}/mocks)
set(PROJECT_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/..)
set(CORE_INC ${PROJECT_ROOT}/Core/Inc)
set(CORE_SRC ${PROJECT_ROOT}/Core/Src)

# Unity library
add_library(unity STATIC ${UNITY_DIR}/unity.c)
target_include_directories(unity PUBLIC ${UNITY_DIR})

# Mock HAL library
add_library(mock_hal STATIC ${MOCK_DIR}/mock_hal_i2c.c)
target_include_directories(mock_hal PUBLIC ${MOCK_DIR})

# BQ76920 driver compiled for host (uses mock HAL instead of real HAL)
add_library(bq76920_host STATIC ${CORE_SRC}/bq76920.c)
target_include_directories(bq76920_host PUBLIC ${CORE_INC})
target_include_directories(bq76920_host PRIVATE ${MOCK_DIR})
target_link_libraries(bq76920_host PRIVATE mock_hal m)

# ---- Test: CRC-8 ----
add_executable(test_crc8 unit/test_bq76920_crc8.c)
target_include_directories(test_crc8 PRIVATE ${CORE_INC} ${MOCK_DIR})
target_link_libraries(test_crc8 PRIVATE unity bq76920_host mock_hal m)
add_test(NAME CRC8 COMMAND test_crc8)

# ---- Test: Voltage conversion ----
add_executable(test_voltage unit/test_bq76920_voltage.c)
target_include_directories(test_voltage PRIVATE ${CORE_INC} ${MOCK_DIR})
target_link_libraries(test_voltage PRIVATE unity bq76920_host mock_hal m)
add_test(NAME Voltage COMMAND test_voltage)
