#!/usr/bin/env python3
"""
EV2300 DLL call tracer -- captures what HID packets the TI DLLs send.

Run this on a Windows machine with the BQ76920_Bridge device plugged in.
It calls the TI DLLs (bq80xrw.dll) through msl-loadlib and logs every
operation to identify what commands I2CPower and other functions send.

Requirements:
  - Windows (32-bit DLLs)
  - pip install msl-loadlib
  - Copy bq80xrw.dll, bq80xusb.dll, CMAPI.dll to the working directory
  - Or set DLL_DIR to the path containing the DLLs

Usage:
  python trace_dll.py [--dll-dir path/to/dlls]
"""
import sys
import os
import ctypes
import argparse


def trace_with_hid(dll_dir):
    """Use the DLL directly via ctypes (must be 32-bit Python on 32-bit DLLs)."""
    dll_path = os.path.join(dll_dir, "bq80xrw.dll")
    if not os.path.exists(dll_path):
        print(f"ERROR: {dll_path} not found")
        return

    print(f"Loading {dll_path}")
    lib = ctypes.CDLL(dll_path)

    # Set up function signatures
    lib.OpenDeviceA.argtypes = [ctypes.POINTER(ctypes.c_ubyte)]
    lib.OpenDeviceA.restype = ctypes.c_int

    lib.CloseDeviceA.argtypes = []
    lib.CloseDeviceA.restype = ctypes.c_int

    lib.CheckForError.argtypes = []
    lib.CheckForError.restype = ctypes.c_int

    lib.TranslateErrorbqSBB.argtypes = [ctypes.c_int]
    lib.TranslateErrorbqSBB.restype = ctypes.c_char_p

    lib.I2CPower.argtypes = [ctypes.c_short]
    lib.I2CPower.restype = ctypes.c_int

    lib.ReadSMBusWord.argtypes = [ctypes.c_short, ctypes.POINTER(ctypes.c_short), ctypes.c_short]
    lib.ReadSMBusWord.restype = ctypes.c_int

    lib.GetAllFreeBoards.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.c_int,
    ]
    lib.GetAllFreeBoards.restype = ctypes.c_int

    def err(code):
        try:
            return lib.TranslateErrorbqSBB(code).decode()
        except Exception:
            return f"code={code}"

    # Step 1: Enumerate boards
    print("\n=== Step 1: GetAllFreeBoards ===")
    count = ctypes.c_int(0)
    buf = (ctypes.c_ubyte * 4096)()
    status = lib.GetAllFreeBoards(4096, ctypes.byref(count), buf, 0)
    names = [c.decode() for c in bytes(buf).split(b"\x00") if c]
    print(f"  status={status} ({err(status)})")
    print(f"  count={count.value}")
    print(f"  boards={names}")

    if not names:
        print("  No boards found. Is the device plugged in?")
        return

    # Step 2: Open device
    adapter = names[0]
    print(f"\n=== Step 2: OpenDeviceA('{adapter}') ===")
    name_buf = (ctypes.c_ubyte * (len(adapter) + 1))(*adapter.encode(), 0)
    status = lib.OpenDeviceA(name_buf)
    print(f"  status={status} ({err(status)})")
    ec = lib.CheckForError()
    print(f"  CheckForError={ec} ({err(ec)})")

    if status != 0:
        print("  Open failed. Aborting.")
        return

    # Step 3: I2CPower
    print("\n=== Step 3: I2CPower(1) ===")
    status = lib.I2CPower(ctypes.c_short(1))
    print(f"  status={status} ({err(status)})")
    ec = lib.CheckForError()
    print(f"  CheckForError={ec} ({err(ec)})")

    # Step 4: ReadSMBusWord
    print("\n=== Step 4: ReadSMBusWord(reg=0x0B, addr=0x08) -- CC_CFG ===")
    value = ctypes.c_short(0)
    status = lib.ReadSMBusWord(ctypes.c_short(0x0B), ctypes.byref(value), ctypes.c_short(0x08))
    print(f"  status={status} ({err(status)})")
    print(f"  value=0x{value.value & 0xFFFF:04X}")
    ec = lib.CheckForError()
    print(f"  CheckForError={ec} ({err(ec)})")

    # Step 5: ReadSMBusWord for SYS_STAT
    print("\n=== Step 5: ReadSMBusWord(reg=0x00, addr=0x08) -- SYS_STAT ===")
    value = ctypes.c_short(0)
    status = lib.ReadSMBusWord(ctypes.c_short(0x00), ctypes.byref(value), ctypes.c_short(0x08))
    print(f"  status={status} ({err(status)})")
    print(f"  value=0x{value.value & 0xFFFF:04X}")

    # Step 6: Close
    print("\n=== Step 6: CloseDeviceA ===")
    status = lib.CloseDeviceA()
    print(f"  status={status} ({err(status)})")

    print("\nDone.")


def main():
    parser = argparse.ArgumentParser(description="Trace EV2300 DLL calls")
    parser.add_argument("--dll-dir", default=".", help="Directory containing TI DLLs")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("ERROR: This script requires Windows (TI DLLs are 32-bit PE)")
        print("Copy this script and the DLLs to the Windows machine and run there.")
        sys.exit(1)

    trace_with_hid(args.dll_dir)


if __name__ == "__main__":
    main()
