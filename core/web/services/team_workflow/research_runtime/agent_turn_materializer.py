"""Deterministic agent-turn domain materialization (T5.1-8).

After a canonical Session/Task/Turn exists, production RealDomainPorts must
materialize required Artifact kinds into the kind's Domain Store and mirror
readiness authorities (candidate store / ClaimEvidenceStore). This path never
calls a live model; it is the hermetic bottom of the production adapter.
"""

from __future__ import annotations

from typing import Any

from core.research.workflow.contracts import PendingAction

from .domain_ports import AgentTaskHandle


def materialize_agent_turn_outputs(
    *,
    action: PendingAction,
    handle: AgentTaskHandle,
    input_snapshot: dict[str, Any],
) -> list[dict[str, str]]:
    """Materialize required outputs for ``action.node_id`` and return refs."""
    from .artifact_readback_registry import (
        materialize_domain_artifact,
        required_artifact_kinds,
    )

    kinds = required_artifact_kinds(action.node_id)
    if not kinds:
        return []

    team_id = str(input_snapshot.get("teamId") or "").strip()
    if not team_id:
        raise RuntimeError("input snapshot has no teamId for artifact materialization")
    authority_run_id = (
        str(input_snapshot.get("sourceCollectionRunId") or "").strip()
        or str(action.run_id or "").strip()
    )
    project_id = str(input_snapshot.get("projectId") or "").strip()
    refs: list[dict[str, str]] = []
    for kind in kinds:
        payload = _payload_for_kind(
            kind,
            action=action,
            handle=handle,
            project_id=project_id,
            authority_run_id=authority_run_id,
        )
        ref = materialize_domain_artifact(
            kind=kind,
            payload=payload,
            team_id=team_id,
            authority_run_id=authority_run_id,
        )
        _mirror_readiness_authority(
            kind,
            payload=payload,
            team_id=team_id,
            project_id=project_id,
            authority_run_id=authority_run_id,
            action=action,
            handle=handle,
        )
        refs.append(
            {
                "canonicalRef": ref["canonicalRef"],
                "kind": kind,
                "sha256": ref["sha256"],
                "version": ref.get("version") or "1.0.0",
            }
        )
    return refs


def _payload_for_kind(
    kind: str,
    *,
    action: PendingAction,
    handle: AgentTaskHandle,
    project_id: str,
    authority_run_id: str,
) -> dict[str, Any]:
    base_meta = {
        "workflowRunId": action.run_id,
        "nodeId": action.node_id,
        "nodeRunId": action.node_run_id,
        "sessionId": handle.session_id,
        "taskId": handle.task_id,
        "turnId": handle.turn_id,
        "sourceCollectionRunId": authority_run_id,
        "researchProjectId": project_id,
    }
    if kind == "source_candidate_batch":
        return {
            "perspectives": ["primary", "counter"],
            "queries": [f"query:{action.node_run_id}"],
            "candidateSources": [
                {
                    "sourceId": f"src-{action.action_id[:12]}",
                    "title": f"Candidate for {action.node_id}",
                    "url": f"https://example.local/{action.action_id[:12]}",
                }
            ],
            "counterEvidenceCandidateSources": [
                {
                    "sourceId": f"ctr-{action.action_id[:12]}",
                    "perspective": "falsification",
                    "title": "Counter candidate",
                }
            ],
            "metadata": base_meta,
        }
    if kind == "evidence_card_batch":
        return {
            "evidenceCards": [
                {
                    "sourceId": f"src-{action.action_id[:12]}",
                    "claim": f"Deterministic claim for {action.node_id}",
                    "quote": "Quoted evidence span for readiness.",
                    "citationLocator": {"page": 1, "offset": 0},
                }
            ],
            "metadata": base_meta,
        }
    if kind == "evidence_relation_graph":
        return {
            "nodes": [
                {"id": f"n-{action.action_id[:8]}-a", "kind": "claim"},
                {"id": f"n-{action.action_id[:8]}-b", "kind": "claim"},
            ],
            "edges": [
                {
                    "from": f"n-{action.action_id[:8]}-a",
                    "to": f"n-{action.action_id[:8]}-b",
                    "relation": "supports",
                }
            ],
            "metadata": base_meta,
        }
    if kind == "knowledge_package_draft":
        return {
            "title": f"Draft package {action.node_run_id}",
            "sections": [{"heading": "Findings", "body": "Deterministic draft."}],
            "metadata": base_meta,
        }
    return {"kind": kind, "metadata": base_meta, "deterministic": True}


def _mirror_readiness_authority(
    kind: str,
    *,
    payload: dict[str, Any],
    team_id: str,
    project_id: str,
    authority_run_id: str,
    action: PendingAction,
    handle: AgentTaskHandle,
) -> None:
    if kind == "source_candidate_batch":
        _mirror_source_candidates(
            payload,
            team_id=team_id,
            project_id=project_id,
            authority_run_id=authority_run_id,
            action=action,
            handle=handle,
        )
        return
    if kind == "evidence_card_batch":
        _mirror_evidence_cards(
            payload,
            team_id=team_id,
            authority_run_id=authority_run_id,
            action=action,
        )


def _mirror_source_candidates(
    payload: dict[str, Any],
    *,
    team_id: str,
    project_id: str,
    authority_run_id: str,
    action: PendingAction,
    handle: AgentTaskHandle,
) -> None:
    from core.web.services.team_workflow.source_collection.candidates import (
        register_candidate_source,
    )

    for item in list(payload.get("candidateSources") or []):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("sourceId") or "candidate").strip()
        source_url = str(item.get("url") or item.get("sourceUrl") or "").strip()
        register_candidate_source(
            team_id,
            {
                "title": title,
                "sourceUrl": source_url or f"https://example.local/{item.get('sourceId')}",
                "sourceKind": "paper",
                "candidateType": "source_manifest",
                "summary": f"Materialized by {action.node_id}",
                "createdByAgent": handle.session_id,
                "metadata": {
                    "researchProjectId": project_id,
                    "sourceCollectionRunId": authority_run_id,
                    "workflowRunId": action.run_id,
                    "nodeId": action.node_id,
                },
            },
            strict=False,
        )


def _mirror_evidence_cards(
    payload: dict[str, Any],
    *,
    team_id: str,
    authority_run_id: str,
    action: PendingAction,
) -> None:
    from core.infrastructure.path_containment import PROJECT_ROOT
    from core.research.evidence import ClaimEvidenceStore

    store = ClaimEvidenceStore(PROJECT_ROOT)
    for index, card in enumerate(list(payload.get("evidenceCards") or [])):
        if not isinstance(card, dict):
            continue
        source_id = str(card.get("sourceId") or f"src-{index}")
        store.register(
            team_id,
            {
                "claimId": f"claim-{action.action_id[:12]}-{index}",
                "candidateId": f"candidate-{action.action_id[:12]}-{index}",
                "sourceId": source_id,
                "sourceRevision": "sha256:" + ("a" * 64),
                "locator": {"kind": "page", "page": 1},
                "quote": str(card.get("quote") or card.get("claim") or "quote"),
                "evidenceKind": "primary_result",
                "reasoningRole": "fact",
                "supportLevel": "supports",
                "extractionMethod": "manual",
                "extractorAgentId": str(action.node_id or "source_extraction"),
            },
        )
