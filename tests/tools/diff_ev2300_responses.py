#!/usr/bin/env python
"""
Dual-device response comparison: send identical commands to both the real
EV2300 and the STM32 bridge, then diff every response byte-for-byte.

Requires both devices connected simultaneously. Opens each with shared
access. Uses overlapped I/O with timeouts so non-responding commands
don't block.

Usage:
    python diff_ev2300_responses.py [--range 0x00-0x7F] [--json output.json]
"""
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
from datetime import datetime

VID, PID, BUF = 0x0451, 0x0036, 64
READ_TIMEOUT_MS = 1500

# ── CRC-8 ───────────────────────────────────────────────────────────────────
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

# ── Windows HID API ─────────────────────────────────────────────────────────
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
class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.POINTER(ctypes.c_ulong)),
                ("InternalHigh", ctypes.POINTER(ctypes.c_ulong)),
                ("Offset", wt.DWORD), ("OffsetHigh", wt.DWORD),
                ("hEvent", ctypes.c_void_p)]

hid = ctypes.windll.hid
sa = ctypes.windll.setupapi
k32 = ctypes.windll.kernel32
IV = ctypes.c_void_p(-1).value
DC = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 5
FILE_FLAG_OVERLAPPED = 0x40000000

# setupapi
sa.SetupDiGetClassDevsA.restype = ctypes.c_void_p
sa.SetupDiGetClassDevsA.argtypes = [ctypes.POINTER(GUID), ctypes.c_char_p,
                                     ctypes.c_void_p, wt.DWORD]
sa.SetupDiEnumDeviceInterfaces.restype = wt.BOOL
sa.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                            ctypes.POINTER(GUID), wt.DWORD,
                                            ctypes.POINTER(SP)]
sa.SetupDiGetDeviceInterfaceDetailA.restype = wt.BOOL
sa.SetupDiGetDeviceInterfaceDetailA.argtypes = [ctypes.c_void_p, ctypes.POINTER(SP),
                                                 ctypes.c_void_p, wt.DWORD,
                                                 ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
sa.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

# kernel32
k32.CreateFileA.restype = ctypes.c_void_p
k32.CreateFileA.argtypes = [ctypes.c_char_p, wt.DWORD, wt.DWORD, ctypes.c_void_p,
                             wt.DWORD, wt.DWORD, ctypes.c_void_p]
k32.CloseHandle.argtypes = [ctypes.c_void_p]
k32.CloseHandle.restype = wt.BOOL
k32.WriteFile.restype = wt.BOOL
k32.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
                           ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
k32.ReadFile.restype = wt.BOOL
k32.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
                          ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
k32.CreateEventA.restype = ctypes.c_void_p
k32.CreateEventA.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, ctypes.c_char_p]
k32.WaitForSingleObject.restype = wt.DWORD
k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wt.DWORD]
k32.GetOverlappedResult.restype = wt.BOOL
k32.GetOverlappedResult.argtypes = [ctypes.c_void_p, ctypes.POINTER(OVERLAPPED),
                                     ctypes.POINTER(wt.DWORD), wt.BOOL]
k32.CancelIo.restype = wt.BOOL
k32.CancelIo.argtypes = [ctypes.c_void_p]
k32.ResetEvent.restype = wt.BOOL
k32.ResetEvent.argtypes = [ctypes.c_void_p]

# hid
hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
hid.HidD_GetAttributes.restype = wt.BOOL
hid.HidD_GetAttributes.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
hid.HidD_SetNumInputBuffers.restype = wt.BOOL
hid.HidD_SetNumInputBuffers.argtypes = [ctypes.c_void_p, wt.ULONG]
hid.HidD_FlushQueue.restype = wt.BOOL
hid.HidD_FlushQueue.argtypes = [ctypes.c_void_p]
for fn in ("HidD_GetSerialNumberString",):
    f = getattr(hid, fn)
    f.restype = wt.BOOL
    f.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.ULONG]


# ── Device class ────────────────────────────────────────────────────────────
class HIDDevice:
    def __init__(self, path_bytes, serial, label):
        self.label = label
        self.serial = serial
        self.handle = k32.CreateFileA(
            path_bytes, 0xC0000000, 0x03, None, 3, FILE_FLAG_OVERLAPPED, None)
        if self.handle == IV:
            raise OSError(f"Cannot open {label} (error {ctypes.GetLastError()})")
        hid.HidD_SetNumInputBuffers(self.handle, 64)
        self.evt = k32.CreateEventA(None, True, False, None)

    def flush(self):
        hid.HidD_FlushQueue(self.handle)

    def send_recv(self, packet, timeout_ms=READ_TIMEOUT_MS):
        """Send 64-byte packet, read response with timeout. Returns bytes or None."""
        report = b"\x00" + bytes(packet[:BUF])
        report += b"\x00" * (65 - len(report))

        # Write (overlapped)
        ol_w = OVERLAPPED()
        ol_w.hEvent = self.evt
        k32.ResetEvent(self.evt)
        w = wt.DWORD()
        ok = k32.WriteFile(self.handle, report, 65, ctypes.byref(w), ctypes.byref(ol_w))
        if not ok:
            err = ctypes.GetLastError()
            if err == 997:  # IO_PENDING
                k32.WaitForSingleObject(self.evt, 5000)
                k32.GetOverlappedResult(self.handle, ctypes.byref(ol_w), ctypes.byref(w), False)
            else:
                return None

        # Read (overlapped with timeout)
        buf = ctypes.create_string_buffer(65)
        ol_r = OVERLAPPED()
        ol_r.hEvent = self.evt
        k32.ResetEvent(self.evt)
        rn = wt.DWORD()
        ok = k32.ReadFile(self.handle, buf, 65, ctypes.byref(rn), ctypes.byref(ol_r))
        if not ok:
            err = ctypes.GetLastError()
            if err == 997:  # IO_PENDING
                wait = k32.WaitForSingleObject(self.evt, timeout_ms)
                if wait == 0:  # WAIT_OBJECT_0
                    k32.GetOverlappedResult(self.handle, ctypes.byref(ol_r),
                                            ctypes.byref(rn), False)
                    raw = buf.raw[:rn.value]
                    return raw[1:] if len(raw) > 1 else None
                else:  # TIMEOUT
                    k32.CancelIo(self.handle)
                    return None
            return None
        raw = buf.raw[:rn.value]
        return raw[1:] if len(raw) > 1 else None

    def close(self):
        k32.CloseHandle(self.handle)
        k32.CloseHandle(self.evt)


def find_devices():
    """Find all VID/PID matching devices, classify as real vs STM32."""
    g = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(g))
    hi = sa.SetupDiGetClassDevsA(ctypes.byref(g), None, None, 0x12)
    if hi == IV:
        return []
    devices = []
    idx = 0
    while True:
        iface = SP()
        iface.cbSize = ctypes.sizeof(SP)
        if not sa.SetupDiEnumDeviceInterfaces(hi, None, ctypes.byref(g), idx, ctypes.byref(iface)):
            break
        d = DT()
        d.cbSize = DC
        r = wt.DWORD()
        sa.SetupDiGetDeviceInterfaceDetailA(hi, ctypes.byref(iface), ctypes.byref(d),
                                             ctypes.sizeof(d), ctypes.byref(r), None)
        idx += 1
        hdev = k32.CreateFileA(d.P, 0, 3, None, 3, 0, None)
        if hdev == IV:
            continue
        a = AT()
        a.S = ctypes.sizeof(AT)
        hid.HidD_GetAttributes(hdev, ctypes.byref(a))
        if a.V == VID and a.P == PID:
            buf = ctypes.create_unicode_buffer(256)
            serial = None
            if hid.HidD_GetSerialNumberString(hdev, buf, ctypes.sizeof(buf)):
                serial = buf.value
            devices.append({"path": d.P, "serial": serial})
        k32.CloseHandle(hdev)
    sa.SetupDiDestroyDeviceInfoList(hi)
    return devices


def build_packet(cmd, payload=b""):
    inner = bytes([cmd, 0, 0, 0, len(payload)]) + payload
    c = crc8(inner)
    frame = bytes([0xAA]) + inner + bytes([c, 0x55])
    pkt = bytes([len(frame)]) + frame
    pkt += b"\x00" * (BUF - len(pkt))
    return pkt


def parse_response(raw):
    """Parse a 64-byte response into a dict."""
    if raw is None:
        return {"resp_cmd": None, "status": "TIMEOUT", "payload": b"", "plen": 0}
    if len(raw) < 3 or raw[1] != 0xAA:
        return {"resp_cmd": None, "status": "BAD_FRAME", "payload": b"", "plen": 0,
                "raw": raw.hex()}
    resp_cmd = raw[2]
    plen = raw[6] if len(raw) > 6 else 0
    available = max(0, len(raw) - 7)
    actual = min(plen, available)
    payload = raw[7:7 + actual] if actual > 0 else b""
    is_error = (resp_cmd == 0x46)
    return {
        "resp_cmd": resp_cmd,
        "resp_hex": f"0x{resp_cmd:02X}",
        "status": "ERROR" if is_error else "OK",
        "plen": plen,
        "payload": payload,
        "payload_hex": " ".join(f"{b:02x}" for b in payload),
        "raw": raw[:max(9, 7 + actual + 2)].hex(),
    }


def main():
    cmd_start, cmd_end = 0x00, 0x7F
    json_path = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--range" and i + 1 < len(args):
            parts = args[i + 1].split("-")
            cmd_start = int(parts[0], 16)
            cmd_end = int(parts[1], 16) if len(parts) > 1 else cmd_start
            i += 2
        elif args[i] == "--json" and i + 1 < len(args):
            json_path = args[i + 1]
            i += 2
        else:
            i += 1

    print("EV2300 Dual-Device Response Comparator")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Command range: 0x{cmd_start:02X} - 0x{cmd_end:02X}")
    print()

    # Find both devices
    devs = find_devices()
    if len(devs) < 2:
        print(f"ERROR: Need 2 devices, found {len(devs)}. Connect both real EV2300 and STM32.")
        sys.exit(1)

    real_info = next((d for d in devs if d["serial"] and "2.0a" in d["serial"]), None)
    stm32_info = next((d for d in devs if d["serial"] and "2.0b" in d["serial"]), None)

    if not real_info or not stm32_info:
        # Fallback: first with TUSB3210 that isn't 2.0b is real
        for d in devs:
            s = d.get("serial", "") or ""
            if "TUSB3210" in s and "2.0b" not in s and not real_info:
                real_info = d
            elif "TUSB3210" in s and "2.0b" in s and not stm32_info:
                stm32_info = d
            elif not real_info:
                real_info = d
            elif not stm32_info:
                stm32_info = d

    if not real_info or not stm32_info:
        print("ERROR: Cannot identify real vs STM32 device.")
        for d in devs:
            print(f"  serial={d['serial']!r}")
        sys.exit(1)

    print(f"Real EV2300:  {real_info['serial']}")
    print(f"STM32 Bridge: {stm32_info['serial']}")
    print()

    real = HIDDevice(real_info["path"], real_info["serial"], "REAL")
    stm32 = HIDDevice(stm32_info["path"], stm32_info["serial"], "STM32")

    # Flush both
    real.flush()
    stm32.flush()
    time.sleep(0.3)

    results = []
    mismatches = []
    matches = 0

    print(f"{'CMD':<8} {'Real EV2300':<20} {'STM32 Bridge':<20} {'Match?'}")
    print("-" * 70)

    for cmd in range(cmd_start, cmd_end + 1):
        # Skip write commands that could change state
        if cmd in (0x04, 0x05, 0x06, 0x07, 0x80):
            continue

        # Build packet (no I2C payload for undocumented cmds)
        if cmd in (0x01, 0x08, 0x09):
            pkt = build_packet(cmd, bytes([0x10, 0x00]))  # addr=0x10, reg=0x00
        elif cmd == 0x02:
            pkt = build_packet(cmd, bytes([0x10, 0x00, 0x04]))
        elif cmd == 0x03:
            pkt = build_packet(cmd, bytes([0x10, 0x00]))
        else:
            pkt = build_packet(cmd)

        # Send to both
        real_raw = real.send_recv(pkt)
        time.sleep(0.05)
        stm32_raw = stm32.send_recv(pkt)
        time.sleep(0.05)

        real_p = parse_response(real_raw)
        stm32_p = parse_response(stm32_raw)

        # Compare response command code (the most important byte)
        real_rc = real_p.get("resp_hex", "TIMEOUT")
        stm32_rc = stm32_p.get("resp_hex", "TIMEOUT")
        if real_p["resp_cmd"] is None:
            real_rc = real_p["status"]
        if stm32_p["resp_cmd"] is None:
            stm32_rc = stm32_p["status"]

        # Match on response code
        match = (real_p["resp_cmd"] == stm32_p["resp_cmd"])
        # Also check payload match for non-error responses
        payload_match = (real_p["payload"] == stm32_p["payload"])

        status = "OK" if match else "** MISMATCH **"
        if match and not payload_match and real_p["status"] != "TIMEOUT":
            status = "resp OK, payload differs"

        if match:
            matches += 1

        result = {
            "cmd": f"0x{cmd:02X}",
            "real": {"resp": real_rc, "plen": real_p["plen"],
                     "payload": real_p.get("payload_hex", ""),
                     "raw": real_p.get("raw", "")},
            "stm32": {"resp": stm32_rc, "plen": stm32_p["plen"],
                      "payload": stm32_p.get("payload_hex", ""),
                      "raw": stm32_p.get("raw", "")},
            "match": match,
            "payload_match": payload_match,
        }
        results.append(result)
        if not match:
            mismatches.append(result)

        # Print line
        real_str = f"{real_rc:<6} p={real_p['plen']}"
        stm32_str = f"{stm32_rc:<6} p={stm32_p['plen']}"
        print(f"  0x{cmd:02X}   {real_str:<20} {stm32_str:<20} {status}")

    real.close()
    stm32.close()

    # Summary
    total = len(results)
    print()
    print("=" * 70)
    print(f"SUMMARY: {matches}/{total} match, {len(mismatches)} mismatches")
    print("=" * 70)

    if mismatches:
        print()
        print("MISMATCHED COMMANDS (these need firmware fixes):")
        print(f"{'CMD':<8} {'Real':<10} {'STM32':<10} {'Real payload':<30} {'STM32 payload'}")
        print("-" * 85)
        for m in mismatches:
            print(f"  {m['cmd']:<6} {m['real']['resp']:<10} {m['stm32']['resp']:<10} "
                  f"{m['real']['payload'][:28]:<30} {m['stm32']['payload'][:28]}")

    # Save
    output = {
        "timestamp": datetime.now().isoformat(),
        "real_serial": real_info["serial"],
        "stm32_serial": stm32_info["serial"],
        "total": total,
        "matches": matches,
        "mismatches_count": len(mismatches),
        "results": results,
        "mismatches": mismatches,
    }
    out_path = json_path or "diff_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
