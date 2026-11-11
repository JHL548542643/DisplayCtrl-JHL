"""Sparse-caps routing and probe outcome cache. Pure: no DDC."""

from displayctl.policy import (
    CONTRAST_VCP,
    INPUT_SOURCE_VCP,
    POWER_MODE_VCP,
    RGB_GAIN_B_VCP,
    RGB_GAIN_G_VCP,
    RGB_GAIN_R_VCP,
    SPARSE_CAPS_MAX_CODES,
    VOLUME_VCP,
)
from displayctl.vcp_probe import ProbeCache, caps_are_sparse, codes_to_probe

KNOWN = (
    CONTRAST_VCP,
    RGB_GAIN_R_VCP,
    RGB_GAIN_G_VCP,
    RGB_GAIN_B_VCP,
    INPUT_SOURCE_VCP,
    VOLUME_VCP,
    POWER_MODE_VCP,
)


class Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_sparse_detects_thin_vcp_lists():
    assert caps_are_sparse("(vcp(02))") is True
    assert caps_are_sparse("(vcp(02 10))") is True
    assert SPARSE_CAPS_MAX_CODES >= 1
    rich = "(vcp(02 04 10 12 14 16 18 1A 60 62))"
    assert caps_are_sparse(rich) is False
    assert caps_are_sparse("(model(x))") is False
    assert caps_are_sparse(None) is False


def test_codes_to_probe_rich_declared_known_safe_only():
    caps = "(model(RICH)vcp(02 04 10 12 14 16 18 1A 60 62 AC AE))"
    # 0xD6 is known-safe but not declared on this rich list, so it stays out.
    expected = (
        CONTRAST_VCP,
        RGB_GAIN_R_VCP,
        RGB_GAIN_G_VCP,
        RGB_GAIN_B_VCP,
        INPUT_SOURCE_VCP,
        VOLUME_VCP,
    )
    assert codes_to_probe(caps, luminance_ok=True) == expected
    assert codes_to_probe(caps, luminance_ok=False) == ()


def test_codes_to_probe_rich_contrast_only_when_undeclared_extras():
    # More than SPARSE_CAPS_MAX_CODES so this stays "rich".
    caps = "(model(x)vcp(02 04 10 12 14 60))"
    assert codes_to_probe(caps, luminance_ok=True) == (CONTRAST_VCP, INPUT_SOURCE_VCP)


def test_codes_to_probe_sparse_includes_known_safe():
    assert codes_to_probe("(vcp(02))", luminance_ok=True) == KNOWN
    assert codes_to_probe("(vcp(10))", luminance_ok=True) == KNOWN


def test_codes_to_probe_keeps_known_usable():
    caps = "(vcp(02 04 10 14 AC AE))"  # rich, no known-safe declared
    assert codes_to_probe(caps, luminance_ok=True) == ()
    assert codes_to_probe(
        caps, luminance_ok=True, known_usable=frozenset({CONTRAST_VCP, VOLUME_VCP, 0x99})
    ) == (CONTRAST_VCP, VOLUME_VCP)


def test_probe_cache_ttl_and_outcomes():
    clock = Clock()
    cache = ProbeCache(ttl_s=10.0, clock=clock)
    assert cache.get("edid:x") == (False, None)
    cache.put("edid:x", {CONTRAST_VCP: True, VOLUME_VCP: False})
    hit, outcomes = cache.get("edid:x")
    assert hit is True
    assert outcomes == {CONTRAST_VCP: True, VOLUME_VCP: False}
    clock.now = 10.0
    assert cache.get("edid:x") == (False, None)
