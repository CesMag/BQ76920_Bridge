/**
  * @file    mock_hal_i2c.h
  * @brief   Mock I2C control API for unit tests
  */
#ifndef MOCK_HAL_I2C_H
#define MOCK_HAL_I2C_H

#include "stm32f4xx_hal.h"

/** @brief Reset all mock state (call in setUp) */
void MockI2C_Reset(void);

/** @brief Pre-load a receive response (data the mock will return on next HAL_I2C_Master_Receive) */
void MockI2C_ExpectReceive(const uint8_t *data, uint16_t size, HAL_StatusTypeDef status);

/** @brief Pre-load a transmit return status */
void MockI2C_ExpectTransmitStatus(HAL_StatusTypeDef status);

/** @brief Pre-load a device-ready probe result */
void MockI2C_ExpectDeviceReady(uint16_t addr, HAL_StatusTypeDef status);

/** @brief Pre-load a memory read response for a register address */
void MockI2C_ExpectMemRead(uint16_t addr, uint16_t reg,
                           const uint8_t *data, uint16_t size,
                           HAL_StatusTypeDef status);

/** @brief Pre-load an expected memory write for a register address */
void MockI2C_ExpectMemWrite(uint16_t addr, uint16_t reg,
                            const uint8_t *data, uint16_t size,
                            HAL_StatusTypeDef status);

/** @brief Get the number of transmit calls recorded */
uint32_t MockI2C_GetTransmitCount(void);

/** @brief Get the total number of recorded I2C transactions */
uint32_t MockI2C_GetTransactionCount(void);

typedef struct
{
  uint16_t addr;
  uint16_t reg;
  uint8_t  data[8];
  uint16_t size;
  uint8_t  op;
} MockI2C_Transaction_t;

/** @brief Get a recorded transmit transaction by index */
const MockI2C_Transaction_t *MockI2C_GetTransaction(uint32_t index);

#endif /* MOCK_HAL_I2C_H */
