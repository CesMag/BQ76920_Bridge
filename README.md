# BQ76920_Bridge

**Texas A&M University — ESET 453/653: Semiconductor Validation and Verification**
**Instructor:** Tom Munns | **Spring 2026**

---

## Project Overview

This project implements a **low-cost, open-source replacement for the Texas Instruments EV2300/EV2400 USB interface adapter** using the **Adafruit Feather STM32F405 Express**. The resulting firmware allows a host PC running **bqStudio** to communicate with the **TI BQ76920 Analog Front-End (AFE)** battery monitor IC over USB — the same workflow used in the ESET 453 laboratory curriculum starting at Week 8.

The TI EV2400 retails for ~$60 and relies on a proprietary MSP430F5529-based design running at 4 MHz with USB HID class communication. This project replicates that USB-to-SMBus bridge functionality on a 168 MHz Cortex-M4F at a fraction of the cost, with fully open, auditable firmware.

**Critically, the EV2300/EV2400 has no scripting interface** — it cannot be controlled programmatically, which prevents automation of the ESET 453 lab exercises. This project eliminates that limitation.

---

## Hardware

### Host Interface Board — Adafruit Feather STM32F405 Express

[Product Page](https://www.adafruit.com/product/4382) | [Schematic](https://cdn-shop.adafruit.com/product-files/4382/4382-schematic.pdf)

| Spec | Value |
|---|---|
| MCU | STM32F405RGT6 (ARM Cortex-M4F @ 168 MHz) |
| Flash | 1024 KB |
| RAM | 192 KB |
| USB | USB-C Full Speed OTG (PA11/PA12) |
| I2C | I2C1 on PB6 (SCL) / PB7 (SDA) — onboard 10K pullups |
| Debug UART | USART3 on PB10 (TX) / PB11 (RX) |
| Debug Interface | SWD on PA13/PA14 (bottom 2×5 pad) |
| Status LED | PC1 |
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

### Interface Being Replaced — TI EV2300 / EV2400

The **EV2300** is a legacy multi-chip USB interface board that uses a **proprietary USB protocol** with a custom Windows driver to bridge a PC to TI battery management ICs over SMBus/I2C/HDQ. The **EV2400** replaced it using a single MSP430F5529 microcontroller at 4 MHz running **USB HID class**, making it driver-free on modern operating systems.

Both are required accessories for operating **bqStudio** — TI's official GUI for register read/write, calibration, and parametric evaluation of the BQ76920. This project replaces both with the STM32F405 Feather.

---

## Goal

This project pursues a layered set of objectives:

### Primary Goal — bqStudio Compatibility
Build firmware that enumerates as a USB HID device on the host PC, presenting the same USB VID/PID and HID report descriptor expected by bqStudio's `.dll` interface layer, enabling full register read/write through the official TI GUI.

### Fallback Goal — Lightweight bqStudio Replacement
If the bqStudio USB HID protocol proves too difficult to fully reverse-engineer, implement a minimal open-source GUI replacement that exposes BQ76920 register access directly.

### Ultimate Objective — Full Lab Automation
The core motivation is eliminating the EV2300/EV2400's lack of a scripting interface. This project enables:

1. **Python USB HID driver** (in sister repo) communicates with the STM32 bridge over USB
2. **LabVIEW Python Node** (native LabVIEW 2018+ feature) calls Python functions directly from a LabVIEW VI, bridging into the Python driver
3. **LabVIEW VIs** automate ESET 453 measurement sequences — parametric sweeps, data logging, pass/fail analysis — replacing manual bqStudio interaction entirely

This enables students to achieve complete programmatic control of BQ76920 register access from LabVIEW, the environment already used in ESET labs.

Firmware behavior:

1. **Enumerates as a USB HID device** on the host PC, presenting the same USB VID/PID and HID report descriptor expected by bqStudio's `.dll` interface layer
2. **Translates USB HID packets** from bqStudio into I2C/SMBus register read and write transactions to the BQ76920
3. **Returns BQ76920 register data** back to bqStudio via USB HID response packets
4. **Supports CRC-8 verification** on all I2C transactions (polynomial 0x07) to match BQ76920 CRC mode

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
│   │   ├── main.h
│   │   ├── i2c.h
│   │   ├── usart.h
│   │   ├── bq76920.h          # BQ76920 register map + driver
│   │   └── usb_hid_bridge.h   # EV2400 HID packet protocol
│   └── Src/
│       ├── main.c
│       ├── i2c.c              # HAL I2C1 init (PB6/PB7, 100kHz)
│       ├── usart.c            # HAL USART3 init (PB10/PB11, 115200)
│       ├── bq76920.c          # Register R/W, CRC-8, protection config
│       └── usb_hid_bridge.c   # USB HID ↔ I2C translation layer
├── USB_DEVICE/
│   └── App/usbd_custom_hid_if.c  # HID report handler — main bridge logic
├── Drivers/                   # STM32 HAL (auto-generated)
├── datasheets/                # Reference datasheets (STM32F405, BQ76920EVM, EV2300)
├── CMakeLists.txt             # CMake build system (GCC + Ninja)
├── BQ76920_Bridge.ioc         # STM32CubeMX project file
└── README.md
```

---

## Build Environment

| Tool | Version | Purpose |
|---|---|---|
| STM32CubeMX | Latest (2026) | Peripheral config + code generation |
| STM32CubeCLT | Latest | ARM GCC, CMake, Ninja, ST-Link GDB |
| VSCode | Latest | IDE |
| STM32 VS Code Extension | v2.0+ | CMake integration, Cortex-Debug |
| CMake | Bundled with CubeCLT | Build system |
| arm-none-eabi-gcc | Bundled with CubeCLT | Cross-compiler |

### Build

```bash
# Configure
cmake --preset Debug

# Build
cmake --build build/Debug

# Flash via ST-Link (SWD pads on bottom of Feather)
st-flash write build/Debug/BQ76920_Bridge.elf 0x08000000
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
*Student: Cesar Magana*
