"""Hard limits for DisplayCtl writes.

Writable MCCS codes: luminance 0x10, contrast 0x12, volume 0x62.
The numbers here are the contract described in docs/SAFETY.md.
"""

from __future__ import annotations

LUMINANCE_VCP = 0x10

# The first CLI wrote this scale and rejected anything outside it.
LUMINANCE_MIN = 0
LUMINANCE_MAX = 100

# A readable 0x10 whose maximum is not 100 is an unknown scale.
# Refuse rather than guess a conversion.
REQUIRED_MAXIMUM = 100

# Exact readback. A mismatch triggers one rollback, not a retry of the new value.
VERIFY_TOLERANCE = 0
VERIFY_SETTLE_S = 0.20
VERIFY_READS = 2

# Writes only. Probes are coalesced by the service cache instead.
MIN_WRITE_INTERVAL_S = 0.80
MAX_WRITES_PER_MINUTE = 12
MAX_WRITES_GLOBAL_PER_MINUTE = 20

# List readings only (`_load(fresh=False)`). Writes, `probe()`, and
# `get_luminance` pass fresh=True and ignore this. The stamp is the time the
# probe returns, so a multi-second DDC pass is still reusable afterwards.
# 8s covers the console refresh (5s) without keeping a brightness reading
# that the write path could mistake for a fresh one — the write path does not
# read this cache.
PROBE_CACHE_S = 8.0

# Capability strings are a property of the panel, not of the current 0x10 value.
# Keyed by EDID identity inside the dxva2 probe. A cold list reads caps once
# per external panel; later lists reuse the string.
CAPS_CACHE_S = 300.0

# Known-safe reads may be GetVCP'd when caps declare them or when the vcp()
# list is sparse. Never written. Outcome cache TTL matches caps.
CONTRAST_VCP = 0x12
VOLUME_VCP = 0x62
INPUT_SOURCE_VCP = 0x60
POWER_MODE_VCP = 0xD6
RGB_GAIN_R_VCP = 0x16
RGB_GAIN_G_VCP = 0x18
RGB_GAIN_B_VCP = 0x1A
KNOWN_SAFE_READ_VCP = (
    CONTRAST_VCP,
    RGB_GAIN_R_VCP,
    RGB_GAIN_G_VCP,
    RGB_GAIN_B_VCP,
    INPUT_SOURCE_VCP,
    VOLUME_VCP,
    POWER_MODE_VCP,
)
SPARSE_CAPS_MAX_CODES = 3
PROBE_OUTCOME_CACHE_S = CAPS_CACHE_S

# Win32 codes treated as "try again later", never as a reason to write.
# 121 ERROR_SEM_TIMEOUT, 170 ERROR_BUSY, 258 WAIT_TIMEOUT, 1460 ERROR_TIMEOUT.
TRANSIENT_WINERRS = frozenset({121, 170, 258, 1460})

# ERROR_GEN_FAILURE. The existing CLI already documents this as a DDC-path failure.
WINERR_GEN_FAILURE = 31


# Codes that may receive SetVCPFeature. Everything else is policy_blocked.
WRITABLE_VCP = (LUMINANCE_VCP, CONTRAST_VCP, VOLUME_VCP)


def ensure_luminance_code(code: int) -> None:
    """Reject every VCP code except luminance. Kept for the legacy 0x10-only call sites."""
    if isinstance(code, bool) or not isinstance(code, int) or code != LUMINANCE_VCP:
        from displayctl.errors import DisplayError

        shown = f"0x{code:02X}" if isinstance(code, int) and not isinstance(code, bool) else "?"
        raise DisplayError("policy_blocked", code=shown)


def ensure_write_code(code: int) -> None:
    """Reject every VCP code outside the writable allow-list before SetVCPFeature."""
    if isinstance(code, bool) or not isinstance(code, int) or code not in WRITABLE_VCP:
        from displayctl.errors import DisplayError

        shown = f"0x{code:02X}" if isinstance(code, int) and not isinstance(code, bool) else "?"
        raise DisplayError("policy_blocked", code=shown)


def feature_for_code(code: int) -> str | None:
    if code == LUMINANCE_VCP:
        return "luminance"
    if code == CONTRAST_VCP:
        return "contrast"
    if code == VOLUME_VCP:
        return "volume"
    return None


def code_for_feature(feature: str) -> int:
    mapping = {
        "luminance": LUMINANCE_VCP,
        "contrast": CONTRAST_VCP,
        "volume": VOLUME_VCP,
    }
    if feature not in mapping:
        from displayctl.errors import DisplayError

        raise DisplayError("policy_blocked", feature=feature)
    return mapping[feature]
