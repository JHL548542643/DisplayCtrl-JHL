"""In-process write limiter. A refusal does not get its own retry loop."""

from __future__ import annotations

from collections.abc import Callable

from displayctl.errors import DisplayError
from displayctl.policy import (
    MAX_WRITES_GLOBAL_PER_MINUTE,
    MAX_WRITES_PER_MINUTE,
    MIN_WRITE_INTERVAL_S,
)


class RateLimiter:
    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._last: dict[str, float] = {}
        self._per_id: dict[str, list[float]] = {}
        self._global: list[float] = []

    def commit(self, monitor_id: str) -> None:
        """Record a write that is about to happen, or refuse."""
        now = self._clock()
        previous = self._last.get(monitor_id)
        if previous is not None and now - previous < MIN_WRITE_INTERVAL_S:
            raise DisplayError("rate_limited", monitor_id=monitor_id)
        recent = [stamp for stamp in self._per_id.get(monitor_id, []) if now - stamp < 60]
        if len(recent) >= MAX_WRITES_PER_MINUTE:
            raise DisplayError("rate_limited", monitor_id=monitor_id)
        global_recent = [stamp for stamp in self._global if now - stamp < 60]
        if len(global_recent) >= MAX_WRITES_GLOBAL_PER_MINUTE:
            raise DisplayError("rate_limited", monitor_id=monitor_id)
        recent.append(now)
        global_recent.append(now)
        self._per_id[monitor_id] = recent
        self._global = global_recent
        self._last[monitor_id] = now
