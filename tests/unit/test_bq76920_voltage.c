/**
  * @file    test_bq76920_voltage.c
  * @brief   Unit tests for BQ76920 voltage conversion and I2C register protocol
  *
  * Tests cell voltage, pack voltage, and current calculations using
  * mocked I2C responses. Verifies the ADC gain/offset math against
  * datasheet formulas.
  */
#include "unity.h"
#include "bq76920.h"
#include "mock_hal_i2c.h"

static BQ76920_t bms;
static I2C_HandleTypeDef hi2c_mock;

void setUp(void)
{
  MockI2C_Reset();

  /* Set up a BMS handle with known calibration values */
  bms.i2cHandle   = &hi2c_mock;
  bms.numCells    = 5;
  bms.ovTrip_V    = 4.25f;
  bms.uvTrip_V    = 2.8f;
  bms.capacity_mAh = 2600;
  bms.nominalV    = 3.6f;
  bms.GAIN        = 380;  /* Typical: 365 + 15 */
  bms.OFFSET      = 0;    /* Zero offset for clean math */

  for (int i = 0; i < 5; i++)
  {
    bms.Vcell[i] = 0.0f;
  }
  bms.Vpack = 0.0f;
}

void tearDown(void) {}

/* ---- Helper: load a mock I2C read response with valid CRC --------------- */

static void mock_register_read(uint8_t value)
{
  /* ReadRegister does: Transmit(reg), then Receive({data, crc})
     CRC is over {addr_R, data} = {0x31, value} */
  uint8_t crcBuf[2] = {0x31, value};
  uint8_t crc = BQ76920_CRC8(crcBuf, 2);
  uint8_t rxData[2] = {value, crc};
  MockI2C_ExpectReceive(rxData, 2, HAL_OK);
}

/* ---- Cell voltage conversion tests -------------------------------------- */

void test_cell_voltage_zero_raw(void)
{
  /* HI=0x00, LO=0x00 -> raw=0 -> mV = (380*0)/1000 + 0 = 0 mV */
  mock_register_read(0x00); /* HI byte */
  mock_register_read(0x00); /* LO byte */

  float v = getCellVoltage(&bms, 1);
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, v);
}

void test_cell_voltage_midrange(void)
{
  /* Target: ~3.6V cell
     mV = (GAIN * raw) / 1000 + OFFSET
     3600 = (380 * raw) / 1000 + 0
     raw = 3600 * 1000 / 380 = 9473.68 -> 9474 (0x2502)
     HI = (9474 >> 8) & 0x3F = 0x25, LO = 9474 & 0xFF = 0x02 */
  mock_register_read(0x25); /* HI */
  mock_register_read(0x02); /* LO */

  float v = getCellVoltage(&bms, 1);
  /* Expected: (380 * 9474) / 1000 / 1000 = 3.600 V */
  float expected = (380.0f * 9474.0f) / 1000.0f / 1000.0f;
  TEST_ASSERT_FLOAT_WITHIN(0.002f, expected, v);
}

void test_cell_voltage_max_14bit(void)
{
  /* Maximum 14-bit value: 0x3FFF = 16383
     mV = (380 * 16383) / 1000 = 6225.54 mV = 6.226 V
     This is above any real cell voltage but tests the math range */
  mock_register_read(0x3F); /* HI = 0x3F (bits [5:0] all set) */
  mock_register_read(0xFF); /* LO = 0xFF */

  float v = getCellVoltage(&bms, 1);
  float expected = (380.0f * 16383.0f) / 1000.0f / 1000.0f;
  TEST_ASSERT_FLOAT_WITHIN(0.01f, expected, v);
}

void test_cell_voltage_with_offset(void)
{
  /* Test with non-zero offset: OFFSET = +30 mV */
  bms.OFFSET = 30;

  /* raw = 9474 -> mV = (380 * 9474) / 1000 + 30 = 3630.12 mV */
  mock_register_read(0x25); /* HI */
  mock_register_read(0x02); /* LO */

  float v = getCellVoltage(&bms, 1);
  float expected = ((380.0f * 9474.0f) / 1000.0f + 30.0f) / 1000.0f;
  TEST_ASSERT_FLOAT_WITHIN(0.002f, expected, v);
}

void test_cell_voltage_with_negative_offset(void)
{
  /* Test with negative offset: OFFSET = -15 mV */
  bms.OFFSET = -15;

  mock_register_read(0x25); /* HI */
  mock_register_read(0x02); /* LO */

  float v = getCellVoltage(&bms, 1);
  float expected = ((380.0f * 9474.0f) / 1000.0f + (-15.0f)) / 1000.0f;
  TEST_ASSERT_FLOAT_WITHIN(0.002f, expected, v);
}

void test_cell_voltage_minimum_gain(void)
{
  /* GAIN = 365 (minimum per datasheet) */
  bms.GAIN = 365;

  mock_register_read(0x25);
  mock_register_read(0x02);

  float v = getCellVoltage(&bms, 1);
  float expected = (365.0f * 9474.0f) / 1000.0f / 1000.0f;
  TEST_ASSERT_FLOAT_WITHIN(0.002f, expected, v);
}

void test_cell_voltage_maximum_gain(void)
{
  /* GAIN = 396 (maximum: 365 + 31) */
  bms.GAIN = 396;

  mock_register_read(0x25);
  mock_register_read(0x02);

  float v = getCellVoltage(&bms, 1);
  float expected = (396.0f * 9474.0f) / 1000.0f / 1000.0f;
  TEST_ASSERT_FLOAT_WITHIN(0.002f, expected, v);
}

void test_cell_voltage_invalid_cell_number(void)
{
  /* Cell 0 and cell 6 should return 0 for a 5-cell pack */
  float v0 = getCellVoltage(&bms, 0);
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, v0);

  float v6 = getCellVoltage(&bms, 6);
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, v6);
}

void test_cell_voltage_stores_in_struct(void)
{
  /* Verify getCellVoltage stores the result in bms.Vcell[cell-1] */
  mock_register_read(0x25);
  mock_register_read(0x02);

  getCellVoltage(&bms, 3); /* Cell 3 */
  TEST_ASSERT_TRUE(bms.Vcell[2] > 0.0f);
}

/* ---- I2C error handling tests ------------------------------------------- */

void test_cell_voltage_i2c_error_returns_zero(void)
{
  /* Simulate I2C NACK on the transmit phase */
  MockI2C_ExpectTransmitStatus(HAL_ERROR);

  float v = getCellVoltage(&bms, 1);
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, v);
}

/* ---- OV/UV threshold tests ---------------------------------------------- */

void test_check_uv_triggers_below_threshold(void)
{
  bms.Vcell[0] = 3.5f;
  bms.Vcell[1] = 3.4f;
  bms.Vcell[2] = 2.7f; /* Below 2.8V threshold */
  bms.Vcell[3] = 3.3f;
  bms.Vcell[4] = 3.6f;

  TEST_ASSERT_EQUAL(1U, checkUV(&bms));
}

void test_check_uv_clear_when_all_above(void)
{
  bms.Vcell[0] = 3.5f;
  bms.Vcell[1] = 3.4f;
  bms.Vcell[2] = 3.0f;
  bms.Vcell[3] = 3.3f;
  bms.Vcell[4] = 3.6f;

  TEST_ASSERT_EQUAL(0U, checkUV(&bms));
}

void test_check_ov_triggers_above_threshold(void)
{
  bms.Vcell[0] = 3.5f;
  bms.Vcell[1] = 4.30f; /* Above 4.25V threshold */
  bms.Vcell[2] = 3.6f;
  bms.Vcell[3] = 3.3f;
  bms.Vcell[4] = 3.6f;

  TEST_ASSERT_EQUAL(1U, checkOV(&bms));
}

void test_check_ov_clear_when_all_below(void)
{
  bms.Vcell[0] = 3.5f;
  bms.Vcell[1] = 4.0f;
  bms.Vcell[2] = 3.6f;
  bms.Vcell[3] = 3.3f;
  bms.Vcell[4] = 3.6f;

  TEST_ASSERT_EQUAL(0U, checkOV(&bms));
}

/* ---- Test runner -------------------------------------------------------- */

int main(void)
{
  UNITY_BEGIN();

  RUN_TEST(test_cell_voltage_zero_raw);
  RUN_TEST(test_cell_voltage_midrange);
  RUN_TEST(test_cell_voltage_max_14bit);
  RUN_TEST(test_cell_voltage_with_offset);
  RUN_TEST(test_cell_voltage_with_negative_offset);
  RUN_TEST(test_cell_voltage_minimum_gain);
  RUN_TEST(test_cell_voltage_maximum_gain);
  RUN_TEST(test_cell_voltage_invalid_cell_number);
  RUN_TEST(test_cell_voltage_stores_in_struct);
  RUN_TEST(test_cell_voltage_i2c_error_returns_zero);
  RUN_TEST(test_check_uv_triggers_below_threshold);
  RUN_TEST(test_check_uv_clear_when_all_above);
  RUN_TEST(test_check_ov_triggers_above_threshold);
  RUN_TEST(test_check_ov_clear_when_all_below);

  return UNITY_END();
}
