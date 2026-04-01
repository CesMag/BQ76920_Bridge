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

/* Debug command log: stores first 10 bytes of each received command */
#define CMD_LOG_SIZE    32U
#define CMD_LOG_BYTES   12U

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

/* Debug ring buffer: log every command received */
static uint8_t cmdLog[CMD_LOG_SIZE][CMD_LOG_BYTES];
static uint8_t cmdLogIdx = 0U;
static uint8_t cmdLogCount = 0U;

/* Private function prototypes -----------------------------------------------*/

static uint8_t EV2300_CRC8(const uint8_t *data, uint8_t len);
static void EV2300_BuildRawResponse(uint8_t respCode,
                                     const uint8_t *payload, uint8_t payloadLen,
                                     uint8_t crcSkipTail);
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

  /* Log first 10 bytes of every command for debug readout */
  memcpy(cmdLog[cmdLogIdx], cmdBuffer, CMD_LOG_BYTES);
  cmdLogIdx = (uint8_t)((cmdLogIdx + 1U) % CMD_LOG_SIZE);
  if (cmdLogCount < CMD_LOG_SIZE) { cmdLogCount++; }

  uint8_t marker = cmdBuffer[1];
  uint8_t cmd    = cmdBuffer[2];
  uint8_t plen   = cmdBuffer[6];

  /* Debug command 0xFE: dump command log */
  if (marker == EV2300_FRAME_MARKER && cmd == 0xFEU)
  {
    memset(rspBuffer, 0, BRIDGE_REPORT_SIZE);
    /* Page number in command payload byte[7], default 0 */
    uint8_t page = (cmdBuffer[6] >= 1U) ? cmdBuffer[7] : 0U;
    uint8_t start = (cmdLogCount >= CMD_LOG_SIZE) ? cmdLogIdx : 0U;
    uint8_t skip = page * 6U;
    rspBuffer[0] = cmdLogCount;
    rspBuffer[1] = page;
    /* Pack 6 entries per page: header(2) + entries(6*10=60) = 62 bytes */
    uint8_t avail = (cmdLogCount > skip) ? (uint8_t)(cmdLogCount - skip) : 0U;
    uint8_t n = (avail < 6U) ? avail : 6U;
    for (uint8_t i = 0U; i < n; i++)
    {
      uint8_t idx = (uint8_t)((start + skip + i) % CMD_LOG_SIZE);
      memcpy(&rspBuffer[2U + i * CMD_LOG_BYTES], cmdLog[idx], CMD_LOG_BYTES);
    }
    EV2300_SendResponse();
    cmdPending = 0U;
    return;
  }

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
  * @param  respCode     Exact response byte (from real EV2300 protocol scan)
  * @param  payload      Response payload
  * @param  payloadLen   Payload length
  * @param  crcSkipTail  Number of trailing payload bytes to EXCLUDE from CRC.
  *                      Real EV2300 excludes the I2C address byte at the end
  *                      of success payloads (crcSkipTail=1). Error responses
  *                      include all payload bytes in CRC (crcSkipTail=0).
  *                      Verified against real EV2300A captures 2026-04-01.
  */
static void EV2300_BuildRawResponse(uint8_t respCode,
                                     const uint8_t *payload, uint8_t payloadLen,
                                     uint8_t crcSkipTail)
{
  memset(rspBuffer, 0, BRIDGE_REPORT_SIZE);

  /* FIX #1: totalLen = plen + 8 (was plen + 9, off by 1).
   * Real EV2300 frame: AA(1)+cmd(1)+rsv(3)+plen(1)+payload(N)+CRC(1)+55(1) = N+8 */
  uint8_t totalLen = (uint8_t)(payloadLen + 8U);

  rspBuffer[0] = totalLen;
  rspBuffer[1] = EV2300_FRAME_MARKER;
  rspBuffer[2] = respCode;
  rspBuffer[5] = 0x01U;  /* Real EV2300 always has 0x01 at reserved[2] */
  rspBuffer[6] = payloadLen;

  if (payloadLen > 0U && payload != NULL)
  {
    memcpy(&rspBuffer[7], payload, payloadLen);
  }

  /* FIX #5: CRC excludes trailing I2C address byte for success responses.
   * CRC covers: cmd + rsv(3) + plen + payload[0..plen-1-crcSkipTail]
   * Error (crcSkipTail=0): 5 + plen bytes.  Success (crcSkipTail=1): 4 + plen bytes. */
  uint8_t crcPos = (uint8_t)(7U + payloadLen);
  uint8_t crcLen = (uint8_t)(5U + payloadLen - crcSkipTail);
  rspBuffer[crcPos] = EV2300_CRC8(&rspBuffer[2], crcLen);
  rspBuffer[crcPos + 1U] = EV2300_FRAME_END;
}

/**
  * @brief  Build a standard error response (0x46 with 2-byte payload)
  *         Real EV2300 always sends 0x46 with payload {0x00, 0x93}.
  *         The DLLs parse this payload for error context.
  */
static void EV2300_BuildErrorResponse(void)
{
  static const uint8_t errPayload[2] = {0x00U, 0x93U};
  EV2300_BuildRawResponse(EV2300_CMD_ERROR, errPayload, 2U, 0U);
}

static void EV2300_SendResponse(void)
{
  USBD_HID_SendReport(&hUsbDeviceFS, rspBuffer, BRIDGE_REPORT_SIZE);
}

/* ---- I2C command handlers (use exact real EV2300 response codes) --------- */

/**
  * @brief  CMD 0x03 READ_BYTE -> response code 0x42 (real EV2300 quirk)
  *         Payload format: {reg, data, i2c_7bit_addr} with crcSkipTail=1.
  *         Note: BQ76920 doesn't support single-byte SMBus reads, so the real
  *         EV2300 returns 0x46 error on BQ76920. Our HAL_I2C_Mem_Read with 1 byte
  *         may succeed (raw I2C vs strict SMBus), which is fine for the DLL.
  */
static void Handle_ReadByte(uint16_t addr, uint8_t reg)
{
  uint8_t val;
  HAL_StatusTypeDef st = HAL_I2C_Mem_Read(&hi2c1, addr, reg,
                                           I2C_MEMADD_SIZE_8BIT,
                                           &val, 1U, I2C_TIMEOUT);
  if (st == HAL_OK)
  {
    uint8_t payload[3] = {reg, val, (uint8_t)(addr >> 1U)};
    EV2300_BuildRawResponse(0x42U, payload, 3U, 1U);
  }
  else
  {
    EV2300_BuildErrorResponse();
  }
  EV2300_SendResponse();
}

/**
  * @brief  CMD 0x01 READ_WORD -> response code 0x41
  *         FIX #2: Real EV2300 payload = {reg, data_lo, data_hi, i2c_7bit_addr}
  *         with plen=4 and crcSkipTail=1 (addr excluded from CRC).
  *         Was: {i2c_8bit_addr, data_lo, data_hi} with plen=3.
  */
static void Handle_ReadWord(uint16_t addr, uint8_t reg)
{
  uint8_t buf[2];
  HAL_StatusTypeDef st = HAL_I2C_Mem_Read(&hi2c1, addr, reg,
                                           I2C_MEMADD_SIZE_8BIT,
                                           buf, 2U, I2C_TIMEOUT);
  if (st == HAL_OK)
  {
    uint8_t payload[4] = {reg, buf[0], buf[1], (uint8_t)(addr >> 1U)};
    EV2300_BuildRawResponse(0x41U, payload, 4U, 1U);
  }
  else
  {
    EV2300_BuildErrorResponse();
  }
  EV2300_SendResponse();
}

/**
  * @brief  CMD 0x02 READ_BLOCK -> response code 0x42
  *         Real EV2300 returns short format: {block_count, first_data_byte, addr7}
  *         with plen=3 and crcSkipTail=1. Reads the SMBus block length byte first.
  */
static void Handle_ReadBlock(uint16_t addr, uint8_t reg)
{
  uint8_t data[32];
  uint8_t reqLen = 2U; /* Default: read 2 bytes (SMBus word) */

  /* If a block length was provided in the command, use it */
  if (cmdBuffer[6] >= 3U)
  {
    reqLen = cmdBuffer[9];
    if (reqLen > 32U) { reqLen = 32U; }
    if (reqLen == 0U) { reqLen = 2U; }
  }

  HAL_StatusTypeDef st = HAL_I2C_Mem_Read(&hi2c1, addr, reg,
                                           I2C_MEMADD_SIZE_8BIT,
                                           data, reqLen, I2C_TIMEOUT);
  if (st == HAL_OK)
  {
    /* Match real EV2300: {block_count, first_data_byte, i2c_7bit_addr} */
    uint8_t payload[3] = {reqLen, data[0], (uint8_t)(addr >> 1U)};
    EV2300_BuildRawResponse(0x42U, payload, 3U, 1U);
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
    EV2300_BuildRawResponse(EV2300_CMD_ERROR, errPayload, 2U, 0U);
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

  /* FIX #4: Real EV2300 ALWAYS returns 0xC0 success, even on I2C NACK.
   * The DLL detects write failure through subsequent read-back, not SUBMIT.
   * Verified: SUBMIT to invalid addr 0xFE returns 0xC0 on real EV2300. */
  (void)st;
  EV2300_BuildRawResponse(0xC0U, submitPayload, 3U, 0U);
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

    /* Payloads ending in I2C 7-bit addr (0x08) use crcSkipTail=1.
     * Error payloads (0x93 suffix) and others use crcSkipTail=0. */

    case 0x00U:
    {
      static const uint8_t p[] = {0x55U, 0x00U, 0x08U};
      EV2300_BuildRawResponse(0x40U, p, (uint8_t)sizeof(p), 1U);
      EV2300_SendResponse();
      break;
    }

    case 0x01U:
    {
      static const uint8_t p[] = {0x55U, 0x00U, 0x00U, 0x08U};
      EV2300_BuildRawResponse(0x41U, p, (uint8_t)sizeof(p), 1U);
      EV2300_SendResponse();
      break;
    }

    case 0x02U:
    {
      static const uint8_t p[] = {0x02U, 0x00U, 0x08U};
      EV2300_BuildRawResponse(0x42U, p, (uint8_t)sizeof(p), 1U);
      EV2300_SendResponse();
      break;
    }

    /* 0x03 bare -> 0x46 error */
    case 0x03U:
      EV2300_BuildRawResponse(0x46U, bareErr, 2U, 0U);
      EV2300_SendResponse();
      break;

    /* 0x0D -> 0x4E (I2C power/bus control, VERIFIED crcSkipTail=1) */
    case 0x0DU:
    {
      static const uint8_t p[] = {0x02U, 0x00U, 0x08U};
      EV2300_BuildRawResponse(0x4EU, p, (uint8_t)sizeof(p), 1U);
      EV2300_SendResponse();
      break;
    }

    /* 0x0E, 0x0F bare -> 0x46 error */
    case 0x0EU:
    case 0x0FU:
      EV2300_BuildRawResponse(0x46U, bareErr, 2U, 0U);
      EV2300_SendResponse();
      break;

    case 0x10U:
      EV2300_BuildRawResponse(0x10U, bareErr, 2U, 0U);
      EV2300_SendResponse();
      break;

    case 0x11U:
    {
      static const uint8_t p[] = {0x00U, 0x08U};
      EV2300_BuildRawResponse(0x50U, p, (uint8_t)sizeof(p), 1U);
      EV2300_SendResponse();
      break;
    }

    case 0x12U:
    {
      static const uint8_t p[] = {0xF6U, 0x00U, 0xFDU};
      EV2300_BuildRawResponse(0x4AU, p, (uint8_t)sizeof(p), 0U);
      EV2300_SendResponse();
      break;
    }

    case 0x14U:
    {
      static const uint8_t p[] = {0xBDU, 0x00U, 0x00U, 0x0AU};
      EV2300_BuildRawResponse(0x4BU, p, (uint8_t)sizeof(p), 0U);
      EV2300_SendResponse();
      break;
    }

    case 0x16U:
    {
      static const uint8_t p[] = {0x79U, 0x00U, 0xFDU};
      EV2300_BuildRawResponse(0x4CU, p, (uint8_t)sizeof(p), 0U);
      EV2300_SendResponse();
      break;
    }

    case 0x19U:
    {
      static const uint8_t p[] = {0x55U, 0x00U, 0x02U};
      EV2300_BuildRawResponse(0x51U, p, (uint8_t)sizeof(p), 0U);
      EV2300_SendResponse();
      break;
    }

    /* 0x1A bare -> 0x46 error */
    case 0x1AU:
      EV2300_BuildRawResponse(0x46U, bareErr, 2U, 0U);
      EV2300_SendResponse();
      break;

    case 0x1DU:
    {
      static const uint8_t p[] = {0x55U, 0x00U, 0x02U};
      EV2300_BuildRawResponse(0x52U, p, (uint8_t)sizeof(p), 0U);
      EV2300_SendResponse();
      break;
    }

    /* 0x1E, 0x20 bare -> 0x46 error */
    case 0x1EU:
    case 0x20U:
      EV2300_BuildRawResponse(0x46U, bareErr, 2U, 0U);
      EV2300_SendResponse();
      break;

    case 0x22U:
      EV2300_BuildRawResponse(0x22U, bareErr, 2U, 0U);
      EV2300_SendResponse();
      break;

    case 0x23U:
    {
      static const uint8_t p[] = {0xC2U, 0x00U, 0x00U};
      EV2300_BuildRawResponse(0x53U, p, (uint8_t)sizeof(p), 0U);
      EV2300_SendResponse();
      break;
    }

    case 0x24U:
    {
      static const uint8_t p[] = {0xC2U, 0x00U, 0x00U};
      EV2300_BuildRawResponse(0x24U, p, (uint8_t)sizeof(p), 0U);
      EV2300_SendResponse();
      break;
    }

    case 0x30U:
    {
      static const uint8_t p[] = {0xC2U, 0x00U, 0x00U};
      EV2300_BuildRawResponse(0x30U, p, (uint8_t)sizeof(p), 0U);
      EV2300_SendResponse();
      break;
    }

    case 0x40U:
    {
      static const uint8_t p[] = {0xC2U, 0x00U, 0x00U};
      EV2300_BuildRawResponse(0x40U, p, (uint8_t)sizeof(p), 0U);
      EV2300_SendResponse();
      break;
    }

    case 0x41U:
    {
      static const uint8_t p[] = {0xC2U, 0x00U, 0x00U};
      EV2300_BuildRawResponse(0x41U, p, (uint8_t)sizeof(p), 0U);
      EV2300_SendResponse();
      break;
    }

    case 0x42U:
    {
      static const uint8_t p[] = {0xC2U, 0x00U, 0x00U};
      EV2300_BuildRawResponse(0x42U, p, (uint8_t)sizeof(p), 0U);
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
      EV2300_BuildRawResponse(0x60U, desc, (uint8_t)sizeof(desc), 0U);
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
