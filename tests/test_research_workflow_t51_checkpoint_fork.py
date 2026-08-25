"""T5.1-7: real checkpoint fork + child resume (threadId == runId)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.web.services.team_workflow.research_runtime.command_service import (
    WorkflowCommandError,
)
from core.web.services.team_workflow.research_runtime.fork_coordinator import (
    execute_checkpoint_fork,
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
        harness.start_thread_to("source_finding", run_id="run-parent")
        parent_snap = harness.coordinator.snapshot("run-parent")
        parent_ckpt = parent_snap["checkpointId"]
        assert parent_ckpt
        assert parent_snap["nextNodeIds"] == ["source_finding"]

        with server_operator_scope("u-1", roles=("operator",)):
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

        fork_outbox = harness.commands.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT action_kind, status FROM outbox_actions "
                "WHERE run_id = ? AND action_kind = 'checkpoint_fork'",
                (child_run_id,),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert fork_outbox and fork_outbox[0][1] == "pending"

        # Durable outbox worker performs checkpoint I/O then enqueues graph_dispatch.
        assert harness.fork_worker.run_once() == 1

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


def test_checkpoint_fork_replay_when_child_already_forked_enqueues_dispatch(
    tmp_path: Path,
) -> None:
    """P1: fork I/O succeeded, Ledger ack failed — replay must not reconcile."""
    harness = GraphHarness(tmp_path)
    try:
        harness.commands.command_service._coordinator_factory = (  # noqa: SLF001
            lambda: harness.coordinator
        )
        harness.seed(run_id="run-parent")
        harness.start_thread_to("source_finding", run_id="run-parent")
        parent_ckpt = harness.coordinator.snapshot("run-parent")["checkpointId"]
        assert parent_ckpt

        with server_operator_scope("u-1", roles=("operator",)):
            harness.commands.command_service.submit(
                harness.commands.request(
                    command=WorkflowCommandKind.FORK_REVISION,
                    run_id="run-parent",
                    node_id="source_finding",
                    expected_run_version=1,
                    idempotency_key="ui:fork-replay-half",
                    payload={
                        "fromNodeId": "source_finding",
                        "reason": "simulate crash after fork I/O",
                        "checkpointId": parent_ckpt,
                    },
                )
            )

        child_run_id = harness.commands.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT run_id FROM workflow_runs WHERE parent_run_id = 'run-parent'"
            ).fetchone()[0],
            force_flush=True,
        ).result(timeout=10)

        # External half-success: LangGraph fork done; outbox still pending.
        execute_checkpoint_fork(
            harness.coordinator,
            parent_run_id="run-parent",
            checkpoint_id=parent_ckpt,
            child_run_id=child_run_id,
            resume_node_id="source_finding",
            state_patch={
                "run_id": child_run_id,
                "parent_run_id": "run-parent",
                "active_node_id": "source_finding",
                "active_attempt": 1,
                "node_attempts": {"source_finding": 1},
            },
        )
        child_snap = harness.coordinator.snapshot(child_run_id)
        assert child_snap["checkpointId"]
        assert child_snap["nextNodeIds"] == ["source_finding"]

        fork_row = harness.commands.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT action_id, status FROM outbox_actions "
                "WHERE run_id = ? AND action_kind = 'checkpoint_fork'",
                (child_run_id,),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert fork_row is not None
        assert fork_row[1] == "pending"

        assert harness.fork_worker.run_once() == 1

        fork_after = harness.commands.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status FROM outbox_actions WHERE action_id = ?",
                (fork_row[0],),
            ).fetchone()[0],
            force_flush=True,
        ).result(timeout=10)
        assert fork_after == "succeeded"

        child_status = harness.commands.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status FROM workflow_runs WHERE run_id = ?",
                (child_run_id,),
            ).fetchone()[0],
            force_flush=True,
        ).result(timeout=10)
        assert child_status != "reconciliation_required"

        graph_dispatch = harness.commands.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT action_id, status FROM outbox_actions "
                "WHERE run_id = ? AND action_kind = 'graph_dispatch'",
                (child_run_id,),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert len(graph_dispatch) == 1
        assert graph_dispatch[0][1] == "pending"
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
        harness.start_thread_to("source_finding", run_id="run-parent")

        with server_operator_scope("u-1", roles=("operator",)):
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

        assert harness.fork_worker.run_once() == 1
        child = harness.commands.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT run_id, status, blocked_problem_json FROM workflow_runs "
                "WHERE parent_run_id = 'run-parent'"
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert child is not None
        assert child[1] == "reconciliation_required"
        assert "checkpoint" in str(child[2] or "").lower()
        graph_dispatch = harness.commands.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT action_id FROM outbox_actions "
                "WHERE run_id = ? AND action_kind = 'graph_dispatch'",
                (child[0],),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert graph_dispatch == []
    finally:
        harness.close()
