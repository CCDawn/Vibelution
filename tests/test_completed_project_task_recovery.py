from __future__ import annotations

import json
from pathlib import Path

from core.research.workflow.contracts import WorkflowCommandKind
from core.web.services.team_workflow.research_runtime.completed_project_task_recovery import (
    find_completed_project_task_recovery,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS
from tests.test_research_workflow_agent_anchor import (
    _outbox_row,
    _project_agent_action,
    _seed,
)


def _lag_problem(task_id: str) -> dict[str, str]:
    return {
        "code": "adapter_execution_exception",
        "detail": json.dumps(
            {
                "code": "project_agent_task_not_reconciled",
                "taskId": task_id,
                "status": "running",
            }
        ),
    }


def _completed_task(*, action, task_id: str = "task-completed") -> dict[str, object]:
    return {
        "taskId": task_id,
        "status": "completed",
        "workflowRunId": action.run_id,
        "nodeRunId": action.node_run_id,
        "sessionId": "session-completed",
        "sessionAttempt": 1,
        "turn": {"turnId": "turn-completed"},
    }


def _seed_failed_project_task_recovery(
    harness: CommandHarness,
    *,
    task_id: str = "task-completed",
    voided_usage: bool = True,
) -> object:
    action = _project_agent_action()
    _seed(harness, action, action.node_id)
    problem = _lag_problem(task_id)

    def mutate(uow):
        uow.repository.update_attempt_status(
            action.node_run_id,
            "failed",
            FIXED_NOW_MS + 1,
            problem_json=json.dumps(problem),
            finished_at_ms=FIXED_NOW_MS + 1,
        )
        uow.repository.execute(
            "UPDATE outbox_actions SET status='failed', last_problem_json=?, "
            "updated_at_ms=? WHERE action_id=?",
            (
                json.dumps(problem),
                FIXED_NOW_MS + 1,
                f"adapter-outbox-{action.action_id}",
            ),
        )
        uow.repository.insert_anchor(
            anchor_id="anchor-project-task",
            node_run_id=action.node_run_id,
            actor_kind="agent",
            anchor_json=json.dumps({"status": "failed"}),
            created_at_ms=FIXED_NOW_MS,
            agent_id="agent-problem",
            role_key="problem_understanding",
            session_id="session-completed",
            session_attempt=1,
            task_id=task_id,
            turn_id="turn-completed",
            status="failed",
        )
        uow.repository.insert_budget_receipt(
            receipt_id="budget-project-task",
            run_id=action.run_id,
            node_run_id=action.node_run_id,
            reservation_id=f"reservation-{action.node_run_id}",
            stage_id="knowledge_collection",
            policy_hash="p-1",
            reserved_json=json.dumps(
                {"reserved": {"estimatedTokens": 100}, "limits": {"tokens": 1000}}
            ),
            created_at_ms=FIXED_NOW_MS,
        )
        if voided_usage:
            uow.repository.update_budget_receipt(
                "budget-project-task",
                status="voided",
                now_ms=FIXED_NOW_MS + 1,
                settled_json=json.dumps(
                    {
                        "usage": {"tokens": 17},
                        "invocations": {"call-1": {"tokens": 17}},
                    }
                ),
            )
        uow.repository.update_run_status(
            action.run_id,
            "research-team",
            "blocked",
            FIXED_NOW_MS + 1,
            active_node_id=action.node_id,
            blocked_problem_json=json.dumps(problem),
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)
    return action


def _task_status_patch(monkeypatch, task: dict[str, object]) -> None:
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks.get_research_project_agent_task_status",
        lambda _team_id, _project_id: {"tasks": [task]},
    )


def test_reconcile_run_recovers_completed_project_task_without_new_execution(
    tmp_path: Path, monkeypatch
) -> None:
    """The historical wrapper resumes the original task/turn and usage only."""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(status="running")
        action = _seed_failed_project_task_recovery(harness)
        _task_status_patch(monkeypatch, _completed_task(action=action))

        receipt = harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.RECONCILE_RUN,
                node_id=None,
                expected_run_version=1,
                idempotency_key="ui:recover-completed-project-task",
            )
        )

        assert receipt.status == "accepted"
        attempt = harness.store.latest_attempt(action.run_id, action.node_id)
        assert attempt is not None and attempt.status == "dispatching"
        outbox = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert outbox is not None and outbox.status == "pending"
        cursor = json.loads(outbox.last_problem_json or "{}")
        assert cursor["completionResume"]["actionId"] == action.action_id
        assert cursor["completionResume"]["handle"]["task_id"] == "task-completed"
        assert harness.store.get_run(action.run_id).status == "running"
        assert harness.wake_count == 1
        budget = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status, settled_json FROM budget_receipts WHERE receipt_id = ?",
                ("budget-project-task",),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert budget[0] == "settled"
        assert json.loads(budget[1])["usage"]["tokens"] == 17
        events = harness.store.list_events(action.run_id)
        recovery_events = [
            event
            for event in events
            if event.event_type == "completed_project_task_recovered"
        ]
        assert len(recovery_events) == 1
        assert json.loads(recovery_events[0].payload_json)["reusedExecution"] is True
    finally:
        harness.close()


def test_reconcile_recovery_requires_exact_completed_task_identity(
    tmp_path: Path, monkeypatch
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(status="running")
        action = _seed_failed_project_task_recovery(harness)
        mismatched = _completed_task(action=action)
        mismatched["nodeRunId"] = "nr-other"
        _task_status_patch(monkeypatch, mismatched)

        assert find_completed_project_task_recovery(
            harness.store,
            run=harness.store.get_run(action.run_id),
        ) is None
        before = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert before is not None and before.status == "failed"
    finally:
        harness.close()


def test_recovery_cursor_reuses_task_and_budget_in_the_normal_adapter_path(
    tmp_path: Path, monkeypatch
) -> None:
    from core.web.services.team_workflow.research_runtime.action_registry import (
        ActionRegistry,
    )
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        AdapterDispatchWorker,
    )
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
        AgentActionAdapter,
    )
    from tests._support.adapter_fakes import FakeDomainPorts

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(status="running")
        action = _seed_failed_project_task_recovery(harness)
        _task_status_patch(monkeypatch, _completed_task(action=action))
        harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.RECONCILE_RUN,
                node_id=None,
                expected_run_version=1,
                idempotency_key="ui:recover-and-dispatch",
            )
        )

        ports = FakeDomainPorts()
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda _node_id: (),
            now_provider=lambda: FIXED_NOW_MS + 2_000,
        )
        worker.run_once()

        attempt = harness.store.latest_attempt(action.run_id, action.node_id)
        assert attempt is not None and attempt.status == "succeeded"
        assert _outbox_row(harness, f"adapter-outbox-{action.action_id}").status == "succeeded"
        assert "create_agent_task" not in ports.calls
        assert "reserve_budget" not in ports.calls
        budget = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status, settled_json FROM budget_receipts WHERE receipt_id = ?",
                ("budget-project-task",),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert budget[0] == "settled"
        assert json.loads(budget[1])["usage"]["tokens"] == 17
    finally:
        harness.close()
