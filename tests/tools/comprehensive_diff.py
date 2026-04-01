#!/usr/bin/env python
"""
Comprehensive dual-device protocol comparison.
Tests reads at multiple I2C addresses, write sequences, and init commands.
"""
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
from datetime import datetime

VID, PID, BUF = 0x0451, 0x0036, 64
TMO = 2000
FILE_FLAG_OVERLAPPED = 0x40000000

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

    def sr(self, pkt, tmo=TMO):
        rpt = b"\x00" + bytes(pkt[:BUF])
        rpt += b"\x00" * (65 - len(rpt))
        ol = OL()
        ol.hE = self.e
        k32.ResetEvent(self.e)
        w = wt.DWORD()
        ok = k32.WriteFile(self.h, rpt, 65, ctypes.byref(w), ctypes.byref(ol))
        if not ok:
            if ctypes.GetLastError() == 997:
                k32.WaitForSingleObject(self.e, 5000)
                k32.GetOverlappedResult(self.h, ctypes.byref(ol), ctypes.byref(w), False)
            else:
                return None
        buf2 = ctypes.create_string_buffer(65)
        ol2 = OL()
        ol2.hE = self.e
        k32.ResetEvent(self.e)
        rn = wt.DWORD()
        ok = k32.ReadFile(self.h, buf2, 65, ctypes.byref(rn), ctypes.byref(ol2))
        if not ok:
            if ctypes.GetLastError() == 997:
                w2 = k32.WaitForSingleObject(self.e, tmo)
                if w2 == 0:
                    k32.GetOverlappedResult(self.h, ctypes.byref(ol2), ctypes.byref(rn), False)
                    raw = buf2.raw[:rn.value]
                    return raw[1:] if len(raw) > 1 else None
                else:
                    k32.CancelIo(self.h)
                    return None
            return None
        raw = buf2.raw[:rn.value]
        return raw[1:] if len(raw) > 1 else None

    def close(self):
        k32.CloseHandle(self.h)
        k32.CloseHandle(self.e)


def build(cmd, payload=b""):
    inner = bytes([cmd, 0, 0, 0, len(payload)]) + payload
    c = crc8(inner)
    frame = bytes([0xAA]) + inner + bytes([c, 0x55])
    pkt = bytes([len(frame)]) + frame + b"\x00" * (BUF - 1 - len(frame))
    return pkt


def fmt(raw, n=30):
    if raw is None:
        return "TIMEOUT"
    return " ".join(f"{b:02x}" for b in raw[:n])


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
    time.sleep(0.3)

    results = []

    def test(label, cmd, payload=b""):
        pkt = build(cmd, payload)
        rr = real.sr(pkt)
        time.sleep(0.05)
        sr = stm.sr(pkt)
        time.sleep(0.05)
        # Compare response cmd byte
        r_cmd = rr[2] if rr and len(rr) > 2 and rr[1] == 0xAA else None
        s_cmd = sr[2] if sr and len(sr) > 2 and sr[1] == 0xAA else None
        both_timeout = (rr is None and sr is None)
        cmd_match = (r_cmd == s_cmd) or both_timeout
        tag = "OK" if cmd_match else "** DIFF **"
        print(f"  {label:<50} {tag}")
        print(f"    REAL:  {fmt(rr)}")
        print(f"    STM32: {fmt(sr)}")
        results.append({
            "label": label,
            "real": fmt(rr, 64),
            "stm32": fmt(sr, 64),
            "real_cmd": f"0x{r_cmd:02X}" if r_cmd is not None else ("TIMEOUT" if rr is None else "BAD"),
            "stm32_cmd": f"0x{s_cmd:02X}" if s_cmd is not None else ("TIMEOUT" if sr is None else "BAD"),
            "match": cmd_match,
        })

    def test_write(label, wcmd, wpayload):
        """Test write ack + submit for both devices."""
        print(f"  --- {label} ---")
        for dev in [real, stm]:
            ack = dev.sr(build(wcmd, wpayload))
            time.sleep(0.05)
            sub = dev.sr(build(0x80))
            time.sleep(0.1)
            print(f"    {dev.lbl:<6} ack:    {fmt(ack)}")
            print(f"    {dev.lbl:<6} submit: {fmt(sub)}")
        results.append({
            "label": f"WRITE {label}",
            "note": "see console output for ack+submit details"
        })

    print("=" * 70)
    print("COMPREHENSIVE EV2300 PROTOCOL COMPARISON")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 70)

    # 1. READ_WORD at multiple I2C addresses
    print("\n--- READ_WORD (0x01) at various I2C addresses ---")
    addrs = [
        ("0x08 (BQ non-CRC)", 0x10),
        ("0x18 (BQ CRC)", 0x30),
        ("0x00 (broadcast)", 0x00),
        ("0x50 (EEPROM)", 0xA0),
        ("0x7F (max)", 0xFE),
    ]
    for aname, addr in addrs:
        for reg in [0x00, 0x0B]:
            test(f"READ_WORD addr={aname} reg=0x{reg:02X}", 0x01, bytes([addr, reg]))

    # 2. READ_BYTE at multiple addresses
    print("\n--- READ_BYTE (0x03) ---")
    for aname, addr in [("0x08 non-CRC", 0x10), ("0x18 CRC", 0x30)]:
        for reg in [0x00, 0x04, 0x0B]:
            test(f"READ_BYTE addr={aname} reg=0x{reg:02X}", 0x03, bytes([addr, reg]))

    # 3. READ_BLOCK
    print("\n--- READ_BLOCK (0x02) ---")
    test("READ_BLOCK addr=0x10 reg=0x00 len=4", 0x02, bytes([0x10, 0x00, 0x04]))
    test("READ_BLOCK addr=0x10 reg=0x00 len=16", 0x02, bytes([0x10, 0x00, 0x10]))

    # 4. Write sequences
    print("\n--- WRITE sequences (ack + submit) ---")
    test_write("WRITE_WORD(0x04) CC_CFG=0x19", 0x04, bytes([0x10, 0x0B, 0x19, 0x00]))
    test_write("WRITE_BYTE(0x07) CC_CFG=0x19", 0x07, bytes([0x10, 0x0B, 0x19]))
    test_write("WRITE_BLOCK(0x05) CC_CFG", 0x05, bytes([0x10, 0x0B, 0x01, 0x19]))
    test_write("SEND_BYTE(0x06)", 0x06, bytes([0x10, 0x0B]))
    test_write("WRITE_WORD(0x04) SYS_CTRL1=0x00", 0x04, bytes([0x10, 0x04, 0x00, 0x00]))
    test_write("WRITE_WORD CRC addr(0x30)", 0x04, bytes([0x30, 0x0B, 0x19, 0x00]))

    # 5. SUBMIT alone
    print("\n--- SUBMIT alone ---")
    test("SUBMIT (0x80) no pending write", 0x80)

    # 6. Key init/undocumented commands
    print("\n--- Init/undocumented commands ---")
    for cmd in [0x00, 0x08, 0x09, 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x12, 0x13,
                0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C,
                0x1D, 0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x30, 0x70]:
        test(f"CMD 0x{cmd:02X}", cmd)

    real.close()
    stm.close()

    with open("comprehensive_diff.json", "w") as f:
        json.dump({"timestamp": datetime.now().isoformat(), "results": results}, f, indent=2)

    diffs = [r for r in results if "match" in r and not r["match"]]
    total = len([r for r in results if "match" in r])
    print(f"\nTotal: {total}, Match: {total - len(diffs)}, Diff: {len(diffs)}")
    if diffs:
        print("\nDIFFS:")
        for d in diffs:
            print(f"  {d['label']}: real={d['real_cmd']} stm32={d['stm32_cmd']}")
    print(f"\nSaved to comprehensive_diff.json")


if __name__ == "__main__":
    main()
