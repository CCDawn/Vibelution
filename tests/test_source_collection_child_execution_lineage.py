"""A finding child consumes parent evidence without executing as its parent."""

import pytest

from core.web.services import session_service
from core.web.services.team_workflow.source_collection import stage_session
from tests.test_finding_attempt_query_memory import _finding_task_setup


@pytest.mark.parametrize("wrong_contract", [False, True])
def test_finding_child_task_and_turn_keep_execution_scope(tmp_path, monkeypatch, wrong_contract):
    team, run, agent, start_payload = _finding_task_setup(tmp_path, monkeypatch)
    start_payload["idempotencyKey"] = "child-execution-lineage"
    execution_id = run["scope"]["workflowRunId"]
    context = stage_session._source_collection_problem_understanding_context(
        team["teamId"], run["runId"], run,
    )
    parent_context = {**context, "workflowRunId": "parent-evidence-run"}
    monkeypatch.setattr(stage_session, "_source_collection_problem_understanding_context", lambda *args: parent_context)
    service = stage_session._service()
    monkeypatch.setattr(service, "bind_challenge_research_task_model", lambda **kwargs: {
        "workflowRunId": "wrong-execution" if wrong_contract else execution_id,
    })
    submitted = []

    def submit(session_id, content, **kwargs):
        submitted.append(kwargs["message_metadata"])
        return {"accepted": True, "sessionId": session_id, "turnId": "turn-child", "status": "running"}

    monkeypatch.setattr(session_service, "submit_session_message", submit)
    if wrong_contract:
        with pytest.raises(service.TeamWorkflowOrchestrationError, match="workflowRunId does not match"):
            stage_session.start_source_collection_stage_session_task(team["teamId"], run["runId"], start_payload)
        assert submitted == []
        return
    result = stage_session.start_source_collection_stage_session_task(team["teamId"], run["runId"], start_payload)
    assert result["workflowRunId"] == execution_id
    assert result["task"]["workflowRunId"] == execution_id
    assert submitted[0]["workflowRunId"] == execution_id
    assert submitted[0]["problemUnderstandingContext"] == parent_context
    assert result["task"]["problemUnderstandingContext"] == parent_context
    replay = stage_session.start_source_collection_stage_session_task(team["teamId"], run["runId"], start_payload)
    assert replay["alreadyPresent"]
    assert replay["workflowRunId"] == execution_id
    assert len(submitted) == 1
