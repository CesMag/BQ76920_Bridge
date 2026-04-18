/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : usb_hid_bridge.h
  * @brief          : EV2300 USB HID protocol emulation for BQ76920 I2C bridge
  ******************************************************************************
  *
  * Emulates the TI EV2300 USB-to-SMBus adapter protocol so that bqStudio
  * and the TI_EV2300 Python driver can communicate with the BQ76920 AFE
  * through this STM32F405 bridge without modification.
  *
  * Protocol reference: scpi-instrument-toolkit/lab_instruments/src/ev2300.py
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
  * @defgroup EV2300_Protocol EV2300 HID protocol constants
  * @{
  */
#define EV2300_FRAME_MARKER  0xAAU  /*!< Packet start marker       */
#define EV2300_FRAME_END     0x55U  /*!< Packet end marker         */
#define EV2300_RESP_FLAG     0x40U  /*!< OR'd into cmd on success  */

/** @brief EV2300 command codes */
#define EV2300_CMD_READ_WORD   0x01U  /*!< SMBus Read Word          */
#define EV2300_CMD_READ_BLOCK  0x02U  /*!< SMBus Read Block         */
#define EV2300_CMD_READ_BYTE   0x03U  /*!< Read single byte         */
#define EV2300_CMD_WRITE_WORD  0x04U  /*!< SMBus Write Word (2-phase) */
#define EV2300_CMD_WRITE_BLOCK 0x05U  /*!< SMBus Write Block (2-phase) */
#define EV2300_CMD_SEND_BYTE   0x06U  /*!< SMBus Send Byte (2-phase)  */
#define EV2300_CMD_WRITE_BYTE  0x07U  /*!< Write single byte (2-phase) */
#define EV2300_CMD_SUBMIT      0x80U  /*!< Write handshake / execute   */
#define EV2300_CMD_ERROR       0x46U  /*!< Device error response       */
#define EV2300_CMD_DEVICE_INFO 0x70U  /*!< Device info (170 bytes)     */
/** @} */

/**
  * @defgroup Bridge_Extensions Firmware-specific bridge commands
  * @brief Commands added by this firmware; not part of the real EV2300 protocol.
  * @{
  */
#define BRIDGE_CMD_GET_VERSION 0x71U  /*!< Firmware version string     */
/** @} */

/* Exported function prototypes ----------------------------------------------*/

/**
  * @brief  Initialise the EV2300 emulation bridge layer
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval None
  */
void Bridge_Init(BQ76920_t *bms);

/**
  * @brief  Process a pending HID command (call from main loop)
  * @retval None
  */
void Bridge_ProcessCommand(void);

/**
  * @brief  USB HID OUT callback (called from USB interrupt context)
  * @param  buf  Pointer to received HID report (64 bytes)
  * @param  len  Number of bytes received
  * @retval None
  */
void Bridge_HID_OutCallback(uint8_t *buf, uint32_t len);

#endif /* INC_USB_HID_BRIDGE_H_ */
