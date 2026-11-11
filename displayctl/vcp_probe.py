"""Known-safe GetVCP probes beyond luminance.

Capability strings are incomplete on some panels (a sparse ``vcp()`` list).
Those panels still answer GetVCP for ordinary codes such as contrast ``0x12``,
volume ``0x62``, RGB gains ``0x16`` / ``0x18`` / ``0x1A``,
input source ``0x60``, and power mode ``0xD6``.
This module decides which codes to try and caches whether each code worked,
keyed the same way as the capabilities-string cache. It never writes.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from displayctl.identity import declared_vcp_codes
from displayctl.policy import KNOWN_SAFE_READ_VCP, PROBE_OUTCOME_CACHE_S, SPARSE_CAPS_MAX_CODES


def caps_are_sparse(caps: str | None) -> bool:
    """True when a ``vcp()`` section exists but is too thin to trust alone."""
    codes = declared_vcp_codes(caps)
    if codes is None:
        return False
    return len(codes) <= SPARSE_CAPS_MAX_CODES


def codes_to_probe(
    caps: str | None,
    *,
    luminance_ok: bool,
    known_usable: frozenset[int] = frozenset(),
) -> tuple[int, ...]:
    """Return the known-safe codes this list probe should GetVCP.

    Declared known-safe codes are always included when present. Sparse caps
    also pull in the full known-safe set so sparse-caps fixtures that only declare
    ``02`` can still expose working contrast / volume / RGB / input / power. Codes
    previously proven usable stay on the list. Nothing outside
    ``KNOWN_SAFE_READ_VCP`` is ever returned. Failed luminance skips extras:
    the DDC path is already dead for this handle.
    """
    if not luminance_ok:
        return ()
    allowed = frozenset(KNOWN_SAFE_READ_VCP)
    wanted: set[int] = {code for code in known_usable if code in allowed}
    codes = declared_vcp_codes(caps)
    if codes is not None:
        wanted.update(code for code in codes if code in allowed)
    if caps_are_sparse(caps):
        wanted.update(allowed)
    return tuple(sorted(wanted))


class ProbeCache:
    """Process-local TTL cache of GetVCP outcomes per identity.

    Values are refreshed on every probe for codes still worth reading. The
    cache remembers which codes succeeded or failed so a sparse panel does not
    keep paying for dead codes, and a successful read stays on the probe list
    after the first discovery.
    """

    def __init__(
        self,
        *,
        ttl_s: float = PROBE_OUTCOME_CACHE_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_s = ttl_s
        self.clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, dict[int, bool]]] = {}

    def get(self, key: str | None) -> tuple[bool, dict[int, bool] | None]:
        """Return ``(hit, outcomes)``. A miss is ``(False, None)``."""
        if not key:
            return False, None
        now = self.clock()
        with self._lock:
            found = self._entries.get(key)
            if found is None:
                return False, None
            stamped, outcomes = found
            if now - stamped >= self.ttl_s:
                del self._entries[key]
                return False, None
            return True, dict(outcomes)

    def put(self, key: str | None, outcomes: dict[int, bool]) -> None:
        """Remember success/failure per code. Empty maps are ignored."""
        if not key or not outcomes:
            return
        with self._lock:
            self._entries[key] = (self.clock(), dict(outcomes))
