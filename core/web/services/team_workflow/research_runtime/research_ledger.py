"""Read-only research ledger projection over canonical domain facts."""

from __future__ import annotations

from typing import Any


def project_research_ledger(
    record: dict[str, Any],
    *,
    claim_evidence: dict[str, Any],
    team_knowledge: dict[str, Any],
    experiment_planning: dict[str, Any],
) -> dict[str, Any]:
    claims = list(claim_evidence.get("evidence") or [])
    knowledge_bases = list(team_knowledge.get("knowledgeBases") or [])
    if not knowledge_bases:
        knowledge_bases = list(team_knowledge.get("bases") or [])
    artifacts = [dict(item) for item in record.get("artifactManifests") or []]
    return {
        "runId": record["runId"],
        "teamId": record["teamId"],
        "projectId": record["projectId"],
        "claimEvidence": claims,
        "teamKnowledge": knowledge_bases,
        "experimentPlanning": experiment_planning,
        "nodeRuns": [dict(item) for item in record.get("nodeRuns") or []],
        "handoffs": [dict(item) for item in record.get("handoffs") or []],
        "artifactManifests": artifacts,
        "resultPackage": record.get("resultPackage"),
        "summary": {
            "claimEvidenceCount": len(claims),
            "knowledgeBaseCount": len(knowledge_bases),
            "nodeRunCount": len(record.get("nodeRuns") or []),
            "handoffCount": len(record.get("handoffs") or []),
            "artifactCount": len(artifacts),
        },
        "boundaries": {
            "readOnly": True,
            "persistsCanonicalEvidence": False,
            "writesTeamKnowledge": False,
            "writesExperimentContract": False,
            "writesWorkflowRun": False,
        },
    }
