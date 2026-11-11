"""Registry EDID lookup. Pure aside from ``WinregReader``.

``EnumDisplayDevicesW`` ``DeviceKey`` points at
``Control\\Class\\{4d36e96e-…}\\NNNN``. On some machines that key has no
``Device Parameters`` subkey, while the block is stored under
``Enum\\DISPLAY\\<id>\\<instance>\\Device Parameters\\EDID``.

``DeviceID`` (``MONITOR\\AOCB433\\{guid}\\0003``) names the active instance:
the folder is the monitor id, and ``Driver`` on that instance equals the
``{guid}\\0003`` suffix. Stale instance keys stay in the same folder. If more
than one instance matches and the blocks differ, this returns None so two
panels cannot share a capabilities-cache entry.
"""

from __future__ import annotations

import re
from typing import Protocol

from displayctl.identity import parse_edid

_GUID = r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
_DEVICE_ID_RE = re.compile(
    rf"^MONITOR\\([^\\]+)\\(\{{{_GUID}}}\\[0-9]{{4}})$",
    re.IGNORECASE,
)
_MONITOR_ID_RE = re.compile(r"^[A-Za-z0-9]{3,32}$")
_ENUM_DISPLAY = r"SYSTEM\CurrentControlSet\Enum\DISPLAY"
_CLASS_MARKER = "system\\currentcontrolset\\"


class RegistryReader(Protocol):
    def subkeys(self, path: str) -> list[str]:
        """Child key names. Missing keys are an empty list, not an error."""

    def value(self, path: str, name: str) -> object | None:
        """One value, or None when the key or value is absent."""


def parse_monitor_device_id(device_id: str) -> tuple[str, str] | None:
    """Return ``(monitor_id, driver)`` from an active ``DeviceID``.

    ``driver`` is the ``{guid}\\\\NNNN`` suffix Windows stores on the enum
    instance. Anything that is not this shape, including a monitor id that
    could escape the ``Enum\\DISPLAY`` folder, is ignored.
    """
    text = str(device_id).replace("/", "\\").replace("\x00", "").strip().strip("\\")
    match = _DEVICE_ID_RE.fullmatch(text)
    if match is None:
        return None
    monitor_id, driver = match.group(1), match.group(2)
    if _MONITOR_ID_RE.fullmatch(monitor_id) is None:
        return None
    return monitor_id, driver


def read_edid_from_registry(
    reader: RegistryReader,
    *,
    device_id: str,
    device_key: str,
) -> bytes | None:
    """128-byte base block for this output, or None.

    The ``Enum\\DISPLAY`` match wins. A conflict, or a matching instance whose
    block does not parse, does not fall through to the class key. The class
    ``DeviceKey`` path is only used when no instance matches this output.
    """
    parsed = parse_monitor_device_id(device_id)
    if parsed is not None:
        status, block = _from_enum_display(reader, parsed[0], parsed[1])
        if status == "hit":
            return block
        # A real Enum\DISPLAY instance matched this output. Do not replace a
        # missing or disagreeing block with the class key.
        if status == "reject":
            return None
    return _from_class_key(reader, device_key)


def _from_enum_display(
    reader: RegistryReader,
    monitor_id: str,
    driver: str,
) -> tuple[str, bytes | None]:
    root = rf"{_ENUM_DISPLAY}\{monitor_id}"
    wanted_driver = _norm_driver(driver)
    wanted_id = f"MONITOR\\{monitor_id}".casefold()
    matched = False
    blocks: list[bytes] = []
    for name in reader.subkeys(root):
        if not _safe_segment(name):
            continue
        instance = rf"{root}\{name}"
        if wanted_id not in _id_tokens(reader.value(instance, "HardwareID")):
            continue
        if _norm_driver(reader.value(instance, "Driver")) != wanted_driver:
            continue
        matched = True
        block = _edid_block(reader.value(rf"{instance}\Device Parameters", "EDID"))
        if block is not None:
            blocks.append(block)
    if not matched:
        return "miss", None
    if not blocks:
        return "reject", None
    first = blocks[0]
    if all(item == first for item in blocks):
        return "hit", first
    return "reject", None


def _from_class_key(reader: RegistryReader, device_key: str) -> bytes | None:
    subkey = _class_subkey(device_key)
    if not subkey:
        return None
    return _edid_block(reader.value(subkey + r"\Device Parameters", "EDID"))


def _class_subkey(device_key: str) -> str | None:
    text = str(device_key).replace("/", "\\").replace("\x00", "")
    index = text.lower().find(_CLASS_MARKER)
    if index < 0:
        return None
    subkey = text[index:].strip("\\")
    if not subkey or ".." in subkey.split("\\"):
        return None
    return subkey


def _edid_block(value: object) -> bytes | None:
    if isinstance(value, str) or not isinstance(value, (bytes, bytearray)):
        return None
    block = bytes(value)
    if parse_edid(block) is None:
        return None
    return block[:128]


def _id_tokens(value: object) -> set[str]:
    tokens: set[str] = set()
    for item in _strings(value):
        text = item.replace("/", "\\").replace("\x00", "").strip().strip("\\")
        if text:
            tokens.add(text.casefold())
    return tokens


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str)]
    return []


def _norm_driver(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace("/", "\\").replace("\x00", "").strip().strip("\\").casefold()


def _safe_segment(name: str) -> bool:
    return bool(name) and name not in {".", ".."} and "\\" not in name and "/" not in name


class WinregReader:
    """HKLM reader. Failures are misses so a probe still returns the other panels."""

    def subkeys(self, path: str) -> list[str]:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, _read_access(winreg)) as key:
                count = winreg.QueryInfoKey(key)[0]
                return [winreg.EnumKey(key, index) for index in range(count)]
        except OSError:
            return []

    def value(self, path: str, name: str) -> object | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, _read_access(winreg)) as key:
                data, _typ = winreg.QueryValueEx(key, name)
                return data
        except OSError:
            return None


def _read_access(winreg) -> int:
    # SYSTEM\Enum is not under Wow6432Node. A 32-bit interpreter should still
    # see the native key instead of a redirected view.
    return winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
