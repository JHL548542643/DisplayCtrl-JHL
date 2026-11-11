"""Windows dxva2 Physical Monitor API. Importing this module does not load dxva2.

The call pattern matches the original brightness CLI: EnumDisplayMonitors,
GetPhysicalMonitorsFromHMONITOR, Get/Set VCP 0x10, then DestroyPhysicalMonitors.
Handles are closed before these functions return. EDID comes from the registry
(``Enum\\DISPLAY`` via ``DeviceID``, then the class ``DeviceKey``), not from
another VCP code.

A capabilities string is read only after GetVCP 0x10 succeeds and the EDID
cache misses. When caps declare known-safe codes, or the vcp() list is sparse, a small
known-safe GetVCP set (contrast / volume / RGB / input / power) runs on the same open handle. Physical
monitors stay serial: shared DDC/I2C buses are not probed in parallel. The write
path opens handles with ``read_vcp=False`` and calls SetVCPFeature once for an
allow-listed code (luminance / contrast / volume).
"""

from __future__ import annotations

import ctypes
import sys
from typing import Any

from displayctl.caps_cache import CapsCache, caps_cache_key, resolve_caps
from displayctl.edid_reg import WinregReader, read_edid_from_registry
from displayctl.errors import DisplayError
from displayctl.identity import same_raw
from displayctl.models import RawMonitor, VcpSample
from displayctl.policy import LUMINANCE_MAX, LUMINANCE_MIN, LUMINANCE_VCP, ensure_write_code
from displayctl.vcp_probe import ProbeCache, codes_to_probe

_CAPS_CACHE = CapsCache()
_PROBE_CACHE = ProbeCache()

_BINDINGS: dict[str, Any] | None = None


def probe_raw() -> list[RawMonitor]:
    if sys.platform != "win32":
        raise DisplayError("platform_unsupported")
    bindings = _bindings()
    opened, arrays = _collect(bindings, read_vcp=True)
    try:
        return [raw for raw, _handle in opened]
    finally:
        _destroy(bindings, arrays)


def set_vcp_raw(target: RawMonitor, code: int, value: int) -> None:
    """Write one allow-listed VCP once. Matching uses EDID or geometry, never a bare index."""
    if sys.platform != "win32":
        raise DisplayError("platform_unsupported")
    ensure_write_code(code)
    if isinstance(value, bool) or not isinstance(value, int):
        raise DisplayError("value_out_of_range")
    if value < LUMINANCE_MIN or value > LUMINANCE_MAX:
        raise DisplayError("value_out_of_range")
    bindings = _bindings()
    opened, arrays = _collect(bindings, read_vcp=False)
    try:
        matches = [(raw, handle) for raw, handle in opened if same_raw(raw, target)]
        if len(matches) != 1:
            kind = "identity_ambiguous" if len(matches) > 1 else "unknown_monitor"
            raise DisplayError(kind)
        _handle = matches[0][1]
        ensure_write_code(code)
        ok = bool(bindings["dxva2"].SetVCPFeature(_handle, code, value))
        if not ok:
            raise DisplayError("write_failed", winerr=ctypes.get_last_error())
    finally:
        _destroy(bindings, arrays)


def set_luminance_raw(target: RawMonitor, value: int) -> None:
    """Write 0x10 once. Thin wrapper around ``set_vcp_raw``."""
    set_vcp_raw(target, LUMINANCE_VCP, value)


def _bindings() -> dict[str, Any]:
    global _BINDINGS
    if _BINDINGS is not None:
        return _BINDINGS
    if sys.platform != "win32":
        raise DisplayError("platform_unsupported")
    from ctypes import wintypes

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        dxva2 = ctypes.WinDLL("dxva2", use_last_error=True)
    except OSError as exc:
        raise DisplayError("platform_unsupported") from exc

    monitor_enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    class PHYSICAL_MONITOR(ctypes.Structure):
        _fields_ = [
            ("hPhysicalMonitor", wintypes.HANDLE),
            ("szPhysicalMonitorDescription", wintypes.WCHAR * 128),
        ]

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("DeviceName", wintypes.WCHAR * 32),
            ("DeviceString", wintypes.WCHAR * 128),
            ("StateFlags", wintypes.DWORD),
            ("DeviceID", wintypes.WCHAR * 128),
            ("DeviceKey", wintypes.WCHAR * 128),
        ]

    user32.EnumDisplayMonitors.argtypes = [
        wintypes.HDC,
        ctypes.c_void_p,
        monitor_enum_proc,
        wintypes.LPARAM,
    ]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.EnumDisplayDevicesW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(DISPLAY_DEVICEW),
        wintypes.DWORD,
    ]
    user32.EnumDisplayDevicesW.restype = wintypes.BOOL

    dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [
        wintypes.HMONITOR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL
    dxva2.GetPhysicalMonitorsFromHMONITOR.argtypes = [
        wintypes.HMONITOR,
        wintypes.DWORD,
        ctypes.POINTER(PHYSICAL_MONITOR),
    ]
    dxva2.GetPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL
    dxva2.DestroyPhysicalMonitors.argtypes = [wintypes.DWORD, ctypes.POINTER(PHYSICAL_MONITOR)]
    dxva2.DestroyPhysicalMonitors.restype = wintypes.BOOL
    dxva2.GetVCPFeatureAndVCPFeatureReply.argtypes = [
        wintypes.HANDLE,
        ctypes.c_ubyte,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    dxva2.GetVCPFeatureAndVCPFeatureReply.restype = wintypes.BOOL
    dxva2.SetVCPFeature.argtypes = [wintypes.HANDLE, ctypes.c_ubyte, wintypes.DWORD]
    dxva2.SetVCPFeature.restype = wintypes.BOOL
    dxva2.GetCapabilitiesStringLength.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    dxva2.GetCapabilitiesStringLength.restype = wintypes.BOOL
    dxva2.CapabilitiesRequestAndCapabilitiesReply.argtypes = [
        wintypes.HANDLE,
        ctypes.c_char_p,
        wintypes.DWORD,
    ]
    dxva2.CapabilitiesRequestAndCapabilitiesReply.restype = wintypes.BOOL

    _BINDINGS = {
        "user32": user32,
        "dxva2": dxva2,
        "PHYSICAL_MONITOR": PHYSICAL_MONITOR,
        "MONITORINFOEXW": MONITORINFOEXW,
        "DISPLAY_DEVICEW": DISPLAY_DEVICEW,
        "MonitorEnumProc": monitor_enum_proc,
        "DWORD": wintypes.DWORD,
    }
    return _BINDINGS


def _collect(bindings: dict[str, Any], *, read_vcp: bool) -> tuple[list[tuple[RawMonitor, Any]], list[Any]]:
    user32 = bindings["user32"]
    dxva2 = bindings["dxva2"]
    physical_cls = bindings["PHYSICAL_MONITOR"]
    info_cls = bindings["MONITORINFOEXW"]
    dword = bindings["DWORD"]
    opened: list[tuple[RawMonitor, Any]] = []
    arrays: list[Any] = []
    edid_cache: dict[str, bytes | None] = {}

    def callback(hmonitor, _hdc, _rect, _data):
        info = info_cls()
        info.cbSize = ctypes.sizeof(info_cls)
        if not user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            return True
        count = dword()
        if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmonitor, ctypes.byref(count)):
            return True
        if count.value == 0:
            return True
        arr = (physical_cls * count.value)()
        if not dxva2.GetPhysicalMonitorsFromHMONITOR(hmonitor, count.value, arr):
            return True
        arrays.append(arr)
        device = _clean(info.szDevice)
        rect = (
            int(info.rcMonitor.left),
            int(info.rcMonitor.top),
            int(info.rcMonitor.right),
            int(info.rcMonitor.bottom),
        )
        primary = bool(info.dwFlags & 1)
        if device not in edid_cache:
            edid_cache[device] = _read_edid(user32, bindings["DISPLAY_DEVICEW"], device)
        edid = edid_cache[device]
        # One physical monitor at a time. Do not fan GetVCP or capabilities
        # requests out across handles; a shared DDC/I2C bus drops replies.
        for item in arr:
            opened.append(
                (
                    _raw_from_handle(
                        dxva2,
                        dword,
                        handle=item.hPhysicalMonitor,
                        device=device,
                        description=_clean(item.szPhysicalMonitorDescription),
                        rect=rect,
                        primary=primary,
                        edid=edid,
                        read_vcp=read_vcp,
                    ),
                    item.hPhysicalMonitor,
                )
            )
        return True

    proc = bindings["MonitorEnumProc"](callback)
    enum_ok = bool(user32.EnumDisplayMonitors(None, None, proc, 0))
    if not enum_ok:
        err = ctypes.get_last_error()
        _destroy(bindings, arrays)
        raise DisplayError("probe_failed", winerr=err)
    return opened, arrays


def _raw_from_handle(
    dxva2,
    dword,
    *,
    handle,
    device: str,
    description: str,
    rect: tuple[int, int, int, int],
    primary: bool,
    edid: bytes | None,
    read_vcp: bool,
) -> RawMonitor:
    current: int | None = None
    maximum: int | None = None
    winerr: int | None = None
    vcp_ok = False
    caps: str | None = None
    reads: tuple[VcpSample, ...] = ()
    if read_vcp:
        ok, current, maximum, winerr = _get_vcp(dxva2, dword, handle, LUMINANCE_VCP)
        vcp_ok = ok
        caps = _resolve_handle_caps(
            dxva2,
            dword,
            handle,
            vcp_ok=vcp_ok,
            edid=edid,
            device=device,
            rect=rect,
            primary=primary,
        )
        if vcp_ok:
            reads = _resolve_extra_reads(
                dxva2,
                dword,
                handle,
                caps=caps,
                edid=edid,
                device=device,
                rect=rect,
                primary=primary,
            )
    return RawMonitor(
        device=device,
        description=description,
        rect=rect,
        primary=primary,
        edid=edid,
        caps=caps,
        vcp_ok=vcp_ok,
        current=current,
        maximum=maximum,
        winerr=winerr,
        reads=reads,
    )


def _get_vcp(dxva2, dword, handle, code: int) -> tuple[bool, int | None, int | None, int | None]:
    """One GetVCPFeatureAndVCPFeatureReply. Returns ok, current, maximum, winerr."""
    vtype = dword()
    cur = dword()
    maxv = dword()
    ok = bool(
        dxva2.GetVCPFeatureAndVCPFeatureReply(
            handle,
            code,
            ctypes.byref(vtype),
            ctypes.byref(cur),
            ctypes.byref(maxv),
        )
    )
    if ok:
        return True, int(cur.value), int(maxv.value), None
    return False, None, None, int(ctypes.get_last_error())


def _resolve_extra_reads(
    dxva2,
    dword,
    handle,
    *,
    caps: str | None,
    edid: bytes | None,
    device: str,
    rect: tuple[int, int, int, int],
    primary: bool,
) -> tuple[VcpSample, ...]:
    """Serial known-safe GetVCP after luminance. Never writes."""
    key = caps_cache_key(edid=edid, device=device, rect=rect, primary=primary)
    hit, prior = _PROBE_CACHE.get(key)
    outcomes = dict(prior or {})
    known_usable = frozenset(code for code, ok in outcomes.items() if ok)
    known_failed = frozenset(code for code, ok in outcomes.items() if not ok)
    wanted = codes_to_probe(caps, luminance_ok=True, known_usable=known_usable)
    samples: list[VcpSample] = []
    changed = False
    for code in wanted:
        if code in known_failed:
            continue
        ok, current, maximum, _winerr = _get_vcp(dxva2, dword, handle, code)
        if ok and current is not None and maximum is not None:
            samples.append(VcpSample(code=code, current=current, maximum=maximum))
            if outcomes.get(code) is not True:
                outcomes[code] = True
                changed = True
        else:
            if outcomes.get(code) is not False:
                outcomes[code] = False
                changed = True
    if changed or (not hit and outcomes):
        _PROBE_CACHE.put(key, outcomes)
    return tuple(samples)


def _resolve_handle_caps(
    dxva2,
    dword,
    handle,
    *,
    vcp_ok: bool,
    edid: bytes | None,
    device: str,
    rect: tuple[int, int, int, int],
    primary: bool,
) -> str | None:
    key = caps_cache_key(edid=edid, device=device, rect=rect, primary=primary)
    hit, cached = _CAPS_CACHE.get(key)
    caps, did_read = resolve_caps(
        vcp_ok=vcp_ok,
        cache_hit=hit,
        cached=cached,
        read=lambda: _read_caps(dxva2, dword, handle),
    )
    if did_read:
        _CAPS_CACHE.put(key, caps)
    return caps


def _read_caps(dxva2, dword, handle) -> str | None:
    length = dword()
    if not dxva2.GetCapabilitiesStringLength(handle, ctypes.byref(length)) or length.value == 0:
        return None
    # Cap the buffer. A hostile or stuck reply should not allocate unbounded memory.
    size = int(length.value)
    if size <= 0 or size > 8192:
        return None
    buf = ctypes.create_string_buffer(size)
    if not dxva2.CapabilitiesRequestAndCapabilitiesReply(handle, buf, size):
        return None
    return buf.value.decode("ascii", errors="replace")


def _read_edid(user32, display_cls, device_name: str) -> bytes | None:
    device = display_cls()
    device.cb = ctypes.sizeof(display_cls)
    if not device_name or not user32.EnumDisplayDevicesW(device_name, 0, ctypes.byref(device), 0):
        return None
    return read_edid_from_registry(
        WinregReader(),
        device_id=_clean(device.DeviceID),
        device_key=_clean(device.DeviceKey),
    )


def _destroy(bindings: dict[str, Any], arrays: list[Any]) -> None:
    dxva2 = bindings.get("dxva2")
    if dxva2 is None:
        return
    for arr in arrays:
        try:
            dxva2.DestroyPhysicalMonitors(len(arr), arr)
        except Exception:
            # Destroying must not turn a finished write into a second write.
            continue


def _clean(text: str) -> str:
    return str(text).replace("\x00", "").strip()
