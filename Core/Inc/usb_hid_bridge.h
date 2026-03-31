/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : usb_hid_bridge.h
  * @brief          : USB HID to I2C bridge protocol for BQ76920
  ******************************************************************************
  *
  * Defines the command protocol for host-side communication with the BQ76920
  * via USB HID reports. All reports are 64 bytes.
  *
  * Request:  [CMD_ID][REG_ADDR][DATA_LEN][DATA...]
  * Response: [CMD_ID][STATUS][DATA_LEN][DATA...]
  *
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef INC_USB_HID_BRIDGE_H_
#define INC_USB_HID_BRIDGE_H_

#include "bq76920.h"
#include "usbd_hid.h"

/* Exported defines ----------------------------------------------------------*/

/** @brief HID report size in bytes */
#define BRIDGE_REPORT_SIZE  64U

/**
  * @defgroup Bridge_Commands HID bridge command IDs
  * @{
  */
#define BRIDGE_CMD_READ_REG      0x01U  /*!< Read single register        */
#define BRIDGE_CMD_WRITE_REG     0x02U  /*!< Write single register       */
#define BRIDGE_CMD_READ_BLOCK    0x03U  /*!< Read N consecutive registers */
#define BRIDGE_CMD_WRITE_BLOCK   0x04U  /*!< Write N consecutive registers */
#define BRIDGE_CMD_INIT_DEVICE   0x10U  /*!< Run BQ76920_Initialise      */
#define BRIDGE_CMD_GET_STATUS    0x11U  /*!< Return SYS_STAT + info      */
#define BRIDGE_CMD_GET_VOLTAGES  0x12U  /*!< Return cell + pack voltages */
#define BRIDGE_CMD_GET_CURRENT   0x13U  /*!< Return coulomb counter      */
#define BRIDGE_CMD_FET_CONTROL   0x14U  /*!< CHG/DSG FET on/off          */
#define BRIDGE_CMD_ECHO          0xFEU  /*!< Loopback test               */
#define BRIDGE_CMD_VERSION       0xFFU  /*!< Firmware version string     */
/** @} */

/**
  * @defgroup Bridge_Status Response status codes
  * @{
  */
#define BRIDGE_STATUS_OK         0x00U  /*!< Success                     */
#define BRIDGE_STATUS_I2C_ERR    0x01U  /*!< I2C transaction failed      */
#define BRIDGE_STATUS_CRC_ERR    0x02U  /*!< CRC mismatch                */
#define BRIDGE_STATUS_BAD_CMD    0x03U  /*!< Unknown command ID          */
/** @} */

/* Exported function prototypes ----------------------------------------------*/

/**
  * @brief  Initialise the bridge layer
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval None
  */
void Bridge_Init(BQ76920_t *bms);

/**
  * @brief  Process a pending HID command (call from main loop)
  * @note   Non-blocking if no command is pending. Performs blocking I2C
  *         when a command is available, then sends the HID response.
  * @retval None
  */
void Bridge_ProcessCommand(void);

/**
  * @brief  USB HID OUT callback (called from USB interrupt context)
  * @note   Copies received data and sets a flag for main-loop processing.
  *         Do NOT call I2C functions from this callback.
  * @param  buf  Pointer to received HID report (64 bytes)
  * @param  len  Number of bytes received
  * @retval None
  */
void Bridge_HID_OutCallback(uint8_t *buf, uint32_t len);

#endif /* INC_USB_HID_BRIDGE_H_ */
