#!/usr/bin/env python
"""
Full protocol sweep: send every command 0x00-0x7F to BOTH devices with
proper flushing between each command to prevent desync.

Also tests write sequences (WRITE + SUBMIT) and reads at multiple
I2C addresses.

Each test: flush -> send -> read with timeout -> record -> flush again.
"""
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
from datetime import datetime

VID, PID, BUF = 0x0451, 0x0036, 64
TMO = 1500  # ms per read
FLUSH_WAIT = 0.15  # seconds after flush
FILE_FLAG_OVERLAPPED = 0x40000000

# CRC-8
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

# ── Windows HID boilerplate ─────────────────────────────────────────────────

class GUID(ctypes.Structure):
    _fields_ = [("D1", ctypes.c_ulong), ("D2", ctypes.c_ushort),
                ("D3", ctypes.c_ushort), ("D4", ctypes.c_ubyte * 8)]
class SP(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("G", GUID), ("F", wt.DWORD),
                ("R", ctypes.POINTER(ctypes.c_ulong))]
class DT(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("P", ctypes.c_char * 512)]
class AT(ctypes.Structure):
    _fields_ = [("S", wt.ULONG), ("V", ctypes.c_ushort),
                ("P", ctypes.c_ushort), ("N", ctypes.c_ushort)]
class OL(ctypes.Structure):
    _fields_ = [("I", ctypes.POINTER(ctypes.c_ulong)),
                ("IH", ctypes.POINTER(ctypes.c_ulong)),
                ("O", wt.DWORD), ("OH", wt.DWORD), ("hE", ctypes.c_void_p)]

hid = ctypes.windll.hid
sa = ctypes.windll.setupapi
k32 = ctypes.windll.kernel32
IV = ctypes.c_void_p(-1).value
DC = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 5

# Setup API types
sa.SetupDiGetClassDevsA.restype = ctypes.c_void_p
sa.SetupDiGetClassDevsA.argtypes = [ctypes.POINTER(GUID), ctypes.c_char_p, ctypes.c_void_p, wt.DWORD]
sa.SetupDiEnumDeviceInterfaces.restype = wt.BOOL
sa.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID), wt.DWORD, ctypes.POINTER(SP)]
sa.SetupDiGetDeviceInterfaceDetailA.restype = wt.BOOL
sa.SetupDiGetDeviceInterfaceDetailA.argtypes = [ctypes.c_void_p, ctypes.POINTER(SP), ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
sa.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
k32.CreateFileA.restype = ctypes.c_void_p
k32.CreateFileA.argtypes = [ctypes.c_char_p, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]
k32.CloseHandle.argtypes = [ctypes.c_void_p]
k32.CloseHandle.restype = wt.BOOL
k32.WriteFile.restype = wt.BOOL
k32.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
k32.ReadFile.restype = wt.BOOL
k32.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
k32.CreateEventA.restype = ctypes.c_void_p
k32.CreateEventA.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, ctypes.c_char_p]
k32.WaitForSingleObject.restype = wt.DWORD
k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wt.DWORD]
k32.GetOverlappedResult.restype = wt.BOOL
k32.GetOverlappedResult.argtypes = [ctypes.c_void_p, ctypes.POINTER(OL), ctypes.POINTER(wt.DWORD), wt.BOOL]
k32.CancelIo.restype = wt.BOOL
k32.CancelIo.argtypes = [ctypes.c_void_p]
k32.ResetEvent.restype = wt.BOOL
k32.ResetEvent.argtypes = [ctypes.c_void_p]
hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
hid.HidD_GetAttributes.restype = wt.BOOL
hid.HidD_GetAttributes.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
hid.HidD_SetNumInputBuffers.restype = wt.BOOL
hid.HidD_SetNumInputBuffers.argtypes = [ctypes.c_void_p, wt.ULONG]
hid.HidD_FlushQueue.restype = wt.BOOL
hid.HidD_FlushQueue.argtypes = [ctypes.c_void_p]
hid.HidD_GetSerialNumberString.restype = wt.BOOL
hid.HidD_GetSerialNumberString.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.ULONG]


# ── Device class with proper flush ──────────────────────────────────────────

class Dev:
    def __init__(self, path, label):
        self.lbl = label
        self.h = k32.CreateFileA(path, 0xC0000000, 3, None, 3, FILE_FLAG_OVERLAPPED, None)
        if self.h == IV:
            raise OSError(f"open {label} err={ctypes.GetLastError()}")
        hid.HidD_SetNumInputBuffers(self.h, 64)
        self.e = k32.CreateEventA(None, True, False, None)

    def flush(self):
        hid.HidD_FlushQueue(self.h)
        time.sleep(FLUSH_WAIT)

    def send_recv(self, pkt, tmo=TMO):
        """Send packet and read response with timeout. Returns raw bytes or None."""
        rpt = b"\x00" + bytes(pkt[:BUF])
        rpt += b"\x00" * (65 - len(rpt))

        # Write
        ol = OL()
        ol.hE = self.e
        k32.ResetEvent(self.e)
        w = wt.DWORD()
        ok = k32.WriteFile(self.h, rpt, 65, ctypes.byref(w), ctypes.byref(ol))
        if not ok:
            err = ctypes.GetLastError()
            if err == 997:
                k32.WaitForSingleObject(self.e, 5000)
                k32.GetOverlappedResult(self.h, ctypes.byref(ol), ctypes.byref(w), False)
            else:
                return None

        # Read with timeout
        buf = ctypes.create_string_buffer(65)
        ol2 = OL()
        ol2.hE = self.e
        k32.ResetEvent(self.e)
        rn = wt.DWORD()
        ok = k32.ReadFile(self.h, buf, 65, ctypes.byref(rn), ctypes.byref(ol2))
        if not ok:
            err = ctypes.GetLastError()
            if err == 997:
                w2 = k32.WaitForSingleObject(self.e, tmo)
                if w2 == 0:
                    k32.GetOverlappedResult(self.h, ctypes.byref(ol2), ctypes.byref(rn), False)
                    raw = buf.raw[:rn.value]
                    return raw[1:] if len(raw) > 1 else None
                else:
                    k32.CancelIo(self.h)
                    return None
            return None
        raw = buf.raw[:rn.value]
        return raw[1:] if len(raw) > 1 else None

    def clean_send_recv(self, pkt, tmo=TMO):
        """Flush, send, recv, flush again. Guarantees no stale data."""
        self.flush()
        result = self.send_recv(pkt, tmo)
        return result

    def close(self):
        k32.CloseHandle(self.h)
        k32.CloseHandle(self.e)


def find_devices():
    g = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(g))
    hi = sa.SetupDiGetClassDevsA(ctypes.byref(g), None, None, 0x12)
    devs = []
    idx = 0
    while True:
        i2 = SP()
        i2.cbSize = ctypes.sizeof(SP)
        if not sa.SetupDiEnumDeviceInterfaces(hi, None, ctypes.byref(g), idx, ctypes.byref(i2)):
            break
        d = DT()
        d.cbSize = DC
        r = wt.DWORD()
        sa.SetupDiGetDeviceInterfaceDetailA(hi, ctypes.byref(i2), ctypes.byref(d),
                                             ctypes.sizeof(d), ctypes.byref(r), None)
        idx += 1
        h2 = k32.CreateFileA(d.P, 0, 3, None, 3, 0, None)
        if h2 == IV:
            continue
        a = AT()
        a.S = ctypes.sizeof(AT)
        hid.HidD_GetAttributes(h2, ctypes.byref(a))
        if a.V == VID and a.P == PID:
            buf = ctypes.create_unicode_buffer(256)
            s = None
            if hid.HidD_GetSerialNumberString(h2, buf, ctypes.sizeof(buf)):
                s = buf.value
            devs.append({"path": d.P, "serial": s})
        k32.CloseHandle(h2)
    sa.SetupDiDestroyDeviceInfoList(hi)
    return devs


def build(cmd, payload=b""):
    inner = bytes([cmd, 0, 0, 0, len(payload)]) + payload
    c = crc8(inner)
    frame = bytes([0xAA]) + inner + bytes([c, 0x55])
    pkt = bytes([len(frame)]) + frame + b"\x00" * (BUF - 1 - len(frame))
    return pkt


def parse(raw):
    """Parse raw HID response into structured dict."""
    if raw is None:
        return {"resp": None, "status": "TIMEOUT", "plen": 0, "payload": "",
                "reserved": "", "raw": ""}
    hexstr = " ".join(f"{b:02x}" for b in raw[:30])
    if len(raw) < 3 or raw[1] != 0xAA:
        return {"resp": None, "status": "BAD_FRAME", "plen": 0, "payload": "",
                "reserved": "", "raw": hexstr}
    resp = raw[2]
    rsv = f"{raw[3]:02x} {raw[4]:02x} {raw[5]:02x}" if len(raw) > 5 else ""
    plen = raw[6] if len(raw) > 6 else 0
    avail = max(0, len(raw) - 7)
    actual = min(plen, avail)
    payload = " ".join(f"{b:02x}" for b in raw[7:7+actual]) if actual > 0 else ""
    return {
        "resp": f"0x{resp:02X}",
        "resp_int": resp,
        "status": "ERROR" if resp == 0x46 else "OK",
        "plen": plen,
        "payload": payload,
        "reserved": rsv,
        "raw": hexstr,
    }


def main():
    devs = find_devices()
    ri = next((d for d in devs if d["serial"] and "2.0a" in d["serial"]), None)
    si = next((d for d in devs if d["serial"] and "2.0b" in d["serial"]), None)
    if not ri or not si:
        print(f"Need both devices. Found: {[d['serial'] for d in devs]}")
        sys.exit(1)

    real = Dev(ri["path"], "REAL")
    stm = Dev(si["path"], "STM32")
    real.flush()
    stm.flush()
    time.sleep(0.5)

    results = []
    print("=" * 80)
    print("FULL EV2300 PROTOCOL SWEEP (with flush between every command)")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Real: {ri['serial']}")
    print(f"STM32: {si['serial']}")
    print("=" * 80)

    # ── SECTION 1: All commands 0x00-0x7F (no payload) ──────────────────────
    print(f"\n{'CMD':<7} {'Real resp':<10} {'STM32 resp':<10} {'Real rsv':<12} {'STM32 rsv':<12} {'Match':<10} {'Real payload':<25} {'STM32 payload'}")
    print("-" * 120)

    for cmd in range(0x00, 0x80):
        # Skip write commands - tested separately
        if cmd in (0x04, 0x05, 0x06, 0x07, 0x80):
            continue

        pkt = build(cmd)
        rr = real.clean_send_recv(pkt)
        sr = stm.clean_send_recv(pkt)

        rp = parse(rr)
        sp = parse(sr)

        resp_match = (rp["resp"] == sp["resp"])
        both_timeout = (rr is None and sr is None)
        match = resp_match or both_timeout
        tag = "OK" if match else "DIFF"

        r = {
            "cmd": f"0x{cmd:02X}",
            "real": rp,
            "stm32": sp,
            "resp_match": match,
        }
        results.append(r)

        marker = "  " if match else ">>"
        print(f"{marker}0x{cmd:02X}  {rp['resp'] or 'TIMEOUT':<10} {sp['resp'] or 'TIMEOUT':<10} "
              f"{rp['reserved']:<12} {sp['reserved']:<12} {tag:<10} "
              f"{rp['payload'][:24]:<25} {sp['payload'][:24]}")

    # ── SECTION 2: Read commands at multiple I2C addresses ──────────────────
    print("\n" + "=" * 80)
    print("READ COMMANDS AT VARIOUS I2C ADDRESSES")
    print("=" * 80)
    print(f"{'Test':<50} {'Real':<12} {'STM32':<12} {'Match'}")
    print("-" * 90)

    read_tests = []
    for addr_name, addr in [("0x08(no-CRC)", 0x10), ("0x18(CRC)", 0x30),
                             ("0x00(bcast)", 0x00), ("0x50(EEPROM)", 0xA0)]:
        for cmd_name, cmd in [("READ_WORD", 0x01), ("READ_BYTE", 0x03), ("READ_BLOCK", 0x02)]:
            for reg in [0x00, 0x04, 0x0B]:
                if cmd == 0x02:
                    payload = bytes([addr, reg, 0x04])
                else:
                    payload = bytes([addr, reg])
                pkt = build(cmd, payload)
                rr = real.clean_send_recv(pkt)
                sr = stm.clean_send_recv(pkt)
                rp = parse(rr)
                sp = parse(sr)
                match = (rp["resp"] == sp["resp"]) or (rr is None and sr is None)
                label = f"{cmd_name} addr={addr_name} reg=0x{reg:02X}"
                marker = "  " if match else ">>"
                print(f"{marker}{label:<48} {rp['resp'] or 'TMO':<12} {sp['resp'] or 'TMO':<12} {'OK' if match else 'DIFF'}")
                read_tests.append({"label": label, "real": rp, "stm32": sp, "match": match})

    # ── SECTION 3: Write sequences ──────────────────────────────────────────
    print("\n" + "=" * 80)
    print("WRITE SEQUENCES (cmd + SUBMIT)")
    print("=" * 80)

    write_tests = []
    for wlabel, wcmd, wpayload in [
        ("WRITE_WORD(0x04) reg=0x0B val=0x19", 0x04, bytes([0x10, 0x0B, 0x19, 0x00])),
        ("WRITE_BYTE(0x07) reg=0x0B val=0x19", 0x07, bytes([0x10, 0x0B, 0x19])),
        ("WRITE_BLOCK(0x05) reg=0x0B", 0x05, bytes([0x10, 0x0B, 0x01, 0x19])),
        ("SEND_BYTE(0x06) reg=0x0B", 0x06, bytes([0x10, 0x0B])),
        ("WRITE_WORD(0x04) CRC addr=0x30", 0x04, bytes([0x30, 0x0B, 0x19, 0x00])),
    ]:
        print(f"\n  --- {wlabel} ---")
        wr = {}
        for dev in [real, stm]:
            dev.flush()
            ack = dev.send_recv(build(wcmd, wpayload))
            time.sleep(0.05)
            sub = dev.send_recv(build(0x80))
            dev.flush()
            ap = parse(ack)
            sp = parse(sub)
            print(f"    {dev.lbl:<6} ack:    resp={ap['resp'] or 'TMO':<8} rsv={ap['reserved']:<12} p={ap['plen']} {ap['payload'][:30]}")
            print(f"    {dev.lbl:<6} submit: resp={sp['resp'] or 'TMO':<8} rsv={sp['reserved']:<12} p={sp['plen']} {sp['payload'][:30]}")
            wr[dev.lbl] = {"ack": ap, "submit": sp}
        write_tests.append({"label": wlabel, "real": wr.get("REAL"), "stm32": wr.get("STM32")})

    # ── SECTION 4: SUBMIT edge cases ───────────────────────────────────────
    print("\n" + "=" * 80)
    print("SUBMIT EDGE CASES")
    print("=" * 80)

    submit_tests = []
    for slabel in ["SUBMIT alone (no pending)", "SUBMIT again (double)"]:
        print(f"\n  --- {slabel} ---")
        for dev in [real, stm]:
            dev.flush()
            r = dev.send_recv(build(0x80))
            rp = parse(r)
            print(f"    {dev.lbl:<6} resp={rp['resp'] or 'TMO':<8} rsv={rp['reserved']:<12} p={rp['plen']} {rp['payload'][:30]}")
            submit_tests.append({"label": slabel, "device": dev.lbl, **rp})

    real.close()
    stm.close()

    # ── Summary ─────────────────────────────────────────────────────────────
    cmd_diffs = [r for r in results if not r["resp_match"]]
    read_diffs = [r for r in read_tests if not r["match"]]

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Command sweep (0x00-0x7F): {len(results) - len(cmd_diffs)}/{len(results)} match, {len(cmd_diffs)} diffs")
    print(f"Read address tests: {len(read_tests) - len(read_diffs)}/{len(read_tests)} match, {len(read_diffs)} diffs")

    if cmd_diffs:
        print(f"\nCommand mismatches:")
        for d in cmd_diffs:
            r, s = d["real"], d["stm32"]
            print(f"  {d['cmd']}: real={r['resp'] or 'TMO'} stm32={s['resp'] or 'TMO'}  "
                  f"real_payload=[{r['payload'][:30]}] stm32_payload=[{s['payload'][:30]}]")

    # Save everything
    output = {
        "timestamp": datetime.now().isoformat(),
        "real_serial": ri["serial"],
        "stm32_serial": si["serial"],
        "command_sweep": results,
        "read_tests": read_tests,
        "write_tests": write_tests,
        "submit_tests": submit_tests,
        "summary": {
            "cmd_total": len(results),
            "cmd_match": len(results) - len(cmd_diffs),
            "cmd_diffs": len(cmd_diffs),
            "read_total": len(read_tests),
            "read_match": len(read_tests) - len(read_diffs),
        }
    }
    with open("full_sweep_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to full_sweep_results.json")


if __name__ == "__main__":
    main()
