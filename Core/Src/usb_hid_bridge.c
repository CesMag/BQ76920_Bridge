/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : usb_hid_bridge.c
  * @brief          : EV2300 USB HID protocol emulation -- transparent I2C adapter
  ******************************************************************************
  *
  * Emulates the TI EV2300 USB-to-SMBus adapter. The bridge is a transparent
  * I2C pass-through: every packet from the host includes the target I2C
  * address, and the bridge forwards it directly to the bus via HAL I2C.
  * No device-specific knowledge is needed -- bqStudio / Python driver
  * handles all protocol details.
  *
  * Write operations are two-phase: host sends the write command (buffered),
  * then sends CMD_SUBMIT (0x80) to trigger the actual I2C transaction.
  *
  * Protocol reference:
  *   - scpi-instrument-toolkit/lab_instruments/src/ev2300.py
  *   - https://locked.cv/posts/1---reverse-engineering-the-ti-ev2300/
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "usb_hid_bridge.h"
#include "usb_device.h"
#include "i2c.h"
#include <string.h>

/* External variables --------------------------------------------------------*/
extern USBD_HandleTypeDef hUsbDeviceFS;

/* Private defines -----------------------------------------------------------*/

#define MAX_WRITE_DATA  56U
#define I2C_TIMEOUT     100U

/* Private types -------------------------------------------------------------*/

typedef struct
{
  uint8_t  active;
  uint8_t  cmd;
  uint16_t i2cAddr;
  uint8_t  reg;
  uint8_t  data[MAX_WRITE_DATA];
  uint8_t  dataLen;
} PendingWrite_t;

/* Private variables ---------------------------------------------------------*/

static volatile uint8_t cmdPending = 0U;
static uint8_t cmdBuffer[BRIDGE_REPORT_SIZE];
static uint8_t rspBuffer[BRIDGE_REPORT_SIZE];
static PendingWrite_t pendingWrite;

/* Private function prototypes -----------------------------------------------*/

static uint8_t EV2300_CRC8(const uint8_t *data, uint8_t len);
static void EV2300_BuildResponse(uint8_t cmd, uint8_t success,
                                  const uint8_t *payload, uint8_t payloadLen);
static void EV2300_SendResponse(void);
static void Handle_ReadByte(uint16_t addr, uint8_t reg);
static void Handle_ReadWord(uint16_t addr, uint8_t reg);
static void Handle_ReadBlock(uint16_t addr, uint8_t reg);
static void Handle_WriteCommand(uint8_t cmd, const uint8_t *payload, uint8_t payloadLen);
static void Handle_Submit(void);
static void Handle_DeviceInfo(void);

/* Exported functions --------------------------------------------------------*/

/**
  * @brief  Initialise the EV2300 emulation bridge layer
  * @param  bms  Pointer to BQ76920_t handle (unused by bridge, kept for API compat)
  * @retval None
  */
void Bridge_Init(BQ76920_t *bms)
{
  (void)bms;
  cmdPending = 0U;
  memset(&pendingWrite, 0, sizeof(pendingWrite));
  USBD_HID_OutEventCallback = Bridge_HID_OutCallback;
}

/**
  * @brief  USB HID OUT callback (called from USB interrupt context)
  */
void Bridge_HID_OutCallback(uint8_t *buf, uint32_t len)
{
  if (cmdPending == 0U)
  {
    uint32_t copyLen = (len > BRIDGE_REPORT_SIZE) ? BRIDGE_REPORT_SIZE : len;
    memcpy(cmdBuffer, buf, copyLen);
    cmdPending = 1U;
  }
}

/**
  * @brief  Process a pending HID command (call from main loop)
  */
void Bridge_ProcessCommand(void)
{
  if (cmdPending == 0U)
  {
    return;
  }

  uint8_t marker = cmdBuffer[1];
  uint8_t cmd    = cmdBuffer[2];
  uint8_t plen   = cmdBuffer[6];

  if (marker != EV2300_FRAME_MARKER)
  {
    EV2300_BuildResponse(EV2300_CMD_ERROR, 0U, NULL, 0U);
    EV2300_SendResponse();
    cmdPending = 0U;
    return;
  }

  /* Extract I2C address and register from payload */
  uint16_t i2cAddr = 0U;
  uint8_t  reg = 0U;

  if (plen >= 1U && cmd != EV2300_CMD_SUBMIT)
  {
    i2cAddr = (uint16_t)cmdBuffer[7];
    if (plen >= 2U)
    {
      reg = cmdBuffer[8];
    }
  }

  switch (cmd)
  {
    case EV2300_CMD_READ_WORD:
      Handle_ReadWord(i2cAddr, reg);
      break;

    case EV2300_CMD_READ_BLOCK:
      Handle_ReadBlock(i2cAddr, reg);
      break;

    case EV2300_CMD_READ_BYTE:
      Handle_ReadByte(i2cAddr, reg);
      break;

    case EV2300_CMD_WRITE_WORD:
    case EV2300_CMD_WRITE_BLOCK:
    case EV2300_CMD_WRITE_BYTE:
    case EV2300_CMD_SEND_BYTE:
      Handle_WriteCommand(cmd, &cmdBuffer[7], plen);
      break;

    case EV2300_CMD_SUBMIT:
      Handle_Submit();
      break;

    case EV2300_CMD_DEVICE_INFO:
      Handle_DeviceInfo();
      break;

    default:
      EV2300_BuildResponse(EV2300_CMD_ERROR, 0U, NULL, 0U);
      EV2300_SendResponse();
      break;
  }

  cmdPending = 0U;
}

/* Private functions ---------------------------------------------------------*/

/**
  * @brief  CRC-8 (poly 0x07) for EV2300 packet framing
  */
static uint8_t EV2300_CRC8(const uint8_t *data, uint8_t len)
{
  uint8_t crc = 0x00U;
  for (uint8_t i = 0U; i < len; i++)
  {
    crc ^= data[i];
    for (uint8_t bit = 0U; bit < 8U; bit++)
    {
      crc = (crc & 0x80U) ? (uint8_t)((crc << 1U) ^ 0x07U) : (uint8_t)(crc << 1U);
    }
  }
  return crc;
}

/**
  * @brief  Build an EV2300-format response packet
  */
static void EV2300_BuildResponse(uint8_t cmd, uint8_t success,
                                  const uint8_t *payload, uint8_t payloadLen)
{
  memset(rspBuffer, 0, BRIDGE_REPORT_SIZE);

  uint8_t respCmd = success ? (cmd | EV2300_RESP_FLAG) : EV2300_CMD_ERROR;
  uint8_t totalLen = (uint8_t)(2U + 1U + 3U + 1U + payloadLen + 1U + 1U);

  rspBuffer[0] = totalLen;
  rspBuffer[1] = EV2300_FRAME_MARKER;
  rspBuffer[2] = respCmd;
  rspBuffer[6] = payloadLen;

  if (payloadLen > 0U && payload != NULL)
  {
    memcpy(&rspBuffer[7], payload, payloadLen);
  }

  uint8_t crcEnd = (uint8_t)(7U + payloadLen);
  rspBuffer[crcEnd] = EV2300_CRC8(&rspBuffer[2], (uint8_t)(crcEnd - 2U));
  rspBuffer[crcEnd + 1U] = EV2300_FRAME_END;
}

static void EV2300_SendResponse(void)
{
  USBD_HID_SendReport(&hUsbDeviceFS, rspBuffer, BRIDGE_REPORT_SIZE);
}

/**
  * @brief  Handle CMD_READ_BYTE (0x03) -- raw HAL I2C read, 1 byte
  */
static void Handle_ReadByte(uint16_t addr, uint8_t reg)
{
  uint8_t val;
  HAL_StatusTypeDef st = HAL_I2C_Mem_Read(&hi2c1, addr, reg,
                                           I2C_MEMADD_SIZE_8BIT,
                                           &val, 1U, I2C_TIMEOUT);
  if (st == HAL_OK)
  {
    uint8_t payload[2] = {(uint8_t)addr, val};
    EV2300_BuildResponse(EV2300_CMD_READ_BYTE, 1U, payload, 2U);
  }
  else
  {
    EV2300_BuildResponse(EV2300_CMD_READ_BYTE, 0U, NULL, 0U);
  }
  EV2300_SendResponse();
}

/**
  * @brief  Handle CMD_READ_WORD (0x01) -- raw HAL I2C read, 2 bytes
  */
static void Handle_ReadWord(uint16_t addr, uint8_t reg)
{
  uint8_t buf[2];
  HAL_StatusTypeDef st = HAL_I2C_Mem_Read(&hi2c1, addr, reg,
                                           I2C_MEMADD_SIZE_8BIT,
                                           buf, 2U, I2C_TIMEOUT);
  if (st == HAL_OK)
  {
    uint8_t payload[3] = {(uint8_t)addr, buf[0], buf[1]};
    EV2300_BuildResponse(EV2300_CMD_READ_WORD, 1U, payload, 3U);
  }
  else
  {
    EV2300_BuildResponse(EV2300_CMD_READ_WORD, 0U, NULL, 0U);
  }
  EV2300_SendResponse();
}

/**
  * @brief  Handle CMD_READ_BLOCK (0x02) -- raw HAL I2C read, N bytes
  */
static void Handle_ReadBlock(uint16_t addr, uint8_t reg)
{
  uint8_t data[32];
  uint8_t maxRead = 32U;

  HAL_StatusTypeDef st = HAL_I2C_Mem_Read(&hi2c1, addr, reg,
                                           I2C_MEMADD_SIZE_8BIT,
                                           data, maxRead, I2C_TIMEOUT);
  if (st == HAL_OK)
  {
    /* Payload: [addr_echo, block_len, data...] */
    uint8_t payload[34];
    payload[0] = (uint8_t)addr;
    payload[1] = maxRead;
    memcpy(&payload[2], data, maxRead);
    EV2300_BuildResponse(EV2300_CMD_READ_BLOCK, 1U, payload, (uint8_t)(2U + maxRead));
  }
  else
  {
    EV2300_BuildResponse(EV2300_CMD_READ_BLOCK, 0U, NULL, 0U);
  }
  EV2300_SendResponse();
}

/**
  * @brief  Handle write commands (0x04-0x07) -- buffer until SUBMIT
  */
static void Handle_WriteCommand(uint8_t cmd, const uint8_t *payload, uint8_t payloadLen)
{
  if (payloadLen < 2U)
  {
    EV2300_BuildResponse(cmd, 0U, NULL, 0U);
    EV2300_SendResponse();
    return;
  }

  pendingWrite.active  = 1U;
  pendingWrite.cmd     = cmd;
  pendingWrite.i2cAddr = (uint16_t)payload[0];
  pendingWrite.reg     = payload[1];
  pendingWrite.dataLen = 0U;

  switch (cmd)
  {
    case EV2300_CMD_WRITE_BYTE:
      if (payloadLen >= 3U)
      {
        pendingWrite.data[0] = payload[2];
        pendingWrite.dataLen = 1U;
      }
      break;

    case EV2300_CMD_WRITE_WORD:
      if (payloadLen >= 4U)
      {
        pendingWrite.data[0] = payload[2];
        pendingWrite.data[1] = payload[3];
        pendingWrite.dataLen = 2U;
      }
      break;

    case EV2300_CMD_WRITE_BLOCK:
      if (payloadLen >= 3U)
      {
        uint8_t blockLen = payload[2];
        if (blockLen > MAX_WRITE_DATA) { blockLen = MAX_WRITE_DATA; }
        if (payloadLen >= (uint8_t)(3U + blockLen))
        {
          memcpy(pendingWrite.data, &payload[3], blockLen);
          pendingWrite.dataLen = blockLen;
        }
      }
      break;

    case EV2300_CMD_SEND_BYTE:
      pendingWrite.dataLen = 0U;
      break;

    default:
      break;
  }

  /* Acknowledge write command (host expects response before SUBMIT) */
  EV2300_BuildResponse(cmd, 1U, NULL, 0U);
  EV2300_SendResponse();
}

/**
  * @brief  Handle CMD_SUBMIT (0x80) -- execute the pending write via raw HAL I2C
  */
static void Handle_Submit(void)
{
  if (pendingWrite.active == 0U)
  {
    EV2300_BuildResponse(EV2300_CMD_SUBMIT, 1U, NULL, 0U);
    EV2300_SendResponse();
    return;
  }

  HAL_StatusTypeDef st = HAL_OK;

  switch (pendingWrite.cmd)
  {
    case EV2300_CMD_WRITE_BYTE:
      if (pendingWrite.dataLen >= 1U)
      {
        st = HAL_I2C_Mem_Write(&hi2c1, pendingWrite.i2cAddr, pendingWrite.reg,
                                I2C_MEMADD_SIZE_8BIT,
                                &pendingWrite.data[0], 1U, I2C_TIMEOUT);
      }
      break;

    case EV2300_CMD_WRITE_WORD:
      if (pendingWrite.dataLen >= 2U)
      {
        st = HAL_I2C_Mem_Write(&hi2c1, pendingWrite.i2cAddr, pendingWrite.reg,
                                I2C_MEMADD_SIZE_8BIT,
                                pendingWrite.data, 2U, I2C_TIMEOUT);
      }
      break;

    case EV2300_CMD_WRITE_BLOCK:
      if (pendingWrite.dataLen > 0U)
      {
        st = HAL_I2C_Mem_Write(&hi2c1, pendingWrite.i2cAddr, pendingWrite.reg,
                                I2C_MEMADD_SIZE_8BIT,
                                pendingWrite.data, pendingWrite.dataLen, I2C_TIMEOUT);
      }
      break;

    case EV2300_CMD_SEND_BYTE:
    {
      /* Send Byte: transmit just the register/command byte, no data */
      uint8_t cmdByte = pendingWrite.reg;
      st = HAL_I2C_Master_Transmit(&hi2c1, pendingWrite.i2cAddr,
                                    &cmdByte, 1U, I2C_TIMEOUT);
      break;
    }

    default:
      st = HAL_ERROR;
      break;
  }

  pendingWrite.active = 0U;

  EV2300_BuildResponse(EV2300_CMD_SUBMIT, (st == HAL_OK) ? 1U : 0U, NULL, 0U);
  EV2300_SendResponse();
}

/**
  * @brief  Handle CMD_DEVICE_INFO (0x70) -- return adapter identification
  * @note   bqStudio may probe this during device discovery.
  */
static void Handle_DeviceInfo(void)
{
  /* Return a minimal success response. The real EV2300 returns 170 bytes
     of USB descriptor info. For now, return product string in payload. */
  static const uint8_t info[] = "EV2300A FW:2.0a/STM32F405";
  uint8_t len = (uint8_t)(sizeof(info) - 1U);
  EV2300_BuildResponse(EV2300_CMD_DEVICE_INFO, 1U, info, len);
  EV2300_SendResponse();
}
