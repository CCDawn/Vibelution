"""D14A Challenge Cup DEV platform control tests.

Covers pure batch invariants, service invariants (team-scoped persistence,
clean-tree requirement, bounded runtime-scene evidence, ordered nextLegalAction),
HTTP contracts and error mapping. No real experiment, Qwen, network, CUDA/GPU,
DANDI or formal submission is ever invoked.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.research.competition.catalog_execution import (
    CatalogExecutionState,
    QuestionStatus,
)
from core.research.competition.dev_control_batch import (
    ALLOWED_DEV_BATCH_PLAN_IDS,
    MAX_DEV_BATCH_MAX_ITEMS,
    DevBatchError,
    new_dev_batch_state,
    project_dev_batch_checkpoint,
    project_dev_batch_outcomes,
    run_dev_fixture_batch,
    validate_dev_batch_max_items,
    validate_dev_batch_plan,
)
from core.research.competition.platform_flow_ready import REPORT_KIND
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
)
from core.infrastructure.no_console_git import no_console_subprocess_kwargs
from core.web import route_bootstrap
from core.web.routes.team_workflows import challenge_cup_dev_controls as dev_controls_routes
from core.web.services import team_service
from core.web.services.team_workflow import challenge_cup_dev_controls as dev_controls_service
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

DEV_CONTROLS_BASE = (
    "/api/teams/research-team/workflow-orchestration/challenge-program/dev-controls"
)
TEST_SOURCE_COMMIT = "a" * 40


@pytest.fixture(autouse=True)
def _isolated_frontend_dist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep API contracts reproducible without an ignored local web build."""

    web_dist = tmp_path / "web-dist"
    web_dist.mkdir()
    (web_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(route_bootstrap, "_web_dist", lambda: web_dist)


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _ready_report(**overrides) -> dict:
    report = {
        "schemaVersion": 1,
        "reportKind": REPORT_KIND,
        "status": "READY",
        "programContract": {
            "version": dev_controls_service.PROGRAM_CONTRACT_VERSION,
            "coreBehaviorHash": dev_controls_service.CORE_BEHAVIOR_HASH,
        },
        "catalogPolicy": {
            "version": dev_controls_service.CATALOG_POLICY_VERSION,
            "corePolicyHash": dev_controls_service.CORE_POLICY_HASH,
        },
        "mode": "dev",
        "researchAuthorizationRequired": True,
        "realCampaignAllowed": False,
        "gates": [
            {"gateId": gate_id, "status": "PASS", "detail": f"{gate_id} fixture PASS"}
            for gate_id in dev_controls_service.REQUIRED_READINESS_GATES
        ],
        "nextLegalAction": "RESEARCH_AUTHORIZATION_REQUIRED",
        "sourceCommit": TEST_SOURCE_COMMIT,
        "generatedAt": dev_controls_service._utc_now(),
    }
    report.update(overrides)
    return report


def _ready_team(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    team_id: str = "team-1",
) -> None:
    monkeypatch.setattr(
        dev_controls_service,
        "build_platform_flow_readiness_report",
        lambda repo, *, clone_dest=None, require_clean=True, run_pytest=True, mode="dev": _ready_report(),
    )
    dev_controls_service.run_challenge_cup_dev_readiness(team_id)


# ---------------------------------------------------------------------------
# Pure batch contract layer
# ---------------------------------------------------------------------------


def test_dev_batch_plan_validation_allows_only_dev_1_and_dev_5() -> None:
    assert validate_dev_batch_plan("dev-1") == "dev-1"
    assert validate_dev_batch_plan("dev-5") == "dev-5"
    assert ALLOWED_DEV_BATCH_PLAN_IDS == ("dev-1", "dev-5")
    for forbidden in ("dev-12", "dev-125"):
        with pytest.raises(DevBatchError, match="not authorized"):
            validate_dev_batch_plan(forbidden)
    with pytest.raises(DevBatchError, match="Unknown DEV batch plan"):
        validate_dev_batch_plan("dev-0")
    with pytest.raises(DevBatchError, match="Unknown DEV batch plan"):
        validate_dev_batch_plan("formal")


def test_dev_batch_max_items_is_bounded() -> None:
    assert validate_dev_batch_max_items(None) is None
    assert validate_dev_batch_max_items(0) == 0
    assert validate_dev_batch_max_items(MAX_DEV_BATCH_MAX_ITEMS) == MAX_DEV_BATCH_MAX_ITEMS
    with pytest.raises(DevBatchError, match="maxItems must be between"):
        validate_dev_batch_max_items(MAX_DEV_BATCH_MAX_ITEMS + 1)
    with pytest.raises(DevBatchError, match="maxItems must be between"):
        validate_dev_batch_max_items(-1)
    with pytest.raises(DevBatchError, match="maxItems must be an integer"):
        validate_dev_batch_max_items("nope")


def test_dev_1_fixture_batch_completes_and_is_not_submission_eligible() -> None:
    state = new_dev_batch_state("dev-1")
    result = run_dev_fixture_batch(state)
    assert result["summary"]["succeeded"] == 1
    assert state.pending_question_ids() == ()
    success = state.result_for(state.plan.question_ids[0])
    assert success is not None
    assert success.submission_eligible is False
    assert success.status == "dev_fixture"
    restored = CatalogExecutionState.from_checkpoint(state.to_checkpoint())
    assert restored.outcome_summary()["succeeded"] == 1


def test_dev_5_interruption_and_resume_never_reruns_succeeded_items() -> None:
    state = new_dev_batch_state("dev-5")
    first = run_dev_fixture_batch(state, max_items=2, on_item=lambda _item: None)
    assert len(first["attempted"]) == 2
    assert state.outcome_summary()["succeeded"] == 2
    assert len(state.pending_question_ids()) == 3

    checkpoint = state.to_checkpoint()
    restored = CatalogExecutionState.from_checkpoint(checkpoint)
    assert [record.question_id for record in _records(restored) if record.status is QuestionStatus.SUCCEEDED] == list(first["attempted"])
    resumed = run_dev_fixture_batch(restored)
    assert len(resumed["attempted"]) == 3
    assert restored.outcome_summary()["succeeded"] == 5
    assert restored.outcome_summary()["total_attempts"] == 5
    assert restored.pending_question_ids() == ()
    assert restored.outcome_summary()["failed"] == 0


def _records(state: CatalogExecutionState) -> list:
    return [record for record in state._records.values()]  # noqa: SLF001 - test only


def test_batch_checkpoint_projection_is_explicit() -> None:
    state = new_dev_batch_state("dev-5")
    run_dev_fixture_batch(state, max_items=2)
    projection = project_dev_batch_checkpoint(
        state.to_checkpoint(), updated_at="2026-08-18T00:00:00Z"
    )
    assert projection["planId"] == "dev-5"
    assert projection["gateId"] == "G5"
    assert projection["questionCount"] == 5
    assert projection["succeededCount"] == 2
    assert projection["pendingCount"] == 3
    assert projection["canResume"] is True
    assert len(projection["completedQuestionIds"]) == 2
    assert projection["statusSummary"]["succeeded"] == 2


def test_outcomes_project_to_camel_case_wire_shape() -> None:
    projected = project_dev_batch_outcomes(
        [{"question_id": "SCI-091", "outcome": "succeeded"}]
    )
    assert projected == [{"questionId": "SCI-091", "outcome": "succeeded"}]


# ---------------------------------------------------------------------------
# Service invariants (team-scoped persistence)
# ---------------------------------------------------------------------------


@pytest.fixture()
def controls_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "teams"
    monkeypatch.setattr(
        dev_controls_service,
        "_current_source_commit",
        lambda: TEST_SOURCE_COMMIT,
    )
    monkeypatch.setattr(
        dev_controls_service,
        "_current_tree_is_clean",
        lambda: True,
    )
    monkeypatch.setattr(
        dev_controls_service,
        "team_workspace_root",
        lambda team_id: root / team_id,
    )
    monkeypatch.setattr(
        dev_controls_service.team_service, "get_team", lambda team_id: {"teamId": team_id}
    )
    return root


def test_snapshot_starts_unrun_without_inventing_lifecycle(controls_root: Path) -> None:
    snapshot = dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")
    assert snapshot["schemaVersion"] == 1
    assert snapshot["teamId"] == "team-1"
    assert snapshot["mode"] == "dev"
    assert snapshot["realCampaignAllowed"] is False
    assert snapshot["nextLegalAction"] == "run_dev_readiness"
    assert snapshot["report"] is None
    assert snapshot["batches"] == {}
    assert snapshot["boundary"]["authorizedPlans"] == ["dev-1", "dev-5"]
    assert "dev-12" in snapshot["boundary"]["forbiddenPlans"]
    assert "dev-125" in snapshot["boundary"]["forbiddenPlans"]


def test_snapshot_rejects_missing_team(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(team_id: str) -> dict:
        raise team_service.TeamNotFoundError("Team not found.")

    monkeypatch.setattr(dev_controls_service.team_service, "get_team", missing)
    with pytest.raises(team_service.TeamNotFoundError):
        dev_controls_service.get_challenge_cup_dev_control_snapshot("missing-team")


def test_readiness_run_requires_clean_tree_and_persists_report(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    def fake_build(repo, *, clone_dest, require_clean, run_pytest, mode):
        calls.append(
            {
                "repo": str(repo),
                "cloneDest": str(clone_dest),
                "requireClean": require_clean,
                "runPytest": run_pytest,
                "mode": mode,
            }
        )
        return _ready_report()

    monkeypatch.setattr(
        dev_controls_service, "build_platform_flow_readiness_report", fake_build
    )
    response = dev_controls_service.run_challenge_cup_dev_readiness("team-1")
    assert response["cleanedUp"] is True
    assert calls[0]["mode"] == "dev"
    assert calls[0]["runPytest"] is True
    assert calls[0]["requireClean"] is True
    assert "clone" in calls[0]["cloneDest"]

    report_file = controls_root / "team-1" / "challenge_cup_dev_controls" / "readiness_report.json"
    assert report_file.is_file()
    envelope = json.loads(report_file.read_text(encoding="utf-8"))
    assert envelope["realCampaignAllowed"] is False
    assert envelope["report"]["status"] == "READY"

    snapshot = dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")
    assert snapshot["report"] is not None
    assert snapshot["report"]["status"] == "READY"
    assert snapshot["report"]["realCampaignAllowed"] is False
    assert snapshot["nextLegalAction"] == "run_dev_1_fixture_batch"


def test_readiness_rejects_non_dev_mode_before_any_build(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_build(**kwargs):
        raise AssertionError("must not build for a non-dev mode")

    monkeypatch.setattr(dev_controls_service, "build_platform_flow_readiness_report", fail_build)
    with pytest.raises(dev_controls_service.ChallengeCupDevControlsError, match="DEV-only"):
        dev_controls_service.run_challenge_cup_dev_readiness("team-1", mode="formal")


def test_dev_1_batch_persists_checkpoint_team_scoped(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready_team(controls_root, monkeypatch)
    response = dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-1", None)
    assert response["planId"] == "dev-1"
    assert response["gateId"] == "G1"
    assert response["checkpoint"]["succeededCount"] == 1
    assert response["persisted"] is True
    assert response["outcomes"] == [{"questionId": "SCI-091", "outcome": "succeeded"}]

    batch_file = controls_root / "team-1" / "challenge_cup_dev_controls" / "batches" / "dev-1.json"
    assert batch_file.is_file()
    snapshot = dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")
    assert snapshot["batches"]["dev-1"]["succeededCount"] == 1
    assert snapshot["batches"]["dev-1"]["pendingCount"] == 0
    assert snapshot["batches"]["dev-1"]["canResume"] is False


def test_next_legal_action_advances_only_after_persisted_state(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_build(repo, *, clone_dest, require_clean, run_pytest, mode):
        return _ready_report()

    monkeypatch.setattr(
        dev_controls_service, "build_platform_flow_readiness_report", fake_build
    )

    def action() -> str:
        return dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")[
            "nextLegalAction"
        ]

    assert action() == "run_dev_readiness"

    dev_controls_service.run_challenge_cup_dev_readiness("team-1")
    assert action() == "run_dev_1_fixture_batch"

    dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-1", None)
    assert action() == "run_dev_5_fixture_batch"

    dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-5", 2)
    assert action() == "resume_dev_5_fixture_batch"

    dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-5", None)
    assert action() == "RESEARCH_AUTHORIZATION_REQUIRED"


def _persist_readiness_report(controls_root: Path, team_id: str) -> None:
    path = controls_root / team_id / "challenge_cup_dev_controls" / "readiness_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "report": _ready_report(),
                "realCampaignAllowed": False,
                "updatedAt": "2026-08-18T00:00:00Z",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _test_readiness_evidence(controls_root: Path, team_id: str) -> dict:
    report_path = (
        controls_root / team_id / "challenge_cup_dev_controls" / "readiness_report.json"
    )
    envelope = json.loads(report_path.read_text(encoding="utf-8"))
    report = envelope["report"]
    return {
        "reportUpdatedAt": envelope["updatedAt"],
        "sourceCommit": report["sourceCommit"],
        "programContract": report["programContract"],
        "catalogPolicy": report["catalogPolicy"],
    }


def _persist_batch_checkpoint(
    controls_root: Path,
    team_id: str,
    plan_id: str,
    checkpoint: dict,
) -> None:
    path = controls_root / team_id / "challenge_cup_dev_controls" / "batches" / f"{plan_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    updated_at = dev_controls_service._utc_now()
    upstream_updated_at = ""
    if plan_id == "dev-5":
        dev_1_path = path.parent / "dev-1.json"
        if dev_1_path.is_file():
            upstream_updated_at = str(
                json.loads(dev_1_path.read_text(encoding="utf-8")).get("updatedAt") or ""
            )
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "planId": plan_id,
                "updatedAt": updated_at,
                "readinessEvidence": _test_readiness_evidence(controls_root, team_id),
                "upstreamCheckpointUpdatedAt": upstream_updated_at,
                "checkpoint": checkpoint,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def test_failed_dev_1_returns_repair_and_does_not_advance_to_dev_5(
    controls_root: Path,
) -> None:
    _persist_readiness_report(controls_root, "team-1")
    state = new_dev_batch_state("dev-1")
    run_dev_fixture_batch(state)
    state.record_failure(state.plan.question_ids[0], "fixture rejected")
    _persist_batch_checkpoint(controls_root, "team-1", "dev-1", state.to_checkpoint())

    snapshot = dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")
    assert snapshot["batches"]["dev-1"]["failedCount"] == 1
    assert snapshot["nextLegalAction"] == "repair_dev_1_fixture_batch"


def test_blocked_dev_1_returns_repair_and_does_not_advance_to_dev_5(
    controls_root: Path,
) -> None:
    _persist_readiness_report(controls_root, "team-1")
    state = new_dev_batch_state("dev-1")
    run_dev_fixture_batch(state)
    state.record_blocked(state.plan.question_ids[0], "fixture blocked")
    _persist_batch_checkpoint(controls_root, "team-1", "dev-1", state.to_checkpoint())

    snapshot = dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")
    assert snapshot["batches"]["dev-1"]["blockedCount"] == 1
    assert snapshot["nextLegalAction"] == "repair_dev_1_fixture_batch"


def test_failed_dev_5_returns_repair_and_does_not_advance_to_authorization(
    controls_root: Path,
) -> None:
    _persist_readiness_report(controls_root, "team-1")
    dev_1 = new_dev_batch_state("dev-1")
    run_dev_fixture_batch(dev_1)
    _persist_batch_checkpoint(controls_root, "team-1", "dev-1", dev_1.to_checkpoint())

    dev_5 = new_dev_batch_state("dev-5")
    run_dev_fixture_batch(dev_5, max_items=2)
    dev_5.record_failure(dev_5.plan.question_ids[0], "fixture rejected")
    _persist_batch_checkpoint(controls_root, "team-1", "dev-5", dev_5.to_checkpoint())

    snapshot = dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")
    assert snapshot["batches"]["dev-1"]["failedCount"] == 0
    assert snapshot["batches"]["dev-5"]["failedCount"] == 1
    assert snapshot["nextLegalAction"] == "repair_dev_5_fixture_batch"


def test_blocked_dev_5_returns_repair_and_does_not_advance_to_authorization(
    controls_root: Path,
) -> None:
    _persist_readiness_report(controls_root, "team-1")
    dev_1 = new_dev_batch_state("dev-1")
    run_dev_fixture_batch(dev_1)
    _persist_batch_checkpoint(controls_root, "team-1", "dev-1", dev_1.to_checkpoint())

    dev_5 = new_dev_batch_state("dev-5")
    run_dev_fixture_batch(dev_5, max_items=2)
    dev_5.record_blocked(dev_5.plan.question_ids[0], "fixture blocked")
    _persist_batch_checkpoint(controls_root, "team-1", "dev-5", dev_5.to_checkpoint())

    snapshot = dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")
    assert snapshot["batches"]["dev-5"]["blockedCount"] == 1
    assert snapshot["nextLegalAction"] == "repair_dev_5_fixture_batch"


def test_dev_5_pause_then_resume_persists_and_never_reruns(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready_team(controls_root, monkeypatch)
    dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-1", None)
    paused = dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-5", 2)
    assert paused["checkpoint"]["succeededCount"] == 2
    assert paused["checkpoint"]["pendingCount"] == 3
    assert paused["checkpoint"]["canResume"] is True

    resumed = dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-5", None)
    assert resumed["attempted"] == paused["checkpoint"]["pendingQuestionIds"]
    checkpoint = resumed["checkpoint"]
    assert checkpoint["succeededCount"] == 5
    assert checkpoint["pendingCount"] == 0
    assert checkpoint["canResume"] is False
    assert checkpoint["totalAttempts"] == 5


def test_forbidden_batch_plans_fail_closed(controls_root: Path) -> None:
    for plan_id in ("dev-12", "dev-125"):
        with pytest.raises(DevBatchError, match="not authorized"):
            dev_controls_service.run_challenge_cup_dev_batch("team-1", plan_id, None)


def test_service_records_bounded_runtime_scene_transitions(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[dict] = []

    def fake_record(component, phase, event_code, **kwargs):
        events.append({"component": component, "phase": phase, "event_code": event_code, **kwargs})

    monkeypatch.setattr(dev_controls_service, "record_runtime_scene_event", fake_record)
    _ready_team(controls_root, monkeypatch)
    dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-1", None)

    codes = [
        item["event_code"] for item in events if "batch" in item["event_code"]
    ]
    assert codes == [
        "challenge_cup_dev_controls.batch.started",
        "challenge_cup_dev_controls.batch.succeeded",
    ]
    for item in events:
        assert item["component"] == "team_workflow_orchestration"
        fields = item.get("fields") or {}
        assert "teamId" in fields
        assert "checkpoint" not in fields
        assert "outcomes" not in fields


def test_service_records_rejection_and_failure_scene_events(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def fake_record(component, phase, event_code, **kwargs):
        events.append(event_code)

    monkeypatch.setattr(dev_controls_service, "record_runtime_scene_event", fake_record)
    with pytest.raises(DevBatchError, match="not authorized"):
        dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-12", None)
    assert "challenge_cup_dev_controls.batch.rejected" in events

    _ready_team(controls_root, monkeypatch)

    def fail_run(state, *, max_items=None, on_item=None):
        raise RuntimeError("fixture boom")

    monkeypatch.setattr(dev_controls_service, "run_dev_fixture_batch", fail_run)
    with pytest.raises(RuntimeError, match="fixture boom"):
        dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-1", None)
    assert "challenge_cup_dev_controls.batch.failed" in events


# ---------------------------------------------------------------------------
# HTTP contracts and error mapping
# ---------------------------------------------------------------------------


def _snapshot_payload() -> dict:
    return {
        "schemaVersion": 1,
        "teamId": "research-team",
        "generatedAt": "2026-08-18T00:00:00Z",
        "mode": "dev",
        "realCampaignAllowed": False,
        "nextLegalAction": "run_dev_readiness",
        "report": None,
        "batches": {},
        "boundary": {
            "mode": "dev",
            "realCampaignAllowed": False,
            "authorizedPlans": ["dev-1", "dev-5"],
            "forbiddenPlans": ["dev-12", "dev-125"],
            "forbiddenFeatures": ["real_qwen_invocation"],
            "fixtureOnly": True,
        },
    }


def test_get_dev_control_snapshot_http_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dev_controls_routes, "get_challenge_cup_dev_control_snapshot", lambda team_id: _snapshot_payload()
    )
    response = _client().get(f"{DEV_CONTROLS_BASE}")
    assert response.status_code == 200
    body = response.json()
    assert body["teamId"] == "research-team"
    assert body["mode"] == "dev"
    assert body["realCampaignAllowed"] is False
    assert body["boundary"]["authorizedPlans"] == ["dev-1", "dev-5"]
    assert body["boundary"]["fixtureOnly"] is True


def test_catalog_overview_lists_all_questions_when_unrun(controls_root: Path) -> None:
    overview = dev_controls_service.get_challenge_cup_catalog_overview("team-1")
    assert overview["schemaVersion"] == 1
    assert overview["teamId"] == "team-1"
    assert overview["questionCount"] == 125
    assert overview["counts"] == {"queued": 125, "running": 0, "succeeded": 0, "failed": 0}
    assert overview["questions"][0]["questionId"] == "SCI-001"
    assert overview["questions"][-1]["questionId"] == "SCI-125"
    assert all(row["status"] == "queued" for row in overview["questions"])
    assert all(row["action"] == "view" for row in overview["questions"])
    assert all(row["blocker"] is None for row in overview["questions"])
    assert overview["questions"][0]["title"]


def test_catalog_overview_projects_failed_dev_1_row(controls_root: Path) -> None:
    _persist_readiness_report(controls_root, "team-1")
    state = new_dev_batch_state("dev-1")
    failed_id = state.plan.question_ids[0]
    state.mark_running(failed_id)
    state.record_failure(failed_id, "fixture rejected")
    _persist_batch_checkpoint(controls_root, "team-1", "dev-1", state.to_checkpoint())

    overview = dev_controls_service.get_challenge_cup_catalog_overview("team-1")
    failed_row = next(row for row in overview["questions"] if row["questionId"] == failed_id)
    assert failed_row["status"] == "failed"
    assert failed_row["action"] == "retry"
    assert failed_row["planId"] == "dev-1"
    assert failed_row["blocker"]["code"] == "question_failed"
    assert failed_row["blocker"]["message"] == "fixture rejected"
    assert failed_row["blocker"]["remediationLabel"]
    assert overview["counts"]["failed"] == 1
    assert overview["counts"]["queued"] == 124


def test_catalog_overview_row_maps_running_to_continue() -> None:
    row = dev_controls_service._catalog_overview_row(
        {"id": "SCI-010", "question_en": "running question", "domain": "physics"},
        {
            "executionStatus": "running",
            "attempts": 1,
            "planId": "dev-5",
            "lastError": "",
        },
    )
    assert row["status"] == "running"
    assert row["action"] == "continue"
    assert row["currentStage"] == "catalog_execution"
    assert row["blocker"] is None


def test_get_catalog_overview_http_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "schemaVersion": 1,
        "teamId": "research-team",
        "generatedAt": "2026-08-20T00:00:00Z",
        "questionCount": 125,
        "counts": {"queued": 125, "running": 0, "succeeded": 0, "failed": 0},
        "questions": [
            {
                "questionId": "SCI-001",
                "title": "Sample question",
                "domain": "physics",
                "status": "queued",
                "executionStatus": "pending",
                "currentStage": "queued",
                "checkpointProgress": "0/1",
                "attempts": 0,
                "planId": "",
                "action": "view",
                "blocker": None,
            }
        ],
    }
    monkeypatch.setattr(
        dev_controls_routes, "get_challenge_cup_catalog_overview", lambda team_id: payload
    )
    response = _client().get(
        "/api/teams/research-team/workflow-orchestration/challenge-program/catalog-overview"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["questionCount"] == 125
    assert body["questions"][0]["questionId"] == "SCI-001"
    assert body["questions"][0]["blocker"] is None


def _receipt_payload(receipt_id: str, question_id: str, stage: str, total_tokens: int) -> dict:
    return ModelInvocationReceipt.from_invocation(
        receipt_id=receipt_id,
        run_id=f"run-{question_id}",
        node_run_id=f"nr-{receipt_id}",
        scope={"teamId": "team-1", "questionId": question_id, "nodeId": stage},
        provider="offline-fake",
        model="fake-model",
        model_version="1",
        requested_model="fake-model",
        status=ModelInvocationStatus.SUCCEEDED,
        request_content="prompt",
        response_content="answer",
        started_at_ms=1000,
        finished_at_ms=1100,
        token_usage={
            "inputTokens": max(total_tokens - 1, 0),
            "outputTokens": min(total_tokens, 1),
            "totalTokens": total_tokens,
        },
        cost={"currency": "USD", "totalCost": 9.99},
        evidence_locator={"kind": "runtime_scene", "sceneId": "scene-1"},
    ).to_dict()


def _persist_receipts(controls_root: Path, team_id: str, receipts: list[dict]) -> None:
    path = controls_root / team_id / "challenge_cup_dev_controls" / "model_invocation_receipts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schemaVersion": 1, "receipts": receipts}, sort_keys=True),
        encoding="utf-8",
    )


def test_token_usage_is_zero_when_no_receipts(controls_root: Path) -> None:
    overview = dev_controls_service.get_challenge_cup_token_usage("team-1")
    assert overview["schemaVersion"] == 1
    assert overview["priced"] is False
    assert overview["unit"] == "tokens"
    assert overview["program"] == {"totalTokens": 0, "callCount": 0, "inputTokens": 0, "outputTokens": 0}
    assert overview["questions"] == []
    assert "totalCost" not in overview
    assert "amount" not in overview


def test_token_usage_skips_malformed_receipts_and_omits_invented_cost(
    controls_root: Path,
) -> None:
    good = _receipt_payload("inv-1", "SCI-001", "hypothesis_design", 12)
    _persist_receipts(
        controls_root,
        "team-1",
        [good, {"receiptId": "broken"}, {"tokenUsage": {"totalTokens": 99}}],
    )
    overview = dev_controls_service.get_challenge_cup_token_usage("team-1")
    assert overview["program"]["callCount"] == 1
    assert overview["program"]["totalTokens"] == 12
    assert overview["questions"][0]["questionId"] == "SCI-001"
    assert overview["priced"] is False
    assert "totalCost" not in overview
    assert overview["questions"][0]["anomaly"] is None


def test_token_usage_warns_when_one_question_exceeds_stage_median(
    controls_root: Path,
) -> None:
    receipts = [
        _receipt_payload("inv-a", "SCI-001", "hypothesis_design", 10),
        _receipt_payload("inv-b", "SCI-002", "hypothesis_design", 10),
        _receipt_payload("inv-c", "SCI-003", "hypothesis_design", 40),
    ]
    _persist_receipts(controls_root, "team-1", receipts)
    overview = dev_controls_service.get_challenge_cup_token_usage("team-1")
    by_id = {row["questionId"]: row for row in overview["questions"]}
    assert by_id["SCI-001"]["anomaly"] is None
    assert by_id["SCI-002"]["anomaly"] is None
    assert by_id["SCI-003"]["anomaly"]["stageId"] == "hypothesis_design"
    assert "3" in by_id["SCI-003"]["anomaly"]["message"]


def test_token_usage_stays_silent_when_median_samples_are_insufficient(
    controls_root: Path,
) -> None:
    receipts = [
        _receipt_payload("inv-a", "SCI-001", "hypothesis_design", 10),
        _receipt_payload("inv-b", "SCI-002", "hypothesis_design", 40),
    ]
    _persist_receipts(controls_root, "team-1", receipts)
    overview = dev_controls_service.get_challenge_cup_token_usage("team-1")
    assert all(row["anomaly"] is None for row in overview["questions"])


def test_get_token_usage_http_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "schemaVersion": 1,
        "teamId": "research-team",
        "generatedAt": "2026-08-20T00:00:00Z",
        "unit": "tokens",
        "priced": False,
        "program": {"totalTokens": 0, "callCount": 0, "inputTokens": 0, "outputTokens": 0},
        "questions": [],
    }
    monkeypatch.setattr(dev_controls_routes, "get_challenge_cup_token_usage", lambda team_id: payload)
    response = _client().get(
        "/api/teams/research-team/workflow-orchestration/challenge-program/token-usage"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["priced"] is False
    assert body["unit"] == "tokens"
    assert "totalCost" not in body


def test_post_readiness_http_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(team_id: str, *, mode: str = "dev") -> dict:
        assert mode == "dev"
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "report": {
                "schemaVersion": 1,
                "reportKind": REPORT_KIND,
                "status": "READY",
                "mode": "dev",
                "realCampaignAllowed": False,
                "researchAuthorizationRequired": True,
                "nextLegalAction": "RESEARCH_AUTHORIZATION_REQUIRED",
                "generatedAt": "2026-08-18T00:00:00Z",
                "updatedAt": "2026-08-18T00:00:00Z",
                "gates": [],
            },
            "cleanedUp": True,
            "updatedAt": "2026-08-18T00:00:00Z",
        }

    monkeypatch.setattr(dev_controls_routes, "run_challenge_cup_dev_readiness", fake_run)
    response = _client().post(
        f"{DEV_CONTROLS_BASE}/readiness",
        json={"mode": "dev"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["report"]["status"] == "READY"
    assert body["report"]["realCampaignAllowed"] is False
    assert body["cleanedUp"] is True


def test_post_batch_http_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(
        team_id: str,
        plan_id: str,
        max_items: int | None,
        *,
        retry_failed: bool = False,
    ) -> dict:
        assert plan_id == "dev-1"
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "planId": plan_id,
            "gateId": "G1",
            "attempted": ["SCI-091"],
            "outcomes": [{"questionId": "SCI-091", "outcome": "succeeded"}],
            "checkpoint": {
                "schemaVersion": 1,
                "planId": "dev-1",
                "gateId": "G1",
                "questionCount": 1,
                "statusSummary": {"pending": 0, "running": 0, "succeeded": 1, "failed": 0, "blocked": 0},
                "pendingCount": 0,
                "succeededCount": 1,
                "failedCount": 0,
                "blockedCount": 0,
                "totalAttempts": 1,
                "completedQuestionIds": ["SCI-091"],
                "pendingQuestionIds": [],
                "lastUpdatedAt": "2026-08-18T00:00:00Z",
                "canResume": False,
            },
            "persistedAt": "2026-08-18T00:00:00Z",
            "persisted": True,
        }

    monkeypatch.setattr(dev_controls_routes, "run_challenge_cup_dev_batch", fake_run)
    response = _client().post(
        f"{DEV_CONTROLS_BASE}/batches/dev-1",
        json={"maxItems": None},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["planId"] == "dev-1"
    assert body["checkpoint"]["succeededCount"] == 1
    assert body["checkpoint"]["canResume"] is False
    assert body["outcomes"] == [{"questionId": "SCI-091", "outcome": "succeeded"}]


def test_forbidden_batch_plan_maps_to_422(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for plan_id in ("dev-12", "dev-125"):
        response = _client().post(
            f"{DEV_CONTROLS_BASE}/batches/{plan_id}",
            json={"maxItems": None},
        )
        assert response.status_code == 422
        assert "not authorized" in response.json()["detail"]


def test_non_dev_readiness_mode_maps_to_422(
    controls_root: Path,
) -> None:
    response = _client().post(
        f"{DEV_CONTROLS_BASE}/readiness",
        json={"mode": "formal"},
    )
    assert response.status_code == 422
    assert "DEV-only" in response.json()["detail"]


def test_out_of_bounds_max_items_maps_to_422(
    controls_root: Path,
) -> None:
    response = _client().post(
        f"{DEV_CONTROLS_BASE}/batches/dev-1",
        json={"maxItems": MAX_DEV_BATCH_MAX_ITEMS + 1},
    )
    assert response.status_code == 422


def test_missing_team_maps_to_404(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(team_id: str) -> dict:
        raise team_service.TeamNotFoundError("Team not found.")

    monkeypatch.setattr(dev_controls_service.team_service, "get_team", missing)
    response = _client().get(DEV_CONTROLS_BASE)
    assert response.status_code == 404
    assert "Team not found" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Authoritative team id, flow order, repair, storage integrity
# ---------------------------------------------------------------------------


def test_authoritative_team_id_is_used_everywhere(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_team(team_id: str) -> dict:
        canonical = str(team_id or "").strip()
        if not canonical:
            raise team_service.TeamNotFoundError("Team not found.")
        return {"teamId": canonical}

    monkeypatch.setattr(dev_controls_service.team_service, "get_team", fake_get_team)
    _ready_team(controls_root, monkeypatch)
    response = dev_controls_service.run_challenge_cup_dev_batch(" team-1 ", "dev-1", None)
    assert response["teamId"] == "team-1"
    canonical_file = (
        controls_root / "team-1" / "challenge_cup_dev_controls" / "batches" / "dev-1.json"
    )
    assert canonical_file.is_file()

    snapshot = dev_controls_service.get_challenge_cup_dev_control_snapshot(" team-1 ")
    assert snapshot["teamId"] == "team-1"
    assert snapshot["batches"]["dev-1"]["succeededCount"] == 1


def test_missing_authoritative_team_id_fails_closed(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dev_controls_service.team_service, "get_team", lambda team_id: {})
    with pytest.raises(
        dev_controls_service.ChallengeCupDevControlsError,
        match="authoritative teamId",
    ):
        dev_controls_service.get_challenge_cup_dev_control_snapshot("team-alias")


def test_similar_team_ids_stay_isolated(controls_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_team(team_id: str) -> dict:
        canonical = str(team_id or "").strip()
        if canonical not in {"team-1", "team-1-alt"}:
            raise team_service.TeamNotFoundError("Team not found.")
        return {"teamId": canonical}

    monkeypatch.setattr(dev_controls_service.team_service, "get_team", fake_get_team)
    _ready_team(controls_root, monkeypatch)
    dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-1", None)

    with pytest.raises(dev_controls_service.DevFlowConflict, match="out of order"):
        dev_controls_service.run_challenge_cup_dev_batch("team-1-alt", "dev-1", None)
    assert not (
        controls_root / "team-1-alt" / "challenge_cup_dev_controls" / "batches" / "dev-1.json"
    ).exists()


def test_dev_1_batch_without_readiness_conflicts_409(controls_root: Path) -> None:
    response = _client().post(
        f"{DEV_CONTROLS_BASE}/batches/dev-1",
        json={"maxItems": None},
    )
    assert response.status_code == 409
    assert "out of order" in response.json()["detail"]


def test_dev_5_batch_before_dev_1_conflicts_409(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready_team(controls_root, monkeypatch, team_id="research-team")
    response = _client().post(
        f"{DEV_CONTROLS_BASE}/batches/dev-5",
        json={"maxItems": None},
    )
    assert response.status_code == 409
    assert "out of order" in response.json()["detail"]


def test_dev_1_rerun_after_completion_conflicts_409(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready_team(controls_root, monkeypatch, team_id="research-team")
    dev_controls_service.run_challenge_cup_dev_batch("research-team", "dev-1", None)
    response = _client().post(
        f"{DEV_CONTROLS_BASE}/batches/dev-1",
        json={"maxItems": None},
    )
    assert response.status_code == 409


def test_repair_retry_reruns_only_failed_items(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready_team(controls_root, monkeypatch)
    dev_1 = new_dev_batch_state("dev-1")
    run_dev_fixture_batch(dev_1)
    _persist_batch_checkpoint(controls_root, "team-1", "dev-1", dev_1.to_checkpoint())

    dev_5 = new_dev_batch_state("dev-5")
    run_dev_fixture_batch(dev_5)
    failed_id = dev_5.plan.question_ids[2]
    dev_5.record_failure(failed_id, "fixture rejected")
    _persist_batch_checkpoint(controls_root, "team-1", "dev-5", dev_5.to_checkpoint())

    with pytest.raises(dev_controls_service.DevFlowConflict, match="out of order"):
        dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-5", None)

    response = dev_controls_service.run_challenge_cup_dev_batch(
        "team-1", "dev-5", None, retry_failed=True
    )
    assert response["attempted"] == [failed_id]
    assert response["checkpoint"]["failedCount"] == 0
    assert response["checkpoint"]["blockedCount"] == 0
    assert response["checkpoint"]["succeededCount"] == 5
    assert response["checkpoint"]["totalAttempts"] == 6
    snapshot = dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")
    assert snapshot["nextLegalAction"] == "RESEARCH_AUTHORIZATION_REQUIRED"


def test_retry_failed_true_on_healthy_plan_conflicts(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready_team(controls_root, monkeypatch)
    with pytest.raises(dev_controls_service.DevFlowConflict, match="retryFailed"):
        dev_controls_service.run_challenge_cup_dev_batch(
            "team-1", "dev-1", None, retry_failed=True
        )


def test_corrupt_checkpoint_blocks_dispatch_and_snapshot(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready_team(controls_root, monkeypatch)
    batch_dir = controls_root / "team-1" / "challenge_cup_dev_controls" / "batches"
    batch_dir.mkdir(parents=True, exist_ok=True)
    path = batch_dir / "dev-1.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(dev_controls_service.DevControlsStorageError, match="corrupt JSON"):
        dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-1", None)
    assert path.read_text(encoding="utf-8") == "{not json"
    with pytest.raises(dev_controls_service.DevControlsStorageError, match="corrupt JSON"):
        dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")


def test_wrong_plan_checkpoint_blocks_dispatch(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready_team(controls_root, monkeypatch)
    dev_5 = new_dev_batch_state("dev-5")
    _persist_batch_checkpoint(controls_root, "team-1", "dev-1", dev_5.to_checkpoint())
    with pytest.raises(dev_controls_service.DevControlsStorageError, match="plan id mismatch"):
        dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-1", None)


def test_corrupt_readiness_report_blocks_flow(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_dir = controls_root / "research-team" / "challenge_cup_dev_controls"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "readiness_report.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "realCampaignAllowed": False,
                "report": {"schemaVersion": 1, "status": "READY"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(dev_controls_service.DevControlsStorageError, match="report kind"):
        dev_controls_service.get_challenge_cup_dev_control_snapshot("research-team")
    response = _client().get(DEV_CONTROLS_BASE)
    assert response.status_code == 409
    assert "report kind" in response.json()["detail"]


@pytest.mark.parametrize("endpoint", ["snapshot", "readiness", "batch"])
def test_storage_errors_map_to_409_for_all_routes(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    def corrupt(*args, **kwargs):
        raise dev_controls_service.DevControlsStorageError("stored DEV state is corrupt")

    if endpoint == "snapshot":
        monkeypatch.setattr(dev_controls_routes, "get_challenge_cup_dev_control_snapshot", corrupt)
        response = _client().get(DEV_CONTROLS_BASE)
    elif endpoint == "readiness":
        monkeypatch.setattr(dev_controls_routes, "run_challenge_cup_dev_readiness", corrupt)
        response = _client().post(f"{DEV_CONTROLS_BASE}/readiness", json={"mode": "dev"})
    else:
        monkeypatch.setattr(dev_controls_routes, "run_challenge_cup_dev_batch", corrupt)
        response = _client().post(
            f"{DEV_CONTROLS_BASE}/batches/dev-1",
            json={"maxItems": None, "retryFailed": False},
        )
    assert response.status_code == 409
    assert "stored DEV state is corrupt" in response.json()["detail"]


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "invalid_status",
        "inconsistent_ready",
        "stale_contract",
        "stale_source",
        "stale_time",
        "wrong_action",
    ],
)
def test_readiness_report_is_validated_before_persist(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    report = _ready_report()
    if mutation == "duplicate":
        report["gates"].append(dict(report["gates"][0]))
        expected = "duplicated"
    elif mutation == "invalid_status":
        report["gates"][0]["status"] = "UNKNOWN"
        expected = "invalid status"
    elif mutation == "inconsistent_ready":
        report["gates"][0]["status"] = "FAIL"
        expected = "inconsistent"
    elif mutation == "stale_contract":
        report["programContract"]["coreBehaviorHash"] = "0" * 64
        expected = "program contract"
    elif mutation == "stale_source":
        report["sourceCommit"] = "0" * 40
        expected = "source commit"
    elif mutation == "stale_time":
        report["generatedAt"] = "2000-01-01T00:00:00Z"
        expected = "stale"
    else:
        report["nextLegalAction"] = "formal_submission"
        expected = "nextLegalAction"
    writes: list[object] = []
    monkeypatch.setattr(
        dev_controls_service,
        "_strict_json_write",
        lambda *args, **kwargs: writes.append((args, kwargs)),
    )
    with pytest.raises(dev_controls_service.DevControlsStorageError, match=expected):
        dev_controls_service._persist_report("team-1", report)
    assert writes == []


def test_succeeded_checkpoint_without_result_fails_closed(
    controls_root: Path,
) -> None:
    _persist_readiness_report(controls_root, "team-1")
    checkpoint = new_dev_batch_state("dev-1").to_checkpoint()
    record = checkpoint["records"][0]
    record.update(
        {
            "status": "succeeded",
            "attempts": 0,
            "invalidated": False,
            "last_error": None,
            "result": None,
        }
    )
    _persist_batch_checkpoint(controls_root, "team-1", "dev-1", checkpoint)
    with pytest.raises(
        dev_controls_service.DevControlsStorageError,
        match="record semantics are invalid",
    ):
        dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")


def test_orphan_dev_5_checkpoint_fails_closed(
    controls_root: Path,
) -> None:
    _persist_readiness_report(controls_root, "team-1")
    dev_5 = new_dev_batch_state("dev-5")
    run_dev_fixture_batch(dev_5)
    _persist_batch_checkpoint(controls_root, "team-1", "dev-5", dev_5.to_checkpoint())
    with pytest.raises(
        dev_controls_service.DevControlsStorageError,
        match="no bound dev-1 checkpoint version",
    ):
        dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")


def test_dev_5_bound_to_stale_dev_1_checkpoint_fails_closed(
    controls_root: Path,
) -> None:
    _persist_readiness_report(controls_root, "team-1")
    dev_1 = new_dev_batch_state("dev-1")
    run_dev_fixture_batch(dev_1)
    _persist_batch_checkpoint(controls_root, "team-1", "dev-1", dev_1.to_checkpoint())
    dev_5 = new_dev_batch_state("dev-5")
    run_dev_fixture_batch(dev_5)
    _persist_batch_checkpoint(controls_root, "team-1", "dev-5", dev_5.to_checkpoint())
    _persist_batch_checkpoint(controls_root, "team-1", "dev-1", dev_1.to_checkpoint())
    with pytest.raises(
        dev_controls_service.DevControlsStorageError,
        match="stale dev-1 checkpoint version",
    ):
        dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")


def test_ready_report_is_rejected_while_working_tree_is_dirty(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dev_controls_service, "_current_tree_is_clean", lambda: False)
    with pytest.raises(
        dev_controls_service.DevControlsStorageError,
        match="working tree is dirty",
    ):
        dev_controls_service._persist_report("team-1", _ready_report())


def test_dirty_not_ready_report_replaces_previous_ready_report(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _persist_readiness_report(controls_root, "team-1")
    failed_gates = [
        dict(gate) for gate in _ready_report()["gates"]
    ]
    failed_gates[0]["status"] = "FAIL"
    monkeypatch.setattr(dev_controls_service, "_current_tree_is_clean", lambda: False)

    dev_controls_service._persist_report(
        "team-1",
        _ready_report(
            status="NOT_READY",
            gates=failed_gates,
            nextLegalAction="repair_failed_platform_gates",
            sourceCommit="",
        ),
    )

    snapshot = dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")
    assert snapshot["report"]["status"] == "NOT_READY"
    assert snapshot["nextLegalAction"] == "repair_failed_platform_gates"


def test_new_readiness_evidence_invalidates_old_batches(controls_root: Path) -> None:
    _persist_readiness_report(controls_root, "team-1")
    dev_1 = new_dev_batch_state("dev-1")
    run_dev_fixture_batch(dev_1)
    _persist_batch_checkpoint(controls_root, "team-1", "dev-1", dev_1.to_checkpoint())
    dev_5 = new_dev_batch_state("dev-5")
    run_dev_fixture_batch(dev_5)
    _persist_batch_checkpoint(controls_root, "team-1", "dev-5", dev_5.to_checkpoint())

    report_path = controls_root / "team-1" / "challenge_cup_dev_controls" / "readiness_report.json"
    envelope = json.loads(report_path.read_text(encoding="utf-8"))
    envelope["updatedAt"] = dev_controls_service._utc_now()
    report_path.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")

    snapshot = dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")
    assert snapshot["batches"] == {}
    assert snapshot["nextLegalAction"] == "run_dev_1_fixture_batch"


def test_current_batch_missing_readiness_evidence_fails_closed(
    controls_root: Path,
) -> None:
    _persist_readiness_report(controls_root, "team-1")
    state = new_dev_batch_state("dev-1")
    run_dev_fixture_batch(state)
    _persist_batch_checkpoint(controls_root, "team-1", "dev-1", state.to_checkpoint())
    batch_path = controls_root / "team-1" / "challenge_cup_dev_controls" / "batches" / "dev-1.json"
    envelope = json.loads(batch_path.read_text(encoding="utf-8"))
    envelope.pop("readinessEvidence")
    batch_path.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")
    with pytest.raises(
        dev_controls_service.DevControlsStorageError,
        match="readiness evidence",
    ):
        dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_locator",
        "submission_eligible",
        "empty_locators",
        "cross_question_knowledge",
        "wrong_adapter",
    ],
)
def test_non_dev_fixture_result_fails_closed(
    controls_root: Path,
    mutation: str,
) -> None:
    _persist_readiness_report(controls_root, "team-1")
    state = new_dev_batch_state("dev-1")
    run_dev_fixture_batch(state)
    checkpoint = state.to_checkpoint()
    result = checkpoint["records"][0]["result"]
    if mutation == "missing_locator":
        result.pop("model_receipt_locator")
    elif mutation == "submission_eligible":
        result["status"] = "submission_eligible"
        result["submission_eligible"] = True
    elif mutation == "empty_locators":
        result["model_receipt_locator"] = "model-receipt://dev/"
        result["knowledge_locator"] = "knowledge://dev/"
    elif mutation == "cross_question_knowledge":
        result["knowledge_locator"] = "knowledge://dev/SCI-096"
    else:
        result["model_receipt_locator"] = (
            "model-receipt://dev/neural_spike_coding/" + "a" * 64
        )
    _persist_batch_checkpoint(controls_root, "team-1", "dev-1", checkpoint)
    with pytest.raises(
        dev_controls_service.DevControlsStorageError,
        match="record semantics|DEV fixture result",
    ):
        dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")


@pytest.mark.parametrize("status", ["failed", "blocked"])
def test_failed_or_blocked_record_cannot_carry_a_formal_result(
    controls_root: Path,
    status: str,
) -> None:
    _persist_readiness_report(controls_root, "team-1")
    state = new_dev_batch_state("dev-1")
    run_dev_fixture_batch(state)
    checkpoint = state.to_checkpoint()
    record = checkpoint["records"][0]
    record["status"] = status
    record["last_error"] = "fixture failure"
    record["result"]["status"] = "submission_eligible"
    record["result"]["submission_eligible"] = True
    _persist_batch_checkpoint(controls_root, "team-1", "dev-1", checkpoint)

    with pytest.raises(
        dev_controls_service.DevControlsStorageError,
        match="DEV fixture result",
    ):
        dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")


def test_dev_result_requires_literal_false_submission_eligibility(
    controls_root: Path,
) -> None:
    _persist_readiness_report(controls_root, "team-1")
    state = new_dev_batch_state("dev-1")
    run_dev_fixture_batch(state)
    checkpoint = state.to_checkpoint()
    checkpoint["records"][0]["result"]["submission_eligible"] = 0
    _persist_batch_checkpoint(controls_root, "team-1", "dev-1", checkpoint)

    with pytest.raises(
        dev_controls_service.DevControlsStorageError,
        match="DEV fixture result",
    ):
        dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")


def test_snapshot_uses_the_same_team_transaction_lock_as_writes(
    controls_root: Path,
) -> None:
    with dev_controls_service._team_transaction("team-1"):
        with pytest.raises(dev_controls_service.DevFlowConflict, match="transaction"):
            dev_controls_service.get_challenge_cup_dev_control_snapshot("team-1")


def test_team_transaction_lock_is_cross_process_and_team_scoped(
    controls_root: Path,
) -> None:
    lock_path = dev_controls_service._team_lock_path("team-1")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        assert dev_controls_service._try_lock_handle(handle) is True
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        code = (
            "from pathlib import Path; "
            "from core.web.services.team_workflow.challenge_cup_dev_controls "
            "import _try_lock_handle; "
            f"h=Path({str(lock_path)!r}).open('a+b'); "
            "print('acquired' if _try_lock_handle(h) else 'blocked'); h.close()"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            **no_console_subprocess_kwargs(),
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "blocked"
        dev_controls_service._unlock_handle(handle)
    with dev_controls_service._team_transaction("team-1"):
        with dev_controls_service._team_transaction("team-2"):
            pass


def test_readiness_in_progress_blocks_batch_and_second_readiness(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready_team(controls_root, monkeypatch, team_id="research-team")
    dev_controls_service._READINESS_IN_PROGRESS.add("research-team")
    try:
        batch_response = _client().post(
            f"{DEV_CONTROLS_BASE}/batches/dev-1",
            json={"maxItems": None, "retryFailed": False},
        )
        readiness_response = _client().post(
            f"{DEV_CONTROLS_BASE}/readiness",
            json={"mode": "dev"},
        )
    finally:
        dev_controls_service._READINESS_IN_PROGRESS.discard("research-team")
    assert batch_response.status_code == 409
    assert "readiness is running" in batch_response.json()["detail"]
    assert readiness_response.status_code == 409
    assert "already running" in readiness_response.json()["detail"]


def test_strict_write_failure_keeps_old_file(controls_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = controls_root / "team-1" / "challenge_cup_dev_controls" / "batches" / "dev-1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("OLD", encoding="utf-8")

    def boom(source, dest):
        raise OSError("replace boom")

    monkeypatch.setattr(dev_controls_service, "_os_replace", boom)
    with pytest.raises(dev_controls_service.DevControlsStorageError, match="write failed"):
        dev_controls_service._strict_json_write(path, {"planId": "dev-1"})
    assert path.read_text(encoding="utf-8") == "OLD"
    assert not list(path.parent.glob(".*.tmp"))


def test_strict_write_wraps_directory_creation_failure(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = controls_root / "team-1" / "challenge_cup_dev_controls" / "report.json"

    def boom(*args, **kwargs):
        raise OSError("mkdir boom")

    monkeypatch.setattr(Path, "mkdir", boom)
    with pytest.raises(dev_controls_service.DevControlsStorageError, match="write failed"):
        dev_controls_service._strict_json_write(path, {"schemaVersion": 1})


def test_batch_persist_failure_never_falls_back_to_inplace(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready_team(controls_root, monkeypatch)

    def boom(source, dest):
        raise OSError("replace boom")

    monkeypatch.setattr(dev_controls_service, "_os_replace", boom)
    with pytest.raises(dev_controls_service.DevControlsStorageError, match="write failed"):
        dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-1", None)
    batch_path = (
        controls_root / "team-1" / "challenge_cup_dev_controls" / "batches" / "dev-1.json"
    )
    assert not batch_path.exists()
    assert not list(batch_path.parent.glob(".*.tmp"))


def test_out_of_order_batch_dispatches_nothing(
    controls_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready_team(controls_root, monkeypatch)
    calls: list[list] = []

    def spy_run(state, *, max_items=None, on_item=None):
        calls.append([state, max_items, on_item])
        from core.research.competition.dev_control_batch import run_dev_fixture_batch as real_run

        return real_run(state, max_items=max_items, on_item=on_item)

    monkeypatch.setattr(dev_controls_service, "run_dev_fixture_batch", spy_run)
    with pytest.raises(dev_controls_service.DevFlowConflict, match="out of order"):
        dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-5", None)
    assert calls == []
