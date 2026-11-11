"""Registry EDID selection. No monitor and no real registry."""

from pathlib import Path

from displayctl.caps_cache import caps_cache_key
from displayctl.edid_reg import parse_monitor_device_id, read_edid_from_registry
from displayctl.identity import encode_edid

_GUID = "{4d36e96e-e325-11ce-bfc1-08002be10318}"
_Q27 = encode_edid("AOC", 0xB433, serial_text="Q27")
_Q24 = encode_edid("AOC", 0x2410, serial_text="Q24")
_PANEL = encode_edid("LEN", 0x41F5, serial_text="LCD")


class FakeReg:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {}
        self.children: dict[str, list[str]] = {}

    def subkeys(self, path: str) -> list[str]:
        return list(self.children.get(path, []))

    def value(self, path: str, name: str) -> object | None:
        return self.values.get(path, {}).get(name)

    def add_enum(
        self,
        monitor_id: str,
        instance: str,
        driver: str,
        edid: bytes | None,
        *,
        hardware_id: object = None,
    ) -> None:
        root = rf"SYSTEM\CurrentControlSet\Enum\DISPLAY\{monitor_id}"
        inst = rf"{root}\{instance}"
        self.children.setdefault(root, []).append(instance)
        hw = hardware_id if hardware_id is not None else [rf"MONITOR\{monitor_id}"]
        self.values[inst] = {"HardwareID": hw, "Driver": driver}
        if edid is not None:
            self.values[rf"{inst}\Device Parameters"] = {"EDID": edid}

    def add_class(self, device_key_suffix: str, edid: bytes) -> None:
        path = rf"System\CurrentControlSet\Control\Class\{device_key_suffix}\Device Parameters"
        self.values[path] = {"EDID": edid}


def _device_id(monitor_id: str, instance: str = "0003") -> str:
    return rf"MONITOR\{monitor_id}\{_GUID}\{instance}"


def _class_key(instance: str = "0001") -> str:
    return rf"\Registry\Machine\System\CurrentControlSet\Control\Class\{_GUID}\{instance}"


def test_device_id_exposes_monitor_id_and_active_driver():
    parsed = parse_monitor_device_id(_device_id("AOCB433", "0003"))
    assert parsed == ("AOCB433", rf"{_GUID}\0003")
    assert parse_monitor_device_id(r"MONITOR\AOCB433\not-a-guid\0003") is None
    assert parse_monitor_device_id("MONITOR\\..\\" + _GUID + r"\0003") is None
    assert parse_monitor_device_id("MONITOR\\AOC\\B433\\" + _GUID + r"\0003") is None


def test_enum_display_edid_is_used_when_class_device_parameters_is_missing():
    reg = FakeReg()
    reg.add_enum("AOCB433", r"5&aaa&0&UID256", rf"{_GUID}\0003", _Q27)
    reg.add_enum("AOCB433", r"5&old&0&UID1", rf"{_GUID}\0001", _Q24)
    block = read_edid_from_registry(
        reg,
        device_id=_device_id("AOCB433", "0003"),
        device_key=_class_key("0003"),
    )
    assert block == _Q27
    key = caps_cache_key(
        edid=block,
        device=r"\\.\DISPLAY3",
        rect=(0, 0, 2560, 1440),
        primary=False,
    )
    moved = caps_cache_key(
        edid=block,
        device=r"\\.\DISPLAY9",
        rect=(1920, 0, 4480, 1440),
        primary=True,
    )
    assert key is not None and key == moved


def test_each_active_driver_keeps_its_own_block():
    reg = FakeReg()
    reg.add_enum("AOCB433", r"5&q27&0&UID256", rf"{_GUID}\0003", _Q27)
    reg.add_enum(
        "AOC2410",
        r"5&q24&0&UID257",
        rf"{_GUID}\0004",
        _Q24,
        hardware_id=r"MONITOR\AOC2410",
    )
    reg.add_enum("LEN41F5", r"5&lcd&0&UID0", rf"{_GUID}\0000", _PANEL)
    q27 = read_edid_from_registry(reg, device_id=_device_id("AOCB433", "0003"), device_key="")
    q24 = read_edid_from_registry(reg, device_id=_device_id("AOC2410", "0004"), device_key="")
    panel = read_edid_from_registry(reg, device_id=_device_id("LEN41F5", "0000"), device_key="")
    assert q27 == _Q27 and q24 == _Q24 and panel == _PANEL
    keys = [
        caps_cache_key(edid=block, device=r"\\.\DISPLAY2", rect=(0, 0, 10, 10), primary=False)
        for block in (q27, q24, panel)
    ]
    assert all(key is not None for key in keys)
    assert len(set(keys)) == 3


def test_conflicting_active_blocks_are_not_guessed_and_do_not_use_the_class_key():
    other = encode_edid("AOC", 0xB433, serial_text="OTHER")
    reg = FakeReg()
    reg.add_enum("AOCB433", r"5&a&0&UID1", rf"{_GUID}\0003", _Q27)
    reg.add_enum("AOCB433", r"5&b&0&UID2", rf"{_GUID}\0003", other)
    reg.add_class(rf"{_GUID}\0003", _Q24)
    assert (
        read_edid_from_registry(
            reg,
            device_id=_device_id("AOCB433", "0003"),
            device_key=_class_key("0003"),
        )
        is None
    )
    assert caps_cache_key(edid=None, device=r"\\.\DISPLAY3", rect=(0, 0, 1, 1), primary=False) is None


def test_duplicate_instances_with_the_same_block_are_safe():
    reg = FakeReg()
    reg.add_enum("AOCB433", r"5&a&0&UID1", rf"{_GUID}\0003", _Q27)
    reg.add_enum("AOCB433", r"5&b&0&UID2", rf"{_GUID.lower()}\0003", bytearray(_Q27))
    assert (
        read_edid_from_registry(reg, device_id=_device_id("AOCB433"), device_key="")
        == _Q27
    )


def test_hardware_id_must_name_this_monitor():
    reg = FakeReg()
    reg.add_enum(
        "AOCB433",
        r"5&a&0&UID1",
        rf"{_GUID}\0003",
        _Q27,
        hardware_id=["MONITOR\\OTHER1"],
    )
    assert read_edid_from_registry(reg, device_id=_device_id("AOCB433"), device_key="") is None


def test_bad_active_edid_does_not_fall_through_to_the_class_key():
    bad = bytearray(_Q27)
    bad[20] ^= 0xFF
    reg = FakeReg()
    reg.add_enum("AOCB433", r"5&a&0&UID1", rf"{_GUID}\0003", bytes(bad))
    reg.add_class(rf"{_GUID}\0003", _Q24)
    assert (
        read_edid_from_registry(
            reg,
            device_id=_device_id("AOCB433", "0003"),
            device_key=_class_key("0003"),
        )
        is None
    )


def test_class_key_is_used_only_when_no_enum_instance_matches():
    reg = FakeReg()
    reg.add_enum("AOCB433", r"5&old&0&UID1", rf"{_GUID}\0001", _Q27)
    reg.add_class(rf"{_GUID}\0003", _Q24)
    assert (
        read_edid_from_registry(
            reg,
            device_id=_device_id("AOCB433", "0003"),
            device_key=_class_key("0003"),
        )
        == _Q24
    )


def test_class_key_still_works_when_device_id_is_not_a_monitor_path():
    reg = FakeReg()
    reg.add_class(rf"{_GUID}\0002", _PANEL)
    assert (
        read_edid_from_registry(
            reg,
            device_id="not-a-monitor",
            device_key=_class_key("0002"),
        )
        == _PANEL
    )


def test_truncated_class_key_and_path_segments_are_not_opened():
    reg = FakeReg()
    reg.children[r"SYSTEM\CurrentControlSet\Enum\DISPLAY\AOCB433"] = ["..", r"foo\bar", "5&ok&0&UID1"]
    reg.values[r"SYSTEM\CurrentControlSet\Enum\DISPLAY\AOCB433\5&ok&0&UID1"] = {
        "HardwareID": ["MONITOR\\AOCB433"],
        "Driver": rf"{_GUID}\0003",
    }
    reg.values[r"SYSTEM\CurrentControlSet\Enum\DISPLAY\AOCB433\5&ok&0&UID1\Device Parameters"] = {
        "EDID": _Q27
    }
    reg.values[r"System\CurrentControlSet\Control\Class"] = {"EDID": _Q24}
    assert read_edid_from_registry(reg, device_id=_device_id("AOCB433"), device_key="truncated") == _Q27
    assert read_edid_from_registry(reg, device_id="", device_key=r"\Registry\Machine\oops") is None


def test_dxva2_reads_edid_through_the_registry_helper():
    source = Path("displayctl/dxva2_win.py").read_text(encoding="utf-8")
    assert "read_edid_from_registry" in source
    assert source.count("SetVCPFeature(") == 1
    assert "Thread(" not in source
    assert "Enum\\DISPLAY" in Path("displayctl/edid_reg.py").read_text(encoding="utf-8")
