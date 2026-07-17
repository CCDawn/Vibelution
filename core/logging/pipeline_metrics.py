"""Non-recursive, bounded self-metrics for the logging pipeline.

This module deliberately has no dependency on any Vibelution logger.  Logging
code can therefore measure itself without creating recursive log events or
persisting user/model/tool content in the metrics snapshot.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic_ns
from typing import Iterator


PIPELINE_METRICS_SCHEMA_VERSION = 1

OPERATION_ENQUEUE = "enqueue"
OPERATION_SERIALIZE = "serialize"
OPERATION_APPEND = "append"
OPERATION_PROJECTION = "projection"
OPERATION_FLUSH = "flush"
OPERATION_ROTATE = "rotate"
OPERATION_SHUTDOWN = "shutdown"

_ALLOWED_OPERATIONS = frozenset(
    {
        OPERATION_ENQUEUE,
        OPERATION_SERIALIZE,
        OPERATION_APPEND,
        OPERATION_PROJECTION,
        OPERATION_FLUSH,
        OPERATION_ROTATE,
        OPERATION_SHUTDOWN,
    }
)
_ALLOWED_PRIORITIES = frozenset({"state", "critical", "operational", "diagnostic", "debug"})
_ALLOWED_OUTCOMES = frozenset({"succeeded", "failed", "degraded", "dropped"})
_LATENCY_BUCKETS_MS = (
    0.05,
    0.1,
    0.2,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    20.0,
    50.0,
    100.0,
    250.0,
    500.0,
    1000.0,
    5000.0,
)


def _bounded_label(value: str, allowed: frozenset[str], fallback: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else fallback


@dataclass
class _OperationMetrics:
    count: int = 0
    total_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
    total_bytes: int = 0
    total_batch_items: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    priorities: dict[str, int] = field(default_factory=dict)
    buckets: list[int] = field(default_factory=lambda: [0] * (len(_LATENCY_BUCKETS_MS) + 1))

    def observe(
        self,
        *,
        duration_ms: float,
        bytes_processed: int,
        batch_items: int,
        priority: str,
        outcome: str,
    ) -> None:
        safe_duration = max(0.0, float(duration_ms or 0.0))
        self.count += 1
        self.total_duration_ms += safe_duration
        self.max_duration_ms = max(self.max_duration_ms, safe_duration)
        self.total_bytes += max(0, int(bytes_processed or 0))
        self.total_batch_items += max(0, int(batch_items or 0))
        self.outcomes[outcome] = self.outcomes.get(outcome, 0) + 1
        self.priorities[priority] = self.priorities.get(priority, 0) + 1
        bucket_index = len(_LATENCY_BUCKETS_MS)
        for index, upper_bound in enumerate(_LATENCY_BUCKETS_MS):
            if safe_duration <= upper_bound:
                bucket_index = index
                break
        self.buckets[bucket_index] += 1

    def snapshot(self) -> dict[str, object]:
        count = self.count
        return {
            "count": count,
            "totalDurationMs": round(self.total_duration_ms, 3),
            "averageDurationMs": round(self.total_duration_ms / count, 3) if count else 0.0,
            "maxDurationMs": round(self.max_duration_ms, 3),
            "p50UpperBoundMs": _percentile_upper_bound(self.buckets, count, 0.50),
            "p95UpperBoundMs": _percentile_upper_bound(self.buckets, count, 0.95),
            "p99UpperBoundMs": _percentile_upper_bound(self.buckets, count, 0.99),
            "totalBytes": self.total_bytes,
            "totalBatchItems": self.total_batch_items,
            "outcomes": dict(sorted(self.outcomes.items())),
            "priorities": dict(sorted(self.priorities.items())),
        }


def _percentile_upper_bound(buckets: list[int], count: int, percentile: float) -> float | str:
    if count <= 0:
        return 0.0
    target = max(1, int(count * percentile + 0.999999))
    observed = 0
    for index, bucket_count in enumerate(buckets):
        observed += bucket_count
        if observed < target:
            continue
        if index >= len(_LATENCY_BUCKETS_MS):
            return ">5000"
        return _LATENCY_BUCKETS_MS[index]
    return ">5000"


class LoggingPipelineMetrics:
    """Thread-safe fixed-cardinality metrics registry for logging hot paths."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._operations: dict[str, _OperationMetrics] = {}
        self._queue_capacity = 0
        self._queue_current_depth = 0
        self._queue_high_watermark = 0
        self._queue_saturation_count = 0
        self._drops: dict[str, int] = {}

    def observe(
        self,
        operation: str,
        duration_ms: float,
        *,
        priority: str = "operational",
        outcome: str = "succeeded",
        bytes_processed: int = 0,
        batch_items: int = 0,
    ) -> None:
        operation_name = _bounded_label(operation, _ALLOWED_OPERATIONS, "other")
        priority_name = _bounded_label(priority, _ALLOWED_PRIORITIES, "operational")
        outcome_name = _bounded_label(outcome, _ALLOWED_OUTCOMES, "degraded")
        with self._lock:
            metric = self._operations.setdefault(operation_name, _OperationMetrics())
            metric.observe(
                duration_ms=duration_ms,
                bytes_processed=bytes_processed,
                batch_items=batch_items,
                priority=priority_name,
                outcome=outcome_name,
            )

    @contextmanager
    def measure(
        self,
        operation: str,
        *,
        priority: str = "operational",
        bytes_processed: int = 0,
        batch_items: int = 0,
    ) -> Iterator[None]:
        started_ns = monotonic_ns()
        outcome = "succeeded"
        try:
            yield
        except BaseException:
            outcome = "failed"
            raise
        finally:
            self.observe(
                operation,
                (monotonic_ns() - started_ns) / 1_000_000,
                priority=priority,
                outcome=outcome,
                bytes_processed=bytes_processed,
                batch_items=batch_items,
            )

    def observe_queue_depth(self, depth: int, *, capacity: int = 0) -> None:
        safe_depth = max(0, int(depth or 0))
        safe_capacity = max(0, int(capacity or 0))
        with self._lock:
            if safe_capacity:
                self._queue_capacity = safe_capacity
            self._queue_current_depth = safe_depth
            self._queue_high_watermark = max(self._queue_high_watermark, safe_depth)
            effective_capacity = safe_capacity or self._queue_capacity
            if effective_capacity and safe_depth >= effective_capacity:
                self._queue_saturation_count += 1

    def note_drop(self, *, priority: str, reason: str) -> None:
        priority_name = _bounded_label(priority, _ALLOWED_PRIORITIES, "operational")
        normalized_reason = str(reason or "unknown").strip().lower()
        reason_name = normalized_reason if normalized_reason in {"queue_full", "sampled", "shutdown", "writer_failed"} else "other"
        key = f"{priority_name}:{reason_name}"
        with self._lock:
            self._drops[key] = self._drops.get(key, 0) + 1

    def snapshot(self, *, reset: bool = False) -> dict[str, object]:
        with self._lock:
            payload = {
                "schemaVersion": PIPELINE_METRICS_SCHEMA_VERSION,
                "operations": {
                    name: metric.snapshot()
                    for name, metric in sorted(self._operations.items())
                },
                "queue": {
                    "capacity": self._queue_capacity,
                    "currentDepth": self._queue_current_depth,
                    "highWatermark": self._queue_high_watermark,
                    "saturationCount": self._queue_saturation_count,
                },
                "drops": dict(sorted(self._drops.items())),
            }
            if reset:
                self._operations.clear()
                self._queue_current_depth = 0
                self._queue_high_watermark = 0
                self._queue_saturation_count = 0
                self._drops.clear()
            return payload


pipeline_metrics = LoggingPipelineMetrics()


__all__ = [
    "LoggingPipelineMetrics",
    "OPERATION_APPEND",
    "OPERATION_ENQUEUE",
    "OPERATION_FLUSH",
    "OPERATION_PROJECTION",
    "OPERATION_ROTATE",
    "OPERATION_SERIALIZE",
    "OPERATION_SHUTDOWN",
    "PIPELINE_METRICS_SCHEMA_VERSION",
    "pipeline_metrics",
]
