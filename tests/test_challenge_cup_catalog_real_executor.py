"""Challenge Cup real catalog batch executor tests.

Covers the pure real-batch contracts (plan allowlist, gate mapping, frozen
concurrency policy, circuit breaker) and the service invariants (fail-closed
authorization, gate progression, bounded launches, checkpoint resume, harvest
mapping, awaiting-approval promotion, cancel). All runtime touchpoints (run
launcher, START_NODE dispatch, status reads, approved outputs) are injected
fakes; no real run, Qwen call, network or formal submission is ever invoked.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.research.competition.catalog_execution import (
    CatalogExecutionState,
    QuestionStatus,
    dev_plan,
)
from core.research.competition.real_control_batch import (
    RealBatchError,
    circuit_breaker_tripped,
    count_consecutive_failures,
    new_real_batch_state,
    project_real_batch_state,
    real_plan,
    validate_real_batch_plan,
    validate_real_concurrency,
)
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services.team_workflow import challenge_cup_real_batch as svc
from core.web.services.team_workflow.research_runtime import catalog_run_authorization
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    CONTROL_OPERATOR_ID_ENV,
    CONTROL_OPERATOR_ROLES_ENV,
)
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS, open_ledger_store

TEAM_ID = "team-real-batch-test"
REAL_BATCH_BASE = (
    "/api/teams/team-real-batch-test/workflow-orchestration/challenge-program/real-batches"
)


class _Harness:
    """Injectable fakes plus isolated team storage for one test."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.ledger = open_ledger_store(tmp_path / "workflow-ledger.sqlite3")
        monkeypatch.setattr(
            catalog_run_authorization,
            "get_write_store",
            lambda: self.ledger,
        )
        self.readiness_report = {
            "status": "READY",
            "researchAuthorizationRequired": True,
            "reportId": "real-batch-test-readiness-v1",
        }
        self.runs: dict[str, dict] = {}
        self.approved: dict[str, dict] = {}
        self.launch_log: list[str] = []
        self.start_log: list[str] = []
        self.launch_failures: set[str] = set()
        monkeypatch.setattr(
            svc,
            "team_workspace_root",
            lambda team_id: tmp_path / "teams" / team_id,
        )
        monkeypatch.setattr(
            svc.team_service,
            "get_team",
            lambda team_id: {"teamId": team_id},
        )
        monkeypatch.setattr(
            svc,
            "get_challenge_cup_dev_control_snapshot",
            lambda team_id: {
                "nextLegalAction": "RESEARCH_AUTHORIZATION_REQUIRED",
                "readinessReport": self.readiness_report,
            },
        )

    def authorize(self, plan_id: str) -> None:
        svc.record_catalog_run_authorization(
            TEAM_ID,
            plan_id=plan_id,
            approved_by="test-operator",
            readiness_evidence=self.readiness_report,
            approved_at_ms=FIXED_NOW_MS,
        )

    def launcher(self, team_id: str, question_id: str, idempotency_key: str) -> dict:
        if question_id in self.launch_failures:
            raise RuntimeError("launcher refused")
        run_id = f"run-{question_id.lower()}"
        self.runs[run_id] = {
            "runId": run_id,
            "questionId": question_id,
            "status": "running",
            "activeNodeId": "node-first",
            "runVersion": 1,
        }
        self.launch_log.append(question_id)
        return self.runs[run_id]

    def start_dispatcher(
        self, team_id: str, run: dict, node_id: str, idempotency_key: str
    ) -> dict:
        self.start_log.append(str(run.get("runId")))
        return {"commandId": f"cmd-{run.get('runId')}", "status": "accepted"}

    def reader(self, team_id: str) -> dict[str, dict]:
        return dict(self.runs)

    def approved_reader(self, team_id: str, question_id: str) -> dict | None:
        return self.approved.get(question_id)

    def set_run_status(self, question_id: str, status: str) -> None:
        run_id = f"run-{question_id.lower()}"
        assert run_id in self.runs
        self.runs[run_id]["status"] = status

    def approve(self, question_id: str) -> None:
        self.approved[question_id] = {
            "reviewRunId": f"review-{question_id.lower()}",
            "catalogId": "science-125-questions-2021",
            "artifactSha256": "f" * 64,
        }


@pytest.fixture()
def harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Harness:
    value = _Harness(monkeypatch, tmp_path)
    try:
        yield value
    finally:
        value.ledger.close()


def _start(harness: _Harness, plan_id: str, **overrides) -> dict:
    harness.authorize(plan_id)
    return svc.start_real_batch(
        TEAM_ID,
        plan_id=plan_id,
        confirmed=True,
        launcher=harness.launcher,
        start_dispatcher=harness.start_dispatcher,
        **overrides,
    )


def _poll(harness: _Harness, plan_id: str) -> dict:
    return svc.poll_real_batch(
        TEAM_ID,
        plan_id=plan_id,
        launcher=harness.launcher,
        start_dispatcher=harness.start_dispatcher,
        run_status_reader=harness.reader,
        approved_output_reader=harness.approved_reader,
    )


# ---------------------------------------------------------------------------
# Pure contract layer
# ---------------------------------------------------------------------------


def test_real_plan_allowlist_and_gate_mapping() -> None:
    assert validate_real_batch_plan("real-1") == "real-1"
    assert validate_real_batch_plan("real-125") == "real-125"
    with pytest.raises(RealBatchError, match="Unknown real batch plan"):
        validate_real_batch_plan("dev-1")
    with pytest.raises(RealBatchError, match="Unknown real batch plan"):
        validate_real_batch_plan("formal")
    for plan_id, gate_id in (
        ("real-1", "G1"),
        ("real-5", "G5"),
        ("real-12", "G12"),
        ("real-125", "G125"),
    ):
        plan = real_plan(plan_id)
        assert plan.gate_id == gate_id
        assert plan.question_ids == dev_plan(plan_id.replace("real-", "dev-")).question_ids


def test_real_concurrency_follows_frozen_policy() -> None:
    assert validate_real_concurrency(1, above_default_allowed=False) == 1
    assert validate_real_concurrency(2, above_default_allowed=False) == 2
    with pytest.raises(RealBatchError, match="requires completed G12 evidence"):
        validate_real_concurrency(3, above_default_allowed=False)
    assert validate_real_concurrency(3, above_default_allowed=True) == 3
    with pytest.raises(RealBatchError, match="frozen hard cap"):
        validate_real_concurrency(9, above_default_allowed=True)
    with pytest.raises(RealBatchError, match="must be an integer"):
        validate_real_concurrency("many", above_default_allowed=False)


def test_circuit_breaker_counts_trailing_failures_only() -> None:
    assert count_consecutive_failures([]) == 0
    assert count_consecutive_failures([{"outcome": "failed"}]) == 1
    assert (
        count_consecutive_failures(
            [{"outcome": "failed"}, {"outcome": "succeeded"}, {"outcome": "failed"}]
        )
        == 1
    )
    assert circuit_breaker_tripped(3, failure_budget=3) is True
    assert circuit_breaker_tripped(2, failure_budget=3) is False


def test_projection_reports_gate_and_breaker_state() -> None:
    state = new_real_batch_state("real-1")
    projection = project_real_batch_state(
        state,
        updated_at="2026-08-20T00:00:00Z",
        consecutive_failures=3,
        failure_budget=3,
    )
    assert projection["gateId"] == "G1"
    assert projection["circuitBreakerOpen"] is True
    assert projection["gateComplete"] is False
    assert projection["canResume"] is True


# ---------------------------------------------------------------------------
# Service: authorization and gate progression fail closed
# ---------------------------------------------------------------------------


def test_start_requires_durable_authorization_and_platform_authorization(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(
        svc.ChallengeCupRealBatchError,
        match="explicit operator confirmation",
    ):
        svc.start_real_batch(TEAM_ID, plan_id="real-1", confirmed=False)
    with pytest.raises(
        svc.ChallengeCupRealBatchError,
        match="durable CatalogRunAuthorization",
    ):
        svc.start_real_batch(
            TEAM_ID,
            plan_id="real-1",
            confirmed=True,
            launcher=harness.launcher,
            start_dispatcher=harness.start_dispatcher,
        )
    monkeypatch.setattr(
        svc,
        "get_challenge_cup_dev_control_snapshot",
        lambda team_id: {"nextLegalAction": "RUN_DEV_FIXTURES"},
    )
    with pytest.raises(svc.ChallengeCupRealBatchError, match="not at RESEARCH_AUTHORIZATION_REQUIRED"):
        _start(harness, "real-1")

    monkeypatch.setattr(
        svc,
        "get_challenge_cup_dev_control_snapshot",
        lambda team_id: {
            "nextLegalAction": "RESEARCH_AUTHORIZATION_REQUIRED",
            "readinessReport": harness.readiness_report,
        },
    )
    harness.authorize("real-1")
    with pytest.raises(
        svc.ChallengeCupRealBatchError,
        match="explicit operator confirmation",
    ):
        svc.start_real_batch(
            TEAM_ID,
            plan_id="real-1",
            confirmed=False,
            launcher=harness.launcher,
            start_dispatcher=harness.start_dispatcher,
        )
    started = svc.start_real_batch(
        TEAM_ID,
        plan_id="real-1",
        confirmed=True,
        launcher=harness.launcher,
        start_dispatcher=harness.start_dispatcher,
    )
    assert started["launched"]

    monkeypatch.setattr(
        svc,
        "get_challenge_cup_dev_control_snapshot",
        lambda team_id: {
            "nextLegalAction": "RESEARCH_AUTHORIZATION_REQUIRED",
            "readinessReport": {
                **harness.readiness_report,
                "reportId": "changed-readiness-report",
            },
        },
    )
    with pytest.raises(
        svc.ChallengeCupRealBatchError,
        match="durable CatalogRunAuthorization",
    ):
        svc.start_real_batch(
            TEAM_ID,
            plan_id="real-1",
            confirmed=True,
            launcher=harness.launcher,
            start_dispatcher=harness.start_dispatcher,
        )


@pytest.mark.parametrize("operation", ["start", "poll"])
def test_old_envelope_cannot_cross_readiness_authorization_change(
    harness: _Harness,
    operation: str,
) -> None:
    harness.authorize("real-1")
    svc.start_real_batch(
        TEAM_ID,
        plan_id="real-1",
        confirmed=True,
        max_items=0,
        launcher=harness.launcher,
        start_dispatcher=harness.start_dispatcher,
    )
    harness.readiness_report = {
        **harness.readiness_report,
        "reportId": "real-batch-test-readiness-v2",
    }
    harness.authorize("real-1")

    with pytest.raises(
        svc.ChallengeCupRealBatchError,
        match="readiness authorization has changed",
    ):
        if operation == "start":
            svc.start_real_batch(
                TEAM_ID,
                plan_id="real-1",
                confirmed=True,
                launcher=harness.launcher,
                start_dispatcher=harness.start_dispatcher,
            )
        else:
            _poll(harness, "real-1")
    assert harness.launch_log == []
    assert harness.start_log == []


def test_poll_revalidates_readiness_immediately_before_refill(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness.authorize("real-1")
    svc.start_real_batch(
        TEAM_ID,
        plan_id="real-1",
        confirmed=True,
        max_items=0,
        launcher=harness.launcher,
        start_dispatcher=harness.start_dispatcher,
    )
    original_save = svc._save_envelope
    readiness_rotated = False

    def save_then_rotate_readiness(team_id: str, envelope: dict) -> None:
        nonlocal readiness_rotated
        original_save(team_id, envelope)
        if readiness_rotated:
            return
        readiness_rotated = True
        harness.readiness_report = {
            **harness.readiness_report,
            "reportId": "real-batch-test-readiness-before-refill",
        }
        harness.authorize("real-1")

    monkeypatch.setattr(svc, "_save_envelope", save_then_rotate_readiness)
    with pytest.raises(
        svc.ChallengeCupRealBatchError,
        match="readiness authorization has changed",
    ):
        _poll(harness, "real-1")
    assert readiness_rotated is True
    assert harness.launch_log == []
    assert harness.start_log == []


def test_gate_progression_requires_previous_gate_complete(harness: _Harness) -> None:
    with pytest.raises(svc.ChallengeCupRealBatchError, match="real-1 batch"):
        _start(harness, "real-5")
    with pytest.raises(svc.ChallengeCupRealBatchError, match="real-5 batch"):
        _start(harness, "real-12")


# ---------------------------------------------------------------------------
# Service: launch, resume and harvest
# ---------------------------------------------------------------------------


def _open_gate(harness: _Harness, plan_id: str) -> None:
    """Drive one gate batch to completion so the next gate unlocks."""
    _start(harness, plan_id)
    state = svc._state_of(svc._load_envelope(TEAM_ID, plan_id))
    for question_id in state.plan.question_ids:
        harness.set_run_status(question_id, "succeeded")
        harness.approve(question_id)
    result = _poll(harness, plan_id)
    assert result["gateComplete"] is True


def test_start_launches_bounded_by_concurrency_and_resumes(harness: _Harness) -> None:
    _open_gate(harness, "real-1")
    started = _start(harness, "real-5")
    assert [item["questionId"] for item in started["launched"]] == [
        "SCI-096",
        "SCI-002",
    ]
    assert started["statusSummary"]["succeeded"] == 1
    assert started["statusSummary"]["running"] == 2
    assert started["pendingCount"] == 2
    assert len(harness.start_log) == 3

    resumed = _start(harness, "real-5")
    assert resumed["launched"] == []
    assert resumed["statusSummary"]["running"] == 2
    assert len(harness.launch_log) == 3

    status = svc.get_real_batch_status(TEAM_ID, "real-5")
    assert status["exists"] is True
    assert status["runRefs"]["SCI-096"]["runId"] == "run-sci-096"


def test_poll_harvests_success_awaiting_and_failure(harness: _Harness) -> None:
    _open_gate(harness, "real-1")
    _start(harness, "real-5")
    harness.set_run_status("SCI-096", "succeeded")
    harness.approve("SCI-096")
    harness.set_run_status("SCI-002", "succeeded")

    polled = _poll(harness, "real-5")
    outcomes = {item["questionId"]: item["outcome"] for item in polled["harvested"]}
    assert outcomes["SCI-096"] == "succeeded"
    assert outcomes["SCI-002"] == "awaiting_human_approval"
    assert polled["statusSummary"]["succeeded"] == 2
    assert polled["statusSummary"]["blocked"] == 1
    assert polled["awaitingApprovalQuestionIds"] == ["SCI-002"]
    assert polled["statusSummary"]["running"] == 2

    result = svc._state_of(svc._load_envelope(TEAM_ID, "real-5"))
    approved = result.result_for("SCI-096")
    assert approved is not None
    assert approved.submission_eligible is True
    assert approved.knowledge_locator.startswith("challenge-question-artifact://science-125-questions-2021/SCI-096/")
    assert approved.model_receipt_locator == "challenge-model-evidence://SCI-096/review-sci-096"


def test_awaiting_approval_promotes_after_human_gate(harness: _Harness) -> None:
    _start(harness, "real-1")
    harness.set_run_status("SCI-091", "succeeded")
    first = _poll(harness, "real-1")
    assert first["awaitingApprovalQuestionIds"] == ["SCI-091"]

    harness.approve("SCI-091")
    second = _poll(harness, "real-1")
    assert second["awaitingApprovalQuestionIds"] == []
    assert second["statusSummary"]["succeeded"] == 1
    assert second["gateComplete"] is True


def test_failure_counts_toward_circuit_breaker_and_stops_refill(harness: _Harness) -> None:
    _open_gate(harness, "real-1")
    _start(harness, "real-5", failure_budget=1)
    harness.set_run_status("SCI-096", "failed")
    harness.set_run_status("SCI-002", "cancelled")

    polled = _poll(harness, "real-5")
    assert polled["statusSummary"]["failed"] == 2
    assert polled["consecutiveFailures"] == 2
    assert polled["circuitBreakerOpen"] is True
    assert polled["launched"] == []
    assert len(harness.launch_log) == 3


def test_checkpoint_round_trip_preserves_batch_state(harness: _Harness) -> None:
    _open_gate(harness, "real-1")
    _start(harness, "real-5")
    envelope = svc._load_envelope(TEAM_ID, "real-5")
    assert envelope is not None
    state = CatalogExecutionState.from_checkpoint(envelope["checkpoint"])
    assert state.outcome_summary()["running"] == 2
    assert state.status("SCI-096") is QuestionStatus.RUNNING


def test_cancel_blocks_pending_and_forbids_restart(harness: _Harness) -> None:
    _open_gate(harness, "real-1")
    _start(harness, "real-5")
    cancelled = svc.cancel_real_batch(TEAM_ID, plan_id="real-5", confirmed=True)
    assert cancelled["cancelled"] is True
    assert cancelled["statusSummary"]["blocked"] == 2
    assert cancelled["statusSummary"]["running"] == 2
    with pytest.raises(svc.ChallengeCupRealBatchError, match="cancelled"):
        _start(harness, "real-5")
    with pytest.raises(svc.ChallengeCupRealBatchError, match="confirmation"):
        svc.cancel_real_batch(TEAM_ID, plan_id="real-5", confirmed=False)


def test_gate_progression_unlocks_after_previous_gate_completes(harness: _Harness) -> None:
    _open_gate(harness, "real-1")

    started = _start(harness, "real-5")
    assert started["statusSummary"]["succeeded"] == 1
    assert [item["questionId"] for item in started["launched"]] == ["SCI-096", "SCI-002"]
    assert started["statusSummary"]["running"] == 2
    with pytest.raises(RealBatchError, match="requires completed G12"):
        _start(harness, "real-5", concurrency=3)
    _start(harness, "real-5", concurrency=1)


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def test_real_batch_routes_authorization_mapping(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _client() as client:
        response = client.get(f"{REAL_BATCH_BASE}/real-1")
        assert response.status_code == 200
        assert response.json()["exists"] is False

        response = client.post(f"{REAL_BATCH_BASE}/real-1/start", json={"confirmed": False})
        assert response.status_code == 428
        assert "explicit operator confirmation" in response.json()["detail"]

        response = client.post(f"{REAL_BATCH_BASE}/real-1/poll")
        assert response.status_code == 404
        assert "No real batch exists" in response.json()["detail"]

        response = client.post(
            f"{REAL_BATCH_BASE}/real-9/start", json={"confirmed": True}
        )
        assert response.status_code == 422


@pytest.mark.parametrize(
    ("suffix", "payload"),
    [
        ("start", {"confirmed": True}),
        ("poll", None),
        ("cancel", {"confirmed": True}),
    ],
)
def test_real_batch_mutating_routes_require_control_token(
    harness: _Harness,
    suffix: str,
    payload: dict | None,
) -> None:
    harness.authorize("real-1")
    with TestClient(create_app()) as client:
        response = client.post(
            f"{REAL_BATCH_BASE}/real-1/{suffix}",
            json=payload,
        )
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("suffix", "payload"),
    [
        ("start", {"confirmed": True}),
        ("poll", None),
        ("cancel", {"confirmed": True}),
    ],
)
def test_real_batch_mutating_routes_require_privileged_operator(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    payload: dict | None,
) -> None:
    harness.authorize("real-1")
    monkeypatch.setenv(CONTROL_OPERATOR_ROLES_ENV, "viewer")
    with _client() as client:
        response = client.post(
            f"{REAL_BATCH_BASE}/real-1/{suffix}",
            json=payload,
        )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "command_forbidden"


def test_real_batch_authorization_route_is_server_principal_bound(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorization_url = f"{REAL_BATCH_BASE}/real-1/authorize"

    with TestClient(create_app()) as client:
        missing_token = client.post(authorization_url, json={})
        assert missing_token.status_code == 403

    monkeypatch.setenv(CONTROL_OPERATOR_ID_ENV, "server-operator-42")
    monkeypatch.setenv(CONTROL_OPERATOR_ROLES_ENV, "viewer")
    with _client() as client:
        denied = client.post(authorization_url, json={})
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "command_forbidden"

    monkeypatch.setenv(CONTROL_OPERATOR_ROLES_ENV, "operator")
    with _client() as client:
        forged_body = client.post(
            authorization_url,
            json={"approvedBy": "client-forged", "readinessReportSha256": "f" * 64},
        )
        assert forged_body.status_code == 422

        approved = client.post(authorization_url, json={})
        assert approved.status_code == 200, approved.text
        body = approved.json()
        assert body["approvedBy"] == "server-operator-42"
        assert body["planId"] == "real-1"
        assert body["readinessReportSha256"]
        assert body["recordHash"]
        assert harness.ledger.get_catalog_run_authorization(body["authorizationId"]) is not None

    started = _start(harness, "real-1")
    assert started["launched"]
