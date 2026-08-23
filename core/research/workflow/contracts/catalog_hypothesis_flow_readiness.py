"""Formal readiness contract for the 125-question hypothesis flow.

The report is evidence-only: ``READY`` means the frozen catalog result set and
all delivery evidence are complete enough to request a separate server-owned
research authorization.  It never grants a real campaign by itself.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._canonical import sha256_hex
from ._validation import ContractValidationError

CATALOG_HYPOTHESIS_FLOW_REPORT_KIND = "CatalogHypothesisFlowReadinessReport"
CATALOG_HYPOTHESIS_FLOW_SCHEMA_VERSION = 1
CATALOG_HYPOTHESIS_FLOW_READY_STATUS = "READY"
CATALOG_HYPOTHESIS_FLOW_NOT_READY_STATUS = "NOT_READY"
RESEARCH_AUTHORIZATION_REQUIRED_ACTION = "RESEARCH_AUTHORIZATION_REQUIRED"
CATALOG_HYPOTHESIS_FLOW_REPAIR_ACTION = "repair_catalog_hypothesis_flow_readiness"
CATALOG_HYPOTHESIS_FLOW_EVIDENCE_IDS = (
    "r0",
    "r1",
    "api",
    "frontend",
    "browser",
)
CATALOG_HYPOTHESIS_FLOW_EVIDENCE_STATUSES = frozenset(
    {"PASS", "FAIL", "BLOCKED", "MISSING"}
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_READY_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "scope",
        "required_question_count",
        "entries",
        "manifest_sha256",
    }
)
_READY_MANIFEST_ENTRY_FIELDS = frozenset(
    {
        "question_id",
        "package_id",
        "run_id",
        "canonical_sha256",
        "idempotency_key",
        "quality_status",
        "human_gate_decisions",
        "receipts",
    }
)
_READY_MANIFEST_RECEIPT_FIELDS = frozenset(
    {
        "receipt_id",
        "node_run_id",
        "evidence_locator",
        "evidence_locator_sha256",
    }
)
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schemaVersion",
        "reportKind",
        "status",
        "researchAuthorizationRequired",
        "realCampaignAllowed",
        "nextLegalAction",
        "sourceCommit",
        "programContract",
        "catalogPolicy",
        "modelPolicySha256",
        "catalogResultSet",
        "evidence",
        "blockers",
        "readinessReportSha256",
        "generatedAt",
    }
)


def _canonical_hash_body(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in payload.items()
        if key not in {"readinessReportSha256", "generatedAt"}
    }


def catalog_hypothesis_flow_report_hash(payload: Mapping[str, Any]) -> str:
    """Hash every stable authority/evidence field, excluding time and self."""

    return sha256_hex(_canonical_hash_body(payload))


def _mapping(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field} must be an object")
    return copy.deepcopy(dict(value))


def _text(payload: Mapping[str, Any], field: str, *, allow_empty: bool = False) -> str:
    value = str(payload.get(field) or "").strip()
    if not value and not allow_empty:
        raise ContractValidationError(f"{field} must be a non-empty string")
    return value


def _sha256(value: Any, field: str, *, allow_empty: bool = False) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized and allow_empty:
        return ""
    if not _SHA256_RE.fullmatch(normalized):
        raise ContractValidationError(f"{field} must be a sha256 hex digest")
    return normalized


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _validate_result_manifest(
    manifest: Mapping[str, Any],
    *,
    ready: bool,
) -> dict[str, Any]:
    normalized = copy.deepcopy(dict(manifest))
    supplied = str(normalized.get("manifest_sha256") or "").strip().upper()
    if not supplied:
        if ready:
            raise ContractValidationError("result manifest hash is required for READY")
        return normalized
    if ready:
        if set(normalized) != _READY_MANIFEST_FIELDS:
            raise ContractValidationError(
                "READY result manifest contains unsupported or missing fields"
            )
        if normalized.get("schema_version") != 1:
            raise ContractValidationError(
                "READY result manifest schema_version must be 1"
            )
        if normalized.get("required_question_count") != 125:
            raise ContractValidationError(
                "READY result manifest required_question_count must be 125"
            )
        if not isinstance(normalized.get("scope"), Mapping):
            raise ContractValidationError("READY result manifest scope must be an object")
    body = {
        key: copy.deepcopy(value)
        for key, value in normalized.items()
        if key != "manifest_sha256"
    }
    expected = sha256_hex(body).upper()
    if supplied != expected:
        raise ContractValidationError("result manifest hash does not match its content")
    entries = normalized.get("entries")
    if not isinstance(entries, list):
        raise ContractValidationError("result manifest entries must be a list")
    question_ids: list[str] = []
    package_ids: set[str] = set()
    run_ids: set[str] = set()
    idempotency_keys: set[str] = set()
    receipt_ids: set[str] = set()
    node_run_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ContractValidationError("result manifest entries must be objects")
        if ready and set(entry) != _READY_MANIFEST_ENTRY_FIELDS:
            raise ContractValidationError(
                "READY result manifest entry contains unsupported or missing fields"
            )
        question_id = str(entry.get("question_id") or "").strip()
        question_ids.append(question_id)
        _sha256(entry.get("canonical_sha256"), "result manifest canonical_sha256")
        gates = entry.get("human_gate_decisions")
        if not isinstance(gates, Mapping):
            raise ContractValidationError(
                "result manifest human_gate_decisions must be an object"
            )
        if ready:
            if set(gates) != {"selection", "research_plan"}:
                raise ContractValidationError(
                    "READY result manifest human gates must contain selection and research_plan"
                )
            if any(gates.get(stage) != "approved" for stage in gates):
                raise ContractValidationError(
                    "READY result manifest human gates must both be approved"
                )
            if entry.get("quality_status") != "approved":
                raise ContractValidationError(
                    "READY result manifest quality_status must be approved"
                )
            for field, values in (
                ("package_id", package_ids),
                ("run_id", run_ids),
                ("idempotency_key", idempotency_keys),
            ):
                value = _required_text(entry.get(field), f"result manifest {field}")
                if value in values:
                    raise ContractValidationError(
                        f"READY result manifest {field} values must be unique"
                    )
                values.add(value)
        receipts = entry.get("receipts")
        if not isinstance(receipts, Mapping) or set(receipts) != {
            "generation",
            "review",
            "revision",
        }:
            raise ContractValidationError(
                "result manifest receipts must contain generation, review, and revision"
            )
        for stage, receipt in receipts.items():
            if not isinstance(receipt, Mapping):
                raise ContractValidationError(
                    f"result manifest receipt {stage} must be an object"
                )
            if ready and set(receipt) != _READY_MANIFEST_RECEIPT_FIELDS:
                raise ContractValidationError(
                    f"READY result manifest receipt {stage} contains unsupported or missing fields"
                )
            locator = receipt.get("evidence_locator")
            if not isinstance(locator, Mapping) or not locator:
                raise ContractValidationError(
                    f"result manifest receipt {stage} requires evidence locator identity"
                )
            if ready:
                receipt_id = _required_text(
                    receipt.get("receipt_id"),
                    f"result manifest receipt {stage}.receipt_id",
                )
                node_run_id = _required_text(
                    receipt.get("node_run_id"),
                    f"result manifest receipt {stage}.node_run_id",
                )
                if receipt_id in receipt_ids or node_run_id in node_run_ids:
                    raise ContractValidationError(
                        "READY result manifest receipt and node-run identities must be unique"
                    )
                receipt_ids.add(receipt_id)
                node_run_ids.add(node_run_id)
            supplied_locator_hash = str(
                receipt.get("evidence_locator_sha256") or ""
            ).strip().upper()
            if supplied_locator_hash != sha256_hex(dict(locator)).upper():
                raise ContractValidationError(
                    f"result manifest receipt {stage} locator hash is invalid"
                )
    if len(set(question_ids)) != len(question_ids):
        raise ContractValidationError("result manifest contains duplicate question ids")
    if ready and len(entries) != 125:
        raise ContractValidationError("READY result manifest must contain 125 entries")
    if ready and question_ids != [f"SCI-{index:03d}" for index in range(1, 126)]:
        raise ContractValidationError(
            "READY result manifest must contain canonical SCI-001 through SCI-125"
        )
    return normalized


def _count(mapping: Mapping[str, Any], field: str) -> int:
    value = mapping.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractValidationError(f"catalogResultSet.counts.{field} is invalid")
    return value


def _projection_count(mapping: Mapping[str, Any], field: str) -> int:
    value = mapping.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractValidationError(f"catalogResultSet.{field} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class CatalogHypothesisFlowReadinessReport:
    schemaVersion: int
    reportKind: str
    status: str
    researchAuthorizationRequired: bool
    realCampaignAllowed: bool
    nextLegalAction: str
    sourceCommit: str
    programContract: dict[str, Any]
    catalogPolicy: dict[str, Any]
    modelPolicySha256: str
    catalogResultSet: dict[str, Any]
    evidence: dict[str, dict[str, str]]
    blockers: tuple[str, ...]
    readinessReportSha256: str
    generatedAt: str

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> CatalogHypothesisFlowReadinessReport:
        if not isinstance(payload, Mapping):
            raise ContractValidationError("catalog hypothesis readiness report must be an object")
        unknown = sorted(set(payload) - _TOP_LEVEL_FIELDS)
        missing = sorted(_TOP_LEVEL_FIELDS - set(payload))
        if missing:
            raise ContractValidationError(
                "catalog hypothesis readiness report is missing fields: "
                + ", ".join(missing)
            )
        if unknown:
            raise ContractValidationError(
                "catalog hypothesis readiness report contains unsupported fields: "
                + ", ".join(unknown)
            )
        if payload.get("schemaVersion") != CATALOG_HYPOTHESIS_FLOW_SCHEMA_VERSION:
            raise ContractValidationError("catalog hypothesis readiness schema is unsupported")
        if payload.get("reportKind") != CATALOG_HYPOTHESIS_FLOW_REPORT_KIND:
            raise ContractValidationError("catalog hypothesis readiness reportKind is invalid")

        blockers_raw = payload.get("blockers")
        if not isinstance(blockers_raw, list) or any(
            not isinstance(item, str) or not item.strip() for item in blockers_raw
        ):
            raise ContractValidationError("blockers must be a list of non-empty strings")
        blockers = tuple(item.strip() for item in blockers_raw)
        if len(set(blockers)) != len(blockers):
            raise ContractValidationError("blockers must not contain duplicates")
        status = str(payload.get("status") or "").strip().upper()
        expected_status = (
            CATALOG_HYPOTHESIS_FLOW_NOT_READY_STATUS
            if blockers
            else CATALOG_HYPOTHESIS_FLOW_READY_STATUS
        )
        if status != expected_status:
            raise ContractValidationError("status does not match readiness blockers")
        if payload.get("researchAuthorizationRequired") is not True:
            raise ContractValidationError("researchAuthorizationRequired must remain true")
        if payload.get("realCampaignAllowed") is not False:
            raise ContractValidationError("realCampaignAllowed must remain false")
        expected_action = (
            RESEARCH_AUTHORIZATION_REQUIRED_ACTION
            if status == CATALOG_HYPOTHESIS_FLOW_READY_STATUS
            else CATALOG_HYPOTHESIS_FLOW_REPAIR_ACTION
        )
        if payload.get("nextLegalAction") != expected_action:
            raise ContractValidationError("nextLegalAction does not match readiness status")

        source_commit = _text(payload, "sourceCommit", allow_empty=True).lower()
        if source_commit and not _SOURCE_COMMIT_RE.fullmatch(source_commit):
            raise ContractValidationError("sourceCommit must be a 40-character git hash")
        program = _mapping(payload, "programContract")
        _text(program, "version")
        program["coreBehaviorHash"] = _sha256(
            program.get("coreBehaviorHash"), "programContract.coreBehaviorHash"
        ).upper()
        policy = _mapping(payload, "catalogPolicy")
        _text(policy, "version")
        policy["corePolicyHash"] = _sha256(
            policy.get("corePolicyHash"), "catalogPolicy.corePolicyHash"
        ).upper()
        model_policy = _sha256(
            payload.get("modelPolicySha256"),
            "modelPolicySha256",
            allow_empty=True,
        )

        result_set = _mapping(payload, "catalogResultSet")
        counts = result_set.get("counts")
        if not isinstance(counts, Mapping):
            raise ContractValidationError("catalogResultSet.counts must be an object")
        for count_field in (
            "present_count",
            "missing_count",
            "duplicate_count",
            "submission_eligible_count",
            "package_backed_count",
            "quality_approved_count",
            "human_gate_approved_count",
            "receipt_complete_count",
            "required_question_count",
        ):
            _count(counts, count_field)
        for projection_field in (
            "selectionApprovedCount",
            "researchPlanApprovedCount",
            "receiptCompleteCount",
            "modelPolicyMatchedCount",
        ):
            _projection_count(result_set, projection_field)
        scope_hash = _sha256(result_set.get("scopeHash"), "catalogResultSet.scopeHash")
        result_set["scopeHash"] = scope_hash.upper()
        manifest = result_set.get("resultManifest")
        if not isinstance(manifest, Mapping):
            raise ContractValidationError(
                "catalogResultSet.resultManifest must be an object"
            )
        result_set["resultManifest"] = _validate_result_manifest(
            manifest,
            ready=status == CATALOG_HYPOTHESIS_FLOW_READY_STATUS,
        )
        manifest_scope = result_set["resultManifest"].get("scope")
        if isinstance(manifest_scope, Mapping) and (
            str(manifest_scope.get("scope_hash") or "").strip().upper()
            != result_set["scopeHash"]
            or str(manifest_scope.get("catalog_id") or "").strip()
            != str(result_set.get("catalogId") or "").strip()
            or str(manifest_scope.get("catalog_version") or "").strip()
            != str(result_set.get("catalogVersion") or "").strip()
        ):
            raise ContractValidationError(
                "result manifest scope does not match catalogResultSet"
            )
        if status == CATALOG_HYPOTHESIS_FLOW_READY_STATUS:
            if not source_commit or not model_policy:
                raise ContractValidationError(
                    "READY requires sourceCommit and modelPolicySha256"
                )
            required_ready_counts = {
                "present_count": 125,
                "missing_count": 0,
                "duplicate_count": 0,
                "submission_eligible_count": 125,
                "package_backed_count": 125,
                "quality_approved_count": 125,
                "human_gate_approved_count": 125,
                "receipt_complete_count": 125,
                "required_question_count": 125,
            }
            if any(
                counts.get(field) != expected
                for field, expected in required_ready_counts.items()
            ) or counts.get("submission_ready") is not True:
                raise ContractValidationError(
                    "READY catalogResultSet counts are not formal-125 complete"
                )
            if any(
                result_set.get(field) != 125
                for field in (
                    "selectionApprovedCount",
                    "researchPlanApprovedCount",
                    "receiptCompleteCount",
                    "modelPolicyMatchedCount",
                )
            ):
                raise ContractValidationError(
                    "READY catalogResultSet approvals, receipts, or model policy are incomplete"
                )

        evidence_raw = payload.get("evidence")
        if not isinstance(evidence_raw, Mapping) or set(evidence_raw) != set(
            CATALOG_HYPOTHESIS_FLOW_EVIDENCE_IDS
        ):
            raise ContractValidationError(
                "evidence must contain exactly r0, r1, api, frontend, and browser"
            )
        evidence: dict[str, dict[str, str]] = {}
        for evidence_id in CATALOG_HYPOTHESIS_FLOW_EVIDENCE_IDS:
            item = evidence_raw.get(evidence_id)
            if not isinstance(item, Mapping):
                raise ContractValidationError(f"evidence.{evidence_id} must be an object")
            status_value = str(item.get("status") or "").strip().upper()
            if status_value not in CATALOG_HYPOTHESIS_FLOW_EVIDENCE_STATUSES:
                raise ContractValidationError(
                    f"evidence.{evidence_id}.status is unsupported"
                )
            evidence[evidence_id] = {
                "status": status_value,
                "locator": str(item.get("locator") or "").strip(),
            }
            if status == CATALOG_HYPOTHESIS_FLOW_READY_STATUS and (
                status_value != "PASS" or not evidence[evidence_id]["locator"]
            ):
                raise ContractValidationError(
                    f"READY requires passing located evidence for {evidence_id}"
                )

        generated_at = _text(payload, "generatedAt")
        supplied_hash = _sha256(
            payload.get("readinessReportSha256"), "readinessReportSha256"
        )
        normalized_payload = {
            "schemaVersion": CATALOG_HYPOTHESIS_FLOW_SCHEMA_VERSION,
            "reportKind": CATALOG_HYPOTHESIS_FLOW_REPORT_KIND,
            "status": status,
            "researchAuthorizationRequired": True,
            "realCampaignAllowed": False,
            "nextLegalAction": expected_action,
            "sourceCommit": source_commit,
            "programContract": program,
            "catalogPolicy": policy,
            "modelPolicySha256": model_policy,
            "catalogResultSet": result_set,
            "evidence": evidence,
            "blockers": list(blockers),
            "readinessReportSha256": supplied_hash,
            "generatedAt": generated_at,
        }
        expected_hash = catalog_hypothesis_flow_report_hash(normalized_payload)
        if supplied_hash != expected_hash:
            raise ContractValidationError(
                "readinessReportSha256 does not match readiness evidence"
            )
        return cls(
            schemaVersion=CATALOG_HYPOTHESIS_FLOW_SCHEMA_VERSION,
            reportKind=CATALOG_HYPOTHESIS_FLOW_REPORT_KIND,
            status=status,
            researchAuthorizationRequired=True,
            realCampaignAllowed=False,
            nextLegalAction=expected_action,
            sourceCommit=source_commit,
            programContract=program,
            catalogPolicy=policy,
            modelPolicySha256=model_policy,
            catalogResultSet=result_set,
            evidence=evidence,
            blockers=blockers,
            readinessReportSha256=supplied_hash,
            generatedAt=generated_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "reportKind": self.reportKind,
            "status": self.status,
            "researchAuthorizationRequired": self.researchAuthorizationRequired,
            "realCampaignAllowed": self.realCampaignAllowed,
            "nextLegalAction": self.nextLegalAction,
            "sourceCommit": self.sourceCommit,
            "programContract": copy.deepcopy(self.programContract),
            "catalogPolicy": copy.deepcopy(self.catalogPolicy),
            "modelPolicySha256": self.modelPolicySha256,
            "catalogResultSet": copy.deepcopy(self.catalogResultSet),
            "evidence": copy.deepcopy(self.evidence),
            "blockers": list(self.blockers),
            "readinessReportSha256": self.readinessReportSha256,
            "generatedAt": self.generatedAt,
        }


__all__ = [
    "CATALOG_HYPOTHESIS_FLOW_EVIDENCE_IDS",
    "CATALOG_HYPOTHESIS_FLOW_EVIDENCE_STATUSES",
    "CATALOG_HYPOTHESIS_FLOW_NOT_READY_STATUS",
    "CATALOG_HYPOTHESIS_FLOW_READY_STATUS",
    "CATALOG_HYPOTHESIS_FLOW_REPAIR_ACTION",
    "CATALOG_HYPOTHESIS_FLOW_REPORT_KIND",
    "CATALOG_HYPOTHESIS_FLOW_SCHEMA_VERSION",
    "RESEARCH_AUTHORIZATION_REQUIRED_ACTION",
    "CatalogHypothesisFlowReadinessReport",
    "catalog_hypothesis_flow_report_hash",
]
