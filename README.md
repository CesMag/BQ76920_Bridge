# BQ76920_Bridge

**Texas A&M University - ESET 453/653: Semiconductor Validation and Verification**

**Instructor:** Tom Munns | **Spring 2026**

**Author**: Cesar Magana & Brighton Sikarskie

---

## Project Overview

This project implements a **low-cost, open-source replacement for the Texas Instruments EV2300/EV2400 USB interface adapter** using the **Adafruit Feather STM32F405 Express**. The resulting firmware allows a host PC running **bqStudio** to communicate with the **TI BQ76920 Analog Front-End (AFE)** battery monitor IC over USB.

The TI EV2400 retails for ~$60 and relies on a proprietary MSP430F5529-based design running at 4 MHz with USB HID class communication. This project replicates that USB-to-SMBus bridge functionality on a 168 MHz Cortex-M4F at a fraction of the cost, with fully open, auditable firmware.

**The EV2300/EV2400 has no scripting interface** — it cannot be controlled programmatically, which prevents automation of the ESET 453 lab exercises. This project eliminates that limitation.

---

## Hardware

### Host Interface Board — Adafruit Feather STM32F405 Express

[Product Page](https://www.adafruit.com/product/4382) | [Schematic (remote)](https://cdn-shop.adafruit.com/product-files/4382/4382-schematic.pdf) | [Schematic (local)](datasheets/Feather%20STM32F405%20rev%20A.pdf)

| Spec | Value |
|---|---|
| MCU | STM32F405RGT6 (ARM Cortex-M4F @ 168 MHz) |
| Flash | 1024 KB |
| RAM | 192 KB |
| USB | USB-C Full Speed OTG (PA11 DM / PA12 DP) |
| I2C | I2C1 on PB6 (SCL) / PB7 (SDA) — onboard 10K pullups |
| STEMMA QT / Qwiic | JST SH 1mm, wired to I2C1 (PB6/PB7) — same bus as BQ76920 |
| Debug UART | USART3 on PB10 (TX) / PB11 (RX) |
| Debug Interface | SWD on PA13 (SWDIO) / PA14 (SWCLK) — bottom 2×5 pad |
| Status LED (red) | PC1 — next to USB jack |
| NeoPixel RGB LED | PC0 (WS2812B, Arduino D8) — available for color-coded status |
| 2 MB SPI Flash | Internal SPI bus (U1, not on GPIO headers) — available for calibration/log storage |
| LiPo Charger | MCP73831T (U3), charges via USB-C VBUS; orange CHG LED |
| Battery Voltage | V_DIV net → A6 ADC — resistor-divided LiPo voltage readback |
| SD Card | SDIO (PC8–PC12 + PD2); detect on PB12 — **Rev A bug: SD detect non-functional** |
| Form Factor | Adafruit Feather (51mm × 23mm) |

### Device Under Test — TI BQ76920 AFE

| Spec | Value |
|---|---|
| Function | 3-Series to 5-Series Li-Ion/LiFePO4 Battery Monitor |
| Interface | I2C / SMBus (CRC-8, polynomial 0x07) |
| I2C Address | 0x08 (no CRC) / 0x18 (CRC enabled) |
| Supply Voltage | 3.0V – 4.25V per cell (9V – 21.25V pack) |
| ADC Resolution | 14-bit cell voltage, 16-bit coulomb counter |
| Key Features | OV/UV protection, OCD, SCD, die temperature, 3× thermistor |
| Package | TSSOP-24 |

### I2C Wiring -- Feather to BQ76920 EVM

The EVM J8 I2C header and the Feather STEMMA QT connector have **different pin orders** -- a straight-through cable will not work. Use individual jumper wires.

| EVM J8 (top to bottom) | Wire Color | Feather Connection |
|---|---|---|
| 1 - GND | Black | GND |
| 2 - SCL | Yellow | SCL (PB6) |
| 3 - SDA | Blue | SDA (PB7) |
| 4 - NC | -- | Not connected |

The Feather STEMMA QT pinout is GND / V+ / SDA / SCL -- note that SCL and SDA are swapped relative to the EVM, and the EVM has no power pin where the Feather has V+.

### Interface Being Replaced — TI EV2300 / EV2400

The **EV2300** is a legacy multi-chip USB interface board that uses a **proprietary USB protocol** with a custom Windows driver to bridge a PC to TI battery management ICs over SMBus/I2C/HDQ. The **EV2400** replaced it using a single MSP430F5529 microcontroller at 4 MHz running **USB HID class**, making it driver-free on modern operating systems.

Both are required accessories for operating **bqStudio** — TI's official GUI for register read/write, calibration, and parametric evaluation of the BQ76920. This project replaces both with the STM32F405 Feather.

---

## Current Status

**The STM32 Feather fully replaces the TI EV2300.** All three goals below are achieved.

| Feature | Status |
|---|---|
| TI bq76940 GUI — register read/write | Working |
| TI DLL (bq80xrw.dll) — ReadSMBusWord, WriteSMBusWord, I2CPower | Working |
| Direct HID — read word, read byte, read block, write byte, ext read/write | Working |
| Python automation via [scpi-instrument-toolkit](https://github.com/T-O-M-Tool-Oauto-Mationator/scpi-instrument-toolkit) | Working |
| Compliance tests | 21/21 passing |
| Bench tests (18V + EVM) | 19/20 passing (block read is the remaining item) |

### Key Protocol Details (discovered via Ghidra reverse-engineering of TI DLLs)

- **Silent commands**: I2CPower (0x18), WriteByte (0x07), and ExtWrite (0x1E) produce NO HID response — matching real EV2300 hardware behavior
- **CRC-8**: The DLL computes CRC over `plen+5` bytes, which **includes** the trailing I2C address byte
- **ExtRead (0x1D)**: Response payload format is `{reg, count, data[count], addr7}` — the DLL reads data from byte offset 8
- **USB descriptors**: bcdUSB=0x0110 (USB 1.1), bInterval=1ms — matching the real EV2300's TUSB3210

---

## Goal

### Primary Goal — bqStudio Compatibility (Achieved)
The firmware enumerates as a USB HID device with VID=0x0451 PID=0x0036 (identical to the real EV2300). TI's bq76940 GUI and DLL stack communicate with it seamlessly.

### Fallback Goal — Lightweight bqStudio Replacement (Achieved)
The [scpi-instrument-toolkit](https://github.com/T-O-M-Tool-Oauto-Mationator/scpi-instrument-toolkit) provides a cross-platform Python driver (`ev2300.py`) that communicates with the bridge directly over HID — no TI software or DLLs required.

### Ultimate Objective — Full Lab Automation (Achieved)
The Python driver enables complete programmatic control of BQ76920 register access. Students can automate ESET 453 measurement sequences via Python scripts or LabVIEW Python Nodes.

---

## Architecture

### Firmware Bridge

```
[bqStudio on PC]
      |
   USB HID
      |
[STM32F405 Feather]
  - USB OTG FS  (PA11/PA12)   ←→ PC
  - I2C1 100kHz (PB6/PB7)     ←→ BQ76920
  - USART3 115200 (PB10/PB11) ←→ Debug terminal
      |
   SMBus / I2C (CRC-8)
      |
[BQ76920 AFE]
  - Cell voltage ADC (VC1–VC5, reg 0x04–0x0D)
  - Pack current / coulomb counter (reg 0x32–0x33)
  - System status / alerts (reg 0x00 SYS_STAT)
  - OV/UV/OCD/SCD protection registers (0x28–0x2C)
```

### Lab Automation Stack

```
[LabVIEW VI]
      |
  Python Node (LabVIEW 2018+ built-in)
      |
[Python Library — sister repo]
      |
   USB HID
      |
[STM32F405 Feather]
      |
   I2C / SMBus (CRC-8)
      |
[BQ76920 AFE]
```

> **LabVIEW Python Node:** LabVIEW 2018 and later includes a native `Python Node` palette item that imports a Python module and calls its functions with LabVIEW data types — no additional middleware required. The Python USB HID driver in the sister repo serves as the module invoked by the LabVIEW VI.

---

## Repository Structure

```
BQ76920_Bridge/
├── Core/
│   ├── Inc/
│   │   ├── bq76920.h              # BQ76920 register map + driver API
│   │   └── usb_hid_bridge.h       # EV2300 HID protocol constants
│   └── Src/
│       ├── bq76920.c              # BQ76920 I2C driver (CRC/non-CRC auto-detect)
│       └── usb_hid_bridge.c       # EV2300 protocol emulation (main bridge logic)
├── USB_DEVICE/
│   └── App/usbd_desc.c            # USB descriptors (VID/PID/serial matching EV2300)
├── Middlewares/.../HID/
│   ├── Src/usbd_hid.c             # USB HID class (modified: 1ms bInterval)
│   └── Inc/usbd_hid.h             # HID handle + constants
├── tests/
│   ├── unit/                      # Host-side unit tests (CRC, voltage, protocol)
│   ├── integration/
│   │   └── test_bench_no_cells.py # Full register I/O bench test (19/20 passing)
│   └── tools/
│       ├── test_ev2300_compliance.py  # 21-test protocol compliance suite
│       ├── trace_dll.py           # TI DLL call tracer
│       ├── sniff_ev2300_init.py   # Real EV2300 HID protocol sniffer
│       └── real_ev2300_*.json     # Ground-truth captures from real hardware
├── docs/
│   └── STM32_EV2300_WORKFLOW.md   # Build/flash/debug workflow
├── CMakeLists.txt
└── README.md
```

---

## Build Environment

| Tool | Version | Purpose |
|---|---|---|
| ARM GNU Toolchain | 14.2 rel1 | `arm-none-eabi-gcc` cross-compiler |
| CMake | 3.28+ | Build system |
| Ninja | Latest | Build backend |
| dfu-util | 0.9+ | USB DFU flashing (no ST-Link needed) |
| Python 3.10+ | 3.12 recommended | Test scripts, `hidapi` package |
| Python 3.10-32 | 32-bit only | Required for loading TI's 32-bit DLLs |

### Build

```bash
# Configure (first time only)
cmake --preset debug

# Build firmware
cmake --build build/debug

# IMPORTANT: cmake doesn't always refresh the .bin -- always regenerate manually
arm-none-eabi-objcopy -O binary build/debug/BQ76920_Bridge.elf build/debug/BQ76920_Bridge.bin
```

### Flash (DFU over USB -- no extra hardware needed)

1. **Connect the B0 pin to 3.3V** on the Feather header with a jumper wire
2. **Press the RESET button** while USB is connected to the PC
3. The board enumerates as "STM32 BOOTLOADER" (VID 0x0483, PID 0xDF11)
4. **Flash:**
   ```bash
   dfu-util -a 0 --dfuse-address 0x08000000:leave -D build/debug/BQ76920_Bridge.bin
   ```
5. **Remove the B0 jumper** and press RESET
6. **Press BOOT on the BQ76920 EVM** to wake the AFE

> **Note:** On Windows, the DFU device may need a WinUSB driver installed via [Zadig](https://zadig.akeo.ie/) on first use.

### Run Tests

```bash
# Host unit tests (no hardware needed)
cmake --build build/tests --config Debug --clean-first
ctest --test-dir build/tests -C Debug --output-on-failure

# EV2300 protocol compliance (device must be flashed + connected to EVM)
pip install hidapi
python tests/tools/test_ev2300_compliance.py    # 21 tests

# Full bench test (device + BQ76920 EVM with 18V supply)
python tests/integration/test_bench_no_cells.py  # 19/20 tests

# TI DLL trace (32-bit Python required, Windows only)
python310-32 tests/tools/trace_dll.py --dll-dir "C:\Program Files (x86)\Texas Instruments\bq76940"
```

---

## STM32CubeMX Configuration Summary

| Peripheral | Mode | Pins | Notes |
|---|---|---|---|
| RCC | HSE Crystal | PH0/PH1 | 12 MHz external |
| SYS | SWD + TIM1 timebase | PA13/PA14 | |
| I2C1 | Standard 100kHz | PB6/PB7 | 10K pullups onboard |
| USB_OTG_FS | Device Only | PA11/PA12 | USB-C connector |
| USB_DEVICE | HID Class | — | EV2400 emulation |
| USART3 | Async 115200 | PB10/PB11 | Debug TX/RX header pins |
| GPIO PC1 | Output | PC1 | Status LED |
| HCLK | 168 MHz | — | PLL: M=6, N=168, P=2, Q=7 |

---

## Key BQ76920 Registers

| Register | Address | Description |
|---|---|---|
| SYS_STAT | 0x00 | Alert flags: OV, UV, SCD, OCD, OVRD_ALERT |
| SYS_CTRL1 | 0x04 | ADC enable, temperature source select |
| SYS_CTRL2 | 0x05 | CHG_ON, DSG_ON, CC_EN, DELAY_DIS |
| VC1_HI/LO | 0x0C–0x0D | Cell 1 voltage (14-bit ADC) |
| VC5_HI/LO | 0x14–0x15 | Cell 5 voltage |
| BAT_HI/LO | 0x2A–0x2B | Total pack voltage |
| CC_HI/LO | 0x32–0x33 | Coulomb counter (16-bit, signed) |
| PROTECT1 | 0x06 | SCD threshold + delay |
| PROTECT2 | 0x07 | OCD threshold + delay |
| OV_TRIP | 0x09 | Overvoltage threshold (8-bit scaled) |
| UV_TRIP | 0x0A | Undervoltage threshold (8-bit scaled) |

---

## ESET 453 Lab Applicability

| Week | Lab | BQ76920 Function Tested |
|---|---|---|
| 8–9 | Lab 5: IDDQ | Supply current (IDD quiescent) |
| 10 | Lab 6: VREG | Internal voltage regulator parametric |
| 11 | Lab 7: OVUV | OV_TRIP / UV_TRIP register validation |
| 12–13 | Lab 8: ADC Parametric | Cell voltage ADC linearity, INL/DNL |

---

## Related Projects

- **[scpi-instrument-toolkit](https://github.com/T-O-M-Tool-Oauto-Mationator/scpi-instrument-toolkit)** — Sister repo containing the host-side Python drivers that communicate with this bridge over USB HID, and the LabVIEW Python Node integration for full lab automation.

---

## References

- [BQ76920 Datasheet (SLUSB30)](https://www.ti.com/product/BQ76920)
- [BQ76920EVM User's Guide (SLVU924)](https://www.ti.com/lit/ug/slvu924d/slvu924d.pdf)
- [EV2400 User's Guide (SLUU446)](https://www.ti.com/lit/pdf/sluu446)
- [Adafruit Feather STM32F405 Product Page](https://www.adafruit.com/product/4382)
- [Adafruit Feather STM32F405 Schematic](https://cdn-shop.adafruit.com/product-files/4382/4382-schematic.pdf)
- [Adafruit Feather STM32F405 Pinouts](https://learn.adafruit.com/adafruit-stm32f405-feather-express/pinouts)
- [SubugFcz/BMS_BQ76920 — STM32 HAL BQ76920 Driver](https://github.com/SubugFcz/BMS_BQ76920)
- [MaJerle/stm32-cube-cmake-vscode — CMake Template](https://github.com/MaJerle/stm32-cube-cmake-vscode)

---

*Texas A&M University — ETID Department — ESET 453/653 Spring 2026*
