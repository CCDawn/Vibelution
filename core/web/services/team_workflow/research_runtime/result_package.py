"""Strict terminal gate and deterministic same-fact Challenge Cup package."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


class ResultPackageError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


_REQUIRED_ARTIFACT_KINDS = frozenset(
    {
        "source_candidate_batch",
        "evidence_card_batch",
        "evidence_relation_graph",
        "knowledge_package_draft",
        "knowledge_package",
        "hypothesis_set",
        "protocol_draft",
        "protocol_review_report",
        "frozen_protocol",
        "smoke_evidence",
        "smoke_release",
        "run_artifacts",
        "evaluation_report",
        "iteration_decision",
        "version_governance_record",
    }
)
_REQUIRED_QUALITY_NODES = frozenset(
    {
        "source_finding",
        "source_extraction",
        "evidence_relations",
        "hypothesis_design",
        "controlled_run",
        "result_evaluation",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _artifact_kind(manifest: dict[str, Any]) -> str:
    return str(manifest.get("artifactId") or "").split(":", 1)[0]


def _validate_terminal_facts(
    record: dict[str, Any],
    research_ledger: dict[str, Any],
) -> dict[str, Any]:
    if record.get("status") != "succeeded" or record.get("runtimeCurrentNodeIds"):
        raise ResultPackageError(
            "Result Package requires a succeeded terminal WorkflowRun",
            code="run_not_terminal",
        )
    if not str(record.get("terminalReason") or "").strip():
        raise ResultPackageError(
            "terminalReason is required",
            code="terminal_reason_missing",
        )
    if any(
        item.get("status") == "pending" for item in record.get("humanTasks") or []
    ):
        raise ResultPackageError(
            "pending HumanTask blocks Result Package",
            code="pending_human_task",
        )
    manifests = [dict(item) for item in record.get("artifactManifests") or []]
    kinds = {_artifact_kind(item) for item in manifests}
    missing = sorted(_REQUIRED_ARTIFACT_KINDS - kinds)
    if missing:
        raise ResultPackageError(
            f"required ArtifactManifest missing: {missing}",
            code="required_artifact_missing",
        )
    if any(
        not _SHA256.fullmatch(str(item.get("contentHash") or ""))
        or "hash:" in str(item)
        for item in manifests
    ):
        raise ResultPackageError(
            "placeholder or invalid ArtifactManifest hash",
            code="invalid_artifact_hash",
        )
    input_snapshot = dict(record.get("inputSnapshot") or {})
    if not (
        input_snapshot.get("questionId")
        and input_snapshot.get("datasetRefs")
        and input_snapshot.get("metricContract")
    ):
        raise ResultPackageError(
            "question, dataset and metric contract must be frozen",
            code="input_snapshot_incomplete",
        )
    decisions = [
        dict(item)
        for item in record.get("iterationDecisions") or []
        if isinstance(item, dict)
    ]
    if not decisions:
        raise ResultPackageError(
            "terminal iteration decision is missing",
            code="iteration_decision_missing",
        )
    official_version = dict(record.get("officialVersion") or {})
    official_candidate = str(record.get("officialCandidateRef") or "")
    if not (
        official_version.get("status") == "official"
        and official_version.get("versionId")
        and official_version.get("candidateRef") == official_candidate
    ):
        raise ResultPackageError(
            "official version does not match the governed candidate",
            code="official_version_invalid",
        )
    if not any(
        item.get("nodeId") == "version_governance"
        and item.get("status") == "succeeded"
        for item in record.get("nodeRuns") or []
    ):
        raise ResultPackageError(
            "version_governance must succeed before packaging",
            code="version_governance_incomplete",
        )
    evaluations = [
        dict(item)
        for item in record.get("competitionEvaluations") or []
        if isinstance(item, dict)
    ]
    if not evaluations:
        raise ResultPackageError(
            "CompetitionEvaluationSnapshot is missing",
            code="evaluation_missing",
        )
    evaluation = evaluations[-1]
    if evaluation.get("blockingWarnings"):
        raise ResultPackageError(
            "blocking warning prevents Result Package",
            code="blocking_warning",
        )
    minimum_claim = float(
        (input_snapshot.get("evaluationContract") or {}).get(
            "minimumClaimEvidenceCoverage"
        )
        or 0
    )
    if float(evaluation.get("claimCoverage") or 0) < minimum_claim:
        raise ResultPackageError(
            "claim coverage is below the frozen minimum",
            code="quality_gate_failed",
        )
    passed_quality = {
        str(item.get("nodeId") or "")
        for item in record.get("qualityGateEvaluations") or []
        if item.get("status") == "passed"
    }
    if not _REQUIRED_QUALITY_NODES.issubset(passed_quality):
        raise ResultPackageError(
            "required quality gates have not all passed",
            code="quality_gate_failed",
        )
    if any(
        item.get("status") not in {"settled", "cancelled"}
        for item in record.get("budgetReservations") or []
    ) or any(
        any(float(value or 0) != 0 for value in (item.get("reserved") or {}).values())
        for item in record.get("budgetLedgers") or []
    ):
        raise ResultPackageError(
            "budget reservations are not fully settled",
            code="budget_unsettled",
        )
    if research_ledger.get("runId") != record.get("runId") or not (
        (research_ledger.get("boundaries") or {}).get("readOnly") is True
    ):
        raise ResultPackageError(
            "ResearchLedger does not match this run",
            code="research_ledger_invalid",
        )
    claims = list(research_ledger.get("claimEvidence") or [])
    if not claims or any(not item.get("evidenceRefs") for item in claims):
        raise ResultPackageError(
            "claim to evidence trace is incomplete",
            code="research_ledger_incomplete",
        )
    campaigns = list(record.get("experimentCampaigns") or [])
    if not campaigns or any(
        not item.get("experimentRunRefs") or not item.get("resultArtifactRefs")
        for item in campaigns
    ):
        raise ResultPackageError(
            "experiment campaign lineage is incomplete",
            code="experiment_lineage_incomplete",
        )
    return {
        "manifests": manifests,
        "decisions": decisions,
        "evaluation": evaluation,
        "officialVersion": official_version,
        "claims": claims,
        "campaigns": campaigns,
    }


def result_package_availability(
    record: dict[str, Any],
    *,
    research_ledger: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    try:
        _validate_terminal_facts(record, research_ledger or {})
    except ResultPackageError as exc:
        return False, str(exc)
    return True, ""


def terminal_package_candidate(record: dict[str, Any]) -> dict[str, Any]:
    """Project the deterministic terminal state that final-node completion commits."""
    ready = [
        item
        for item in record.get("nodeRuns") or []
        if item.get("nodeId") == "result_package" and item.get("status") == "ready"
    ]
    if record.get("runtimeCurrentNodeIds") != ["result_package"] or not ready:
        raise ResultPackageError(
            "result_package is not the sole ready terminal node",
            code="result_package_not_ready",
        )
    return {
        **record,
        "status": "succeeded",
        "runtimeCurrentNodeIds": [],
        "completedNodeIds": [
            *(record.get("completedNodeIds") or []),
            "result_package",
        ],
    }


def build_result_package(
    record: dict[str, Any],
    *,
    research_ledger: dict[str, Any],
) -> dict[str, Any]:
    facts = _validate_terminal_facts(record, research_ledger)
    manifests = facts["manifests"]
    artifact_refs = [
        {
            "artifactId": item["artifactId"],
            "contentHash": item["contentHash"],
            "schemaVersion": item["schemaVersion"],
        }
        for item in sorted(manifests, key=lambda item: str(item["artifactId"]))
    ]
    fact_chain = {
        "runId": record["runId"],
        "workflowVersionId": record["workflowVersionId"],
        "questionId": (record.get("inputSnapshot") or {}).get("questionId"),
        "datasetRefs": (record.get("inputSnapshot") or {}).get("datasetRefs"),
        "metricContract": (record.get("inputSnapshot") or {}).get("metricContract"),
        "terminalReason": record["terminalReason"],
        "officialVersion": facts["officialVersion"],
        "iterationDecision": facts["decisions"][-1],
        "competitionEvaluation": facts["evaluation"],
        "claimEvidence": facts["claims"],
        "experimentCampaigns": facts["campaigns"],
        "artifactRefs": artifact_refs,
    }
    fact_chain_hash = _canonical_hash(fact_chain)

    def deliverable(kind: str, sections: list[str]) -> dict[str, Any]:
        return {
            "kind": kind,
            "factChainHash": fact_chain_hash,
            "officialVersionId": facts["officialVersion"]["versionId"],
            "sections": sections,
            "claimRefs": [str(item.get("claimId") or "") for item in facts["claims"]],
            "artifactRefs": [item["artifactId"] for item in artifact_refs],
        }

    deliverables = {
        "report": deliverable(
            "report",
            ["problem", "method", "evidence", "experiments", "results", "limitations"],
        ),
        "defenseSlides": deliverable(
            "defense_slides",
            ["rubric_mapping", "innovation", "evidence", "reproducibility"],
        ),
        "demoScript": deliverable(
            "demo_script",
            ["setup", "workflow", "experiment_replay", "result_verification"],
        ),
        "experimentAppendix": deliverable(
            "experiment_appendix",
            ["protocol", "environment", "seeds", "metrics", "ablation", "replication"],
        ),
        "limitations": deliverable(
            "limitations",
            ["negative_results", "failed_attempts", "risks", "open_questions"],
        ),
    }
    package_core = {
        "runId": record["runId"],
        "workflowId": record["workflowId"],
        "workflowVersionId": record["workflowVersionId"],
        "teamId": record["teamId"],
        "projectId": record["projectId"],
        "factChainHash": fact_chain_hash,
        "officialVersion": facts["officialVersion"],
        "terminalReason": record["terminalReason"],
        "builtAt": str(facts["officialVersion"].get("governedAt") or ""),
        "deliverables": deliverables,
        "traceability": {
            "claimCount": len(facts["claims"]),
            "artifactCount": len(artifact_refs),
            "experimentCampaignCount": len(facts["campaigns"]),
            "artifactRefs": artifact_refs,
        },
    }
    content_hash = _canonical_hash(package_core)
    package = {
        **package_core,
        "packageId": f"rrp:{record['runId']}:{content_hash[:16]}",
        "packageRef": f"research-result-package:{content_hash}",
        "contentHash": content_hash,
    }
    existing = record.get("resultPackage")
    if isinstance(existing, dict) and existing.get("contentHash"):
        if existing.get("contentHash") != content_hash:
            raise ResultPackageError(
                "terminal facts changed after Result Package was built",
                code="terminal_facts_changed",
            )
        return dict(existing)
    return package
