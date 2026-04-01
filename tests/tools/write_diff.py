#!/usr/bin/env python
"""
Capture write ack + submit responses from both real EV2300 and STM32,
both connected to their own BQ boards with real I2C traffic.
"""
import ctypes
import ctypes.wintypes as wt
import time

BUF = 64
TMO = 3000
FILE_FLAG_OVERLAPPED = 0x40000000

# Known paths from enumeration
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


def fmt(raw, n=64):
    if raw is None:
        return "TIMEOUT (no response)"
    return " ".join(f"{b:02x}" for b in raw[:n])


def test_rw(dev, label, wcmd, wpayload, read_cmd=0x01, read_payload=None):
    """Send write + submit + readback on one device."""
    dev.flush()
    time.sleep(0.05)

    # Write command
    ack = dev.sr(build(wcmd, wpayload))
    dev.flush()
    time.sleep(0.05)

    # Submit
    sub = dev.sr(build(0x80))
    dev.flush()
    time.sleep(0.05)

    # Readback
    rb = None
    if read_payload:
        rb = dev.sr(build(read_cmd, read_payload))
        dev.flush()
        time.sleep(0.05)

    print(f"  {dev.lbl:<7} write_ack: {fmt(ack)}")
    print(f"  {dev.lbl:<7} submit:    {fmt(sub)}")
    if rb is not None:
        print(f"  {dev.lbl:<7} readback:  {fmt(rb)}")
    return ack, sub, rb


def main():
    print("Opening devices...")
    real = Dev(REAL_PATH, "REAL")
    stm  = Dev(STM_PATH, "STM32")
    real.flush()
    stm.flush()
    time.sleep(0.3)

    print("=" * 75)
    print("WRITE ACK COMPARISON — Both devices connected to BQ boards")
    print("=" * 75)

    # BQ76920 I2C addr 0x08 -> shifted = 0x10
    ADDR = 0x10

    # Test 1: WRITE_WORD CC_CFG=0x19 (safe, required value)
    print("\n--- Test 1: WRITE_WORD (0x04) CC_CFG=0x19 ---")
    for dev in [real, stm]:
        test_rw(dev, "WR_WORD CC_CFG",
                0x04, bytes([ADDR, 0x0B, 0x19, 0x00]),
                read_cmd=0x01, read_payload=bytes([ADDR, 0x0B]))

    # Test 2: WRITE_BYTE CC_CFG=0x19
    print("\n--- Test 2: WRITE_BYTE (0x07) CC_CFG=0x19 ---")
    for dev in [real, stm]:
        test_rw(dev, "WR_BYTE CC_CFG",
                0x07, bytes([ADDR, 0x0B, 0x19]),
                read_cmd=0x01, read_payload=bytes([ADDR, 0x0B]))

    # Test 3: WRITE_WORD SYS_CTRL1 read current, write same back
    print("\n--- Test 3: WRITE_WORD (0x04) SYS_CTRL1 (read-modify-write) ---")
    for dev in [real, stm]:
        dev.flush()
        time.sleep(0.05)
        cur = dev.sr(build(0x01, bytes([ADDR, 0x04])))
        print(f"  {dev.lbl:<7} current SYS_CTRL1: {fmt(cur)}")
        # Write back 0x18 (ADC_EN=1, TEMP_SEL=1) which is a safe value
        test_rw(dev, "WR SYS_CTRL1",
                0x04, bytes([ADDR, 0x04, 0x18, 0x00]),
                read_cmd=0x01, read_payload=bytes([ADDR, 0x04]))

    # Test 4: SEND_BYTE (0x06)
    print("\n--- Test 4: SEND_BYTE (0x06) ---")
    for dev in [real, stm]:
        dev.flush()
        time.sleep(0.05)
        ack = dev.sr(build(0x06, bytes([ADDR, 0x00])))
        dev.flush()
        time.sleep(0.05)
        sub = dev.sr(build(0x80))
        dev.flush()
        time.sleep(0.05)
        print(f"  {dev.lbl:<7} write_ack: {fmt(ack)}")
        print(f"  {dev.lbl:<7} submit:    {fmt(sub)}")

    # Test 5: WRITE_BLOCK (0x05)
    print("\n--- Test 5: WRITE_BLOCK (0x05) CC_CFG=0x19 ---")
    for dev in [real, stm]:
        test_rw(dev, "WR_BLOCK CC_CFG",
                0x05, bytes([ADDR, 0x0B, 0x01, 0x19]),
                read_cmd=0x01, read_payload=bytes([ADDR, 0x0B]))

    # Test 6: Write to invalid address (should NACK)
    print("\n--- Test 6: WRITE_WORD to invalid addr 0x7F (should NACK) ---")
    for dev in [real, stm]:
        test_rw(dev, "WR bad addr",
                0x04, bytes([0xFE, 0x00, 0x00, 0x00]))

    # Test 7: Quick read comparison
    print("\n--- Test 7: READ_WORD comparison (sanity check) ---")
    for reg, name in [(0x00, "SYS_STAT"), (0x04, "SYS_CTRL1"), (0x06, "PROTECT1"), (0x0B, "CC_CFG")]:
        for dev in [real, stm]:
            dev.flush()
            time.sleep(0.05)
            r = dev.sr(build(0x01, bytes([ADDR, reg])))
            print(f"  {dev.lbl:<7} {name:12s} (0x{reg:02X}): {fmt(r)}")

    # Test 8: Init command 0x0D (I2C bus config)
    print("\n--- Test 8: CMD 0x0D with payload (I2C bus config) ---")
    for dev in [real, stm]:
        dev.flush()
        time.sleep(0.05)
        r = dev.sr(build(0x0D, bytes([0x02, 0x00, 0x08])))
        print(f"  {dev.lbl:<7} 0x0D resp: {fmt(r)}")

    real.close()
    stm.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
