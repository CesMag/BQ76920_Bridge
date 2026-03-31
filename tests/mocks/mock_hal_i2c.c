/**
  * @file    mock_hal_i2c.c
  * @brief   Configurable I2C mock for host-side unit testing
  *
  * Records transmit calls and returns pre-configured data for receive calls.
  * Tests configure the mock before each test case, then verify interactions.
  */
#include "stm32f4xx_hal.h"
#include <string.h>

/* Maximum number of I2C transactions to record per test */
#define MOCK_I2C_MAX_TRANSACTIONS  32
#define MOCK_I2C_MAX_DATA          8

/* Transaction record */
typedef struct
{
  uint16_t addr;
  uint8_t  data[MOCK_I2C_MAX_DATA];
  uint16_t size;
  uint8_t  isTransmit; /* 1 = transmit, 0 = receive */
} MockI2C_Transaction_t;

/* Mock state */
static MockI2C_Transaction_t mockTxLog[MOCK_I2C_MAX_TRANSACTIONS];
static uint32_t mockTxCount = 0U;

/* Pre-loaded receive responses */
static uint8_t  mockRxData[MOCK_I2C_MAX_TRANSACTIONS][MOCK_I2C_MAX_DATA];
static uint16_t mockRxSize[MOCK_I2C_MAX_TRANSACTIONS];
static HAL_StatusTypeDef mockRxStatus[MOCK_I2C_MAX_TRANSACTIONS];
static uint32_t mockRxIndex = 0U;
static uint32_t mockRxCount = 0U;

/* Pre-loaded transmit return status */
static HAL_StatusTypeDef mockTxStatus[MOCK_I2C_MAX_TRANSACTIONS];
static uint32_t mockTxStatusCount = 0U;
static uint32_t mockTxStatusIndex = 0U;

/* ---- Mock control API --------------------------------------------------- */

void MockI2C_Reset(void)
{
  memset(mockTxLog, 0, sizeof(mockTxLog));
  mockTxCount = 0U;
  memset(mockRxData, 0, sizeof(mockRxData));
  memset(mockRxSize, 0, sizeof(mockRxSize));
  mockRxIndex = 0U;
  mockRxCount = 0U;
  mockTxStatusCount = 0U;
  mockTxStatusIndex = 0U;

  for (uint32_t i = 0U; i < MOCK_I2C_MAX_TRANSACTIONS; i++)
  {
    mockRxStatus[i] = HAL_OK;
    mockTxStatus[i] = HAL_OK;
  }
}

void MockI2C_ExpectReceive(const uint8_t *data, uint16_t size, HAL_StatusTypeDef status)
{
  if (mockRxCount < MOCK_I2C_MAX_TRANSACTIONS)
  {
    memcpy(mockRxData[mockRxCount], data, size);
    mockRxSize[mockRxCount] = size;
    mockRxStatus[mockRxCount] = status;
    mockRxCount++;
  }
}

void MockI2C_ExpectTransmitStatus(HAL_StatusTypeDef status)
{
  if (mockTxStatusCount < MOCK_I2C_MAX_TRANSACTIONS)
  {
    mockTxStatus[mockTxStatusCount] = status;
    mockTxStatusCount++;
  }
}

uint32_t MockI2C_GetTransmitCount(void)
{
  return mockTxCount;
}

const MockI2C_Transaction_t *MockI2C_GetTransaction(uint32_t index)
{
  if (index < mockTxCount)
  {
    return &mockTxLog[index];
  }
  return NULL;
}

/* ---- HAL stub implementations ------------------------------------------- */

HAL_StatusTypeDef HAL_I2C_Master_Transmit(I2C_HandleTypeDef *hi2c,
                                           uint16_t DevAddress,
                                           uint8_t *pData,
                                           uint16_t Size,
                                           uint32_t Timeout)
{
  (void)hi2c;
  (void)Timeout;

  if (mockTxCount < MOCK_I2C_MAX_TRANSACTIONS)
  {
    mockTxLog[mockTxCount].addr = DevAddress;
    mockTxLog[mockTxCount].isTransmit = 1U;
    mockTxLog[mockTxCount].size = Size;
    uint16_t copySize = (Size > MOCK_I2C_MAX_DATA) ? MOCK_I2C_MAX_DATA : Size;
    memcpy(mockTxLog[mockTxCount].data, pData, copySize);
    mockTxCount++;
  }

  /* Return pre-configured status */
  HAL_StatusTypeDef st = HAL_OK;
  if (mockTxStatusIndex < mockTxStatusCount)
  {
    st = mockTxStatus[mockTxStatusIndex];
    mockTxStatusIndex++;
  }
  return st;
}

HAL_StatusTypeDef HAL_I2C_Master_Receive(I2C_HandleTypeDef *hi2c,
                                          uint16_t DevAddress,
                                          uint8_t *pData,
                                          uint16_t Size,
                                          uint32_t Timeout)
{
  (void)hi2c;
  (void)DevAddress;
  (void)Timeout;

  if (mockRxIndex < mockRxCount)
  {
    uint16_t copySize = (Size < mockRxSize[mockRxIndex]) ? Size : mockRxSize[mockRxIndex];
    memcpy(pData, mockRxData[mockRxIndex], copySize);
    HAL_StatusTypeDef st = mockRxStatus[mockRxIndex];
    mockRxIndex++;
    return st;
  }

  /* No more pre-loaded responses */
  return HAL_ERROR;
}
