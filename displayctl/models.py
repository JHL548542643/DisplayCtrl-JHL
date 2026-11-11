"""Structured monitor records. Handles never appear here."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class VcpSample:
    """One successful GetVCP reply that is not the luminance fields below."""

    code: int
    current: int
    maximum: int


@dataclass(frozen=True)
class RawMonitor:
    """One physical monitor as the backend just observed it.

    ``edid`` is included only when the base block parses. It is a match key,
    not something the API returns. ``reads`` holds extra GetVCP samples
    (contrast / volume / RGB gains / input source / power mode); luminance stays in ``current`` / ``maximum`` / ``vcp_ok``.
    """

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
    reads: tuple[VcpSample, ...] = ()


@dataclass(frozen=True)
class LuminanceCapability:
    """What the existing VCP 0x10 get, plus the write decision, actually support."""

    readable: bool
    writable: bool
    current: int | None
    maximum: int | None
    vcp: str = "0x10"

    def to_dict(self) -> dict[str, Any]:
        return {
            "vcp": self.vcp,
            "readable": self.readable,
            "writable": self.writable,
            "current": self.current,
            "maximum": self.maximum,
        }


@dataclass(frozen=True)
class ContrastCapability:
    """Contrast from caps declaration and/or a successful GetVCP of contrast.

    Writable follows the same gate as luminance: readable sample on a 0..100
    scale, stable identity, and an explicit confirm on the write path.
    """

    declared: bool
    readable: bool = False
    writable: bool = False
    current: int | None = None
    maximum: int | None = None
    vcp: str = "0x12"

    def to_dict(self) -> dict[str, Any]:
        return {
            "vcp": self.vcp,
            "declared": self.declared,
            "readable": self.readable,
            "writable": self.writable,
            "current": self.current if self.readable else None,
            "maximum": self.maximum if self.readable else None,
        }


@dataclass(frozen=True)
class VolumeCapability:
    """Speaker volume from caps declaration and/or a successful GetVCP of 0x62.

    Writable follows the same gate as luminance: readable sample on a 0..100
    scale, stable identity, and an explicit confirm on the write path.
    """

    declared: bool
    readable: bool = False
    writable: bool = False
    current: int | None = None
    maximum: int | None = None
    vcp: str = "0x62"

    def to_dict(self) -> dict[str, Any]:
        return {
            "vcp": self.vcp,
            "declared": self.declared,
            "readable": self.readable,
            "writable": self.writable,
            "current": self.current if self.readable else None,
            "maximum": self.maximum if self.readable else None,
        }


@dataclass(frozen=True)
class InputSourceCapability:
    """Input source select from caps declaration and/or a successful GetVCP of 0x60.

    Discrete MCCS value; exposed as current/maximum. Writable is always false.
    """

    declared: bool
    readable: bool = False
    current: int | None = None
    maximum: int | None = None
    vcp: str = "0x60"

    def to_dict(self) -> dict[str, Any]:
        return {
            "vcp": self.vcp,
            "declared": self.declared,
            "readable": self.readable,
            "writable": False,
            "current": self.current if self.readable else None,
            "maximum": self.maximum if self.readable else None,
        }


@dataclass(frozen=True)
class PowerModeCapability:
    """Power mode from caps declaration and/or a successful GetVCP of 0xD6.

    Discrete MCCS value; exposed as current/maximum. Writable is always false.
    """

    declared: bool
    readable: bool = False
    current: int | None = None
    maximum: int | None = None
    vcp: str = "0xD6"

    def to_dict(self) -> dict[str, Any]:
        return {
            "vcp": self.vcp,
            "declared": self.declared,
            "readable": self.readable,
            "writable": False,
            "current": self.current if self.readable else None,
            "maximum": self.maximum if self.readable else None,
        }


@dataclass(frozen=True)
class RgbChannelCapability:
    """One RGB gain channel. Writable is always false."""

    vcp: str
    declared: bool
    readable: bool = False
    current: int | None = None
    maximum: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "vcp": self.vcp,
            "declared": self.declared,
            "readable": self.readable,
            "writable": False,
            "current": self.current if self.readable else None,
            "maximum": self.maximum if self.readable else None,
        }


@dataclass(frozen=True)
class RgbGainsCapability:
    """RGB gains from caps declaration and/or successful GetVCP of 0x16/0x18/0x1A.

    Writable is always false: SetVCP stays luminance-only.
    """

    declared: bool
    readable: bool
    red: RgbChannelCapability
    green: RgbChannelCapability
    blue: RgbChannelCapability

    def to_dict(self) -> dict[str, Any]:
        return {
            "declared": self.declared,
            "readable": self.readable,
            "writable": False,
            "red": self.red.to_dict(),
            "green": self.green.to_dict(),
            "blue": self.blue.to_dict(),
        }


@dataclass(frozen=True)
class MonitorCapabilities:
    luminance: LuminanceCapability
    contrast: ContrastCapability | None
    volume: VolumeCapability | None = None
    rgb_gains: RgbGainsCapability | None = None
    input_source: InputSourceCapability | None = None
    power_mode: PowerModeCapability | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "luminance": self.luminance.to_dict(),
            "contrast": None if self.contrast is None else self.contrast.to_dict(),
            "volume": None if self.volume is None else self.volume.to_dict(),
            "rgb_gains": None if self.rgb_gains is None else self.rgb_gains.to_dict(),
            "input_source": None if self.input_source is None else self.input_source.to_dict(),
            "power_mode": None if self.power_mode is None else self.power_mode.to_dict(),
        }


@dataclass(frozen=True)
class MonitorView:
    id: str
    stable: bool
    identity_quality: str
    writable: bool
    failure: str | None
    message: str | None
    model: str | None
    manufacturer: str | None
    product_code: str | None
    serial: str | None
    description: str
    device: str
    primary: bool
    session_index: int
    rect: tuple[int, int, int, int]
    current: int | None
    maximum: int | None
    vcp_ok: bool
    winerr: int | None
    capabilities: MonitorCapabilities

    def to_dict(self) -> dict[str, Any]:
        luminance = None
        if self.vcp_ok and self.current is not None and self.maximum is not None:
            luminance = {
                "current": self.current,
                "maximum": self.maximum,
                "vcp": "0x10",
            }
        return {
            "id": self.id,
            "stable": self.stable,
            "identity_quality": self.identity_quality,
            "writable": self.writable,
            "failure": self.failure,
            "message": self.message,
            "model": self.model,
            "manufacturer": self.manufacturer,
            "product_code": self.product_code,
            "serial": self.serial,
            "description": self.description,
            "device": self.device,
            "primary": self.primary,
            "session_index": self.session_index,
            "rect": list(self.rect),
            "luminance": luminance,
            "capabilities": self.capabilities.to_dict(),
            "winerr": self.winerr,
        }


@dataclass(frozen=True)
class MonitorRecord:
    view: MonitorView
    raw: RawMonitor


@dataclass(frozen=True)
class LuminanceReading:
    monitor_id: str
    current: int
    maximum: int
    vcp: str = "0x10"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SetResult:
    monitor_id: str
    requested: int
    previous: int
    verified: int
    noop: bool
    rolled_back: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
