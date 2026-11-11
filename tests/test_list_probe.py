"""List-probe speedups that do not require a real monitor.

Caps identity, skip-on-failed-VCP, and list singleflight. Physical-monitor DDC
stays serial: a fresh probe waits for an in-flight list probe instead of
overlapping it.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from displayctl.assemble import build_records
from displayctl.caps_cache import CapsCache, caps_cache_key, resolve_caps
from displayctl.errors import DisplayError
from displayctl.identity import caps_declares_contrast, encode_edid, identify
from displayctl.memory import MemoryBackend, MemoryMonitor
from displayctl.models import RawMonitor
from displayctl.policy import CAPS_CACHE_S, PROBE_CACHE_S
from displayctl.service import DisplayService


class Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _panel(**overrides) -> MemoryMonitor:
    edid = overrides.pop("edid", encode_edid("AOC", 0x1234, serial_text="Q27"))
    base = dict(
        device=r"\\.\DISPLAY2",
        description="AOC",
        rect=(0, 0, 2560, 1440),
        primary=False,
        edid=edid,
        caps="(model(Q27)vcp(10 12))",
        vcp_ok=True,
        current=40,
        maximum=100,
        winerr=None,
    )
    base.update(overrides)
    return MemoryMonitor(**base)


def _wait_until(predicate, *, what) -> None:
    for _ in range(400):
        if predicate():
            return
        threading.Event().wait(0.005)
    raise AssertionError(what() if callable(what) else what)


def _service(backend: MemoryBackend, clock: Clock | None = None) -> DisplayService:
    return DisplayService(backend, sleep=lambda _seconds: None, clock=clock or Clock())


def test_caps_key_matches_stable_edid_identity_and_ignores_the_output_name():
    edid = encode_edid("AOC", 0x1234, serial_text="Q27")
    rect = (0, 0, 2560, 1440)
    key = caps_cache_key(edid=edid, device=r"\\.\DISPLAY2", rect=rect, primary=False)
    moved = caps_cache_key(
        edid=edid,
        device=r"\\.\DISPLAY9",
        rect=(1920, 0, 4480, 1440),
        primary=True,
    )
    ident = identify(
        RawMonitor(
            device=r"\\.\DISPLAY9",
            description="other",
            rect=(1920, 0, 4480, 1440),
            primary=True,
            edid=edid,
            caps=None,
            vcp_ok=False,
            current=None,
            maximum=None,
            winerr=None,
        )
    )
    assert key == moved == ident.id
    assert ident.stable is True


def test_caps_key_without_serial_keeps_panels_apart_and_without_edid_is_uncached():
    edid = encode_edid("AOC", 0x1234, serial=0)
    left = caps_cache_key(
        edid=edid,
        device=r"\\.\DISPLAY2",
        rect=(0, 0, 2560, 1440),
        primary=False,
    )
    right = caps_cache_key(
        edid=edid,
        device=r"\\.\DISPLAY3",
        rect=(2560, 0, 4480, 1440),
        primary=False,
    )
    assert left is not None and right is not None
    assert left != right
    assert left.startswith("edid:AOC:1234:noserial:")
    assert caps_cache_key(
        edid=None,
        device=r"\\.\DISPLAY1",
        rect=(0, 0, 1920, 1080),
        primary=True,
    ) is None
    bad = bytearray(encode_edid("AOC", 0x1234, serial_text="Q27"))
    bad[20] ^= 0xFF
    assert caps_cache_key(edid=bytes(bad), device=r"\\.\DISPLAY2", rect=(0, 0, 1, 1), primary=False) is None


def test_resolve_skips_caps_when_vcp_failed_and_reuses_a_hit():
    calls: list[str] = []

    def read() -> str:
        calls.append("read")
        return "(vcp(10 12))"

    missed, did_read = resolve_caps(vcp_ok=False, cache_hit=False, cached=None, read=read)
    assert missed is None and did_read is False
    warm, did_read = resolve_caps(
        vcp_ok=False,
        cache_hit=True,
        cached="(model(Q27)vcp(10 12))",
        read=read,
    )
    assert warm == "(model(Q27)vcp(10 12))" and did_read is False
    assert calls == []
    assert caps_declares_contrast(warm) is True


def test_resolve_reads_once_on_a_miss_and_not_again_on_a_hit():
    calls: list[str] = []

    def read() -> str:
        calls.append("read")
        return "(model(Q27)vcp(10 12))"

    first, did_read = resolve_caps(vcp_ok=True, cache_hit=False, cached=None, read=read)
    assert did_read is True
    second, did_read = resolve_caps(vcp_ok=True, cache_hit=True, cached=first, read=read)
    assert second == first and did_read is False
    assert calls == ["read"]
    view = build_records(
        [
            RawMonitor(
                device=r"\\.\DISPLAY2",
                description="AOC",
                rect=(0, 0, 2560, 1440),
                primary=False,
                edid=encode_edid("AOC", 0x1234, serial_text="Q27"),
                caps=second,
                vcp_ok=True,
                current=40,
                maximum=100,
                winerr=None,
            )
        ]
    )[0].view
    assert view.capabilities.contrast is not None
    assert view.capabilities.contrast.declared is True
    assert view.capabilities.luminance.current == 40
    assert view.writable is True


def test_caps_cache_ttl_and_empty_values():
    clock = Clock()
    cache = CapsCache(ttl_s=CAPS_CACHE_S, clock=clock)
    key = "edid:AOC:1234:Q27"
    assert cache.get(key) == (False, None)
    cache.put(None, "(vcp(10))")
    cache.put(key, None)
    cache.put(key, "")
    assert cache.get(key) == (False, None)
    cache.put(key, "(vcp(10 12))")
    assert cache.get(key) == (True, "(vcp(10 12))")
    clock.now += CAPS_CACHE_S - 0.1
    assert cache.get(key) == (True, "(vcp(10 12))")
    clock.now += 0.1
    assert cache.get(key) == (False, None)


def test_dxva2_helper_skips_failed_vcp_and_caches_by_edid(monkeypatch):
    import displayctl.dxva2_win as dx

    clock = Clock()
    monkeypatch.setattr(dx, "_CAPS_CACHE", CapsCache(ttl_s=CAPS_CACHE_S, clock=clock))
    calls: list[object] = []

    def fake_read(_dxva2, _dword, handle):
        calls.append(handle)
        return "(model(Q27)vcp(10 12))" if handle == "q27" else "(model(Q24)vcp(10))"

    monkeypatch.setattr(dx, "_read_caps", fake_read)
    q27 = encode_edid("AOC", 0x1234, serial_text="Q27")
    q24 = encode_edid("AOC", 0x5678, serial_text="Q24")
    common = dict(dxva2=object(), dword=object(), device=r"\\.\DISPLAY3", rect=(0, 0, 2560, 1440), primary=False)

    assert dx._resolve_handle_caps(handle="oled", vcp_ok=False, edid=encode_edid("APP", 1, serial_text="LCD"), **common) is None
    assert calls == []

    first = dx._resolve_handle_caps(handle="q27", vcp_ok=True, edid=q27, **common)
    again = dx._resolve_handle_caps(handle="q27", vcp_ok=True, edid=q27, **common)
    assert first == again == "(model(Q27)vcp(10 12))"
    assert calls == ["q27"]
    # A later failed get still does not touch DDC, and contrast stays known.
    assert dx._resolve_handle_caps(handle="q27", vcp_ok=False, edid=q27, **common) == first
    assert calls == ["q27"]
    assert caps_declares_contrast(first) is True

    other = dx._resolve_handle_caps(
        handle="q24",
        vcp_ok=True,
        edid=q24,
        dxva2=object(),
        dword=object(),
        device=r"\\.\DISPLAY4",
        rect=(2560, 0, 4480, 1440),
        primary=False,
    )
    assert other == "(model(Q24)vcp(10))"
    assert caps_declares_contrast(other) is False
    assert calls == ["q27", "q24"]

    clock.now += CAPS_CACHE_S
    assert dx._resolve_handle_caps(handle="q27", vcp_ok=True, edid=q27, **common) == first
    assert calls == ["q27", "q24", "q27"]

    # No EDID: do not remember the string, even after a successful read.
    monkeypatch.setattr(dx, "_read_caps", lambda *_args: calls.append("bare") or "(vcp(10 12))")
    bare = dict(dxva2=object(), dword=object(), device=r"\\.\DISPLAY1", rect=(0, 0, 100, 100), primary=True, edid=None)
    assert dx._resolve_handle_caps(handle="x", vcp_ok=True, **bare) == "(vcp(10 12))"
    assert dx._resolve_handle_caps(handle="x", vcp_ok=True, **bare) == "(vcp(10 12))"
    assert calls.count("bare") == 2


def test_dxva2_probe_does_not_fan_out_across_monitors():
    source = Path("displayctl/dxva2_win.py").read_text(encoding="utf-8")
    assert "resolve_caps" in source
    assert "Thread(" not in source
    assert "concurrent.futures" not in source


class _SlowBackend(MemoryBackend):
    def __init__(self, monitors: list[MemoryMonitor]) -> None:
        super().__init__(monitors)
        self.probes = 0
        self.current = 0
        self.peak = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self._gate = threading.Lock()

    def probe(self):
        with self._gate:
            self.probes += 1
            self.current += 1
            self.peak = max(self.peak, self.current)
            first = self.probes == 1
        if first:
            self.entered.set()
            assert self.release.wait(timeout=5)
        with self._gate:
            self.current -= 1
        return super().probe()


def test_concurrent_list_callers_share_one_probe():
    backend = _SlowBackend([_panel()])
    service = _service(backend)
    errors: list[BaseException] = []
    found: list[str] = []

    def run() -> None:
        try:
            found.append(service.enumerate_monitors()[0].id)
        except BaseException as exc:  # pragma: no cover - failure path asserts below
            errors.append(exc)

    threads = [threading.Thread(target=run, daemon=True) for _ in range(3)]
    try:
        threads[0].start()
        assert backend.entered.wait(2)
        threads[1].start()
        threads[2].start()
        _wait_until(
            lambda: service._list_waiters >= 2 and backend.probes == 1 and backend.peak == 1,
            what=lambda: f"followers did not join: probes={backend.probes} waiters={service._list_waiters}",
        )
        assert backend.peak == 1
    finally:
        backend.release.set()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    assert errors == []
    assert backend.probes == 1
    assert found == [found[0], found[0], found[0]]
    service.enumerate_monitors()
    assert backend.probes == 1


def test_fresh_probe_does_not_overlap_list_ddc():
    backend = _SlowBackend([_panel()])
    service = _service(backend)
    fresh_probes: list[int] = []
    errors: list[BaseException] = []

    def refresh() -> None:
        try:
            fresh_probes.append(len(service.probe()))
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    leader = threading.Thread(target=service.enumerate_monitors, daemon=True)
    follower = threading.Thread(target=refresh, daemon=True)
    try:
        leader.start()
        assert backend.entered.wait(2)
        follower.start()
        # Leader still holds the hardware lock inside probe. Release only after
        # the fresh caller has been started, so it has to wait its turn.
        assert backend.probes == 1
    finally:
        backend.release.set()
    leader.join(2)
    follower.join(2)
    assert not leader.is_alive()
    assert not follower.is_alive()
    assert errors == []
    assert fresh_probes == [1]
    assert backend.probes == 2
    assert backend.peak == 1


def test_failed_list_probe_is_shared_then_retried():
    entered = threading.Event()
    release = threading.Event()
    probes = {"n": 0}

    class Boom(MemoryBackend):
        def probe(self):
            probes["n"] += 1
            entered.set()
            assert release.wait(timeout=5)
            raise DisplayError("probe_failed")

    service = _service(Boom([]))
    kinds: list[str] = []

    def run() -> None:
        try:
            service.enumerate_monitors()
        except DisplayError as exc:
            kinds.append(exc.kind)
        except BaseException as exc:  # pragma: no cover
            kinds.append(type(exc).__name__)

    threads = [threading.Thread(target=run, daemon=True) for _ in range(2)]
    try:
        threads[0].start()
        assert entered.wait(2)
        threads[1].start()
        _wait_until(
            lambda: service._list_waiters >= 1 and probes["n"] == 1,
            what=lambda: f"follower missed the failure flight: {probes}",
        )
    finally:
        release.set()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    assert kinds == ["probe_failed", "probe_failed"]
    assert probes["n"] == 1
    with pytest.raises(DisplayError) as caught:
        service.enumerate_monitors()
    assert caught.value.kind == "probe_failed"
    assert probes["n"] == 2


def test_list_cache_starts_when_the_probe_returns():
    clock = Clock()

    class SlowClock(MemoryBackend):
        def __init__(self, monitors: list[MemoryMonitor]) -> None:
            super().__init__(monitors)
            self.probes = 0

        def probe(self):
            self.probes += 1
            clock.now += 30
            return super().probe()

    backend = SlowClock([_panel()])
    service = _service(backend, clock)
    service.enumerate_monitors()
    service.enumerate_monitors()
    assert backend.probes == 1
    clock.now += PROBE_CACHE_S
    service.enumerate_monitors()
    assert backend.probes == 2


def test_write_still_probes_fresh_and_verifies():
    class Counting(MemoryBackend):
        def __init__(self, monitors: list[MemoryMonitor]) -> None:
            super().__init__(monitors)
            self.probes = 0

        def probe(self):
            self.probes += 1
            return super().probe()

    panel = _panel(current=40)
    backend = Counting([panel])
    service = _service(backend)
    views = service.enumerate_monitors()
    assert backend.probes == 1
    result = service.set_luminance_safe(views[0].id, 50, confirm=True)
    assert result.previous == 40
    assert result.verified == 50
    assert result.noop is False
    assert backend.set_calls == [(panel.device, 50)]
    # List snapshot, the write's own fresh probe, and one confirming readback.
    assert backend.probes == 3
