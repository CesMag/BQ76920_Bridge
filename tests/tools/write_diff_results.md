# EV2300 Protocol Comparison Results — 2026-04-01

Both devices connected to their own BQ76920 boards with real I2C traffic.

- REAL = TI EV2300A (`6&2cb02d24`), connected to BQ board
- STM32 = BQ76920_Bridge (`6&191bcf7d`), connected to BQ board

## Critical Differences Found

### 1. totalLen off by 1

Every STM32 response has `totalLen` 1 byte too large.

| Packet | REAL totalLen | STM32 totalLen |
|--------|--------------|----------------|
| Write ack (plen=2) | 0x0A (10) | 0x0B (11) |
| Submit (plen=3) | 0x0B (11) | 0x0C (12) |
| CMD 0x0D (plen=3) | 0x0B (11) | 0x0C (12) |
| READ_WORD (plen=4) | 0x0C (12) | 0x0C (12)* |

*STM32 READ_WORD totalLen happens to match because it uses plen=3 (wrong format).

Real formula: `totalLen = 1(AA) + 1(cmd) + 3(rsv) + 1(plen) + N(payload) + 1(CRC) + 1(55) = N + 8`
STM32 formula (buggy): `totalLen = N + 9` (off by 1)

### 2. READ_WORD payload format completely wrong

Real EV2300 READ_WORD (0x01 -> 0x41) returns **4-byte payload**: `{reg, data_lo, data_hi, i2c_7bit_addr}`
STM32 returns **3-byte payload**: `{i2c_8bit_addr, data_lo, data_hi}`

Example — READ_WORD CC_CFG (reg=0x0B) at addr 0x08:

```
REAL:  0c aa 41 00 00 01 04 0b 00 00 08 19 55
       ^len     ^cmd        ^plen=4
                             payload: 0b(reg) 00(lo) 00(hi) 08(addr_7bit)
                             CRC=0x19  END=0x55

STM32: 0c aa 41 00 00 01 03 10 19 00 df 55
       ^len     ^cmd        ^plen=3
                             payload: 10(addr_8bit) 19(lo) 00(hi)
                             CRC=0xDF  END=0x55
```

Note: Real BQ board had CC_CFG=0x0000, STM32's BQ board had CC_CFG=0x0019.
Format difference is: {reg, lo, hi, addr7} vs {addr8, lo, hi}.

### 3. WRITE_BYTE (0x07) must NOT respond

Real EV2300 returns **TIMEOUT (no response)** for WRITE_BYTE.
STM32 incorrectly sends 0x46 error ack.

```
REAL:  write_ack: TIMEOUT (no response)
REAL:  submit:    0b aa c0 00 00 01 03 33 31 6d 8f 55

STM32: write_ack: 0b aa 46 00 00 01 02 0b 93 2e 55   <-- WRONG, should be silent
STM32: submit:    0c aa c0 00 00 01 03 33 31 6d 8f 55
```

### 4. SUBMIT always returns 0xC0 success on real EV2300

Even for invalid I2C address (0x7F, no device), real EV2300 SUBMIT returns success.
STM32 returns 0x46 error when HAL_I2C reports NACK.

```
Invalid addr 0xFE write + submit:
REAL:  submit: 0b aa c0 00 00 01 03 33 31 6d 8f 55  (SUCCESS!)
STM32: submit: 0b aa 46 00 00 01 02 00 93 b9 55     (ERROR)
```

### 5. CRC excludes last payload byte (I2C address)

The real EV2300 computes CRC-8 (poly=0x07, init=0x00) over bytes[2..2+5+plen-1],
i.e., it EXCLUDES the last payload byte when that byte is the I2C address.

Verified across ALL read responses:
- SYS_STAT:  CRC(excl addr)=0xF5 == expected 0xF5
- SYS_CTRL1: CRC(excl addr)=0x5E == expected 0x5E
- PROTECT1:  CRC(excl addr)=0x88 == expected 0x88
- CC_CFG:    CRC(excl addr)=0x19 == expected 0x19
- CMD 0x0D:  CRC(excl addr)=0xE2 == expected 0xE2

Current STM32 CRC includes ALL payload bytes -> CRC mismatch on every read response.

## Packets That Already Match

| Packet | Match? |
|--------|--------|
| Write ack cmd byte (0x46) | YES |
| Write ack payload format ({reg, 0x93}) | YES |
| Submit cmd byte (0xC0) | YES |
| Submit payload ({0x33, 0x31, 0x6D}) | YES |
| SEND_BYTE ack (0x46) | YES |
| WRITE_BLOCK ack (0x46) | YES |
| CMD 0x0D response code (0x4E) | YES |
| CMD 0x0D payload ({0x02, 0x00, 0x08}) | YES |
| rsv[2] = 0x01 | YES |

## Raw Captures

### Test 1: WRITE_WORD (0x04) CC_CFG=0x19
```
REAL    write_ack: 0a aa 46 00 00 01 02 0b 93 2e 55
REAL    submit:    0b aa c0 00 00 01 03 33 31 6d 8f 55
REAL    readback:  0c aa 41 00 00 01 04 0b 00 00 08 19 55
STM32   write_ack: 0b aa 46 00 00 01 02 0b 93 2e 55
STM32   submit:    0c aa c0 00 00 01 03 33 31 6d 8f 55
STM32   readback:  0c aa 41 00 00 01 03 10 19 00 df 55
```

### Test 2: WRITE_BYTE (0x07) CC_CFG=0x19
```
REAL    write_ack: TIMEOUT (no response)
REAL    submit:    0b aa c0 00 00 01 03 33 31 6d 8f 55
REAL    readback:  0c aa 41 00 00 01 04 0b 00 00 08 19 55
STM32   write_ack: 0b aa 46 00 00 01 02 0b 93 2e 55
STM32   submit:    0c aa c0 00 00 01 03 33 31 6d 8f 55
STM32   readback:  0c aa 41 00 00 01 03 10 19 00 df 55
```

### Test 3: WRITE_WORD (0x04) SYS_CTRL1=0x18
```
REAL    current:   0c aa 41 00 00 01 04 04 00 00 08 5e 55
REAL    write_ack: 0a aa 46 00 00 01 02 04 93 ed 55
REAL    submit:    0a aa 46 00 00 01 02 04 93 ed 55  (desync? got write ack again)
REAL    readback:  0b aa c0 00 00 01 03 33 31 6d 8f 55  (got submit resp late)
STM32   current:   0c aa 41 00 00 01 03 10 10 00 62 55
STM32   write_ack: 0b aa 46 00 00 01 02 04 93 ed 55
STM32   submit:    0c aa c0 00 00 01 03 33 31 6d 8f 55
STM32   readback:  0c aa 41 00 00 01 03 10 18 00 ca 55
```

### Test 4: SEND_BYTE (0x06)
```
REAL    write_ack: 0a aa 46 00 00 01 02 00 93 b9 55
REAL    submit:    0b aa c0 00 00 01 03 33 31 6d 8f 55
STM32   write_ack: 0b aa 46 00 00 01 02 00 93 b9 55
STM32   submit:    0c aa c0 00 00 01 03 33 31 6d 8f 55
```

### Test 5: WRITE_BLOCK (0x05) CC_CFG=0x19
```
REAL    write_ack: 0a aa 46 00 00 01 02 0b 93 2e 55
REAL    submit:    0b aa c0 00 00 01 03 33 31 6d 8f 55
REAL    readback:  0c aa 41 00 00 01 04 0b 00 00 08 19 55
STM32   write_ack: 0b aa 46 00 00 01 02 0b 93 2e 55
STM32   submit:    0c aa c0 00 00 01 03 33 31 6d 8f 55
STM32   readback:  0c aa 41 00 00 01 03 10 19 00 df 55
```

### Test 6: WRITE_WORD to invalid addr 0x7F
```
REAL    write_ack: 0a aa 46 00 00 01 02 00 93 b9 55
REAL    submit:    0b aa c0 00 00 01 03 33 31 6d 8f 55  (SUCCESS despite NACK)
STM32   write_ack: 0b aa 46 00 00 01 02 00 93 b9 55
STM32   submit:    0b aa 46 00 00 01 02 00 93 b9 55     (ERROR)
```

### Test 7: READ_WORD comparison
```
REAL    SYS_STAT:  0c aa 41 00 00 01 04 00 00 00 08 f5 55
STM32   SYS_STAT:  0c aa 41 00 00 01 03 10 04 00 61 55
REAL    SYS_CTRL1: 0c aa 41 00 00 01 04 04 00 00 08 5e 55
STM32   SYS_CTRL1: 0c aa 41 00 00 01 03 10 18 00 ca 55
REAL    PROTECT1:  0c aa 41 00 00 01 04 06 00 00 08 88 55
STM32   PROTECT1:  0c aa 41 00 00 01 03 10 00 00 35 55
REAL    CC_CFG:    0c aa 41 00 00 01 04 0b 00 00 08 19 55
STM32   CC_CFG:    0c aa 41 00 00 01 03 10 19 00 df 55
```

### Test 8: CMD 0x0D
```
REAL:  0b aa 4e 00 00 01 03 02 00 08 e2 55
STM32: 0c aa 4e 00 00 01 03 02 00 08 98 55
```

---

## READ Format Comparison (read_format_diff.py)

### 6. READ_BYTE returns ERROR on real EV2300

Real EV2300 returns 0x46 error for ALL READ_BYTE (0x03) commands on BQ76920.
STM32 returns 0x42 success with actual data.
BQ76920 does not support single-byte SMBus reads — all registers are word-width.

```
READ_BYTE SYS_STAT (0x00):
  REAL:  0a aa 46 00 00 01 02 00 93 b9 55   (ERROR {reg=0x00, 0x93})
  STM32: 0b aa 42 00 00 01 02 10 04 77 55   (SUCCESS {addr=0x10, val=0x04})

READ_BYTE SYS_CTRL1 (0x04):
  REAL:  0a aa 46 00 00 01 02 04 93 ed 55   (ERROR {reg=0x04, 0x93})
  STM32: 0b aa 42 00 00 01 02 10 18 23 55   (SUCCESS)

READ_BYTE CC_CFG (0x0B):
  REAL:  0a aa 46 00 00 01 02 0b 93 2e 55   (ERROR {reg=0x0B, 0x93})
  STM32: 0b aa 42 00 00 01 02 10 19 24 55   (SUCCESS)
```

### 7. READ_WORD at invalid addr returns SUCCESS on real EV2300

Real EV2300 does NOT return error on I2C NACK for reads. Returns stale data.
STM32 correctly returns 0x46 error.

```
READ_WORD at addr 0xFE (no device):
  REAL:  0c aa 41 00 00 01 04 00 00 00 08 f5 55   (SUCCESS! stale data)
  STM32: 0b aa 46 00 00 01 02 00 93 b9 55         (ERROR)
```

### 8. READ_BLOCK format differences

Real EV2300 READ_BLOCK returns very short response (plen=3).
STM32 returns full 32-byte block (plen=34).

```
READ_BLOCK reg=0x00 len=4:
  REAL:  0b aa 42 00 00 01 03 02 00 08 7d 55   (plen=3: {0x02, 0x00, addr=0x08})
  STM32: 2b aa 42 00 00 01 22 10 20 ...         (plen=34: {addr, 32_bytes_data...})

READ_BLOCK reg=0x00 len=16:
  REAL:  0b aa 42 00 00 01 03 02 00 08 7d 55   (same short response)
  STM32: 2b aa 42 00 00 01 22 10 20 ...         (full block)
```

### 9. CRC Pattern Confirmed

CRC-8 poly=0x07 init=0x00 EXCLUDES the I2C address byte at end of payload.

For success responses with I2C addr as last payload byte:
- CRC covers: cmd + rsv(3) + plen + payload[0:plen-1] (excludes last byte)
- Address byte is placed in payload but computed separately

For error responses (0x46) — no I2C addr in payload:
- CRC covers: cmd + rsv(3) + plen + all payload bytes

Verified formula:
- Success: CRC = crc8(rspBuffer[2 : 2 + 5 + plen - 1])  → (4 + plen) bytes
- Error:   CRC = crc8(rspBuffer[2 : 2 + 5 + plen])       → (5 + plen) bytes

## Summary of ALL Bugs to Fix

| # | Bug | Impact |
|---|-----|--------|
| 1 | totalLen = N+9 (should be N+8) | Every response has wrong length byte |
| 2 | READ_WORD payload: {addr8, lo, hi} should be {reg, lo, hi, addr7} | DLL parses wrong data bytes → "no ack" |
| 3 | WRITE_BYTE sends 0x46 ack (should be TIMEOUT/no response) | DLL gets unexpected packet |
| 4 | SUBMIT returns 0x46 on I2C NACK (should always return 0xC0) | DLL interprets as write failure |
| 5 | CRC includes addr byte (should exclude for success responses) | CRC mismatch on every success response |
| 6 | READ_WORD returns 0x46 on I2C NACK (real returns 0x41 + stale) | May not matter for normal operation |
| 7 | READ_BLOCK format: full dump vs short response | Different from real EV2300 |
