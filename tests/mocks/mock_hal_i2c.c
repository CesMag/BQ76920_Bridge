/**
  * @file    mock_hal_i2c.c
  * @brief   Configurable I2C mock for host-side unit testing
  */
#include "mock_hal_i2c.h"
#include <string.h>

#define MOCK_I2C_MAX_TRANSACTIONS  32U
#define MOCK_I2C_MAX_DATA          8U

enum
{
  MOCK_OP_TX = 1U,
  MOCK_OP_RX = 2U,
  MOCK_OP_MEM_READ = 3U,
  MOCK_OP_MEM_WRITE = 4U,
  MOCK_OP_READY = 5U
};

typedef struct
{
  uint16_t addr;
  uint16_t reg;
  uint8_t  data[MOCK_I2C_MAX_DATA];
  uint16_t size;
  HAL_StatusTypeDef status;
} MockMemExpectation_t;

typedef struct
{
  uint16_t addr;
  HAL_StatusTypeDef status;
} MockReadyExpectation_t;

static MockI2C_Transaction_t mockLog[MOCK_I2C_MAX_TRANSACTIONS];
static uint32_t mockLogCount = 0U;

static uint8_t  mockRxData[MOCK_I2C_MAX_TRANSACTIONS][MOCK_I2C_MAX_DATA];
static uint16_t mockRxSize[MOCK_I2C_MAX_TRANSACTIONS];
static HAL_StatusTypeDef mockRxStatus[MOCK_I2C_MAX_TRANSACTIONS];
static uint32_t mockRxIndex = 0U;
static uint32_t mockRxCount = 0U;

static HAL_StatusTypeDef mockTxStatus[MOCK_I2C_MAX_TRANSACTIONS];
static uint32_t mockTxStatusCount = 0U;
static uint32_t mockTxStatusIndex = 0U;

static MockMemExpectation_t mockMemReads[MOCK_I2C_MAX_TRANSACTIONS];
static uint32_t mockMemReadIndex = 0U;
static uint32_t mockMemReadCount = 0U;

static MockMemExpectation_t mockMemWrites[MOCK_I2C_MAX_TRANSACTIONS];
static uint32_t mockMemWriteIndex = 0U;
static uint32_t mockMemWriteCount = 0U;

static MockReadyExpectation_t mockReady[MOCK_I2C_MAX_TRANSACTIONS];
static uint32_t mockReadyIndex = 0U;
static uint32_t mockReadyCount = 0U;

static void MockI2C_Record(uint8_t op, uint16_t addr, uint16_t reg,
                           const uint8_t *data, uint16_t size)
{
  if (mockLogCount >= MOCK_I2C_MAX_TRANSACTIONS)
  {
    return;
  }

  mockLog[mockLogCount].addr = addr;
  mockLog[mockLogCount].reg = reg;
  mockLog[mockLogCount].op = op;
  mockLog[mockLogCount].size = size;
  memset(mockLog[mockLogCount].data, 0, sizeof(mockLog[mockLogCount].data));

  if (data != NULL && size > 0U)
  {
    uint16_t copySize = (size > MOCK_I2C_MAX_DATA) ? MOCK_I2C_MAX_DATA : size;
    memcpy(mockLog[mockLogCount].data, data, copySize);
  }

  mockLogCount++;
}

void MockI2C_Reset(void)
{
  memset(mockLog, 0, sizeof(mockLog));
  mockLogCount = 0U;

  memset(mockRxData, 0, sizeof(mockRxData));
  memset(mockRxSize, 0, sizeof(mockRxSize));
  mockRxIndex = 0U;
  mockRxCount = 0U;

  mockTxStatusCount = 0U;
  mockTxStatusIndex = 0U;

  memset(mockMemReads, 0, sizeof(mockMemReads));
  mockMemReadIndex = 0U;
  mockMemReadCount = 0U;

  memset(mockMemWrites, 0, sizeof(mockMemWrites));
  mockMemWriteIndex = 0U;
  mockMemWriteCount = 0U;

  memset(mockReady, 0, sizeof(mockReady));
  mockReadyIndex = 0U;
  mockReadyCount = 0U;

  for (uint32_t i = 0U; i < MOCK_I2C_MAX_TRANSACTIONS; i++)
  {
    mockRxStatus[i] = HAL_OK;
    mockTxStatus[i] = HAL_OK;
  }
}

void MockI2C_ExpectReceive(const uint8_t *data, uint16_t size, HAL_StatusTypeDef status)
{
  if (mockRxCount >= MOCK_I2C_MAX_TRANSACTIONS)
  {
    return;
  }

  if (data != NULL && size > 0U)
  {
    memcpy(mockRxData[mockRxCount], data,
           (size > MOCK_I2C_MAX_DATA) ? MOCK_I2C_MAX_DATA : size);
  }
  mockRxSize[mockRxCount] = size;
  mockRxStatus[mockRxCount] = status;
  mockRxCount++;
}

void MockI2C_ExpectTransmitStatus(HAL_StatusTypeDef status)
{
  if (mockTxStatusCount < MOCK_I2C_MAX_TRANSACTIONS)
  {
    mockTxStatus[mockTxStatusCount++] = status;
  }
}

void MockI2C_ExpectDeviceReady(uint16_t addr, HAL_StatusTypeDef status)
{
  if (mockReadyCount >= MOCK_I2C_MAX_TRANSACTIONS)
  {
    return;
  }

  mockReady[mockReadyCount].addr = addr;
  mockReady[mockReadyCount].status = status;
  mockReadyCount++;
}

void MockI2C_ExpectMemRead(uint16_t addr, uint16_t reg,
                           const uint8_t *data, uint16_t size,
                           HAL_StatusTypeDef status)
{
  if (mockMemReadCount >= MOCK_I2C_MAX_TRANSACTIONS)
  {
    return;
  }

  mockMemReads[mockMemReadCount].addr = addr;
  mockMemReads[mockMemReadCount].reg = reg;
  mockMemReads[mockMemReadCount].size = size;
  mockMemReads[mockMemReadCount].status = status;
  memset(mockMemReads[mockMemReadCount].data, 0, MOCK_I2C_MAX_DATA);
  if (data != NULL && size > 0U)
  {
    memcpy(mockMemReads[mockMemReadCount].data, data,
           (size > MOCK_I2C_MAX_DATA) ? MOCK_I2C_MAX_DATA : size);
  }
  mockMemReadCount++;
}

void MockI2C_ExpectMemWrite(uint16_t addr, uint16_t reg,
                            const uint8_t *data, uint16_t size,
                            HAL_StatusTypeDef status)
{
  if (mockMemWriteCount >= MOCK_I2C_MAX_TRANSACTIONS)
  {
    return;
  }

  mockMemWrites[mockMemWriteCount].addr = addr;
  mockMemWrites[mockMemWriteCount].reg = reg;
  mockMemWrites[mockMemWriteCount].size = size;
  mockMemWrites[mockMemWriteCount].status = status;
  memset(mockMemWrites[mockMemWriteCount].data, 0, MOCK_I2C_MAX_DATA);
  if (data != NULL && size > 0U)
  {
    memcpy(mockMemWrites[mockMemWriteCount].data, data,
           (size > MOCK_I2C_MAX_DATA) ? MOCK_I2C_MAX_DATA : size);
  }
  mockMemWriteCount++;
}

uint32_t MockI2C_GetTransmitCount(void)
{
  uint32_t count = 0U;
  for (uint32_t i = 0U; i < mockLogCount; i++)
  {
    if (mockLog[i].op == MOCK_OP_TX)
    {
      count++;
    }
  }
  return count;
}

uint32_t MockI2C_GetTransactionCount(void)
{
  return mockLogCount;
}

const MockI2C_Transaction_t *MockI2C_GetTransaction(uint32_t index)
{
  if (index < mockLogCount)
  {
    return &mockLog[index];
  }
  return NULL;
}

HAL_StatusTypeDef HAL_I2C_Master_Transmit(I2C_HandleTypeDef *hi2c,
                                          uint16_t DevAddress,
                                          uint8_t *pData,
                                          uint16_t Size,
                                          uint32_t Timeout)
{
  (void)hi2c;
  (void)Timeout;

  MockI2C_Record(MOCK_OP_TX, DevAddress, 0U, pData, Size);

  if (mockTxStatusIndex < mockTxStatusCount)
  {
    return mockTxStatus[mockTxStatusIndex++];
  }
  return HAL_OK;
}

HAL_StatusTypeDef HAL_I2C_Master_Receive(I2C_HandleTypeDef *hi2c,
                                         uint16_t DevAddress,
                                         uint8_t *pData,
                                         uint16_t Size,
                                         uint32_t Timeout)
{
  (void)hi2c;
  (void)Timeout;

  MockI2C_Record(MOCK_OP_RX, DevAddress, 0U, NULL, Size);

  if (mockRxIndex < mockRxCount)
  {
    uint16_t copySize = (Size < mockRxSize[mockRxIndex]) ? Size : mockRxSize[mockRxIndex];
    memcpy(pData, mockRxData[mockRxIndex], copySize);
    return mockRxStatus[mockRxIndex++];
  }

  return HAL_ERROR;
}

HAL_StatusTypeDef HAL_I2C_Mem_Read(I2C_HandleTypeDef *hi2c,
                                   uint16_t DevAddress,
                                   uint16_t MemAddress,
                                   uint16_t MemAddSize,
                                   uint8_t *pData,
                                   uint16_t Size,
                                   uint32_t Timeout)
{
  (void)hi2c;
  (void)MemAddSize;
  (void)Timeout;

  MockI2C_Record(MOCK_OP_MEM_READ, DevAddress, MemAddress, NULL, Size);

  if (mockMemReadIndex < mockMemReadCount)
  {
    MockMemExpectation_t *exp = &mockMemReads[mockMemReadIndex++];
    if (exp->status == HAL_OK)
    {
      uint16_t copySize = (Size < exp->size) ? Size : exp->size;
      memcpy(pData, exp->data, copySize);
    }
    return exp->status;
  }

  return HAL_ERROR;
}

HAL_StatusTypeDef HAL_I2C_Mem_Write(I2C_HandleTypeDef *hi2c,
                                    uint16_t DevAddress,
                                    uint16_t MemAddress,
                                    uint16_t MemAddSize,
                                    uint8_t *pData,
                                    uint16_t Size,
                                    uint32_t Timeout)
{
  (void)hi2c;
  (void)MemAddSize;
  (void)Timeout;

  MockI2C_Record(MOCK_OP_MEM_WRITE, DevAddress, MemAddress, pData, Size);

  if (mockMemWriteIndex < mockMemWriteCount)
  {
    return mockMemWrites[mockMemWriteIndex++].status;
  }

  return HAL_OK;
}

HAL_StatusTypeDef HAL_I2C_IsDeviceReady(I2C_HandleTypeDef *hi2c,
                                        uint16_t DevAddress,
                                        uint32_t Trials,
                                        uint32_t Timeout)
{
  (void)hi2c;
  (void)Trials;
  (void)Timeout;

  MockI2C_Record(MOCK_OP_READY, DevAddress, 0U, NULL, 0U);

  if (mockReadyIndex < mockReadyCount)
  {
    return mockReady[mockReadyIndex++].status;
  }

  return HAL_ERROR;
}
