"""Build the formal 125-question hypothesis-flow readiness report.

This core module consumes already trusted inputs and performs no filesystem,
network, model, route, or runtime work.  ``READY`` only advances to the
separate server authorization boundary; it never authorizes a real campaign.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from core.research.workflow.contracts.catalog_hypothesis_flow_readiness import (
    CATALOG_HYPOTHESIS_FLOW_EVIDENCE_IDS,
    CATALOG_HYPOTHESIS_FLOW_NOT_READY_STATUS,
    CATALOG_HYPOTHESIS_FLOW_READY_STATUS,
    CATALOG_HYPOTHESIS_FLOW_REPAIR_ACTION,
    CATALOG_HYPOTHESIS_FLOW_REPORT_KIND,
    CATALOG_HYPOTHESIS_FLOW_SCHEMA_VERSION,
    RESEARCH_AUTHORIZATION_REQUIRED_ACTION,
    CatalogHypothesisFlowReadinessReport,
    catalog_hypothesis_flow_report_hash,
    sha256_hex,
)

from .platform_flow_ready import CATALOG_POLICY_VERSION, PROGRAM_CONTRACT_VERSION
from .resources import CATALOG_QUESTION_COUNT, CORE_BEHAVIOR_HASH, CORE_POLICY_HASH
from .result_set import (
    RESULT_MANIFEST_SCHEMA_VERSION,
    FullCatalogResultSet,
    ResultSetContractError,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256(value: Any, *, upper: bool = False) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        return ""
    return normalized.upper() if upper else normalized


def _normalize_contract(
    value: Mapping[str, Any],
    *,
    version_field: str,
    hash_field: str,
) -> dict[str, str]:
    return {
        version_field: str(value.get(version_field) or "").strip(),
        hash_field: _sha256(value.get(hash_field), upper=True),
    }


def _normalize_evidence(
    value: Mapping[str, Any],
) -> tuple[dict[str, dict[str, str]], list[str]]:
    normalized: dict[str, dict[str, str]] = {}
    blockers: list[str] = []
    for evidence_id in CATALOG_HYPOTHESIS_FLOW_EVIDENCE_IDS:
        item = value.get(evidence_id)
        raw = item if isinstance(item, Mapping) else {}
        status = str(raw.get("status") or "MISSING").strip().upper()
        if status not in {"PASS", "FAIL", "BLOCKED", "MISSING"}:
            status = "MISSING"
        locator = str(raw.get("locator") or "").strip()
        normalized[evidence_id] = {"status": status, "locator": locator}
        if status != "PASS" or not locator:
            blockers.append(f"evidence_{evidence_id}")
    if set(value) - set(CATALOG_HYPOTHESIS_FLOW_EVIDENCE_IDS):
        blockers.append("evidence_contract")
    return normalized, blockers


def _fallback_manifest(result_set: FullCatalogResultSet) -> dict[str, Any]:
    """Build a hashable partial manifest when one receipt identity is invalid.

    A failing receipt must not make every other package identity disappear from
    the readiness hash.  Valid entries remain projected through the same
    identity-only method as a complete manifest; invalid entries carry only a
    question id and a snapshot digest, never package content.
    """

    body: dict[str, Any] = {
        "schema_version": RESULT_MANIFEST_SCHEMA_VERSION,
        "scope": result_set.scope.to_dict(),
        "required_question_count": CATALOG_QUESTION_COUNT,
        "entries": [],
        "manifestError": "invalid_or_incomplete_receipt_identity",
    }
    invalid_entries: list[dict[str, str]] = []
    for result in result_set.results():
        try:
            body["entries"].append(result.manifest_entry())
            continue
        except ResultSetContractError:
            pass
        snapshot_hash = ""
        try:
            snapshot = result.package_snapshot
        except ResultSetContractError:
            snapshot = None
        if isinstance(snapshot, Mapping):
            snapshot_hash = sha256_hex(snapshot).upper()
        invalid_entries.append(
            {
                "question_id": result.question_id,
                "snapshot_sha256": snapshot_hash,
            }
        )
    if invalid_entries:
        body["invalid_entries"] = invalid_entries
    return {**body, "manifest_sha256": sha256_hex(body).upper()}


def _catalog_projection(
    result_set: FullCatalogResultSet,
    *,
    model_policy_sha256: str,
) -> tuple[dict[str, Any], list[str]]:
    state = result_set.submission_state()
    selection_approved = 0
    research_plan_approved = 0
    matching_model_policy = 0
    for result in result_set.results():
        decisions = result.human_gate_decisions
        if len(decisions) == 2:
            selection_approved += decisions[0] == "approved"
            research_plan_approved += decisions[1] == "approved"
        snapshot = result.package_snapshot
        policy = snapshot.get("model_policy") if isinstance(snapshot, dict) else None
        if (
            model_policy_sha256
            and isinstance(policy, Mapping)
            and str(policy.get("policySha256") or "").strip().lower()
            == model_policy_sha256
        ):
            matching_model_policy += 1

    blockers: list[str] = []
    if state["present_count"] != CATALOG_QUESTION_COUNT or state["missing_count"]:
        blockers.append("catalog_present_count")
    if state["package_backed_count"] != CATALOG_QUESTION_COUNT:
        blockers.append("catalog_package_backing")
    if state["quality_approved_count"] != CATALOG_QUESTION_COUNT:
        blockers.append("catalog_quality")
    if (
        selection_approved != CATALOG_QUESTION_COUNT
        or research_plan_approved != CATALOG_QUESTION_COUNT
    ):
        blockers.append("catalog_human_gates")
    if state["receipt_complete_count"] != CATALOG_QUESTION_COUNT:
        blockers.append("catalog_receipts")
    if state["duplicate_count"]:
        blockers.append("catalog_duplicates")
    if state["submission_eligible_count"] != CATALOG_QUESTION_COUNT:
        blockers.append("catalog_submission_eligibility")
    if model_policy_sha256 and matching_model_policy != CATALOG_QUESTION_COUNT:
        blockers.append("model_policy_mismatch")

    try:
        manifest = result_set.manifest()
    except ResultSetContractError:
        manifest = _fallback_manifest(result_set)
        if "catalog_receipts" not in blockers:
            blockers.append("catalog_receipts")

    counts = result_set.export_counts()
    # ``FullCatalogResultSet`` is the existing result authority and exposes
    # this value as ``official_question_count``.  The formal readiness report
    # uses the contract name ``required_question_count`` so that a report can
    # be validated without depending on the result-set implementation's
    # projection vocabulary.
    counts["required_question_count"] = counts["official_question_count"]

    return (
        {
            "catalogId": result_set.catalog_id,
            "catalogVersion": result_set.catalog_version,
            "scopeHash": result_set.scope_hash,
            "counts": counts,
            "selectionApprovedCount": selection_approved,
            "researchPlanApprovedCount": research_plan_approved,
            "receiptCompleteCount": state["receipt_complete_count"],
            "modelPolicyMatchedCount": matching_model_policy,
            "resultManifest": manifest,
        },
        blockers,
    )


def build_catalog_hypothesis_flow_readiness_report(
    result_set: FullCatalogResultSet,
    *,
    model_policy_sha256: str,
    source_commit: str,
    program_contract: Mapping[str, Any],
    catalog_policy: Mapping[str, Any],
    evidence: Mapping[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build one deterministic report from trusted formal-catalog evidence."""

    if not isinstance(result_set, FullCatalogResultSet):
        raise TypeError("result_set must be a trusted FullCatalogResultSet")
    if not isinstance(program_contract, Mapping):
        raise TypeError("program_contract must be an object")
    if not isinstance(catalog_policy, Mapping):
        raise TypeError("catalog_policy must be an object")
    if not isinstance(evidence, Mapping):
        raise TypeError("evidence must be an object")

    blockers: list[str] = []
    normalized_source = str(source_commit or "").strip().lower()
    if not _SOURCE_COMMIT_RE.fullmatch(normalized_source):
        normalized_source = ""
        blockers.append("source_commit")

    program = _normalize_contract(
        program_contract,
        version_field="version",
        hash_field="coreBehaviorHash",
    )
    if program != {
        "version": PROGRAM_CONTRACT_VERSION,
        "coreBehaviorHash": CORE_BEHAVIOR_HASH,
    }:
        blockers.append("program_contract")

    policy = _normalize_contract(
        catalog_policy,
        version_field="version",
        hash_field="corePolicyHash",
    )
    if policy != {
        "version": CATALOG_POLICY_VERSION,
        "corePolicyHash": CORE_POLICY_HASH,
    }:
        blockers.append("catalog_policy")

    raw_model_policy = str(model_policy_sha256 or "").strip()
    normalized_model_policy = _sha256(raw_model_policy)
    if not raw_model_policy:
        blockers.append("model_policy_missing")
    elif not normalized_model_policy:
        blockers.append("model_policy_invalid")

    catalog_projection, catalog_blockers = _catalog_projection(
        result_set,
        model_policy_sha256=normalized_model_policy,
    )
    blockers.extend(catalog_blockers)
    normalized_evidence, evidence_blockers = _normalize_evidence(evidence)
    blockers.extend(evidence_blockers)
    blockers = list(dict.fromkeys(blockers))

    status = (
        CATALOG_HYPOTHESIS_FLOW_NOT_READY_STATUS
        if blockers
        else CATALOG_HYPOTHESIS_FLOW_READY_STATUS
    )
    next_action = (
        CATALOG_HYPOTHESIS_FLOW_REPAIR_ACTION
        if blockers
        else RESEARCH_AUTHORIZATION_REQUIRED_ACTION
    )
    payload: dict[str, Any] = {
        "schemaVersion": CATALOG_HYPOTHESIS_FLOW_SCHEMA_VERSION,
        "reportKind": CATALOG_HYPOTHESIS_FLOW_REPORT_KIND,
        "status": status,
        "researchAuthorizationRequired": True,
        "realCampaignAllowed": False,
        "nextLegalAction": next_action,
        "sourceCommit": normalized_source,
        "programContract": program,
        "catalogPolicy": policy,
        "modelPolicySha256": normalized_model_policy,
        "catalogResultSet": catalog_projection,
        "evidence": normalized_evidence,
        "blockers": blockers,
        "generatedAt": str(generated_at or _now()).strip(),
    }
    payload["readinessReportSha256"] = catalog_hypothesis_flow_report_hash(payload)
    return CatalogHypothesisFlowReadinessReport.from_dict(payload).to_dict()


# Keep the shorter module-name spelling available to later service adapters.
build_catalog_hypothesis_flow_ready_report = (
    build_catalog_hypothesis_flow_readiness_report
)


__all__ = [
    "build_catalog_hypothesis_flow_readiness_report",
    "build_catalog_hypothesis_flow_ready_report",
]
