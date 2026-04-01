#!/usr/bin/env python3
"""
USB HID integration tests for the BQ76920_Bridge firmware (EV2300 emulation).

Uses the EV2300 packet protocol to communicate with the bridge device.

Usage:
    python3 tests/integration/test_usb_hid_bridge.py
"""
import sys
import struct
import time

try:
    import hid
except ImportError:
    print("ERROR: pip install hidapi")
    sys.exit(1)

# EV2300 identity (our firmware emulates this)
VID = 0x0451
PID = 0x0036
REPORT_SIZE = 64

# EV2300 protocol constants
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

# BQ76920 default I2C address (7-bit, no CRC)
BQ_ADDR = 0x08


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

    payload = bytearray()
    payload.append(i2c_addr << 1)
    payload.append(reg)
    payload.extend(data)

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


def parse_response(raw):
    if raw is None or len(raw) < 8:
        return {"ok": False, "error": True, "status_text": "Response too short"}
    cmd = raw[2]
    success = bool(cmd & RESP_FLAG) and cmd != CMD_ERROR
    plen = raw[6] if len(raw) > 6 else 0
    payload = bytes(raw[7:7 + plen]) if plen > 0 else b""
    return {"ok": success, "cmd": cmd, "payload": payload, "raw": bytes(raw)}


class EV2300Bridge:
    def __init__(self):
        self.dev = hid.device()

    def open(self):
        self.dev.open(VID, PID)
        self.dev.set_nonblocking(0)

    def close(self):
        self.dev.close()

    def _send(self, pkt):
        self.dev.write(bytes([0x00]) + bytes(pkt))
        time.sleep(0.01)
        resp = self.dev.read(REPORT_SIZE, 2000)
        return parse_response(resp)

    def _send_with_submit(self, pkt):
        # Phase 1: send command, read ack
        self.dev.write(bytes([0x00]) + bytes(pkt))
        time.sleep(0.01)
        self.dev.read(REPORT_SIZE, 2000)  # discard write ack

        # Phase 2: send SUBMIT, read final response
        submit = build_packet(CMD_SUBMIT)
        self.dev.write(bytes([0x00]) + bytes(submit))
        time.sleep(0.01)
        resp = self.dev.read(REPORT_SIZE, 2000)
        return parse_response(resp)

    def read_byte(self, addr, reg):
        pkt = build_packet(CMD_READ_BYTE, addr, reg)
        resp = self._send(pkt)
        if resp["ok"] and len(resp.get("raw", b"")) > 8:
            resp["value"] = resp["raw"][8]
        else:
            resp["value"] = None
        return resp

    def read_word(self, addr, reg):
        pkt = build_packet(CMD_READ_WORD, addr, reg)
        resp = self._send(pkt)
        if resp["ok"] and len(resp.get("raw", b"")) >= 10:
            resp["value"] = struct.unpack("<H", resp["raw"][8:10])[0]
        else:
            resp["value"] = None
        return resp

    def write_byte(self, addr, reg, val):
        pkt = build_packet(CMD_WRITE_BYTE, addr, reg, bytes([val & 0xFF]))
        return self._send_with_submit(pkt)


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

    print("=" * 60)
    print("BQ76920_Bridge EV2300 Protocol Integration Tests")
    print("=" * 60)

    # Find device
    devices = hid.enumerate(VID, PID)
    if not devices:
        print(f"\nDevice not found (VID=0x{VID:04X}, PID=0x{PID:04X}).")
        print("Is the firmware flashed?")
        print("\nAll HID devices:")
        for d in hid.enumerate():
            if d["vendor_id"]:
                print(f"  VID=0x{d['vendor_id']:04X} PID=0x{d['product_id']:04X} "
                      f'"{d["product_string"]}"')
        sys.exit(1)

    print(f"\nDevice: {devices[0]['product_string']}")
    b = EV2300Bridge()
    b.open()

    # --- Protocol tests (no BQ76920 needed) ---
    print("\n--- EV2300 packet format tests ---")

    # Bad marker should return error
    bad_pkt = bytearray(REPORT_SIZE)
    bad_pkt[1] = 0x00  # wrong marker
    bad_pkt[2] = CMD_READ_BYTE
    b.dev.write(bytes([0x00]) + bytes(bad_pkt))
    time.sleep(0.01)
    resp = b.dev.read(REPORT_SIZE, 2000)
    r = parse_response(resp)
    check("Bad marker returns error", r["cmd"] == CMD_ERROR)

    # --- BQ76920 I2C tests ---
    print("\n--- BQ76920 register tests ---")

    # Read CC_CFG (should be 0x19 after init)
    r = b.read_byte(BQ_ADDR, 0x0B)
    if r["ok"]:
        check("READ_BYTE CC_CFG", r["value"] == 0x19,
              f"0x{r['value']:02X}")
    else:
        check("READ_BYTE CC_CFG", False, "I2C error")
        print("  (BQ76920 not detected -- skipping remaining I2C tests)")
        b.close()
        print(f"\nResults: {passed}/{passed + failed} passed")
        sys.exit(0 if failed == 0 else 1)

    # Read SYS_CTRL1 (ADC_EN should be set)
    r = b.read_byte(BQ_ADDR, 0x04)
    check("READ_BYTE SYS_CTRL1 ADC_EN", r["ok"] and (r["value"] & 0x10),
          f"0x{r['value']:02X}" if r["ok"] else "err")

    # Read word: VC1_HI/LO (cell 1 voltage)
    r = b.read_word(BQ_ADDR, 0x0C)
    check("READ_WORD VC1", r["ok"] and r["value"] is not None,
          f"raw=0x{r['value']:04X}" if r["ok"] else "err")

    # Read word: BAT_HI/LO (pack voltage)
    r = b.read_word(BQ_ADDR, 0x2A)
    check("READ_WORD BAT", r["ok"] and r["value"] is not None,
          f"raw=0x{r['value']:04X}" if r["ok"] else "err")

    # Write/readback test: OV_TRIP
    r_orig = b.read_byte(BQ_ADDR, 0x09)
    if r_orig["ok"]:
        orig = r_orig["value"]
        test_val = 0xAA if orig != 0xAA else 0x55
        w = b.write_byte(BQ_ADDR, 0x09, test_val)
        check("WRITE_BYTE OV_TRIP", w["ok"])

        r_back = b.read_byte(BQ_ADDR, 0x09)
        check("OV_TRIP readback matches",
              r_back["ok"] and r_back["value"] == test_val,
              f"wrote 0x{test_val:02X}, read 0x{r_back['value']:02X}" if r_back["ok"] else "err")

        # Restore
        b.write_byte(BQ_ADDR, 0x09, orig)

    b.close()

    print()
    print("=" * 60)
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
