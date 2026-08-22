from __future__ import annotations

import hashlib
import json

import pytest

from core.research.competition.result_set import (
    CATALOG_ID,
    CATALOG_QUESTION_COUNT,
    CATALOG_SHA256,
    CATALOG_VERSION,
    DEFAULT_TEMPLATE_VERSION,
    CatalogScope,
    FullCatalogResultSet,
    QuestionResult,
    ResultSetContractError,
    compute_scope_hash,
    is_official_question_id,
    official_question_ids,
)
from tests.test_catalog_execution_state_machine import _package


def _scope() -> CatalogScope:
    return CatalogScope.from_tracked_resources()


def _make_result(scope: CatalogScope, question_id: str, *, eligible: bool = True) -> QuestionResult:
    return QuestionResult.create(
        scope=scope,
        question_id=question_id,
        model_receipt_locator=f"model-receipt://{question_id}",
        knowledge_locator=f"knowledge://{question_id}",
        submission_eligible=eligible,
    )


def _is_hex_upper_64(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789ABCDEF" for char in value)


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


def test_scope_hash_is_stable_and_binds_catalog_identity() -> None:
    scope = _scope()
    assert scope.catalog_id == CATALOG_ID
    assert scope.catalog_version == CATALOG_VERSION
    assert scope.catalog_sha256 == CATALOG_SHA256
    assert _is_hex_upper_64(scope.scope_hash)
    assert scope.scope_hash == compute_scope_hash()
    assert compute_scope_hash(catalog_id="other") != scope.scope_hash
    assert compute_scope_hash(catalog_version="2") != scope.scope_hash
    assert compute_scope_hash(catalog_sha256="0" * 64) != scope.scope_hash


def test_official_question_ids_are_unique_and_ordered() -> None:
    ids = official_question_ids()
    assert len(ids) == CATALOG_QUESTION_COUNT
    assert len(set(ids)) == CATALOG_QUESTION_COUNT
    assert ids == tuple(f"SCI-{index:03d}" for index in range(1, CATALOG_QUESTION_COUNT + 1))
    assert is_official_question_id("SCI-001")
    assert is_official_question_id("SCI-125")
    assert not is_official_question_id("SCI-000")
    assert not is_official_question_id("SCI-126")
    assert not is_official_question_id("001")


def test_legacy_full_result_set_sorts_and_binds_identity_but_is_not_formal_ready() -> None:
    scope = _scope()
    result_set = FullCatalogResultSet(scope=scope)
    for question_id in official_question_ids():
        result_set.add_result(_make_result(scope, question_id))

    results = result_set.results()
    assert [result.question_id for result in results] == list(official_question_ids())
    assert result_set.present_count() == CATALOG_QUESTION_COUNT
    assert result_set.missing_count() == 0
    for result in results:
        assert result.catalog_id == CATALOG_ID
        assert result.catalog_version == CATALOG_VERSION
        assert result.scope_hash == scope.scope_hash
        assert result.model_receipt_locator == f"model-receipt://{result.question_id}"
        assert result.knowledge_locator == f"knowledge://{result.question_id}"
        assert result.template_version == DEFAULT_TEMPLATE_VERSION
        assert result.submission_eligible is True

    assert result_set.is_submission_ready() is False
    assert result_set.submission_state()["package_backed_count"] == 0
    counts = result_set.export_counts()
    assert counts["present_count"] == CATALOG_QUESTION_COUNT
    assert counts["missing_count"] == 0
    assert counts["submission_eligible_count"] == CATALOG_QUESTION_COUNT
    assert counts["submission_ready"] is False


def test_124_results_are_not_submission_ready() -> None:
    scope = _scope()
    result_set = FullCatalogResultSet(scope=scope)
    for question_id in official_question_ids()[:124]:
        result_set.add_result(_make_result(scope, question_id))

    assert result_set.present_count() == 124
    assert result_set.missing_count() == 1
    state = result_set.submission_state()
    assert state["submission_ready"] is False
    assert "present_count_124_required_125" in state["reasons"]
    assert state["missing_count"] == 1
    assert result_set.is_submission_ready() is False
    with pytest.raises(ResultSetContractError, match="not submission-ready"):
        result_set.assert_submission_ready()


def test_126th_result_is_rejected_and_checkpoint_duplicate_is_rejected() -> None:
    scope = _scope()
    result_set = FullCatalogResultSet(scope=scope)
    for question_id in official_question_ids():
        result_set.add_result(_make_result(scope, question_id))

    with pytest.raises(ResultSetContractError, match="Duplicate result"):
        result_set.add_result(_make_result(scope, "SCI-001"))
    assert result_set.present_count() == CATALOG_QUESTION_COUNT
    assert result_set.duplicate_count() == 1
    assert result_set.is_submission_ready() is False
    assert "duplicate_attempts_1" in result_set.submission_state()["reasons"]

    payload = result_set.to_checkpoint()
    payload["results"].append(payload["results"][0])
    _rehash_checkpoint(payload)
    with pytest.raises(ResultSetContractError, match="Duplicate result"):
        FullCatalogResultSet.from_checkpoint(payload)


def test_all_125_present_but_not_all_eligible_is_not_submission_ready() -> None:
    scope = _scope()
    result_set = FullCatalogResultSet(scope=scope)
    for index, question_id in enumerate(official_question_ids()):
        result_set.add_result(_make_result(scope, question_id, eligible=index != 0))

    assert result_set.present_count() == CATALOG_QUESTION_COUNT
    assert result_set.eligible_count() == 124
    assert result_set.non_eligible_question_ids() == ("SCI-001",)
    state = result_set.submission_state()
    assert state["submission_ready"] is False
    assert "submission_eligible_count_124_required_125" in state["reasons"]
    assert result_set.is_submission_ready() is False
    with pytest.raises(ResultSetContractError, match="not submission-ready"):
        result_set.assert_submission_ready()


def test_non_official_question_result_is_rejected() -> None:
    scope = _scope()
    with pytest.raises(ResultSetContractError, match="Not an official catalog question"):
        _make_result(scope, "SCI-999")
    with pytest.raises(ResultSetContractError, match="Not an official catalog question"):
        QuestionResult.from_dict(
            {
                "question_id": "SCI-126",
                "catalog_id": CATALOG_ID,
                "catalog_version": CATALOG_VERSION,
                "scope_hash": scope.scope_hash,
                "model_receipt_locator": "m",
                "knowledge_locator": "k",
                "template_version": DEFAULT_TEMPLATE_VERSION,
            }
        )


def test_locator_identity_requires_question_id_and_full_scope_hash() -> None:
    scope = _scope()
    other_scope = CatalogScope(
        catalog_id=CATALOG_ID,
        catalog_version=CATALOG_VERSION,
        catalog_sha256=CATALOG_SHA256,
        scope_hash="B" * 64,
    )
    locator_a = scope.locator_for("SCI-001")
    locator_b = other_scope.locator_for("SCI-001")
    assert locator_a.identity_key() == ("SCI-001", scope.scope_hash)
    assert locator_a.identity_key() != locator_b.identity_key()
    assert not locator_a.matches(locator_b)
    assert locator_a.cache_key() != locator_b.cache_key()
    assert _is_hex_upper_64(locator_a.cache_key())

    result_set = FullCatalogResultSet(scope=scope)
    result_set.add_result(_make_result(scope, "SCI-001"))
    assert result_set.has_result("SCI-001")
    with pytest.raises(ResultSetContractError, match="scope hash"):
        result_set.add_result(
            QuestionResult.create(
                scope=other_scope,
                question_id="SCI-002",
                model_receipt_locator="m",
                knowledge_locator="k",
            )
        )


def test_result_set_checkpoint_round_trip() -> None:
    scope = _scope()
    result_set = FullCatalogResultSet(scope=scope)
    for question_id in official_question_ids():
        result_set.add_result(_make_result(scope, question_id))

    restored = FullCatalogResultSet.from_checkpoint(result_set.to_checkpoint())
    assert restored.present_count() == CATALOG_QUESTION_COUNT
    assert [result.question_id for result in restored.results()] == list(official_question_ids())
    assert restored.scope_hash == scope.scope_hash
    assert restored.is_submission_ready() is False
    assert restored.export_counts() == result_set.export_counts()

    partial = FullCatalogResultSet(scope=scope)
    partial.add_result(_make_result(scope, "SCI-001"))
    restored_partial = FullCatalogResultSet.from_checkpoint(partial.to_checkpoint())
    assert restored_partial.present_count() == 1
    assert restored_partial.is_submission_ready() is False


def test_submission_requires_package_backed_quality_and_human_gate_evidence() -> None:
    scope = _scope()
    result_set = FullCatalogResultSet(scope=scope)
    for question_id in official_question_ids():
        result_set.add_result(QuestionResult.from_package(_package(scope, question_id)))

    state = result_set.assert_submission_ready()
    manifest = result_set.manifest()

    assert state["package_backed_count"] == CATALOG_QUESTION_COUNT
    assert state["human_gate_approved_count"] == CATALOG_QUESTION_COUNT
    assert state["receipt_complete_count"] == CATALOG_QUESTION_COUNT
    assert len(manifest["entries"]) == CATALOG_QUESTION_COUNT
    assert len(manifest["manifest_sha256"]) == 64
    assert manifest == result_set.manifest()
    assert set(manifest["entries"][0]["receipts"]) == {
        "generation",
        "review",
        "revision",
    }
    assert "package" not in manifest["entries"][0]
    changed = FullCatalogResultSet(scope=scope)
    changed.add_result(
        QuestionResult.from_package(
            _package(
                scope,
                "SCI-001",
                input_snapshot_sha256="b" * 64,
            )
        )
    )
    baseline = FullCatalogResultSet(scope=scope)
    baseline.add_result(QuestionResult.from_package(_package(scope, "SCI-001")))
    assert changed.manifest()["manifest_sha256"] != baseline.manifest()[
        "manifest_sha256"
    ]


def test_manifest_receipt_locator_projects_only_stable_identity_fields() -> None:
    scope = _scope()
    package = _package(
        scope,
        "SCI-001",
        evidence_locator_extras={
            "evidenceId": "evidence-001",
            "outputRef": "artifact://generation-output",
            "outputSha256": "b" * 64,
            "fullContent": "must never enter the identity manifest",
            "freeForm": {"nested": "must also stay out"},
        },
    )
    result_set = FullCatalogResultSet(scope=scope)
    result_set.add_result(QuestionResult.from_package(package))

    receipt = result_set.manifest()["entries"][0]["receipts"]["generation"]
    assert receipt["evidence_locator"] == {
        "kind": "workflow-ledger",
        "evidenceId": "evidence-001",
        "outputRef": "artifact://generation-output",
        "outputSha256": "b" * 64,
        "ref": "receipt://generation",
    }
    assert len(receipt["evidence_locator_sha256"]) == 64
    assert "fullContent" not in json.dumps(receipt, ensure_ascii=False)
    assert "freeForm" not in json.dumps(receipt, ensure_ascii=False)


def test_manifest_rejects_receipt_locator_without_stable_identity() -> None:
    scope = _scope()
    package = _package(
        scope,
        "SCI-001",
        evidence_locator_override={
            "fullContent": "free-form content is not a stable locator identity",
            "metadata": {"path": "mutable/path"},
        },
    )
    result_set = FullCatalogResultSet(scope=scope)
    result_set.add_result(QuestionResult.from_package(package))

    with pytest.raises(ResultSetContractError, match="stable identity"):
        result_set.manifest()


def test_legacy_or_pending_gate_results_cannot_be_submission_ready() -> None:
    scope = _scope()
    legacy = FullCatalogResultSet(scope=scope)
    pending = FullCatalogResultSet(scope=scope)
    for question_id in official_question_ids():
        legacy.add_result(_make_result(scope, question_id))
        pending.add_result(
            QuestionResult.from_package(
                _package(scope, question_id, gate_decision="pending")
            )
        )

    assert legacy.is_submission_ready() is False
    assert "package_backed_count_0_required_125" in legacy.submission_state()["reasons"]
    assert pending.is_submission_ready() is False
    assert pending.submission_state()["human_gate_approved_count"] == 0


def test_package_result_set_checkpoint_requires_policy_and_detects_tampering() -> None:
    scope = _scope()
    package = _package(scope, "SCI-001")
    result_set = FullCatalogResultSet(scope=scope)
    result_set.add_result(QuestionResult.from_package(package))
    checkpoint = result_set.to_checkpoint()

    assert checkpoint["schema_version"] == 2
    with pytest.raises(ResultSetContractError, match="authorized model policy"):
        FullCatalogResultSet.from_checkpoint(checkpoint)
    restored = FullCatalogResultSet.from_checkpoint(
        checkpoint,
        expected_model_policy_sha256=package.model_policy["policySha256"],
    )
    assert restored.get_result("SCI-001").package_snapshot == package.to_dict()
    checkpoint["results"][0]["package"]["competition_result_view"]["rationale"] = (
        "tampered"
    )
    with pytest.raises(ResultSetContractError, match="checkpoint hash"):
        FullCatalogResultSet.from_checkpoint(
            checkpoint,
            expected_model_policy_sha256=package.model_policy["policySha256"],
        )
    layered_tamper = result_set.to_checkpoint()
    layered_tamper["results"][0]["package"]["competition_result_view"][
        "rationale"
    ] = "tampered and outer hash recomputed"
    _rehash_checkpoint(layered_tamper)
    with pytest.raises(ResultSetContractError, match="canonical validation"):
        FullCatalogResultSet.from_checkpoint(
            layered_tamper,
            expected_model_policy_sha256=package.model_policy["policySha256"],
        )
