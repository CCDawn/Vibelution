"""ISS-064: corrupt transfer (交接) records stay skipped fail-soft, but the
coordination status surface must report the skip through the existing
workflow event channel instead of silently dropping the lines."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.services import team_workflow_orchestration_service
from core.web.services.team_workflow.knowledge_kernel import _load_transfer_records
from core.web.services.team_workflow.knowledge import decide_transfer_request
from core.web.routes.team_workflows.knowledge import router
from core.web.routes.team_workflows.research_ops import router as research_router


def _capture_workflow_event(monkeypatch) -> list[dict]:
    events: list[dict] = []

    def _capture(event_code, team_id, *, fields, **kwargs):
        events.append(
            {"eventCode": event_code, "teamId": team_id, "fields": fields, **kwargs}
        )

    monkeypatch.setattr(
        team_workflow_orchestration_service, "_record_workflow_event", _capture
    )
    return events


def test_corrupt_transfer_lines_are_skipped_with_observable_event(
    tmp_path, monkeypatch
) -> None:
    records_path = tmp_path / "transfer_records.jsonl"
    records_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "transferId": "tr-1",
                        "candidateId": "cand-1",
                        "status": "requested",
                    }
                ),
                "{corrupt line",
                "",
                json.dumps(
                    {
                        "transferId": "tr-2",
                        "candidateId": "cand-2",
                        "status": "approved",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_transfer_records_path",
        lambda team_id: records_path,
    )
    events = _capture_workflow_event(monkeypatch)

    records = _load_transfer_records("team-1")

    assert [record["transferId"] for record in records] == ["tr-1", "tr-2"]
    assert len(events) == 1
    event = events[0]
    assert event["eventCode"] == "workflow.transfer_records_corrupt_lines_skipped"
    assert event["teamId"] == "team-1"
    assert event["outcome"] == "degraded"
    assert event["level"] == "warning"
    assert event["fields"]["skippedLineCount"] == 1
    assert event["fields"]["skippedReasons"] == ["line 2: Expecting property name enclosed in double quotes"]


def test_clean_transfer_records_write_no_degraded_event(
    tmp_path, monkeypatch
) -> None:
    records_path = tmp_path / "transfer_records.jsonl"
    records_path.write_text(
        json.dumps({"transferId": "tr-ok", "status": "requested"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_transfer_records_path",
        lambda team_id: records_path,
    )
    events = _capture_workflow_event(monkeypatch)

    records = _load_transfer_records("team-1")

    assert [record["transferId"] for record in records] == ["tr-ok"]
    assert events == []


def test_invalid_utf8_skips_only_bad_line_and_reports_it(tmp_path, monkeypatch):
    records_path = tmp_path / "transfer_records.jsonl"
    original = b'{"transferId":"before"}\n\xff\n{bad json\n[]\n{"transferId":"after"}\n'
    records_path.write_bytes(original)
    monkeypatch.setattr(team_workflow_orchestration_service, "_transfer_records_path", lambda _: records_path)
    events = _capture_workflow_event(monkeypatch)

    records = _load_transfer_records("team-1")

    assert [record["transferId"] for record in records] == ["before", "after"]
    assert records_path.read_bytes() == original
    assert len(events) == 1
    assert events[0]["fields"]["skippedLineCount"] == 3
    assert events[0]["fields"]["skippedReasons"][0] == "line 2: invalid UTF-8"
    assert events[0]["fields"]["skippedReasons"][1].startswith("line 3:")
    assert events[0]["fields"]["skippedReasons"][2] == "line 4: expected JSON object"


def test_coordination_status_survives_invalid_utf8(tmp_path, monkeypatch):
    records_path = tmp_path / "transfer_records.jsonl"
    records_path.write_bytes(b'{"transferId":"good"}\n\xff\n')
    s = team_workflow_orchestration_service
    monkeypatch.setattr(s.team_service, "assert_team_exists", lambda *_: True)
    monkeypatch.setattr(s, "_load_or_create_workflow", lambda *_: {"workflowId": "wf", "workflowKind": "test", "routingPolicy": {}})
    monkeypatch.setattr(s, "_load_candidate_store", lambda *_: {"candidates": []})
    monkeypatch.setattr(s, "_transfer_records_path", lambda *_: records_path)
    monkeypatch.setattr(s, "_relative_path", lambda *_: "synthetic/records.jsonl")
    events = _capture_workflow_event(monkeypatch)
    app = FastAPI()
    app.include_router(router, prefix="/api")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/teams/synthetic-team/workflow-orchestration/coordination/status")

    assert response.status_code == 200
    assert any(event["eventCode"] == "workflow.transfer_records_corrupt_lines_skipped" for event in events)


@pytest.mark.parametrize(
    ("bad_line", "error"),
    [(b"\xff", "invalid UTF-8"), (b"{broken json", "invalid JSON"), (b"[]", "expected JSON object")],
)
def test_decision_refuses_to_overwrite_corrupt_records(tmp_path, monkeypatch, bad_line, error):
    records_path = tmp_path / "transfer_records.jsonl"
    original = b'{"transferId":"good","status":"requested"}\n' + bad_line + b"\n"
    records_path.write_bytes(original)
    s = team_workflow_orchestration_service
    monkeypatch.setattr(s.team_service, "get_team", lambda *_: {})
    monkeypatch.setattr(s, "_load_or_create_workflow", lambda *_: {"ownerAgentId": "owner"})
    monkeypatch.setattr(s, "_load_candidate_store", lambda *_: {"candidates": []})
    monkeypatch.setattr(s, "_transfer_records_path", lambda *_: records_path)
    writes = []
    monkeypatch.setattr(s, "_write_json", lambda *args: writes.append(args))

    with pytest.raises(s.TeamWorkflowOrchestrationError, match=f"{error} at line 2"):
        decide_transfer_request("team-1", "good", {"decision": "approved", "decidedByAgent": "owner"})

    app = FastAPI()
    app.include_router(research_router, prefix="/api")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/teams/team-1/workflow-orchestration/transfers/good/decide",
            json={"decision": "approved", "decidedByAgent": "owner"},
        )

    assert response.status_code == 422
    assert f"{error} at line 2" in response.text
    assert writes == []
    assert records_path.read_bytes() == original
