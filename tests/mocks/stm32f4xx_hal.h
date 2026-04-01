/**
  * @file    stm32f4xx_hal.h
  * @brief   Minimal mock HAL header for host-side unit testing
  *
  * Provides just enough type definitions to compile bq76920.c on
  * x86/ARM Mac without the real STM32 HAL.
  */
#ifndef STM32F4XX_HAL_H_MOCK
#define STM32F4XX_HAL_H_MOCK

#include <stdint.h>
#include <stddef.h>

#define I2C_MEMADD_SIZE_8BIT  1U

/* HAL status type */
typedef enum
{
  HAL_OK       = 0x00U,
  HAL_ERROR    = 0x01U,
  HAL_BUSY     = 0x02U,
  HAL_TIMEOUT  = 0x03U
} HAL_StatusTypeDef;

/* Minimal I2C handle -- only the fields bq76920.c touches */
typedef struct
{
  void *Instance;
} I2C_HandleTypeDef;

/* I2C function stubs -- implemented in mock_hal_i2c.c */
HAL_StatusTypeDef HAL_I2C_Master_Transmit(I2C_HandleTypeDef *hi2c,
                                           uint16_t DevAddress,
                                           uint8_t *pData,
                                           uint16_t Size,
                                           uint32_t Timeout);

HAL_StatusTypeDef HAL_I2C_Master_Receive(I2C_HandleTypeDef *hi2c,
                                          uint16_t DevAddress,
                                          uint8_t *pData,
                                          uint16_t Size,
                                          uint32_t Timeout);

HAL_StatusTypeDef HAL_I2C_Mem_Read(I2C_HandleTypeDef *hi2c,
                                    uint16_t DevAddress,
                                    uint16_t MemAddress,
                                    uint16_t MemAddSize,
                                    uint8_t *pData,
                                    uint16_t Size,
                                    uint32_t Timeout);

HAL_StatusTypeDef HAL_I2C_Mem_Write(I2C_HandleTypeDef *hi2c,
                                     uint16_t DevAddress,
                                     uint16_t MemAddress,
                                     uint16_t MemAddSize,
                                     uint8_t *pData,
                                     uint16_t Size,
                                     uint32_t Timeout);

HAL_StatusTypeDef HAL_I2C_IsDeviceReady(I2C_HandleTypeDef *hi2c,
                                         uint16_t DevAddress,
                                         uint32_t Trials,
                                         uint32_t Timeout);

#endif /* STM32F4XX_HAL_H_MOCK */
