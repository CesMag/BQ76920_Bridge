/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : bq76920.c
  * @brief          : STM32 HAL driver for the TI BQ76920 3S-5S Li-Ion AFE
  ******************************************************************************
  *
  * Implements all functions declared in bq76920.h.
  * I2C communication uses CRC-8 mode (address 0x18, polynomial 0x07).
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "bq76920.h"
#include <string.h>
#include <math.h>

/* Private defines -----------------------------------------------------------*/

/** @brief I2C timeout in milliseconds */
#define BQ_I2C_TIMEOUT  100U

/** @brief Sense resistor value in milliohms (BQ76920EVM uses 1 mohm) */
#define SENSE_RESISTOR_MOHM  1

/** @brief Coulomb counter LSB in uV (8.44 uV per datasheet) */
#define CC_LSB_UV  8.44f

/** @brief Balance threshold: only balance when |current| < this (mA) */
#define BALANCE_CURRENT_THRESH_MA  50

/** @brief Balance voltage delta in V -- cells above (smallest + delta) get balanced */
#define BALANCE_DELTA_V  0.020f

/* Private function prototypes -----------------------------------------------*/

static HAL_StatusTypeDef BQ76920_ReadRegisterPair(BQ76920_t *bms, uint8_t regHI,
                                                   uint8_t *hi, uint8_t *lo);

/* Exported functions --------------------------------------------------------*/

/**
  * @brief  Compute CRC-8 over a byte array (polynomial 0x07)
  * @param  data  Pointer to input data buffer
  * @param  len   Number of bytes to process
  * @retval uint8_t  Computed CRC-8 byte
  */
uint8_t BQ76920_CRC8(uint8_t *data, uint8_t len)
{
  uint8_t crc = 0x00U;

  for (uint8_t i = 0U; i < len; i++)
  {
    crc ^= data[i];
    for (uint8_t bit = 0U; bit < 8U; bit++)
    {
      if ((crc & 0x80U) != 0U)
      {
        crc = (uint8_t)((crc << 1U) ^ BQ76920_CRC_POLY);
      }
      else
      {
        crc <<= 1U;
      }
    }
  }

  return crc;
}

/**
  * @brief  Read one register byte from the BQ76920
  * @note   Automatically uses CRC or non-CRC protocol based on bms->crcEnabled.
  * @param  bms   Pointer to initialised BQ76920_t handle
  * @param  reg   Register address
  * @param  data  Pointer to byte where the register value will be stored
  * @retval HAL_StatusTypeDef  HAL_OK on success, HAL_ERROR on NACK or CRC fail
  */
HAL_StatusTypeDef BQ76920_ReadRegister(BQ76920_t *bms, uint8_t reg, uint8_t *data)
{
  HAL_StatusTypeDef status;

  if (bms->crcEnabled == 0U)
  {
    /* No-CRC mode: simple HAL_I2C_Mem_Read */
    return HAL_I2C_Mem_Read(bms->i2cHandle, bms->i2cAddr,
                            reg, I2C_MEMADD_SIZE_8BIT,
                            data, 1U, BQ_I2C_TIMEOUT);
  }

  /* CRC mode: manual two-phase with CRC verification */
  uint8_t txBuf[1];
  uint8_t rxBuf[2]; /* data + CRC */

  /* Phase 1: send register address */
  txBuf[0] = reg;
  status = HAL_I2C_Master_Transmit(bms->i2cHandle, bms->i2cAddr,
                                   txBuf, 1U, BQ_I2C_TIMEOUT);
  if (status != HAL_OK)
  {
    return status;
  }

  /* Phase 2: read data byte + CRC byte */
  status = HAL_I2C_Master_Receive(bms->i2cHandle, bms->i2cAddr,
                                  rxBuf, 2U, BQ_I2C_TIMEOUT);
  if (status != HAL_OK)
  {
    return status;
  }

  /* Verify CRC: computed over {addr_R, data} */
  uint8_t crcBuf[2];
  crcBuf[0] = bms->i2cAddr | 0x01U; /* read address */
  crcBuf[1] = rxBuf[0];             /* data byte    */

  if (BQ76920_CRC8(crcBuf, 2U) != rxBuf[1])
  {
    return HAL_ERROR;
  }

  *data = rxBuf[0];
  return HAL_OK;
}

/**
  * @brief  Write one register byte to the BQ76920
  * @note   Automatically uses CRC or non-CRC protocol based on bms->crcEnabled.
  * @param  bms   Pointer to initialised BQ76920_t handle
  * @param  reg   Register address
  * @param  data  Byte value to write
  * @retval HAL_StatusTypeDef  HAL_OK on success, HAL_ERROR on NACK
  */
HAL_StatusTypeDef BQ76920_WriteRegister(BQ76920_t *bms, uint8_t reg, uint8_t data)
{
  if (bms->crcEnabled == 0U)
  {
    /* No-CRC mode: simple HAL_I2C_Mem_Write */
    return HAL_I2C_Mem_Write(bms->i2cHandle, bms->i2cAddr,
                             reg, I2C_MEMADD_SIZE_8BIT,
                             &data, 1U, BQ_I2C_TIMEOUT);
  }

  /* CRC mode: append CRC byte to payload */
  uint8_t txBuf[3];
  uint8_t crcBuf[3];

  crcBuf[0] = bms->i2cAddr; /* write address */
  crcBuf[1] = reg;
  crcBuf[2] = data;

  txBuf[0] = reg;
  txBuf[1] = data;
  txBuf[2] = BQ76920_CRC8(crcBuf, 3U);

  return HAL_I2C_Master_Transmit(bms->i2cHandle, bms->i2cAddr,
                                 txBuf, 3U, BQ_I2C_TIMEOUT);
}

/**
  * @brief  Read a HI/LO register pair (used for cell voltage, temperature, etc.)
  * @param  bms    Pointer to initialised BQ76920_t handle
  * @param  regHI  Address of the HI register (LO is regHI + 1)
  * @param  hi     Pointer to store HI byte
  * @param  lo     Pointer to store LO byte
  * @retval HAL_StatusTypeDef
  */
static HAL_StatusTypeDef BQ76920_ReadRegisterPair(BQ76920_t *bms, uint8_t regHI,
                                                   uint8_t *hi, uint8_t *lo)
{
  HAL_StatusTypeDef status;

  status = BQ76920_ReadRegister(bms, regHI, hi);
  if (status != HAL_OK)
  {
    return status;
  }

  return BQ76920_ReadRegister(bms, (uint8_t)(regHI + 1U), lo);
}

/**
  * @brief  Initialise the BQ76920 device handle and write startup config
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
                                     float nominalV)
{
  HAL_StatusTypeDef status;
  uint8_t regVal;

  /* Store configuration */
  memset(bms, 0, sizeof(BQ76920_t));
  bms->i2cHandle   = i2c;
  bms->numCells    = numCells;
  bms->ovTrip_V    = ovTrip_V;
  bms->uvTrip_V    = uvTrip_V;
  bms->capacity_mAh = capacity_mAh;
  bms->nominalV    = nominalV;

  /* Auto-detect I2C address: try CRC mode first, then no-CRC */
  bms->i2cAddr    = BQ76920_ADDR_CRC;
  bms->crcEnabled = 1U;

  status = HAL_I2C_IsDeviceReady(i2c, BQ76920_ADDR_CRC, 3U, BQ_I2C_TIMEOUT);
  if (status != HAL_OK)
  {
    /* CRC address didn't respond -- try no-CRC address */
    status = HAL_I2C_IsDeviceReady(i2c, BQ76920_ADDR_NO_CRC, 3U, BQ_I2C_TIMEOUT);
    if (status != HAL_OK)
    {
      /* Neither address responded */
      return status;
    }
    bms->i2cAddr    = BQ76920_ADDR_NO_CRC;
    bms->crcEnabled = 0U;
  }

  /* Clear all faults first -- BQ76920 won't enable CC_EN or FETs
     while protection faults are active */
  status = BQ76920_WriteRegister(bms, SYS_STAT, 0xFFU);
  if (status != HAL_OK)
  {
    return status;
  }

  /* Write CC_CFG = 0x19 (required at startup per datasheet) */
  status = BQ76920_WriteRegister(bms, CC_CFG, 0x19U);
  if (status != HAL_OK)
  {
    return status;
  }

  /* Enable ADC: set ADC_EN bit in SYS_CTRL1 */
  status = BQ76920_ReadRegister(bms, SYS_CTRL1, &regVal);
  if (status != HAL_OK)
  {
    return status;
  }
  regVal |= BQ_CTRL1_ADC_EN;
  status = BQ76920_WriteRegister(bms, SYS_CTRL1, regVal);
  if (status != HAL_OK)
  {
    return status;
  }

  /* Enable coulomb counter: set CC_EN bit in SYS_CTRL2 */
  status = BQ76920_ReadRegister(bms, SYS_CTRL2, &regVal);
  if (status != HAL_OK)
  {
    return status;
  }
  regVal |= BQ_CTRL2_CC_EN;
  status = BQ76920_WriteRegister(bms, SYS_CTRL2, regVal);
  if (status != HAL_OK)
  {
    return status;
  }

  /* Read factory ADC calibration: GAIN and OFFSET */
  uint8_t adcGain1, adcGain2, adcOffset;

  status = BQ76920_ReadRegister(bms, ADCGAIN1, &adcGain1);
  if (status != HAL_OK)
  {
    return status;
  }

  status = BQ76920_ReadRegister(bms, ADCGAIN2, &adcGain2);
  if (status != HAL_OK)
  {
    return status;
  }

  status = BQ76920_ReadRegister(bms, ADCOFFSET, &adcOffset);
  if (status != HAL_OK)
  {
    return status;
  }

  /* GAIN (uV/LSB) = 365 + { ADCGAIN1[4:3] << 3 | ADCGAIN2[2:0] } */
  uint8_t gainCode = (uint8_t)(((adcGain1 >> 3U) & 0x03U) << 3U)
                   | (uint8_t)(adcGain2 & 0x07U);
  bms->GAIN = (uint16_t)(365U + gainCode);

  /* OFFSET is a signed byte */
  bms->OFFSET = (int8_t)adcOffset;

  return HAL_OK;
}

/**
  * @brief  Read and convert one cell voltage
  * @param  bms   Pointer to initialised BQ76920_t handle
  * @param  cell  Cell number 1-5 (must be <= bms->numCells)
  * @retval float Cell voltage in V, or 0.0f on I2C error
  */
float getCellVoltage(BQ76920_t *bms, uint8_t cell)
{
  if (cell < 1U || cell > bms->numCells)
  {
    return 0.0f;
  }

  /* Cell register base addresses: VC1_HI = 0x0C, each cell offset by 2 */
  uint8_t regHI = (uint8_t)(VC1_HI + ((cell - 1U) * 2U));
  uint8_t hi, lo;

  if (BQ76920_ReadRegisterPair(bms, regHI, &hi, &lo) != HAL_OK)
  {
    return 0.0f;
  }

  /* 14-bit raw value: HI[5:0] << 8 | LO[7:0] */
  uint16_t raw = (uint16_t)(((uint16_t)(hi & 0x3FU) << 8U) | lo);

  /* Voltage (mV) = (GAIN * raw) / 1000 + OFFSET */
  float mV = ((float)bms->GAIN * (float)raw) / 1000.0f + (float)bms->OFFSET;
  float volts = mV / 1000.0f;

  bms->Vcell[cell - 1U] = volts;
  return volts;
}

/**
  * @brief  Read total pack voltage from BAT_HI/LO registers
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval float Pack voltage in V, or 0.0f on I2C error
  */
float getPackVoltage(BQ76920_t *bms)
{
  uint8_t hi, lo;

  if (BQ76920_ReadRegisterPair(bms, BAT_HI, &hi, &lo) != HAL_OK)
  {
    return 0.0f;
  }

  /* Pack voltage raw = (HI << 8) | LO, full 16-bit */
  uint16_t raw = (uint16_t)(((uint16_t)hi << 8U) | lo);

  /* Pack voltage (mV) = 4 * GAIN * raw / 1000 + (numCells * OFFSET) */
  float mV = (4.0f * (float)bms->GAIN * (float)raw) / 1000.0f
           + ((float)bms->numCells * (float)bms->OFFSET);
  float volts = mV / 1000.0f;

  bms->Vpack = volts;
  return volts;
}

/**
  * @brief  Read coulomb counter and calculate pack current
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval float Pack current in mA (signed, negative = discharge)
  */
float getCurrent(BQ76920_t *bms)
{
  uint8_t hi, lo;

  if (BQ76920_ReadRegisterPair(bms, CC_HI, &hi, &lo) != HAL_OK)
  {
    return 0.0f;
  }

  /* Signed 16-bit coulomb counter value */
  int16_t raw = (int16_t)(((uint16_t)hi << 8U) | lo);

  /* Current (mA) = raw * 8.44 uV / Rsense (mohm) */
  float current_mA = ((float)raw * CC_LSB_UV) / (float)SENSE_RESISTOR_MOHM;

  bms->currentUsage = (int32_t)current_mA;
  bms->wattUsage = (int32_t)(current_mA * bms->Vpack);

  return current_mA;
}

/**
  * @brief  Update coulomb-count state of charge estimate
  * @param  bms             Pointer to initialised BQ76920_t handle
  * @param  packCurrent_mA  Current reading in mA (negative = discharge)
  * @param  Vpack           Current pack voltage in V
  * @retval float Updated SOC in %
  */
float SOCPack(BQ76920_t *bms, float packCurrent_mA, float Vpack)
{
  /* Simple coulomb counting: integrate current over time */
  /* SOCCapacity tracks mAh consumed */
  /* This is a simplified model; call periodically (e.g. every 250 ms) */
  float dt_h = 0.250f / 3600.0f; /* assume 250 ms interval */
  bms->SOCCapacity += packCurrent_mA * dt_h;

  if (bms->capacity_mAh > 0U)
  {
    bms->SOC = 100.0f * (1.0f - (bms->SOCCapacity / (float)bms->capacity_mAh));
    if (bms->SOC > 100.0f)
    {
      bms->SOC = 100.0f;
    }
    if (bms->SOC < 0.0f)
    {
      bms->SOC = 0.0f;
    }
  }

  /* Energy-based SOC */
  float nominalEnergy = (float)bms->capacity_mAh * bms->nominalV * (float)bms->numCells;
  if (nominalEnergy > 0.0f)
  {
    bms->SOCEnergy = 100.0f * (Vpack * packCurrent_mA) / nominalEnergy;
  }

  return bms->SOC;
}

/**
  * @brief  Estimate state of health from remaining vs. nominal capacity
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval float SOH in %
  */
float SOHPack(BQ76920_t *bms)
{
  /* Placeholder: SOH requires full charge/discharge cycle data */
  /* Return 100% until real cycle data is available */
  bms->SOH = 100.0f;
  bms->SOHCapacity = 100.0f;
  bms->SOHEnergy = 100.0f;
  bms->SOHOCV = 100.0f;
  return bms->SOH;
}

/**
  * @brief  Read SYS_STAT register and update bms->Alert[] array
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval None
  */
void readAlert(BQ76920_t *bms)
{
  uint8_t stat;

  if (BQ76920_ReadRegister(bms, SYS_STAT, &stat) != HAL_OK)
  {
    return;
  }

  for (uint8_t i = 0U; i < 8U; i++)
  {
    bms->Alert[i] = (stat >> i) & 0x01U;
  }
}

/**
  * @brief  Return one SYS_STAT bit from the last readAlert() call
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @param  bit  Bit index 0-7
  * @retval uint8_t  1 if fault is active, 0 otherwise
  */
uint8_t getAlert(BQ76920_t *bms, uint8_t bit)
{
  if (bit > 7U)
  {
    return 0U;
  }
  return bms->Alert[bit];
}

/**
  * @brief  Check whether any cell voltage is at or below bms->uvTrip_V
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval uint8_t  1 if UV condition present, 0 otherwise
  */
uint8_t checkUV(BQ76920_t *bms)
{
  for (uint8_t i = 0U; i < bms->numCells; i++)
  {
    if (bms->Vcell[i] <= bms->uvTrip_V)
    {
      return 1U;
    }
  }
  return 0U;
}

/**
  * @brief  Check whether all cells have recovered above bms->uvTrip_V
  * @param  bms     Pointer to initialised BQ76920_t handle
  * @param  uvFlag  Previous return value of checkUV()
  * @retval uint8_t  1 if all cells are above threshold, 0 otherwise
  */
uint8_t checkNotUV(BQ76920_t *bms, uint8_t uvFlag)
{
  (void)uvFlag;
  for (uint8_t i = 0U; i < bms->numCells; i++)
  {
    if (bms->Vcell[i] <= bms->uvTrip_V)
    {
      return 0U;
    }
  }
  return 1U;
}

/**
  * @brief  Check whether any cell voltage is at or above bms->ovTrip_V
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval uint8_t  1 if OV condition present, 0 otherwise
  */
uint8_t checkOV(BQ76920_t *bms)
{
  for (uint8_t i = 0U; i < bms->numCells; i++)
  {
    if (bms->Vcell[i] >= bms->ovTrip_V)
    {
      return 1U;
    }
  }
  return 0U;
}

/**
  * @brief  Check whether all cells have recovered below bms->ovTrip_V
  * @param  bms     Pointer to initialised BQ76920_t handle
  * @param  ovFlag  Previous return value of checkOV()
  * @retval uint8_t  1 if all cells are below threshold, 0 otherwise
  */
uint8_t checkNotOV(BQ76920_t *bms, uint8_t ovFlag)
{
  (void)ovFlag;
  for (uint8_t i = 0U; i < bms->numCells; i++)
  {
    if (bms->Vcell[i] >= bms->ovTrip_V)
    {
      return 0U;
    }
  }
  return 1U;
}

/**
  * @brief  Set CHG_ON bit in SYS_CTRL2 to enable the charge FET
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval HAL_StatusTypeDef
  */
HAL_StatusTypeDef turnCHGOn(BQ76920_t *bms)
{
  uint8_t regVal;
  HAL_StatusTypeDef status;

  status = BQ76920_ReadRegister(bms, SYS_CTRL2, &regVal);
  if (status != HAL_OK)
  {
    return status;
  }

  regVal |= BQ_CTRL2_CHG_ON;
  return BQ76920_WriteRegister(bms, SYS_CTRL2, regVal);
}

/**
  * @brief  Clear CHG_ON bit in SYS_CTRL2 to disable the charge FET
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval HAL_StatusTypeDef
  */
HAL_StatusTypeDef turnCHGOff(BQ76920_t *bms)
{
  uint8_t regVal;
  HAL_StatusTypeDef status;

  status = BQ76920_ReadRegister(bms, SYS_CTRL2, &regVal);
  if (status != HAL_OK)
  {
    return status;
  }

  regVal &= (uint8_t)~BQ_CTRL2_CHG_ON;
  return BQ76920_WriteRegister(bms, SYS_CTRL2, regVal);
}

/**
  * @brief  Set DSG_ON bit in SYS_CTRL2 to enable the discharge FET
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval HAL_StatusTypeDef
  */
HAL_StatusTypeDef turnDSGOn(BQ76920_t *bms)
{
  uint8_t regVal;
  HAL_StatusTypeDef status;

  status = BQ76920_ReadRegister(bms, SYS_CTRL2, &regVal);
  if (status != HAL_OK)
  {
    return status;
  }

  regVal |= BQ_CTRL2_DSG_ON;
  return BQ76920_WriteRegister(bms, SYS_CTRL2, regVal);
}

/**
  * @brief  Clear DSG_ON bit in SYS_CTRL2 to disable the discharge FET
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval HAL_StatusTypeDef
  */
HAL_StatusTypeDef turnDSGOff(BQ76920_t *bms)
{
  uint8_t regVal;
  HAL_StatusTypeDef status;

  status = BQ76920_ReadRegister(bms, SYS_CTRL2, &regVal);
  if (status != HAL_OK)
  {
    return status;
  }

  regVal &= (uint8_t)~BQ_CTRL2_DSG_ON;
  return BQ76920_WriteRegister(bms, SYS_CTRL2, regVal);
}

/**
  * @brief  Activate passive cell balancing on cells above the balance threshold
  * @param  bms             Pointer to initialised BQ76920_t handle
  * @param  packCurrent_mA  Current pack current, mA (signed)
  * @retval None
  */
void EnableBalanceCell(BQ76920_t *bms, float packCurrent_mA)
{
  /* Only balance when pack is at rest */
  if (fabsf(packCurrent_mA) > (float)BALANCE_CURRENT_THRESH_MA)
  {
    /* Turn off all balancing */
    BQ76920_WriteRegister(bms, CELLBAL1, 0x00U);
    return;
  }

  /* Find minimum cell voltage */
  float minV = bms->Vcell[0];
  for (uint8_t i = 1U; i < bms->numCells; i++)
  {
    if (bms->Vcell[i] < minV)
    {
      minV = bms->Vcell[i];
    }
  }
  bms->smallestV = minV;

  /* Build CELLBAL1 bitmask: enable balancing on cells above threshold */
  uint8_t balMask = 0x00U;
  for (uint8_t i = 0U; i < bms->numCells; i++)
  {
    if (bms->Vcell[i] > (minV + BALANCE_DELTA_V))
    {
      balMask |= (uint8_t)(1U << i);
    }
  }

  BQ76920_WriteRegister(bms, CELLBAL1, balMask);
}

/**
  * @brief  Clear all active bits in SYS_STAT
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval HAL_StatusTypeDef
  */
HAL_StatusTypeDef CLEAR_SYS_STAT(BQ76920_t *bms)
{
  /* Writing 1 to each bit clears it */
  return BQ76920_WriteRegister(bms, SYS_STAT, 0xFFU);
}

/**
  * @brief  Enter SHIP (deep sleep) mode
  * @param  bms  Pointer to initialised BQ76920_t handle
  * @retval HAL_StatusTypeDef  HAL_OK if both writes succeeded
  */
HAL_StatusTypeDef BQ76920_EnterShipMode(BQ76920_t *bms)
{
  HAL_StatusTypeDef status;
  uint8_t regVal;

  /* Step 1: set SHUT_B in SYS_CTRL1 */
  status = BQ76920_ReadRegister(bms, SYS_CTRL1, &regVal);
  if (status != HAL_OK)
  {
    return status;
  }

  regVal |= BQ_CTRL1_SHUT_B;
  regVal &= (uint8_t)~BQ_CTRL1_SHUT_A; /* ensure SHUT_A is clear */
  status = BQ76920_WriteRegister(bms, SYS_CTRL1, regVal);
  if (status != HAL_OK)
  {
    return status;
  }

  /* Step 2: set SHUT_A in SYS_CTRL1 (must happen within ~1 s) */
  regVal |= BQ_CTRL1_SHUT_A;
  status = BQ76920_WriteRegister(bms, SYS_CTRL1, regVal);

  /* After this write the device enters SHIP mode and stops responding */
  return status;
}
