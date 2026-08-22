from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from core.research.competition.catalog_execution import (
    CatalogExecutionError,
    CatalogExecutionState,
    QuestionBlockedError,
    QuestionStatus,
    build_result_set,
    dev_plan,
    dev_plans,
    run_pending_batch,
)
from core.research.competition.question_result_package import QuestionResultPackage
from core.research.competition.result_set import (
    CATALOG_ID,
    CATALOG_QUESTION_COUNT,
    CatalogScope,
    QuestionResult,
    ResultSetContractError,
    official_question_ids,
)
from tests.test_challenge_question_result_package import _valid_payload


def _scope() -> CatalogScope:
    return CatalogScope.from_tracked_resources()


def _result(scope: CatalogScope, question_id: str) -> QuestionResult:
    return QuestionResult.create(
        scope=scope,
        question_id=question_id,
        model_receipt_locator=f"model-receipt://{question_id}",
        knowledge_locator=f"knowledge://{question_id}",
    )


def _rehash_checkpoint(payload: dict) -> None:
    body = {key: value for key, value in payload.items() if key != "checkpoint_sha256"}
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    payload["checkpoint_sha256"] = hashlib.sha256(encoded).hexdigest().upper()


def _package(
    scope: CatalogScope,
    question_id: str,
    *,
    gate_decision: str = "approved",
    quality_status: str = "approved",
    input_snapshot_sha256: str = "a" * 64,
) -> QuestionResultPackage:
    payload = deepcopy(_valid_payload())
    run_id = f"run-{question_id.lower()}-r1"
    payload.update(
        {
            "package_id": f"pkg-{question_id.lower()}-r1",
            "question_id": question_id,
            "run_id": run_id,
            "scope": scope.to_dict(),
            "input_snapshot_sha256": input_snapshot_sha256,
        }
    )
    for section in ("selection", "research_plan"):
        gate = payload[section]["human_gate"]
        gate["decision"] = gate_decision
        if gate_decision == "pending":
            gate.pop("reviewer", None)
            gate.pop("decided_at", None)
        else:
            gate["reviewer"] = "reviewer-1"
            gate["decided_at"] = "2026-08-23T10:00:00Z"
    classification = payload["result_classification"]
    classification["status"] = quality_status
    if quality_status in {"blocked", "failed"}:
        classification["classification"] = quality_status
        payload["failure"] = {
            "stage": "revision",
            "code": f"package_{quality_status}",
            "message": f"Package closed as {quality_status}.",
            "retryable": True,
        }
    else:
        payload.pop("failure", None)
    for stage, receipt in payload["model_invocation_receipts"].items():
        receipt["receiptId"] = f"receipt-{question_id.lower()}-{stage}"
        receipt["nodeRunId"] = f"node-{question_id.lower()}-{stage}"
        receipt["runId"] = run_id
        receipt["scope"].update(
            {
                "questionId": question_id,
                "runId": run_id,
                "catalogId": scope.catalog_id,
                "catalogVersion": scope.catalog_version,
                "catalogSha256": scope.catalog_sha256,
                "scopeHash": scope.scope_hash,
            }
        )
    return QuestionResultPackage.create(payload)


def test_dev_plans_cover_0_1_5_12_125() -> None:
    plans = {plan.plan_id: plan for plan in dev_plans()}
    assert set(plans) == {"dev-0", "dev-1", "dev-5", "dev-12", "dev-125"}
    assert plans["dev-0"].question_ids == ()
    assert plans["dev-1"].question_ids == ("SCI-091",)
    assert plans["dev-5"].question_ids == (
        "SCI-091",
        "SCI-096",
        "SCI-002",
        "SCI-020",
        "SCI-056",
    )
    assert len(plans["dev-12"].question_ids) == 12
    assert len(set(plans["dev-12"].question_ids)) == 12
    assert len(plans["dev-125"].question_ids) == CATALOG_QUESTION_COUNT
    assert plans["dev-125"].question_ids == official_question_ids()
    for plan in plans.values():
        assert all(question_id in official_question_ids() for question_id in plan.question_ids)
    with pytest.raises(CatalogExecutionError, match="Unknown DEV plan"):
        dev_plan("dev-7")


def test_resume_only_reruns_pending_or_invalidated() -> None:
    scope = _scope()
    plan = dev_plan("dev-5")
    state = CatalogExecutionState(plan=plan, scope=scope)
    assert state.pending_question_ids() == plan.question_ids
    assert state.pending_question_ids() == state.pending_question_ids()

    state.mark_running("SCI-091")
    state.record_success("SCI-091", _result(scope, "SCI-091"))
    state.record_failure("SCI-002", "model timeout")
    state.record_blocked("SCI-020", "resource unavailable")
    assert state.pending_question_ids() == ("SCI-096", "SCI-056")
    assert state.pending_question_ids() == ("SCI-096", "SCI-056")


def test_failed_or_blocked_requires_explicit_invalidation_to_rerun() -> None:
    scope = _scope()
    plan = dev_plan("dev-5")
    state = CatalogExecutionState(plan=plan, scope=scope)
    state.mark_running("SCI-091")
    state.record_success("SCI-091", _result(scope, "SCI-091"))
    state.record_failure("SCI-002", "boom")
    state.record_blocked("SCI-020", "blocked")
    assert state.pending_question_ids() == ("SCI-096", "SCI-056")

    state.invalidate("SCI-002", "retry after infra fix")
    state.invalidate("SCI-091", "explicit re-run of a succeeded item")
    assert state.pending_question_ids() == ("SCI-091", "SCI-096", "SCI-002", "SCI-056")


def test_interrupted_running_is_rerun_on_resume() -> None:
    scope = _scope()
    plan = dev_plan("dev-1")
    state = CatalogExecutionState(plan=plan, scope=scope)
    state.mark_running("SCI-091")
    assert state.pending_question_ids() == ("SCI-091",)


def test_single_failure_or_block_does_not_pollute_other_questions() -> None:
    scope = _scope()
    plan = dev_plan("dev-5")
    state = CatalogExecutionState(plan=plan, scope=scope)

    def execute(question_id: str) -> QuestionResult:
        if question_id == "SCI-002":
            raise RuntimeError("flaky model call")
        if question_id == "SCI-020":
            raise QuestionBlockedError("no budget for this question")
        return _result(scope, question_id)

    summary = run_pending_batch(state, execute)
    assert summary["attempted"] == list(plan.question_ids)
    assert {item["question_id"]: item["outcome"] for item in summary["outcomes"]} == {
        "SCI-091": "succeeded",
        "SCI-096": "succeeded",
        "SCI-002": "failed",
        "SCI-020": "blocked",
        "SCI-056": "succeeded",
    }
    assert summary["summary"]["succeeded"] == 3
    assert summary["summary"]["failed"] == 1
    assert summary["summary"]["blocked"] == 1
    assert state.status("SCI-002") is QuestionStatus.FAILED
    assert state.status("SCI-020") is QuestionStatus.BLOCKED
    assert state.status("SCI-091") is QuestionStatus.SUCCEEDED
    assert state.pending_question_ids() == ()


def test_rerunning_batch_after_partial_progress_is_idempotent() -> None:
    scope = _scope()
    plan = dev_plan("dev-5")
    state = CatalogExecutionState(plan=plan, scope=scope)
    first = run_pending_batch(state, lambda question_id: _result(scope, question_id))
    assert first["attempted"] == list(plan.question_ids)
    second = run_pending_batch(state, lambda question_id: _result(scope, question_id))
    assert second["attempted"] == []
    assert state.outcome_summary()["succeeded"] == 5


def test_invalidate_then_rerun_increments_attempts() -> None:
    scope = _scope()
    plan = dev_plan("dev-1")
    state = CatalogExecutionState(plan=plan, scope=scope)
    run_pending_batch(state, lambda question_id: _result(scope, question_id))
    assert state.attempts("SCI-091") == 1
    state.invalidate("SCI-091", "explicit re-run requested")
    assert state.pending_question_ids() == ("SCI-091",)
    run_pending_batch(state, lambda question_id: _result(scope, question_id))
    assert state.attempts("SCI-091") == 2
    assert state.status("SCI-091") is QuestionStatus.SUCCEEDED
    assert state.pending_question_ids() == ()


def test_checkpoint_round_trip_preserves_resume_semantics() -> None:
    scope = _scope()
    plan = dev_plan("dev-12")
    state = CatalogExecutionState(plan=plan, scope=scope)
    for question_id in plan.question_ids[:5]:
        state.mark_running(question_id)
        state.record_success(question_id, _result(scope, question_id))
    state.record_failure("SCI-034", "crashed")
    state.mark_running("SCI-080")
    pending_before = state.pending_question_ids()

    restored = CatalogExecutionState.from_checkpoint(state.to_checkpoint())
    assert restored.pending_question_ids() == pending_before
    assert restored.status("SCI-034") is QuestionStatus.FAILED
    assert restored.status("SCI-080") is QuestionStatus.RUNNING
    assert restored.status("SCI-087") is QuestionStatus.PENDING
    assert restored.attempts("SCI-080") == 1
    assert restored.plan == plan


def test_checkpoint_identity_requires_question_id_and_full_scope_hash() -> None:
    scope = _scope()
    plan = dev_plan("dev-1")
    state = CatalogExecutionState(plan=plan, scope=scope)
    state.mark_running("SCI-091")
    state.record_success("SCI-091", _result(scope, "SCI-091"))

    assert state.result_cache_key("SCI-091") == scope.locator_for("SCI-091").cache_key()

    payload = state.to_checkpoint()
    payload["records"][0]["result"]["scope_hash"] = "E" * 64
    _rehash_checkpoint(payload)
    with pytest.raises(CatalogExecutionError, match="scope hash"):
        CatalogExecutionState.from_checkpoint(payload)

    payload = state.to_checkpoint()
    payload["records"][0]["result"]["question_id"] = "SCI-096"
    _rehash_checkpoint(payload)
    with pytest.raises(CatalogExecutionError, match="question id"):
        CatalogExecutionState.from_checkpoint(payload)


def test_result_with_mismatched_scope_is_rejected_on_success() -> None:
    scope = _scope()
    other_scope = CatalogScope(
        catalog_id=CATALOG_ID,
        catalog_version="1",
        catalog_sha256="0" * 64,
        scope_hash="C" * 64,
    )
    plan = dev_plan("dev-1")
    state = CatalogExecutionState(plan=plan, scope=scope)
    with pytest.raises(CatalogExecutionError, match="does not match"):
        state.record_success("SCI-091", _result(other_scope, "SCI-091"))


def test_full_dev_125_state_builds_submission_ready_result_set() -> None:
    scope = _scope()
    plan = dev_plan("dev-125")
    state = CatalogExecutionState(plan=plan, scope=scope)
    run_pending_batch(
        state,
        lambda question_id: QuestionResult.from_package(_package(scope, question_id)),
    )
    result_set = build_result_set(state)
    assert result_set.present_count() == CATALOG_QUESTION_COUNT
    assert [result.question_id for result in result_set.results()] == list(official_question_ids())
    assert result_set.is_submission_ready()
    assert result_set.assert_submission_ready()["submission_ready"] is True


def test_124_of_125_succeeded_is_not_submission_ready() -> None:
    scope = _scope()
    plan = dev_plan("dev-125")
    state = CatalogExecutionState(plan=plan, scope=scope)

    def execute(question_id: str) -> QuestionResult:
        if question_id == "SCI-001":
            raise RuntimeError("failure")
        return _result(scope, question_id)

    run_pending_batch(state, execute)
    result_set = build_result_set(state)
    assert result_set.present_count() == 124
    assert result_set.missing_count() == 1
    assert result_set.is_submission_ready() is False
    with pytest.raises(ResultSetContractError, match="not submission-ready"):
        result_set.assert_submission_ready()


@pytest.mark.parametrize(
    ("gate_decision", "quality_status", "expected_status"),
    [
        ("pending", "approved", QuestionStatus.RUNNING),
        ("approved", "approved", QuestionStatus.SUCCEEDED),
        ("rejected", "approved", QuestionStatus.BLOCKED),
        ("revision_requested", "approved", QuestionStatus.BLOCKED),
        ("approved", "blocked", QuestionStatus.BLOCKED),
        ("approved", "failed", QuestionStatus.FAILED),
    ],
)
def test_package_quality_and_human_gates_map_to_existing_states(
    gate_decision: str,
    quality_status: str,
    expected_status: QuestionStatus,
) -> None:
    scope = _scope()
    state = CatalogExecutionState(plan=dev_plan("dev-1"), scope=scope)
    package = _package(
        scope,
        "SCI-091",
        gate_decision=gate_decision,
        quality_status=quality_status,
    )

    state.record_package(package)

    assert state.status("SCI-091") is expected_status
    assert state.result_for("SCI-091") is not None
    assert state.result_for("SCI-091").package_snapshot == package.to_dict()


def test_package_checkpoint_requires_hash_and_external_policy_authority() -> None:
    scope = _scope()
    state = CatalogExecutionState(plan=dev_plan("dev-1"), scope=scope)
    package = _package(scope, "SCI-091")
    state.record_package(package)

    checkpoint = state.to_checkpoint()

    assert checkpoint["schema_version"] == 2
    assert len(checkpoint["checkpoint_sha256"]) == 64
    with pytest.raises(CatalogExecutionError, match="authorized model policy"):
        CatalogExecutionState.from_checkpoint(checkpoint)
    with pytest.raises(CatalogExecutionError, match="authorized model policy"):
        CatalogExecutionState.from_checkpoint(
            checkpoint,
            expected_model_policy_sha256="0" * 64,
        )
    restored = CatalogExecutionState.from_checkpoint(
        checkpoint,
        expected_model_policy_sha256=package.model_policy["policySha256"],
    )
    assert restored.status("SCI-091") is QuestionStatus.SUCCEEDED
    tampered = deepcopy(checkpoint)
    tampered["records"][0]["result"]["package"]["package_id"] = "pkg-tampered"
    with pytest.raises(CatalogExecutionError, match="checkpoint hash"):
        CatalogExecutionState.from_checkpoint(
            tampered,
            expected_model_policy_sha256=package.model_policy["policySha256"],
        )


def test_failed_package_checkpoint_preserves_explicit_invalidation_recovery() -> None:
    scope = _scope()
    state = CatalogExecutionState(plan=dev_plan("dev-1"), scope=scope)
    package = _package(scope, "SCI-091", quality_status="failed")
    state.record_package(package)

    restored = CatalogExecutionState.from_checkpoint(
        state.to_checkpoint(),
        expected_model_policy_sha256=package.model_policy["policySha256"],
    )

    assert restored.status("SCI-091") is QuestionStatus.FAILED
    assert restored.pending_question_ids() == ()
    assert restored.result_for("SCI-091").package_snapshot["failure"]["retryable"] is True
    restored.invalidate("SCI-091", "retry after fixing the failed stage")
    assert restored.pending_question_ids() == ("SCI-091",)
