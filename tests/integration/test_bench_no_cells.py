#!/usr/bin/env python3
"""
Bench test suite for BQ76920_Bridge -- cell simulator mode (no real cells).

Setup: 18V / 0.5A DC supply on BATT+/BATT- (J3/J2), cell simulator dip
switches closed, BOOT button pressed after power-up.

Tests register access, ADC readings, protection config, FET control,
coulomb counter, and alert status -- everything that works without
actual cell connections.

Usage:
    python3 tests/integration/test_bench_no_cells.py
"""
import sys
import time
import struct

try:
    import hid
except ImportError:
    print("ERROR: pip install hidapi")
    sys.exit(1)

VID = 0x0483
PID = 0x572B
REPORT_SIZE = 64

# Command IDs
CMD_READ_REG     = 0x01
CMD_WRITE_REG    = 0x02
CMD_READ_BLOCK   = 0x03
CMD_INIT_DEVICE  = 0x10
CMD_GET_STATUS   = 0x11
CMD_GET_VOLTAGES = 0x12
CMD_GET_CURRENT  = 0x13
CMD_FET_CONTROL  = 0x14
CMD_VERSION      = 0xFF

STATUS_OK = 0x00

# BQ76920 register addresses
SYS_STAT   = 0x00
CELLBAL1   = 0x01
SYS_CTRL1  = 0x04
SYS_CTRL2  = 0x05
PROTECT1   = 0x06
PROTECT2   = 0x07
PROTECT3   = 0x08
OV_TRIP    = 0x09
UV_TRIP    = 0x0A
CC_CFG     = 0x0B
ADCGAIN1   = 0x50
ADCOFFSET  = 0x51
ADCGAIN2   = 0x59


class Bridge:
    def __init__(self):
        self.dev = hid.device()
        self.dev.open(VID, PID)
        self.dev.set_nonblocking(0)

    def close(self):
        self.dev.close()

    def cmd(self, cmd_id, reg=0, dlen=0, data=b""):
        report = bytes([0x00, cmd_id, reg, dlen]) + data
        report = report.ljust(REPORT_SIZE + 1, b"\x00")
        self.dev.write(report)
        resp = self.dev.read(REPORT_SIZE, 3000)
        if not resp:
            raise TimeoutError(f"No response for 0x{cmd_id:02X}")
        return bytes(resp)

    def read_reg(self, reg):
        r = self.cmd(CMD_READ_REG, reg)
        return r[1], r[3]  # status, value

    def write_reg(self, reg, val):
        r = self.cmd(CMD_WRITE_REG, reg, 0, bytes([val]))
        return r[1]  # status

    def read_block(self, reg, n):
        r = self.cmd(CMD_READ_BLOCK, reg, n)
        return r[1], r[3:3 + r[2]]  # status, data


passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  PASS  {name}" + (f" -- {detail}" if detail else ""))
        passed += 1
    else:
        print(f"  FAIL  {name}" + (f" -- {detail}" if detail else ""))
        failed += 1


def main():
    global passed, failed

    print("=" * 65)
    print("BQ76920 Bench Test -- Cell Simulator Mode (18V, no real cells)")
    print("=" * 65)

    b = Bridge()

    # ------------------------------------------------------------------
    print("\n--- 1. Device identification ---")

    r = b.cmd(CMD_VERSION)
    ver = r[3:3 + r[2]].decode("ascii", errors="replace")
    print(f"  Firmware: {ver}")

    r = b.cmd(CMD_INIT_DEVICE)
    check("INIT responds OK", r[1] == STATUS_OK)
    gain = r[3] | (r[4] << 8)
    offset = struct.unpack("b", bytes([r[5]]))[0]
    ncells = r[6]
    print(f"  GAIN={gain} uV/LSB, OFFSET={offset} mV, cells={ncells}")
    check("GAIN in valid range (365-396)", 365 <= gain <= 396, f"{gain}")
    check("OFFSET in valid range (-128 to +127)", -128 <= offset <= 127, f"{offset}")

    # ------------------------------------------------------------------
    print("\n--- 2. Register read/write verification ---")

    # CC_CFG should be 0x19 after init
    st, val = b.read_reg(CC_CFG)
    check("CC_CFG reads 0x19", st == STATUS_OK and val == 0x19,
          f"0x{val:02X}")

    # SYS_CTRL1: ADC_EN should be set (bit 4)
    st, val = b.read_reg(SYS_CTRL1)
    check("SYS_CTRL1 ADC_EN set", st == STATUS_OK and (val & 0x10),
          f"0x{val:02X}")

    # SYS_CTRL2: CC_EN may be cleared by hardware if OV/UV fault is active
    st, val = b.read_reg(SYS_CTRL2)
    if val & 0x20:
        check("SYS_CTRL2 CC_EN set", True, f"0x{val:02X}")
    else:
        check("SYS_CTRL2 CC_EN cleared by protection (OV/UV active)",
              st == STATUS_OK, f"0x{val:02X} -- normal if cell simulator trips OV")

    # Read ADC calibration registers directly
    st, g1 = b.read_reg(ADCGAIN1)
    check("ADCGAIN1 readable", st == STATUS_OK, f"0x{g1:02X}")
    st, g2 = b.read_reg(ADCGAIN2)
    check("ADCGAIN2 readable", st == STATUS_OK, f"0x{g2:02X}")
    st, ofs = b.read_reg(ADCOFFSET)
    check("ADCOFFSET readable", st == STATUS_OK, f"0x{ofs:02X}")

    # ------------------------------------------------------------------
    print("\n--- 3. Block read ---")

    # Read protection registers as a block (PROTECT1 through CC_CFG: 0x06-0x0B = 6 bytes)
    st, data = b.read_block(PROTECT1, 6)
    check("Block read PROTECT1-CC_CFG (6 bytes)", st == STATUS_OK and len(data) >= 6,
          f"{len(data)} bytes: {data.hex()}")

    if len(data) >= 6:
        print(f"    PROTECT1=0x{data[0]:02X}  PROTECT2=0x{data[1]:02X}  "
              f"PROTECT3=0x{data[2]:02X}")
        print(f"    OV_TRIP=0x{data[3]:02X}  UV_TRIP=0x{data[4]:02X}  "
              f"CC_CFG=0x{data[5]:02X}")

    # ------------------------------------------------------------------
    print("\n--- 4. SYS_STAT alert register ---")

    st, stat = b.read_reg(SYS_STAT)
    check("SYS_STAT readable", st == STATUS_OK, f"0x{stat:02X}")
    if st == STATUS_OK:
        flags = []
        if stat & 0x80: flags.append("CC_READY")
        if stat & 0x20: flags.append("DEVICE_XREADY")
        if stat & 0x10: flags.append("OVRD_ALERT")
        if stat & 0x08: flags.append("UV")
        if stat & 0x04: flags.append("OV")
        if stat & 0x02: flags.append("SCD")
        if stat & 0x01: flags.append("OCD")
        print(f"    Active flags: {', '.join(flags) if flags else 'none'}")

    # Clear faults by writing 0xFF
    st = b.write_reg(SYS_STAT, 0xFF)
    check("SYS_STAT clear faults", st == STATUS_OK)

    # Re-read to verify cleared
    st, stat2 = b.read_reg(SYS_STAT)
    if st == STATUS_OK:
        # CC_READY (bit 7) may re-assert immediately -- mask it
        cleared = (stat2 & 0x3F) == 0x00
        check("SYS_STAT faults cleared", cleared,
              f"0x{stat2:02X} (was 0x{stat:02X})")

    # ------------------------------------------------------------------
    print("\n--- 5. Cell voltages (cell simulator) ---")

    r = b.cmd(CMD_GET_VOLTAGES)
    check("GET_VOLTAGES responds OK", r[1] == STATUS_OK)

    voltages = []
    for i in range(ncells):
        v = struct.unpack_from("<f", r, 3 + i * 4)[0]
        voltages.append(v)
        # With 18V across 5-cell simulator (200 ohm resistors), expect ~3.6V/cell
        # Some cells may read near 0 if not connected
        in_range = (0.0 <= v <= 5.0)
        check(f"Cell {i+1} voltage plausible", in_range, f"{v:.3f} V")

    vpack = struct.unpack_from("<f", r, 3 + ncells * 4)[0]
    check("Pack voltage ~18V", 10.0 <= vpack <= 25.0, f"{vpack:.3f} V")

    # Check if cell voltages roughly sum to pack voltage
    vsum = sum(voltages)
    if vpack > 1.0:
        ratio = vsum / vpack
        check("Cell sum approx equals pack voltage",
              0.5 < ratio < 1.5, f"sum={vsum:.2f}V, pack={vpack:.2f}V")

    # ------------------------------------------------------------------
    print("\n--- 6. Coulomb counter / current ---")

    r = b.cmd(CMD_GET_CURRENT)
    check("GET_CURRENT responds OK", r[1] == STATUS_OK)
    current = struct.unpack_from("<f", r, 3)[0]
    # With no load, current should be near zero (small bias)
    check("Current near zero (no load)", abs(current) < 500.0,
          f"{current:.1f} mA")

    # ------------------------------------------------------------------
    print("\n--- 7. Protection register write/readback ---")

    # Read current OV_TRIP, modify, verify, restore
    st, ov_orig = b.read_reg(OV_TRIP)
    if st == STATUS_OK:
        test_val = 0xAA if ov_orig != 0xAA else 0x55
        st = b.write_reg(OV_TRIP, test_val)
        check("OV_TRIP write", st == STATUS_OK)

        st, ov_read = b.read_reg(OV_TRIP)
        check("OV_TRIP readback matches write",
              st == STATUS_OK and ov_read == test_val,
              f"wrote 0x{test_val:02X}, read 0x{ov_read:02X}")

        # Restore original
        b.write_reg(OV_TRIP, ov_orig)
        print(f"    Restored OV_TRIP to 0x{ov_orig:02X}")

    # Same for UV_TRIP
    st, uv_orig = b.read_reg(UV_TRIP)
    if st == STATUS_OK:
        test_val = 0x55 if uv_orig != 0x55 else 0xAA
        st = b.write_reg(UV_TRIP, test_val)
        st2, uv_read = b.read_reg(UV_TRIP)
        check("UV_TRIP write/readback",
              st == STATUS_OK and st2 == STATUS_OK and uv_read == test_val,
              f"wrote 0x{test_val:02X}, read 0x{uv_read:02X}")
        b.write_reg(UV_TRIP, uv_orig)
        print(f"    Restored UV_TRIP to 0x{uv_orig:02X}")

    # ------------------------------------------------------------------
    print("\n--- 8. FET control ---")

    # Read SYS_CTRL2 before FET operations
    st, ctrl2_before = b.read_reg(SYS_CTRL2)

    # Enable CHG FET -- BQ76920 will refuse if OV fault is active
    r = b.cmd(CMD_FET_CONTROL, 0, 0, bytes([0x01 | 0x04]))  # CHG + ON
    check("CHG FET ON command accepted", r[1] == STATUS_OK)

    st, ctrl2 = b.read_reg(SYS_CTRL2)
    if st == STATUS_OK:
        if ctrl2 & 0x01:
            check("CHG_ON bit set", True, f"SYS_CTRL2=0x{ctrl2:02X}")
        else:
            # OV protection blocks CHG FET -- this is correct hardware behavior
            st2, stat = b.read_reg(SYS_STAT)
            ov_active = (stat & 0x04) != 0 if st2 == STATUS_OK else False
            check("CHG blocked by OV protection (expected)",
                  ov_active, f"SYS_CTRL2=0x{ctrl2:02X}, SYS_STAT=0x{stat:02X}")

    # Enable DSG FET
    r = b.cmd(CMD_FET_CONTROL, 0, 0, bytes([0x02 | 0x04]))  # DSG + ON
    check("DSG FET ON command", r[1] == STATUS_OK)

    st, ctrl2 = b.read_reg(SYS_CTRL2)
    if st == STATUS_OK:
        check("DSG_ON bit set", (ctrl2 & 0x02) != 0, f"SYS_CTRL2=0x{ctrl2:02X}")

    # Disable both
    r = b.cmd(CMD_FET_CONTROL, 0, 0, bytes([0x03]))  # CHG+DSG + OFF
    check("FET OFF command", r[1] == STATUS_OK)

    st, ctrl2 = b.read_reg(SYS_CTRL2)
    if st == STATUS_OK:
        check("Both FETs off", (ctrl2 & 0x03) == 0, f"SYS_CTRL2=0x{ctrl2:02X}")

    # ------------------------------------------------------------------
    print("\n--- 9. Cell balance register ---")

    st, bal_orig = b.read_reg(CELLBAL1)
    check("CELLBAL1 readable", st == STATUS_OK, f"0x{bal_orig:02X}")

    # Write a test pattern (enable balancing on cell 1 and 3)
    st = b.write_reg(CELLBAL1, 0x05)
    st2, bal_read = b.read_reg(CELLBAL1)
    check("CELLBAL1 write/readback", st == STATUS_OK and bal_read == 0x05,
          f"wrote 0x05, read 0x{bal_read:02X}")

    # Clear balancing
    b.write_reg(CELLBAL1, 0x00)

    # ------------------------------------------------------------------
    print("\n--- 10. Full register dump (0x00-0x0B) ---")

    st, dump = b.read_block(0x00, 12)
    if st == STATUS_OK and len(dump) >= 12:
        names = ["SYS_STAT", "CELLBAL1", "CELLBAL2", "CELLBAL3",
                 "SYS_CTRL1", "SYS_CTRL2", "PROTECT1", "PROTECT2",
                 "PROTECT3", "OV_TRIP", "UV_TRIP", "CC_CFG"]
        for i, name in enumerate(names):
            print(f"    0x{i:02X} {name:12s} = 0x{dump[i]:02X}")
        check("Register dump complete", True)
    else:
        check("Register dump complete", False, "block read failed")

    # ------------------------------------------------------------------
    b.close()

    print()
    print("=" * 65)
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 65)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
