/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    i2c.c
  * @brief   This file provides code for the configuration
  *          of the I2C instances.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "i2c.h"

/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

I2C_HandleTypeDef hi2c1;

/* I2C1 init function */
void MX_I2C1_Init(void)
{

  /* USER CODE BEGIN I2C1_Init 0 */

  /* USER CODE END I2C1_Init 0 */

  /* USER CODE BEGIN I2C1_Init 1 */

  /* USER CODE END I2C1_Init 1 */
  hi2c1.Instance = I2C1;
  hi2c1.Init.ClockSpeed = 100000;
  hi2c1.Init.DutyCycle = I2C_DUTYCYCLE_2;
  hi2c1.Init.OwnAddress1 = 0;
  hi2c1.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
  hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
  hi2c1.Init.OwnAddress2 = 0;
  hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
  hi2c1.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
  if (HAL_I2C_Init(&hi2c1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN I2C1_Init 2 */

  /* USER CODE END I2C1_Init 2 */

}

void HAL_I2C_MspInit(I2C_HandleTypeDef* i2cHandle)
{

  GPIO_InitTypeDef GPIO_InitStruct = {0};
  if(i2cHandle->Instance==I2C1)
  {
  /* USER CODE BEGIN I2C1_MspInit 0 */

  /* USER CODE END I2C1_MspInit 0 */

    __HAL_RCC_GPIOB_CLK_ENABLE();
    /**I2C1 GPIO Configuration
    PB6     ------> I2C1_SCL
    PB7     ------> I2C1_SDA
    */
    GPIO_InitStruct.Pin = GPIO_PIN_6|GPIO_PIN_7;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_OD;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF4_I2C1;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    /* I2C1 clock enable */
    __HAL_RCC_I2C1_CLK_ENABLE();
  /* USER CODE BEGIN I2C1_MspInit 1 */

  /* USER CODE END I2C1_MspInit 1 */
  }
}

void HAL_I2C_MspDeInit(I2C_HandleTypeDef* i2cHandle)
{

  if(i2cHandle->Instance==I2C1)
  {
  /* USER CODE BEGIN I2C1_MspDeInit 0 */

  /* USER CODE END I2C1_MspDeInit 0 */
    /* Peripheral clock disable */
    __HAL_RCC_I2C1_CLK_DISABLE();

    /**I2C1 GPIO Configuration
    PB6     ------> I2C1_SCL
    PB7     ------> I2C1_SDA
    */
    HAL_GPIO_DeInit(GPIOB, GPIO_PIN_6);

    HAL_GPIO_DeInit(GPIOB, GPIO_PIN_7);

  /* USER CODE BEGIN I2C1_MspDeInit 1 */

  /* USER CODE END I2C1_MspDeInit 1 */
  }
}

/* USER CODE BEGIN 1 */

/**
  * @brief  Recover the I2C1 bus and re-init the peripheral.
  *
  * STM32F4 HAL I2C is well-known to wedge after a NACK: HAL_I2C_IsDeviceReady
  * leaves the AF (Acknowledge Failure) flag set and BUSY can stick high, so
  * subsequent transactions return HAL_BUSY/HAL_ERROR even when the slave is
  * fine.  Without explicit recovery, every retry inside main.c's 2-second
  * loop hits the same wedged peripheral and silently fails forever.
  *
  * Root cause observed on bench: when the bridge boots before the BQ76920
  * EVM has been BOOT-pulsed, the first IsDeviceReady NACKs at both 0x18 and
  * 0x08, wedging I2C1.  After BOOT, the chip ACKs at the bus level, but the
  * STM32 peripheral can no longer talk to it -- "works sometimes, fails
  * others" depending on whether the EVM was awake at the bridge's first
  * probe.  This routine breaks the trap by deinitialising the peripheral,
  * pulsing SCL to flush any stuck slave, and re-initialising cleanly.
  *
  * Safe to call anytime: the only side effects are <~10 ms of bus activity
  * and a peripheral reset.  Always returns the bus in a state where the
  * next HAL_I2C_* call starts from a clean slate.
  */
void MX_I2C1_BusRecover(void)
{
  GPIO_InitTypeDef gpio = {0};

  /* 1. Tear down the I2C peripheral cleanly. */
  HAL_I2C_DeInit(&hi2c1);

  /* 2. Reconfigure PB6 (SCL) and PB7 (SDA) as plain GPIO open-drain
   *    outputs so we can drive them by hand. */
  __HAL_RCC_GPIOB_CLK_ENABLE();
  gpio.Pin   = GPIO_PIN_6 | GPIO_PIN_7;
  gpio.Mode  = GPIO_MODE_OUTPUT_OD;
  gpio.Pull  = GPIO_NOPULL;
  gpio.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &gpio);

  /* 3. Release both lines (open-drain high) and let pull-ups settle. */
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6, GPIO_PIN_SET);
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_7, GPIO_PIN_SET);
  HAL_Delay(1U);

  /* 4. If a slave is mid-transaction with SDA stuck low, pulse SCL up to
   *    9 times (one full byte + ACK) so it advances and releases SDA. */
  for (uint8_t i = 0U; i < 9U; i++)
  {
    if (HAL_GPIO_ReadPin(GPIOB, GPIO_PIN_7) == GPIO_PIN_SET)
    {
      break;
    }
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6, GPIO_PIN_RESET);
    HAL_Delay(1U);
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6, GPIO_PIN_SET);
    HAL_Delay(1U);
  }

  /* 5. Manual STOP condition: SDA falling, then rising, while SCL is high. */
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_7, GPIO_PIN_RESET);
  HAL_Delay(1U);
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_7, GPIO_PIN_SET);
  HAL_Delay(1U);

  /* 6. Re-init the I2C peripheral.  HAL_I2C_Init internally calls
   *    HAL_I2C_MspInit which restores PB6/PB7 to AF4 open-drain mode. */
  MX_I2C1_Init();
}

/* USER CODE END 1 */

