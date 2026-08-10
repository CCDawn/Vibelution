"""Failed Agent attempts settle real usage before a retry is scheduled."""

from __future__ import annotations

from pathlib import Path

from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime.budget_lifecycle import (
    reserve_node_budget,
)
from core.web.services.team_workflow.research_runtime.failed_agent_budget import (
    settle_failed_agent_task_budget,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowRuntimeService,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore

from .test_research_workflow_v21_node_retry_capability import _run_input


def test_failed_agent_usage_is_settled_exactly_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = WorkflowRunStore(tmp_path / "runs")
    service = ResearchWorkflowRuntimeService(
        run_store=store,
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    created = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(
            workflowDefaults={"source_finder": "agent-source-finder"}
        ),
        idempotency_key="create-failed-budget",
    )
    node_run = dict(created["nodeRuns"][0])
    reservation = reserve_node_budget(
        store,
        record=created,
        node_run=node_run,
        stage_id="knowledge_collection",
        request={"tokens": 100, "toolCalls": 3, "wallClockSeconds": 30},
        idempotency_key="reserve-failed-attempt",
    )
    record = store.get_run(created["runId"])
    assert record is not None
    node_run.update(
        {
            "status": "blocked",
            "taskId": "task-failed",
            "sessionId": "session-failed",
            "budgetLedgerRef": reservation["reservationId"],
            "failureCode": "quality_gate_failed",
        }
    )
    record = store.update_run(
        created["runId"],
        {
            "status": "blocked",
            "nodeRuns": [node_run],
        },
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.failed_agent_budget.load_external_agent_task",
        lambda *_args, **_kwargs: {
            "taskId": "task-failed",
            "sessionId": "session-failed",
            "status": "needs_review",
            "createdAt": "2026-08-10T00:00:00+00:00",
            "updatedAt": "2026-08-10T00:00:10+00:00",
            "turn": {"acceptedAt": "2026-08-10T08:00:01"},
            "taskToolProgress": {"toolCallCount": 2},
        },
    )
    monkeypatch.setattr(
        "core.web.services.session_service.get_session_detail",
        lambda *_args, **_kwargs: {
            "id": "session-failed",
            "updatedAt": "2026-08-10T00:00:10+00:00",
            "llmUsage": {"totalTokens": 90},
        },
    )

    settled = settle_failed_agent_task_budget(
        store,
        record=record,
        node_run=node_run,
    )
    replay = settle_failed_agent_task_budget(
        store,
        record=settled,
        node_run=node_run,
    )

    persisted = replay["budgetReservations"][0]
    ledger = replay["budgetLedgers"][0]
    assert persisted["status"] == "settled"
    assert persisted["actual"] == {
        "tokens": 90,
        "toolCalls": 2,
        "wallClockSeconds": 9,
    }
    assert ledger["reserved"]["tokens"] == 0
    assert ledger["consumed"]["tokens"] == 90
    assert len([event for event in replay["events"] if event["type"] == "BudgetSettled"]) == 1
