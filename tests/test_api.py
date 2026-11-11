import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from displayctl.api import build_app, resolve_bind_host, resolve_port
from displayctl.demo import demo_backend, demo_service
from displayctl.service import DisplayService


class _Clock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now


def test_bind_host_is_loopback_only():
    assert resolve_bind_host(None) == "127.0.0.1"
    assert resolve_bind_host("localhost") == "127.0.0.1"
    assert resolve_bind_host("::1") == "::1"
    for host in ("0.0.0.0", "::", "192.168.1.5", "10.0.0.8"):
        with pytest.raises(SystemExit):
            resolve_bind_host(host)


def test_port_range():
    assert resolve_port(8765) == 8765
    with pytest.raises(SystemExit):
        resolve_port(0)
    with pytest.raises(SystemExit):
        resolve_port(True)  # type: ignore[arg-type]


def test_demo_health_and_safe_set():
    backend = demo_backend()
    service = DisplayService(backend, sleep=lambda _seconds: None, clock=_Clock(), demo=True)
    client = TestClient(build_app(service))
    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["loopback_only"] is True
    assert body["demo"] is True
    assert body["policy"]["vcp"] == ["0x10", "0x12", "0x62"]
    assert body["backend"] == "memory"

    listed = client.get("/api/monitors")
    assert listed.status_code == 200
    monitors = listed.json()["monitors"]
    writable = [monitor for monitor in monitors if monitor["writable"]]
    gsm = next(monitor for monitor in writable if monitor["id"].startswith("edid:GSM:"))
    assert gsm["stable"] is True
    failures = {monitor["failure"] for monitor in monitors if monitor["failure"]}
    assert {"ddc_off", "cable", "internal_panel"} <= failures

    monitor_id = gsm["id"]
    rejected = client.post(
        f"/api/monitors/{monitor_id}/luminance",
        json={"value": 30, "confirm": False},
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["kind"] == "confirm_required"
    assert backend.set_calls == []

    applied = client.post(
        f"/api/monitors/{monitor_id}/luminance",
        json={"value": 30, "confirm": True},
    )
    assert applied.status_code == 200
    assert applied.json()["result"]["verified"] == 30
    assert applied.json()["result"]["previous"] == 42

    again = client.post(
        f"/api/monitors/{monitor_id}/luminance",
        json={"value": 55, "confirm": True},
    )
    assert again.status_code == 429

    blocked = next(monitor for monitor in monitors if monitor["failure"] == "internal_panel")
    refused = client.post(
        f"/api/monitors/{blocked['id']}/luminance",
        json={"value": 40, "confirm": True},
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["kind"] == "internal_panel"



def test_contrast_and_volume_api_require_confirm():
    from displayctl.demo import demo_service
    from displayctl.api import build_app
    from fastapi.testclient import TestClient

    service = demo_service()
    client = TestClient(build_app(service))
    monitor_id = next(
        m["id"] for m in client.get("/api/monitors").json()["monitors"] if m["model"] == "27G2"
    )
    refused = client.post(
        f"/api/monitors/{monitor_id}/contrast", json={"value": 50, "confirm": False}
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["kind"] == "confirm_required"
    assert service.backend.vcp_writes == []
    ok = client.post(
        f"/api/monitors/{monitor_id}/contrast", json={"value": 50, "confirm": True}
    )
    assert ok.status_code == 200
    assert ok.json()["result"]["verified"] == 50


def test_api_rejects_extra_fields_and_remote_clients():
    client = TestClient(build_app(demo_service()))
    listed = client.get("/api/monitors").json()["monitors"]
    monitor_id = next(monitor["id"] for monitor in listed if monitor["writable"])
    extra = client.post(
        f"/api/monitors/{monitor_id}/luminance",
        json={"value": 20, "confirm": True, "vcp": "0x04"},
    )
    assert extra.status_code == 422

    remote = TestClient(build_app(demo_service()), client=("192.168.1.20", 50000))
    assert remote.get("/api/health").status_code == 403


def test_static_ui_does_not_shadow_api(tmp_path: Path):
    (tmp_path / "index.html").write_text("UI", encoding="utf-8")
    client = TestClient(build_app(demo_service(), static_dir=tmp_path))
    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/").text == "UI"


def test_docs_and_ui_contract():
    safety = Path("docs/SAFETY.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    css = Path("web/src/styles.css").read_text(encoding="utf-8")
    api = Path("web/src/api.ts").read_text(encoding="utf-8")
    for needle in ("0x10", "127.0.0.1", "EDID", "回滚", "ddc_off", "internal_panel"):
        assert needle in safety
    assert "set_luminance_safe" in architecture
    assert '[data-theme="day"]' in css
    assert "--accent" in css
    assert "127.0.0.1:8765" in api


def test_package_entry_points_on_non_windows():
    if sys.platform == "win32":
        pytest.skip("platform refusal is the non-Windows contract")
    import displayctl
    import displayctl.dxva2_win as dxva2_win
    from displayctl.cli import main
    from displayctl.errors import DisplayError

    with pytest.raises(DisplayError) as caught:
        displayctl.set_luminance_safe("none", 10, confirm=False)
    assert caught.value.kind == "confirm_required"
    with pytest.raises(DisplayError) as caught:
        displayctl.enumerate()
    assert caught.value.kind == "platform_unsupported"
    with pytest.raises(DisplayError) as caught:
        dxva2_win.probe_raw()
    assert caught.value.kind == "platform_unsupported"
    assert main(["list"]) == 1
    assert "SetVCPFeature" not in Path("brightness_vcp.py").read_text(encoding="utf-8")
