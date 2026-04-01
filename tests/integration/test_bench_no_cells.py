#!/usr/bin/env python3
"""
Bench test suite for BQ76920_Bridge -- EV2300 emulation mode.

Setup: 18V / 0.5A DC supply on BATT+/BATT- (J3/J2), cell simulator dip
switches closed, BOOT button pressed after power-up.

Usage:
    python3 tests/integration/test_bench_no_cells.py
"""
import sys
import struct
import time

try:
    import hid
except ImportError:
    print("ERROR: pip install hidapi")
    sys.exit(1)

# EV2300 identity
VID = 0x0451
PID = 0x0036
REPORT_SIZE = 64

# Protocol constants
FRAME_MARKER = 0xAA
FRAME_END    = 0x55
RESP_FLAG    = 0x40
CMD_READ_WORD  = 0x01
CMD_READ_BLOCK = 0x02
CMD_READ_BYTE  = 0x03
CMD_WRITE_WORD = 0x04
CMD_WRITE_BYTE = 0x07
CMD_SUBMIT     = 0x80
CMD_ERROR      = 0x46

BQ_ADDR = 0x08

# BQ76920 registers
SYS_STAT  = 0x00
SYS_CTRL1 = 0x04
SYS_CTRL2 = 0x05
PROTECT1  = 0x06
OV_TRIP   = 0x09
UV_TRIP   = 0x0A
CC_CFG    = 0x0B
VC1_HI    = 0x0C
BAT_HI    = 0x2A
CC_HI     = 0x32
ADCGAIN1  = 0x50
ADCOFFSET = 0x51
ADCGAIN2  = 0x59


def crc8(data):
    crc = 0x00
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def build_packet(cmd, i2c_addr=0, reg=0, data=b""):
    buf = bytearray(REPORT_SIZE)
    if cmd == CMD_SUBMIT:
        buf[0] = 8
        buf[1] = FRAME_MARKER
        buf[2] = CMD_SUBMIT
        buf[6] = 0
        buf[7] = crc8(buf[2:7])
        buf[8] = FRAME_END
        return buf
    payload = bytearray([i2c_addr << 1, reg]) + bytearray(data)
    plen = len(payload)
    buf[0] = 2 + 1 + 3 + 1 + plen + 1 + 1
    buf[1] = FRAME_MARKER
    buf[2] = cmd
    buf[6] = plen
    buf[7:7 + plen] = payload
    crc_end = 7 + plen
    buf[crc_end] = crc8(buf[2:crc_end])
    buf[crc_end + 1] = FRAME_END
    return buf


class Bridge:
    def __init__(self):
        self.dev = hid.device()
        self.dev.open(VID, PID)
        self.dev.set_nonblocking(0)

    def close(self):
        self.dev.close()

    def _send(self, pkt):
        self.dev.write(bytes([0x00]) + bytes(pkt))
        time.sleep(0.01)
        raw = self.dev.read(REPORT_SIZE, 2000)
        if raw is None or len(raw) < 8:
            return {"ok": False}
        cmd = raw[2]
        ok = bool(cmd & RESP_FLAG) and cmd != CMD_ERROR
        plen = raw[6]
        return {"ok": ok, "cmd": cmd, "plen": plen, "raw": bytes(raw)}

    def _write_submit(self, pkt):
        self.dev.write(bytes([0x00]) + bytes(pkt))
        time.sleep(0.01)
        self.dev.read(REPORT_SIZE, 2000)  # ack
        submit = build_packet(CMD_SUBMIT)
        self.dev.write(bytes([0x00]) + bytes(submit))
        time.sleep(0.01)
        raw = self.dev.read(REPORT_SIZE, 2000)
        if raw is None or len(raw) < 8:
            return {"ok": False}
        cmd = raw[2]
        return {"ok": bool(cmd & RESP_FLAG) and cmd != CMD_ERROR}

    def read_byte(self, reg):
        r = self._send(build_packet(CMD_READ_BYTE, BQ_ADDR, reg))
        r["value"] = r["raw"][8] if r["ok"] and len(r.get("raw", b"")) > 8 else None
        return r

    def read_word(self, reg):
        r = self._send(build_packet(CMD_READ_WORD, BQ_ADDR, reg))
        if r["ok"] and len(r.get("raw", b"")) >= 10:
            r["value"] = struct.unpack("<H", r["raw"][8:10])[0]
        else:
            r["value"] = None
        return r

    def write_byte(self, reg, val):
        pkt = build_packet(CMD_WRITE_BYTE, BQ_ADDR, reg, bytes([val]))
        return self._write_submit(pkt)

    def read_block(self, reg):
        r = self._send(build_packet(CMD_READ_BLOCK, BQ_ADDR, reg))
        if r["ok"] and len(r.get("raw", b"")) > 9:
            blen = r["raw"][8]
            r["block"] = bytes(r["raw"][9:9 + blen])
        else:
            r["block"] = None
        return r


passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        print(f"  PASS  {name}" + (f" -- {detail}" if detail else ""))
        passed += 1
    else:
        print(f"  FAIL  {name}" + (f" -- {detail}" if detail else ""))
        failed += 1


def main():
    global passed, failed

    print("=" * 65)
    print("BQ76920 Bench Test -- EV2300 Emulation (18V cell simulator)")
    print("=" * 65)

    b = Bridge()

    # --- 1. Register reads ---
    print("\n--- 1. Basic register reads ---")

    r = b.read_byte(CC_CFG)
    check("CC_CFG = 0x19", r["ok"] and r["value"] == 0x19,
          f"0x{r['value']:02X}" if r["value"] is not None else "err")

    r = b.read_byte(SYS_CTRL1)
    check("SYS_CTRL1 ADC_EN set", r["ok"] and (r["value"] & 0x10),
          f"0x{r['value']:02X}" if r["ok"] else "err")

    r = b.read_byte(ADCGAIN1)
    check("ADCGAIN1 readable", r["ok"], f"0x{r['value']:02X}" if r["ok"] else "err")

    r = b.read_byte(ADCGAIN2)
    check("ADCGAIN2 readable", r["ok"], f"0x{r['value']:02X}" if r["ok"] else "err")

    r = b.read_byte(ADCOFFSET)
    check("ADCOFFSET readable", r["ok"], f"0x{r['value']:02X}" if r["ok"] else "err")

    # --- 2. ADC calibration ---
    print("\n--- 2. ADC calibration ---")

    g1 = b.read_byte(ADCGAIN1)
    g2 = b.read_byte(ADCGAIN2)
    ofs = b.read_byte(ADCOFFSET)

    if g1["ok"] and g2["ok"] and ofs["ok"]:
        gain_code = ((g1["value"] >> 3) & 0x03) << 3 | (g2["value"] & 0x07)
        gain = 365 + gain_code
        offset = struct.unpack("b", bytes([ofs["value"]]))[0]
        check("GAIN in range (365-396)", 365 <= gain <= 396, f"{gain} uV/LSB")
        check("OFFSET in range", -128 <= offset <= 127, f"{offset} mV")
    else:
        check("ADC cal readable", False, "I2C error")

    # --- 3. Cell voltages via READ_WORD ---
    print("\n--- 3. Cell voltages ---")

    for i in range(5):
        reg = VC1_HI + (i * 2)
        r = b.read_word(reg)
        if r["ok"] and r["value"] is not None:
            # READ_WORD returns [HI, LO] as LE word, so swap bytes for BQ76920
            raw_le = r["value"]
            hi_byte = raw_le & 0xFF
            lo_byte = (raw_le >> 8) & 0xFF
            raw14 = ((hi_byte & 0x3F) << 8) | lo_byte
            mV = (gain * raw14) / 1000.0 + offset
            V = mV / 1000.0
            check(f"Cell {i+1} readable", True, f"{V:.3f} V (raw14={raw14})")
        else:
            check(f"Cell {i+1} readable", False, "I2C error")

    # Pack voltage
    r = b.read_word(BAT_HI)
    if r["ok"] and r["value"] is not None:
        raw_le = r["value"]
        hi_byte = raw_le & 0xFF
        lo_byte = (raw_le >> 8) & 0xFF
        raw16 = (hi_byte << 8) | lo_byte
        mV = (4.0 * gain * raw16) / 1000.0 + (5 * offset)
        V = mV / 1000.0
        check("Pack voltage", 10.0 <= V <= 25.0, f"{V:.3f} V")
    else:
        check("Pack voltage", False, "I2C error")

    # --- 4. SYS_STAT ---
    print("\n--- 4. Alert status ---")

    r = b.read_byte(SYS_STAT)
    if r["ok"]:
        stat = r["value"]
        flags = []
        if stat & 0x80: flags.append("CC_READY")
        if stat & 0x20: flags.append("XREADY")
        if stat & 0x10: flags.append("OVRD_ALERT")
        if stat & 0x08: flags.append("UV")
        if stat & 0x04: flags.append("OV")
        if stat & 0x02: flags.append("SCD")
        if stat & 0x01: flags.append("OCD")
        check("SYS_STAT readable", True,
              f"0x{stat:02X} [{', '.join(flags) if flags else 'clear'}]")

    # Clear faults
    w = b.write_byte(SYS_STAT, 0xFF)
    check("Clear faults", w["ok"])

    # --- 5. Write/readback ---
    print("\n--- 5. Register write/readback ---")

    r = b.read_byte(OV_TRIP)
    if r["ok"]:
        orig = r["value"]
        test_val = 0xAA if orig != 0xAA else 0x55
        w = b.write_byte(OV_TRIP, test_val)
        check("OV_TRIP write", w["ok"])
        r2 = b.read_byte(OV_TRIP)
        check("OV_TRIP readback", r2["ok"] and r2["value"] == test_val,
              f"wrote 0x{test_val:02X}, read 0x{r2['value']:02X}" if r2["ok"] else "err")
        b.write_byte(OV_TRIP, orig)
        print(f"    Restored OV_TRIP to 0x{orig:02X}")

    r = b.read_byte(UV_TRIP)
    if r["ok"]:
        orig = r["value"]
        test_val = 0x55 if orig != 0x55 else 0xAA
        w = b.write_byte(UV_TRIP, test_val)
        r2 = b.read_byte(UV_TRIP)
        check("UV_TRIP write/readback", r2["ok"] and r2["value"] == test_val,
              f"wrote 0x{test_val:02X}, read 0x{r2['value']:02X}" if r2["ok"] else "err")
        b.write_byte(UV_TRIP, orig)
        print(f"    Restored UV_TRIP to 0x{orig:02X}")

    # --- 6. Coulomb counter ---
    print("\n--- 6. Coulomb counter ---")

    r = b.read_word(CC_HI)
    if r["ok"] and r["value"] is not None:
        raw = struct.unpack("<h", struct.pack("<H", r["value"]))[0]
        current_mA = (raw * 8.44) / 1.0  # 1 mohm sense resistor
        check("CC readable", True, f"raw={raw}, ~{current_mA:.1f} mA")
    else:
        check("CC readable", False, "I2C error")

    # --- 7. Block read ---
    print("\n--- 7. Block read ---")

    r = b.read_block(PROTECT1)
    if r["ok"] and r["block"] is not None and len(r["block"]) >= 6:
        names = ["PROTECT1", "PROTECT2", "PROTECT3", "OV_TRIP", "UV_TRIP", "CC_CFG"]
        for i, name in enumerate(names):
            print(f"    {name} = 0x{r['block'][i]:02X}")
        check("Block read (6 regs)", True, f"{len(r['block'])} bytes")
    else:
        check("Block read", False, "err")

    b.close()

    print()
    print("=" * 65)
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 65)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
