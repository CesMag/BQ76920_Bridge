/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : bq76920.h
  * @brief          : STM32 HAL driver for the TI BQ76920 3S-5S Li-Ion AFE
  ******************************************************************************
  *
  * Originally based on:
  *   BQ76920.h by Nawat Kitiphuwadon, extensively modified by Ignatius Djaynurdin
  *   Version 2.0, 2023-07-04
  *   https://github.com/SubugFcz/BMS_BQ76920/blob/main/BQ76920.h
  *
  * Modified by Cesar Magana, 2026
  *   - Ported from STM32G0 to STM32F405 (stm32f4xx_hal.h)
  *   - R/W functions return HAL_StatusTypeDef for I2C error propagation
  *   - Added CRC-8 (poly 0x07) declaration for CRC mode (addr 0x18)
  *   - Added BQ76920_EnterShipMode() using SHUT_B/SHUT_A sequence
  *   - Added TS2, TS3 thermistor register addresses
  *   - Added SYS_CTRL1, SYS_CTRL2, SYS_STAT bit mask defines
  *   - Expanded cell array to 5 elements; cell count is a runtime struct field
  *   - Moved pack constants (OV/UV thresholds, capacity) into device struct
  *   - Removed hardcoded debug stub functions
  *   - Reformatted to STM32 Doxygen comment style
  *
  ******************************************************************************
  *
  * MIT License
  * Copyright (c) 2018 ETA Systems
  *
  * Permission is hereby granted, free of charge, to any person obtaining a
  * copy of this software and associated documentation files (the "Software"),
  * to deal in the Software without restriction, including without limitation
  * the rights to use, copy, modify, merge, publish, distribute, sublicense,
  * and/or sell copies of the Software, and to permit persons to whom the
  * Software is furnished to do so, subject to the following conditions:
  *
  * The above copyright notice and this permission notice shall be included in
  * all copies or substantial portions of the Software.
  *
  * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
  * OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
  * THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
  * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
  * DEALINGS IN THE SOFTWARE.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef INC_BQ76920_H_
#define INC_BQ76920_H_

#include "stm32f4xx_hal.h"

/* Exported defines ----------------------------------------------------------*/

/**
  * @defgroup BQ76920_I2C_Addresses I2C device addresses (8-bit, STM32 HAL)
  * @{
  * The BQ76920 has two I2C addresses depending on CRC mode selection.
  * Addresses are left-shifted by 1 for use with STM32 HAL functions.
  *   0x08 << 1 = 0x10  (CRC disabled)
  *   0x18 << 1 = 0x30  (CRC enabled -- use this)
  */
#define BQ76920_ADDR_CRC     (0x18 << 1)  /*!< CRC mode enabled  (recommended) */
#define BQ76920_ADDR_NO_CRC  (0x08 << 1)  /*!< CRC mode disabled               */
/** @} */

/** @brief CRC-8 polynomial used by BQ76920 SMBus/I2C CRC mode */
#define BQ76920_CRC_POLY     0x07U

/* Exported register addresses -----------------------------------------------*/

/**
  * @defgroup BQ76920_Registers Register address map
  * @{
  */
#define SYS_STAT   0x00U  /*!< Alert flags -- clear by writing 1 to each bit */
#define CELLBAL1   0x01U  /*!< Cell balancing control (BQ76920, up to 5 cells) */
#define CELLBAL2   0x02U  /*!< Cell balancing control (BQ76930)                */
#define CELLBAL3   0x03U  /*!< Cell balancing control (BQ76940)                */
#define SYS_CTRL1  0x04U  /*!< ADC enable, temperature source select, SHIP mode */
#define SYS_CTRL2  0x05U  /*!< Coulomb counter enable and FET control           */
#define PROTECT1   0x06U  /*!< SCD threshold and delay                          */
#define PROTECT2   0x07U  /*!< OCD threshold and delay                          */
#define PROTECT3   0x08U  /*!< OV and UV protection delays                      */
#define OV_TRIP    0x09U  /*!< Overvoltage trip threshold (8-bit scaled)        */
#define UV_TRIP    0x0AU  /*!< Undervoltage trip threshold (8-bit scaled)       */
#define CC_CFG     0x0BU  /*!< Coulomb counter config -- write 0x19 at startup  */

/**
  * Cell voltage registers: each cell uses a HI/LO register pair.
  * Raw 14-bit value: (HI[5:0] << 8) | LO[7:0]
  * Converted voltage (mV) = (GAIN * raw) / 1000 + OFFSET
  * GAIN (uV/LSB) is assembled from ADCGAIN1[4:3] and ADCGAIN2[2:0].
  */
#define VC1_HI     0x0CU  /*!< Cell 1 voltage MSB [5:0] */
#define VC1_LO     0x0DU  /*!< Cell 1 voltage LSB [7:0] */
#define VC2_HI     0x0EU  /*!< Cell 2 voltage MSB [5:0] */
#define VC2_LO     0x0FU  /*!< Cell 2 voltage LSB [7:0] */
#define VC3_HI     0x10U  /*!< Cell 3 voltage MSB [5:0] */
#define VC3_LO     0x11U  /*!< Cell 3 voltage LSB [7:0] */
#define VC4_HI     0x12U  /*!< Cell 4 voltage MSB [5:0] */
#define VC4_LO     0x13U  /*!< Cell 4 voltage LSB [7:0] */
#define VC5_HI     0x14U  /*!< Cell 5 voltage MSB [5:0] */
#define VC5_LO     0x15U  /*!< Cell 5 voltage LSB [7:0] */

#define BAT_HI     0x2AU  /*!< Pack voltage MSB [7:0] (16-bit result)          */
#define BAT_LO     0x2BU  /*!< Pack voltage LSB [7:0]                          */
#define TS1_HI     0x2CU  /*!< Thermistor 1 / die temp ADC MSB [5:0]           */
#define TS1_LO     0x2DU  /*!< Thermistor 1 / die temp ADC LSB [7:0]           */
#define TS2_HI     0x2EU  /*!< Thermistor 2 ADC MSB [5:0]                      */
#define TS2_LO     0x2FU  /*!< Thermistor 2 ADC LSB [7:0]                      */
#define TS3_HI     0x30U  /*!< Thermistor 3 ADC MSB [5:0]                      */
#define TS3_LO     0x31U  /*!< Thermistor 3 ADC LSB [7:0]                      */
#define CC_HI      0x32U  /*!< Coulomb counter upper 8 bits (signed 16-bit)    */
#define CC_LO      0x33U  /*!< Coulomb counter lower 8 bits                    */

/**
  * ADC calibration registers (factory-trimmed, read once at init).
  * GAIN (uV/LSB) = 365 + { ADCGAIN1[4:3] << 3 | ADCGAIN2[2:0] }
  * OFFSET (mV)   = signed byte in ADCOFFSET[7:0]
  */
#define ADCGAIN1   0x50U  /*!< ADC gain trim bits [4:3] */
#define ADCOFFSET  0x51U  /*!< ADC offset trim, signed mV */
#define ADCGAIN2   0x59U  /*!< ADC gain trim bits [2:0]  */
/** @} */

/* Exported bit mask defines -------------------------------------------------*/

/**
  * @defgroup BQ76920_SYS_STAT_Bits SYS_STAT (0x00) bit masks
  * Clear a fault by writing 1 to its bit position.
  * @{
  */
#define BQ_STAT_CC_READY       (1U << 7)  /*!< Coulomb counter data ready   */
#define BQ_STAT_DEVICE_XREADY  (1U << 5)  /*!< Device XREADY fault          */
#define BQ_STAT_OVRD_ALERT     (1U << 4)  /*!< Override alert input active  */
#define BQ_STAT_UV             (1U << 3)  /*!< Undervoltage fault           */
#define BQ_STAT_OV             (1U << 2)  /*!< Overvoltage fault            */
#define BQ_STAT_SCD            (1U << 1)  /*!< Short-circuit in discharge   */
#define BQ_STAT_OCD            (1U << 0)  /*!< Overcurrent in discharge     */
/** @} */

/**
  * @defgroup BQ76920_SYS_CTRL1_Bits SYS_CTRL1 (0x04) bit masks
  * @{
  */
#define BQ_CTRL1_LOAD_P        (1U << 7)  /*!< Load present input polarity  */
#define BQ_CTRL1_ADC_EN        (1U << 4)  /*!< ADC enable                   */
#define BQ_CTRL1_TEMP_S        (1U << 3)  /*!< Temp source: 0=die, 1=TS pin */
#define BQ_CTRL1_SHUT_A        (1U << 1)  /*!< SHIP mode entry step 2       */
#define BQ_CTRL1_SHUT_B        (1U << 0)  /*!< SHIP mode entry step 1       */
/** @} */

/**
  * @defgroup BQ76920_SYS_CTRL2_Bits SYS_CTRL2 (0x05) bit masks
  * @{
  */
#define BQ_CTRL2_DLY_DIS       (1U << 7)  /*!< Disable OCD/SCD delay        */
#define BQ_CTRL2_CC_EN         (1U << 5)  /*!< Coulomb counter enable       */
#define BQ_CTRL2_DSG_ON        (1U << 1)  /*!< Discharge FET on             */
#define BQ_CTRL2_CHG_ON        (1U << 0)  /*!< Charge FET on                */
/** @} */

/* Exported types ------------------------------------------------------------*/

/**
  * @brief  Short-circuit in discharge delay (PROTECT1[1:0])
  */
typedef enum
{
  SCD_DELAY_70us  = 0x00,
  SCD_DELAY_100us = 0x01,
  SCD_DELAY_200us = 0x02,
  SCD_DELAY_400us = 0x03
} BQ76920_SCD_Delay;

/**
  * @brief  Short-circuit in discharge threshold (PROTECT1[5:3], RSNS = 1)
  */
typedef enum
{
  SCD_THRESH_44mV  = 0x00,
  SCD_THRESH_67mV  = 0x01,
  SCD_THRESH_89mV  = 0x02,
  SCD_THRESH_111mV = 0x03,
  SCD_THRESH_133mV = 0x04,
  SCD_THRESH_155mV = 0x05,
  SCD_THRESH_178mV = 0x06,
  SCD_THRESH_200mV = 0x07
} BQ76920_SCD_Thresh;

/**
  * @brief  Overcurrent in discharge delay (PROTECT2[6:4])
  */
typedef enum
{
  OCD_DELAY_8ms    = 0x00,
  OCD_DELAY_20ms   = 0x01,
  OCD_DELAY_40ms   = 0x02,
  OCD_DELAY_80ms   = 0x03,
  OCD_DELAY_160ms  = 0x04,
  OCD_DELAY_320ms  = 0x05,
  OCD_DELAY_640ms  = 0x06,
  OCD_DELAY_1280ms = 0x07
} BQ76920_OCD_Delay;

/**
  * @brief  Overcurrent in discharge threshold (PROTECT2[3:0], RSNS = 0)
  */
typedef enum
{
  OCD_THRESH_8mV  = 0x00,
  OCD_THRESH_11mV = 0x01,
  OCD_THRESH_14mV = 0x02,
  OCD_THRESH_17mV = 0x03,
  OCD_THRESH_19mV = 0x04,
  OCD_THRESH_22mV = 0x05,
  OCD_THRESH_25mV = 0x06,
  OCD_THRESH_28mV = 0x07,
  OCD_THRESH_31mV = 0x08,
  OCD_THRESH_33mV = 0x09,
  OCD_THRESH_36mV = 0x0A,
  OCD_THRESH_39mV = 0x0B,
  OCD_THRESH_42mV = 0x0C,
  OCD_THRESH_44mV = 0x0D,
  OCD_THRESH_47mV = 0x0E,
  OCD_THRESH_50mV = 0x0F
} BQ76920_OCD_Thresh;

/**
  * @brief  Undervoltage protection delay (PROTECT3[1:0])
  */
typedef enum
{
  UV_DELAY_1s  = 0x00,
  UV_DELAY_4s  = 0x01,
  UV_DELAY_8s  = 0x02,
  UV_DELAY_16s = 0x03
} BQ76920_UV_Delay;

/**
  * @brief  Overvoltage protection delay (PROTECT3[3:2])
  */
typedef enum
{
  OV_DELAY_1s = 0x00,
  OV_DELAY_2s = 0x01,
  OV_DELAY_4s = 0x02,
  OV_DELAY_8s = 0x03
} BQ76920_OV_Delay;

/**
  * @brief  Cell voltage register base addresses for use with getCellVoltage()
  *
  * Each value is the address of the corresponding VCx_HI register.
  * The VCx_LO register is always VCx_HI + 1.
  */
typedef enum
{
  CELL_1 = VC1_HI,
  CELL_2 = VC2_HI,
  CELL_3 = VC3_HI,
  CELL_4 = VC4_HI,
  CELL_5 = VC5_HI
} BQ76920_Cell;

/**
  * @brief  BQ76920 device handle
  *
  * Populate via BQ76920_Initialise(). All driver functions take a pointer
  * to this struct. Do not modify fields directly after init.
  */
typedef struct
{
  /* I2C peripheral --------------------------------------------------------*/
  I2C_HandleTypeDef *i2cHandle;  /*!< HAL I2C handle (I2C1, 100 kHz, PB6/PB7) */
  uint16_t i2cAddr;              /*!< Detected I2C address (0x10 or 0x30)      */
  uint8_t  crcEnabled;           /*!< 1 if CRC mode (addr 0x18), 0 if no-CRC  */

  /* Pack configuration (set at init, treated as read-only thereafter) -----*/
  uint8_t  numCells;      /*!< Series cell count: 3, 4, or 5                  */
  float    ovTrip_V;      /*!< Overvoltage threshold per cell, V               */
  float    uvTrip_V;      /*!< Undervoltage threshold per cell, V              */
  uint32_t capacity_mAh; /*!< Nominal pack capacity, mAh                      */
  float    nominalV;      /*!< Nominal cell voltage, V (e.g. 3.6 for Li-Ion)  */

  /* ADC calibration (read from device registers at init) ------------------*/
  int8_t   OFFSET;        /*!< ADC offset trim, mV (signed)                   */
  uint16_t GAIN;          /*!< ADC gain, uV/LSB (typ. 365-396)               */

  /* Live telemetry (updated by get* functions) ----------------------------*/
  uint8_t  Alert[8];      /*!< SYS_STAT bit history; index = bit position 0-7 */
  int32_t  currentUsage;  /*!< Pack current, mA (negative = discharge)        */
  int32_t  wattUsage;     /*!< Instantaneous power, mW (negative = discharge) */
  float    Vcell[5];      /*!< Cell voltages, V; index 0 = cell 1             */
  float    Vpack;         /*!< Total pack voltage, V                           */

  /* State estimation ------------------------------------------------------*/
  float    SOC;           /*!< State of charge, %                              */
  float    SOCEnergy;     /*!< Energy-based SOC, %                             */
  float    SOCCapacity;   /*!< Capacity-based SOC, %                           */
  float    SOH;           /*!< State of health, %                              */
  float    SOHEnergy;     /*!< Energy-based SOH, %                             */
  float    SOHCapacity;   /*!< Capacity-based SOH, %                           */
  float    SOHOCV;        /*!< OCV-based SOH, %                                */
  float    smallestV;     /*!< Minimum cell voltage across pack, V             */
} BQ76920_t;

/* Exported function prototypes ----------------------------------------------*/

/**
  * @brief  Initialise the BQ76920 device handle and write startup config
  * @note   Writes CC_CFG = 0x19, enables ADC (SYS_CTRL1 ADC_EN), and reads
  *         factory ADC calibration (ADCGAIN1, ADCGAIN2, ADCOFFSET).
  * @param  bms           Pointer to uninitialised BQ76920_t handle
  * @param  i2c           Pointer to initialised HAL I2C handle
  * @param  numCells      Series cell count: 3, 4, or 5
  * @param  ovTrip_V      Overvoltage threshold per cell, V
  * @param  uvTrip_V      Undervoltage threshold per cell, V
  * @param  capacity_mAh  Nominal pack capacity, mAh
  * @param  nominalV      Nominal cell voltage, V
  * @retval HAL_StatusTypeDef  HAL_OK on success
  */
HAL_StatusTypeDef BQ76920_Initialise(BQ76920_t *bms,
                                     I2C_HandleTypeDef *i2c,
                                     uint8_t numCells,
                                     float ovTrip_V,
                                     float uvTrip_V,
                                     uint32_t capacity_mAh,
                                     float nominalV);

/**
  * @brief  Read and convert one cell voltage
  * @note   Result is stored in bms->Vcell[cell - 1] and also returned.
  * @param  bms   Pointer to initialised BQ76920_t handle
  * @param  cell  Cell number 1-5 (must be <= bms->numCells)
  * @retval float Cell voltage in V, or 0.0f on I2C error
  */
float getCellVoltage(BQ76920_t *bms, uint8_t cell);

/**
  * @brief  Read total pack voltage from BAT_HI/LO registers
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval float Pack voltage in V, or 0.0f on I2C error
  */
float getPackVoltage(BQ76920_t *bms);

/**
  * @brief  Read coulomb counter and calculate pack current
  * @note   Result is stored in bms->currentUsage (mA, signed).
  *         Negative values indicate discharge current.
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval float Pack current in mA (signed)
  */
float getCurrent(BQ76920_t *bms);

/**
  * @brief  Update coulomb-count state of charge estimate
  * @param  bms             Pointer to initialised BQ76920_t handle
  * @param  packCurrent_mA  Current reading in mA (negative = discharge)
  * @param  Vpack           Current pack voltage in V
  * @retval float Updated SOC in %
  */
float SOCPack(BQ76920_t *bms, float packCurrent_mA, float Vpack);

/**
  * @brief  Estimate state of health from remaining vs. nominal capacity
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval float SOH in %
  */
float SOHPack(BQ76920_t *bms);

/**
  * @brief  Read SYS_STAT register and update bms->Alert[] array
  * @note   Call this before getAlert(). Alert[] index matches bit position:
  *         index 0 = OCD, 1 = SCD, 2 = OV, 3 = UV, 4 = OVRD_ALERT,
  *         5 = DEVICE_XREADY, 7 = CC_READY.
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval None
  */
void readAlert(BQ76920_t *bms);

/**
  * @brief  Return one SYS_STAT bit from the last readAlert() call
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @param  bit  Bit index 0-7 (use BQ_STAT_* masks or bit position directly)
  * @retval uint8_t  1 if fault is active, 0 otherwise
  */
uint8_t getAlert(BQ76920_t *bms, uint8_t bit);

/**
  * @brief  Check whether any cell voltage is at or below bms->uvTrip_V
  * @note   Operates on bms->Vcell[]; call getCellVoltage() first.
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval uint8_t  1 if UV condition present, 0 otherwise
  */
uint8_t checkUV(BQ76920_t *bms);

/**
  * @brief  Check whether all cells have recovered above bms->uvTrip_V
  * @param  bms     Pointer to initialised BQ76920_t handle
  * @param  uvFlag  Previous return value of checkUV() for hysteresis tracking
  * @retval uint8_t  1 if all cells are above threshold, 0 otherwise
  */
uint8_t checkNotUV(BQ76920_t *bms, uint8_t uvFlag);

/**
  * @brief  Check whether any cell voltage is at or above bms->ovTrip_V
  * @note   Operates on bms->Vcell[]; call getCellVoltage() first.
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval uint8_t  1 if OV condition present, 0 otherwise
  */
uint8_t checkOV(BQ76920_t *bms);

/**
  * @brief  Check whether all cells have recovered below bms->ovTrip_V
  * @param  bms     Pointer to initialised BQ76920_t handle
  * @param  ovFlag  Previous return value of checkOV() for hysteresis tracking
  * @retval uint8_t  1 if all cells are below threshold, 0 otherwise
  */
uint8_t checkNotOV(BQ76920_t *bms, uint8_t ovFlag);

/**
  * @brief  Set CHG_ON bit in SYS_CTRL2 to enable the charge FET
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval HAL_StatusTypeDef
  */
HAL_StatusTypeDef turnCHGOn(BQ76920_t *bms);

/**
  * @brief  Set DSG_ON bit in SYS_CTRL2 to enable the discharge FET
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval HAL_StatusTypeDef
  */
HAL_StatusTypeDef turnDSGOn(BQ76920_t *bms);

/**
  * @brief  Clear CHG_ON bit in SYS_CTRL2 to disable the charge FET
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval HAL_StatusTypeDef
  */
HAL_StatusTypeDef turnCHGOff(BQ76920_t *bms);

/**
  * @brief  Clear DSG_ON bit in SYS_CTRL2 to disable the discharge FET
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval HAL_StatusTypeDef
  */
HAL_StatusTypeDef turnDSGOff(BQ76920_t *bms);

/**
  * @brief  Activate passive cell balancing on cells above the balance threshold
  * @note   Balancing is only enabled when |packCurrent_mA| is near zero
  *         (rest condition). Writes CELLBAL1 with the appropriate cell bitmask.
  * @param  bms             Pointer to initialised BQ76920_t handle
  * @param  packCurrent_mA  Current pack current, mA (signed)
  * @retval None
  */
void EnableBalanceCell(BQ76920_t *bms, float packCurrent_mA);

/**
  * @brief  Clear all active bits in SYS_STAT by writing 1 to each set bit
  * @note   Must be called after handling a fault before protection can re-arm.
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval HAL_StatusTypeDef
  */
HAL_StatusTypeDef CLEAR_SYS_STAT(BQ76920_t *bms);

/**
  * @brief  Enter SHIP (deep sleep) mode
  * @note   Required write sequence (BQ76920 datasheet):
  *           1. Write SHUT_B = 1 in SYS_CTRL1 (0x04)
  *           2. Write SHUT_A = 1 in SYS_CTRL1 within ~1 s
  *         After both bits are set the device stops responding on I2C.
  *         Wake-up requires an external pulse on the BOOT pin -- this is
  *         not handled in firmware.
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval HAL_StatusTypeDef  HAL_OK if both writes succeeded before shutdown
  */
HAL_StatusTypeDef BQ76920_EnterShipMode(BQ76920_t *bms);

/**
  * @brief  Compute CRC-8 over a byte array
  * @note   Uses polynomial 0x07 (BQ76920_CRC_POLY). In CRC mode (address
  *         BQ76920_ADDR_CRC), append the returned byte to every write payload
  *         and verify it on every read response.
  * @param  data  Pointer to input data buffer
  * @param  len   Number of bytes to process
  * @retval uint8_t  Computed CRC-8 byte
  */
uint8_t BQ76920_CRC8(uint8_t *data, uint8_t len);

/**
  * @brief  Read one register byte from the BQ76920
  * @note   In CRC mode the device appends a CRC byte; this function verifies
  *         it and returns HAL_ERROR on mismatch.
  * @param  bms   Pointer to initialised BQ76920_t handle
  * @param  reg   Register address (use defines above, e.g. SYS_STAT)
  * @param  data  Pointer to byte where the register value will be stored
  * @retval HAL_StatusTypeDef  HAL_OK on success, HAL_ERROR on NACK or CRC fail
  */
HAL_StatusTypeDef BQ76920_ReadRegister(BQ76920_t *bms, uint8_t reg, uint8_t *data);

/**
  * @brief  Write one register byte to the BQ76920
  * @note   In CRC mode this function appends a CRC byte to the payload before
  *         transmission.
  * @param  bms   Pointer to initialised BQ76920_t handle
  * @param  reg   Register address (use defines above, e.g. SYS_CTRL2)
  * @param  data  Byte value to write
  * @retval HAL_StatusTypeDef  HAL_OK on success, HAL_ERROR on NACK
  */
HAL_StatusTypeDef BQ76920_WriteRegister(BQ76920_t *bms, uint8_t reg, uint8_t data);

#endif /* INC_BQ76920_H_ */
