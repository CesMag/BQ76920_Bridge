#!/usr/bin/env python
"""
Compare USB HID descriptors between real EV2300 and STM32 bridge.

Enumerates all VID=0x0451/PID=0x0036 HID devices and prints a side-by-side
comparison of their USB descriptors, HID capabilities, and string descriptors.

Zero dependencies -- uses only ctypes + Windows HID/SetupDI API.
Run with any Python (32- or 64-bit).

Usage:
    python compare_ev2300_descriptors.py [--json output.json]
"""
import ctypes
import ctypes.wintypes as wt
import json
import sys
from datetime import datetime

VID = 0x0451
PID = 0x0036

# ── Windows HID API structures ──────────────────────────────────────────────

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

class CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", ctypes.c_ushort), ("UsagePage", ctypes.c_ushort),
        ("InputReportByteLength", ctypes.c_ushort),
        ("OutputReportByteLength", ctypes.c_ushort),
        ("FeatureReportByteLength", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort * 17),
        ("NumberLinkCollectionNodes", ctypes.c_ushort),
        ("NumberInputButtonCaps", ctypes.c_ushort),
        ("NumberInputValueCaps", ctypes.c_ushort),
        ("NumberInputDataIndices", ctypes.c_ushort),
        ("NumberOutputButtonCaps", ctypes.c_ushort),
        ("NumberOutputValueCaps", ctypes.c_ushort),
        ("NumberOutputDataIndices", ctypes.c_ushort),
        ("NumberFeatureButtonCaps", ctypes.c_ushort),
        ("NumberFeatureValueCaps", ctypes.c_ushort),
        ("NumberFeatureDataIndices", ctypes.c_ushort)]

# ── DLL handles ─────────────────────────────────────────────────────────────

hid = ctypes.windll.hid
sa = ctypes.windll.setupapi
k32 = ctypes.windll.kernel32

INVALID_HANDLE = ctypes.c_void_p(-1).value
SHARE_RW = 0x03
OPEN_EXISTING = 3
DETAIL_CBSIZE = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 5

# setupapi
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

# kernel32
k32.CreateFileA.restype = ctypes.c_void_p
k32.CreateFileA.argtypes = [
    ctypes.c_char_p, wt.DWORD, wt.DWORD, ctypes.c_void_p,
    wt.DWORD, wt.DWORD, ctypes.c_void_p]
k32.CloseHandle.argtypes = [ctypes.c_void_p]
k32.CloseHandle.restype = wt.BOOL

# hid
hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
hid.HidD_GetAttributes.restype = wt.BOOL
hid.HidD_GetAttributes.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
hid.HidD_GetPreparsedData.restype = wt.BOOL
hid.HidD_GetPreparsedData.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
hid.HidP_GetCaps.restype = ctypes.c_long
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(CAPS)]
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]

for fn_name in ("HidD_GetSerialNumberString", "HidD_GetProductString",
                "HidD_GetManufacturerString"):
    fn = getattr(hid, fn_name)
    fn.restype = wt.BOOL
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.ULONG]


# ── Helpers ─────────────────────────────────────────────────────────────────

def _get_string(handle, func):
    buf = ctypes.create_unicode_buffer(256)
    ok = func(handle, buf, ctypes.sizeof(buf))
    return buf.value if ok else None


def enumerate_ev2300_devices():
    """Find all HID devices matching VID/PID and read their full descriptor info."""
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    h_info = sa.SetupDiGetClassDevsA(ctypes.byref(guid), None, None, 0x12)
    if h_info == INVALID_HANDLE:
        return []

    devices = []
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
            path_str = path_bytes.decode("ascii", errors="replace")
            idx += 1

            # Open read-only (access=0) to read attributes without interfering
            h_dev = k32.CreateFileA(path_bytes, 0, SHARE_RW, None, OPEN_EXISTING, 0, None)
            if h_dev == INVALID_HANDLE:
                continue

            attrs = ATTRS()
            attrs.Size = ctypes.sizeof(ATTRS)
            if not hid.HidD_GetAttributes(h_dev, ctypes.byref(attrs)):
                k32.CloseHandle(h_dev)
                continue

            if attrs.VendorID != VID or attrs.ProductID != PID:
                k32.CloseHandle(h_dev)
                continue

            # Read string descriptors
            serial = _get_string(h_dev, hid.HidD_GetSerialNumberString)
            product = _get_string(h_dev, hid.HidD_GetProductString)
            manufacturer = _get_string(h_dev, hid.HidD_GetManufacturerString)

            # Read HID capabilities
            ppd = ctypes.c_void_p()
            caps_dict = {}
            if hid.HidD_GetPreparsedData(h_dev, ctypes.byref(ppd)):
                caps = CAPS()
                hid.HidP_GetCaps(ppd, ctypes.byref(caps))
                caps_dict = {
                    "usage": f"0x{caps.Usage:04X}",
                    "usage_page": f"0x{caps.UsagePage:04X}",
                    "input_report_length": caps.InputReportByteLength,
                    "output_report_length": caps.OutputReportByteLength,
                    "feature_report_length": caps.FeatureReportByteLength,
                }
                hid.HidD_FreePreparsedData(ppd)

            k32.CloseHandle(h_dev)

            dev_info = {
                "path": path_str,
                "vid": f"0x{attrs.VendorID:04X}",
                "pid": f"0x{attrs.ProductID:04X}",
                "bcdDevice": f"0x{attrs.VersionNumber:04X}",
                "bcdDevice_raw": attrs.VersionNumber,
                "serial": serial,
                "product": product,
                "manufacturer": manufacturer,
                "manufacturer_len": len(manufacturer) if manufacturer else 0,
                "caps": caps_dict,
            }

            # Classify: real EV2300 has "TUSB3210" in serial, STM32 has hex UID
            if serial and "TUSB3210" in serial.upper():
                dev_info["identity"] = "REAL_EV2300"
            elif serial and all(c in "0123456789ABCDEFabcdef" for c in serial):
                dev_info["identity"] = "STM32_BRIDGE"
            else:
                dev_info["identity"] = "UNKNOWN"

            devices.append(dev_info)
    finally:
        sa.SetupDiDestroyDeviceInfoList(h_info)

    return devices


def print_comparison(devices):
    """Print side-by-side comparison of device descriptors."""
    if not devices:
        print("ERROR: No EV2300 devices found (VID=0x0451, PID=0x0036)")
        return

    print(f"\nFound {len(devices)} device(s) matching VID=0x{VID:04X} PID=0x{PID:04X}\n")

    for i, dev in enumerate(devices):
        print(f"--- Device {i}: {dev['identity']} ---")
        print(f"  Path:             {dev['path']}")
        print(f"  VID:              {dev['vid']}")
        print(f"  PID:              {dev['pid']}")
        print(f"  bcdDevice:        {dev['bcdDevice']} (raw={dev['bcdDevice_raw']})")
        print(f"  Serial:           {dev['serial']!r}")
        print(f"  Product:          {dev['product']!r}")
        print(f"  Manufacturer:     {dev['manufacturer']!r} ({dev['manufacturer_len']} chars)")
        if dev["caps"]:
            c = dev["caps"]
            print(f"  UsagePage:        {c['usage_page']}")
            print(f"  Usage:            {c['usage']}")
            print(f"  InputReportLen:   {c['input_report_length']}")
            print(f"  OutputReportLen:  {c['output_report_length']}")
            print(f"  FeatureReportLen: {c['feature_report_length']}")
        print()

    # Side-by-side diff if we have exactly 2 devices
    if len(devices) == 2:
        real = next((d for d in devices if d["identity"] == "REAL_EV2300"), devices[0])
        stm32 = next((d for d in devices if d["identity"] == "STM32_BRIDGE"), devices[1])
        print("=" * 72)
        print("COMPARISON: REAL_EV2300 vs STM32_BRIDGE")
        print("=" * 72)

        fields = [
            ("bcdDevice", "bcdDevice"),
            ("Serial", "serial"),
            ("Product", "product"),
            ("Manufacturer", "manufacturer"),
            ("Manufacturer len", "manufacturer_len"),
        ]
        cap_fields = [
            ("UsagePage", "usage_page"),
            ("Usage", "usage"),
            ("InputReportLen", "input_report_length"),
            ("OutputReportLen", "output_report_length"),
            ("FeatureReportLen", "feature_report_length"),
        ]

        print(f"{'Property':<20} {'Real EV2300':<35} {'STM32 Bridge':<35} {'Match?'}")
        print("-" * 100)
        for label, key in fields:
            rv = repr(real.get(key, "N/A"))
            sv = repr(stm32.get(key, "N/A"))
            match = "OK" if real.get(key) == stm32.get(key) else "** MISMATCH **"
            print(f"{label:<20} {rv:<35} {sv:<35} {match}")

        if real.get("caps") and stm32.get("caps"):
            for label, key in cap_fields:
                rv = repr(real["caps"].get(key, "N/A"))
                sv = repr(stm32["caps"].get(key, "N/A"))
                match = "OK" if real["caps"].get(key) == stm32["caps"].get(key) else "** MISMATCH **"
                print(f"{label:<20} {rv:<35} {sv:<35} {match}")
        print()


def main():
    json_path = None
    if "--json" in sys.argv:
        idx = sys.argv.index("--json")
        if idx + 1 < len(sys.argv):
            json_path = sys.argv[idx + 1]

    print("EV2300 USB HID Descriptor Comparison Tool")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Python: {sys.version}")
    print(f"Pointer size: {ctypes.sizeof(ctypes.c_void_p) * 8}-bit")

    devices = enumerate_ev2300_devices()
    print_comparison(devices)

    if json_path:
        output = {
            "timestamp": datetime.now().isoformat(),
            "python_bits": ctypes.sizeof(ctypes.c_void_p) * 8,
            "devices": devices,
        }
        # Strip non-serializable fields
        for d in output["devices"]:
            d.pop("bcdDevice_raw", None)
        with open(json_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Saved to {json_path}")


if __name__ == "__main__":
    main()
