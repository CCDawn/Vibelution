from __future__ import annotations

import pytest

from core.research.competition.catalog_execution import (
    CatalogExecutionError,
    build_result_set,
)
from core.research.competition.real_control_batch import (
    new_real_batch_state,
    project_real_batch_state,
)
from core.research.competition.result_set import QuestionResult
from tests.test_catalog_execution_state_machine import _package


def test_real_projection_exposes_package_quality_and_integrity_hashes() -> None:
    state = new_real_batch_state("real-1")
    package = _package(state.scope, state.plan.question_ids[0])
    state.record_package(package)

    projection = project_real_batch_state(
        state,
        updated_at="2026-08-23T10:00:00Z",
    )

    checkpoint = state.to_checkpoint()
    manifest = build_result_set(state).manifest()
    assert projection["checkpointSha256"] == checkpoint["checkpoint_sha256"]
    assert projection["resultManifestSha256"] == manifest["manifest_sha256"]
    assert projection["packageQualitySummary"] == {
        "approved": 1,
        "blocked": 0,
        "failed": 0,
        "pendingHumanGate": 0,
        "packageBacked": 1,
    }


def test_real_projection_preserves_legacy_checkpoint_without_claiming_v2_hash() -> None:
    state = new_real_batch_state("real-1")
    question_id = state.plan.question_ids[0]
    state.mark_running(question_id)
    state.record_success(
        question_id,
        QuestionResult.create(
            scope=state.scope,
            question_id=question_id,
            model_receipt_locator="legacy-model-receipt://sci-091",
            knowledge_locator="legacy-knowledge://sci-091",
        ),
    )

    checkpoint = state.to_checkpoint()
    assert "schema_version" not in checkpoint
    assert "checkpoint_sha256" not in checkpoint

    projection = project_real_batch_state(
        state,
        updated_at="2026-08-23T10:00:00Z",
    )

    assert projection["checkpointSha256"] == ""


@pytest.mark.parametrize(
    ("hash_mutation", "error_pattern"),
    [
        pytest.param("missing", "hash is required", id="missing-hash"),
        pytest.param("wrong", "hash does not match", id="wrong-hash"),
    ],
)
def test_real_projection_rejects_v2_checkpoint_without_valid_outer_hash(
    monkeypatch: pytest.MonkeyPatch,
    hash_mutation: str,
    error_pattern: str,
) -> None:
    state = new_real_batch_state("real-1")
    checkpoint = state.to_checkpoint()
    if hash_mutation == "missing":
        checkpoint.pop("checkpoint_sha256")
    else:
        checkpoint["checkpoint_sha256"] = "0" * 64
    monkeypatch.setattr(state, "to_checkpoint", lambda: checkpoint)

    with pytest.raises(CatalogExecutionError, match=error_pattern):
        project_real_batch_state(
            state,
            updated_at="2026-08-23T10:00:00Z",
        )


def test_real_projection_reports_drain_rates_and_stop_reason_while_draining() -> None:
    state = new_real_batch_state("real-5")
    ids = state.plan.question_ids
    state.record_package(_package(state.scope, ids[0]))
    state.mark_running(ids[1])
    state.record_failure(ids[2], "run_failed")
    state.record_blocked(ids[3], "awaiting_human_approval:run-9")

    projection = project_real_batch_state(
        state,
        updated_at="2026-08-28T10:00:00Z",
        awaiting_approval={ids[3]: {"runId": "run-9", "since": "2026-08-28T09:00:00Z"}},
        consecutive_failures=1,
        failure_budget=3,
        cancelled=True,
        concurrency_limit=4,
    )

    assert projection["drainState"] == "draining"
    assert projection["concurrencyLimit"] == 4
    assert projection["totalCompletedCount"] == 3
    assert projection["autoClosedCount"] == 1
    assert projection["escalatedCount"] == 2
    assert projection["autoCloseRate"] == pytest.approx(1 / 3)
    assert projection["escalationRate"] == pytest.approx(2 / 3)
    assert projection["autoCloseTarget"] == pytest.approx(0.85)
    assert projection["escalationStopLine"] == pytest.approx(0.15)
    assert projection["stopReason"] == "cancelled_by_operator"
    assert projection["remainingFailureBudget"] == 2
    assert projection["canResume"] is False


def test_real_projection_reports_drained_and_failure_budget_stop_reason() -> None:
    state = new_real_batch_state("real-1")
    state.record_failure(state.plan.question_ids[0], "launch_failed: boom")

    projection = project_real_batch_state(
        state,
        updated_at="2026-08-28T10:00:00Z",
        consecutive_failures=3,
        failure_budget=3,
        cancelled=True,
    )

    assert projection["drainState"] == "drained"
    assert projection["circuitBreakerOpen"] is True
    assert projection["stopReason"] == "failure_budget_exhausted"
    assert projection["remainingFailureBudget"] == 0
    assert projection["totalCompletedCount"] == 1
    assert projection["autoClosedCount"] == 0
    assert projection["autoCloseRate"] == 0.0
    assert projection["escalationRate"] == 1.0


def test_real_projection_defaults_drain_to_none_and_rates_to_none_fresh() -> None:
    state = new_real_batch_state("real-1")

    projection = project_real_batch_state(
        state,
        updated_at="2026-08-28T10:00:00Z",
    )

    assert projection["drainState"] == "none"
    assert projection["concurrencyLimit"] is None
    assert projection["totalCompletedCount"] == 0
    assert projection["autoClosedCount"] == 0
    assert projection["escalatedCount"] == 0
    assert projection["autoCloseRate"] is None
    assert projection["escalationRate"] is None
    assert projection["stopReason"] == ""
    assert projection["remainingFailureBudget"] == 3


def test_real_projection_round_trips_through_the_wire_response_model() -> None:
    from core.web.routes.team_workflows.challenge_cup_real_batch_models import (
        ChallengeCupRealBatchProjectionResponse,
    )

    state = new_real_batch_state("real-1")
    state.mark_running(state.plan.question_ids[0])
    projection = project_real_batch_state(
        state,
        updated_at="2026-08-28T10:00:00Z",
        consecutive_failures=1,
        failure_budget=3,
        cancelled=True,
        concurrency_limit=4,
    )

    wire = ChallengeCupRealBatchProjectionResponse.model_validate(projection)
    assert wire.drainState == "draining"
    assert wire.concurrencyLimit == 4
    assert wire.stopReason == "cancelled_by_operator"
    assert wire.remainingFailureBudget == 2
    assert wire.autoCloseTarget == pytest.approx(0.85)
    assert wire.escalationStopLine == pytest.approx(0.15)
