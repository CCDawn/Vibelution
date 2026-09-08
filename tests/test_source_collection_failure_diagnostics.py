from types import SimpleNamespace

from core.web.services.team_workflow.source_collection import stage_reconcile, stage_session_replay
from tests.test_source_collection_stage_session_replay import _FakeService


def test_budget_problem_survives_journal_to_stage_task_and_fresh_retry(monkeypatch):
    service = _FakeService()
    monkeypatch.setattr(stage_reconcile, "_service", lambda: service)
    result = stage_reconcile._source_collection_stage_session_task_turn_journal_result(
        "session-1", "turn-1", events=[SimpleNamespace(
            turn_id="turn-1", event_type="turn_failed", status="failed_runtime",
            event_id="failed-1", timestamp="2026-09-08T00:00:00Z",
            payload={"problemCode": "context_budget_exhausted", "message": "Next call exceeds hard budget."},
        )],
    )
    service._source_collection_stage_session_task_turn_result = lambda *args, **kwargs: result
    service._source_collection_stage_task_status_from_turn_result = stage_reconcile._source_collection_stage_task_status_from_turn_result
    task = stage_reconcile._reconcile_source_collection_stage_session_task_from_turn_result({
        "status": "running", "sessionId": "session-1", "agentId": "agent-1",
        "turn": {"turnId": "turn-1"},
        "writeback": {"status": "needs_review", "candidateIds": ["accepted-source-1"]},
    })
    assert task["failureCode"] == "context_budget_exhausted"
    assert task["failureMessage"] == "Next call exceeds hard budget."
    assert task["writeback"]["candidateIds"] == ["accepted-source-1"]
    assert stage_session_replay._failed_on_context_budget_loop(task)
    assert stage_reconcile._reconcile_source_collection_stage_session_task_turn_status(task)["status"] == "failed"


def test_budget_problem_survives_completion_snapshot(monkeypatch):
    service = _FakeService()
    service.session_service.get_session_turn_completion_snapshot = lambda *args: {
        "terminal": True, "terminalStatus": "failed_runtime", "isRunning": False,
        "terminalProblemCode": "context_budget_exhausted", "completionSource": "turn_journal",
        "assistantText": "Budget exhausted.",
    }
    monkeypatch.setattr(stage_reconcile, "_service", lambda: service)
    result = stage_reconcile._source_collection_stage_session_task_completion_snapshot_result("session-1", "turn-1")
    assert result["failureCode"] == "context_budget_exhausted"
