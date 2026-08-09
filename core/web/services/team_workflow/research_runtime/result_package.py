"""Durable research result package builder for workflow runs.

The workflow runtime records validated ArtifactManifest references, not package content.
This module assembles the human-readable result package from the run record:
decision history, promotion proposals, evaluation report refs and the official
candidate. Building is idempotent (one package per run) and read-only on the
run record; the store layer owns persistence.
"""

from __future__ import annotations

import uuid
from typing import Any

_IDENTITY_FIELDS = ("runId", "workflowId", "teamId", "projectId")


def _artifact_refs(record: dict[str, Any]) -> dict[str, Any]:
    return dict((record.get("langGraph") or {}).get("artifacts") or {})


def _decision_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "decisionId": str(item.get("decisionId") or ""),
        "decisionKind": str(item.get("decisionKind") or ""),
        "iterationAttempt": int(item.get("iterationAttempt") or 1),
        "decidedBy": str(item.get("decidedBy") or ""),
        "decidedAt": str(item.get("decidedAt") or ""),
        "reason": str(item.get("reason") or ""),
        "selectedCandidateRef": str(item.get("selectedCandidateRef") or ""),
        "baselineRef": str(item.get("baselineRef") or ""),
    }


def _proposal_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "proposalId": str(item.get("proposalId") or ""),
        "operation": str(item.get("operation") or ""),
        "targetCandidateRef": str(item.get("targetCandidateRef") or ""),
        "status": str(item.get("status") or ""),
        "reason": str(item.get("reason") or ""),
        "createdAt": str(item.get("createdAt") or ""),
    }


def _handoff_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "handoffId": str(item.get("handoffId") or ""),
        "fromNodeId": str(item.get("fromNodeId") or ""),
        "toNodeId": str(item.get("toNodeId") or ""),
        "status": str(item.get("status") or ""),
        "edgeId": str(item.get("edgeId") or ""),
    }


def result_package_availability(record: dict[str, Any]) -> tuple[bool, str]:
    """A package is buildable once the run has decision/official-candidate facts."""
    if record.get("resultPackage"):
        return True, ""
    if record.get("iterationDecisions") or record.get("officialCandidateRef"):
        return True, ""
    return False, "尚无迭代决策或官方候选，无法生成结果包"


def build_result_package(record: dict[str, Any]) -> dict[str, Any]:
    """Assemble (or return the existing) result package for a run.

    Idempotent: once stored, a run keeps exactly one package; rebuilds return
    the stored one so no command can duplicate or diverge it.
    """
    existing = record.get("resultPackage")
    if isinstance(existing, dict) and existing.get("packageId"):
        return existing

    run_id = str(record.get("runId") or "")
    artifacts = _artifact_refs(record)
    package_id = f"rrp:{run_id}:{uuid.uuid4().hex[:8]}"

    evaluation_refs: list[dict[str, str]] = []
    run_refs: dict[str, str] = {}
    for key, value in sorted(artifacts.items()):
        if not isinstance(value, str):
            continue
        if key.startswith("run_artifacts:attempt:"):
            run_refs[key.rsplit(":", 1)[-1]] = value
        elif key == "evaluation_report":
            evaluation_refs.append({"attempt": "", "ref": value})
    for attempt, ref in sorted(run_refs.items()):
        evaluation_refs.append({"attempt": attempt, "ref": ref})

    decisions = [
        _decision_summary(item)
        for item in (record.get("iterationDecisions") or [])
        if isinstance(item, dict)
    ]
    proposals = [
        _proposal_summary(item)
        for item in (record.get("promotionProposals") or [])
        if isinstance(item, dict)
    ]
    handoffs = [
        _handoff_summary(item)
        for item in (record.get("handoffs") or [])
        if isinstance(item, dict)
    ][-60:]

    package_ref = str(record.get("resultPackageRef") or "") or str(
        artifacts.get("research_result_package") or ""
    ) or package_id

    package: dict[str, Any] = {
        "packageId": package_id,
        "packageRef": package_ref,
        "overview": {
            "status": str(record.get("status") or ""),
            "completionKind": str(record.get("completionKind") or ""),
            "terminalReason": str(record.get("terminalReason") or ""),
            "officialCandidateRef": str(record.get("officialCandidateRef") or ""),
            "frozenProtocolRef": str(artifacts.get("frozen_protocol") or ""),
            "iterationAttemptCount": len(decisions),
        },
        "iterationDecisions": decisions,
        "promotionProposals": proposals,
        "evaluationReportRefs": evaluation_refs,
        "handoffSummary": handoffs,
        "builtAt": "",
    }
    for field in _IDENTITY_FIELDS:
        if record.get(field):
            package[field] = str(record.get(field) or "")
    return package
