"""Build NodeHandoffRecord dicts from definition edges (ADR 0007)."""

from __future__ import annotations

import uuid
from typing import Any

from core.research.workflow.definition import build_challenge_cup_workflow_definition


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def definition_edge(from_node_id: str, to_node_id: str) -> dict[str, Any] | None:
    for edge in build_challenge_cup_workflow_definition().edges:
        if edge.fromNodeId == from_node_id and edge.toNodeId == to_node_id:
            return edge.to_dict()
    return None


def successor_node(from_node_id: str) -> str | None:
    for edge in build_challenge_cup_workflow_definition().edges:
        if edge.fromNodeId == from_node_id:
            return edge.toNodeId
    return None


def artifact_kind_for_gate(from_node_id: str) -> str:
    mapping = {
        "knowledge_handoff": "knowledge_package",
        "protocol_freeze": "frozen_protocol",
        "smoke_gate": "smoke_release",
        "candidate_promotion": "promotion_proposal",
        "knowledge_ingestion": "knowledge_package_draft",
        "source_finding": "source_candidate_batch",
        "source_extraction": "evidence_card_batch",
        "evidence_relations": "evidence_relation_graph",
        "hypothesis_design": "hypothesis_set",
        "protocol_design": "protocol_draft",
        "protocol_review": "protocol_review_report",
        "controlled_run": "run_artifacts",
        "result_evaluation": "evaluation_report",
        "iteration_decision": "iteration_decision",
        "version_governance": "version_governance_record",
        "result_package": "research_result_package",
    }
    return mapping.get(from_node_id, "artifact")


def build_handoff_record(
    *,
    run_id: str,
    workflow_id: str,
    workflow_version_id: str,
    from_node_id: str,
    to_node_id: str | None = None,
    status: str,
    artifacts: dict[str, Any] | None = None,
    from_node_run_id: str = "",
    to_node_run_id: str = "",
    accepted_by: str = "",
    rejection_reason: str = "",
    supersedes_handoff_id: str = "",
    human_task_id: str = "",
) -> dict[str, Any]:
    target = to_node_id or successor_node(from_node_id) or ""
    edge = definition_edge(from_node_id, target) if target else None
    kind = artifact_kind_for_gate(from_node_id)
    artifacts = artifacts or {}
    content_hash = str(artifacts.get(kind) or artifacts.get("knowledge_package") or f"hash:{kind}:{run_id}")
    refs = [
        {
            "artifactId": f"{kind}:{run_id}:{from_node_id}",
            "kind": kind,
            "version": "1",
            "contentHash": content_hash,
        }
    ]
    # Smoke handoff also carries frozen protocol ref when present.
    if from_node_id == "smoke_gate" and artifacts.get("frozen_protocol"):
        refs.append(
            {
                "artifactId": f"frozen_protocol:{run_id}",
                "kind": "frozen_protocol",
                "version": "1",
                "contentHash": str(artifacts.get("frozen_protocol")),
            }
        )
    return {
        "handoffId": f"ho-{uuid.uuid4().hex[:10]}",
        "workflowId": workflow_id,
        "workflowVersionId": workflow_version_id,
        "runId": run_id,
        "fromNodeId": from_node_id,
        "fromNodeRunId": from_node_run_id or f"nr-{from_node_id}",
        "toNodeId": target,
        "toNodeRunId": to_node_run_id,
        "gateKind": (edge or {}).get("gateKind") or "auto",
        "edgeId": (edge or {}).get("edgeId") or f"{from_node_id}->{target}",
        "outputArtifactRefs": refs if status == "accepted" else [],
        "inputSnapshotHash": content_hash if status == "accepted" else "",
        "status": status,
        "offeredAt": _utc_now(),
        "acceptedAt": _utc_now() if status == "accepted" else "",
        "acceptedBy": accepted_by if status == "accepted" else "",
        "rejectionReason": rejection_reason if status == "rejected" else "",
        "supersedesHandoffId": supersedes_handoff_id,
        "humanTaskId": human_task_id,
    }


def edges_between_completed(completed: list[str]) -> list[tuple[str, str]]:
    """Return definition edges whose endpoints are both in completed, in definition order."""
    done = set(completed)
    pairs: list[tuple[str, str]] = []
    for edge in build_challenge_cup_workflow_definition().edges:
        if edge.fromNodeId in done and edge.toNodeId in done:
            pairs.append((edge.fromNodeId, edge.toNodeId))
    return pairs
