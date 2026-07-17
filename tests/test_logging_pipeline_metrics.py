from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from core.logging.pipeline_metrics import LoggingPipelineMetrics


def test_pipeline_metrics_records_bounded_latency_bytes_batches_and_queue_state() -> None:
    metrics = LoggingPipelineMetrics()

    metrics.observe("append", 0.18, bytes_processed=128, batch_items=1)
    metrics.observe("append", 2.4, priority="critical", bytes_processed=256, batch_items=2)
    metrics.observe_queue_depth(3, capacity=8)
    metrics.observe_queue_depth(8)
    metrics.note_drop(priority="diagnostic", reason="sampled")

    snapshot = metrics.snapshot()

    append = snapshot["operations"]["append"]
    assert append["count"] == 2
    assert append["totalBytes"] == 384
    assert append["totalBatchItems"] == 3
    assert append["p50UpperBoundMs"] == 0.2
    assert append["p95UpperBoundMs"] == 5.0
    assert append["priorities"] == {"critical": 1, "operational": 1}
    assert snapshot["queue"] == {
        "capacity": 8,
        "currentDepth": 8,
        "highWatermark": 8,
        "saturationCount": 1,
    }
    assert snapshot["drops"] == {"diagnostic:sampled": 1}


def test_pipeline_metrics_measure_records_failure_without_swallowing_exception() -> None:
    metrics = LoggingPipelineMetrics()

    with pytest.raises(RuntimeError, match="disk unavailable"):
        with metrics.measure("flush", priority="critical"):
            raise RuntimeError("disk unavailable")

    flush = metrics.snapshot()["operations"]["flush"]
    assert flush["count"] == 1
    assert flush["outcomes"] == {"failed": 1}


def test_pipeline_metrics_use_fixed_cardinality_labels_and_reset_atomically() -> None:
    metrics = LoggingPipelineMetrics()

    metrics.observe("attacker-controlled-operation", 1.0, priority="unknown", outcome="unknown")
    metrics.note_drop(priority="unknown", reason="attacker-controlled-reason")

    before_reset = metrics.snapshot(reset=True)
    after_reset = metrics.snapshot()

    assert set(before_reset["operations"]) == {"other"}
    assert before_reset["operations"]["other"]["priorities"] == {"operational": 1}
    assert before_reset["operations"]["other"]["outcomes"] == {"degraded": 1}
    assert before_reset["drops"] == {"operational:other": 1}
    assert after_reset["operations"] == {}
    assert after_reset["drops"] == {}


def test_pipeline_metrics_are_thread_safe_without_logging_dependencies() -> None:
    metrics = LoggingPipelineMetrics()

    def record(index: int) -> None:
        metrics.observe("enqueue", index / 1000, bytes_processed=index, batch_items=1)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(record, range(200)))

    enqueue = metrics.snapshot()["operations"]["enqueue"]
    assert enqueue["count"] == 200
    assert enqueue["totalBytes"] == sum(range(200))
    assert enqueue["totalBatchItems"] == 200
