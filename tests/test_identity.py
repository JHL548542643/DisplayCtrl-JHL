from displayctl.identity import (
    caps_declares_luminance,
    encode_edid,
    identify,
    parse_caps_model,
    parse_edid,
    same_raw,
)
from displayctl.models import RawMonitor


def _raw(**overrides) -> RawMonitor:
    base = dict(
        device=r"\\.\DISPLAY2",
        description="Generic PnP Monitor",
        rect=(0, 0, 1920, 1080),
        primary=False,
        edid=None,
        caps=None,
        vcp_ok=False,
        current=None,
        maximum=None,
        winerr=31,
    )
    base.update(overrides)
    return RawMonitor(**base)


def test_dell_manufacturer_id_roundtrip():
    edid = encode_edid("DEL", 0x4142, serial_text="CN123456", name="DELL U2723QE")
    parsed = parse_edid(edid)
    assert parsed is not None
    assert parsed.manufacturer == "DEL"
    assert parsed.product_code == "4142"
    assert parsed.serial == "CN123456"
    assert parsed.name == "DELL U2723QE"
    assert int.from_bytes(edid[8:10], "big") == 0x10AC


def test_serial_dword_used_when_text_missing():
    parsed = parse_edid(encode_edid("GSM", 0x0001, serial=99))
    assert parsed is not None
    assert parsed.serial == "99"


def test_zero_serial_is_not_an_identity():
    parsed = parse_edid(encode_edid("GSM", 0x0001, serial=0))
    assert parsed is not None
    assert parsed.serial is None


def test_bad_checksum_is_ignored():
    edid = bytearray(encode_edid("GSM", 0x0001, serial_text="ABC"))
    edid[20] ^= 0xFF
    assert parse_edid(bytes(edid)) is None


def test_caps_model_and_luminance_flag():
    caps = "(prot(monitor)type(LCD)model(27G2)vcp(10 12 14(05 08) 16))"
    assert parse_caps_model(caps) == "27G2"
    assert caps_declares_luminance(caps) is True
    assert caps_declares_luminance("(vcp(12 14))") is False
    assert caps_declares_luminance("model(only)") is None
    assert parse_caps_model("model(no-close") is None


def test_same_raw_follows_edid_when_display_index_changes():
    edid = encode_edid("GSM", 0x5B05, serial_text="K1")
    before = _raw(device=r"\\.\DISPLAY1", edid=edid, rect=(0, 0, 100, 100))
    after = _raw(device=r"\\.\DISPLAY4", edid=edid, rect=(1920, 0, 3000, 1080))
    assert same_raw(before, after)


def test_same_raw_does_not_guess_without_edid():
    left = _raw(rect=(0, 0, 100, 100))
    moved = _raw(rect=(10, 0, 110, 100))
    assert same_raw(left, left)
    assert not same_raw(left, moved)
    assert not same_raw(left, _raw(edid=encode_edid("GSM", 1, serial_text="A")))


def test_identify_prefers_edid_serial():
    raw = _raw(
        edid=encode_edid("GSM", 0x5B05, serial_text="K1 A"),
        caps="model(27G2)",
        vcp_ok=True,
        current=40,
        maximum=100,
        winerr=None,
    )
    ident = identify(raw)
    assert ident.id == "edid:GSM:5B05:K1_A"
    assert ident.quality == "strong"
    assert ident.stable is True
    assert ident.model == "27G2"
