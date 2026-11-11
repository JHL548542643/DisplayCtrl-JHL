"""Turn raw probe rows into views. Pure: no DDC, no clock."""

from __future__ import annotations

from collections import Counter

from displayctl.errors import message_for
from displayctl.identity import (
    caps_declares_code,
    caps_declares_contrast,
    caps_declares_input_source,
    caps_declares_luminance,
    caps_declares_power_mode,
    caps_declares_rgb_gains,
    caps_declares_volume,
    identify,
)
from displayctl.models import (
    ContrastCapability,
    InputSourceCapability,
    LuminanceCapability,
    MonitorCapabilities,
    MonitorRecord,
    MonitorView,
    PowerModeCapability,
    RawMonitor,
    RgbChannelCapability,
    RgbGainsCapability,
    VcpSample,
    VolumeCapability,
)
from displayctl.policy import (
    CONTRAST_VCP,
    INPUT_SOURCE_VCP,
    LUMINANCE_MAX,
    LUMINANCE_MIN,
    POWER_MODE_VCP,
    REQUIRED_MAXIMUM,
    RGB_GAIN_B_VCP,
    RGB_GAIN_G_VCP,
    RGB_GAIN_R_VCP,
    TRANSIENT_WINERRS,
    VOLUME_VCP,
    WINERR_GEN_FAILURE,
)


def classify(raw: RawMonitor) -> str | None:
    """Return a failure kind, or None when luminance is safe to change.

    ddc_off versus cable is a heuristic. Both kinds refuse the write.
    Primary is decided first so an internal panel that still has EDID is not
    described as an external DDC fault.
    """
    if raw.vcp_ok:
        if not _scale_ok(raw):
            return "unsupported_scale"
        return None
    if raw.primary:
        return "internal_panel"
    if raw.winerr in TRANSIENT_WINERRS:
        return "transient"
    declared = caps_declares_luminance(raw.caps)
    if raw.caps is not None and declared is False:
        return "unsupported"
    if raw.caps is not None and declared is True:
        return "transient"
    if raw.winerr not in {None, WINERR_GEN_FAILURE}:
        return "probe_failed"
    if raw.edid:
        return "ddc_off"
    return "cable"


def _scale_ok(raw: RawMonitor) -> bool:
    if raw.maximum != REQUIRED_MAXIMUM or raw.current is None:
        return False
    if isinstance(raw.current, bool) or not isinstance(raw.current, int):
        return False
    return LUMINANCE_MIN <= raw.current <= LUMINANCE_MAX


def build_records(raws: list[RawMonitor]) -> list[MonitorRecord]:
    """Preserve enumeration order. That order is the CLI session index only."""
    drafts = [(raw, identify(raw), classify(raw)) for raw in raws]
    counts = Counter(ident.id for _raw, ident, _failure in drafts)
    records: list[MonitorRecord] = []
    for index, (raw, ident, failure) in enumerate(drafts):
        quality = ident.quality
        stable = ident.stable
        public_id = ident.id
        if counts[ident.id] > 1:
            # Suffix is only a row key. The row stays unwritable.
            quality = "ambiguous"
            stable = False
            public_id = f"{ident.id}.dup{index}"
            if failure is None:
                failure = "identity_ambiguous"
        elif quality == "unstable" and failure is None:
            failure = "identity_unstable"
            stable = False
        message = message_for(failure, raw.winerr) if failure else None
        writable = failure is None
        view = MonitorView(
            id=public_id,
            stable=stable,
            identity_quality=quality,
            writable=writable,
            failure=failure,
            message=message,
            model=ident.model,
            manufacturer=ident.manufacturer,
            product_code=ident.product_code,
            serial=ident.serial,
            description=raw.description,
            device=raw.device,
            primary=raw.primary,
            session_index=index,
            rect=raw.rect,
            current=raw.current if raw.vcp_ok else None,
            maximum=raw.maximum if raw.vcp_ok else None,
            vcp_ok=raw.vcp_ok,
            winerr=raw.winerr,
            capabilities=_capabilities(raw, writable=writable),
        )
        records.append(MonitorRecord(view=view, raw=raw))
    return records


def _capabilities(raw: RawMonitor, *, writable: bool) -> MonitorCapabilities:
    """Luminance from 0x10. Contrast/volume may be writable; RGB/input/power stay read-only."""
    readable = (
        raw.vcp_ok
        and raw.current is not None
        and raw.maximum is not None
        and not isinstance(raw.current, bool)
        and isinstance(raw.current, int)
        and not isinstance(raw.maximum, bool)
        and isinstance(raw.maximum, int)
    )
    luminance = LuminanceCapability(
        readable=readable,
        writable=bool(writable and readable),
        current=raw.current if readable else None,
        maximum=raw.maximum if readable else None,
    )
    return MonitorCapabilities(
        luminance=luminance,
        contrast=_scalar_capability(
            raw,
            code=CONTRAST_VCP,
            declare=caps_declares_contrast,
            cls=ContrastCapability,
            monitor_writable=writable,
            allow_write=True,
        ),
        volume=_scalar_capability(
            raw,
            code=VOLUME_VCP,
            declare=caps_declares_volume,
            cls=VolumeCapability,
            monitor_writable=writable,
            allow_write=True,
        ),
        rgb_gains=_rgb_gains_capability(raw),
        input_source=_scalar_capability(
            raw, code=INPUT_SOURCE_VCP, declare=caps_declares_input_source, cls=InputSourceCapability
        ),
        power_mode=_scalar_capability(
            raw, code=POWER_MODE_VCP, declare=caps_declares_power_mode, cls=PowerModeCapability
        ),
    )


def _scalar_capability(
    raw: RawMonitor,
    *,
    code: int,
    declare,
    cls,
    monitor_writable: bool = False,
    allow_write: bool = False,
):
    declared = declare(raw.caps)
    sample = _sample_for(raw, code)
    if declared is None and sample is None:
        return None
    readable = sample is not None
    scale_ok = False
    if sample is not None:
        scale_ok = (
            sample.maximum == REQUIRED_MAXIMUM
            and not isinstance(sample.current, bool)
            and isinstance(sample.current, int)
            and LUMINANCE_MIN <= sample.current <= LUMINANCE_MAX
        )
    kwargs = dict(
        declared=bool(declared) if declared is not None else False,
        readable=readable,
        current=None if sample is None else sample.current,
        maximum=None if sample is None else sample.maximum,
    )
    # Contrast/Volume dataclass accept writable=; input/power do not.
    if allow_write:
        kwargs["writable"] = bool(monitor_writable and readable and scale_ok)
    return cls(**kwargs)


def _rgb_gains_capability(raw: RawMonitor) -> RgbGainsCapability | None:
    declared = caps_declares_rgb_gains(raw.caps)
    red = _rgb_channel(raw, RGB_GAIN_R_VCP, "0x16")
    green = _rgb_channel(raw, RGB_GAIN_G_VCP, "0x18")
    blue = _rgb_channel(raw, RGB_GAIN_B_VCP, "0x1A")
    any_readable = red.readable or green.readable or blue.readable
    if declared is None and not any_readable:
        return None
    return RgbGainsCapability(
        declared=bool(declared) if declared is not None else False,
        readable=any_readable,
        red=red,
        green=green,
        blue=blue,
    )


def _rgb_channel(raw: RawMonitor, code: int, vcp: str) -> RgbChannelCapability:
    declared = caps_declares_code(raw.caps, code)
    sample = _sample_for(raw, code)
    return RgbChannelCapability(
        vcp=vcp,
        declared=bool(declared) if declared is not None else False,
        readable=sample is not None,
        current=None if sample is None else sample.current,
        maximum=None if sample is None else sample.maximum,
    )


def _sample_for(raw: RawMonitor, code: int) -> VcpSample | None:
    for sample in raw.reads:
        if sample.code != code:
            continue
        if isinstance(sample.current, bool) or not isinstance(sample.current, int):
            continue
        if isinstance(sample.maximum, bool) or not isinstance(sample.maximum, int):
            continue
        if sample.maximum <= 0:
            continue
        return sample
    return None
