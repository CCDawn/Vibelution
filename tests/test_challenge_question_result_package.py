from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from core.research.competition.question_result_package import (
    QuestionResultPackage,
    QuestionResultPackageError,
    canonical_model_policy,
)
from core.research.competition.result_set import CatalogScope, compute_scope_hash
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
)

DIMENSIONS = (
    "evidence_support",
    "factual_accuracy",
    "novelty",
    "falsifiability",
    "plan_feasibility",
    "risk_and_ethics",
    "counterexample_coverage",
)


def _scope() -> CatalogScope:
    return CatalogScope.from_tracked_resources()


def _model_policy(
    *,
    provider_ids: list[str] | None = None,
    model_ids: list[str] | None = None,
) -> dict:
    body = {
        "family": "qwen",
        "providerIds": provider_ids or ["dashscope"],
        "modelIds": model_ids or ["qwen3.6-plus"],
        "requireOfficialProvider": True,
    }
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {**body, "policySha256": hashlib.sha256(encoded).hexdigest()}


def _human_gate() -> dict:
    return {
        "required": True,
        "decision": "pending",
        "rationale": "Awaiting explicit human review.",
    }


def _receipt(
    scope: CatalogScope,
    *,
    stage: str,
    policy_sha256: str,
    run_id: str = "run-sci-001-r1",
) -> dict:
    receipt = ModelInvocationReceipt.from_invocation(
        receipt_id=f"receipt-{stage}",
        run_id=run_id,
        node_run_id=f"node-run-{stage}",
        scope={
            "catalogId": scope.catalog_id,
            "catalogVersion": scope.catalog_version,
            "catalogSha256": scope.catalog_sha256,
            "scopeHash": scope.scope_hash,
            "questionId": "SCI-001",
            "runId": run_id,
            "stageId": stage,
            "modelPolicySha256": policy_sha256,
        },
        provider="dashscope",
        model="qwen3.6-plus",
        model_version="2026-01",
        requested_model="qwen3.6-plus",
        status=ModelInvocationStatus.SUCCEEDED,
        request_content={"stage": stage, "questionId": "SCI-001"},
        response_content={"stage": stage, "status": "ok"},
        started_at_ms=100,
        finished_at_ms=110,
        token_usage={"inputTokens": 10, "outputTokens": 12, "totalTokens": 22},
        evidence_locator={"kind": "workflow-ledger", "ref": f"receipt://{stage}"},
    )
    return receipt.to_dict()


def _candidate(candidate_id: str, mechanism: str) -> dict:
    return {
        "hypothesis_id": candidate_id,
        "statement": f"The {candidate_id} mechanism explains the observed effect.",
        "mechanism": mechanism,
        "novelty_basis": "A measurable mechanism not tested by the baseline.",
        "falsifiability": "The mechanism predicts a directional intervention result.",
        "predictions": [f"Prediction for {candidate_id}"],
        "supporting_evidence_refs": ["evidence-1"],
        "challenging_evidence_refs": ["evidence-2"],
        "boundary_conditions": ["Only within the declared study population."],
    }


def _review(hypothesis_id: str, dimension: str) -> dict:
    return {
        "hypothesis_id": hypothesis_id,
        "dimension": dimension,
        "rating": "adequate",
        "rationale": f"Independent review for {hypothesis_id}/{dimension}.",
        "evidence_refs": ["evidence-1"],
        "reviewer": f"reviewer-{dimension}",
    }


def _valid_payload() -> dict:
    scope = _scope()
    run_id = "run-sci-001-r1"
    model_policy = _model_policy()
    hypotheses = [
        _candidate("H1", "A receptor-mediated signaling mechanism changes the response."),
        _candidate("H2", "A resource-allocation mechanism changes the response."),
    ]
    reviews = [
        _review(hypothesis["hypothesis_id"], dimension)
        for hypothesis in hypotheses
        for dimension in DIMENSIONS
    ]
    return {
        "schema_version": 2,
        "package_id": "pkg-sci-001-r1",
        "question_id": "SCI-001",
        "run_id": run_id,
        "scope": scope.to_dict(),
        "model_policy": model_policy,
        "input_snapshot_sha256": "a" * 64,
        "hypotheses": hypotheses,
        "dimension_reviews": reviews,
        "selection": {
            "selected_hypothesis_id": "H1",
            "comparison_method": "multi_dimension_pareto_plus_human_decision",
            "tradeoffs": ["H1 is more directly testable."],
            "rejected_hypotheses": [{"hypothesis_id": "H2", "reason": "Lower feasibility."}],
            "human_gate": _human_gate(),
        },
        "research_plan": {
            "objective": "Test the selected mechanism under controlled conditions.",
            "method": "Pre-registered controlled comparison.",
            "work_packages": [
                {
                    "work_package_id": "wp-1",
                    "goal": "Run the controlled comparison.",
                    "inputs": ["dataset-1"],
                    "procedure": ["Apply the pre-registered intervention."],
                    "outputs": ["effect estimate"],
                    "dependencies": ["matched baseline"],
                }
            ],
            "variables": ["intervention", "response"],
            "controls": ["matched baseline"],
            "data_and_materials": ["dataset-1"],
            "analysis": ["estimate the predeclared effect"],
            "success_criteria": ["effect direction matches prediction"],
            "failure_criteria": ["effect is absent or reversed"],
            "stop_conditions": ["safety boundary crossed"],
            "resources": ["lab allocation"],
            "timeline": ["week-1"],
            "risks": ["measurement bias"],
            "human_gate": _human_gate(),
        },
        "feedback_iterations": [
            {
                "round": 1,
                "trigger": "Independent review requested a clearer control.",
                "input_refs": ["review-1"],
                "changes": ["Added matched baseline."],
                "unresolved_issues": ["External validity remains limited."],
                "human_feedback": "Keep the study boundary explicit.",
            }
        ],
        "result_classification": {
            "status": "approved",
            "actual_execution": False,
            "classification": "proposal_only",
            "final_summary": {
                "answer_boundary": "This is a proposal, not an executed result.",
                "selected_hypothesis": "H1",
                "research_plan_summary": "Run the controlled comparison.",
                "key_evidence_refs": ["evidence-1"],
                "counterevidence_refs": ["evidence-2"],
                "limitations": ["No deep experiment has run."],
                "next_validation_step": "Approve the controlled comparison.",
            },
            "claim_boundary": "No causal claim is made before execution.",
        },
        "competition_result_view": {
            "problem_statement": "Can the selected mechanism explain the effect?",
            "rationale": "The candidate is testable and evidence-linked.",
            "technical_details": "Use the pre-registered controlled comparison.",
            "datasets": {"source": ["dataset-1"], "target": ["response"]},
            "paper_title": "A mechanism-first test",
            "paper_abstract": "A bounded proposal for later validation.",
            "methods": ["controlled comparison"],
            "experiments": ["planned experiment"],
            "results": ["not executed"],
            "references": ["evidence-1", "evidence-2"],
        },
        "model_invocation_receipts": {
            stage: _receipt(
                scope,
                stage=stage,
                policy_sha256=model_policy["policySha256"],
                run_id=run_id,
            )
            for stage in ("generation", "review", "revision")
        },
    }


def _create(payload: dict) -> QuestionResultPackage:
    scope = payload["scope"]
    if isinstance(scope, dict):
        scope = CatalogScope.from_dict(scope)
    return QuestionResultPackage.create(
        scope=scope,
        model_policy=payload["model_policy"],
        question_id=payload["question_id"],
        run_id=payload["run_id"],
        input_snapshot_sha256=payload["input_snapshot_sha256"],
        hypotheses=payload["hypotheses"],
        dimension_reviews=payload["dimension_reviews"],
        selection=payload["selection"],
        research_plan=payload["research_plan"],
        feedback_iterations=payload["feedback_iterations"],
        result_classification=payload["result_classification"],
        competition_result_view=payload["competition_result_view"],
        model_invocation_receipts=payload["model_invocation_receipts"],
        package_id=payload["package_id"],
        failure=payload.get("failure"),
    )


def test_valid_package_round_trips_with_stable_canonical_hash_and_idempotency_key() -> None:
    package = QuestionResultPackage.create(_valid_payload())

    serialized = package.to_dict()
    restored = QuestionResultPackage.from_dict(
        serialized,
        expected_model_policy_sha256=serialized["model_policy"]["policySha256"],
    )

    assert package.question_id == "SCI-001"
    assert package.run_id == "run-sci-001-r1"
    assert package.canonical_hash == restored.canonical_hash
    assert package.idempotency_key == restored.idempotency_key
    assert package.canonical_payload() == restored.canonical_payload()
    assert serialized["canonical_sha256"] == package.canonical_hash
    assert set(package.model_invocation_receipts) == {"generation", "review", "revision"}


def test_package_rejects_same_mechanism_even_when_candidate_ids_differ() -> None:
    payload = _valid_payload()
    payload["hypotheses"][1]["mechanism"] = payload["hypotheses"][0]["mechanism"].upper()

    with pytest.raises(QuestionResultPackageError, match="mechanism"):
        _create(payload)


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda p: p["model_invocation_receipts"].pop("revision"), "receipt"),
        (
            lambda p: p["model_invocation_receipts"]["review"]["scope"]["questionId"] == "SCI-096",
            "question",
        ),
        (
            lambda p: p["model_invocation_receipts"]["review"]["scope"].update({"runId": "run-other"}),
            "run",
        ),
        (
            lambda p: p["model_invocation_receipts"]["review"]["scope"].update(
                {"catalogSha256": "0" * 64}
            ),
            "scope",
        ),
    ],
)
def test_package_fails_closed_when_stage_receipt_is_incomplete(mutation, message: str) -> None:
    payload = _valid_payload()
    if message == "question":
        payload["model_invocation_receipts"]["review"]["scope"]["questionId"] = "SCI-096"
    else:
        mutation(payload)

    with pytest.raises(QuestionResultPackageError, match=message):
        _create(payload)


def test_package_rejects_non_qwen_or_unapproved_provider() -> None:
    payload = _valid_payload()
    payload["model_invocation_receipts"]["generation"]["provider"] = "offline-fake"

    with pytest.raises(QuestionResultPackageError, match="Qwen"):
        _create(payload)


def test_package_rejects_tampered_canonical_hash() -> None:
    payload = _create(_valid_payload()).to_dict()
    payload["competition_result_view"]["rationale"] = "tampered"

    with pytest.raises(QuestionResultPackageError, match="canonical"):
        QuestionResultPackage.from_dict(
            payload,
            expected_model_policy_sha256=payload["model_policy"]["policySha256"],
        )


@pytest.mark.parametrize("status", ["blocked", "failed"])
def test_failed_package_requires_explicit_failure_closure(status: str) -> None:
    payload = _valid_payload()
    payload["result_classification"]["status"] = status
    payload["result_classification"]["classification"] = status

    with pytest.raises(QuestionResultPackageError, match="failure"):
        _create(payload)


def test_idempotency_key_changes_when_input_snapshot_changes() -> None:
    first = _create(_valid_payload())
    second_payload = deepcopy(_valid_payload())
    second_payload["input_snapshot_sha256"] = "b" * 64
    second = _create(second_payload)

    assert first.idempotency_key != second.idempotency_key


def test_persisted_restore_requires_canonical_hash() -> None:
    payload = _valid_payload()
    with pytest.raises(QuestionResultPackageError, match="canonical"):
        QuestionResultPackage.from_dict(
            payload,
            expected_model_policy_sha256=payload["model_policy"]["policySha256"],
        )


@pytest.mark.parametrize("as_object", [False, True])
def test_package_rejects_self_consistent_but_non_official_catalog_scope(as_object: bool) -> None:
    payload = _valid_payload()
    custom = CatalogScope(
        catalog_id="science-125-questions-fork",
        catalog_version="2",
        catalog_sha256="0" * 64,
        scope_hash=compute_scope_hash("science-125-questions-fork", "2", "0" * 64),
    )
    payload["scope"] = custom if as_object else custom.to_dict()

    with pytest.raises(QuestionResultPackageError, match="official"):
        QuestionResultPackage.create(payload)


@pytest.mark.parametrize("field", ["receiptId", "nodeRunId"])
def test_receipt_identity_cannot_be_reused_across_stages(field: str) -> None:
    payload = _valid_payload()
    payload["model_invocation_receipts"]["review"][field] = payload[
        "model_invocation_receipts"
    ]["generation"][field]

    with pytest.raises(QuestionResultPackageError, match="unique"):
        _create(payload)


def test_receipt_stage_scope_must_match_the_stage_key() -> None:
    payload = _valid_payload()
    payload["model_invocation_receipts"]["review"]["scope"]["stageId"] = "generation"

    with pytest.raises(QuestionResultPackageError, match="stage"):
        _create(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda receipt: receipt.update({"provider": "dashscope_main"}),
        lambda receipt: receipt.update({"requestedModel": ""}),
        lambda receipt: receipt.update({"evidenceLocator": {}}),
    ],
)
def test_receipt_requires_exact_qwen_route_and_evidence(mutation) -> None:
    payload = _valid_payload()
    mutation(payload["model_invocation_receipts"]["generation"])

    with pytest.raises(QuestionResultPackageError, match="Qwen|evidence"):
        _create(payload)


def test_dimension_reviews_must_be_unique() -> None:
    payload = _valid_payload()
    payload["dimension_reviews"].append(deepcopy(payload["dimension_reviews"][0]))

    with pytest.raises(QuestionResultPackageError, match="unique"):
        _create(payload)


@pytest.mark.parametrize("field", ["rating", "rationale", "reviewer", "evidence_refs"])
def test_dimension_review_requires_complete_evidence_carrying_record(field: str) -> None:
    payload = _valid_payload()
    review = payload["dimension_reviews"][0]
    review[field] = [] if field == "evidence_refs" else ""

    with pytest.raises(QuestionResultPackageError, match=field):
        _create(payload)


@pytest.mark.parametrize("field", ["tradeoffs", "rejected_hypotheses"])
def test_selection_requires_tradeoffs_and_reasons_for_every_unselected_candidate(field: str) -> None:
    payload = _valid_payload()
    payload["selection"].pop(field)

    with pytest.raises(QuestionResultPackageError, match=field):
        _create(payload)


@pytest.mark.parametrize(
    "field",
    [
        "work_packages",
        "variables",
        "controls",
        "data_and_materials",
        "analysis",
        "success_criteria",
        "failure_criteria",
        "stop_conditions",
        "resources",
        "timeline",
        "risks",
    ],
)
def test_research_plan_requires_every_execution_field_non_empty(field: str) -> None:
    payload = _valid_payload()
    payload["research_plan"][field] = []

    with pytest.raises(QuestionResultPackageError, match=field):
        _create(payload)


@pytest.mark.parametrize(
    "field",
    ["round", "trigger", "input_refs", "changes", "unresolved_issues", "human_feedback"],
)
def test_feedback_iteration_requires_complete_revision_record(field: str) -> None:
    payload = _valid_payload()
    payload["feedback_iterations"][0].pop(field)

    with pytest.raises(QuestionResultPackageError, match=field):
        _create(payload)


def test_feedback_rounds_must_be_unique_and_strictly_increasing() -> None:
    payload = _valid_payload()
    second = deepcopy(payload["feedback_iterations"][0])
    second["trigger"] = "Second review."
    payload["feedback_iterations"].append(second)

    with pytest.raises(QuestionResultPackageError, match="round"):
        _create(payload)


@pytest.mark.parametrize(
    "classification, actual_execution",
    [("proposal_only", True), ("executed_positive", False)],
)
def test_result_classification_must_match_actual_execution(
    classification: str, actual_execution: bool
) -> None:
    payload = _valid_payload()
    payload["result_classification"].update(
        {"classification": classification, "actual_execution": actual_execution}
    )

    with pytest.raises(QuestionResultPackageError, match="actual_execution"):
        _create(payload)


def test_final_summary_must_match_selected_hypothesis() -> None:
    payload = _valid_payload()
    payload["result_classification"]["final_summary"]["selected_hypothesis"] = "H2"

    with pytest.raises(QuestionResultPackageError, match="selected_hypothesis"):
        _create(payload)


def test_executed_classification_cannot_carry_planned_result_text() -> None:
    payload = _valid_payload()
    payload["result_classification"].update(
        {"classification": "executed_positive", "actual_execution": True}
    )

    with pytest.raises(QuestionResultPackageError, match="executed|actual"):
        _create(payload)


def test_package_cannot_be_directly_constructed() -> None:
    with pytest.raises((TypeError, QuestionResultPackageError)):
        QuestionResultPackage()


def test_source_and_exposed_nested_mutation_cannot_change_canonical_content() -> None:
    source = _valid_payload()
    package = _create(source)
    original_hash = package.canonical_hash

    source["hypotheses"][0]["mechanism"] = "tampered source"
    serialized = package.to_dict()
    serialized["selection"]["selected_hypothesis_id"] = "H2"
    exposed_receipt = package.model_invocation_receipts["generation"]
    exposed_receipt.scope["questionId"] = "SCI-096"
    with pytest.raises(TypeError):
        package.hypotheses[0]["mechanism"] = "tampered package"

    assert package.canonical_hash == original_hash
    assert package.hypotheses[0]["mechanism"] != "tampered source"
    assert package.selection["selected_hypothesis_id"] == "H1"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_package_rejects_non_finite_nested_numbers(value: float) -> None:
    payload = _valid_payload()
    payload["research_plan"]["non_finite"] = value

    with pytest.raises(QuestionResultPackageError, match="finite|JSON"):
        _create(payload)


def test_package_persists_normalized_model_policy_and_receipt_binding() -> None:
    payload = _valid_payload()
    package = _create(payload)
    serialized = package.to_dict()

    assert serialized["model_policy"] == payload["model_policy"]
    assert all(
        receipt["scope"]["modelPolicySha256"]
        == payload["model_policy"]["policySha256"]
        for receipt in serialized["model_invocation_receipts"].values()
    )


def test_model_policy_normalizes_case_order_and_duplicates_before_hashing() -> None:
    payload = _valid_payload()
    canonical_policy = payload["model_policy"]
    payload["model_policy"] = {
        "family": "QWEN",
        "providerIds": ["DASHSCOPE", "dashscope"],
        "modelIds": ["QWEN3.6-PLUS", "qwen3.6-plus"],
        "requireOfficialProvider": True,
        "policySha256": canonical_policy["policySha256"],
    }

    package = _create(payload)

    assert package.to_dict()["model_policy"] == canonical_policy


def test_server_model_policy_canonicalization_is_order_and_case_stable() -> None:
    first = canonical_model_policy(
        {
            "family": "QWEN",
            "providerIds": ["DashScope", "ALIYUN", "dashscope"],
            "modelIds": ["Qwen-Plus", "qwen-plus", "Qwen-Max"],
            "requireOfficialProvider": True,
        }
    )
    second = canonical_model_policy(
        {
            "family": "qwen",
            "providerIds": ["aliyun", "dashscope"],
            "modelIds": ["qwen-max", "qwen-plus"],
            "requireOfficialProvider": True,
        }
    )

    assert first == second
    assert first["policySha256"] == _model_policy(
        provider_ids=["aliyun", "dashscope"],
        model_ids=["qwen-max", "qwen-plus"],
    )["policySha256"]


def test_model_policy_hash_participates_in_idempotency_identity() -> None:
    baseline = _create(_valid_payload())
    payload = _valid_payload()
    future_policy = _model_policy(model_ids=["qwen-future-managed"])
    payload["model_policy"] = future_policy
    for receipt in payload["model_invocation_receipts"].values():
        receipt["model"] = "qwen-future-managed"
        receipt["requestedModel"] = "qwen-future-managed"
        receipt["scope"]["modelPolicySha256"] = future_policy["policySha256"]

    future = _create(payload)

    assert future.idempotency_key != baseline.idempotency_key


def test_persisted_restore_requires_external_authorized_model_policy_hash() -> None:
    package = _create(_valid_payload())
    serialized = package.to_dict()

    with pytest.raises(TypeError):
        QuestionResultPackage.from_dict(serialized)

    restored = QuestionResultPackage.from_dict(
        serialized,
        expected_model_policy_sha256=serialized["model_policy"]["policySha256"],
    )
    assert restored.canonical_hash == package.canonical_hash


def test_self_minted_qwen_fake_policy_cannot_bypass_authorized_restore_hash() -> None:
    trusted_policy_sha256 = _valid_payload()["model_policy"]["policySha256"]
    fake_payload = _valid_payload()
    fake_policy = _model_policy(model_ids=["qwen-fake"])
    fake_payload["model_policy"] = fake_policy
    for receipt in fake_payload["model_invocation_receipts"].values():
        receipt["model"] = "qwen-fake"
        receipt["requestedModel"] = "qwen-fake"
        receipt["scope"]["modelPolicySha256"] = fake_policy["policySha256"]
    persisted = QuestionResultPackage.create(fake_payload).to_dict()

    with pytest.raises(QuestionResultPackageError, match="authorized|expected|policy"):
        QuestionResultPackage.from_dict(
            persisted,
            expected_model_policy_sha256=trusted_policy_sha256,
        )


def test_model_policy_rejects_self_modified_internal_hash() -> None:
    payload = _valid_payload()
    payload["model_policy"]["policySha256"] = "0" * 64

    with pytest.raises(QuestionResultPackageError, match="policy.*hash|hash.*policy"):
        QuestionResultPackage.create(payload)


@pytest.mark.parametrize("field, value", [("provider", "bailian"), ("model", "qwen-fake")])
def test_receipt_route_must_exactly_match_authorized_policy(field: str, value: str) -> None:
    payload = _valid_payload()
    receipt = payload["model_invocation_receipts"]["generation"]
    receipt[field] = value
    if field == "model":
        receipt["requestedModel"] = value

    with pytest.raises(QuestionResultPackageError, match="policy"):
        _create(payload)


def test_receipt_scope_must_bind_authorized_policy_hash() -> None:
    payload = _valid_payload()
    payload["model_invocation_receipts"]["review"]["scope"][
        "modelPolicySha256"
    ] = "0" * 64

    with pytest.raises(QuestionResultPackageError, match="policy"):
        _create(payload)


@pytest.mark.parametrize(
    "canonical_key, alias_key, conflicting_value",
    [
        ("stageId", "stage", "review"),
        ("stageId", "nodeId", "review"),
        ("questionId", "question", "SCI-096"),
        ("runId", "run_id", "run-other"),
        ("modelPolicySha256", "model_policy_sha256", "0" * 64),
        ("catalogId", "catalog_id", "other-catalog"),
        ("catalogVersion", "catalog_version", "other-version"),
        ("catalogSha256", "catalog_sha256", "0" * 64),
        ("scopeHash", "scope_hash", "0" * 64),
    ],
)
def test_receipt_scope_rejects_conflicting_alias_values(
    canonical_key: str,
    alias_key: str,
    conflicting_value: str,
) -> None:
    payload = _valid_payload()
    scope = payload["model_invocation_receipts"]["generation"]["scope"]
    assert canonical_key in scope
    scope[alias_key] = conflicting_value

    with pytest.raises(QuestionResultPackageError, match="conflicting.*alias"):
        _create(payload)


def test_selection_comparison_method_is_fixed() -> None:
    payload = _valid_payload()
    payload["selection"]["comparison_method"] = "aggregate_score"

    with pytest.raises(QuestionResultPackageError, match="comparison_method"):
        _create(payload)


@pytest.mark.parametrize("section", ["selection", "research_plan"])
def test_selection_and_research_plan_require_human_gate(section: str) -> None:
    payload = _valid_payload()
    payload[section].pop("human_gate")

    with pytest.raises(QuestionResultPackageError, match="human_gate"):
        _create(payload)


@pytest.mark.parametrize("section", ["selection", "research_plan"])
def test_human_gate_rejects_invalid_or_unreviewable_state(section: str) -> None:
    payload = _valid_payload()
    payload[section]["human_gate"]["required"] = False

    with pytest.raises(QuestionResultPackageError, match="human_gate"):
        _create(payload)


@pytest.mark.parametrize("section", ["selection", "research_plan"])
def test_decided_human_gate_requires_reviewer_and_timestamp(section: str) -> None:
    payload = _valid_payload()
    payload[section]["human_gate"]["decision"] = "approved"

    with pytest.raises(QuestionResultPackageError, match="reviewer|decided_at"):
        _create(payload)


@pytest.mark.parametrize(
    "field, value",
    [
        ("decision", True),
        ("rationale", 123),
        ("reviewer", False),
        ("decided_at", 123),
    ],
)
def test_human_gate_rejects_non_string_v2_fields(field: str, value: object) -> None:
    payload = _valid_payload()
    gate = payload["selection"]["human_gate"]
    gate.update(
        {
            "decision": "approved",
            "reviewer": "reviewer-1",
            "decided_at": "2026-08-23T10:00:00Z",
        }
    )
    gate[field] = value

    with pytest.raises(QuestionResultPackageError, match="must be a string"):
        _create(payload)


@pytest.mark.parametrize(
    "field",
    ["work_package_id", "goal", "inputs", "procedure", "outputs", "dependencies"],
)
def test_work_package_requires_exact_six_fields(field: str) -> None:
    payload = _valid_payload()
    payload["research_plan"]["work_packages"][0].pop(field)

    with pytest.raises(QuestionResultPackageError, match=field):
        _create(payload)


def test_work_package_rejects_junk_fields() -> None:
    payload = _valid_payload()
    payload["research_plan"]["work_packages"][0]["junk"] = "ignored"

    with pytest.raises(QuestionResultPackageError, match="junk|unsupported"):
        _create(payload)


def test_rejected_hypothesis_rejects_junk_fields() -> None:
    payload = _valid_payload()
    payload["selection"]["rejected_hypotheses"][0]["junk"] = "ignored"

    with pytest.raises(QuestionResultPackageError, match="junk|unsupported"):
        _create(payload)


def test_work_package_ids_must_be_unique() -> None:
    payload = _valid_payload()
    payload["research_plan"]["work_packages"].append(
        deepcopy(payload["research_plan"]["work_packages"][0])
    )

    with pytest.raises(QuestionResultPackageError, match="unique"):
        _create(payload)


@pytest.mark.parametrize("field", ["inputs", "procedure", "outputs", "dependencies"])
def test_work_package_lists_must_be_non_empty(field: str) -> None:
    payload = _valid_payload()
    payload["research_plan"]["work_packages"][0][field] = []

    with pytest.raises(QuestionResultPackageError, match=field):
        _create(payload)


@pytest.mark.parametrize("section", ["selection", "research_plan"])
def test_selection_and_research_plan_reject_junk_fields(section: str) -> None:
    payload = _valid_payload()
    payload[section]["junk"] = "ignored"

    with pytest.raises(QuestionResultPackageError, match="junk|unsupported"):
        _create(payload)
