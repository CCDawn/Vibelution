from __future__ import annotations

from types import SimpleNamespace

from core.web.services import data_processing_service, team_service
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain,
    hypothesis_first_state_v2,
)
from core.web.services.team_workflow.source_collection import residual


def test_data_processing_cancel_is_terminal_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(data_processing_service, "PROJECT_ROOT", tmp_path)
    run = data_processing_service.create_processing_run(
        scope={"teamId": "team-1"},
    )
    data_processing_service.create_collection_assignment(
        run["runId"],
        {"agentRole": "source_finder", "instructions": "collect"},
    )

    first = data_processing_service.cancel_processing_run(run["runId"])
    second = data_processing_service.cancel_processing_run(run["runId"])

    assert first["status"] == "cancelled"
    assert second["status"] == "cancelled"
    assert data_processing_service.get_processing_run(run["runId"])["status"] == "cancelled"

    # A worker that loaded the run before cancellation can still report late
    # output. That must not reopen the terminal run.
    data_processing_service.record_collection_output(
        run["runId"],
        data_processing_service.list_collection_assignments(run["runId"])[
            "assignments"
        ][0]["assignmentId"],
        {"status": "completed", "records": []},
    )
    assert data_processing_service.get_processing_run(run["runId"])["status"] == "cancelled"


def test_cancelled_search_result_projects_terminal_cancelled(monkeypatch):
    service = SimpleNamespace(
        _source_collection_work_run_terminal_status=(
            residual._source_collection_work_run_terminal_status
        )
    )
    monkeypatch.setattr(residual, "_service", lambda: service)

    assert residual._source_collection_work_run_terminal_status(
        {"status": "cancelled"}
    ) == "cancelled"
    assert residual._source_collection_work_run_terminal_phase(
        {"status": "cancelled"}
    ) == "cancelled"


def test_stop_collection_request_releases_reset_guard(tmp_path, monkeypatch):
    from core.web.services.team_workflow.source_collection import runs

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hypothesis_first_chain, "PROJECT_ROOT", tmp_path)
    hypothesis_first_chain._append_jsonl(
        hypothesis_first_chain._storage_path("team-1"),
        {
            "schemaVersion": 1,
            "recordKind": hypothesis_first_chain.COLLECTION_REQUEST_KIND,
            "requestId": "request-stuck",
            "questionId": "SCI-001",
            "status": "pending",
            "collectionRunId": "run-stuck",
            "collectionRunStatus": "running",
        },
    )
    monkeypatch.setattr(
        runs,
        "stop_source_collection_search",
        lambda *_args, **_kwargs: {"status": "cancelled", "runId": "run-stuck"},
    )

    result = hypothesis_first_chain.stop_collection_request(
        "team-1", "request-stuck"
    )
    snapshot = hypothesis_first_chain._question_reset_snapshot(
        "team-1", "SCI-001"
    )

    assert result["request"]["status"] == "failed"
    assert result["request"]["collectionRunStatus"] == "cancelled"
    assert snapshot["activeRequestIds"] == []


def test_source_collection_stop_cancels_run_and_clears_active_snapshot(monkeypatch):
    from core.web.services.team_workflow.source_collection import runs

    calls: list[tuple[str, object]] = []
    processing = SimpleNamespace(
        DataProcessingError=ValueError,
        get_processing_run=lambda run_id: {
            "runId": run_id,
            "status": "collecting",
            "scope": {"teamId": "team-1"},
        },
        cancel_processing_run=lambda run_id, reason: calls.append(("cancel", run_id))
        or {"runId": run_id, "status": "cancelled"},
        list_collection_assignments=lambda _run_id: {"assignments": []},
        list_records=lambda _run_id: {"records": []},
    )
    service = SimpleNamespace(
        SCHEMA_VERSION=1,
        data_processing_service=processing,
        team_service=SimpleNamespace(get_team=lambda team_id: {"teamId": team_id}),
        _normalize_required_id=lambda value, _message: value,
        _source_collection_run_belongs_to_team=lambda _run, _team_id: True,
        _persist_source_collection_work_run=lambda *_args, **kwargs: calls.append(
            ("persist-active", kwargs["active"])
        )
        or {"status": kwargs["status"]},
        _trim_text=lambda value, max_length=300: str(value or "")[:max_length],
        _source_collection_assignment_stage_summary=lambda _items: {},
        _sync_source_collection_stage_round_after_search=lambda *_args, **kwargs: calls.append(
            ("sync", kwargs["terminal_status"])
        ),
    )
    monkeypatch.setattr(runs, "_service", lambda: service)

    result = runs.stop_source_collection_search("team-1", "run-stuck")

    assert result["status"] == "cancelled"
    assert calls == [
        ("cancel", "run-stuck"),
        ("persist-active", False),
        ("sync", "cancelled"),
    ]


def test_v2_stop_collection_command_uses_owned_stop_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hypothesis_first_chain, "PROJECT_ROOT", tmp_path)
    snapshot = {
        "stateVersion": "hf2-action:collection-running",
        "allowedActions": [{
            "kind": "command",
            "actionId": "stop-collection:request-stuck",
            "command": "stop_collection",
            "payload": {
                "requestId": "request-stuck",
                "childRunId": "run-stuck",
            },
            "enabled": True,
            "idempotencyKey": "hf2:stop-collection:request-stuck",
        }],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        hypothesis_first_chain,
        "stop_collection_request",
        lambda team_id, request_id: calls.append((team_id, request_id))
        or {"status": "stopped"},
    )

    result = hypothesis_first_chain.execute_v2_command(
        "team-1",
        {
            "actionId": "stop-collection:request-stuck",
            "idempotencyKey": "hf2:stop-collection:request-stuck",
            "expectedStateVersion": "hf2-action:collection-running",
            "command": "stop_collection",
            "payload": {
                "requestId": "request-stuck",
                "childRunId": "run-stuck",
            },
        },
        question_id="SCI-001",
    )

    assert result["result"]["status"] == "stopped"
    assert calls == [("team-1", "request-stuck")]
