"""Canonical writer for the Challenge Cup problem-understanding artifact.

The problem-understanding artifact is deliberately small and schema-shaped.  It
is the only accepted input contract for ``source_finding``; task summaries and
search result projections are not allowed to backfill it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .artifact_readback_registry import build_canonical_ref
from .human_gate_artifacts import canonical_sha256
from .workflow_artifact_store import put_workflow_artifact

PROBLEM_UNDERSTANDING_KIND = "problem_understanding"
HUMAN_GATE_DECISIONS = frozenset(
    {"pending", "approved", "revision_requested", "rejected"}
)
_REQUIRED_FIELDS = frozenset(
    {"scope", "subquestions", "assumptions", "known_unknowns", "human_gate"}
)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"problemUnderstanding.{field} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"problemUnderstanding.{field} must be an array")
    result: list[str] = []
    for item in value:
        text = _text(item, f"{field}[]")
        if text in result:
            raise ValueError(f"problemUnderstanding.{field} must contain unique values")
        result.append(text)
    return result


def validate_problem_understanding(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and detach the exact v2 ``problemUnderstanding`` shape."""

    if not isinstance(value, Mapping):
        raise ValueError("problemUnderstanding must be an object")
    supplied = set(value)
    missing = _REQUIRED_FIELDS - supplied
    extra = supplied - _REQUIRED_FIELDS
    if missing:
        raise ValueError(f"problemUnderstanding missing fields: {sorted(missing)}")
    if extra:
        raise ValueError(f"problemUnderstanding has unsupported fields: {sorted(extra)}")
    gate = value.get("human_gate")
    if not isinstance(gate, Mapping):
        raise ValueError("problemUnderstanding.human_gate must be an object")
    gate_keys = set(gate)
    allowed_gate_keys = {"required", "decision", "reviewer", "decided_at", "rationale"}
    if gate_keys - allowed_gate_keys:
        raise ValueError("problemUnderstanding.human_gate has unsupported fields")
    if gate.get("required") is not True:
        raise ValueError("problemUnderstanding.human_gate.required must be true")
    decision = gate.get("decision")
    if decision not in HUMAN_GATE_DECISIONS:
        raise ValueError("problemUnderstanding.human_gate.decision is invalid")
    normalized_gate: dict[str, Any] = {
        "required": True,
        "decision": decision,
        "rationale": _text(gate.get("rationale"), "human_gate.rationale"),
    }
    for field in ("reviewer", "decided_at"):
        if field in gate:
            normalized_gate[field] = _text(gate.get(field), f"human_gate.{field}")
    return {
        "scope": _text(value.get("scope"), "scope"),
        "subquestions": _string_list(value.get("subquestions"), "subquestions"),
        "assumptions": _string_list(value.get("assumptions"), "assumptions"),
        "known_unknowns": _string_list(value.get("known_unknowns"), "known_unknowns"),
        "human_gate": normalized_gate,
    }


def write_problem_understanding_artifact(
    *,
    team_id: str,
    workflow_run_id: str,
    problem_understanding: Mapping[str, Any],
    source_collection_run_id: str = "",
    node_run_id: str = "",
) -> dict[str, Any]:
    """Validate and append one immutable canonical artifact, idempotently."""

    payload = validate_problem_understanding(problem_understanding)
    run_id = str(workflow_run_id or "").strip()
    identity = str(node_run_id or "").strip() or f"problem-understanding:{run_id}"
    record = put_workflow_artifact(
        team_id,
        kind=PROBLEM_UNDERSTANDING_KIND,
        workflow_run_id=run_id,
        source_collection_run_id=str(source_collection_run_id or "").strip() or run_id,
        artifact_identity=identity,
        payload=payload,
    )
    envelope = {
        "teamId": str(team_id or "").strip(),
        "kind": PROBLEM_UNDERSTANDING_KIND,
        "workflowRunId": str(record.get("workflowRunId") or run_id),
        "sourceCollectionRunId": str(record.get("sourceCollectionRunId") or run_id),
        "payload": payload,
    }
    content_hash = canonical_sha256(envelope)
    return {
        "artifact": record,
        "canonicalRef": build_canonical_ref(
            kind=PROBLEM_UNDERSTANDING_KIND,
            team_id=str(team_id or "").strip(),
            authority_run_id=str(record.get("sourceCollectionRunId") or run_id),
            content_hash=content_hash,
        ),
        "contentHash": content_hash,
        "payload": payload,
    }


__all__ = [
    "HUMAN_GATE_DECISIONS",
    "PROBLEM_UNDERSTANDING_KIND",
    "validate_problem_understanding",
    "write_problem_understanding_artifact",
]
