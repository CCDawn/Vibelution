"""T4 RED: fork lineage — child threads inherit parent checkpoints, parents
stay immutable, revise_protocol forks a child run."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._support.graph_helpers import GraphHarness


def test_fork_creates_child_thread_scheduled_at_resume_node(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed(run_id="run-parent")
        harness.enqueue_graph_dispatch("run-parent", "source_finding", 1)
        harness.worker.run_once()
        harness.resume(
            run_id="run-parent",
            node_id="source_finding",
            attempt=1,
        )
        harness.worker.run_once()
        parent_snapshot = harness.coordinator.snapshot("run-parent")
        parent_checkpoint_id = parent_snapshot["checkpointId"]
        assert parent_checkpoint_id

        child_checkpoint_id = harness.coordinator.fork_from_checkpoint(
            source_thread_id="run-parent",
            source_checkpoint_id=parent_checkpoint_id,
            child_thread_id="run-child",
            resume_node_id="source_finding",
        )
        assert child_checkpoint_id
        child_snapshot = harness.coordinator.snapshot("run-child")
        assert child_snapshot["nextNodeIds"] == ["source_finding"]
        # 父线程不受影响。
        parent_again = harness.coordinator.snapshot("run-parent")
        assert parent_again["nextNodeIds"] == ["source_extraction"]
        assert parent_again["checkpointId"] == parent_checkpoint_id
    finally:
        harness.close()


def test_fork_child_runs_independently(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed(run_id="run-parent")
        harness.enqueue_graph_dispatch("run-parent", "source_finding", 1)
        harness.worker.run_once()
        parent_snapshot = harness.coordinator.snapshot("run-parent")
        harness.coordinator.fork_from_checkpoint(
            source_thread_id="run-parent",
            source_checkpoint_id=parent_snapshot["checkpointId"],
            child_thread_id="run-child",
            resume_node_id="source_finding",
            state_patch={"input_snapshot_hash": "c" * 64},
        )
        # child 独立执行 source_finding（child run 已在 Ledger 建行）。
        harness.seed(run_id="run-child")
        harness.enqueue_graph_dispatch(
            "run-child",
            "source_finding",
            1,
            input_snapshot_hash="c" * 64,
            command_id="cmd-child",
        )
        harness.worker.run_once()
        pending = harness.latest_adapter_pending("run-child")
        assert pending is not None
        import json

        payload = json.loads(pending.payload_json)
        assert payload["nodeId"] == "source_finding"
        assert payload["inputSnapshotHash"] == "c" * 64
    finally:
        harness.close()


def test_fork_existing_child_thread_same_resume_is_idempotent(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed(run_id="run-parent")
        harness.enqueue_graph_dispatch("run-parent", "source_finding", 1)
        harness.worker.run_once()
        parent_snapshot = harness.coordinator.snapshot("run-parent")
        first = harness.coordinator.fork_from_checkpoint(
            source_thread_id="run-parent",
            source_checkpoint_id=parent_snapshot["checkpointId"],
            child_thread_id="run-child",
            resume_node_id="source_finding",
        )
        second = harness.coordinator.fork_from_checkpoint(
            source_thread_id="run-parent",
            source_checkpoint_id=parent_snapshot["checkpointId"],
            child_thread_id="run-child",
            resume_node_id="source_finding",
        )
        assert second == first
        with pytest.raises(RuntimeError, match="different state"):
            harness.coordinator.fork_from_checkpoint(
                source_thread_id="run-parent",
                source_checkpoint_id=parent_snapshot["checkpointId"],
                child_thread_id="run-child",
                resume_node_id="source_extraction",
            )
    finally:
        harness.close()
