"""Challenge Cup delivery-pack control flow.

Formal packs are refused until 125/125, R0/R1, no pending claims and a frozen
submission projection exist. Preview packs never claim to be final.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from core.research.competition.resources import (
    CATALOG_QUESTION_COUNT,
    CORE_BEHAVIOR_HASH,
    CORE_POLICY_HASH,
    PROGRAM_CONTRACT_VERSION,
)
from core.research.workflow.contracts.catalog_hypothesis_flow_readiness import (
    CatalogHypothesisFlowReadinessAuthority,
    CatalogHypothesisFlowReadinessReport,
)

from .catalog_hypothesis_flow_ready import _fallback_manifest
from .result_set import (
    CatalogScope,
    FullCatalogResultSet,
    ResultSetContractError,
)

DEFAULT_PDF_LIMIT_BYTES = 20 * 1024 * 1024
CATALOG_RESULT_PACK_SCHEMA_VERSION = 1
CATALOG_RESULT_PACK_KIND = "challenge_cup_catalog_result_pack"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def formal_blockers(payload: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    approved = int(payload.get("approvedQuestionCount") or 0)
    if approved != CATALOG_QUESTION_COUNT:
        blockers.append("catalog_incomplete")
    if str(payload.get("r0") or "") != "PASS":
        blockers.append("r0_not_pass")
    if str(payload.get("r1") or "") != "PASS":
        blockers.append("r1_not_pass")
    if str(payload.get("r2") or "pending") != "PASS":
        blockers.append("r2_not_pass")
    if str(payload.get("r3") or "pending") != "PASS":
        blockers.append("r3_not_pass")
    if int(payload.get("pendingClaimCount") or 0) > 0:
        blockers.append("pending_claims")
    if payload.get("submissionProjectionFrozen") is not True:
        blockers.append("submission_projection_unfrozen")
    return blockers


def export_results(payload: dict[str, Any], *, mode: str) -> dict[str, Any]:
    requested = str(mode or "preview").strip().lower()
    if requested not in {"preview", "formal"}:
        raise ValueError(f"unsupported export mode: {mode}")
    blockers = formal_blockers(payload) if requested == "formal" else []
    status = "refused" if blockers else ("final" if requested == "formal" else "preview")
    return {
        "schemaVersion": 1,
        "packKind": "challenge_cup_result_pack",
        "mode": requested,
        "status": status,
        "blockers": blockers,
        "programContract": {
            "version": PROGRAM_CONTRACT_VERSION,
            "coreBehaviorHash": CORE_BEHAVIOR_HASH,
        },
        "catalogPolicy": {
            "version": "1.2.0",
            "corePolicyHash": CORE_POLICY_HASH,
        },
        "approvedQuestionCount": int(payload.get("approvedQuestionCount") or 0),
        "requiredQuestionCount": CATALOG_QUESTION_COUNT,
        "evidenceIndex": list(payload.get("evidenceIndex") or []),
        "generatedAt": _now(),
        "final": status == "final",
    }


def _catalog_result_manifest(result_set: FullCatalogResultSet) -> dict[str, Any]:
    """Return the result-set-owned manifest, including a partial fallback.

    ``FullCatalogResultSet.manifest`` is the canonical identity projection.  A
    partial result set with one invalid receipt cannot produce that projection
    directly; the readiness builder uses the same identity-only fallback for
    its NOT_READY diagnostic, so reuse it here instead of accepting a caller
    supplied manifest.
    """

    try:
        return copy.deepcopy(result_set.manifest())
    except (ResultSetContractError, TypeError, ValueError, KeyError):
        try:
            return copy.deepcopy(_fallback_manifest(result_set))
        except (ResultSetContractError, TypeError, ValueError, KeyError) as exc:
            raise ValueError("catalog result set cannot produce a canonical manifest") from exc


def _canonical_catalog_result_set(
    result_set: FullCatalogResultSet,
    *,
    manifest: Mapping[str, Any],
    model_policy_sha256: str,
) -> dict[str, Any]:
    """Project canonical counts and identity for readiness-report binding."""

    try:
        counts = dict(result_set.export_counts())
        counts["required_question_count"] = CATALOG_QUESTION_COUNT
        selection_approved = 0
        research_plan_approved = 0
        receipt_complete = 0
        model_policy_matched = 0
        normalized_model_policy = str(model_policy_sha256 or "").strip().lower()
        for result in result_set.results():
            decisions = result.human_gate_decisions
            if len(decisions) == 2:
                selection_approved += decisions[0] == "approved"
                research_plan_approved += decisions[1] == "approved"
            if result.receipt_complete:
                receipt_complete += 1
            snapshot = result.package_snapshot
            package_policy = snapshot.get("model_policy") if isinstance(snapshot, Mapping) else None
            if (
                normalized_model_policy
                and isinstance(package_policy, Mapping)
                and str(package_policy.get("policySha256") or "").strip().lower()
                == normalized_model_policy
            ):
                model_policy_matched += 1
    except (ResultSetContractError, TypeError, ValueError, KeyError) as exc:
        raise ValueError("catalog result set contains invalid canonical data") from exc
    return {
        "catalogId": result_set.catalog_id,
        "catalogVersion": result_set.catalog_version,
        "scopeHash": result_set.scope_hash,
        "counts": counts,
        "selectionApprovedCount": selection_approved,
        "researchPlanApprovedCount": research_plan_approved,
        "receiptCompleteCount": receipt_complete,
        "modelPolicyMatchedCount": model_policy_matched,
        "resultManifest": copy.deepcopy(dict(manifest)),
    }


def _coerce_readiness_report(
    readiness_report: CatalogHypothesisFlowReadinessReport | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(readiness_report, CatalogHypothesisFlowReadinessReport):
        return readiness_report.to_dict()
    if isinstance(readiness_report, Mapping):
        return copy.deepcopy(dict(readiness_report))
    raise TypeError(
        "readiness_report must be a CatalogHypothesisFlowReadinessReport or mapping"
    )


def export_catalog_results(
    result_set: FullCatalogResultSet,
    readiness_report: CatalogHypothesisFlowReadinessReport | Mapping[str, Any],
    *,
    trusted_authority: CatalogHypothesisFlowReadinessAuthority | None = None,
) -> dict[str, Any]:
    """Export a canonical 125-question catalog diagnostic/result pack.

    This is intentionally separate from :func:`export_results`: it never
    evaluates R2/R3, PDF, frozen-submission, or official-campaign gates and it
    can never emit ``final=True``.  The result set and readiness report are
    both revalidated and cross-bound to the same tracked catalog scope before
    any fields are copied into the pack.  A NOT_READY or partial result set is
    exportable for diagnosis, but a forged client projection is not.
    """

    if not isinstance(result_set, FullCatalogResultSet):
        raise TypeError("result_set must be a trusted FullCatalogResultSet")
    if result_set.scope != CatalogScope.from_tracked_resources():
        raise ValueError("catalog result set scope is not the tracked catalog scope")
    if trusted_authority is not None and not isinstance(
        trusted_authority, CatalogHypothesisFlowReadinessAuthority
    ):
        raise TypeError("trusted_authority must be a CatalogHypothesisFlowReadinessAuthority")

    manifest = _catalog_result_manifest(result_set)
    raw_report = _coerce_readiness_report(readiness_report)

    # READY reports require an independently constructed server-side authority.
    # Never derive that authority from the report itself: a self-consistent
    # payload/hash is not proof that its source, program, policy, or model
    # facts were authorized by the service.
    report_status = str(raw_report.get("status") or "").strip().upper()
    authority = trusted_authority
    if report_status == "READY" and authority is None:
        raise ValueError("READY catalog export requires trusted authority")

    try:
        validated_report = CatalogHypothesisFlowReadinessReport.from_dict(
            raw_report,
            trusted_authority=authority,
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("readiness report failed canonical validation") from exc

    canonical_catalog = _canonical_catalog_result_set(
        result_set,
        manifest=manifest,
        model_policy_sha256=validated_report.modelPolicySha256,
    )
    if validated_report.catalogResultSet != canonical_catalog:
        raise ValueError("readiness report does not match the trusted catalog result set")
    if authority is not None:
        if authority.canonicalResultManifest != manifest:
            raise ValueError("trusted readiness authority manifest does not match result set")
        authority_catalog = _canonical_catalog_result_set(
            result_set,
            manifest=manifest,
            model_policy_sha256=authority.modelPolicySha256,
        )
        if authority.catalogResultSet != authority_catalog:
            raise ValueError("trusted readiness authority does not match result set")

    report_payload = validated_report.to_dict()
    counts = copy.deepcopy(canonical_catalog["counts"])
    canonical_manifest = copy.deepcopy(manifest)
    manifest_sha256 = str(canonical_manifest.get("manifest_sha256") or "").strip().upper()
    if len(manifest_sha256) != 64:
        raise ValueError("canonical result manifest hash is invalid")
    return {
        "schemaVersion": CATALOG_RESULT_PACK_SCHEMA_VERSION,
        "packKind": CATALOG_RESULT_PACK_KIND,
        "status": validated_report.status,
        "readinessStatus": validated_report.status,
        "blockers": list(validated_report.blockers),
        "catalogId": result_set.catalog_id,
        "catalogVersion": result_set.catalog_version,
        "scopeHash": result_set.scope_hash,
        "requiredQuestionCount": CATALOG_QUESTION_COUNT,
        "counts": counts,
        "catalogResultSet": copy.deepcopy(canonical_catalog),
        "canonicalResultManifest": canonical_manifest,
        "canonicalResultManifestSha256": manifest_sha256,
        "readinessReport": report_payload,
        "readinessReportSha256": validated_report.readinessReportSha256,
        "nextLegalAction": validated_report.nextLegalAction,
        "researchAuthorizationRequired": True,
        "realCampaignAllowed": False,
        "final": False,
        "generatedAt": _now(),
    }


def validate_submission_projection(payload: dict[str, Any]) -> dict[str, Any]:
    frozen = payload.get("submissionProjectionFrozen") is True
    captured = payload.get("captured") is True
    return {
        "frozen": frozen,
        "captured": captured,
        "blocksFormalPack": not frozen,
        "allowedPackMode": "preview" if not frozen else "formal",
        "officialPageObservedState": str(payload.get("officialPageObservedState") or "unknown"),
    }


def build_evidence_index(entries: list[dict[str, Any]]) -> dict[str, Any]:
    index = []
    for item in entries:
        path = str(item.get("path") or "").replace("\\", "/")
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ValueError(f"unsafe evidence path: {path}")
        index.append(
            {
                "path": path,
                "kind": str(item.get("kind") or "artifact"),
                "sha256": str(item.get("sha256") or ""),
                "scope": dict(item.get("scope") or {}),
            }
        )
    return {
        "schemaVersion": 1,
        "entryCount": len(index),
        "entries": index,
        "generatedAt": _now(),
    }


def check_pdf_limit(size_bytes: int, *, limit_bytes: int = DEFAULT_PDF_LIMIT_BYTES) -> dict[str, Any]:
    if size_bytes < 0:
        raise ValueError("size_bytes must be non-negative")
    return {
        "sizeBytes": int(size_bytes),
        "limitBytes": int(limit_bytes),
        "withinLimit": int(size_bytes) <= int(limit_bytes),
        "generatedContent": False,
    }
