"""Throttled visibility for degraded session reads.

Session list/query fallbacks used to swallow directory read failures silently:
callers fell back to the discarded JSON projection and rebuilt for tens of
seconds with no operator signal. This module owns that throttled warning so
every read path (directory bridge, catalog, projection, turn diagnostics)
reports degradation through one place and one import direction, instead of
reaching back into ``directory_bridge``.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from . import directory_runtime


logger = logging.getLogger(__name__)

SESSION_READ_DEGRADED_LOG_INTERVAL_SECONDS = 60.0


@dataclass
class _DegradationBucket:
    last_emit_monotonic: float = 0.0
    suppressed_since_last_emit: int = 0


_buckets_lock = threading.Lock()
_buckets: dict[str, _DegradationBucket] = {}


def note_session_read_degraded(*, source: str, error_type: str = "") -> None:
    """Throttled per-source visibility for a degraded session read.

    A missing store or a raising read used to be invisible: list/query simply
    fell back to the discarded JSON projection and rebuilt for tens of seconds.
    Callers still get their fallback, but operators get a throttled warning
    naming the runtime status and error type.

    Throttling is per source, so one chatty source can no longer swallow the
    warning for every other source. Each emitted line reports how many hits it
    stood for, so a one-off blip reads differently from a persistent
    regression. A source's first degradation always logs, so a cold process
    never hides its first failure behind the throttle window.
    """

    key = str(source or "unknown")
    now = time.monotonic()
    with _buckets_lock:
        bucket = _buckets.get(key)
        if bucket is None:
            bucket = _DegradationBucket()
            _buckets[key] = bucket
        elif now - bucket.last_emit_monotonic < SESSION_READ_DEGRADED_LOG_INTERVAL_SECONDS:
            bucket.suppressed_since_last_emit += 1
            return
        suppressed = bucket.suppressed_since_last_emit
        bucket.suppressed_since_last_emit = 0
        bucket.last_emit_monotonic = now
    runtime_status = directory_runtime.current_directory_runtime_status()
    logger.warning(
        "Session read degraded (status=%s error=%s detail=%s suppressed=%d); %s reads fall back.",
        str(getattr(runtime_status, "status", "") or "idle"),
        str(getattr(runtime_status, "error_type", "") or "none"),
        str(error_type or "none"),
        suppressed,
        key,
    )


def session_read_degradation_snapshot() -> dict[str, dict[str, Any]]:
    """Read-only per-source degradation state for tests and telemetry."""

    with _buckets_lock:
        return {
            key: {
                "lastEmitMonotonic": bucket.last_emit_monotonic,
                "suppressed": bucket.suppressed_since_last_emit,
            }
            for key, bucket in _buckets.items()
        }


def reset_session_read_degradation_state() -> None:
    """Clear throttled state; call between tests or after a runtime restart."""

    with _buckets_lock:
        _buckets.clear()
