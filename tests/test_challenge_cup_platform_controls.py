"""D14A Challenge Cup DEV platform control tests.

Covers pure batch invariants, service invariants (team-scoped persistence,
clean-tree requirement, bounded runtime-scene evidence, ordered nextLegalAction),
HTTP contracts and error mapping. No real experiment, Qwen, network, CUDA/GPU,
DANDI or formal submission is ever invoked.
"""

from __future__ import annotations

import json
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
from core.web.routes.team_workflows import challenge_cup_dev_controls as dev_controls_routes
from core.web.services import team_service
from core.web.services.team_workflow import challenge_cup_dev_controls as dev_controls_service
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

DEV_CONTROLS_BASE = (
    "/api/teams/research-team/workflow-orchestration/challenge-program/dev-controls"
)


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _ready_report(**overrides) -> dict:
    report = {
        "schemaVersion": 1,
        "reportKind": REPORT_KIND,
        "status": "READY",
        "programContract": {"version": "2.2.0", "coreBehaviorHash": "a" * 64},
        "catalogPolicy": {"version": "1.2.0", "corePolicyHash": "b" * 64},
        "mode": "dev",
        "researchAuthorizationRequired": True,
        "realCampaignAllowed": False,
        "gates": [
            {"gateId": "r1_clean_clone", "status": "PASS", "detail": "R1 pytest passed"}
        ],
        "nextLegalAction": "RESEARCH_AUTHORIZATION_REQUIRED",
        "generatedAt": "2026-08-18T00:00:00Z",
    }
    report.update(overrides)
    return report


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


def test_dev_1_batch_persists_checkpoint_team_scoped(controls_root: Path) -> None:
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


def _persist_batch_checkpoint(
    controls_root: Path,
    team_id: str,
    plan_id: str,
    checkpoint: dict,
) -> None:
    path = controls_root / team_id / "challenge_cup_dev_controls" / "batches" / f"{plan_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "planId": plan_id,
                "updatedAt": "2026-08-18T00:00:00Z",
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


def test_dev_5_pause_then_resume_persists_and_never_reruns(controls_root: Path) -> None:
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
    dev_controls_service.run_challenge_cup_dev_batch("team-1", "dev-1", None)

    codes = [item["event_code"] for item in events]
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
    def fake_run(team_id: str, plan_id: str, max_items: int | None) -> dict:
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