/**
  * @file    test_bq76920_protocol.c
  * @brief   Unit tests for BQ76920 transport behavior
  */
#include <string.h>

#include "unity.h"
#include "bq76920.h"
#include "mock_hal_i2c.h"

static BQ76920_t bms;
static I2C_HandleTypeDef hi2c_mock;

void setUp(void)
{
  MockI2C_Reset();
  bms.i2cHandle = &hi2c_mock;
  bms.i2cAddr = BQ76920_ADDR_CRC;
  bms.crcEnabled = 1U;
}

void tearDown(void) {}

void test_read_register_crc_mode_uses_transmit_then_receive(void)
{
  uint8_t reg = SYS_CTRL1;
  uint8_t value = 0x10U;
  uint8_t crcInput[2] = { (uint8_t)(BQ76920_ADDR_CRC | 0x01U), value };
  uint8_t rx[2] = { value, BQ76920_CRC8(crcInput, 2U) };
  uint8_t out = 0U;

  MockI2C_ExpectTransmitStatus(HAL_OK);
  MockI2C_ExpectReceive(rx, 2U, HAL_OK);

  TEST_ASSERT_EQUAL(HAL_OK, BQ76920_ReadRegister(&bms, reg, &out));
  TEST_ASSERT_EQUAL_HEX8(value, out);
  TEST_ASSERT_EQUAL_UINT32(2U, MockI2C_GetTransactionCount());
}

void test_read_register_non_crc_mode_uses_mem_read(void)
{
  uint8_t out = 0U;
  uint8_t value = 0x19U;

  bms.i2cAddr = BQ76920_ADDR_NO_CRC;
  bms.crcEnabled = 0U;
  MockI2C_ExpectMemRead(BQ76920_ADDR_NO_CRC, CC_CFG, &value, 1U, HAL_OK);

  TEST_ASSERT_EQUAL(HAL_OK, BQ76920_ReadRegister(&bms, CC_CFG, &out));
  TEST_ASSERT_EQUAL_HEX8(value, out);

  const MockI2C_Transaction_t *txn = MockI2C_GetTransaction(0U);
  TEST_ASSERT_NOT_NULL(txn);
  TEST_ASSERT_EQUAL_HEX16(BQ76920_ADDR_NO_CRC, txn->addr);
  TEST_ASSERT_EQUAL_HEX16(CC_CFG, txn->reg);
}

void test_write_register_crc_mode_appends_crc_byte(void)
{
  uint8_t expected[3] = { CC_CFG, 0x19U, 0U };
  uint8_t crcInput[3] = { BQ76920_ADDR_CRC, CC_CFG, 0x19U };

  expected[2] = BQ76920_CRC8(crcInput, 3U);
  MockI2C_ExpectTransmitStatus(HAL_OK);

  TEST_ASSERT_EQUAL(HAL_OK, BQ76920_WriteRegister(&bms, CC_CFG, 0x19U));

  const MockI2C_Transaction_t *txn = MockI2C_GetTransaction(0U);
  TEST_ASSERT_NOT_NULL(txn);
  TEST_ASSERT_EQUAL_HEX16(BQ76920_ADDR_CRC, txn->addr);
  TEST_ASSERT_EQUAL_UINT8_ARRAY(expected, txn->data, 3U);
}

void test_write_register_non_crc_mode_uses_mem_write(void)
{
  uint8_t value = 0x19U;

  bms.i2cAddr = BQ76920_ADDR_NO_CRC;
  bms.crcEnabled = 0U;
  MockI2C_ExpectMemWrite(BQ76920_ADDR_NO_CRC, CC_CFG, &value, 1U, HAL_OK);

  TEST_ASSERT_EQUAL(HAL_OK, BQ76920_WriteRegister(&bms, CC_CFG, value));

  const MockI2C_Transaction_t *txn = MockI2C_GetTransaction(0U);
  TEST_ASSERT_NOT_NULL(txn);
  TEST_ASSERT_EQUAL_HEX16(BQ76920_ADDR_NO_CRC, txn->addr);
  TEST_ASSERT_EQUAL_HEX16(CC_CFG, txn->reg);
  TEST_ASSERT_EQUAL_HEX8(value, txn->data[0]);
}

void test_initialise_falls_back_to_non_crc_and_configures_device(void)
{
  BQ76920_t localBms;
  uint8_t zero = 0x00U;
  uint8_t gain1 = 0x10U;
  uint8_t gain2 = 0x03U;
  uint8_t offset = 0xFEU;
  uint8_t clearAll = 0xFFU;
  uint8_t ccCfg = 0x19U;
  uint8_t adcEnable = BQ_CTRL1_ADC_EN;
  uint8_t ccEnable = BQ_CTRL2_CC_EN;

  MockI2C_ExpectDeviceReady(BQ76920_ADDR_CRC, HAL_ERROR);
  MockI2C_ExpectDeviceReady(BQ76920_ADDR_NO_CRC, HAL_OK);
  MockI2C_ExpectMemWrite(BQ76920_ADDR_NO_CRC, SYS_STAT, &clearAll, 1U, HAL_OK);
  MockI2C_ExpectMemWrite(BQ76920_ADDR_NO_CRC, CC_CFG, &ccCfg, 1U, HAL_OK);
  MockI2C_ExpectMemRead(BQ76920_ADDR_NO_CRC, SYS_CTRL1, &zero, 1U, HAL_OK);
  MockI2C_ExpectMemWrite(BQ76920_ADDR_NO_CRC, SYS_CTRL1, &adcEnable, 1U, HAL_OK);
  MockI2C_ExpectMemRead(BQ76920_ADDR_NO_CRC, SYS_CTRL2, &zero, 1U, HAL_OK);
  MockI2C_ExpectMemWrite(BQ76920_ADDR_NO_CRC, SYS_CTRL2, &ccEnable, 1U, HAL_OK);
  MockI2C_ExpectMemRead(BQ76920_ADDR_NO_CRC, ADCGAIN1, &gain1, 1U, HAL_OK);
  MockI2C_ExpectMemRead(BQ76920_ADDR_NO_CRC, ADCGAIN2, &gain2, 1U, HAL_OK);
  MockI2C_ExpectMemRead(BQ76920_ADDR_NO_CRC, ADCOFFSET, &offset, 1U, HAL_OK);

  TEST_ASSERT_EQUAL(HAL_OK,
                    BQ76920_Initialise(&localBms, &hi2c_mock, 5U,
                                       4.25f, 2.8f, 2600U, 3.6f));

  TEST_ASSERT_EQUAL_HEX16(BQ76920_ADDR_NO_CRC, localBms.i2cAddr);
  TEST_ASSERT_EQUAL_UINT8(0U, localBms.crcEnabled);
  TEST_ASSERT_EQUAL_UINT16(384U, localBms.GAIN);
  TEST_ASSERT_EQUAL_INT8(-2, localBms.OFFSET);
}

/* Regression: fix/bq-reinit-on-no-device
 *
 * When neither I2C address responds at boot, main loop calls
 * BQ76920_Initialise() again every 2 s until the device appears.  These
 * two tests lock in the contract main.c depends on: a failing init returns
 * HAL_ERROR without touching configuration registers, and a subsequent
 * successful init on the same struct yields clean state (no stale bytes
 * carried over from the failed attempt). */

void test_initialise_returns_error_when_neither_address_responds(void)
{
  BQ76920_t localBms;
  /* Pre-fill with sentinel bytes to prove memset inside Initialise wipes state. */
  memset(&localBms, 0xAAU, sizeof(localBms));

  MockI2C_ExpectDeviceReady(BQ76920_ADDR_CRC, HAL_ERROR);
  MockI2C_ExpectDeviceReady(BQ76920_ADDR_NO_CRC, HAL_ERROR);

  TEST_ASSERT_EQUAL(HAL_ERROR,
                    BQ76920_Initialise(&localBms, &hi2c_mock, 5U,
                                       4.25f, 2.8f, 2600U, 3.6f));

  /* Only the two IsDeviceReady probes should have run.  No register I/O. */
  TEST_ASSERT_EQUAL_UINT32(2U, MockI2C_GetTransactionCount());
}

void test_initialise_retry_succeeds_after_initial_failure(void)
{
  BQ76920_t localBms;
  uint8_t zero = 0x00U;
  uint8_t gain1 = 0x10U;
  uint8_t gain2 = 0x03U;
  uint8_t offset = 0xFEU;
  uint8_t clearAll = 0xFFU;
  uint8_t ccCfg = 0x19U;
  uint8_t adcEnable = BQ_CTRL1_ADC_EN;
  uint8_t ccEnable = BQ_CTRL2_CC_EN;

  /* First attempt: device absent -- both addresses NACK. */
  MockI2C_ExpectDeviceReady(BQ76920_ADDR_CRC, HAL_ERROR);
  MockI2C_ExpectDeviceReady(BQ76920_ADDR_NO_CRC, HAL_ERROR);
  TEST_ASSERT_EQUAL(HAL_ERROR,
                    BQ76920_Initialise(&localBms, &hi2c_mock, 5U,
                                       4.25f, 2.8f, 2600U, 3.6f));

  /* Second attempt (2 s later in main loop): device now responds on
   * no-CRC address.  Queue the full happy-path expectations. */
  MockI2C_ExpectDeviceReady(BQ76920_ADDR_CRC, HAL_ERROR);
  MockI2C_ExpectDeviceReady(BQ76920_ADDR_NO_CRC, HAL_OK);
  MockI2C_ExpectMemWrite(BQ76920_ADDR_NO_CRC, SYS_STAT, &clearAll, 1U, HAL_OK);
  MockI2C_ExpectMemWrite(BQ76920_ADDR_NO_CRC, CC_CFG, &ccCfg, 1U, HAL_OK);
  MockI2C_ExpectMemRead(BQ76920_ADDR_NO_CRC, SYS_CTRL1, &zero, 1U, HAL_OK);
  MockI2C_ExpectMemWrite(BQ76920_ADDR_NO_CRC, SYS_CTRL1, &adcEnable, 1U, HAL_OK);
  MockI2C_ExpectMemRead(BQ76920_ADDR_NO_CRC, SYS_CTRL2, &zero, 1U, HAL_OK);
  MockI2C_ExpectMemWrite(BQ76920_ADDR_NO_CRC, SYS_CTRL2, &ccEnable, 1U, HAL_OK);
  MockI2C_ExpectMemRead(BQ76920_ADDR_NO_CRC, ADCGAIN1, &gain1, 1U, HAL_OK);
  MockI2C_ExpectMemRead(BQ76920_ADDR_NO_CRC, ADCGAIN2, &gain2, 1U, HAL_OK);
  MockI2C_ExpectMemRead(BQ76920_ADDR_NO_CRC, ADCOFFSET, &offset, 1U, HAL_OK);

  TEST_ASSERT_EQUAL(HAL_OK,
                    BQ76920_Initialise(&localBms, &hi2c_mock, 5U,
                                       4.25f, 2.8f, 2600U, 3.6f));

  /* Struct must reflect the retry's result, not stale fields from the
   * failed attempt (which left i2cAddr at BQ76920_ADDR_CRC). */
  TEST_ASSERT_EQUAL_HEX16(BQ76920_ADDR_NO_CRC, localBms.i2cAddr);
  TEST_ASSERT_EQUAL_UINT8(0U, localBms.crcEnabled);
  TEST_ASSERT_EQUAL_UINT16(384U, localBms.GAIN);
  TEST_ASSERT_EQUAL_INT8(-2, localBms.OFFSET);
  TEST_ASSERT_EQUAL_UINT8(5U, localBms.numCells);
  TEST_ASSERT_EQUAL_PTR(&hi2c_mock, localBms.i2cHandle);
}

int main(void)
{
  UNITY_BEGIN();

  RUN_TEST(test_read_register_crc_mode_uses_transmit_then_receive);
  RUN_TEST(test_read_register_non_crc_mode_uses_mem_read);
  RUN_TEST(test_write_register_crc_mode_appends_crc_byte);
  RUN_TEST(test_write_register_non_crc_mode_uses_mem_write);
  RUN_TEST(test_initialise_falls_back_to_non_crc_and_configures_device);
  RUN_TEST(test_initialise_returns_error_when_neither_address_responds);
  RUN_TEST(test_initialise_retry_succeeds_after_initial_failure);

  return UNITY_END();
}
