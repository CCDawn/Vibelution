from core.web.services import team_workflow_orchestration_service as s
from core.web.services.team_workflow.source_collection.source_repair_context import source_repair_message


def test_finding_receives_only_current_run_extraction_gaps(monkeypatch):
    calls = []
    task = {"taskId": "extraction-current", "stageId": "extraction", "createdAt": "2026-09-08T00:00:00Z"}

    def tasks(team, run):
        calls.append((team, run))
        return [task]

    monkeypatch.setattr(s, "_source_collection_stage_session_tasks", tasks)
    candidates = [
        {"candidateId": "gap", "title": "Unavailable paper", "sourceUrl": "https://example.org/paper",
         "metadata": {"contentExtraction": {"evidenceStatus": "missing_evidence_anchor"}}},
        {"candidateId": "ready", "title": "Already verified",
         "metadata": {"contentExtraction": {"evidenceStatus": "evidence_ready"}}},
    ]
    message = source_repair_message(team_id="team", run_id="current", candidates=candidates)
    assert calls == [("team", "current")]
    assert '"candidateId": "gap"' in message
    assert "extraction-current" in message
    assert "Already verified" not in message
    assert "web_fetch_tool" in message
    assert "不得将搜索摘要冒充原文" in message


def test_initial_finding_has_no_repair_instruction(monkeypatch):
    monkeypatch.setattr(s, "_source_collection_stage_session_tasks", lambda *_: [])
    assert source_repair_message(team_id="team", run_id="new", candidates=[]) == ""


def test_resolved_gaps_do_not_request_more_search(monkeypatch):
    monkeypatch.setattr(s, "_source_collection_stage_session_tasks", lambda *_: [
        {"taskId": "done", "stageId": "extraction"},
    ])
    assert source_repair_message(team_id="team", run_id="current", candidates=[
        {"candidateId": "ready", "metadata": {"contentExtraction": {"evidenceStatus": "evidence_ready"}}},
    ]) == ""


def test_extraction_retry_includes_new_replacement_source():
    from core.web.services.team_workflow.source_collection.stage_reconcile import (
        _source_collection_stage_evidence_retry_focus,
    )
    focus = _source_collection_stage_evidence_retry_focus(
        {"taskId": "previous-extraction"},
        [
            {"candidateId": "replacement", "metadata": {}},
            {"candidateId": "old-gap", "metadata": {"contentExtraction": {"evidenceStatus": "missing_evidence_anchor"}}},
            {"candidateId": "ready", "metadata": {"contentExtraction": {"evidenceStatus": "evidence_ready"}}},
        ],
    )
    assert focus["evidenceGapCandidateIds"] == ["replacement", "old-gap"]


def test_completed_finding_repair_starts_bounded_new_batch_ledger(tmp_path, monkeypatch):
    from tests._support.team_workflow.cases_source_collection import _finding_close_first_step_task
    from core.web.services.team_workflow.source_collection import stage_session
    env = _finding_close_first_step_task(tmp_path, monkeypatch)
    team_id, run_id = env["team"]["teamId"], env["runId"]
    previous = dict(env["task"]["task"])
    previous["status"] = "completed"
    previous["sourceCollectionWritebackBatches"] = [
        {"batchFingerprint": "old", "leadFingerprints": ["https://example.org/old"]},
    ]
    s._upsert_source_collection_stage_session_task(team_id, run_id, previous)
    monkeypatch.setattr(stage_session, "source_repair_message", lambda **_: "current extraction gaps")
    created = s.start_source_collection_stage_session_task(team_id, run_id, {
        "stageId": "finding", "agentId": previous["agentId"], "agentRole": "source_finder",
        "idempotencyKey": "replacement-finding-pass",
    })["task"]
    assert created["sourceRepairOfTaskId"] == previous["taskId"]
    assert created["sourceCollectionWritebackBatches"] == []
    assert created["writebackContract"]["searchEnvelope"] == previous["writebackContract"]["searchEnvelope"]
    assert "current extraction gaps" in env["submitted"][-1]["content"]
