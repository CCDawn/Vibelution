"""D13 delivery toolchain tests. Fixture packs never impersonate a final 125/125."""

from __future__ import annotations

from copy import deepcopy

import pytest

from core.research.competition.catalog_hypothesis_flow_ready import (
    build_catalog_hypothesis_flow_readiness_report,
)
from core.research.competition.delivery import (
    build_evidence_index,
    check_pdf_limit,
    export_catalog_results,
    export_results,
    validate_submission_projection,
)
from core.research.competition.resources import (
    CATALOG_POLICY_VERSION,
    CATALOG_QUESTION_COUNT,
    CORE_BEHAVIOR_HASH,
    CORE_POLICY_HASH,
    PROGRAM_CONTRACT_VERSION,
)
from core.research.competition.result_set import (
    CatalogScope,
    FullCatalogResultSet,
    QuestionResult,
    official_question_ids,
)
from core.research.workflow.contracts.catalog_hypothesis_flow_readiness import (
    CATALOG_HYPOTHESIS_FLOW_EVIDENCE_IDS,
    CatalogHypothesisFlowReadinessAuthority,
    catalog_hypothesis_flow_report_hash,
)
from tests.test_catalog_execution_state_machine import _package

COMPLETE = {
    "approvedQuestionCount": CATALOG_QUESTION_COUNT,
    "r0": "PASS",
    "r1": "PASS",
    "r2": "PASS",
    "r3": "PASS",
    "pendingClaimCount": 0,
    "submissionProjectionFrozen": True,
    "evidenceIndex": [{"path": "offline/receipt.json", "kind": "receipt", "sha256": "A" * 64}],
}


def test_preview_pack_is_not_final_without_125() -> None:
    pack = export_results({"approvedQuestionCount": 1, "r0": "FAIL"}, mode="preview")
    assert pack["status"] == "preview"
    assert pack["final"] is False
    assert pack["blockers"] == []
    assert pack["requiredQuestionCount"] == 125


def test_formal_pack_refuses_incomplete_catalog_and_unfrozen_projection() -> None:
    pack = export_results(
        {
            "approvedQuestionCount": 5,
            "r0": "PASS",
            "r1": "PASS",
            "r2": "PASS",
            "r3": "PASS",
            "pendingClaimCount": 1,
            "submissionProjectionFrozen": False,
        },
        mode="formal",
    )
    assert pack["status"] == "refused"
    assert pack["final"] is False
    assert "catalog_incomplete" in pack["blockers"]
    assert "pending_claims" in pack["blockers"]
    assert "submission_projection_unfrozen" in pack["blockers"]


def test_formal_pack_rejects_preview_r2_r3_exemption() -> None:
    pack = export_results(
        {
            **COMPLETE,
            "r2": "not_required_for_preview",
            "r3": "not_required_for_preview",
        },
        mode="formal",
    )
    assert pack["status"] == "refused"
    assert pack["final"] is False
    assert "r2_not_pass" in pack["blockers"]
    assert "r3_not_pass" in pack["blockers"]


def test_submission_projection_unfrozen_only_allows_preview() -> None:
    report = validate_submission_projection(
        {
            "captured": False,
            "submissionProjectionFrozen": False,
            "officialPageObservedState": "submission_entry_coming_soon",
        }
    )
    assert report["allowedPackMode"] == "preview"
    assert report["blocksFormalPack"] is True


def test_evidence_index_rejects_path_escape() -> None:
    with pytest.raises(ValueError, match="unsafe evidence path"):
        build_evidence_index([{"path": "../secret.json"}])
    index = build_evidence_index(
        [{"path": "offline/receipt.json", "kind": "receipt", "sha256": "A" * 64}]
    )
    assert index["entryCount"] == 1


def test_pdf_limit_is_decoupled_from_generation() -> None:
    ok = check_pdf_limit(1024)
    assert ok["withinLimit"] is True
    assert ok["generatedContent"] is False
    over = check_pdf_limit(ok["limitBytes"] + 1)
    assert over["withinLimit"] is False


def _catalog_evidence() -> dict[str, dict[str, str]]:
    return {
        evidence_id: {
            "status": "PASS",
            "locator": f"evidence://catalog-export/{evidence_id}/1",
        }
        for evidence_id in CATALOG_HYPOTHESIS_FLOW_EVIDENCE_IDS
    }


def _catalog_readiness_report(result_set: FullCatalogResultSet) -> dict:
    first = result_set.get_result("SCI-001")
    snapshot = first.package_snapshot if first is not None else None
    model_policy = (
        str(snapshot["model_policy"]["policySha256"])
        if isinstance(snapshot, dict)
        else "f" * 64
    )
    return build_catalog_hypothesis_flow_readiness_report(
        result_set,
        model_policy_sha256=model_policy,
        source_commit="a" * 40,
        program_contract={
            "version": PROGRAM_CONTRACT_VERSION,
            "coreBehaviorHash": CORE_BEHAVIOR_HASH,
        },
        catalog_policy={
            "version": CATALOG_POLICY_VERSION,
            "corePolicyHash": CORE_POLICY_HASH,
        },
        evidence=_catalog_evidence(),
        generated_at="2026-08-23T00:00:00Z",
    )


def _catalog_readiness_authority(
    result_set: FullCatalogResultSet,
) -> CatalogHypothesisFlowReadinessAuthority:
    first = result_set.get_result("SCI-001")
    snapshot = first.package_snapshot if first is not None else None
    model_policy = (
        str(snapshot["model_policy"]["policySha256"])
        if isinstance(snapshot, dict)
        else "f" * 64
    )
    return CatalogHypothesisFlowReadinessAuthority.from_result_set(
        result_set,
        source_commit="a" * 40,
        program_contract={
            "version": PROGRAM_CONTRACT_VERSION,
            "coreBehaviorHash": CORE_BEHAVIOR_HASH,
        },
        catalog_policy={
            "version": CATALOG_POLICY_VERSION,
            "corePolicyHash": CORE_POLICY_HASH,
        },
        model_policy_sha256=model_policy,
    )


@pytest.fixture(scope="module")
def complete_catalog_result_set() -> FullCatalogResultSet:
    scope = CatalogScope.from_tracked_resources()
    result_set = FullCatalogResultSet(scope=scope)
    for question_id in official_question_ids():
        result_set.add_result(QuestionResult.from_package(_package(scope, question_id)))
    return result_set


def test_catalog_result_pack_binds_complete_canonical_manifest(
    complete_catalog_result_set: FullCatalogResultSet,
) -> None:
    report = _catalog_readiness_report(complete_catalog_result_set)
    authority = _catalog_readiness_authority(complete_catalog_result_set)
    pack = export_catalog_results(
        complete_catalog_result_set,
        report,
        trusted_authority=authority,
    )

    assert pack["schemaVersion"] == 1
    assert pack["packKind"] == "challenge_cup_catalog_result_pack"
    assert pack["status"] == "READY"
    assert pack["readinessStatus"] == "READY"
    assert pack["requiredQuestionCount"] == CATALOG_QUESTION_COUNT
    assert pack["counts"]["present_count"] == CATALOG_QUESTION_COUNT
    assert pack["catalogResultSet"]["counts"]["required_question_count"] == 125
    assert pack["canonicalResultManifest"] == complete_catalog_result_set.manifest()
    assert (
        pack["canonicalResultManifestSha256"]
        == complete_catalog_result_set.manifest()["manifest_sha256"]
    )
    assert pack["readinessReportSha256"] == report["readinessReportSha256"]
    assert pack["readinessReport"]["status"] == "READY"
    assert pack["researchAuthorizationRequired"] is True
    assert pack["realCampaignAllowed"] is False
    assert pack["final"] is False
    assert "r2" not in pack
    assert "r3" not in pack


def test_catalog_result_pack_requires_authority_for_ready_report(
    complete_catalog_result_set: FullCatalogResultSet,
) -> None:
    report = _catalog_readiness_report(complete_catalog_result_set)
    with pytest.raises(ValueError, match="trusted authority"):
        export_catalog_results(complete_catalog_result_set, report)


def test_catalog_result_pack_rejects_rehashed_forged_authority_facts(
    complete_catalog_result_set: FullCatalogResultSet,
) -> None:
    report = _catalog_readiness_report(complete_catalog_result_set)
    authority = _catalog_readiness_authority(complete_catalog_result_set)
    forged = deepcopy(report)
    forged["sourceCommit"] = "b" * 40
    forged["programContract"]["version"] = "9.9.9"
    forged["catalogPolicy"]["version"] = "9.9.9"
    forged["readinessReportSha256"] = catalog_hypothesis_flow_report_hash(forged)

    with pytest.raises(ValueError):
        export_catalog_results(
            complete_catalog_result_set,
            forged,
            trusted_authority=authority,
        )


def test_catalog_result_pack_exports_partial_not_ready_diagnostic() -> None:
    scope = CatalogScope.from_tracked_resources()
    partial = FullCatalogResultSet(scope=scope)
    partial.add_result(
        QuestionResult.create(
            scope=scope,
            question_id="SCI-001",
            model_receipt_locator="receipt://SCI-001",
            knowledge_locator="knowledge://SCI-001",
        )
    )
    report = _catalog_readiness_report(partial)
    pack = export_catalog_results(partial, report)

    assert pack["status"] == "NOT_READY"
    assert pack["final"] is False
    assert pack["realCampaignAllowed"] is False
    assert "catalog_present_count" in pack["blockers"]
    assert pack["counts"]["present_count"] == 1
    assert pack["canonicalResultManifest"]["entries"] == []


def test_catalog_result_pack_rejects_tampered_report_or_manifest(
    complete_catalog_result_set: FullCatalogResultSet,
) -> None:
    report = _catalog_readiness_report(complete_catalog_result_set)
    authority = _catalog_readiness_authority(complete_catalog_result_set)

    tampered_hash = deepcopy(report)
    tampered_hash["readinessReportSha256"] = "0" * 64
    with pytest.raises(ValueError, match="readiness report"):
        export_catalog_results(
            complete_catalog_result_set,
            tampered_hash,
            trusted_authority=authority,
        )

    tampered_manifest = deepcopy(report)
    tampered_manifest["catalogResultSet"]["resultManifest"]["entries"][0][
        "question_id"
    ] = "SCI-999"
    tampered_manifest["catalogResultSet"]["resultManifest"]["manifest_sha256"] = (
        "f" * 64
    )
    tampered_manifest["readinessReportSha256"] = catalog_hypothesis_flow_report_hash(
        tampered_manifest
    )
    with pytest.raises(ValueError):
        export_catalog_results(
            complete_catalog_result_set,
            tampered_manifest,
            trusted_authority=authority,
        )


def test_catalog_result_pack_rejects_mismatched_result_set_and_scope(
    complete_catalog_result_set: FullCatalogResultSet,
) -> None:
    report = _catalog_readiness_report(complete_catalog_result_set)
    authority = _catalog_readiness_authority(complete_catalog_result_set)
    partial = FullCatalogResultSet(scope=complete_catalog_result_set.scope)
    partial.add_result(
        QuestionResult.create(
            scope=partial.scope,
            question_id="SCI-001",
            model_receipt_locator="receipt://SCI-001",
            knowledge_locator="knowledge://SCI-001",
        )
    )
    with pytest.raises(ValueError):
        export_catalog_results(partial, report, trusted_authority=authority)

    attacker_scope = CatalogScope(
        catalog_id="attacker-catalog",
        catalog_version="999",
        catalog_sha256="0" * 64,
        scope_hash="0" * 64,
    )
    attacker = FullCatalogResultSet(scope=attacker_scope)
    with pytest.raises(ValueError):
        export_catalog_results(attacker, report)
