/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : usb_hid_bridge.c
  * @brief          : USB HID to I2C bridge protocol for BQ76920
  ******************************************************************************
  *
  * Translates USB HID reports into I2C register transactions on the BQ76920.
  * The USB DataOut callback (interrupt context) sets a flag; the main loop
  * polls and executes blocking I2C work.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "usb_hid_bridge.h"
#include "usb_device.h"
#include <string.h>

/* External variables --------------------------------------------------------*/
extern USBD_HandleTypeDef hUsbDeviceFS;

/* Private defines -----------------------------------------------------------*/

#define FW_VERSION  "BQ76920_Bridge v0.1"

/* Private variables ---------------------------------------------------------*/

static BQ76920_t *pBms = NULL;

static volatile uint8_t cmdPending = 0U;
static uint8_t cmdBuffer[BRIDGE_REPORT_SIZE];
static uint8_t rspBuffer[BRIDGE_REPORT_SIZE];

/* Exported functions --------------------------------------------------------*/

/**
  * @brief  Initialise the bridge layer
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval None
  */
void Bridge_Init(BQ76920_t *bms)
{
  pBms = bms;
  cmdPending = 0U;

  /* Register our callback with the USB HID layer */
  USBD_HID_OutEventCallback = Bridge_HID_OutCallback;
}

/**
  * @brief  USB HID OUT callback (called from USB interrupt context)
  * @param  buf  Pointer to received HID report
  * @param  len  Number of bytes received
  * @retval None
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
  * @retval None
  */
void Bridge_ProcessCommand(void)
{
  if (cmdPending == 0U)
  {
    return;
  }

  memset(rspBuffer, 0, BRIDGE_REPORT_SIZE);

  uint8_t cmd     = cmdBuffer[0];
  uint8_t regAddr = cmdBuffer[1];
  uint8_t dataLen = cmdBuffer[2];

  /* Echo the command ID in the response */
  rspBuffer[0] = cmd;

  switch (cmd)
  {
    /* ------------------------------------------------------------------ */
    case BRIDGE_CMD_READ_REG:
    {
      uint8_t val;
      HAL_StatusTypeDef st = BQ76920_ReadRegister(pBms, regAddr, &val);
      rspBuffer[1] = (st == HAL_OK) ? BRIDGE_STATUS_OK : BRIDGE_STATUS_I2C_ERR;
      rspBuffer[2] = 1U;
      rspBuffer[3] = val;
      break;
    }

    /* ------------------------------------------------------------------ */
    case BRIDGE_CMD_WRITE_REG:
    {
      uint8_t val = cmdBuffer[3];
      HAL_StatusTypeDef st = BQ76920_WriteRegister(pBms, regAddr, val);
      rspBuffer[1] = (st == HAL_OK) ? BRIDGE_STATUS_OK : BRIDGE_STATUS_I2C_ERR;
      rspBuffer[2] = 0U;
      break;
    }

    /* ------------------------------------------------------------------ */
    case BRIDGE_CMD_READ_BLOCK:
    {
      if (dataLen > (BRIDGE_REPORT_SIZE - 3U))
      {
        dataLen = (uint8_t)(BRIDGE_REPORT_SIZE - 3U);
      }
      uint8_t status = BRIDGE_STATUS_OK;
      for (uint8_t i = 0U; i < dataLen; i++)
      {
        uint8_t val;
        if (BQ76920_ReadRegister(pBms, (uint8_t)(regAddr + i), &val) != HAL_OK)
        {
          status = BRIDGE_STATUS_I2C_ERR;
          dataLen = i;
          break;
        }
        rspBuffer[3U + i] = val;
      }
      rspBuffer[1] = status;
      rspBuffer[2] = dataLen;
      break;
    }

    /* ------------------------------------------------------------------ */
    case BRIDGE_CMD_WRITE_BLOCK:
    {
      if (dataLen > (BRIDGE_REPORT_SIZE - 3U))
      {
        dataLen = (uint8_t)(BRIDGE_REPORT_SIZE - 3U);
      }
      uint8_t status = BRIDGE_STATUS_OK;
      for (uint8_t i = 0U; i < dataLen; i++)
      {
        if (BQ76920_WriteRegister(pBms, (uint8_t)(regAddr + i), cmdBuffer[3U + i]) != HAL_OK)
        {
          status = BRIDGE_STATUS_I2C_ERR;
          break;
        }
      }
      rspBuffer[1] = status;
      rspBuffer[2] = 0U;
      break;
    }

    /* ------------------------------------------------------------------ */
    case BRIDGE_CMD_INIT_DEVICE:
    {
      /* Re-initialise with current config */
      HAL_StatusTypeDef st = BQ76920_Initialise(pBms, pBms->i2cHandle,
                                                 pBms->numCells,
                                                 pBms->ovTrip_V,
                                                 pBms->uvTrip_V,
                                                 pBms->capacity_mAh,
                                                 pBms->nominalV);
      rspBuffer[1] = (st == HAL_OK) ? BRIDGE_STATUS_OK : BRIDGE_STATUS_I2C_ERR;
      rspBuffer[2] = 4U;
      /* Return GAIN (2 bytes, little-endian) and OFFSET (signed byte) */
      rspBuffer[3] = (uint8_t)(pBms->GAIN & 0xFFU);
      rspBuffer[4] = (uint8_t)(pBms->GAIN >> 8U);
      rspBuffer[5] = (uint8_t)pBms->OFFSET;
      rspBuffer[6] = pBms->numCells;
      break;
    }

    /* ------------------------------------------------------------------ */
    case BRIDGE_CMD_GET_STATUS:
    {
      readAlert(pBms);
      uint8_t sysStat;
      HAL_StatusTypeDef st = BQ76920_ReadRegister(pBms, SYS_STAT, &sysStat);
      rspBuffer[1] = (st == HAL_OK) ? BRIDGE_STATUS_OK : BRIDGE_STATUS_I2C_ERR;
      rspBuffer[2] = 4U;
      rspBuffer[3] = sysStat;
      rspBuffer[4] = pBms->numCells;
      rspBuffer[5] = (uint8_t)(pBms->GAIN & 0xFFU);
      rspBuffer[6] = (uint8_t)(pBms->GAIN >> 8U);
      break;
    }

    /* ------------------------------------------------------------------ */
    case BRIDGE_CMD_GET_VOLTAGES:
    {
      uint8_t status = BRIDGE_STATUS_OK;

      /* Read all cell voltages */
      for (uint8_t i = 1U; i <= pBms->numCells; i++)
      {
        float v = getCellVoltage(pBms, i);
        if (v == 0.0f && pBms->Vcell[i - 1U] == 0.0f)
        {
          /* Could be I2C error or genuinely 0V -- report as-is */
        }
        /* Pack as 32-bit float, little-endian */
        memcpy(&rspBuffer[3U + ((i - 1U) * 4U)], &v, 4U);
      }

      /* Pack voltage after cell voltages */
      float vpack = getPackVoltage(pBms);
      uint8_t packOffset = (uint8_t)(3U + (pBms->numCells * 4U));
      memcpy(&rspBuffer[packOffset], &vpack, 4U);

      rspBuffer[1] = status;
      rspBuffer[2] = (uint8_t)((pBms->numCells + 1U) * 4U);
      break;
    }

    /* ------------------------------------------------------------------ */
    case BRIDGE_CMD_GET_CURRENT:
    {
      float current = getCurrent(pBms);
      rspBuffer[1] = BRIDGE_STATUS_OK;
      rspBuffer[2] = 4U;
      memcpy(&rspBuffer[3], &current, 4U);
      break;
    }

    /* ------------------------------------------------------------------ */
    case BRIDGE_CMD_FET_CONTROL:
    {
      uint8_t control = cmdBuffer[3];
      uint8_t status = BRIDGE_STATUS_OK;
      HAL_StatusTypeDef st;

      /* bit 0: CHG, bit 1: DSG, bit 2: 1=on 0=off */
      uint8_t turnOn = (control >> 2U) & 0x01U;

      if (control & 0x01U) /* CHG */
      {
        st = turnOn ? turnCHGOn(pBms) : turnCHGOff(pBms);
        if (st != HAL_OK) { status = BRIDGE_STATUS_I2C_ERR; }
      }
      if (control & 0x02U) /* DSG */
      {
        st = turnOn ? turnDSGOn(pBms) : turnDSGOff(pBms);
        if (st != HAL_OK) { status = BRIDGE_STATUS_I2C_ERR; }
      }

      rspBuffer[1] = status;
      rspBuffer[2] = 0U;
      break;
    }

    /* ------------------------------------------------------------------ */
    case BRIDGE_CMD_ECHO:
    {
      /* Loopback: copy the entire request into the response */
      memcpy(rspBuffer, cmdBuffer, BRIDGE_REPORT_SIZE);
      break;
    }

    /* ------------------------------------------------------------------ */
    case BRIDGE_CMD_VERSION:
    {
      rspBuffer[1] = BRIDGE_STATUS_OK;
      rspBuffer[2] = (uint8_t)(sizeof(FW_VERSION) - 1U);
      memcpy(&rspBuffer[3], FW_VERSION, sizeof(FW_VERSION) - 1U);
      break;
    }

    /* ------------------------------------------------------------------ */
    default:
      rspBuffer[1] = BRIDGE_STATUS_BAD_CMD;
      rspBuffer[2] = 0U;
      break;
  }

  /* Send response via USB HID IN endpoint */
  USBD_HID_SendReport(&hUsbDeviceFS, rspBuffer, BRIDGE_REPORT_SIZE);

  /* Clear pending flag */
  cmdPending = 0U;
}
