"""Backend selection. The default never opens a display on non-Windows hosts."""

from __future__ import annotations

import sys
from typing import Protocol

from displayctl.errors import DisplayError
from displayctl.models import RawMonitor
from displayctl.policy import LUMINANCE_VCP


class MonitorBackend(Protocol):
    name: str

    def probe(self) -> list[RawMonitor]:
        """Open handles, read, and close them before returning."""

    def set_vcp(self, target: RawMonitor, code: int, value: int) -> None:
        """Write one allowed VCP code once to the panel that matches ``target``."""

    def set_luminance(self, target: RawMonitor, value: int) -> None:
        """Write VCP 0x10 once. Convenience wrapper around ``set_vcp``."""


class UnavailableBackend:
    name = "unavailable"

    def probe(self) -> list[RawMonitor]:
        raise DisplayError("platform_unsupported")

    def set_vcp(self, target: RawMonitor, code: int, value: int) -> None:
        raise DisplayError("platform_unsupported")

    def set_luminance(self, target: RawMonitor, value: int) -> None:
        self.set_vcp(target, LUMINANCE_VCP, value)


class WindowsDxva2Backend:
    name = "dxva2"

    def probe(self) -> list[RawMonitor]:
        from displayctl.dxva2_win import probe_raw

        return probe_raw()

    def set_vcp(self, target: RawMonitor, code: int, value: int) -> None:
        from displayctl.dxva2_win import set_vcp_raw

        set_vcp_raw(target, code, value)

    def set_luminance(self, target: RawMonitor, value: int) -> None:
        self.set_vcp(target, LUMINANCE_VCP, value)


def default_backend() -> MonitorBackend:
    if sys.platform == "win32":
        return WindowsDxva2Backend()
    return UnavailableBackend()
