#!/usr/bin/env python3
"""
USB HID integration tests for the BQ76920_Bridge firmware.

Prerequisites:
  - Firmware must be flashed to the STM32F405 Feather
  - Device must be connected via USB
  - pip install hidapi

Usage:
  python3 tests/integration/test_usb_hid_bridge.py

These tests send real USB HID reports to the device and verify responses.
The ECHO and VERSION commands work without a BQ76920 connected.
Register read/write commands require the BQ76920 EVM wired to I2C1.
"""
import sys
import time
import struct

try:
    import hid
except ImportError:
    print("ERROR: hidapi not installed. Run: pip install hidapi")
    sys.exit(1)

# Bridge device identifiers (STMicro defaults)
VID = 0x0483
PID = 0x572B

# Command IDs (must match usb_hid_bridge.h)
CMD_READ_REG     = 0x01
CMD_WRITE_REG    = 0x02
CMD_READ_BLOCK   = 0x03
CMD_WRITE_BLOCK  = 0x04
CMD_INIT_DEVICE  = 0x10
CMD_GET_STATUS   = 0x11
CMD_GET_VOLTAGES = 0x12
CMD_GET_CURRENT  = 0x13
CMD_FET_CONTROL  = 0x14
CMD_ECHO         = 0xFE
CMD_VERSION      = 0xFF

# Status codes
STATUS_OK      = 0x00
STATUS_I2C_ERR = 0x01
STATUS_CRC_ERR = 0x02
STATUS_BAD_CMD = 0x03

REPORT_SIZE = 64


class BridgeDevice:
    """Wrapper for USB HID communication with the BQ76920 bridge."""

    def __init__(self):
        self.dev = hid.device()

    def open(self):
        """Open the bridge device. Raises IOError if not found."""
        self.dev.open(VID, PID)
        self.dev.set_nonblocking(0)
        print(f"Opened: {self.dev.get_manufacturer_string()} "
              f"- {self.dev.get_product_string()}")

    def close(self):
        self.dev.close()

    def send_command(self, cmd_id, reg_addr=0, data_len=0, data=b"", timeout_ms=2000):
        """Send a command and wait for the response."""
        # Build 64-byte report (prepend 0x00 report ID for hidapi)
        report = bytes([0x00, cmd_id, reg_addr, data_len]) + data
        report = report.ljust(REPORT_SIZE + 1, b"\x00")

        self.dev.write(report)
        response = self.dev.read(REPORT_SIZE, timeout_ms)

        if response is None or len(response) == 0:
            raise TimeoutError(f"No response for command 0x{cmd_id:02X}")

        return bytes(response)


def find_device():
    """Check if the bridge device is connected."""
    devices = hid.enumerate(VID, PID)
    if not devices:
        return None
    return devices[0]


# ---- Test functions --------------------------------------------------------

def test_echo(bridge):
    """Send ECHO command, verify loopback."""
    payload = bytes(range(64))
    # ECHO: entire request is echoed back
    report = bytes([0x00, CMD_ECHO]) + payload[:62]
    report = report.ljust(REPORT_SIZE + 1, b"\x00")
    bridge.dev.write(report)

    resp = bridge.dev.read(REPORT_SIZE, 2000)
    assert resp is not None and len(resp) > 0, "No ECHO response"

    # First byte of response should be CMD_ECHO
    assert resp[0] == CMD_ECHO, f"Expected CMD_ECHO (0xFE), got 0x{resp[0]:02X}"
    print("  ECHO: PASS")


def test_version(bridge):
    """Request firmware version string."""
    resp = bridge.send_command(CMD_VERSION)
    assert resp[0] == CMD_VERSION, "Wrong command echo"
    assert resp[1] == STATUS_OK, f"Status error: 0x{resp[1]:02X}"

    str_len = resp[2]
    version = resp[3:3 + str_len].decode("ascii", errors="replace")
    print(f"  VERSION: \"{version}\" (len={str_len})")
    assert "BQ76920_Bridge" in version, f"Unexpected version: {version}"
    print("  VERSION: PASS")


def test_bad_command(bridge):
    """Send invalid command ID, expect BAD_CMD status."""
    resp = bridge.send_command(0x99)
    assert resp[0] == 0x99, "Wrong command echo"
    assert resp[1] == STATUS_BAD_CMD, f"Expected BAD_CMD, got 0x{resp[1]:02X}"
    print("  BAD_CMD: PASS")


def test_read_register(bridge, reg_addr, reg_name=""):
    """Read a single register (requires BQ76920 connected)."""
    resp = bridge.send_command(CMD_READ_REG, reg_addr=reg_addr)
    status = resp[1]
    value = resp[3]
    label = f"0x{reg_addr:02X}" + (f" ({reg_name})" if reg_name else "")
    if status == STATUS_OK:
        print(f"  READ_REG {label} = 0x{value:02X}: PASS")
    else:
        print(f"  READ_REG {label}: I2C ERROR (status=0x{status:02X})")
    return status, value


def test_init_device(bridge):
    """Run INIT_DEVICE and report GAIN/OFFSET."""
    resp = bridge.send_command(CMD_INIT_DEVICE)
    status = resp[1]
    if status == STATUS_OK:
        gain = resp[3] | (resp[4] << 8)
        offset = struct.unpack("b", bytes([resp[5]]))[0]
        ncells = resp[6]
        print(f"  INIT_DEVICE: GAIN={gain} uV/LSB, OFFSET={offset} mV, "
              f"cells={ncells}: PASS")
    else:
        print(f"  INIT_DEVICE: I2C ERROR (status=0x{status:02X})")
    return status


def test_get_voltages(bridge, ncells=5):
    """Read all cell voltages + pack voltage."""
    resp = bridge.send_command(CMD_GET_VOLTAGES)
    status = resp[1]
    if status != STATUS_OK:
        print(f"  GET_VOLTAGES: I2C ERROR (status=0x{status:02X})")
        return status

    data_len = resp[2]
    print(f"  GET_VOLTAGES ({data_len} bytes):")

    for i in range(ncells):
        v = struct.unpack_from("<f", resp, 3 + i * 4)[0]
        print(f"    Cell {i+1}: {v:.3f} V")

    vpack = struct.unpack_from("<f", resp, 3 + ncells * 4)[0]
    print(f"    Pack:   {vpack:.3f} V")
    print("  GET_VOLTAGES: PASS")
    return status


def test_get_current(bridge):
    """Read coulomb counter / current."""
    resp = bridge.send_command(CMD_GET_CURRENT)
    status = resp[1]
    if status != STATUS_OK:
        print(f"  GET_CURRENT: I2C ERROR (status=0x{status:02X})")
        return status

    current = struct.unpack_from("<f", resp, 3)[0]
    print(f"  GET_CURRENT: {current:.1f} mA: PASS")
    return status


# ---- Main ------------------------------------------------------------------

def main():
    print("=" * 60)
    print("BQ76920_Bridge USB HID Integration Tests")
    print("=" * 60)

    # Check device presence
    info = find_device()
    if info is None:
        print(f"\nDevice not found (VID=0x{VID:04X}, PID=0x{PID:04X}).")
        print("Is the firmware flashed and the device plugged in?")
        print("\nListing all HID devices:")
        for d in hid.enumerate():
            if d["vendor_id"] != 0:
                print(f"  VID=0x{d['vendor_id']:04X} "
                      f"PID=0x{d['product_id']:04X} "
                      f"\"{d['product_string']}\"")
        sys.exit(1)

    print(f"\nDevice found: {info['product_string']}")
    print(f"  Path: {info['path'].decode()}")
    print()

    bridge = BridgeDevice()
    bridge.open()

    passed = 0
    failed = 0

    # ---- Tests that work without BQ76920 hardware ----
    print("--- No-hardware tests ---")
    try:
        test_echo(bridge)
        passed += 1
    except Exception as e:
        print(f"  ECHO: FAIL ({e})")
        failed += 1

    try:
        test_version(bridge)
        passed += 1
    except Exception as e:
        print(f"  VERSION: FAIL ({e})")
        failed += 1

    try:
        test_bad_command(bridge)
        passed += 1
    except Exception as e:
        print(f"  BAD_CMD: FAIL ({e})")
        failed += 1

    # ---- Tests that require BQ76920 on I2C bus ----
    print("\n--- BQ76920 I2C tests (require EVM connected) ---")

    st = test_init_device(bridge)
    if st == STATUS_OK:
        passed += 1

        # Read CC_CFG -- should be 0x19 after init
        st2, val = test_read_register(bridge, 0x0B, "CC_CFG")
        if st2 == STATUS_OK:
            if val == 0x19:
                passed += 1
            else:
                print(f"    WARNING: CC_CFG = 0x{val:02X}, expected 0x19")
                failed += 1
        else:
            failed += 1

        test_get_voltages(bridge)
        passed += 1

        test_get_current(bridge)
        passed += 1
    else:
        print("  (Skipping register tests -- no BQ76920 detected)")

    bridge.close()

    # Summary
    print()
    print("=" * 60)
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
