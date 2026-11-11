"""Capability-string cache. Pure: no DDC, no dxva2.

The capability string is large and slow to read, and it does not move when
luminance does, so a list probe should reuse it. Contrast may also come from
a GetVCP sample; the string still drives declaration and sparse detection.
The key is computed before the read.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from displayctl.identity import identify, parse_edid, slug
from displayctl.models import RawMonitor
from displayctl.policy import CAPS_CACHE_S


def caps_cache_key(
    *,
    edid: bytes | None,
    device: str,
    rect: tuple[int, int, int, int],
    primary: bool,
) -> str | None:
    """Key for a capabilities string this panel already proved it has.

    A stable EDID serial uses the same id as ``identify``, so a renamed
    ``\\\\.\\DISPLAYn`` still hits. EDID without a serial is only a model:
    the slot also binds the output and the geometry seen with that block, so
    two such panels do not share a string and a move pays for one new read.
    No parsed EDID means no cache. Device names are reused by Windows, and a
    wrong string would mis-state contrast.
    """
    if parse_edid(edid) is None:
        return None
    ident = identify(
        RawMonitor(
            device=device,
            description="",
            rect=rect,
            primary=primary,
            edid=edid,
            caps=None,
            vcp_ok=False,
            current=None,
            maximum=None,
            winerr=None,
        )
    )
    if ident.stable:
        return ident.id
    left, top, right, bottom = rect
    geo = f"{int(left)},{int(top)},{int(right)},{int(bottom)}"
    return f"{ident.id}:{slug(device)}:{1 if primary else 0}:{geo}"


def resolve_caps(
    *,
    vcp_ok: bool,
    cache_hit: bool,
    cached: str | None,
    read: Callable[[], str | None],
) -> tuple[str | None, bool]:
    """Return ``(caps, did_read)``.

    ``read`` is the DDC capabilities request. It runs only after GetVCP 0x10
    succeeded and this identity missed the cache. A failed get must not pay
    for it. When a previous read is still cached, that string is kept even if
    this get failed, so contrast stays declared without another round trip.
    """
    if not vcp_ok:
        return (cached if cache_hit else None), False
    if cache_hit:
        return cached, False
    return read(), True


class CapsCache:
    """Process-local TTL cache. Stores successful strings only."""

    def __init__(
        self,
        *,
        ttl_s: float = CAPS_CACHE_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_s = ttl_s
        self.clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, str]] = {}

    def get(self, key: str | None) -> tuple[bool, str | None]:
        """Return ``(hit, caps)``. A miss is ``(False, None)``."""
        if not key:
            return False, None
        now = self.clock()
        with self._lock:
            found = self._entries.get(key)
            if found is None:
                return False, None
            stamped, caps = found
            if now - stamped >= self.ttl_s:
                del self._entries[key]
                return False, None
            return True, caps

    def put(self, key: str | None, caps: str | None) -> None:
        """Remember a non-empty string. Failures stay misses so the next probe can retry."""
        if not key or not caps:
            return
        with self._lock:
            self._entries[key] = (self.clock(), caps)
