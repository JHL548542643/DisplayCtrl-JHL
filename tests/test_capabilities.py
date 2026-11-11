"""Capability records from the 0x10 get, caps declaration, and GetVCP probes.

Contrast is read-only. Nothing here issues SetVCP for contrast.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from displayctl.api import build_app
from displayctl.assemble import build_records
from displayctl.demo import demo_service
from displayctl.identity import caps_declares_luminance, declared_vcp_codes, encode_edid
from displayctl.models import RawMonitor, VcpSample
from displayctl.policy import (
    CONTRAST_VCP,
    INPUT_SOURCE_VCP,
    POWER_MODE_VCP,
    RGB_GAIN_B_VCP,
    RGB_GAIN_G_VCP,
    RGB_GAIN_R_VCP,
    VOLUME_VCP,
)


def _raw(**overrides) -> RawMonitor:
    base = dict(
        device=r"\\.\DISPLAY2",
        description="Generic PnP Monitor",
        rect=(0, 0, 1920, 1080),
        primary=False,
        edid=encode_edid("GSM", 0x5B05, serial_text="K1"),
        caps="(model(27G2)vcp(10 12))",
        vcp_ok=True,
        current=40,
        maximum=100,
        winerr=None,
    )
    base.update(overrides)
    return RawMonitor(**base)


def test_vcp_section_ignores_nested_values_and_unclosed_text():
    caps = "(prot(monitor)type(LCD)model(27G2)vcp(10 12 14(05 08 10) 16))"
    assert declared_vcp_codes(caps) == frozenset({0x10, 0x12, 0x14, 0x16})
    assert declared_vcp_codes("(vcp(14(10 12)))") == frozenset({0x14})
    assert caps_declares_luminance("(vcp(14(10 12)))") is False
    assert declared_vcp_codes("(vcp(10 12") is None
    assert declared_vcp_codes("model(only)") is None
    assert declared_vcp_codes(None) is None


def test_capabilities_do_not_copy_the_code_list():
    view = build_records([_raw()])[0].view
    body = view.to_dict()
    assert body["luminance"] == {"current": 40, "maximum": 100, "vcp": "0x10"}
    assert body["capabilities"]["luminance"] == {
        "vcp": "0x10",
        "readable": True,
        "writable": True,
        "current": 40,
        "maximum": 100,
    }
    assert body["capabilities"]["contrast"] == {
        "vcp": "0x12",
        "declared": True,
        "readable": False,
        "writable": False,
        "current": None,
        "maximum": None,
    }
    assert body["capabilities"]["volume"]["declared"] is False
    assert body["capabilities"]["volume"]["readable"] is False
    assert body["capabilities"]["rgb_gains"]["declared"] is False
    assert body["capabilities"]["rgb_gains"]["readable"] is False
    assert body["capabilities"]["input_source"]["declared"] is False
    assert body["capabilities"]["input_source"]["readable"] is False
    assert body["capabilities"]["power_mode"]["declared"] is False
    assert body["capabilities"]["power_mode"]["readable"] is False
    assert "vcp_codes" not in body
    assert "vcp_codes" not in body["capabilities"]
    blob = json.dumps(body)
    assert "vcp(" not in blob
    assert "prot(monitor)" not in blob


def test_rich_caps_plus_probe_makes_contrast_readable():
    view = build_records(
        [
            _raw(
                caps="(model(27G2)vcp(10 12 14 16))",
                reads=(VcpSample(code=CONTRAST_VCP, current=70, maximum=100),),
            )
        ]
    )[0].view
    contrast = view.to_dict()["capabilities"]["contrast"]
    assert contrast["declared"] is True
    assert contrast["readable"] is True
    assert contrast["current"] == 70
    assert contrast["maximum"] == 100
    assert contrast["writable"] is True


def test_sparse_caps_plus_probe_makes_contrast_readable():
    view = build_records(
        [
            _raw(
                caps="(model(SPARSE)vcp(02))",
                reads=(VcpSample(code=CONTRAST_VCP, current=55, maximum=100),),
            )
        ]
    )[0].view
    contrast = view.to_dict()["capabilities"]["contrast"]
    assert contrast["declared"] is False
    assert contrast["readable"] is True
    assert contrast["current"] == 55
    assert contrast["maximum"] == 100
    assert contrast["writable"] is True


def test_rich_caps_plus_probe_makes_volume_and_rgb_readable():
    view = build_records(
        [
            _raw(
                caps="(model(RICH)vcp(10 12 16 18 1A 62))",
                reads=(
                    VcpSample(code=VOLUME_VCP, current=22, maximum=100),
                    VcpSample(code=RGB_GAIN_R_VCP, current=50, maximum=100),
                    VcpSample(code=RGB_GAIN_G_VCP, current=51, maximum=100),
                    VcpSample(code=RGB_GAIN_B_VCP, current=49, maximum=100),
                ),
            )
        ]
    )[0].view
    body = view.to_dict()["capabilities"]
    volume = body["volume"]
    assert volume["declared"] is True
    assert volume["readable"] is True
    assert volume["current"] == 22
    assert volume["writable"] is True
    rgb = body["rgb_gains"]
    assert rgb["declared"] is True
    assert rgb["readable"] is True
    assert rgb["writable"] is False
    assert rgb["red"]["current"] == 50
    assert rgb["green"]["current"] == 51
    assert rgb["blue"]["current"] == 49


def test_sparse_caps_plus_probe_makes_volume_and_rgb_readable():
    view = build_records(
        [
            _raw(
                caps="(model(SPARSE)vcp(02))",
                reads=(
                    VcpSample(code=VOLUME_VCP, current=10, maximum=100),
                    VcpSample(code=RGB_GAIN_R_VCP, current=40, maximum=100),
                    VcpSample(code=RGB_GAIN_G_VCP, current=41, maximum=100),
                    VcpSample(code=RGB_GAIN_B_VCP, current=42, maximum=100),
                ),
            )
        ]
    )[0].view
    body = view.to_dict()["capabilities"]
    assert body["volume"]["declared"] is False
    assert body["volume"]["readable"] is True
    assert body["volume"]["current"] == 10
    assert body["rgb_gains"]["declared"] is False
    assert body["rgb_gains"]["readable"] is True
    assert body["rgb_gains"]["blue"]["current"] == 42


def test_rich_caps_plus_probe_makes_input_and_power_readable():
    view = build_records(
        [
            _raw(
                caps="(model(RICH)vcp(10 12 16 18 1A 60 62 D6))",
                reads=(
                    VcpSample(code=INPUT_SOURCE_VCP, current=8, maximum=3),
                    VcpSample(code=POWER_MODE_VCP, current=1, maximum=4),
                ),
            )
        ]
    )[0].view
    body = view.to_dict()["capabilities"]
    source = body["input_source"]
    assert source["declared"] is True
    assert source["readable"] is True
    assert source["current"] == 8
    assert source["maximum"] == 3
    assert source["writable"] is False
    assert source["vcp"] == "0x60"
    power = body["power_mode"]
    assert power["declared"] is True
    assert power["readable"] is True
    assert power["current"] == 1
    assert power["maximum"] == 4
    assert power["writable"] is False
    assert power["vcp"] == "0xD6"


def test_sparse_caps_plus_probe_makes_input_and_power_readable():
    view = build_records(
        [
            _raw(
                caps="(model(SPARSE)vcp(02))",
                reads=(
                    VcpSample(code=INPUT_SOURCE_VCP, current=50, maximum=100),
                    VcpSample(code=POWER_MODE_VCP, current=1, maximum=5),
                ),
            )
        ]
    )[0].view
    body = view.to_dict()["capabilities"]
    assert body["input_source"]["declared"] is False
    assert body["input_source"]["readable"] is True
    assert body["input_source"]["current"] == 50
    assert body["power_mode"]["declared"] is False
    assert body["power_mode"]["readable"] is True
    assert body["power_mode"]["current"] == 1


def test_missing_caps_section_leaves_contrast_unknown_without_probe():
    view = build_records([_raw(caps="(model(27G2))", vcp_ok=True, current=20, maximum=100)])[0].view
    body = view.to_dict()
    assert body["capabilities"]["luminance"]["writable"] is True
    assert body["capabilities"]["contrast"] is None


def test_probe_without_caps_section_still_exposes_contrast():
    view = build_records(
        [
            _raw(
                caps="(model(27G2))",
                reads=(VcpSample(code=CONTRAST_VCP, current=40, maximum=100),),
            )
        ]
    )[0].view
    contrast = view.to_dict()["capabilities"]["contrast"]
    assert contrast["declared"] is False
    assert contrast["readable"] is True
    assert contrast["current"] == 40


def test_declared_without_twelve_is_luminance_only():
    view = build_records([_raw(caps="(model(GW2480)vcp(10))")])[0].view
    caps = view.to_dict()["capabilities"]
    assert caps["volume"]["declared"] is False
    assert caps["volume"]["readable"] is False
    assert caps["rgb_gains"]["declared"] is False
    assert caps["rgb_gains"]["readable"] is False
    assert caps["input_source"]["declared"] is False
    assert caps["input_source"]["readable"] is False
    assert caps["power_mode"]["declared"] is False
    assert caps["power_mode"]["readable"] is False
    contrast = caps["contrast"]
    assert contrast["declared"] is False
    assert contrast["writable"] is False
    assert contrast["readable"] is False


def test_readable_luminance_stays_unwritable_when_identity_is_unstable():
    view = build_records(
        [
            _raw(
                edid=None,
                caps="(vcp(10))",
                description="Mystery",
                vcp_ok=True,
                current=33,
                maximum=100,
            )
        ]
    )[0].view
    assert view.writable is False
    assert view.failure == "identity_unstable"
    luminance = view.to_dict()["capabilities"]["luminance"]
    assert luminance["readable"] is True
    assert luminance["writable"] is False
    assert luminance["current"] == 33
    assert view.to_dict()["capabilities"]["contrast"]["declared"] is False


def test_contrast_declaration_survives_a_failed_luminance_read():
    view = build_records(
        [_raw(vcp_ok=False, current=None, maximum=None, winerr=31, caps="(vcp(12))")]
    )[0].view
    body = view.to_dict()
    assert body["writable"] is False
    assert body["luminance"] is None
    assert body["capabilities"]["luminance"]["readable"] is False
    assert body["capabilities"]["contrast"]["declared"] is True
    assert body["capabilities"]["contrast"]["readable"] is False
    assert body["capabilities"]["contrast"]["writable"] is False


def test_demo_api_shape_differs_per_monitor_and_does_not_write():
    service = demo_service()
    client = TestClient(build_app(service))
    listed = client.get("/api/monitors")
    assert listed.status_code == 200
    monitors = listed.json()["monitors"]
    assert service.backend.set_calls == []

    by_model = {monitor["model"]: monitor for monitor in monitors}
    bright = by_model["27G2"]
    plain = by_model["GW2480"]
    assert bright["capabilities"]["luminance"]["writable"] is True
    assert bright["capabilities"]["luminance"]["current"] == 42
    assert bright["capabilities"]["contrast"]["declared"] is True
    assert bright["capabilities"]["contrast"]["readable"] is True
    assert bright["capabilities"]["contrast"]["current"] == 55
    assert bright["capabilities"]["contrast"]["writable"] is True
    assert bright["capabilities"]["volume"]["readable"] is True
    assert bright["capabilities"]["volume"]["current"] == 30
    assert bright["capabilities"]["volume"]["writable"] is True
    assert bright["capabilities"]["rgb_gains"]["readable"] is True
    assert bright["capabilities"]["rgb_gains"]["red"]["current"] == 50
    assert bright["capabilities"]["rgb_gains"]["writable"] is False
    assert bright["capabilities"]["input_source"]["readable"] is True
    assert bright["capabilities"]["input_source"]["current"] == 15
    assert bright["capabilities"]["input_source"]["writable"] is False
    assert bright["capabilities"]["power_mode"]["readable"] is True
    assert bright["capabilities"]["power_mode"]["current"] == 1
    assert bright["capabilities"]["power_mode"]["writable"] is False
    assert plain["capabilities"]["luminance"]["writable"] is True
    assert plain["capabilities"]["luminance"]["current"] == 28
    assert plain["capabilities"]["contrast"]["declared"] is False
    assert plain["capabilities"]["contrast"]["readable"] is False
    assert plain["capabilities"]["volume"] is None or plain["capabilities"]["volume"]["readable"] is False
    assert plain["capabilities"]["input_source"] is None or plain["capabilities"]["input_source"]["readable"] is False
    assert plain["capabilities"]["power_mode"] is None or plain["capabilities"]["power_mode"]["readable"] is False

    dark = [monitor for monitor in monitors if monitor["capabilities"]["luminance"]["readable"] is False]
    assert {monitor["failure"] for monitor in dark} >= {"ddc_off", "cable", "internal_panel"}
    assert all(monitor["capabilities"]["contrast"] is None for monitor in dark)
    assert all(monitor["luminance"] is None for monitor in dark)

    one = client.get(f"/api/monitors/{bright['id']}")
    assert one.status_code == 200
    assert one.json()["monitor"]["capabilities"]["contrast"]["vcp"] == "0x12"
    assert service.backend.set_calls == []
    assert client.get("/api/health").json()["policy"]["vcp"] == ["0x10", "0x12", "0x62"]
    assert "/contrast" in Path("displayctl/api.py").read_text(encoding="utf-8")
    assert "/volume" in Path("displayctl/api.py").read_text(encoding="utf-8")


def test_preview_sample_matches_demo_ids():
    text = Path("web/src/demoData.ts").read_text(encoding="utf-8")
    views = demo_service().probe()
    assert text.count("\n    id: ") == len(views)
    for view in views:
        assert f'id: "{view.id}"' in text
        rect = ", ".join(str(part) for part in view.rect)
        assert f"rect: [{rect}]" in text
    assert "declared: true" in text
    assert "declared: false" in text
    assert "readable: true" in text
    assert "current: 55" in text
    assert "volume" in text.lower() or "0x62" in text or "音量" in text or "30" in text
    assert "input_source" in text or "0x60" in text or "15" in text
    assert "power_mode" in text or "0xD6" in text


def test_console_writes_only_through_the_existing_call():
    app = Path("web/src/App.tsx").read_text(encoding="utf-8")
    desktop = Path("web/src/DesktopLayout.tsx").read_text(encoding="utf-8")
    assert "MonitorCard" not in app
    assert "setLuminance" in app and "setContrast" in app and "setVolume" in app
    assert "setLuminance" not in desktop
    assert "confirm" not in desktop
    assert desktop.count('type="range"') >= 2
    assert "apply-brightness" in desktop
    assert "apply-${testId}" in desktop
    assert 'feature="contrast"' in desktop or 'feature: "contrast"' in desktop
    assert "capability-contrast" in desktop
    assert "capability-volume" in desktop
    assert "capability-rgb" in desktop
    assert "capability-input" in desktop
    assert "capability-power" in desktop
    assert "contrastVisible" in desktop
    assert "volumeVisible" in desktop
    assert "rgbVisible" in desktop
    assert "inputSourceVisible" in desktop
    assert "powerModeVisible" in desktop


def test_luminance_commit_stays_out_of_the_slider_row():
    desktop = Path("web/src/DesktopLayout.tsx").read_text(encoding="utf-8")
    css = Path("web/src/styles.css").read_text(encoding="utf-8")
    slider = desktop.split('className="tile-slider"', 1)[1].split("</label>", 1)[0]
    assert "apply-brightness" not in slider
    assert "撤销" not in slider
    rule = css.split(".tile-commit {", 1)[1].split("}", 1)[0]
    assert "position: absolute" in rule
    control = css.split(".tile-control {", 1)[1].split("}", 1)[0]
    assert "height: 28px" in control


def test_dxva2_getvcp_may_read_known_safe_and_set_allowlisted():
    source = Path("displayctl/dxva2_win.py").read_text(encoding="utf-8")
    assert "0x12" not in source
    assert "0x62" not in source
    assert "0x16" not in source
    assert "CONTRAST_VCP" not in source
    assert "VOLUME_VCP" not in source
    assert "codes_to_probe" in source
    assert "_resolve_extra_reads" in source
    assert source.count("SetVCPFeature(") == 1
    assert source.count("GetVCPFeatureAndVCPFeatureReply(") == 1
    assert "ensure_write_code" in source
    assert "set_vcp_raw" in source
