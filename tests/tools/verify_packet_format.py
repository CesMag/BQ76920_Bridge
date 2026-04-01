#!/usr/bin/env python
"""
Verify firmware packet format against real EV2300 captures.
Computes expected packet bytes for each response type and compares
to the raw captures from write_diff.py and read_format_diff.py.

This script does NOT talk to hardware — it's a pure math verification.
"""

_T = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = ((_c << 1) ^ 0x07) & 0xFF if _c & 0x80 else (_c << 1) & 0xFF
    _T.append(_c)

def crc8(d):
    c = 0
    for b in d:
        c = _T[c ^ b]
    return c


def build_response(resp_code, payload, crc_skip_tail=0):
    """Build a response packet the way the FIXED firmware should."""
    plen = len(payload)
    total_len = plen + 8  # FIX #1: was plen + 9

    pkt = [0] * 64
    pkt[0] = total_len
    pkt[1] = 0xAA
    pkt[2] = resp_code
    pkt[3] = 0x00
    pkt[4] = 0x00
    pkt[5] = 0x01
    pkt[6] = plen
    for i, b in enumerate(payload):
        pkt[7 + i] = b

    crc_pos = 7 + plen
    crc_len = 5 + plen - crc_skip_tail  # FIX #5: exclude addr from CRC
    crc_val = crc8(pkt[2:2 + crc_len])
    pkt[crc_pos] = crc_val
    pkt[crc_pos + 1] = 0x55

    return pkt


def fmt(pkt, n=15):
    return " ".join(f"{b:02x}" for b in pkt[:n])


def verify(label, built, real_hex, check_bytes=None):
    """Compare built packet against real EV2300 capture."""
    real = [int(x, 16) for x in real_hex.split()]
    n = len(real)
    match = all(built[i] == real[i] for i in range(n))

    status = "PASS" if match else "FAIL"
    print(f"  [{status}] {label}")
    if not match:
        print(f"    Built: {fmt(built, n)}")
        print(f"    Real:  {real_hex}")
        for i in range(n):
            if built[i] != real[i]:
                print(f"    DIFF at [{i}]: built=0x{built[i]:02X} real=0x{real[i]:02X}")
    return match


def main():
    passed = 0
    failed = 0

    print("=" * 70)
    print("PACKET FORMAT VERIFICATION vs REAL EV2300 CAPTURES")
    print("=" * 70)

    # ─── FIX #1: totalLen = N+8 (was N+9) ───────────────────────────

    print("\n--- FIX #1: totalLen = plen + 8 ---")

    # Write ack: resp=0x46, payload={reg, 0x93}, crc_skip=0
    pkt = build_response(0x46, [0x0B, 0x93], crc_skip_tail=0)
    r = verify("WRITE_WORD ack CC_CFG", pkt, "0a aa 46 00 00 01 02 0b 93 2e 55")
    passed += r; failed += (not r)

    # Submit success: resp=0xC0, payload={0x33, 0x31, 0x6D}, crc_skip=0
    pkt = build_response(0xC0, [0x33, 0x31, 0x6D], crc_skip_tail=0)
    r = verify("SUBMIT success", pkt, "0b aa c0 00 00 01 03 33 31 6d 8f 55")
    passed += r; failed += (not r)

    # Error response: resp=0x46, payload={0x00, 0x93}, crc_skip=0
    pkt = build_response(0x46, [0x00, 0x93], crc_skip_tail=0)
    r = verify("Generic error {0x00, 0x93}", pkt, "0a aa 46 00 00 01 02 00 93 b9 55")
    passed += r; failed += (not r)

    # ─── FIX #2: READ_WORD payload = {reg, lo, hi, addr7} ───────────

    print("\n--- FIX #2: READ_WORD format {reg, lo, hi, addr7} plen=4 ---")

    # READ_WORD SYS_STAT: reg=0x00, val=0x0000, addr7=0x08
    # Note: real BQ board had val=0x0000 for these regs at capture time
    pkt = build_response(0x41, [0x00, 0x00, 0x00, 0x08], crc_skip_tail=1)
    r = verify("READ_WORD SYS_STAT", pkt, "0c aa 41 00 00 01 04 00 00 00 08 f5 55")
    passed += r; failed += (not r)

    pkt = build_response(0x41, [0x04, 0x00, 0x00, 0x08], crc_skip_tail=1)
    r = verify("READ_WORD SYS_CTRL1", pkt, "0c aa 41 00 00 01 04 04 00 00 08 5e 55")
    passed += r; failed += (not r)

    pkt = build_response(0x41, [0x06, 0x00, 0x00, 0x08], crc_skip_tail=1)
    r = verify("READ_WORD PROTECT1", pkt, "0c aa 41 00 00 01 04 06 00 00 08 88 55")
    passed += r; failed += (not r)

    pkt = build_response(0x41, [0x0B, 0x00, 0x00, 0x08], crc_skip_tail=1)
    r = verify("READ_WORD CC_CFG (val=0)", pkt, "0c aa 41 00 00 01 04 0b 00 00 08 19 55")
    passed += r; failed += (not r)

    # ─── FIX #5: CRC excludes addr for success responses ────────────

    print("\n--- FIX #5: CRC verification ---")

    # CMD 0x0D response: {0x02, 0x00, 0x08}, crc_skip=1 (addr=0x08)
    pkt = build_response(0x4E, [0x02, 0x00, 0x08], crc_skip_tail=1)
    r = verify("CMD 0x0D response", pkt, "0b aa 4e 00 00 01 03 02 00 08 e2 55")
    passed += r; failed += (not r)

    # READ_BLOCK: {0x02, 0x00, 0x08}, crc_skip=1
    pkt = build_response(0x42, [0x02, 0x00, 0x08], crc_skip_tail=1)
    r = verify("READ_BLOCK short", pkt, "0b aa 42 00 00 01 03 02 00 08 7d 55")
    passed += r; failed += (not r)

    # Write ack SYS_CTRL1: {0x04, 0x93}, crc_skip=0 (no addr in error)
    pkt = build_response(0x46, [0x04, 0x93], crc_skip_tail=0)
    r = verify("WRITE_WORD ack SYS_CTRL1", pkt, "0a aa 46 00 00 01 02 04 93 ed 55")
    passed += r; failed += (not r)

    # SEND_BYTE ack: {0x00, 0x93}, crc_skip=0
    pkt = build_response(0x46, [0x00, 0x93], crc_skip_tail=0)
    r = verify("SEND_BYTE ack", pkt, "0a aa 46 00 00 01 02 00 93 b9 55")
    passed += r; failed += (not r)

    # ─── FIX #3: WRITE_BYTE -> no response (verified by observation) ─

    print("\n--- FIX #3: WRITE_BYTE = no response ---")
    print("  [INFO] Real EV2300 WRITE_BYTE (0x07) returns TIMEOUT (no response)")
    print("  [INFO] Firmware must NOT send any HID report for WRITE_BYTE ack")
    print("  [INFO] SUBMIT after WRITE_BYTE still returns 0xC0 success")

    # ─── FIX #4: SUBMIT always returns 0xC0 ──────────────────────────

    print("\n--- FIX #4: SUBMIT always 0xC0 success ---")
    print("  [INFO] Real EV2300 returns 0xC0 + {0x33, 0x31, 0x6D} even on I2C NACK")
    print("  [INFO] Verified: SUBMIT to invalid addr 0xFE -> 0xC0 on real EV2300")
    pkt = build_response(0xC0, [0x33, 0x31, 0x6D], crc_skip_tail=0)
    r = verify("SUBMIT (always success)", pkt, "0b aa c0 00 00 01 03 33 31 6d 8f 55")
    passed += r; failed += (not r)

    # ─── Summary ──────────────────────────────────────────────────────

    print(f"\n{'=' * 70}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed}")
    if failed == 0:
        print("ALL VERIFICATIONS PASSED - firmware packet format matches real EV2300")
    else:
        print("FAILURES DETECTED - check diffs above")
    print(f"{'=' * 70}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit(main())
