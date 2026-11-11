import argparse
from pathlib import Path

import pytest

from displayctl.assemble import build_records, classify
from displayctl.cli import _cmd_list, _cmd_set
from displayctl.errors import DisplayError
from displayctl.identity import encode_edid
from displayctl.memory import MemoryBackend, MemoryMonitor
from displayctl.models import RawMonitor
from displayctl.policy import PROBE_CACHE_S, ensure_luminance_code, ensure_write_code
from displayctl.rate_limit import RateLimiter
from displayctl.service import DisplayService


class Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def monitor(**overrides) -> MemoryMonitor:
    edid = overrides.pop("edid", encode_edid("GSM", 0x5B05, serial_text="K1"))
    base = dict(
        device=r"\\.\DISPLAY2",
        description="LG",
        rect=(0, 0, 2560, 1440),
        primary=False,
        edid=edid,
        caps="(model(27G2)vcp(10))",
        vcp_ok=True,
        current=40,
        maximum=100,
        winerr=None,
    )
    base.update(overrides)
    return MemoryMonitor(**base)


def service_for(*monitors: MemoryMonitor, clock: Clock | None = None) -> tuple[MemoryBackend, DisplayService]:
    backend = MemoryBackend(list(monitors))
    clock = clock or Clock(1000.0)
    service = DisplayService(backend, sleep=lambda _s: None, clock=clock)
    return backend, service


def _id(service: DisplayService, index: int = 0) -> str:
    return service.probe()[index].id


def test_policy_blocks_unknown_vcp_code():
    with pytest.raises(DisplayError) as caught:
        ensure_luminance_code(0x12)
    assert caught.value.kind == "policy_blocked"
    ensure_luminance_code(0x10)
    ensure_write_code(0x10)
    ensure_write_code(0x12)
    ensure_write_code(0x62)
    with pytest.raises(DisplayError) as caught:
        ensure_write_code(0x16)
    assert caught.value.kind == "policy_blocked"


def test_windows_writer_has_one_vcp_call_site():
    source = Path("displayctl/dxva2_win.py").read_text(encoding="utf-8")
    assert source.count("SetVCPFeature(") == 1
    assert "ensure_write_code" in source
    assert "DestroyPhysicalMonitors" in source
    assert "0x12" not in source


def test_confirm_false_does_not_probe():
    backend, service = service_for(monitor())
    with pytest.raises(DisplayError) as caught:
        service.set_luminance_safe(_id(service), 50, confirm=False)
    assert caught.value.kind == "confirm_required"
    assert backend.set_calls == []


def test_failed_probe_never_writes():
    backend, service = service_for(
        monitor(vcp_ok=False, current=None, maximum=None, winerr=31, caps=None)
    )
    view = service.probe()[0]
    assert view.failure == "ddc_off"
    assert view.writable is False
    with pytest.raises(DisplayError) as caught:
        service.set_luminance_safe(view.id, 30, confirm=True)
    assert caught.value.kind == "ddc_off"
    assert backend.set_calls == []


def test_success_reads_back_the_target_monitor_only():
    backend, service = service_for(
        monitor(device=r"\\.\DISPLAY2", current=10, edid=encode_edid("GSM", 0x0001, serial_text="A")),
        monitor(
            device=r"\\.\DISPLAY3",
            current=20,
            rect=(2560, 0, 4000, 1440),
            edid=encode_edid("DEL", 0x0002, serial_text="B"),
            caps="(model(U2720Q)vcp(10))",
        ),
    )
    views = service.probe()
    result = service.set_luminance_safe(views[1].id, 30, confirm=True)
    assert result.verified == 30
    assert result.previous == 20
    assert backend.set_calls == [(r"\\.\DISPLAY3", 30)]
    assert backend.monitors[0].current == 10


def test_set_follows_edid_when_display_name_changes():
    backend, service = service_for(monitor())
    view = service.probe()[0]
    backend.monitors[0].device = r"\\.\DISPLAY9"
    result = service.set_luminance_safe(view.id, 70, confirm=True)
    assert result.verified == 70
    assert backend.set_calls == [(r"\\.\DISPLAY9", 70)]


def test_lost_identity_does_not_write():
    backend, service = service_for(monitor())
    view = service.probe()[0]
    backend.monitors[0].edid = encode_edid("DEL", 0x9999, serial_text="OTHER")
    with pytest.raises(DisplayError) as caught:
        service.set_luminance_safe(view.id, 70, confirm=True)
    assert caught.value.kind == "unknown_monitor"
    assert backend.set_calls == []


def test_mismatch_rolls_back_once():
    panel = monitor(current=40)
    panel.script = [40, 40]
    backend, service = service_for(panel)
    view = service.probe()[0]
    with pytest.raises(DisplayError) as caught:
        service.set_luminance_safe(view.id, 80, confirm=True)
    assert caught.value.kind == "verify_mismatch"
    assert caught.value.details["rolled_back"] is True
    assert caught.value.details["restored"] == 40
    assert backend.set_calls == [(panel.device, 80), (panel.device, 40)]


def test_second_read_can_confirm_without_rollback():
    panel = monitor(current=40)
    panel.script = [40, 80]
    backend, service = service_for(panel)
    result = service.set_luminance_safe(service.probe()[0].id, 80, confirm=True)
    assert result.verified == 80
    assert backend.set_calls == [(panel.device, 80)]


def test_write_failure_with_unchanged_readback_does_not_rollback():
    panel = monitor(current=40)
    backend, service = service_for(panel)
    backend.fail_on.add(1)
    with pytest.raises(DisplayError) as caught:
        service.set_luminance_safe(service.probe()[0].id, 80, confirm=True)
    assert caught.value.kind == "write_failed"
    assert backend.set_calls == [(panel.device, 80)]
    assert panel.current == 40


def test_rollback_failure_stops():
    panel = monitor(current=40)
    panel.script = [40, 40]
    backend, service = service_for(panel)
    backend.fail_on.add(2)
    with pytest.raises(DisplayError) as caught:
        service.set_luminance_safe(service.probe()[0].id, 80, confirm=True)
    assert caught.value.kind == "rollback_failed"
    assert backend.set_calls == [(panel.device, 80), (panel.device, 40)]


def test_unconfirmed_read_does_not_write_again():
    panel = monitor(current=40, blind_after=True)
    backend, service = service_for(panel)
    with pytest.raises(DisplayError) as caught:
        service.set_luminance_safe(service.probe()[0].id, 80, confirm=True)
    assert caught.value.kind == "verify_unconfirmed"
    assert len(backend.set_calls) == 1


def test_noop_does_not_write_or_rate_limit():
    backend, service = service_for(monitor(current=40))
    result = service.set_luminance_safe(service.probe()[0].id, 40, confirm=True)
    assert result.noop is True
    assert backend.set_calls == []
    again = service.set_luminance_safe(service.probe()[0].id, 40, confirm=True)
    assert again.noop is True


def test_rate_limit_blocks_the_second_write():
    clock = Clock(50.0)
    backend, service = service_for(monitor(current=40), clock=clock)
    service.set_luminance_safe(service.probe()[0].id, 41, confirm=True)
    with pytest.raises(DisplayError) as caught:
        service.set_luminance_safe(service.probe()[0].id, 42, confirm=True)
    assert caught.value.kind == "rate_limited"
    assert len(backend.set_calls) == 1
    clock.now += 1
    service.set_luminance_safe(service.probe()[0].id, 43, confirm=True)
    assert [call[1] for call in backend.set_calls] == [41, 43]


def test_rate_limiter_window():
    clock = Clock()
    limiter = RateLimiter(clock)
    for _ in range(12):
        limiter.commit("panel")
        clock.now += 1
    with pytest.raises(DisplayError) as caught:
        limiter.commit("panel")
    assert caught.value.kind == "rate_limited"


def test_rejects_bool_and_out_of_range():
    _backend, service = service_for(monitor())
    monitor_id = service.probe()[0].id
    with pytest.raises(DisplayError) as caught:
        service.set_luminance_safe(monitor_id, True, confirm=True)  # type: ignore[arg-type]
    assert caught.value.kind == "value_out_of_range"
    with pytest.raises(DisplayError) as caught:
        service.set_luminance_safe(monitor_id, 101, confirm=True)
    assert caught.value.kind == "value_out_of_range"


def test_unknown_scale_is_not_writable():
    backend, service = service_for(monitor(maximum=255, current=80))
    view = service.probe()[0]
    assert view.failure == "unsupported_scale"
    with pytest.raises(DisplayError):
        service.set_luminance_safe(view.id, 40, confirm=True)
    assert backend.set_calls == []


def test_duplicate_serial_is_not_writable():
    edid = encode_edid("GSM", 0x5B05, serial_text="SAME")
    backend, service = service_for(
        monitor(edid=edid, device=r"\\.\DISPLAY2"),
        monitor(edid=edid, device=r"\\.\DISPLAY3", rect=(10, 0, 20, 10)),
    )
    views = service.probe()
    assert len(views) == 2
    assert {view.identity_quality for view in views} == {"ambiguous"}
    assert all(not view.writable for view in views)
    for view in views:
        with pytest.raises(DisplayError) as caught:
            service.set_luminance_safe(view.id, 20, confirm=True)
        assert caught.value.kind == "identity_ambiguous"
    assert backend.set_calls == []


def test_unique_model_without_serial_can_be_written():
    backend, service = service_for(monitor(edid=None, caps="(model(27G2)vcp(10))"))
    view = service.probe()[0]
    assert view.identity_quality == "model"
    assert view.stable is False
    assert view.writable is True
    service.set_luminance_safe(view.id, 15, confirm=True)
    assert backend.set_calls == [(view.device, 15)]


def test_no_identity_refuses_even_if_vcp_reads():
    backend, service = service_for(
        monitor(edid=None, caps=None, description="Mystery", vcp_ok=True, current=20, maximum=100)
    )
    view = service.probe()[0]
    assert view.failure == "identity_unstable"
    with pytest.raises(DisplayError):
        service.set_luminance_safe(view.id, 21, confirm=True)
    assert backend.set_calls == []


def test_primary_external_with_vcp_is_writable_internal_without_vcp_is_not():
    _backend, service = service_for(
        monitor(primary=True, device=r"\\.\DISPLAY1", rect=(0, 0, 100, 100)),
        monitor(
            primary=True,
            device=r"\\.\DISPLAY1",
            edid=encode_edid("APP", 0x0001, serial_text="LCD"),
            vcp_ok=False,
            current=None,
            maximum=None,
            winerr=31,
            caps=None,
            description="Integrated",
            rect=(0, 0, 100, 100),
        ),
    )
    views = service.probe()
    assert views[0].writable is True
    assert views[1].failure == "internal_panel"


def test_failure_taxonomy_heuristics():
    def kind(**overrides) -> str | None:
        base = dict(
            device=r"\\.\DISPLAY3",
            description="x",
            rect=(0, 0, 1, 1),
            primary=False,
            edid=None,
            caps=None,
            vcp_ok=False,
            current=None,
            maximum=None,
            winerr=31,
        )
        base.update(overrides)
        return classify(RawMonitor(**base))

    assert kind(primary=True, edid=encode_edid("APP", 1, serial_text="IN")) == "internal_panel"
    assert kind(winerr=258) == "transient"
    assert kind(edid=encode_edid("DEL", 2, serial_text="Z")) == "ddc_off"
    assert kind() == "cable"
    assert kind(winerr=5) == "probe_failed"
    assert kind(caps="(vcp(12))", winerr=31) == "unsupported"
    assert kind(caps="(vcp(10))", winerr=31) == "transient"


def test_enumerate_cache_collapses_probes():
    class Counting(MemoryBackend):
        def __init__(self, monitors):
            super().__init__(monitors)
            self.probes = 0

        def probe(self):
            self.probes += 1
            return super().probe()

    clock = Clock()
    backend = Counting([monitor()])
    service = DisplayService(backend, sleep=lambda _s: None, clock=clock)
    service.enumerate_monitors()
    service.enumerate_monitors()
    assert backend.probes == 1
    service.probe()
    assert backend.probes == 2
    clock.now += PROBE_CACHE_S
    service.enumerate_monitors()
    assert backend.probes == 3


def test_cli_refuses_without_yes_and_writes_with_yes(capsys):
    backend, service = service_for(monitor(current=40))
    refused = _cmd_set(argparse.Namespace(index=0, value=55, yes=False), service)
    assert refused == 3
    assert capsys.readouterr().out.strip() == "refusing to change brightness without --yes"
    assert backend.set_calls == []
    assert _cmd_set(argparse.Namespace(index=0, value=55, yes=True), service) == 0
    output = capsys.readouterr().out
    assert "40 -> set 55 -> read 55/100" in output
    assert "id=edid:GSM:5B05:K1" in output


def test_cli_list_keeps_index_and_adds_id(capsys):
    _backend, service = service_for(monitor())
    assert _cmd_list(argparse.Namespace(), service) == 0
    line = capsys.readouterr().out
    assert line.startswith("[0] 27G2 |")
    assert "luminance=40/100" in line
    assert "id=edid:GSM:5B05:K1" in line


def test_cli_range_message(capsys):
    _backend, service = service_for(monitor())
    code = _cmd_set(argparse.Namespace(index=0, value=150, yes=True), service)
    assert code == 1
    assert "value must be 0..100" in capsys.readouterr().err


def test_records_keep_enumeration_order():
    records = build_records(
        [
            MemoryMonitor(
                device=r"\\.\DISPLAY1",
                description="A",
                rect=(0, 0, 1, 1),
                primary=True,
                edid=None,
                caps=None,
                vcp_ok=False,
                current=None,
                maximum=None,
                winerr=31,
            ).snapshot(None),
            monitor(device=r"\\.\DISPLAY2").snapshot(40),
        ]
    )
    assert [record.view.session_index for record in records] == [0, 1]
    assert records[0].view.failure == "internal_panel"
    assert records[1].view.writable is True


def test_contrast_and_volume_write_confirm_and_verify():
    from displayctl.models import VcpSample
    from displayctl.policy import CONTRAST_VCP, VOLUME_VCP

    panel = monitor(
        caps="(model(27G2)vcp(10 12 62))",
        reads=(
            VcpSample(code=CONTRAST_VCP, current=55, maximum=100),
            VcpSample(code=VOLUME_VCP, current=30, maximum=100),
        ),
    )
    backend, service = service_for(panel)
    view = service.probe()[0]
    assert view.capabilities.contrast.writable is True
    assert view.capabilities.volume.writable is True
    with pytest.raises(DisplayError) as caught:
        service.set_contrast_safe(view.id, 60, confirm=False)
    assert caught.value.kind == "confirm_required"
    assert backend.vcp_writes == []
    result = service.set_contrast_safe(view.id, 60, confirm=True)
    assert result.previous == 55
    assert result.verified == 60
    assert backend.vcp_writes == [(panel.device, CONTRAST_VCP, 60)]
    clock = Clock(1000.0)
    backend2, service2 = service_for(
        monitor(
            caps="(model(27G2)vcp(10 12 62))",
            reads=(
                VcpSample(code=CONTRAST_VCP, current=55, maximum=100),
                VcpSample(code=VOLUME_VCP, current=30, maximum=100),
            ),
        ),
        clock=clock,
    )
    view2 = service2.probe()[0]
    clock.now += 2.0
    vol = service2.set_volume_safe(view2.id, 44, confirm=True)
    assert vol.verified == 44
    assert backend2.vcp_writes[-1] == (view2.device, VOLUME_VCP, 44)


def test_rgb_still_has_no_write_path():
    source = Path("displayctl/api.py").read_text(encoding="utf-8")
    assert "/rgb" not in source
    assert "set_rgb" not in source
