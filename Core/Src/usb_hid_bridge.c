/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : usb_hid_bridge.c
  * @brief          : EV2300 USB HID protocol emulation -- transparent I2C adapter
  ******************************************************************************
  *
  * Emulates the TI EV2300 USB-to-SMBus adapter. Response codes are matched
  * exactly to the real EV2300 hardware based on protocol scan results from
  * ev2300_protocol_results.json (tested 2026-03-26 against real EV2300A).
  *
  * The real EV2300 does NOT always use cmd|0x40 for success. Many commands
  * have non-standard response codes that the TI DLLs expect.
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
static void EV2300_BuildRawResponse(uint8_t respCode,
                                     const uint8_t *payload, uint8_t payloadLen);
static void EV2300_BuildErrorResponse(void);
static void EV2300_SendResponse(void);
static void Handle_ReadByte(uint16_t addr, uint8_t reg);
static void Handle_ReadWord(uint16_t addr, uint8_t reg);
static void Handle_ReadBlock(uint16_t addr, uint8_t reg);
static void Handle_WriteCommand(uint8_t cmd, const uint8_t *payload, uint8_t payloadLen);
static void Handle_Submit(void);
static void Handle_Undocumented(uint8_t cmd);

/* Exported functions --------------------------------------------------------*/

void Bridge_Init(BQ76920_t *bms)
{
  (void)bms;
  cmdPending = 0U;
  memset(&pendingWrite, 0, sizeof(pendingWrite));
  USBD_HID_OutEventCallback = Bridge_HID_OutCallback;
}

void Bridge_HID_OutCallback(uint8_t *buf, uint32_t len)
{
  if (cmdPending == 0U)
  {
    uint32_t copyLen = (len > BRIDGE_REPORT_SIZE) ? BRIDGE_REPORT_SIZE : len;
    memcpy(cmdBuffer, buf, copyLen);
    cmdPending = 1U;
  }
}

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
    EV2300_BuildErrorResponse();
    EV2300_SendResponse();
    cmdPending = 0U;
    return;
  }

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

  /* Real EV2300 ignores I2C commands with no payload (full sweep confirmed).
   * Only process read/write if we have at least an I2C address byte. */
  if (plen == 0U && cmd != EV2300_CMD_SUBMIT && cmd != 0x70U)
  {
    /* No payload = no I2C address. Real EV2300 does not respond. */
    Handle_Undocumented(cmd);
    cmdPending = 0U;
    return;
  }

  switch (cmd)
  {
    case EV2300_CMD_READ_WORD:  /* 0x01 -> resp 0x41 */
      Handle_ReadWord(i2cAddr, reg);
      break;

    case EV2300_CMD_READ_BLOCK: /* 0x02 -> resp 0x42 or 0x46 */
      Handle_ReadBlock(i2cAddr, reg);
      break;

    case EV2300_CMD_READ_BYTE:  /* 0x03 -> resp 0x42 (NOT 0x43!) */
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

    default:
      Handle_Undocumented(cmd);
      break;
  }

  cmdPending = 0U;
}

/* Private functions ---------------------------------------------------------*/

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
  * @brief  Build response with an EXACT response code (not computed)
  * @param  respCode    Exact response byte (from real EV2300 protocol scan)
  * @param  payload     Response payload
  * @param  payloadLen  Payload length
  */
static void EV2300_BuildRawResponse(uint8_t respCode,
                                     const uint8_t *payload, uint8_t payloadLen)
{
  memset(rspBuffer, 0, BRIDGE_REPORT_SIZE);

  uint8_t totalLen = (uint8_t)(2U + 1U + 3U + 1U + payloadLen + 1U + 1U);

  rspBuffer[0] = totalLen;
  rspBuffer[1] = EV2300_FRAME_MARKER;
  rspBuffer[2] = respCode;
  rspBuffer[5] = 0x01U;  /* Real EV2300 always has 0x01 at reserved[2] */
  rspBuffer[6] = payloadLen;

  if (payloadLen > 0U && payload != NULL)
  {
    memcpy(&rspBuffer[7], payload, payloadLen);
  }

  uint8_t crcEnd = (uint8_t)(7U + payloadLen);
  rspBuffer[crcEnd] = EV2300_CRC8(&rspBuffer[2], (uint8_t)(crcEnd - 2U));
  rspBuffer[crcEnd + 1U] = EV2300_FRAME_END;
}

/**
  * @brief  Build a standard error response (0x46 with 2-byte payload)
  *         Real EV2300 always sends 0x46 with payload {0x00, 0x93}.
  *         The DLLs parse this payload for error context.
  */
static void EV2300_BuildErrorResponse(void)
{
  static const uint8_t errPayload[2] = {0x00U, 0x93U};
  EV2300_BuildRawResponse(EV2300_CMD_ERROR, errPayload, 2U);
}

static void EV2300_SendResponse(void)
{
  USBD_HID_SendReport(&hUsbDeviceFS, rspBuffer, BRIDGE_REPORT_SIZE);
}

/* ---- I2C command handlers (use exact real EV2300 response codes) --------- */

/**
  * @brief  CMD 0x03 READ_BYTE -> response code 0x42 (real EV2300 quirk)
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
    EV2300_BuildRawResponse(0x42U, payload, 2U); /* Real EV2300: 0x42, not 0x43 */
  }
  else
  {
    EV2300_BuildErrorResponse();
  }
  EV2300_SendResponse();
}

/**
  * @brief  CMD 0x01 READ_WORD -> response code 0x41
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
    EV2300_BuildRawResponse(0x41U, payload, 3U);
  }
  else
  {
    EV2300_BuildErrorResponse();
  }
  EV2300_SendResponse();
}

/**
  * @brief  CMD 0x02 READ_BLOCK -> response code 0x42
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
    uint8_t payload[34];
    payload[0] = (uint8_t)addr;
    payload[1] = maxRead;
    memcpy(&payload[2], data, maxRead);
    EV2300_BuildRawResponse(0x42U, payload, (uint8_t)(2U + maxRead));
  }
  else
  {
    EV2300_BuildErrorResponse();
  }
  EV2300_SendResponse();
}

/**
  * @brief  Handle write commands -- buffer until SUBMIT
  *         Write ack uses exact response codes from real EV2300:
  *         0x06 COMMAND -> 0xC0, 0x07 WRITE_BYTE -> 0x4E, others -> cmd|0x40
  */
static void Handle_WriteCommand(uint8_t cmd, const uint8_t *payload, uint8_t payloadLen)
{
  if (payloadLen < 2U)
  {
    EV2300_BuildErrorResponse();
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

  /* Real EV2300 write ack behavior (from dual-device diff):
   *   WRITE_WORD (0x04): returns 0x46 error (write is buffered, not executed)
   *   WRITE_BLOCK (0x05): returns 0x46 error (same as WRITE_WORD)
   *   SEND_BYTE (0x06):  returns 0x46 error
   *   WRITE_BYTE (0x07): NO RESPONSE -- host times out, then sends SUBMIT
   * bqStudio DLL interprets any 0x46 on WRITE_BYTE as I2C NACK and aborts. */
  if (cmd != EV2300_CMD_WRITE_BYTE)
  {
    uint8_t errPayload[2] = {pendingWrite.reg, 0x93U};
    EV2300_BuildRawResponse(EV2300_CMD_ERROR, errPayload, 2U);
    EV2300_SendResponse();
  }
}

/**
  * @brief  CMD 0x80 SUBMIT -> execute pending write
  */
static void Handle_Submit(void)
{
  /* Real EV2300 SUBMIT always returns 0xC0 with 3-byte payload {0x33, 0x31, 0x6D} */
  static const uint8_t submitPayload[3] = {0x33U, 0x31U, 0x6DU};

  if (pendingWrite.active == 0U)
  {
    /* Real EV2300 returns error when SUBMIT is sent with no pending write */
    EV2300_BuildErrorResponse();
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

  if (st == HAL_OK)
  {
    EV2300_BuildRawResponse(0xC0U, submitPayload, 3U);
  }
  else
  {
    EV2300_BuildErrorResponse();
  }
  EV2300_SendResponse();
}

/**
  * @brief  Handle all undocumented commands with exact real EV2300 responses
  *
  * Response codes verified by dual-device diff (diff_ev2300_responses.py)
  * against real EV2300A hardware, 2026-04-01. Three categories:
  *
  *   1. Commands that get a specific response -> match exactly
  *   2. Commands that return 0x46 error       -> return 0x46
  *   3. Commands that TIMEOUT (no response)   -> don't respond at all
  *
  * Category 3 is critical: the real EV2300 simply ignores unknown commands.
  * The TI DLLs distinguish "no response" from "error response".
  */
static void Handle_Undocumented(uint8_t cmd)
{
  /* Shared payload for bare error responses (real EV2300 uses 55 93 for bare cmds,
   * distinct from the I2C-failure error payload {00 93} in EV2300_BuildErrorResponse). */
  static const uint8_t bareErr[2] = {0x55U, 0x93U};

  switch (cmd)
  {
    /* ── Bare command responses verified against real EV2300A (full_sweep_results.json
       2026-04-01T01:37). All values are exact response codes and payloads captured
       from the real hardware. ────────────────────────────────────────────────────── */

    case 0x00U:
    {
      static const uint8_t p[] = {0x55U, 0x00U, 0x08U};
      EV2300_BuildRawResponse(0x40U, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    case 0x01U:
    {
      static const uint8_t p[] = {0x55U, 0x00U, 0x00U, 0x08U};
      EV2300_BuildRawResponse(0x41U, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    case 0x02U:
    {
      static const uint8_t p[] = {0x02U, 0x00U, 0x08U};
      EV2300_BuildRawResponse(0x42U, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    /* 0x03 bare -> 0x46 error */
    case 0x03U:
      EV2300_BuildRawResponse(0x46U, bareErr, 2U);
      EV2300_SendResponse();
      break;

    /* 0x0D -> 0x4E (I2C power/bus control) */
    case 0x0DU:
    {
      static const uint8_t p[] = {0x02U, 0x00U, 0x08U};
      EV2300_BuildRawResponse(0x4EU, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    /* 0x0E, 0x0F bare -> 0x46 error */
    case 0x0EU:
    case 0x0FU:
      EV2300_BuildRawResponse(0x46U, bareErr, 2U);
      EV2300_SendResponse();
      break;

    case 0x10U:
      EV2300_BuildRawResponse(0x10U, bareErr, 2U);
      EV2300_SendResponse();
      break;

    case 0x11U:
    {
      static const uint8_t p[] = {0x00U, 0x08U};
      EV2300_BuildRawResponse(0x50U, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    case 0x12U:
    {
      static const uint8_t p[] = {0xF6U, 0x00U, 0xFDU};
      EV2300_BuildRawResponse(0x4AU, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    case 0x14U:
    {
      static const uint8_t p[] = {0xBDU, 0x00U, 0x00U, 0x0AU};
      EV2300_BuildRawResponse(0x4BU, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    case 0x16U:
    {
      static const uint8_t p[] = {0x79U, 0x00U, 0xFDU};
      EV2300_BuildRawResponse(0x4CU, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    case 0x19U:
    {
      static const uint8_t p[] = {0x55U, 0x00U, 0x02U};
      EV2300_BuildRawResponse(0x51U, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    /* 0x1A bare -> 0x46 error */
    case 0x1AU:
      EV2300_BuildRawResponse(0x46U, bareErr, 2U);
      EV2300_SendResponse();
      break;

    case 0x1DU:
    {
      static const uint8_t p[] = {0x55U, 0x00U, 0x02U};
      EV2300_BuildRawResponse(0x52U, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    /* 0x1E, 0x20 bare -> 0x46 error */
    case 0x1EU:
    case 0x20U:
      EV2300_BuildRawResponse(0x46U, bareErr, 2U);
      EV2300_SendResponse();
      break;

    case 0x22U:
      EV2300_BuildRawResponse(0x22U, bareErr, 2U);
      EV2300_SendResponse();
      break;

    case 0x23U:
    {
      static const uint8_t p[] = {0xC2U, 0x00U, 0x00U};
      EV2300_BuildRawResponse(0x53U, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    case 0x24U:
    {
      static const uint8_t p[] = {0xC2U, 0x00U, 0x00U};
      EV2300_BuildRawResponse(0x24U, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    case 0x30U:
    {
      static const uint8_t p[] = {0xC2U, 0x00U, 0x00U};
      EV2300_BuildRawResponse(0x30U, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    case 0x40U:
    {
      static const uint8_t p[] = {0xC2U, 0x00U, 0x00U};
      EV2300_BuildRawResponse(0x40U, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    case 0x41U:
    {
      static const uint8_t p[] = {0xC2U, 0x00U, 0x00U};
      EV2300_BuildRawResponse(0x41U, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    case 0x42U:
    {
      static const uint8_t p[] = {0xC2U, 0x00U, 0x00U};
      EV2300_BuildRawResponse(0x42U, p, (uint8_t)sizeof(p));
      EV2300_SendResponse();
      break;
    }

    /* 0x70 -> 0x60 with USB descriptor dump */
    case 0x70U:
    {
      static const uint8_t desc[] = {
        0x61U, 0x00U, 0x04U, 0x08U, 0xAAU, 0x62U, 0x01U, 0x00U,
        0x00U, 0x00U, 0x01U,
        0x09U, 0x02U, 0x19U, 0x00U, 0x01U, 0x01U, 0x00U, 0x80U, 0x32U,
        0x09U, 0x04U, 0x00U, 0x00U, 0x01U, 0xFFU, 0x00U, 0x00U, 0x00U,
        0x07U, 0x05U, 0x01U, 0x02U, 0x40U, 0x00U, 0x00U,
      };
      EV2300_BuildRawResponse(0x60U, desc, (uint8_t)sizeof(desc));
      EV2300_SendResponse();
      break;
    }

    /* ── All other commands ───────────────────────────────────────── */
    /* Commands with payload that aren't handled above get an error
     * response so the host doesn't hang. Bare commands (plen=0) that
     * aren't listed above stay silent, matching real EV2300 timeout. */
    default:
      if (cmdBuffer[6] > 0U)
      {
        EV2300_BuildErrorResponse();
        EV2300_SendResponse();
      }
      break;
  }
}
