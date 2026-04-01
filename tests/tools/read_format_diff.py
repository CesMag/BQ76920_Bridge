#!/usr/bin/env python
"""
Capture READ_BYTE and READ_BLOCK response formats from both devices.
"""
import ctypes
import ctypes.wintypes as wt
import time

BUF = 64
TMO = 3000
FILE_FLAG_OVERLAPPED = 0x40000000

REAL_PATH = b"\\\\?\\hid#vid_0451&pid_0036#6&2cb02d24&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}"
STM_PATH  = b"\\\\?\\hid#vid_0451&pid_0036#6&191bcf7d&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}"

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


class Dev:
    def __init__(self, path, label):
        self.lbl = label
        self.h = k32.CreateFileA(path, 0xC0000000, 3, None, 3, FILE_FLAG_OVERLAPPED, None)
        if self.h == IV:
            raise OSError(f"Cannot open {label} err={ctypes.GetLastError()}")
        hid.HidD_SetNumInputBuffers(self.h, 64)
        self.e = k32.CreateEventA(None, True, False, None)

    def flush(self):
        hid.HidD_FlushQueue(self.h)

    def sr(self, pkt, tmo=TMO):
        rpt = b"\x00" + bytes(pkt[:BUF])
        rpt += b"\x00" * (65 - len(rpt))
        ol = OL(); ol.hE = self.e
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
        ol2 = OL(); ol2.hE = self.e
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


def fmt(raw, n=20):
    if raw is None:
        return "TIMEOUT"
    return " ".join(f"{b:02x}" for b in raw[:n])


def parse_response(raw, label=""):
    """Parse and print response structure."""
    if raw is None:
        print(f"  {label} TIMEOUT")
        return
    b = raw
    tlen = b[0]
    cmd = b[2] if len(b) > 2 else 0
    plen = b[6] if len(b) > 6 else 0
    payload = b[7:7+plen] if len(b) > 7 else b""
    crc_pos = 7 + plen
    crc_val = b[crc_pos] if crc_pos < len(b) else 0
    end_val = b[crc_pos+1] if crc_pos+1 < len(b) else 0

    # Compute expected CRC (excl last byte and incl all)
    crc_data_excl = bytes(b[2:2+5+plen-1]) if plen > 0 else bytes(b[2:7])
    crc_data_incl = bytes(b[2:2+5+plen])
    crc_excl = crc8(crc_data_excl)
    crc_incl = crc8(crc_data_incl)

    print(f"  {label}")
    print(f"    raw:     {fmt(raw, 20)}")
    print(f"    tlen=0x{tlen:02X} cmd=0x{cmd:02X} plen={plen} end=0x{end_val:02X}")
    print(f"    payload: {' '.join(f'{x:02x}' for x in payload)}")
    print(f"    CRC: got=0x{crc_val:02X} calc_excl_last=0x{crc_excl:02X} calc_incl_all=0x{crc_incl:02X}")


def main():
    real = Dev(REAL_PATH, "REAL")
    stm  = Dev(STM_PATH, "STM32")
    real.flush()
    stm.flush()
    time.sleep(0.3)

    ADDR = 0x10  # BQ76920 8-bit addr

    print("=" * 70)
    print("READ FORMAT COMPARISON")
    print("=" * 70)

    # READ_BYTE (0x03) at various registers
    print("\n--- READ_BYTE (0x03) ---")
    for reg, name in [(0x00, "SYS_STAT"), (0x04, "SYS_CTRL1"), (0x0B, "CC_CFG")]:
        for dev in [real, stm]:
            dev.flush()
            time.sleep(0.05)
            r = dev.sr(build(0x03, bytes([ADDR, reg])))
            parse_response(r, f"{dev.lbl} READ_BYTE {name} (0x{reg:02X})")

    # READ_WORD (0x01) for reference
    print("\n--- READ_WORD (0x01) ---")
    for reg, name in [(0x00, "SYS_STAT"), (0x0B, "CC_CFG")]:
        for dev in [real, stm]:
            dev.flush()
            time.sleep(0.05)
            r = dev.sr(build(0x01, bytes([ADDR, reg])))
            parse_response(r, f"{dev.lbl} READ_WORD {name} (0x{reg:02X})")

    # READ_BLOCK (0x02)
    print("\n--- READ_BLOCK (0x02) ---")
    for dev in [real, stm]:
        dev.flush()
        time.sleep(0.05)
        r = dev.sr(build(0x02, bytes([ADDR, 0x00, 0x04])))
        parse_response(r, f"{dev.lbl} READ_BLOCK reg=0x00 len=4")

    for dev in [real, stm]:
        dev.flush()
        time.sleep(0.05)
        r = dev.sr(build(0x02, bytes([ADDR, 0x00, 0x10])))
        parse_response(r, f"{dev.lbl} READ_BLOCK reg=0x00 len=16")

    # READ_BYTE at error address (no device)
    print("\n--- READ_BYTE at invalid addr 0xFE ---")
    for dev in [real, stm]:
        dev.flush()
        time.sleep(0.05)
        r = dev.sr(build(0x03, bytes([0xFE, 0x00])))
        parse_response(r, f"{dev.lbl} READ_BYTE invalid addr")

    # READ_WORD at error address
    print("\n--- READ_WORD at invalid addr 0xFE ---")
    for dev in [real, stm]:
        dev.flush()
        time.sleep(0.05)
        r = dev.sr(build(0x01, bytes([0xFE, 0x00])))
        parse_response(r, f"{dev.lbl} READ_WORD invalid addr")

    real.close()
    stm.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
