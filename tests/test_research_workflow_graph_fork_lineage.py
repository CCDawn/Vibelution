"""T4 RED: fork lineage — child threads inherit parent checkpoints, parents
stay immutable, revise_protocol forks a child run."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import definition_identity
from tests._support.graph_helpers import GraphHarness


CURRENT_VERSION_ID = definition_identity(
    build_challenge_cup_workflow_definition()
).workflowVersionId


def test_fork_creates_child_thread_scheduled_at_resume_node(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed(run_id="run-parent")
        harness.start_thread_to("hypothesis_design", run_id="run-parent")
        harness.resume(
            run_id="run-parent",
            node_id="hypothesis_design",
            attempt=1,
        )
        harness.worker.run_once()
        parent_snapshot = harness.coordinator.snapshot("run-parent", CURRENT_VERSION_ID)
        parent_checkpoint_id = parent_snapshot["checkpointId"]
        assert parent_checkpoint_id

        child_checkpoint_id = harness.coordinator.fork_from_checkpoint(
            workflow_version_id=CURRENT_VERSION_ID,
            source_thread_id="run-parent",
            source_checkpoint_id=parent_checkpoint_id,
            child_thread_id="run-child",
            resume_node_id="hypothesis_design",
        )
        assert child_checkpoint_id
        child_snapshot = harness.coordinator.snapshot("run-child", CURRENT_VERSION_ID)
        assert child_snapshot["nextNodeIds"] == ["hypothesis_design"]
        # 父线程不受影响。
        parent_again = harness.coordinator.snapshot("run-parent", CURRENT_VERSION_ID)
        assert parent_again["nextNodeIds"] == ["protocol_design"]
        assert parent_again["checkpointId"] == parent_checkpoint_id
    finally:
        harness.close()


def test_fork_child_runs_independently(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed(run_id="run-parent")
        harness.start_thread_to("hypothesis_design", run_id="run-parent")
        parent_snapshot = harness.coordinator.snapshot("run-parent", CURRENT_VERSION_ID)
        harness.coordinator.fork_from_checkpoint(
            workflow_version_id=CURRENT_VERSION_ID,
            source_thread_id="run-parent",
            source_checkpoint_id=parent_snapshot["checkpointId"],
            child_thread_id="run-child",
            resume_node_id="hypothesis_design",
            state_patch={"input_snapshot_hash": "c" * 64},
        )
        # child 独立执行 hypothesis_design（child run 已在 Ledger 建行）。
        harness.seed(run_id="run-child")
        harness.enqueue_graph_dispatch(
            "run-child",
            "hypothesis_design",
            1,
            input_snapshot_hash="c" * 64,
            command_id="cmd-child",
        )
        harness.worker.run_once()
        pending = harness.latest_adapter_pending("run-child")
        assert pending is not None
        import json

        payload = json.loads(pending.payload_json)
        assert payload["nodeId"] == "hypothesis_design"
        assert payload["inputSnapshotHash"] == "c" * 64
    finally:
        harness.close()


def test_fork_existing_child_thread_same_resume_is_idempotent(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed(run_id="run-parent")
        harness.start_thread_to("hypothesis_design", run_id="run-parent")
        parent_snapshot = harness.coordinator.snapshot("run-parent", CURRENT_VERSION_ID)
        first = harness.coordinator.fork_from_checkpoint(
            workflow_version_id=CURRENT_VERSION_ID,
            source_thread_id="run-parent",
            source_checkpoint_id=parent_snapshot["checkpointId"],
            child_thread_id="run-child",
            resume_node_id="hypothesis_design",
        )
        second = harness.coordinator.fork_from_checkpoint(
            workflow_version_id=CURRENT_VERSION_ID,
            source_thread_id="run-parent",
            source_checkpoint_id=parent_snapshot["checkpointId"],
            child_thread_id="run-child",
            resume_node_id="hypothesis_design",
        )
        assert second == first
        with pytest.raises(RuntimeError, match="different state"):
            harness.coordinator.fork_from_checkpoint(
                workflow_version_id=CURRENT_VERSION_ID,
                source_thread_id="run-parent",
                source_checkpoint_id=parent_snapshot["checkpointId"],
                child_thread_id="run-child",
                resume_node_id="protocol_design",
            )
    finally:
        harness.close()


def test_fork_state_patch_declared_channels_reach_child_checkpoint(
    tmp_path: Path,
) -> None:
    """Fork patches must persist their contract/parent identity channels.

    Before ``parent_run_id`` and ``evidence_remediation_contract`` were
    declared graph channels, langgraph silently dropped them from the fork
    state patch, so child checkpoints lost the fork contract.
    """

    harness = GraphHarness(tmp_path)
    try:
        harness.seed(run_id="run-parent")
        harness.start_thread_to("hypothesis_design", run_id="run-parent")
        parent_snapshot = harness.coordinator.snapshot("run-parent", CURRENT_VERSION_ID)
        contract = {
            "schemaVersion": 1,
            "parentRunId": "run-parent",
            "sourceNodeId": "protocol_design",
            "resolutionKind": "add_budget",
        }
        harness.coordinator.fork_from_checkpoint(
            workflow_version_id=CURRENT_VERSION_ID,
            source_thread_id="run-parent",
            source_checkpoint_id=parent_snapshot["checkpointId"],
            child_thread_id="run-child",
            resume_node_id="hypothesis_design",
            state_patch={
                "parent_run_id": "run-parent",
                "evidence_remediation_contract": contract,
            },
        )
        child_values = dict(
            harness.coordinator.snapshot("run-child", CURRENT_VERSION_ID).get("values") or {}
        )
        assert child_values.get("parent_run_id") == "run-parent"
        assert child_values.get("evidence_remediation_contract") == contract
        # The parent thread keeps its own state (no patch leakage).
        parent_again = harness.coordinator.snapshot("run-parent", CURRENT_VERSION_ID)
        parent_values = dict(parent_again.get("values") or {})
        assert "parent_run_id" not in parent_values
        assert "evidence_remediation_contract" not in parent_values
    finally:
        harness.close()
