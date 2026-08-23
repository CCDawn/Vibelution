from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace

import pytest

from core.research.competition.catalog_hypothesis_flow_ready import (
    build_catalog_hypothesis_flow_readiness_report,
)
from core.research.competition.resources import (
    CATALOG_POLICY_VERSION,
    CORE_BEHAVIOR_HASH,
    CORE_POLICY_HASH,
    PROGRAM_CONTRACT_VERSION,
)
from core.research.competition.result_set import (
    CatalogScope,
    FullCatalogResultSet,
    QuestionResult,
    ResultSetContractError,
    compute_scope_hash,
    official_question_ids,
)
from core.research.workflow.contracts._validation import ContractValidationError
from core.research.workflow.contracts.catalog_hypothesis_flow_readiness import (
    CATALOG_HYPOTHESIS_FLOW_EVIDENCE_IDS,
    CATALOG_HYPOTHESIS_FLOW_REPAIR_ACTION,
    RESEARCH_AUTHORIZATION_REQUIRED_ACTION,
    CatalogHypothesisFlowReadinessAuthority,
    CatalogHypothesisFlowReadinessReport,
    catalog_hypothesis_flow_report_hash,
)
from tests.test_catalog_execution_state_machine import _package

GENERATED_AT = "2026-08-23T00:00:00Z"
SOURCE_COMMIT = "a" * 40


def _evidence() -> dict[str, dict[str, str]]:
    return {
        evidence_id: {
            "status": "PASS",
            "locator": f"evidence://catalog-readiness/{evidence_id}/1",
        }
        for evidence_id in CATALOG_HYPOTHESIS_FLOW_EVIDENCE_IDS
    }


def _program_contract(**overrides: str) -> dict[str, str]:
    return {
        "version": PROGRAM_CONTRACT_VERSION,
        "coreBehaviorHash": CORE_BEHAVIOR_HASH,
        **overrides,
    }


def _catalog_policy(**overrides: str) -> dict[str, str]:
    return {
        "version": CATALOG_POLICY_VERSION,
        "corePolicyHash": CORE_POLICY_HASH,
        **overrides,
    }


@pytest.fixture(scope="module")
def complete_result_set() -> FullCatalogResultSet:
    scope = CatalogScope.from_tracked_resources()
    result_set = FullCatalogResultSet(scope=scope)
    for question_id in official_question_ids():
        result_set.add_result(QuestionResult.from_package(_package(scope, question_id)))
    return result_set


def _model_policy_sha256(result_set: FullCatalogResultSet) -> str:
    result = result_set.get_result("SCI-001")
    assert result is not None and result.package_snapshot is not None
    return str(result.package_snapshot["model_policy"]["policySha256"])


def _authority(
    result_set: FullCatalogResultSet,
) -> CatalogHypothesisFlowReadinessAuthority:
    return CatalogHypothesisFlowReadinessAuthority.from_result_set(
        result_set,
        source_commit=SOURCE_COMMIT,
        program_contract=_program_contract(),
        catalog_policy=_catalog_policy(),
        model_policy_sha256=_model_policy_sha256(result_set),
    )


def _rebound_attacker_result_set(
    result_set: FullCatalogResultSet,
) -> FullCatalogResultSet:
    attacker_scope = CatalogScope(
        catalog_id="attacker-catalog",
        catalog_version="999",
        catalog_sha256="0" * 64,
        scope_hash=compute_scope_hash(
            "attacker-catalog",
            "999",
            "0" * 64,
        ),
    )
    rebound = FullCatalogResultSet(scope=attacker_scope)
    for result in result_set.results():
        rebound.add_result(
            replace(result, locator=attacker_scope.locator_for(result.question_id))
        )
    return rebound


def _build(
    result_set: FullCatalogResultSet,
    *,
    generated_at: str = GENERATED_AT,
    model_policy_sha256: str | None = None,
    source_commit: str = SOURCE_COMMIT,
    program_contract: dict[str, str] | None = None,
    catalog_policy: dict[str, str] | None = None,
    evidence: dict[str, dict[str, str]] | None = None,
) -> dict:
    return build_catalog_hypothesis_flow_readiness_report(
        result_set,
        model_policy_sha256=(
            _model_policy_sha256(result_set)
            if model_policy_sha256 is None
            else model_policy_sha256
        ),
        source_commit=source_commit,
        program_contract=program_contract or _program_contract(),
        catalog_policy=catalog_policy or _catalog_policy(),
        evidence=_evidence() if evidence is None else evidence,
        generated_at=generated_at,
    )


def _rehash_report(report: dict) -> None:
    manifest = report["catalogResultSet"]["resultManifest"]
    manifest_body = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            manifest_body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest().upper()
    report["readinessReportSha256"] = catalog_hypothesis_flow_report_hash(report)


def test_ready_requires_all_125_canonical_packages_and_preserves_boundary(
    complete_result_set: FullCatalogResultSet,
) -> None:
    report = _build(complete_result_set)

    assert report["status"] == "READY"
    assert report["researchAuthorizationRequired"] is True
    assert report["realCampaignAllowed"] is False
    assert report["nextLegalAction"] == RESEARCH_AUTHORIZATION_REQUIRED_ACTION
    assert len(report["readinessReportSha256"]) == 64
    assert "reportHash" not in report
    assert report["catalogResultSet"]["counts"]["present_count"] == 125
    assert report["catalogResultSet"]["counts"]["required_question_count"] == 125
    assert report["catalogResultSet"]["counts"]["package_backed_count"] == 125
    assert report["catalogResultSet"]["counts"]["quality_approved_count"] == 125
    assert report["catalogResultSet"]["selectionApprovedCount"] == 125
    assert report["catalogResultSet"]["researchPlanApprovedCount"] == 125
    assert report["catalogResultSet"]["receiptCompleteCount"] == 125
    assert len(report["catalogResultSet"]["resultManifest"]["entries"]) == 125
    assert report["blockers"] == []


@pytest.mark.parametrize(
    "mutation",
    (
        "schema_version",
        "required_question_count",
        "question_order",
        "quality_status",
        "human_gate",
        "package_empty",
        "package_duplicate",
        "run_empty",
        "run_duplicate",
        "idempotency_empty",
        "idempotency_duplicate",
        "receipt_missing",
        "receipt_empty",
        "node_run_empty",
        "locator_empty",
        "locator_hash",
        "receipt_duplicate",
    ),
)
def test_ready_manifest_rejects_rehashed_semantic_tampering(
    complete_result_set: FullCatalogResultSet,
    mutation: str,
) -> None:
    report = deepcopy(_build(complete_result_set))
    manifest = report["catalogResultSet"]["resultManifest"]
    entries = manifest["entries"]
    first = entries[0]
    second = entries[1]
    if mutation == "schema_version":
        manifest["schema_version"] = 99
    elif mutation == "required_question_count":
        manifest["required_question_count"] = 124
    elif mutation == "question_order":
        first["question_id"] = "SCI-002"
    elif mutation == "quality_status":
        first["quality_status"] = "blocked"
    elif mutation == "human_gate":
        first["human_gate_decisions"]["selection"] = "rejected"
    elif mutation == "package_empty":
        first["package_id"] = ""
    elif mutation == "package_duplicate":
        second["package_id"] = first["package_id"]
    elif mutation == "run_empty":
        first["run_id"] = ""
    elif mutation == "run_duplicate":
        second["run_id"] = first["run_id"]
    elif mutation == "idempotency_empty":
        first["idempotency_key"] = ""
    elif mutation == "idempotency_duplicate":
        second["idempotency_key"] = first["idempotency_key"]
    elif mutation == "receipt_missing":
        first["receipts"].pop("revision")
    elif mutation == "receipt_empty":
        first["receipts"]["generation"]["receipt_id"] = ""
    elif mutation == "node_run_empty":
        first["receipts"]["generation"]["node_run_id"] = ""
    elif mutation == "locator_empty":
        first["receipts"]["generation"]["evidence_locator"] = {}
    elif mutation == "locator_hash":
        first["receipts"]["generation"]["evidence_locator_sha256"] = "0" * 64
    elif mutation == "receipt_duplicate":
        second["receipts"]["generation"]["receipt_id"] = first["receipts"][
            "generation"
        ]["receipt_id"]
    else:
        raise AssertionError(f"Unhandled mutation: {mutation}")

    _rehash_report(report)
    with pytest.raises(ContractValidationError):
        CatalogHypothesisFlowReadinessReport.from_dict(
            report,
            trusted_authority=_authority(complete_result_set),
        )


@pytest.mark.parametrize("mutation", ("catalog_id", "catalog_version", "scope_hash"))
def test_ready_rejects_rehashed_catalog_scope_tampering(
    complete_result_set: FullCatalogResultSet,
    mutation: str,
) -> None:
    report = deepcopy(_build(complete_result_set))
    catalog = report["catalogResultSet"]
    scope = catalog["resultManifest"]["scope"]
    if mutation == "catalog_id":
        catalog["catalogId"] = "tampered-catalog"
        scope["catalog_id"] = "tampered-catalog"
    elif mutation == "catalog_version":
        catalog["catalogVersion"] = "tampered-version"
        scope["catalog_version"] = "tampered-version"
    elif mutation == "scope_hash":
        catalog["scopeHash"] = "0" * 64
        scope["scope_hash"] = "0" * 64
    else:
        raise AssertionError(f"Unhandled mutation: {mutation}")

    _rehash_report(report)
    with pytest.raises(ContractValidationError):
        CatalogHypothesisFlowReadinessReport.from_dict(
            report,
            trusted_authority=_authority(complete_result_set),
        )


def test_rebound_packages_under_attacker_scope_cannot_be_ready(
    complete_result_set: FullCatalogResultSet,
) -> None:
    rebound = _rebound_attacker_result_set(complete_result_set)

    report = _build(rebound)
    assert report["status"] == "NOT_READY"
    assert "catalog_scope" in report["blockers"]

    with pytest.raises(ContractValidationError, match="official tracked catalog scope"):
        _authority(rebound)


@pytest.mark.parametrize("mutation", ("source", "program", "policy", "model"))
def test_ready_rejects_rehashed_authority_context_tampering(
    complete_result_set: FullCatalogResultSet,
    mutation: str,
) -> None:
    report = deepcopy(_build(complete_result_set))
    if mutation == "source":
        report["sourceCommit"] = "b" * 40
    elif mutation == "program":
        report["programContract"]["coreBehaviorHash"] = "1" * 64
    elif mutation == "policy":
        report["catalogPolicy"]["corePolicyHash"] = "2" * 64
    elif mutation == "model":
        report["modelPolicySha256"] = "3" * 64
    else:
        raise AssertionError(f"Unhandled mutation: {mutation}")

    _rehash_report(report)
    with pytest.raises(ContractValidationError):
        CatalogHypothesisFlowReadinessReport.from_dict(
            report,
            trusted_authority=_authority(complete_result_set),
        )


def test_report_hash_is_stable_for_identical_evidence_and_ignores_generated_at(
    complete_result_set: FullCatalogResultSet,
) -> None:
    first = _build(complete_result_set, generated_at="2026-08-23T00:00:00Z")
    second = _build(complete_result_set, generated_at="2026-08-24T00:00:00Z")

    assert first["generatedAt"] != second["generatedAt"]
    assert first["readinessReportSha256"] == second["readinessReportSha256"]


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source", "b" * 40),
        ("program", "1" * 64),
        ("policy", "2" * 64),
        ("model_policy", "3" * 64),
    ],
)
def test_report_hash_covers_source_program_policy_and_model_policy(
    complete_result_set: FullCatalogResultSet,
    field: str,
    replacement: str,
) -> None:
    baseline = _build(complete_result_set)
    kwargs: dict = {}
    if field == "source":
        kwargs["source_commit"] = replacement
    elif field == "program":
        kwargs["program_contract"] = _program_contract(coreBehaviorHash=replacement)
    elif field == "policy":
        kwargs["catalog_policy"] = _catalog_policy(corePolicyHash=replacement)
    else:
        kwargs["model_policy_sha256"] = replacement

    changed = _build(complete_result_set, **kwargs)
    assert changed["readinessReportSha256"] != baseline["readinessReportSha256"]
    if field != "source":
        assert changed["status"] == "NOT_READY"


def test_report_hash_covers_package_and_receipt_identities() -> None:
    scope = CatalogScope.from_tracked_resources()
    baseline = FullCatalogResultSet(scope=scope)
    changed_package = FullCatalogResultSet(scope=scope)
    changed_receipt = FullCatalogResultSet(scope=scope)
    baseline.add_result(QuestionResult.from_package(_package(scope, "SCI-001")))
    changed_package.add_result(
        QuestionResult.from_package(
            _package(scope, "SCI-001", input_snapshot_sha256="b" * 64)
        )
    )
    changed_receipt.add_result(
        QuestionResult.from_package(
            _package(
                scope,
                "SCI-001",
                evidence_locator_extras={"outputRef": "artifact://changed-receipt"},
            )
        )
    )

    baseline_hash = _build(baseline)["readinessReportSha256"]
    assert _build(changed_package)["readinessReportSha256"] != baseline_hash
    assert _build(changed_receipt)["readinessReportSha256"] != baseline_hash


def test_124_and_legacy_results_are_not_ready(
    complete_result_set: FullCatalogResultSet,
) -> None:
    partial = FullCatalogResultSet(scope=complete_result_set.scope)
    for result in complete_result_set.results()[:124]:
        partial.add_result(result)
    partial_report = _build(partial)
    assert partial_report["status"] == "NOT_READY"
    assert "catalog_present_count" in partial_report["blockers"]

    legacy = FullCatalogResultSet(scope=complete_result_set.scope)
    for question_id in official_question_ids():
        legacy.add_result(
            QuestionResult.create(
                scope=complete_result_set.scope,
                question_id=question_id,
                model_receipt_locator=f"receipt://{question_id}",
                knowledge_locator=f"knowledge://{question_id}",
            )
        )
    legacy_report = _build(
        legacy,
        model_policy_sha256=_model_policy_sha256(complete_result_set),
    )
    assert legacy_report["status"] == "NOT_READY"
    assert "catalog_package_backing" in legacy_report["blockers"]


def test_rejected_human_gate_and_missing_model_policy_are_not_ready(
    complete_result_set: FullCatalogResultSet,
) -> None:
    rejected = FullCatalogResultSet(scope=complete_result_set.scope)
    rejected.add_result(
        QuestionResult.from_package(
            _package(complete_result_set.scope, "SCI-001", gate_decision="rejected")
        )
    )
    for result in complete_result_set.results()[1:]:
        rejected.add_result(result)

    rejected_report = _build(rejected)
    assert rejected_report["status"] == "NOT_READY"
    assert "catalog_human_gates" in rejected_report["blockers"]

    missing_policy = _build(complete_result_set, model_policy_sha256="")
    assert missing_policy["status"] == "NOT_READY"
    assert "model_policy_missing" in missing_policy["blockers"]


def test_missing_receipt_and_duplicate_attempt_fail_closed(
    complete_result_set: FullCatalogResultSet,
) -> None:
    missing_receipt = FullCatalogResultSet(scope=complete_result_set.scope)
    first = complete_result_set.results()[0]
    snapshot = deepcopy(first.package_snapshot)
    assert snapshot is not None
    snapshot["model_invocation_receipts"].pop("revision")
    missing_receipt.add_result(
        replace(
            first,
            _package_snapshot_json=json.dumps(
                snapshot,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    )
    for result in complete_result_set.results()[1:]:
        missing_receipt.add_result(result)
    receipt_report = _build(missing_receipt)
    assert receipt_report["status"] == "NOT_READY"
    assert "catalog_receipts" in receipt_report["blockers"]
    assert len(receipt_report["catalogResultSet"]["resultManifest"]["entries"]) == 124
    assert len(receipt_report["catalogResultSet"]["resultManifest"]["manifest_sha256"]) == 64

    duplicated = FullCatalogResultSet(scope=complete_result_set.scope)
    for result in complete_result_set.results():
        duplicated.add_result(result)
    with pytest.raises(ResultSetContractError, match="Duplicate result"):
        duplicated.add_result(complete_result_set.results()[0])
    duplicate_report = _build(duplicated)
    assert duplicate_report["status"] == "NOT_READY"
    assert "catalog_duplicates" in duplicate_report["blockers"]


def test_failed_or_missing_delivery_evidence_is_not_ready(
    complete_result_set: FullCatalogResultSet,
) -> None:
    failed = _evidence()
    failed["browser"] = {"status": "FAIL", "locator": "evidence://browser/failure"}
    report = _build(complete_result_set, evidence=failed)
    assert report["status"] == "NOT_READY"
    assert "evidence_browser" in report["blockers"]
    assert report["nextLegalAction"] == CATALOG_HYPOTHESIS_FLOW_REPAIR_ACTION

    missing = _evidence()
    missing.pop("frontend")
    missing_report = _build(complete_result_set, evidence=missing)
    assert missing_report["status"] == "NOT_READY"
    assert "evidence_frontend" in missing_report["blockers"]


def test_evidence_locator_change_changes_readiness_hash(
    complete_result_set: FullCatalogResultSet,
) -> None:
    baseline = _build(complete_result_set)
    changed = _evidence()
    changed["api"]["locator"] = "evidence://catalog-readiness/api/2"
    updated = _build(complete_result_set, evidence=changed)

    assert updated["status"] == "READY"
    assert updated["readinessReportSha256"] != baseline["readinessReportSha256"]


def test_report_round_trip_rejects_manifest_tampering(
    complete_result_set: FullCatalogResultSet,
) -> None:
    report = _build(complete_result_set)
    restored = CatalogHypothesisFlowReadinessReport.from_dict(
        report,
        trusted_authority=_authority(complete_result_set),
    )
    assert restored.to_dict() == report

    tampered = deepcopy(report)
    tampered["catalogResultSet"]["resultManifest"]["entries"][0][
        "canonical_sha256"
    ] = "0" * 64
    with pytest.raises(ContractValidationError, match="manifest"):
        CatalogHypothesisFlowReadinessReport.from_dict(
            tampered,
            trusted_authority=_authority(complete_result_set),
        )


def test_ready_requires_trusted_authority_context(
    complete_result_set: FullCatalogResultSet,
) -> None:
    with pytest.raises(ContractValidationError, match="trusted authority"):
        CatalogHypothesisFlowReadinessReport.from_dict(_build(complete_result_set))


def test_catalog_readiness_import_does_not_load_experiment_adapters() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import core.research.competition.catalog_hypothesis_flow_ready; "
                "assert 'core.research.experiment_adapters' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_platform_readiness_keeps_compatibility_version_exports() -> None:
    from core.research.competition import platform_flow_ready

    assert platform_flow_ready.PROGRAM_CONTRACT_VERSION == PROGRAM_CONTRACT_VERSION
    assert platform_flow_ready.CATALOG_POLICY_VERSION == CATALOG_POLICY_VERSION
