"""Challenge Cup real catalog batch executor tests.

Covers the pure real-batch contracts (plan allowlist, gate mapping, frozen
concurrency policy, circuit breaker) and the service invariants (fail-closed
authorization, gate progression, bounded launches, checkpoint resume, harvest
mapping, awaiting-approval promotion, cancel). All runtime touchpoints (run
launcher, START_NODE dispatch, status reads, approved outputs) are injected
fakes; no real run, Qwen call, network or formal submission is ever invoked.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from core.research.competition.catalog_execution import (
    CatalogExecutionError,
    CatalogExecutionState,
    QuestionStatus,
    build_result_set,
    dev_plan,
)
from core.research.competition.question_result_package import (
    QuestionResultPackage,
    canonical_model_policy,
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
from core.research.competition.result_set import QuestionResult
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services.team_workflow import challenge_cup_real_batch as svc
from core.web.services.team_workflow.research_runtime import catalog_run_authorization
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    CONTROL_OPERATOR_ID_ENV,
    CONTROL_OPERATOR_ROLES_ENV,
)
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS, open_ledger_store
from tests.test_challenge_question_result_package import _valid_payload

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
        self.model_policy = deepcopy(_valid_payload()["model_policy"])
        self.runs: dict[str, dict] = {}
        self.approved: dict[str, dict] = {}
        self.launch_log: list[str] = []
        self.start_log: list[str] = []
        self.launch_failures: set[str] = set()
        monkeypatch.setattr(
            svc,
            "formal_team_workspace_root",
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
        monkeypatch.setattr(
            svc,
            "resolve_catalog_model_policy",
            lambda _team_id: deepcopy(self.model_policy),
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

    def approve(
        self,
        question_id: str,
        plan_id: str,
        *,
        package: QuestionResultPackage | dict | None = None,
    ) -> None:
        state = svc._state_of(svc._load_envelope(TEAM_ID, plan_id))
        resolved_package = package or _approved_package(
            state,
            question_id,
            run_id=f"run-{question_id.lower()}",
        )
        self.approved[question_id] = {
            "reviewRunId": f"run-{question_id.lower()}",
            "catalogId": "science-125-questions-2021",
            "artifactSha256": "f" * 64,
            "resultPackage": (
                resolved_package.to_dict()
                if isinstance(resolved_package, QuestionResultPackage)
                else deepcopy(resolved_package)
            ),
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


def _approved_package(
    state: CatalogExecutionState,
    question_id: str,
    *,
    package_id: str | None = None,
    run_id: str | None = None,
) -> QuestionResultPackage:
    payload = deepcopy(_valid_payload())
    resolved_run_id = run_id or f"run-{question_id.lower()}-seed"
    payload.update(
        {
            "package_id": package_id or f"pkg-{question_id.lower()}-seed",
            "scope": state.scope.to_dict(),
            "question_id": question_id,
            "run_id": resolved_run_id,
            "input_snapshot_sha256": "a" * 64,
        }
    )
    for section_name in ("selection", "research_plan"):
        human_gate = payload[section_name]["human_gate"]
        human_gate.update(
            {
                "decision": "approved",
                "reviewer": "reviewer-seed",
                "decided_at": "2026-08-23T10:00:00Z",
            }
        )
    payload["result_classification"]["status"] = "approved"
    payload.pop("failure", None)
    for stage, receipt in payload["model_invocation_receipts"].items():
        receipt["receiptId"] = f"receipt-{question_id.lower()}-{stage}"
        receipt["nodeRunId"] = f"node-{question_id.lower()}-{stage}"
        receipt["runId"] = resolved_run_id
        receipt["scope"].update(
            {
                "questionId": question_id,
                "runId": resolved_run_id,
                "catalogId": state.scope.catalog_id,
                "catalogVersion": state.scope.catalog_version,
                "catalogSha256": state.scope.catalog_sha256,
                "scopeHash": state.scope.scope_hash,
            }
        )
    return QuestionResultPackage.create(payload)


class _SeedState:
    def __init__(self, *results: QuestionResult) -> None:
        self._results = results

    def succeeded_results(self) -> tuple[QuestionResult, ...]:
        return self._results


def _seed_state(
    monkeypatch: pytest.MonkeyPatch,
    *results: QuestionResult,
) -> None:
    monkeypatch.setattr(svc, "_load_envelope", lambda team_id, plan_id: {"planId": plan_id})
    monkeypatch.setattr(svc, "_state_of", lambda envelope: _SeedState(*results))


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


@pytest.mark.parametrize(
    ("snapshot_kind", "expected_code"),
    [
        ("lookalike_action", "platform_not_authorized"),
        ("mismatched_report_hash", "catalog_run_authorization_required"),
        ("foreign_team", "platform_not_authorized"),
    ],
)
def test_start_rejects_untrusted_readiness_snapshot(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    snapshot_kind: str,
    expected_code: str,
) -> None:
    harness.authorize("real-1")
    snapshot: dict[str, object] = {
        "nextLegalAction": "RESEARCH_AUTHORIZATION_REQUIRED",
        "readinessReport": dict(harness.readiness_report),
    }
    if snapshot_kind == "lookalike_action":
        snapshot["nextLegalAction"] = "BOGUS_AUTHORIZATION_REQUIRED"
    elif snapshot_kind == "mismatched_report_hash":
        snapshot["readinessReport"] = {
            **harness.readiness_report,
            "reportId": "changed-under-old-hash",
        }
        snapshot["readinessReportSha256"] = catalog_run_authorization.readiness_report_sha256(
            harness.readiness_report
        )
    elif snapshot_kind == "foreign_team":
        snapshot["teamId"] = "another-research-team"
    else:  # pragma: no cover - keeps the parametrized fixture exhaustive.
        raise AssertionError(snapshot_kind)
    monkeypatch.setattr(
        svc,
        "get_challenge_cup_dev_control_snapshot",
        lambda _team_id: dict(snapshot),
    )

    with pytest.raises(svc.ChallengeCupRealBatchError) as rejected:
        svc.start_real_batch(
            TEAM_ID,
            plan_id="real-1",
            confirmed=True,
            launcher=harness.launcher,
            start_dispatcher=harness.start_dispatcher,
        )
    assert rejected.value.code == expected_code
    assert harness.launch_log == []
    assert harness.start_log == []


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


def test_poll_harvests_terminal_run_across_readiness_rotation(
    harness: _Harness,
) -> None:
    _start(harness, "real-1")
    harness.readiness_report = {
        **harness.readiness_report,
        "reportId": "real-batch-test-readiness-v2",
    }
    harness.authorize("real-1")
    launch_log_after_rotation = list(harness.launch_log)
    harness.set_run_status("SCI-091", "succeeded")
    harness.approve("SCI-091", "real-1")

    polled = _poll(harness, "real-1")

    outcomes = {item["questionId"]: item["outcome"] for item in polled["harvested"]}
    assert outcomes["SCI-091"] == "succeeded"
    assert harness.launch_log == launch_log_after_rotation
    state = svc._state_of(svc._load_envelope(TEAM_ID, "real-1"))
    assert state.status("SCI-091") is QuestionStatus.SUCCEEDED
    assert svc._gate_complete(TEAM_ID, "G5") is True


def test_poll_fences_start_dispatch_across_readiness_rotation(
    harness: _Harness,
) -> None:
    _start(harness, "real-1")
    envelope = svc._load_envelope(TEAM_ID, "real-1")
    envelope["runRefs"]["SCI-091"]["started"] = False
    svc._save_envelope(TEAM_ID, envelope)
    harness.readiness_report = {
        **harness.readiness_report,
        "reportId": "real-batch-test-readiness-v2",
    }
    harness.authorize("real-1")
    start_log_after_rotation = list(harness.start_log)

    with pytest.raises(
        svc.ChallengeCupRealBatchError,
        match="readiness authorization has changed",
    ):
        _poll(harness, "real-1")

    assert harness.start_log == start_log_after_rotation


def test_gate_progression_requires_previous_gate_complete(harness: _Harness) -> None:
    with pytest.raises(svc.ChallengeCupRealBatchError, match="real-1 batch"):
        _start(harness, "real-5")
    with pytest.raises(svc.ChallengeCupRealBatchError, match="real-5 batch"):
        _start(harness, "real-12")


def test_cross_gate_seed_preserves_canonical_package_and_is_idempotent(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = new_real_batch_state("real-5")
    package = _approved_package(target, "SCI-091")
    result = QuestionResult.from_package(package)
    _seed_state(monkeypatch, result, result)

    assert (
        svc._seed_from_previous_gates(
            TEAM_ID,
            target,
            expected_model_policy_sha256=package.model_policy["policySha256"],
        )
        == 1
    )

    seeded = target.result_for("SCI-091")
    assert seeded is not None
    assert target.status("SCI-091") is QuestionStatus.SUCCEEDED
    assert target.attempts("SCI-091") == 1
    assert seeded.submission_eligible is True
    assert seeded.catalog_id == target.scope.catalog_id
    assert seeded.catalog_version == target.scope.catalog_version
    assert seeded.scope_hash == target.scope.scope_hash
    assert seeded.package_snapshot == package.to_dict()
    assert seeded.package_snapshot["canonical_sha256"] == package.canonical_sha256
    assert seeded.package_snapshot["idempotency_key"] == package.idempotency_key
    assert (
        seeded.package_snapshot["model_invocation_receipts"]
        == package.to_dict()["model_invocation_receipts"]
    )


def test_cross_gate_seed_rejects_legacy_result(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = new_real_batch_state("real-5")
    legacy = QuestionResult.create(
        scope=target.scope,
        question_id="SCI-091",
        model_receipt_locator="legacy://receipt",
        knowledge_locator="legacy://knowledge",
    )
    _seed_state(monkeypatch, legacy)

    with pytest.raises(CatalogExecutionError, match="canonical package"):
        svc._seed_from_previous_gates(
            TEAM_ID,
            target,
            expected_model_policy_sha256=harness.model_policy["policySha256"],
        )

    assert target.result_for("SCI-091") is None


def test_cross_gate_seed_validates_every_package_before_mutating_target(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = new_real_batch_state("real-5")
    valid = QuestionResult.from_package(_approved_package(target, "SCI-091"))
    corrupt = QuestionResult.from_package(_approved_package(target, "SCI-096"))
    corrupt_snapshot = corrupt.package_snapshot
    assert corrupt_snapshot is not None
    corrupt_snapshot["canonical_sha256"] = "0" * 64
    corrupt = QuestionResult(
        locator=corrupt.locator,
        model_receipt_locator=corrupt.model_receipt_locator,
        knowledge_locator=corrupt.knowledge_locator,
        template_version=corrupt.template_version,
        status=corrupt.status,
        submission_eligible=corrupt.submission_eligible,
        _package_snapshot_json=json.dumps(
            corrupt_snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    _seed_state(monkeypatch, valid, corrupt)
    before = target.to_checkpoint()
    target_envelope = svc._envelope_path(TEAM_ID, "real-5")
    target_envelope.parent.mkdir(parents=True, exist_ok=True)
    target_envelope.write_text('{"sentinel":true}\n', encoding="utf-8")
    envelope_before = target_envelope.read_bytes()

    with pytest.raises(ValueError, match="canonical hash"):
        svc._seed_from_previous_gates(
            TEAM_ID,
            target,
            expected_model_policy_sha256=harness.model_policy["policySha256"],
        )

    assert target.to_checkpoint() == before
    assert target.attempts("SCI-091") == 0
    assert target.result_for("SCI-091") is None
    assert target.attempts("SCI-096") == 0
    assert target.result_for("SCI-096") is None
    assert target_envelope.read_bytes() == envelope_before


def test_cross_gate_seed_rejects_conflicting_package_hashes_before_mutation(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = new_real_batch_state("real-5")
    first = QuestionResult.from_package(
        _approved_package(target, "SCI-091", package_id="pkg-sci-091-seed-a")
    )
    second = QuestionResult.from_package(
        _approved_package(target, "SCI-091", package_id="pkg-sci-091-seed-b")
    )
    _seed_state(monkeypatch, first, second)
    before = target.to_checkpoint()

    with pytest.raises(CatalogExecutionError, match="different canonical packages"):
        svc._seed_from_previous_gates(
            TEAM_ID,
            target,
            expected_model_policy_sha256=harness.model_policy["policySha256"],
        )

    assert target.to_checkpoint() == before
    assert target.attempts("SCI-091") == 0
    assert target.result_for("SCI-091") is None


def test_server_model_policy_freezes_configured_flash_dialogue_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    role_bindings = {
        role.product_role_id: f"agent-{index}"
        for index, role in enumerate(
            catalog_run_authorization.CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.product_agents
        )
    }
    model_by_agent = {
        f"agent-{index}": ("opencode_go", "deepseek-v4-flash")
        for index in range(6)
    }

    class _FakeLlm:
        model_library: ClassVar[dict[str, object]] = {
            "opencode_go/deepseek-v4-flash": {
                "upstream_id": "deepseek-v4-flash"
            },
            "opencode_go/gpt-5": {"upstream_id": "gpt-5"},
        }

        @staticmethod
        def resolve_model_ref(value: str) -> str:
            return value

        @staticmethod
        def get_provider(provider_id: str) -> SimpleNamespace:
            return SimpleNamespace(
                provider_id=provider_id,
                service_class="aggregator",
                kind="opencode",
                vendor="opencode",
                label=provider_id,
                base_url="https://opencode.ai/zen/go/v1",
            )

    monkeypatch.setattr(
        catalog_run_authorization,
        "resolve_team_role_bindings",
        lambda _team_id: role_bindings,
    )
    monkeypatch.setattr(
        catalog_run_authorization.agent_directory_service,
        "get_agent",
        lambda agent_id, include_archived=False: {
            "agentId": agent_id,
            "status": "active",
            "llmBindings": {"dialogue": {"modelId": model_by_agent[agent_id][1]}},
        },
    )
    monkeypatch.setattr(
        catalog_run_authorization,
        "get_config",
        lambda: SimpleNamespace(llm=_FakeLlm()),
    )
    monkeypatch.setattr(
        catalog_run_authorization,
        "resolve_agent_llm",
        lambda agent, slot, config: SimpleNamespace(
            config=config,
            model_ref=(
                f"{model_by_agent[agent['agentId']][0]}/"
                f"{model_by_agent[agent['agentId']][1]}"
            ),
            model_id=model_by_agent[agent["agentId"]][1],
            model=model_by_agent[agent["agentId"]][1],
            provider_id=model_by_agent[agent["agentId"]][0],
        ),
    )

    policy = catalog_run_authorization.resolve_catalog_model_policy(TEAM_ID)

    assert policy["family"] == "deepseek"
    assert policy["providerIds"] == ["opencode_go"]
    assert policy["modelIds"] == ["deepseek-v4-flash"]
    assert policy["requireOfficialProvider"] is False
    assert len(policy["policySha256"]) == 64

    routing_policy = catalog_run_authorization.resolve_catalog_model_routing_policy(
        TEAM_ID
    )
    for purpose_routes in routing_policy["routes"].values():
        for role_id, route in purpose_routes["byProductRole"].items():
            assert route["productRoleId"] == role_id
            assert route["modelRef"] == "opencode_go/deepseek-v4-flash"
            assert route["officialProvider"] is False

    model_by_agent["agent-5"] = ("opencode_go", "gpt-5")
    monkeypatch.setattr(
        catalog_run_authorization,
        "resolve_agent_llm",
        lambda agent, slot, config: SimpleNamespace(
            config=config,
            model_ref=(
                f"{model_by_agent[agent['agentId']][0]}/"
                f"{model_by_agent[agent['agentId']][1]}"
            ),
            model_id=model_by_agent[agent["agentId"]][1],
            model=model_by_agent[agent["agentId"]][1],
            provider_id=model_by_agent[agent["agentId"]][0],
        ),
    )
    with pytest.raises(
        catalog_run_authorization.CatalogRunAuthorizationError,
        match="one model family",
    ):
        catalog_run_authorization.resolve_catalog_model_policy(TEAM_ID)

    model_by_agent["agent-5"] = ("opencode_go", "deepseek-v4-flash")
    monkeypatch.setattr(
        _FakeLlm,
        "get_provider",
        staticmethod(
            lambda provider_id: SimpleNamespace(
                provider_id=provider_id,
                service_class="aggregator",
                kind="opencode",
                vendor="opencode",
                label=provider_id,
                base_url="http://opencode.ai/zen/go/v1",
            )
        ),
    )
    with pytest.raises(
        catalog_run_authorization.CatalogRunAuthorizationError,
        match="valid configured provider",
    ):
        catalog_run_authorization.resolve_catalog_model_policy(TEAM_ID)


def test_legacy_catalog_authorization_without_policy_fails_closed(
    harness: _Harness,
) -> None:
    plan = real_plan("real-1")
    legacy_scope = {
        "planId": "real-1",
        "gateId": str(plan.gate_id),
        "questionIds": [str(question_id) for question_id in plan.question_ids],
    }
    legacy_record = catalog_run_authorization.record_catalog_run_authorization(
        TEAM_ID,
        plan_id="real-1",
        batch_scope=legacy_scope,
        approved_by="legacy-operator",
        readiness_evidence=harness.readiness_report,
        approved_at_ms=FIXED_NOW_MS,
    )
    with pytest.raises(
        catalog_run_authorization.CatalogRunAuthorizationError,
        match="authorization",
    ):
        svc._new_envelope(
            TEAM_ID,
            "real-1",
            concurrency=1,
            failure_budget=3,
            authorization=catalog_run_authorization.authorization_to_dict(legacy_record),
        )
    assert not svc._envelope_path(TEAM_ID, "real-1").exists()


def test_question_launch_authorization_lookup_includes_server_model_policy(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness.authorize("real-1")
    from core.web.services.team_workflow import challenge_cup_dev_controls
    from core.web.services.team_workflow.research_runtime import question_launch

    snapshot = {
        "teamId": TEAM_ID,
        "nextLegalAction": "RESEARCH_AUTHORIZATION_REQUIRED",
        "readinessReport": dict(harness.readiness_report),
    }
    monkeypatch.setattr(
        challenge_cup_dev_controls,
        "get_challenge_cup_dev_control_snapshot",
        lambda _team_id: dict(snapshot),
    )
    monkeypatch.setattr(
        catalog_run_authorization,
        "resolve_catalog_model_policy",
        lambda _team_id: deepcopy(harness.model_policy),
    )
    captured: dict[str, object] = {}
    original_find = catalog_run_authorization.find_catalog_run_authorization

    def capture_find(*args, **kwargs):
        captured["scope"] = kwargs["batch_scope"]
        return original_find(*args, **kwargs)

    monkeypatch.setattr(
        catalog_run_authorization,
        "find_catalog_run_authorization",
        capture_find,
    )

    assert question_launch._dev_authorization_ready(TEAM_ID) is True
    assert captured["scope"]["modelPolicy"] == harness.model_policy
    assert question_launch._dev_authorization_ready("another-research-team") is False

    snapshot["nextLegalAction"] = "BOGUS_AUTHORIZATION_REQUIRED"
    assert question_launch._dev_authorization_ready(TEAM_ID) is False
    snapshot["nextLegalAction"] = "RESEARCH_AUTHORIZATION_REQUIRED"
    snapshot["readinessReport"] = {
        **harness.readiness_report,
        "reportId": "changed-under-old-hash",
    }
    snapshot["readinessReportSha256"] = catalog_run_authorization.readiness_report_sha256(
        harness.readiness_report
    )
    assert question_launch._dev_authorization_ready(TEAM_ID) is False


def test_cross_gate_checkpoint_restore_uses_durable_policy_and_seeds_without_state_mock(
    harness: _Harness,
) -> None:
    harness.authorize("real-1")
    prior_authorization = svc._current_catalog_run_authorization(TEAM_ID, "real-1")
    prior_envelope = svc._new_envelope(
        TEAM_ID,
        "real-1",
        concurrency=1,
        failure_budget=3,
        authorization=prior_authorization,
    )
    svc._save_envelope(TEAM_ID, prior_envelope)
    prior_envelope = svc._load_envelope(TEAM_ID, "real-1")
    assert prior_envelope is not None
    prior_state = svc._state_of(prior_envelope)
    package = _approved_package(prior_state, "SCI-091")
    prior_state.record_package(package)
    prior_envelope["checkpoint"] = prior_state.to_checkpoint()
    svc._save_envelope(TEAM_ID, prior_envelope)

    harness.authorize("real-5")
    target_authorization = svc._current_catalog_run_authorization(TEAM_ID, "real-5")
    target_envelope = svc._new_envelope(
        TEAM_ID,
        "real-5",
        concurrency=1,
        failure_budget=3,
        authorization=target_authorization,
    )
    svc._save_envelope(TEAM_ID, target_envelope)
    target_envelope = svc._load_envelope(TEAM_ID, "real-5")
    assert target_envelope is not None
    target_state = svc._state_of(target_envelope)
    seeded = target_state.result_for("SCI-091")
    assert seeded is not None
    assert seeded.package_snapshot == package.to_dict()
    assert (
        seeded.package_snapshot["model_policy"]["policySha256"]
        == package.model_policy["policySha256"]
    )


def test_cross_gate_seed_rejects_target_policy_mismatch_before_envelope_write(
    harness: _Harness,
) -> None:
    harness.authorize("real-1")
    prior_authorization = svc._current_catalog_run_authorization(TEAM_ID, "real-1")
    prior_envelope = svc._new_envelope(
        TEAM_ID,
        "real-1",
        concurrency=1,
        failure_budget=3,
        authorization=prior_authorization,
    )
    prior_state = svc._state_of(prior_envelope)
    prior_state.record_package(_approved_package(prior_state, "SCI-091"))
    prior_envelope["checkpoint"] = prior_state.to_checkpoint()
    svc._save_envelope(TEAM_ID, prior_envelope)

    harness.model_policy = canonical_model_policy(
        {
            "family": "qwen",
            "providerIds": ["dashscope"],
            "modelIds": ["qwen-max"],
            "requireOfficialProvider": True,
        }
    )
    harness.authorize("real-5")
    target_path = svc._envelope_path(TEAM_ID, "real-5")

    with pytest.raises(CatalogExecutionError, match="authorized policy"):
        svc.start_real_batch(
            TEAM_ID,
            plan_id="real-5",
            confirmed=True,
            max_items=0,
            launcher=harness.launcher,
            start_dispatcher=harness.start_dispatcher,
        )

    assert not target_path.exists()


def test_policy_snapshot_is_record_hashed_and_old_policy_fails_closed(
    harness: _Harness,
) -> None:
    harness.authorize("real-1")
    authorization = svc._current_catalog_run_authorization(TEAM_ID, "real-1")
    scope = authorization["batchScope"]
    record = catalog_run_authorization.find_catalog_run_authorization(
        TEAM_ID,
        plan_id="real-1",
        batch_scope=scope,
        readiness_report_sha256_value=catalog_run_authorization.readiness_report_sha256(
            harness.readiness_report
        ),
        require_model_policy=True,
    )
    assert record is not None
    mutated_scope = deepcopy(scope)
    mutated_scope["modelPolicy"]["modelIds"] = ["qwen-replaced"]
    mutated_record = replace(
        record,
        batch_scope_json=json.dumps(
            mutated_scope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    assert catalog_run_authorization.expected_record_hash(mutated_record) != record.record_hash
    assert (
        catalog_run_authorization.validate_catalog_run_authorization(
            mutated_record,
            team_id=TEAM_ID,
            plan_id="real-1",
            require_model_policy=True,
        )
        is False
    )

    envelope = svc._new_envelope(
        TEAM_ID,
        "real-1",
        concurrency=1,
        failure_budget=3,
        authorization=authorization,
    )
    envelope["catalogRunAuthorization"]["batchScope"].pop("modelPolicy")
    with pytest.raises(svc.RealBatchStorageError, match="authorization"):
        svc._state_of(envelope)

    harness.model_policy = canonical_model_policy(
        {
            "family": "qwen",
            "providerIds": ["dashscope"],
            "modelIds": ["qwen-replaced"],
            "requireOfficialProvider": True,
        }
    )
    with pytest.raises(svc.ChallengeCupRealBatchError, match="durable CatalogRunAuthorization"):
        svc._current_catalog_run_authorization(TEAM_ID, "real-1")


def test_catalog_state_missing_envelope_is_none_but_team_boundary_is_enforced(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert svc.get_real_batch_catalog_state(TEAM_ID) is None

    def missing(_team_id: str) -> dict:
        raise svc.team_service.TeamNotFoundError("Team not found.")

    monkeypatch.setattr(svc.team_service, "get_team", missing)
    with pytest.raises(svc.team_service.TeamNotFoundError, match="Team not found"):
        svc.get_real_batch_catalog_state("missing-team")


def test_catalog_state_loads_persisted_real_125_envelope_and_policy_hash(
    harness: _Harness,
) -> None:
    harness.authorize("real-125")
    authorization = svc._current_catalog_run_authorization(TEAM_ID, "real-125")
    envelope = svc._new_envelope(
        TEAM_ID,
        "real-125",
        concurrency=1,
        failure_budget=3,
        authorization=authorization,
    )
    svc._save_envelope(TEAM_ID, envelope)

    loaded = svc.get_real_batch_catalog_state(TEAM_ID)

    assert loaded is not None
    state, policy_sha256 = loaded
    assert isinstance(state, CatalogExecutionState)
    assert state.plan.plan_id == "real-125"
    assert len(state.plan.question_ids) == 125
    assert policy_sha256 == authorization["batchScope"]["modelPolicy"]["policySha256"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("plan", "canonical formal catalog plan"),
        ("authorization", "checkpoint is malformed"),
    ),
)
def test_catalog_state_rejects_noncanonical_plan_or_durable_authorization(
    harness: _Harness,
    mutation: str,
    message: str,
) -> None:
    harness.authorize("real-125")
    authorization = svc._current_catalog_run_authorization(TEAM_ID, "real-125")
    envelope = svc._new_envelope(
        TEAM_ID,
        "real-125",
        concurrency=1,
        failure_budget=3,
        authorization=authorization,
    )
    if mutation == "plan":
        envelope["checkpoint"]["plan"]["plan_id"] = "real-1"
        checkpoint_body = {
            key: value
            for key, value in envelope["checkpoint"].items()
            if key != "checkpoint_sha256"
        }
        encoded = json.dumps(
            checkpoint_body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        envelope["checkpoint"]["checkpoint_sha256"] = hashlib.sha256(encoded).hexdigest().upper()
    else:
        envelope["catalogRunAuthorization"]["recordHash"] = "0" * 64
    svc._save_envelope(TEAM_ID, envelope)

    with pytest.raises(svc.RealBatchStorageError, match=message):
        svc.get_real_batch_catalog_state(TEAM_ID)


# ---------------------------------------------------------------------------
# Service: launch, resume and harvest
# ---------------------------------------------------------------------------


def _open_gate(harness: _Harness, plan_id: str) -> None:
    """Drive one gate batch to completion so the next gate unlocks."""
    _start(harness, plan_id)
    state = svc._state_of(svc._load_envelope(TEAM_ID, plan_id))
    for question_id in state.plan.question_ids:
        harness.set_run_status(question_id, "succeeded")
        harness.approve(question_id, plan_id)
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
    harness.approve("SCI-096", "real-5")
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
    assert approved.is_package_backed is True
    assert approved.receipt_complete is True
    assert approved.submission_eligible is True
    assert approved.knowledge_locator.startswith("question-result-package://")
    assert approved.model_receipt_locator.endswith("#model-invocation-receipts")
    manifest = build_result_set(result).manifest()
    entry = next(item for item in manifest["entries"] if item["question_id"] == "SCI-096")
    assert set(entry["receipts"]) == {
        "generation",
        "review",
        "revision",
    }


def test_poll_rejects_approved_output_without_canonical_package(
    harness: _Harness,
) -> None:
    _start(harness, "real-1")
    harness.set_run_status("SCI-091", "succeeded")
    harness.approved["SCI-091"] = {
        "reviewRunId": "run-sci-091",
        "catalogId": "science-125-questions-2021",
        "artifactSha256": "f" * 64,
    }

    with pytest.raises(svc.ChallengeCupRealBatchError) as exc_info:
        _poll(harness, "real-1")

    assert exc_info.value.code == "result_package_invalid"
    envelope = svc._load_envelope(TEAM_ID, "real-1")
    assert envelope["runRefs"]["SCI-091"]["runId"] == "run-sci-091"
    state = svc._state_of(envelope)
    assert state.status("SCI-091") is QuestionStatus.RUNNING
    assert state.result_for("SCI-091") is None


def test_poll_rejects_package_missing_required_receipt_stage(
    harness: _Harness,
) -> None:
    _start(harness, "real-1")
    harness.set_run_status("SCI-091", "succeeded")
    state = svc._state_of(svc._load_envelope(TEAM_ID, "real-1"))
    package = _approved_package(
        state,
        "SCI-091",
        run_id="run-sci-091",
    ).to_dict()
    package["model_invocation_receipts"].pop("revision")
    harness.approve("SCI-091", "real-1", package=package)

    with pytest.raises(svc.ChallengeCupRealBatchError) as exc_info:
        _poll(harness, "real-1")

    assert exc_info.value.code == "result_package_invalid"


def test_poll_rejects_package_bound_to_another_run(harness: _Harness) -> None:
    _start(harness, "real-1")
    harness.set_run_status("SCI-091", "succeeded")
    state = svc._state_of(svc._load_envelope(TEAM_ID, "real-1"))
    harness.approve(
        "SCI-091",
        "real-1",
        package=_approved_package(
            state,
            "SCI-091",
            run_id="run-other",
        ),
    )

    with pytest.raises(svc.ChallengeCupRealBatchError) as exc_info:
        _poll(harness, "real-1")

    assert exc_info.value.code == "result_package_invalid"
    assert "run" in str(exc_info.value)


def test_poll_rejects_canonical_package_tamper(harness: _Harness) -> None:
    _start(harness, "real-1")
    harness.set_run_status("SCI-091", "succeeded")
    state = svc._state_of(svc._load_envelope(TEAM_ID, "real-1"))
    package = _approved_package(
        state,
        "SCI-091",
        run_id="run-sci-091",
    ).to_dict()
    package["result_classification"]["summary"] = "tampered after approval"
    harness.approve("SCI-091", "real-1", package=package)

    with pytest.raises(svc.ChallengeCupRealBatchError) as exc_info:
        _poll(harness, "real-1")

    assert exc_info.value.code == "result_package_invalid"


def test_awaiting_approval_promotes_after_human_gate(harness: _Harness) -> None:
    _start(harness, "real-1")
    harness.set_run_status("SCI-091", "succeeded")
    first = _poll(harness, "real-1")
    assert first["awaitingApprovalQuestionIds"] == ["SCI-091"]

    harness.approve("SCI-091", "real-1")
    second = _poll(harness, "real-1")
    assert second["awaitingApprovalQuestionIds"] == []
    assert second["statusSummary"]["succeeded"] == 1
    assert second["gateComplete"] is True
    state = svc._state_of(svc._load_envelope(TEAM_ID, "real-1"))
    assert state.status("SCI-091") is QuestionStatus.SUCCEEDED
    assert state.attempts("SCI-091") == 2


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
    state = svc._state_of(envelope)
    assert state.outcome_summary()["running"] == 2
    assert state.status("SCI-096") is QuestionStatus.RUNNING


def test_cancel_blocks_pending_and_forbids_restart(harness: _Harness) -> None:
    _open_gate(harness, "real-1")
    _start(harness, "real-5")
    cancelled = svc.cancel_real_batch(TEAM_ID, plan_id="real-5", confirmed=True)
    assert cancelled["cancelled"] is True
    assert cancelled["statusSummary"]["blocked"] == 2
    assert cancelled["statusSummary"]["running"] == 2
    assert cancelled["drainState"] == "draining"
    assert cancelled["stopReason"] == "cancelled_by_operator"
    assert cancelled["remainingFailureBudget"] == cancelled["failureBudget"]
    assert cancelled["concurrencyLimit"] >= 1
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
        assert body["batchScope"]["modelPolicy"] == harness.model_policy
        assert harness.ledger.get_catalog_run_authorization(body["authorizationId"]) is not None

    started = _start(harness, "real-1")
    assert started["launched"]
