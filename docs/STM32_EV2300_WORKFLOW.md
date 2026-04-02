# STM32 EV2300 Workflow

Build, flash, and test workflow for the STM32 EV2300 bridge on Windows.

## Build

```powershell
cd C:\Users\sikar\BQ76920_Bridge
cmake --build build/debug
# ALWAYS regenerate BIN manually (cmake doesn't reliably refresh it):
& 'C:\Program Files (x86)\Arm GNU Toolchain arm-none-eabi\14.2 rel1\bin\arm-none-eabi-objcopy.exe' `
    -O binary build\debug\BQ76920_Bridge.elf build\debug\BQ76920_Bridge.bin
```

## Flash

1. Connect B0 to 3.3V, press RESET (board enumerates as `VID_0483&PID_DF11`)
2. Flash:
   ```powershell
   & 'C:\Users\sikar\Downloads\dfu-util-0.9-win64\dfu-util-0.9-win64\dfu-util-static.exe' `
       -a 0 --dfuse-address 0x08000000:leave -D build\debug\BQ76920_Bridge.bin
   ```
3. Remove B0 jumper, press RESET
4. Press BOOT on the BQ76920 EVM to wake the AFE

## Test

```powershell
# Host unit tests
cmake --build build/tests --config Debug --clean-first
ctest --test-dir build/tests -C Debug --output-on-failure

# Protocol compliance (21 tests)
python tests\tools\test_ev2300_compliance.py

# Bench test with 18V EVM (19/20 tests)
python tests\integration\test_bench_no_cells.py

# TI DLL trace (needs 32-bit Python)
& 'C:\Users\sikar\AppData\Local\Programs\Python\Python310-32\python.exe' `
    tests\tools\trace_dll.py --dll-dir 'C:\Program Files (x86)\Texas Instruments\bq76940'
```

## Important Notes

- **Do not keep the real EV2300 plugged in** while debugging the Feather (both use VID=0x0451 PID=0x0036)
- **The BQ76920 EVM goes to sleep** if idle too long. Press BOOT to wake it
- **The TI DLL requires `SetTimeout`** via `bq80xusb.dll` before ReadSMBusWord calls will work
- **The real EV2300 needs its firmware loader driver** (`ApLoader.sys` + `EV2300A.BIN`) and HVCI disabled to work on Windows 11

## Protocol Summary

| Command | Code | Response | Notes |
|---|---|---|---|
| ReadWord | 0x01 | 0x41 `{reg, lo, hi, addr7}` | |
| ReadBlock | 0x02 | 0x42 `{count, data[0], addr7}` | |
| ReadByte | 0x03 | 0x42 `{reg, val, addr7}` | GUI uses ExtRead instead |
| WriteByte | 0x07 | **Silent** (no response) | Buffered for SUBMIT |
| I2CPower | 0x18 | **Silent** (no response) | DLL interprets silence as success |
| ExtRead | 0x1D | 0x52 `{reg, count, data[count], addr7}` | Used by TI GUI |
| ExtWrite | 0x1E | **Silent** (no response) | Buffered for SUBMIT |
| Submit | 0x80 | 0xC0 `{0x33, 0x31, 0x6D}` | Always returns success |

CRC-8: polynomial 0x07, init 0x00. Covers `plen+5` bytes from response code through all payload bytes (including addr7).
