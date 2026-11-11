"""Probe, then maybe write once, then read back.

This is the only write pipeline the CLI and the local API use.
List probes share one in-flight read. Writes always probe again, and every
physical-monitor DDC call stays on one hardware lock.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future

from displayctl.assemble import build_records
from displayctl.backend import MonitorBackend, default_backend
from displayctl.errors import DisplayError
from displayctl.models import LuminanceReading, MonitorRecord, MonitorView, SetResult
from displayctl.policy import (
    CONTRAST_VCP,
    LUMINANCE_MAX,
    LUMINANCE_MIN,
    LUMINANCE_VCP,
    PROBE_CACHE_S,
    VERIFY_READS,
    VERIFY_SETTLE_S,
    VERIFY_TOLERANCE,
    VOLUME_VCP,
    code_for_feature,
    ensure_write_code,
)
from displayctl.rate_limit import RateLimiter

log = logging.getLogger("displayctl")

_default: DisplayService | None = None
_default_guard = threading.Lock()


class DisplayService:
    def __init__(
        self,
        backend: MonitorBackend,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        demo: bool = False,
    ) -> None:
        self.backend = backend
        self.sleep = sleep
        self.clock = clock
        self.demo = demo
        self.limiter = RateLimiter(clock)
        # State (cache, write critical section). Never acquired while waiting
        # on `_hw_lock` by a thread that does not already hold `_hw_lock`.
        self._lock = threading.RLock()
        # Serializes probe() and SetVCPFeature. Re-entrant so a write can
        # probe, write, and read back without a second hardware owner.
        # List singleflight waits on the Future, not on this lock, so a second
        # GET does not queue its own DDC pass behind the first.
        self._hw_lock = threading.RLock()
        self._flight_lock = threading.Lock()
        self._cache: tuple[float, list[MonitorRecord]] | None = None
        self._list_flight: Future[list[MonitorRecord]] | None = None
        self._list_waiters = 0
        self._probe_generation = 0

    @property
    def backend_name(self) -> str:
        return self.backend.name

    def enumerate_monitors(self) -> list[MonitorView]:
        return [record.view for record in self._load(fresh=False)]

    def probe(self, monitor_id: str | None = None) -> list[MonitorView]:
        records = self._load(fresh=True)
        if monitor_id is None:
            return [record.view for record in records]
        found = [record.view for record in records if record.view.id == monitor_id]
        if not found:
            raise DisplayError("unknown_monitor", monitor_id=monitor_id)
        return found

    def get_luminance(self, monitor_id: str) -> LuminanceReading:
        view = self._record(monitor_id, fresh=True).view
        if view.failure or view.current is None or view.maximum is None:
            raise DisplayError(
                view.failure or "probe_failed",
                view.message,
                monitor_id=monitor_id,
                winerr=view.winerr,
            )
        return LuminanceReading(view.id, view.current, view.maximum)

    def set_luminance_safe(
        self,
        monitor_id: str,
        value: int,
        *,
        confirm: bool = False,
    ) -> SetResult:
        """Set VCP 0x10 after a fresh probe and an explicit confirm."""
        return self.set_feature_safe(monitor_id, "luminance", value, confirm=confirm)

    def set_contrast_safe(
        self,
        monitor_id: str,
        value: int,
        *,
        confirm: bool = False,
    ) -> SetResult:
        """Set VCP 0x12 after a fresh probe and an explicit confirm."""
        return self.set_feature_safe(monitor_id, "contrast", value, confirm=confirm)

    def set_volume_safe(
        self,
        monitor_id: str,
        value: int,
        *,
        confirm: bool = False,
    ) -> SetResult:
        """Set VCP 0x62 after a fresh probe and an explicit confirm."""
        return self.set_feature_safe(monitor_id, "volume", value, confirm=confirm)

    def set_feature_safe(
        self,
        monitor_id: str,
        feature: str,
        value: int,
        *,
        confirm: bool = False,
    ) -> SetResult:
        """Set an allow-listed VCP after a fresh successful probe and explicit confirm.

        On readback mismatch the previous value is written once. There is no
        second attempt at ``value``.
        """
        if confirm is not True:
            raise DisplayError("confirm_required", monitor_id=monitor_id)
        code = code_for_feature(feature)
        ensure_write_code(code)
        _require_percent(value)
        # Hardware lock first, then the write section. A list probe holds
        # `_hw_lock` only for the DDC call and never takes `_lock` while
        # waiting for it, so these two cannot deadlock.
        with self._hw_lock:
            with self._lock:
                record = self._record(monitor_id, fresh=True)
                view = record.view
                previous, maximum = self._feature_reading(view, code)
                if previous is None or maximum is None:
                    raise DisplayError(
                        view.failure or "probe_failed",
                        view.message,
                        monitor_id=monitor_id,
                        winerr=view.winerr,
                    )
                if not self._feature_writable(view, code):
                    raise DisplayError(
                        view.failure or "probe_failed",
                        view.message,
                        monitor_id=monitor_id,
                        winerr=view.winerr,
                    )
                if value > maximum:
                    raise DisplayError("value_out_of_range", monitor_id=monitor_id)
                if previous == value:
                    return SetResult(view.id, value, previous, previous, noop=True)
                self.limiter.commit(monitor_id)
                log.info("%s write id=%s code=0x%02X from=%s to=%s", feature, view.id, code, previous, value)
                return self._write_and_verify(record, code, value, previous)

    def _feature_writable(self, view, code: int) -> bool:
        if code == LUMINANCE_VCP:
            return bool(view.writable and view.capabilities.luminance.writable)
        if code == CONTRAST_VCP:
            cap = view.capabilities.contrast
            return bool(cap is not None and cap.writable)
        if code == VOLUME_VCP:
            cap = view.capabilities.volume
            return bool(cap is not None and cap.writable)
        return False

    def _feature_reading(self, view, code: int) -> tuple[int | None, int | None]:
        if code == LUMINANCE_VCP:
            if view.failure or not view.writable or view.current is None or view.maximum is None:
                return None, None
            return view.current, view.maximum
        if code == CONTRAST_VCP:
            cap = view.capabilities.contrast
        elif code == VOLUME_VCP:
            cap = view.capabilities.volume
        else:
            return None, None
        if cap is None or not cap.readable or cap.current is None or cap.maximum is None:
            return None, None
        return cap.current, cap.maximum

    def _write_and_verify(
        self, record: MonitorRecord, code: int, value: int, previous: int
    ) -> SetResult:
        write_error: DisplayError | None = None
        try:
            self.backend.set_vcp(record.raw, code, value)
        except DisplayError as exc:
            # unknown/ambiguous/policy means SetVCPFeature was not called.
            if exc.kind != "write_failed":
                raise
            write_error = exc
        seen = self._await_value(record.view.id, code, value)
        if seen is not None and abs(seen - value) <= VERIFY_TOLERANCE:
            return SetResult(record.view.id, value, previous, seen, noop=False)
        if seen is None or (write_error is not None and seen == previous):
            if write_error is not None:
                raise DisplayError(
                    "write_failed",
                    monitor_id=record.view.id,
                    previous=previous,
                    requested=value,
                    verified=seen,
                    winerr=write_error.details.get("winerr"),
                ) from write_error
            raise DisplayError(
                "verify_unconfirmed",
                monitor_id=record.view.id,
                previous=previous,
                requested=value,
            )
        restored = self._rollback(record, code, previous, value, seen)
        raise DisplayError(
            "verify_mismatch",
            monitor_id=record.view.id,
            previous=previous,
            requested=value,
            verified=seen,
            restored=restored,
            rolled_back=True,
        )

    def _rollback(
        self, record: MonitorRecord, code: int, previous: int, value: int, seen: int
    ) -> int:
        try:
            log.warning(
                "vcp readback mismatch id=%s code=0x%02X requested=%s read=%s; rolling back to %s",
                record.view.id,
                code,
                value,
                seen,
                previous,
            )
            self.backend.set_vcp(record.raw, code, previous)
        except DisplayError as exc:
            raise DisplayError(
                "rollback_failed",
                monitor_id=record.view.id,
                previous=previous,
                requested=value,
                verified=seen,
                rolled_back=False,
            ) from exc
        restored = self._await_value(record.view.id, code, previous)
        if restored is None or abs(restored - previous) > VERIFY_TOLERANCE:
            raise DisplayError(
                "rollback_failed",
                monitor_id=record.view.id,
                previous=previous,
                requested=value,
                verified=seen,
                restored=restored,
                rolled_back=False,
            )
        return restored

    def _await_value(self, monitor_id: str, code: int, expected: int) -> int | None:
        seen: int | None = None
        for _ in range(VERIFY_READS):
            self.sleep(VERIFY_SETTLE_S)
            seen = self._read_current(monitor_id, code)
            if seen is not None and abs(seen - expected) <= VERIFY_TOLERANCE:
                return seen
        return seen

    def _read_current(self, monitor_id: str, code: int = LUMINANCE_VCP) -> int | None:
        try:
            records = self._load(fresh=True)
        except DisplayError:
            return None
        for record in records:
            if record.view.id != monitor_id:
                continue
            current, _maximum = self._feature_reading(record.view, code)
            return current
        return None

    def _record(self, monitor_id: str, *, fresh: bool) -> MonitorRecord:
        matches = [record for record in self._load(fresh=fresh) if record.view.id == monitor_id]
        if not matches:
            raise DisplayError("unknown_monitor", monitor_id=monitor_id)
        if len(matches) > 1:
            raise DisplayError("identity_ambiguous", monitor_id=monitor_id)
        return matches[0]

    def _load(self, *, fresh: bool) -> list[MonitorRecord]:
        if fresh:
            return self._load_fresh()
        return self._load_shared()

    def _cached_records(self) -> list[MonitorRecord] | None:
        """Caller holds ``_lock``."""
        if self._cache is None:
            return None
        stamped, cached = self._cache
        if self.clock() - stamped < PROBE_CACHE_S:
            return cached
        return None

    def _load_fresh(self) -> list[MonitorRecord]:
        """A write, ``probe()``, or ``get_luminance`` read. Never a list snapshot.

        Nested calls from ``set_luminance_safe`` already hold both locks.
        """
        with self._hw_lock:
            with self._lock:
                records = build_records(self.backend.probe())
                self._probe_generation += 1
                self._cache = (self.clock(), records)
                return records

    def _load_shared(self) -> list[MonitorRecord]:
        """One in-flight list probe. Later list callers wait for that result.

        The hardware lock is not held while waiting to join, and it is not
        held across the Future wait. Physical monitors inside ``probe()`` stay
        serial because every DDC entry takes ``_hw_lock``.
        """
        with self._lock:
            hit = self._cached_records()
            if hit is not None:
                return hit
        with self._flight_lock:
            flight = self._list_flight
            if flight is None or flight.done():
                flight = Future()
                self._list_flight = flight
                leader = True
            else:
                leader = False
                self._list_waiters += 1
        if not leader:
            try:
                return flight.result()
            finally:
                with self._flight_lock:
                    self._list_waiters -= 1
        try:
            records = self._probe_list()
        except BaseException as exc:
            if not flight.done():
                flight.set_exception(exc)
            raise
        else:
            flight.set_result(records)
            return records
        finally:
            with self._flight_lock:
                if self._list_flight is flight:
                    self._list_flight = None

    def _probe_list(self) -> list[MonitorRecord]:
        """List-only probe. Does not run in parallel with a fresh probe or a write.

        ``_lock`` is released around the DDC call so other list callers can
        join the flight. A fresh probe that lands in that window bumps
        ``_probe_generation`` and must not be overwritten by this older pass.
        """
        with self._hw_lock:
            with self._lock:
                generation = self._probe_generation
                hit = self._cached_records()
                if hit is not None:
                    return hit
            raws = self.backend.probe()
        records = build_records(raws)
        with self._lock:
            if generation == self._probe_generation:
                self._probe_generation += 1
                self._cache = (self.clock(), records)
        return records


def _require_percent(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DisplayError("value_out_of_range")
    if value < LUMINANCE_MIN or value > LUMINANCE_MAX:
        raise DisplayError("value_out_of_range")


def default_service() -> DisplayService:
    global _default
    with _default_guard:
        if _default is None:
            _default = DisplayService(default_backend())
        return _default


def enumerate_monitors() -> list[MonitorView]:
    return default_service().enumerate_monitors()


def probe(monitor_id: str | None = None) -> list[MonitorView]:
    return default_service().probe(monitor_id)


def get_luminance(monitor_id: str) -> LuminanceReading:
    return default_service().get_luminance(monitor_id)


def set_luminance_safe(monitor_id: str, value: int, *, confirm: bool = False) -> SetResult:
    return default_service().set_luminance_safe(monitor_id, value, confirm=confirm)


def set_contrast_safe(monitor_id: str, value: int, *, confirm: bool = False) -> SetResult:
    return default_service().set_contrast_safe(monitor_id, value, confirm=confirm)


def set_volume_safe(monitor_id: str, value: int, *, confirm: bool = False) -> SetResult:
    return default_service().set_volume_safe(monitor_id, value, confirm=confirm)
