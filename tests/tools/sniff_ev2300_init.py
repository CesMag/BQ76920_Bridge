#!/usr/bin/env python
"""
Sniff HID protocol commands from a real EV2300 to capture the full init sequence.

Opens the real EV2300 via Windows HID API (ctypes, zero dependencies) and sends
every known command code, logging the full 64-byte raw responses including
trailing data after the 0x55 frame end marker.

Special handling for CMD 0x70 (device info) which returns a 170-byte payload
that may span multiple HID reports.

Usage:
    python sniff_ev2300_init.py [--serial SERIAL] [--json output.json]

If --serial is not provided, opens the first device whose serial contains
"TUSB3210" (i.e., the real EV2300, not the STM32 bridge).
"""
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
from datetime import datetime

VID = 0x0451
PID = 0x0036
BUF_SIZE = 64

# ── CRC-8 (poly 0x07, init 0x00) ───────────────────────────────────────────

_CRC8_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = ((_c << 1) ^ 0x07) & 0xFF if _c & 0x80 else (_c << 1) & 0xFF
    _CRC8_TABLE.append(_c)

def crc8(data):
    crc = 0x00
    for b in data:
        crc = _CRC8_TABLE[crc ^ b]
    return crc

# ── Windows HID API setup ──────────────────────────────────────────────────

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

class SP_DEVIF(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD), ("InterfaceClassGuid", GUID),
        ("Flags", wt.DWORD), ("Reserved", ctypes.POINTER(ctypes.c_ulong))]

class DETAIL(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("DevicePath", ctypes.c_char * 512)]

class ATTRS(ctypes.Structure):
    _fields_ = [
        ("Size", wt.ULONG), ("VendorID", ctypes.c_ushort),
        ("ProductID", ctypes.c_ushort), ("VersionNumber", ctypes.c_ushort)]

hid_dll = ctypes.windll.hid
sa = ctypes.windll.setupapi
k32 = ctypes.windll.kernel32

INVALID_HANDLE = ctypes.c_void_p(-1).value
SHARE_RW = 0x03
OPEN_EXISTING = 3
DETAIL_CBSIZE = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 5

sa.SetupDiGetClassDevsA.restype = ctypes.c_void_p
sa.SetupDiGetClassDevsA.argtypes = [
    ctypes.POINTER(GUID), ctypes.c_char_p, ctypes.c_void_p, wt.DWORD]
sa.SetupDiEnumDeviceInterfaces.restype = wt.BOOL
sa.SetupDiEnumDeviceInterfaces.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID),
    wt.DWORD, ctypes.POINTER(SP_DEVIF)]
sa.SetupDiGetDeviceInterfaceDetailA.restype = wt.BOOL
sa.SetupDiGetDeviceInterfaceDetailA.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(SP_DEVIF),
    ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
sa.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

k32.CreateFileA.restype = ctypes.c_void_p
k32.CreateFileA.argtypes = [
    ctypes.c_char_p, wt.DWORD, wt.DWORD, ctypes.c_void_p,
    wt.DWORD, wt.DWORD, ctypes.c_void_p]
k32.CloseHandle.argtypes = [ctypes.c_void_p]
k32.CloseHandle.restype = wt.BOOL
k32.WriteFile.restype = wt.BOOL
k32.WriteFile.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
    ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
k32.ReadFile.restype = wt.BOOL
k32.ReadFile.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
    ctypes.POINTER(wt.DWORD), ctypes.c_void_p]

hid_dll.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
hid_dll.HidD_GetAttributes.restype = wt.BOOL
hid_dll.HidD_GetAttributes.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
hid_dll.HidD_SetNumInputBuffers.restype = wt.BOOL
hid_dll.HidD_SetNumInputBuffers.argtypes = [ctypes.c_void_p, wt.ULONG]

for fn_name in ("HidD_GetSerialNumberString", "HidD_GetProductString",
                "HidD_GetManufacturerString"):
    fn = getattr(hid_dll, fn_name)
    fn.restype = wt.BOOL
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.ULONG]


# ── Device enumeration and I/O ─────────────────────────────────────────────

def find_device(target_serial=None):
    """Find the real EV2300 device path. Returns (path_bytes, serial_str)."""
    guid = GUID()
    hid_dll.HidD_GetHidGuid(ctypes.byref(guid))
    h_info = sa.SetupDiGetClassDevsA(ctypes.byref(guid), None, None, 0x12)
    if h_info == INVALID_HANDLE:
        return None, None

    try:
        idx = 0
        while True:
            iface = SP_DEVIF()
            iface.cbSize = ctypes.sizeof(SP_DEVIF)
            if not sa.SetupDiEnumDeviceInterfaces(
                    h_info, None, ctypes.byref(guid), idx, ctypes.byref(iface)):
                break
            detail = DETAIL()
            detail.cbSize = DETAIL_CBSIZE
            req = wt.DWORD()
            sa.SetupDiGetDeviceInterfaceDetailA(
                h_info, ctypes.byref(iface), ctypes.byref(detail),
                ctypes.sizeof(detail), ctypes.byref(req), None)
            path_bytes = detail.DevicePath
            idx += 1

            h_dev = k32.CreateFileA(path_bytes, 0, SHARE_RW, None, OPEN_EXISTING, 0, None)
            if h_dev == INVALID_HANDLE:
                continue

            attrs = ATTRS()
            attrs.Size = ctypes.sizeof(ATTRS)
            if not hid_dll.HidD_GetAttributes(h_dev, ctypes.byref(attrs)):
                k32.CloseHandle(h_dev)
                continue

            if attrs.VendorID != VID or attrs.ProductID != PID:
                k32.CloseHandle(h_dev)
                continue

            buf = ctypes.create_unicode_buffer(256)
            serial = None
            if hid_dll.HidD_GetSerialNumberString(h_dev, buf, ctypes.sizeof(buf)):
                serial = buf.value
            k32.CloseHandle(h_dev)

            if target_serial:
                if serial and target_serial.lower() in serial.lower():
                    return path_bytes, serial
            else:
                # Default: pick the real EV2300 (has TUSB3210 in serial)
                if serial and "TUSB3210" in serial.upper():
                    return path_bytes, serial
    finally:
        sa.SetupDiDestroyDeviceInfoList(h_info)

    return None, None


def open_device(path_bytes):
    """Open device for read/write."""
    h = k32.CreateFileA(
        path_bytes, 0x80000000 | 0x40000000, SHARE_RW,
        None, OPEN_EXISTING, 0, None)
    if h == INVALID_HANDLE:
        raise OSError(f"CreateFile failed (error {ctypes.GetLastError()})")
    hid_dll.HidD_SetNumInputBuffers(h, 64)
    return h


def write_report(handle, data):
    """Write 64-byte HID report (prepend report ID 0x00, pad to 65)."""
    report = b"\x00" + bytes(data[:BUF_SIZE])
    report += b"\x00" * (65 - len(report))
    written = wt.DWORD()
    return bool(k32.WriteFile(handle, report, len(report), ctypes.byref(written), None))


def read_report(handle, timeout_ms=2000):
    """Read 64-byte HID report (strips report ID). Returns None on failure."""
    buf = ctypes.create_string_buffer(65)
    read_n = wt.DWORD()
    ok = k32.ReadFile(handle, buf, 65, ctypes.byref(read_n), None)
    if not ok:
        return None
    raw = buf.raw[:read_n.value]
    return raw[1:] if len(raw) > 1 else None


def build_packet(cmd, payload=b""):
    """Build a 64-byte EV2300 HID packet."""
    # Frame: [length] [0xAA] [cmd] [0x00 0x00 0x00] [payload_len] [payload...] [crc] [0x55]
    inner = bytes([cmd, 0x00, 0x00, 0x00, len(payload)]) + payload
    crc_val = crc8(inner)
    frame = bytes([0xAA]) + inner + bytes([crc_val, 0x55])
    pkt = bytes([len(frame)]) + frame
    pkt += b"\x00" * (BUF_SIZE - len(pkt))
    return pkt


# ── Command scanning ───────────────────────────────────────────────────────

# All commands from 0x00-0xFF, with known labels
KNOWN_CMDS = {
    0x01: "READ_WORD",
    0x02: "READ_BLOCK",
    0x03: "READ_BYTE",
    0x04: "WRITE_WORD",
    0x05: "WRITE_BLOCK",
    0x06: "SEND_BYTE",
    0x07: "WRITE_BYTE",
    0x0D: "I2C_BUS_STATUS",
    0x0E: "UNKNOWN_0x0E",
    0x11: "INTERNAL_STATUS",
    0x14: "DEVICE_CONFIG",
    0x1D: "FW_CONTROL",
    0x1E: "UNKNOWN_0x1E",
    0x1F: "UNKNOWN_0x1F",
    0x20: "UNKNOWN_0x20",
    0x21: "UNKNOWN_0x21",
    0x22: "UNKNOWN_0x22",
    0x2D: "UNKNOWN_0x2D",
    0x30: "ECHO_PING",
    0x31: "UNKNOWN_0x31",
    0x32: "UNKNOWN_0x32",
    0x33: "UNKNOWN_0x33",
    0x34: "UNKNOWN_0x34",
    0x35: "UNKNOWN_0x35",
    0x70: "DEVICE_INFO",
    0x80: "SUBMIT",
}

# Commands known to return valid (non-error) responses from protocol_results.json
VALID_CMDS = [0x01, 0x03, 0x0D, 0x0E, 0x11, 0x14, 0x1D, 0x1E, 0x1F, 0x20,
              0x21, 0x22, 0x2D, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x70]


def send_and_capture(handle, cmd, extra_reads=0):
    """Send a command and capture the response(s)."""
    # For read commands that need an I2C address/register, use dummy values
    if cmd in (0x01, 0x03):
        # READ_WORD/READ_BYTE: addr=0x10 (BQ76920), reg=0x00
        payload = bytes([0x10, 0x00])
    elif cmd == 0x02:
        # READ_BLOCK: addr=0x10, reg=0x00, len=4
        payload = bytes([0x10, 0x00, 0x04])
    else:
        payload = b""

    pkt = build_packet(cmd, payload)
    if not write_report(handle, pkt):
        return {"cmd": cmd, "error": "write_failed"}

    responses = []
    resp = read_report(handle)
    if resp:
        responses.append(resp)
    for _ in range(extra_reads):
        r = read_report(handle)
        if r:
            responses.append(r)

    if not responses:
        return {"cmd": cmd, "error": "no_response"}

    first = responses[0]
    result = {
        "cmd": cmd,
        "cmd_hex": f"0x{cmd:02X}",
        "label": KNOWN_CMDS.get(cmd, f"CMD_0x{cmd:02X}"),
        "response_count": len(responses),
        "raw_responses": [r.hex() for r in responses],
        "raw_bytes_pretty": [" ".join(f"{b:02x}" for b in r) for r in responses],
    }

    # Parse first response frame
    if len(first) >= 3 and first[1] == 0xAA:
        result["resp_cmd"] = first[2]
        result["resp_cmd_hex"] = f"0x{first[2]:02X}"
        result["is_error"] = (first[2] == 0x46)
        # Extract payload length if present
        if len(first) >= 7:
            result["payload_len"] = first[6]
            if first[6] > 0 and len(first) >= 7 + first[6]:
                payload_data = first[7:7 + first[6]]
                result["payload"] = " ".join(f"{b:02x}" for b in payload_data)
    else:
        result["resp_cmd"] = None
        result["is_error"] = True

    return result


def main():
    target_serial = None
    json_path = None
    scan_all = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--serial" and i + 1 < len(args):
            target_serial = args[i + 1]
            i += 2
        elif args[i] == "--json" and i + 1 < len(args):
            json_path = args[i + 1]
            i += 2
        elif args[i] == "--scan-all":
            scan_all = True
            i += 1
        else:
            i += 1

    print("EV2300 HID Protocol Sniffer")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()

    path, serial = find_device(target_serial)
    if not path:
        print("ERROR: No real EV2300 found. Is it plugged in?")
        print("Use --serial PATTERN to match a specific device.")
        sys.exit(1)

    print(f"Found device: serial={serial!r}")
    print(f"Opening device...")

    handle = open_device(path)
    results = []

    try:
        # Determine which commands to scan
        if scan_all:
            cmds_to_scan = list(range(0x00, 0x80))  # Skip 0x80+ to avoid writes
        else:
            cmds_to_scan = VALID_CMDS

        print(f"Scanning {len(cmds_to_scan)} commands...\n")

        for cmd in cmds_to_scan:
            label = KNOWN_CMDS.get(cmd, f"CMD_0x{cmd:02X}")
            extra = 3 if cmd == 0x70 else 0  # CMD 0x70 may have multi-report response

            result = send_and_capture(handle, cmd, extra_reads=extra)
            results.append(result)

            # Pretty print
            status = "ERROR" if result.get("is_error") else "OK"
            resp_hex = result.get("resp_cmd_hex", "N/A")
            plen = result.get("payload_len", 0)
            print(f"  CMD 0x{cmd:02X} ({label:<18}) -> resp={resp_hex:<6} "
                  f"payload={plen:<4} status={status}")
            if result.get("payload"):
                print(f"    payload: {result['payload']}")
            if cmd == 0x70 and result.get("response_count", 0) > 1:
                print(f"    ({result['response_count']} reports received)")

            # Brief pause between commands to avoid overwhelming the device
            time.sleep(0.05)

    finally:
        k32.CloseHandle(handle)

    # Print full CMD 0x70 response if captured
    cmd70 = next((r for r in results if r["cmd"] == 0x70), None)
    if cmd70 and not cmd70.get("error"):
        print("\n" + "=" * 72)
        print("CMD 0x70 (DEVICE_INFO) Full Response")
        print("=" * 72)
        for i, raw in enumerate(cmd70.get("raw_bytes_pretty", [])):
            print(f"  Report {i}: {raw}")
        print()

    # Save to JSON
    output = {
        "timestamp": datetime.now().isoformat(),
        "device_serial": serial,
        "scan_mode": "all" if scan_all else "known_valid",
        "results": results,
    }

    if json_path:
        with open(json_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Saved to {json_path}")
    else:
        # Default: save next to script
        default_path = sys.argv[0].replace(".py", "_results.json")
        with open(default_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Saved to {default_path}")


if __name__ == "__main__":
    main()
