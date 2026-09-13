"""Focused contract checks for the operator knowledge wait cursor."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.research.workflow.contracts import PendingAction
from core.research.workflow.ledger import (
    CommandRecord,
    KnowledgeInvocationRecord,
    NodeAttemptRecord,
    OutboxRecord,
    RunRecord,
)
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.operator_optimization.knowledge_wait import (
    KnowledgeChildPending,
    _terminal_ready,
)
from tests._support.graph_helpers import GraphHarness
from tests._support.workflow_ledger_helpers import build_event_record


def test_pending_exception_preserves_exact_child_cursor() -> None:
    error = KnowledgeChildPending("inv-1", "run-child-1")
    assert error.invocation_id == "inv-1"
    assert error.child_run_id == "run-child-1"
    assert "run-child-1" in str(error)


def test_terminal_ready_requires_accepted_handoff_for_success() -> None:
    assert _terminal_ready(SimpleNamespace(status="failed", handoff_state="pending"))
    assert _terminal_ready(SimpleNamespace(status="cancelled", handoff_state="pending"))
    assert _terminal_ready(
        SimpleNamespace(status="completed", handoff_state="accepted")
    )
    assert not _terminal_ready(
        SimpleNamespace(status="completed", handoff_state="pending")
    )
    assert not _terminal_ready(
        SimpleNamespace(status="running", handoff_state="accepted")
    )


@pytest.mark.parametrize(
    "terminal,blocked,early",
    [
        ("completed", "", False),
        ("failed", "", False),
        ("cancelled", "", False),
        ("completed", "cancelled", False),
        ("completed", "superseded", False),
        ("completed", "undelivered", False),
        ("completed", "ordinary", False),
        ("completed", "", True),
        ("failed", "", True),
    ],
)
def test_real_sqlite_park_then_terminal_wake_preserves_original_cursor(
    tmp_path, terminal, blocked, early
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed("parent")
        store = harness.commands.store
        action = PendingAction(
            action_id="act-parent-knowledge",
            run_id="parent",
            node_run_id="nr-parent-knowledge",
            node_id="optimization_knowledge",
            attempt=1,
            actor_kind=ActorKind.SYSTEM,
            action_kind="system_action",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="b" * 64,
        )
        child = RunRecord(
            run_id="child-knowledge",
            team_id="research-team",
            workflow_id="challenge-cup-knowledge-sideflow",
            workflow_version_id="v1",
            thread_id="child-knowledge",
            project_id="p",
            question_id="q",
            status="running",
            run_version=1,
            last_event_sequence=0,
            input_snapshot_json="{}",
            input_snapshot_hash="c" * 64,
            safety_limits_json="{}",
            binding_snapshot_set_id="b",
            active_node_id="source_finding",
            parent_run_id="parent",
            forked_from_checkpoint_id=None,
            completion_kind="knowledge_sideflow",
            terminal_reason=None,
            blocked_problem_json=None,
            created_at_ms=1,
            updated_at_ms=1,
            completed_at_ms=None,
        )
        invocation = KnowledgeInvocationRecord(
            invocation_id="inv-1",
            parent_run_id="parent",
            parent_node_id="optimization_knowledge",
            parent_node_run_id="nr-parent-knowledge",
            parent_attempt=1,
            question_id="q",
            scope_hash="s",
            request_hash="r",
            search_envelope_hash="e",
            requirements_hash="g",
            source_policy_version="1",
            knowledge_child_run_id="child-knowledge",
            status="pending",
            knowledge_package_ref=None,
            package_content_hash=None,
            handoff_state="pending",
            error_json=None,
            created_at_ms=1,
            updated_at_ms=1,
        )
        attempt = NodeAttemptRecord(
            node_run_id="nr-parent-knowledge",
            run_id="parent",
            node_id="optimization_knowledge",
            attempt=1,
            actor_kind="system",
            status="dispatching",
            command_id="cmd",
            binding_snapshot_id=None,
            input_snapshot_hash=action.input_snapshot_hash,
            pending_action_id=action.action_id,
            execution_anchor_id=None,
            retry_of_node_run_id=None,
            problem_json=None,
            started_at_ms=1,
            updated_at_ms=1,
            finished_at_ms=None,
        )
        outbox = OutboxRecord(
            action_id=action.action_id,
            run_id="parent",
            command_id="cmd",
            node_run_id=action.node_run_id,
            action_kind="adapter_dispatch",
            idempotency_key="ik",
            payload_json=json.dumps(action.to_dict()),
            status="leased",
            attempt_count=1,
            available_at_ms=1,
            lease_owner="worker",
            lease_expires_at_ms=999999,
            last_problem_json=None,
            created_at_ms=1,
            updated_at_ms=1,
        )

        def seed(uow):
            uow.repository.execute(
                "UPDATE workflow_runs SET workflow_id='operator-optimization', project_id='p', question_id='q', status='running', active_node_id='optimization_knowledge' WHERE run_id='parent'"
            )
            uow.repository.insert_run(child)
            uow.repository.insert_command(
                CommandRecord(
                    command_id="cmd",
                    run_id="parent",
                    team_id="research-team",
                    node_id="optimization_knowledge",
                    command_kind="start_node",
                    expected_run_version=1,
                    accepted_run_version=1,
                    idempotency_key="cmd-ik",
                    request_hash="r",
                    request_json="{}",
                    requested_by_json="{}",
                    status="completed",
                    result_json=None,
                    problem_json=None,
                    created_at_ms=1,
                    completed_at_ms=1,
                )
            )
            uow.repository.insert_attempt(attempt)
            uow.repository.insert_knowledge_invocation(invocation)
            uow.repository.insert_outbox(outbox)

        store.submit(seed, force_flush=True).result(timeout=10)
        from core.web.services.team_workflow.operator_optimization.knowledge_wait import (
            defer_knowledge_child,
            wake_knowledge_child,
        )
        from core.web.services.team_workflow.research_runtime.knowledge_sideflow_service import (
            knowledge_result_event_id,
        )

        def settle(uow):
            uow.repository.update_knowledge_invocation(
                "inv-1",
                20,
                status=terminal,
                handoff_state="accepted",
                package_content_hash="d" * 64,
            )
            if terminal == "completed" and blocked != "undelivered":
                sequence = uow.repository.advance_last_sequence("parent", 1, 20)
                uow.repository.insert_event(
                    build_event_record(
                        sequence,
                        run_id="parent",
                        event_type="knowledge_result_absorbed",
                        event_id=knowledge_result_event_id("inv-1", "d" * 64),
                    )
                )

        if early:
            store.submit(settle, force_flush=True).result(timeout=10)
        defer = lambda: defer_knowledge_child(
            store,
            outbox=outbox,
            action=action,
            error=KnowledgeChildPending("inv-1", "child-knowledge"),
            owner="worker",
            now_ms=10,
        )
        defer()
        defer()  # Replaying a lost lease cannot produce another action.
        parked = store.read(lambda repo: repo.get_outbox(action.action_id))
        assert parked.status == ("pending" if early else "failed")
        assert store.get_run("parent").status == ("running" if early else "blocked")
        assert (
            store.latest_attempt("parent", "optimization_knowledge").status == "running"
        )
        problem = json.loads(parked.last_problem_json)
        assert problem["action"]["actionId"] == action.action_id
        assert problem["action"]["inputSnapshotHash"] == action.input_snapshot_hash
        if not early:
            from core.web.services.team_workflow.research_runtime.command_service import _apply_ledger_reconcile_for_run
            def reconcile(uow):
                return _apply_ledger_reconcile_for_run(uow, run=uow.repository.get_run("parent"),
                    node_order=("optimization_knowledge",), now_ms=15)
            plan, revived, _ = store.submit(reconcile, force_flush=True).result(timeout=10)
            assert plan.landing_problem["code"] == "operator_knowledge_child_pending"
            assert revived == 0
            assert store.latest_attempt("parent", "optimization_knowledge").finished_at_ms is None
            # Recover precisely the historical zombie-finalization corruption.
            store.submit(lambda uow: uow.repository.update_attempt_status(action.node_run_id,
                "failed", 16, problem_json=parked.last_problem_json, finished_at_ms=16), force_flush=True).result()
            store.submit(reconcile, force_flush=True).result(timeout=10)
            restored = store.latest_attempt("parent", "optimization_knowledge")
            assert restored.status == "running" and restored.finished_at_ms is None
            store.submit(settle, force_flush=True).result(timeout=10)

        def invalidate(uow):
            if blocked == "cancelled":
                uow.repository.update_run_status(
                    "parent", "research-team", "cancelled", 21
                )
            elif blocked == "superseded":
                uow.repository.insert_attempt(
                    replace(attempt, node_run_id="new-parent-attempt", attempt=2)
                )
            elif blocked == "ordinary":
                uow.repository.execute(
                    "UPDATE workflow_runs SET workflow_id='challenge-cup' WHERE run_id='parent'"
                )

        store.submit(invalidate, force_flush=True).result(timeout=10)
        woke = store.submit(
            lambda uow: wake_knowledge_child(uow, "inv-1", 22), force_flush=True
        ).result(timeout=10)
        assert woke == (not blocked and not early)
        assert not store.submit(
            lambda uow: wake_knowledge_child(uow, "inv-1", 23), force_flush=True
        ).result(timeout=10)
        assert store.read(lambda repo: repo.get_outbox(action.action_id)).status == (
            "failed" if blocked else "pending"
        )
        assert (
            store.read(
                lambda repo: repo.execute(
                    "SELECT COUNT(*) FROM outbox_actions WHERE node_run_id=?",
                    (action.node_run_id,),
                ).fetchone()[0]
            )
            == 1
        )
    finally:
        harness.close()
