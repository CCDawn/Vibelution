"""Handoff lineage rules: definition edgeId identity, append-only attempts.

Owns uniqueness and supersede semantics so service.py only orchestrates.
"""

from __future__ import annotations

from typing import Any

from core.research.workflow.models import WorkflowDefinition

from .handoff_builder import build_handoff_record, definition_edge, edges_between_completed


ACTIVE_HANDOFF_STATUSES = frozenset(
    {"pending", "ready", "waiting_human", "accepted", "rejected", "failed"}
)


def handoff_edge_id(handoff: dict[str, Any]) -> str:
    """Canonical identity for a handoff is the definition edgeId."""
    edge_id = str(handoff.get("edgeId") or "").strip()
    if edge_id:
        return edge_id
    from_id = str(handoff.get("fromNodeId") or "")
    to_id = str(handoff.get("toNodeId") or "")
    if from_id and to_id:
        edge = definition_edge(from_id, to_id)
        if edge and edge.get("edgeId"):
            return str(edge["edgeId"])
        return f"{from_id}->{to_id}"
    return ""


def definition_edge_id(from_node_id: str, to_node_id: str) -> str:
    edge = definition_edge(from_node_id, to_node_id)
    if edge and edge.get("edgeId"):
        return str(edge["edgeId"])
    return f"{from_node_id}->{to_node_id}"


def existing_active_edge_ids(handoffs: list[dict[str, Any]]) -> set[str]:
    """EdgeIds that already have a non-superseded lineage record."""
    ids: set[str] = set()
    for handoff in handoffs:
        status = str(handoff.get("status") or "")
        if status == "superseded":
            continue
        edge_id = handoff_edge_id(handoff)
        if edge_id:
            ids.add(edge_id)
    return ids


def find_active_handoff_for_edge(
    handoffs: list[dict[str, Any]], edge_id: str
) -> dict[str, Any] | None:
    for handoff in reversed(handoffs):
        if handoff_edge_id(handoff) != edge_id:
            continue
        if str(handoff.get("status") or "") == "superseded":
            continue
        return handoff
    return None


def mark_superseded(handoff: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with status superseded; never deletes history fields."""
    return {**handoff, "status": "superseded"}


def append_handoff_attempt(
    handoffs: list[dict[str, Any]],
    new_handoff: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Append a new attempt for an edge, superseding any prior active attempt.

    Returns (normalized_new_handoff, full_lineage_list).
    Does not delete prior records; prior active row is marked superseded in-place
    within the returned list (append-only identity of handoffId preserved).
    """
    lineage = [dict(h) for h in handoffs]
    edge_id = handoff_edge_id(new_handoff)
    if not edge_id:
        raise ValueError("handoff attempt requires edgeId")

    prior = find_active_handoff_for_edge(lineage, edge_id)
    attempt = dict(new_handoff)
    attempt["edgeId"] = edge_id
    if prior is not None:
        prior_id = str(prior.get("handoffId") or "")
        for index, item in enumerate(lineage):
            if str(item.get("handoffId") or "") == prior_id:
                lineage[index] = mark_superseded(item)
                break
        attempt.setdefault("supersedesHandoffId", prior_id)
        prior_attempt = int(prior.get("nodeAttempt") or 1)
        attempt.setdefault("nodeAttempt", prior_attempt + 1)
    else:
        attempt.setdefault("nodeAttempt", int(attempt.get("nodeAttempt") or 1))
        attempt.setdefault("supersedesHandoffId", attempt.get("supersedesHandoffId") or "")

    lineage.append(attempt)
    return attempt, lineage


def should_skip_auto_handoff(existing_edge_ids: set[str], from_id: str, to_id: str) -> bool:
    edge_id = definition_edge_id(from_id, to_id)
    return edge_id in existing_edge_ids


def build_auto_handoffs_for_completed(
    *,
    run_id: str,
    workflow_id: str,
    workflow_version_id: str,
    completed: list[str],
    artifacts: dict[str, Any],
    existing_edge_ids: set[str],
    definition: WorkflowDefinition | None = None,
) -> list[dict[str, Any]]:
    """Create accepted auto handoffs for completed edges not yet in lineage."""
    created: list[dict[str, Any]] = []
    for from_id, to_id in edges_between_completed(
        completed,
        definition=definition,
    ):
        edge = definition_edge(from_id, to_id, definition=definition)
        edge_id = str((edge or {}).get("edgeId") or f"{from_id}->{to_id}")
        if edge_id in existing_edge_ids:
            continue
        record = build_handoff_record(
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_version_id=workflow_version_id,
            from_node_id=from_id,
            to_node_id=to_id,
            status="accepted",
            artifacts=artifacts,
            definition=definition,
        )
        # Ensure edgeId is definition identity even if builder fell back.
        record["edgeId"] = edge_id
        record.setdefault("nodeAttempt", 1)
        created.append(record)
        existing_edge_ids.add(edge_id)
    return created
