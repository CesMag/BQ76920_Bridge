#!/usr/bin/env python
"""
Read the command log from STM32 firmware debug buffer.
Sends CMD 0xFE to get the commands that bq76940.exe sent.
Supports pagination (6 entries per page, 12 bytes each).
"""
import ctypes
import ctypes.wintypes as wt
import sys
import time

BUF = 64
TMO = 2000
FILE_FLAG_OVERLAPPED = 0x40000000
ENTRY_SIZE = 12

STM_PATH = b"\\\\?\\hid#vid_0451&pid_0036#6&191bcf7d&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}"

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

CMD_NAMES = {
    0x00: "BARE_0x00", 0x01: "READ_WORD", 0x02: "READ_BLOCK", 0x03: "READ_BYTE",
    0x04: "WRITE_WORD", 0x05: "WRITE_BLOCK", 0x06: "SEND_BYTE", 0x07: "WRITE_BYTE",
    0x0D: "I2C_CFG", 0x0E: "I2C_STAT", 0x11: "INT_STAT", 0x14: "DEV_CFG",
    0x1D: "FW_CTRL", 0x1E: "UNK_0x1E", 0x1F: "UNK_0x1F",
    0x70: "DEV_INFO", 0x80: "SUBMIT", 0xFE: "DEBUG_LOG",
}

class OL(ctypes.Structure):
    _fields_ = [("I", ctypes.POINTER(ctypes.c_ulong)),
                ("IH", ctypes.POINTER(ctypes.c_ulong)),
                ("O", wt.DWORD), ("OH", wt.DWORD), ("hE", ctypes.c_void_p)]

hid = ctypes.windll.hid
k32 = ctypes.windll.kernel32
IV = ctypes.c_void_p(-1).value

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
hid.HidD_SetNumInputBuffers.restype = wt.BOOL
hid.HidD_SetNumInputBuffers.argtypes = [ctypes.c_void_p, wt.ULONG]
hid.HidD_FlushQueue.restype = wt.BOOL
hid.HidD_FlushQueue.argtypes = [ctypes.c_void_p]


def build(cmd, payload=b""):
    inner = bytes([cmd, 0, 0, 0, len(payload)]) + payload
    c = crc8(inner)
    frame = bytes([0xAA]) + inner + bytes([c, 0x55])
    pkt = bytes([len(frame)]) + frame + b"\x00" * (BUF - 1 - len(frame))
    return pkt


def sr(h, e, pkt, tmo=TMO):
    rpt = b"\x00" + bytes(pkt[:BUF]) + b"\x00" * (65 - 1 - BUF)
    ol = OL(); ol.hE = e; k32.ResetEvent(e); w = wt.DWORD()
    ok = k32.WriteFile(h, rpt, 65, ctypes.byref(w), ctypes.byref(ol))
    if not ok and ctypes.GetLastError() == 997:
        k32.WaitForSingleObject(e, 5000)
        k32.GetOverlappedResult(h, ctypes.byref(ol), ctypes.byref(w), False)
    buf2 = ctypes.create_string_buffer(65)
    ol2 = OL(); ol2.hE = e; k32.ResetEvent(e); rn = wt.DWORD()
    ok = k32.ReadFile(h, buf2, 65, ctypes.byref(rn), ctypes.byref(ol2))
    if not ok:
        if ctypes.GetLastError() == 997:
            w2 = k32.WaitForSingleObject(e, tmo)
            if w2 == 0:
                k32.GetOverlappedResult(h, ctypes.byref(ol2), ctypes.byref(rn), False)
                return buf2.raw[1:rn.value]
            else:
                k32.CancelIo(h)
                return None
        return None
    return buf2.raw[1:rn.value]


def main():
    print("Opening STM32 device...")
    h = k32.CreateFileA(STM_PATH, 0xC0000000, 3, None, 3, FILE_FLAG_OVERLAPPED, None)
    if h == IV:
        print(f"Cannot open device (err={ctypes.GetLastError()}). Is bq76940.exe still running?")
        sys.exit(1)

    hid.HidD_SetNumInputBuffers(h, 64)
    e = k32.CreateEventA(None, True, False, None)
    hid.HidD_FlushQueue(h)
    time.sleep(0.1)

    all_entries = []

    # Read pages until we have all entries
    for page in range(6):
        raw = sr(h, e, build(0xFE, bytes([page])))
        if raw is None:
            print("TIMEOUT reading debug log")
            break

        total_count = raw[0]
        resp_page = raw[1]

        if page == 0:
            print(f"Total commands logged: {total_count}")
            # Subtract the debug reads themselves
            effective = total_count
            print(f"(includes {page+1}+ debug reads)\n")

        # Parse entries from this page
        entries_per_page = 5  # 2 header + 5*12 = 62 bytes
        for i in range(entries_per_page):
            offset = 2 + i * ENTRY_SIZE
            if offset + ENTRY_SIZE > len(raw):
                break
            entry = raw[offset:offset + ENTRY_SIZE]
            if all(b == 0 for b in entry):
                continue
            all_entries.append(entry)

        if len(all_entries) >= total_count:
            break
        time.sleep(0.05)

    # Print all entries
    print(f"{'#':>3}  {'CMD':>4}  {'Name':<12}  {'plen':>4}  {'Raw (12 bytes)':<40}  Payload")
    print("-" * 95)

    for i, entry in enumerate(all_entries):
        if len(entry) < 7:
            continue
        tlen = entry[0]
        marker = entry[1]
        cmd = entry[2]
        plen = entry[6]
        name = CMD_NAMES.get(cmd, f"UNK_0x{cmd:02X}")
        hex_str = " ".join(f"{b:02x}" for b in entry)

        # Extract payload bytes
        payload = entry[7:7 + min(plen, 5)]
        payload_str = " ".join(f"{b:02x}" for b in payload)
        if plen > 5:
            payload_str += f"... ({plen}B)"

        print(f"{i+1:3d}  0x{cmd:02X}  {name:<12}  {plen:4d}  {hex_str}  [{payload_str}]")

    k32.CloseHandle(h)
    k32.CloseHandle(e)
    print("\nDone!")


if __name__ == "__main__":
    main()
