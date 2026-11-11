"""In-memory monitor backend for tests and ``--demo``.

It never opens dxva2. The service in front of it is the same one used on Windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from displayctl.errors import DisplayError
from displayctl.identity import same_raw
from displayctl.models import RawMonitor, VcpSample
from displayctl.policy import (
    CONTRAST_VCP,
    LUMINANCE_MAX,
    LUMINANCE_MIN,
    LUMINANCE_VCP,
    VOLUME_VCP,
    ensure_write_code,
)


@dataclass
class MemoryMonitor:
    device: str
    description: str
    rect: tuple[int, int, int, int]
    primary: bool
    edid: bytes | None
    caps: str | None
    vcp_ok: bool
    current: int | None
    maximum: int | None
    winerr: int | None
    script: list[int] = field(default_factory=list)
    consume_script: bool = False
    blind_after: bool = False
    reads: tuple[VcpSample, ...] = field(default_factory=tuple)

    def snapshot(self, current: int | None) -> RawMonitor:
        return RawMonitor(
            device=self.device,
            description=self.description,
            rect=self.rect,
            primary=self.primary,
            edid=self.edid if _edid_usable(self.edid) else None,
            caps=self.caps,
            vcp_ok=self.vcp_ok,
            current=current if self.vcp_ok else None,
            maximum=self.maximum if self.vcp_ok else None,
            winerr=self.winerr,
            reads=self.reads,
        )


def _edid_usable(edid: bytes | None) -> bool:
    from displayctl.identity import parse_edid

    return parse_edid(edid) is not None


class MemoryBackend:
    name = "memory"

    def __init__(self, monitors: list[MemoryMonitor]) -> None:
        self.monitors = monitors
        # (device, value) for luminance-era tests; also (device, code, value) in vcp_writes.
        self.set_calls: list[tuple[str, int]] = []
        self.vcp_writes: list[tuple[str, int, int]] = []
        self.fail_on: set[int] = set()
        self._attempts = 0

    def probe(self) -> list[RawMonitor]:
        rows: list[RawMonitor] = []
        for monitor in self.monitors:
            current = monitor.current
            if monitor.consume_script and monitor.script:
                current = monitor.script.pop(0)
            rows.append(monitor.snapshot(current))
        return rows

    def set_luminance(self, target: RawMonitor, value: int) -> None:
        self.set_vcp(target, LUMINANCE_VCP, value)

    def set_vcp(self, target: RawMonitor, code: int, value: int) -> None:
        ensure_write_code(code)
        if isinstance(value, bool) or not isinstance(value, int):
            raise DisplayError("value_out_of_range")
        if value < LUMINANCE_MIN or value > LUMINANCE_MAX:
            raise DisplayError("value_out_of_range")
        matches = [monitor for monitor in self.monitors if same_raw(monitor.snapshot(monitor.current), target)]
        if len(matches) != 1:
            kind = "identity_ambiguous" if len(matches) > 1 else "unknown_monitor"
            raise DisplayError(kind)
        self._attempts += 1
        device = matches[0].device
        self.set_calls.append((device, value))
        self.vcp_writes.append((device, code, value))
        if self._attempts in self.fail_on:
            raise DisplayError("write_failed")
        panel = matches[0]
        if code == LUMINANCE_VCP:
            panel.current = value
            panel.consume_script = True
            if panel.blind_after:
                panel.vcp_ok = False
            return
        if code not in {CONTRAST_VCP, VOLUME_VCP}:
            raise DisplayError("policy_blocked", code=f"0x{code:02X}")
        updated: list[VcpSample] = []
        found = False
        for sample in panel.reads:
            if sample.code == code:
                updated.append(VcpSample(code=code, current=value, maximum=sample.maximum))
                found = True
            else:
                updated.append(sample)
        if not found:
            updated.append(VcpSample(code=code, current=value, maximum=100))
        panel.reads = tuple(updated)
