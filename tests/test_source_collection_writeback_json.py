import json

import pytest

from tools import source_collection_stage_tools as stage_tools
from core.web.services import team_workflow_orchestration_service as workflow


@pytest.fixture
def writes(monkeypatch):
    calls = []
    monkeypatch.setattr(stage_tools, "_resolve_source_collection_team_id", lambda **_: ("team", {}))
    monkeypatch.setattr(stage_tools, "_record_stage_tool_event", lambda *_a, **_kw: None)
    monkeypatch.setattr(workflow, "writeback_source_collection_stage_session_task",
                        lambda team, task, payload: calls.append(payload) or {})
    return calls


def test_malformed_outer_result_is_not_replaced_by_valid_nested_object(writes):
    raw = '{"edges":[{"sourceCandidateId":"a"}],"claim":"invalid "quote""}'
    result = json.loads(stage_tools.source_collection_stage_writeback_tool(
        team_id="team", task_id="task", result_json=raw,
    ))
    assert writes == []
    assert result["status"] == "error"
    assert "result_json" in result["message"]
    assert "line 1" in result["message"]


@pytest.mark.parametrize("raw", ['[]', '"text"', '```json\n{"edges": []}\n```'])
def test_non_object_or_wrapped_result_is_rejected_without_writeback(writes, raw):
    result = json.loads(stage_tools.source_collection_stage_writeback_tool(
        team_id="team", task_id="task", result_json=raw,
    ))
    assert writes == []
    assert result["status"] == "error"
    assert "result_json" in result["message"]


def test_valid_result_preserves_all_fields(writes):
    payload = {"edges": [{"evidenceRefs": ["claim-1"]}],
               "counterEvidenceRefs": [{"evidenceRef": "claim-2", "claim": "Method limitation"}]}
    stage_tools.source_collection_stage_writeback_tool(
        team_id="team", task_id="task", result_json=json.dumps(payload),
    )
    assert writes[0]["result"] == payload
