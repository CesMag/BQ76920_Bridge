#!/usr/bin/env python3
"""
EV2300 protocol compliance test suite.

Verifies the STM32 bridge matches real EV2300 behavior captured on
2026-04-01 with flushed HID reads.  Covers silent commands, response
codes, DLL-like sequences, GUI-like sequences, and buffer-poisoning
regression tests.

Usage:
    python tests/tools/test_ev2300_compliance.py
"""
import sys
import time

try:
    import hid
except ImportError:
    print("ERROR: pip install hidapi")
    sys.exit(1)

# ── Constants ─────────────────────────────────────────────────────────────────

VID = 0x0451
PID = 0x0036
BUF = 64

BQ_ADDR_7BIT = 0x08          # BQ76920 7-bit SMBus address (no-CRC)
BQ_ADDR_8BIT = 0x10          # same address left-shifted for EV2300 ext cmds

# EV2300 command codes
CMD_READ_WORD   = 0x01
CMD_READ_BLOCK  = 0x02
CMD_READ_BYTE   = 0x03
CMD_WRITE_WORD  = 0x04
CMD_WRITE_BYTE  = 0x07
CMD_I2CPOWER    = 0x18
CMD_EXT_READ    = 0x1D
CMD_EXT_WRITE   = 0x1E
CMD_SUBMIT      = 0x80
CMD_ERROR       = 0x46

# Expected response codes
RESP_READ_WORD  = 0x41
RESP_READ_BLOCK = 0x42
RESP_EXT_READ   = 0x52
RESP_SUBMIT     = 0xC0
RESP_NULL       = 0x40
RESP_I2C_STATUS = 0x4E

# BQ76920 registers
SYS_STAT  = 0x00
CC_CFG    = 0x0B

# ── CRC-8 (poly 0x07, init 0x00) ─────────────────────────────────────────────

_CRC_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = ((_c << 1) ^ 0x07) & 0xFF if _c & 0x80 else (_c << 1) & 0xFF
    _CRC_TABLE.append(_c)


def crc8(data):
    c = 0
    for b in data:
        c = _CRC_TABLE[c ^ b]
    return c


# ── Packet builder ────────────────────────────────────────────────────────────

def build(cmd, payload=b""):
    inner = bytes([cmd, 0, 0, 0, len(payload)]) + payload
    frame = bytes([0xAA]) + inner + bytes([crc8(inner), 0x55])
    pkt = bytes([len(frame)]) + frame
    return pkt + b"\x00" * (BUF - len(pkt))


# ── Response parser ───────────────────────────────────────────────────────────

def parse(raw):
    """Parse a 64-byte HID response.  Returns dict with resp_code, plen,
    payload, or None if the frame is invalid."""
    if raw is None or len(raw) < 8:
        return None
    # Frame starts at byte 1 (byte 0 is total length), marker at byte 1
    if raw[1] != 0xAA:
        return None
    return {
        "resp_code": raw[2],
        "reserved":  bytes(raw[3:6]),
        "plen":      raw[6],
        "payload":   bytes(raw[7:7 + raw[6]]) if raw[6] > 0 else b"",
        "raw":       bytes(raw),
    }


# ── HID helpers ───────────────────────────────────────────────────────────────

def flush(dev, max_reads=20):
    """Drain any stale HID reports."""
    dev.set_nonblocking(True)
    for _ in range(max_reads):
        r = dev.read(BUF)
        if not r:
            break
    dev.set_nonblocking(False)


def send(dev, cmd, payload=b"", timeout=2000):
    """Send a command and read the response.  Returns raw list or None."""
    pkt = build(cmd, payload)
    dev.write(b"\x00" + pkt)
    time.sleep(0.02)
    return dev.read(BUF, timeout)


def send_clean(dev, cmd, payload=b"", timeout=2000):
    """Flush, send, read.  Returns raw list or None."""
    flush(dev)
    return send(dev, cmd, payload, timeout)


def send_silent_test(dev, cmd, payload=b"", timeout=1200):
    """For commands expected to produce NO response.  Flushes first,
    then verifies read times out.  Returns True if silent (correct)."""
    flush(dev)
    time.sleep(0.02)
    pkt = build(cmd, payload)
    dev.write(b"\x00" + pkt)
    time.sleep(0.02)
    r = dev.read(BUF, timeout)
    return r is None or len(r) == 0


# ── Test framework ────────────────────────────────────────────────────────────

_passed = 0
_failed = 0


def check(name, condition, detail=""):
    global _passed, _failed
    if condition:
        print(f"  PASS  {name}" + (f" -- {detail}" if detail else ""))
        _passed += 1
    else:
        print(f"  FAIL  {name}" + (f" -- {detail}" if detail else ""))
        _failed += 1


# ── Section A: Silent command verification ────────────────────────────────────

def test_silent_commands(dev):
    print("\n=== Section A: Silent Commands ===")
    print("  (Real EV2300 sends NO HID response for these)")
    print()

    # I2CPower enable
    ok = send_silent_test(dev, CMD_I2CPOWER, bytes([0x01]))
    check("I2CPower(1) is silent", ok)

    # I2CPower disable
    ok = send_silent_test(dev, CMD_I2CPOWER, bytes([0x00]))
    check("I2CPower(0) is silent", ok)

    # WRITE_BYTE (addr=0x08, reg=CC_CFG, val=0x19)
    ok = send_silent_test(dev, CMD_WRITE_BYTE,
                          bytes([BQ_ADDR_7BIT, CC_CFG, 0x19]))
    check("WRITE_BYTE is silent", ok)

    # EXT_WRITE (addr=0x10, reg=CC_CFG, count=1, data=0x19)
    ok = send_silent_test(dev, CMD_EXT_WRITE,
                          bytes([BQ_ADDR_8BIT, CC_CFG, 0x01, 0x19]))
    check("EXT_WRITE is silent", ok)


# ── Section B: Response code verification ─────────────────────────────────────

def test_response_codes(dev):
    print("\n=== Section B: Response Codes ===")
    print()

    # READ_WORD (0x01) -> 0x41
    r = send_clean(dev, CMD_READ_WORD, bytes([BQ_ADDR_7BIT, CC_CFG]))
    p = parse(r)
    check("READ_WORD response code",
          p is not None and p["resp_code"] == RESP_READ_WORD,
          f"got 0x{p['resp_code']:02X}" if p else "no response")
    check("READ_WORD plen=4",
          p is not None and p["plen"] == 4,
          f"got {p['plen']}" if p else "no response")

    # READ_BLOCK (0x02) -> 0x42
    r = send_clean(dev, CMD_READ_BLOCK,
                   bytes([BQ_ADDR_7BIT, SYS_STAT, 0x04]))
    p = parse(r)
    check("READ_BLOCK response code",
          p is not None and p["resp_code"] == RESP_READ_BLOCK,
          f"got 0x{p['resp_code']:02X}" if p else "no response")

    # READ_BYTE (0x03) -> 0x42 (real EV2300 quirk)
    r = send_clean(dev, CMD_READ_BYTE, bytes([BQ_ADDR_7BIT, SYS_STAT]))
    p = parse(r)
    check("READ_BYTE response code",
          p is not None and p["resp_code"] == RESP_READ_BLOCK,
          f"got 0x{p['resp_code']:02X}" if p else "no response")

    # EXT_READ (0x1D) -> 0x52
    r = send_clean(dev, CMD_EXT_READ,
                   bytes([BQ_ADDR_8BIT, SYS_STAT, 0x01]))
    p = parse(r)
    check("EXT_READ response code",
          p is not None and p["resp_code"] == RESP_EXT_READ,
          f"got 0x{p['resp_code']:02X}" if p else "no response")

    # NULL command (0x00) -> 0x40
    r = send_clean(dev, 0x00)
    p = parse(r)
    check("NULL (0x00) response code",
          p is not None and p["resp_code"] == RESP_NULL,
          f"got 0x{p['resp_code']:02X}" if p else "no response")

    # SUBMIT (0x80) with pending write -> 0xC0
    # First stage a WRITE_BYTE (silent), then SUBMIT
    flush(dev)
    send(dev, CMD_WRITE_BYTE, bytes([BQ_ADDR_7BIT, CC_CFG, 0x19]), 200)
    time.sleep(0.05)
    r = send(dev, CMD_SUBMIT, timeout=2000)
    p = parse(r)
    check("SUBMIT response code",
          p is not None and p["resp_code"] == RESP_SUBMIT,
          f"got 0x{p['resp_code']:02X}" if p else "no response")
    if p and p["resp_code"] == RESP_SUBMIT:
        check("SUBMIT payload {0x33,0x31,0x6D}",
              p["payload"][:3] == bytes([0x33, 0x31, 0x6D]),
              f"got {p['payload'][:3].hex()}")


# ── Section C: DLL-like sequence ──────────────────────────────────────────────

def test_dll_sequence(dev):
    print("\n=== Section C: DLL Sequence (I2CPower -> ReadSMBusWord) ===")
    print()

    # Step 1: I2CPower(1) - must be silent
    flush(dev)
    pkt = build(CMD_I2CPOWER, bytes([0x01]))
    dev.write(b"\x00" + pkt)
    time.sleep(0.1)

    # Step 2: ReadSMBusWord (CC_CFG) - must get 0x41, NOT stale 0x46
    pkt2 = build(CMD_READ_WORD, bytes([BQ_ADDR_7BIT, CC_CFG]))
    dev.write(b"\x00" + pkt2)
    time.sleep(0.05)
    r = dev.read(BUF, 2000)
    p = parse(r)

    check("DLL: ReadWord after I2CPower gets 0x41 (not stale 0x46)",
          p is not None and p["resp_code"] == RESP_READ_WORD,
          f"got 0x{p['resp_code']:02X}" if p else "TIMEOUT")

    if p and p["resp_code"] == RESP_READ_WORD and p["plen"] >= 4:
        word = p["payload"][1] | (p["payload"][2] << 8)
        check("DLL: CC_CFG value is 0x0019",
              word == 0x0019,
              f"got 0x{word:04X}")


# ── Section D: GUI-like sequence ──────────────────────────────────────────────

def test_gui_sequence(dev):
    print("\n=== Section D: GUI Sequence (ExtRead -> ExtWrite -> Submit -> ExtRead) ===")
    print()

    # Step 1: ExtRead CC_CFG - get baseline
    r1 = send_clean(dev, CMD_EXT_READ,
                    bytes([BQ_ADDR_8BIT, CC_CFG, 0x01]))
    p1 = parse(r1)
    check("GUI: initial ExtRead gets 0x52",
          p1 is not None and p1["resp_code"] == RESP_EXT_READ,
          f"got 0x{p1['resp_code']:02X}" if p1 else "TIMEOUT")

    # Step 2: ExtWrite CC_CFG = 0x19 - must be silent
    flush(dev)
    pkt_w = build(CMD_EXT_WRITE,
                  bytes([BQ_ADDR_8BIT, CC_CFG, 0x01, 0x19]))
    dev.write(b"\x00" + pkt_w)
    time.sleep(0.1)

    # Step 3: Submit - must get 0xC0
    pkt_s = build(CMD_SUBMIT)
    dev.write(b"\x00" + pkt_s)
    time.sleep(0.05)
    r3 = dev.read(BUF, 2000)
    p3 = parse(r3)
    check("GUI: Submit gets 0xC0",
          p3 is not None and p3["resp_code"] == RESP_SUBMIT,
          f"got 0x{p3['resp_code']:02X}" if p3 else "TIMEOUT")

    # Step 4: ExtRead again - must get 0x52 (NOT stale 0x46 from ExtWrite)
    r4 = send_clean(dev, CMD_EXT_READ,
                    bytes([BQ_ADDR_8BIT, CC_CFG, 0x01]))
    p4 = parse(r4)
    check("GUI: readback ExtRead gets 0x52 (not stale 0x46)",
          p4 is not None and p4["resp_code"] == RESP_EXT_READ,
          f"got 0x{p4['resp_code']:02X}" if p4 else "TIMEOUT")


# ── Section E: Buffer poisoning regression ────────────────────────────────────

def test_buffer_poisoning(dev):
    print("\n=== Section E: Buffer Poisoning Regression ===")
    print()

    # Test 1: I2CPower + ReadWord rapid-fire (no flush between)
    flush(dev)
    dev.write(b"\x00" + build(CMD_I2CPOWER, bytes([0x01])))
    time.sleep(0.02)
    dev.write(b"\x00" + build(CMD_READ_WORD, bytes([BQ_ADDR_7BIT, CC_CFG])))
    time.sleep(0.05)
    r = dev.read(BUF, 2000)
    p = parse(r)
    check("Rapid I2CPower+ReadWord: first response is 0x41",
          p is not None and p["resp_code"] == RESP_READ_WORD,
          f"got 0x{p['resp_code']:02X}" if p else "TIMEOUT")

    # Test 2: ExtWrite + ExtRead rapid-fire
    flush(dev)
    dev.write(b"\x00" + build(CMD_EXT_WRITE,
                              bytes([BQ_ADDR_8BIT, CC_CFG, 0x01, 0x19])))
    time.sleep(0.02)
    dev.write(b"\x00" + build(CMD_EXT_READ,
                              bytes([BQ_ADDR_8BIT, SYS_STAT, 0x01])))
    time.sleep(0.05)
    r = dev.read(BUF, 2000)
    p = parse(r)
    check("Rapid ExtWrite+ExtRead: first response is 0x52",
          p is not None and p["resp_code"] == RESP_EXT_READ,
          f"got 0x{p['resp_code']:02X}" if p else "TIMEOUT")

    # Test 3: Three silent commands back-to-back, then one read
    flush(dev)
    dev.write(b"\x00" + build(CMD_I2CPOWER, bytes([0x01])))
    time.sleep(0.02)
    dev.write(b"\x00" + build(CMD_WRITE_BYTE,
                              bytes([BQ_ADDR_7BIT, CC_CFG, 0x19])))
    time.sleep(0.02)
    dev.write(b"\x00" + build(CMD_EXT_WRITE,
                              bytes([BQ_ADDR_8BIT, CC_CFG, 0x01, 0x19])))
    time.sleep(0.02)
    dev.write(b"\x00" + build(CMD_READ_WORD,
                              bytes([BQ_ADDR_7BIT, SYS_STAT])))
    time.sleep(0.05)
    r = dev.read(BUF, 2000)
    p = parse(r)
    check("3x silent + ReadWord: response is 0x41 (no stale 0x46)",
          p is not None and p["resp_code"] == RESP_READ_WORD,
          f"got 0x{p['resp_code']:02X}" if p else "TIMEOUT")

    # Test 4: Verify no extra reports in buffer after silent cmds
    flush(dev)
    dev.write(b"\x00" + build(CMD_I2CPOWER, bytes([0x01])))
    time.sleep(0.02)
    dev.write(b"\x00" + build(CMD_EXT_WRITE,
                              bytes([BQ_ADDR_8BIT, CC_CFG, 0x01, 0x19])))
    time.sleep(0.2)
    dev.set_nonblocking(True)
    stale = dev.read(BUF)
    dev.set_nonblocking(False)
    check("No stale reports after 2 silent commands",
          stale is None or len(stale) == 0,
          f"got {len(stale)} bytes" if stale else "clean")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("EV2300 Protocol Compliance Test Suite")
    print("=" * 50)

    dev = hid.device()
    try:
        dev.open(VID, PID)
    except Exception as e:
        print(f"ERROR: Cannot open device VID=0x{VID:04X} PID=0x{PID:04X}: {e}")
        print("Is the STM32 bridge plugged in?")
        sys.exit(1)

    dev.set_nonblocking(False)
    print(f"Opened device VID=0x{VID:04X} PID=0x{PID:04X}")

    try:
        test_silent_commands(dev)
        test_response_codes(dev)
        test_dll_sequence(dev)
        test_gui_sequence(dev)
        test_buffer_poisoning(dev)
    finally:
        dev.close()

    print()
    print("=" * 50)
    total = _passed + _failed
    print(f"Results: {_passed}/{total} passed, {_failed} failed")

    if _failed > 0:
        print("\nFAILED TESTS DETECTED")
        sys.exit(1)
    else:
        print("\nALL TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
