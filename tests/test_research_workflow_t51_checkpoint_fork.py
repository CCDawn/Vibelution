"""T5.1-7: real checkpoint fork + child resume (threadId == runId)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.web.services.team_workflow.research_runtime.command_service import (
    WorkflowCommandError,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope,
)
from tests._support.graph_helpers import GraphHarness


def test_fork_revision_requires_checkpoint_id(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed(run_id="run-parent")
        harness.commands.service.submit(
            harness.commands.request(run_id="run-parent", idempotency_key="ui:start")
        )
        with pytest.raises(WorkflowCommandError, match="checkpointId"):
            harness.commands.service.submit(
                harness.commands.request(
                    command=WorkflowCommandKind.FORK_REVISION,
                    run_id="run-parent",
                    node_id="source_finding",
                    expected_run_version=2,
                    idempotency_key="ui:fork-no-ckpt",
                    payload={
                        "fromNodeId": "source_finding",
                        "reason": "missing checkpoint",
                    },
                )
            )
    finally:
        harness.close()


def test_fork_revision_child_thread_id_equals_run_id_and_resumes(
    tmp_path: Path,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        # Wire real LangGraph coordinator into command service (production root does).
        harness.commands.command_service._coordinator_factory = (  # noqa: SLF001
            lambda: harness.coordinator
        )

        harness.seed(run_id="run-parent")
        harness.enqueue_graph_dispatch("run-parent", "source_finding", 1)
        harness.worker.run_once()
        parent_snap = harness.coordinator.snapshot("run-parent")
        parent_ckpt = parent_snap["checkpointId"]
        assert parent_ckpt
        assert parent_snap["nextNodeIds"] == ["source_finding"]

        with server_operator_scope("u-1"):
            receipt = harness.commands.command_service.submit(
                harness.commands.request(
                    command=WorkflowCommandKind.FORK_REVISION,
                    run_id="run-parent",
                    node_id="source_finding",
                    expected_run_version=1,
                    idempotency_key="ui:fork-real-1",
                    payload={
                        "fromNodeId": "source_finding",
                        "reason": "branch for independent exploration",
                        "checkpointId": parent_ckpt,
                    },
                )
            )
        assert receipt.status == "accepted"

        child_rows = harness.commands.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT run_id, thread_id, parent_run_id, forked_from_checkpoint_id, "
                "active_node_id, status FROM workflow_runs "
                "WHERE parent_run_id = 'run-parent'"
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert len(child_rows) == 1
        child_run_id, thread_id, parent_id, forked_ckpt, active_node, status = (
            child_rows[0]
        )
        assert parent_id == "run-parent"
        assert thread_id == child_run_id
        assert not str(thread_id).startswith("thread-")
        assert forked_ckpt == parent_ckpt
        assert active_node == "source_finding"
        assert status in {"created", "reconciliation_required"}

        # Post-commit fork must seed child checkpoint at resume node.
        child_snap = harness.coordinator.snapshot(child_run_id)
        assert child_snap["checkpointId"]
        assert child_snap["nextNodeIds"] == ["source_finding"]
        assert child_snap["values"].get("run_id") == child_run_id
        assert child_snap["values"].get("active_node_id") == "source_finding"

        # Parent remains at its own checkpoint (immutable lineage).
        parent_again = harness.coordinator.snapshot("run-parent")
        assert parent_again["checkpointId"] == parent_ckpt
        assert parent_again["nextNodeIds"] == ["source_finding"]

        # Child graph_dispatch recovers from forked checkpoint (no START re-run).
        harness.worker.run_once()
        pending = harness.latest_adapter_pending(child_run_id)
        assert pending is not None
        import json

        payload = json.loads(pending.payload_json)
        assert payload["nodeId"] == "source_finding"
        assert payload["runId"] == child_run_id
    finally:
        harness.close()


def test_fork_checkpoint_failure_marks_reconciliation_required(
    tmp_path: Path,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.commands.command_service._coordinator_factory = (  # noqa: SLF001
            lambda: harness.coordinator
        )
        harness.seed(run_id="run-parent")
        harness.enqueue_graph_dispatch("run-parent", "source_finding", 1)
        harness.worker.run_once()

        with server_operator_scope("u-1"):
            harness.commands.command_service.submit(
                harness.commands.request(
                    command=WorkflowCommandKind.FORK_REVISION,
                    run_id="run-parent",
                    node_id="source_finding",
                    expected_run_version=1,
                    idempotency_key="ui:fork-bad-ckpt",
                    payload={
                        "fromNodeId": "source_finding",
                        "reason": "bad checkpoint probe",
                        "checkpointId": "ckpt-does-not-exist",
                    },
                )
            )

        # Post-commit fork failure marks reconciliation asynchronously.
        import time

        status = None
        problem = None
        for _ in range(50):
            child = harness.commands.store.submit(
                lambda uow: uow.repository.execute(
                    "SELECT run_id, status, blocked_problem_json FROM workflow_runs "
                    "WHERE parent_run_id = 'run-parent'"
                ).fetchone(),
                force_flush=True,
            ).result(timeout=10)
            assert child is not None
            status = child[1]
            problem = child[2]
            if status == "reconciliation_required":
                break
            time.sleep(0.05)
        assert status == "reconciliation_required"
        assert "checkpoint" in str(problem or "").lower()
    finally:
        harness.close()
