"""Canonical evolution-lineage artifact writer.

This is the narrow projection writer behind decision #3 of the 13-decision
contract (automatic revision is bounded at two rounds and
``auto_revision_exhausted`` is a mandatory exception-review marker): it projects
already-recorded screening / review-disagreement / revision-fork outputs into
one immutable :class:`EvolutionLineage` artifact per (questionId, roundId)
scope.

The writer is append-only and replay-idempotent: an incoming event batch is
merged onto the latest stored lineage for the same scope (deduplicated by
``eventId``), the merged lineage is re-validated fail-closed by the contract,
and a fresh immutable snapshot is stored.  Exact replay of the same batch
reproduces the same snapshot hash and reuses the stored record; a conflicting
replay of an already-recorded ``eventId`` is blocked instead of overwritten.

This writer never re-runs a review, a screening, or a revision fork; missing
input yields a structured ``NEEDS_CONTEXT`` result without writing anything.
``system_policy`` actor events are recorded verbatim — the artifact never
presents a system-policy decision as a human-operator one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core.research.workflow.contracts import ContractValidationError
from core.research.workflow.contracts.evolution_lineage import (
    EVOLUTION_LINEAGE_SCHEMA_VERSION,
    EvolutionLineage,
    evolution_lineage_summary,
)

from .artifact_readback_registry import build_canonical_ref
from .human_gate_artifacts import canonical_sha256
from .workflow_artifact_store import list_workflow_artifacts, put_workflow_artifact

SCHEMA_VERSION = 1
ARTIFACT_KIND = "evolution_lineage"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _event_rows(events: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(events, (list, tuple)):
        return []
    return [dict(item) for item in events if isinstance(item, Mapping)]


def _event_fingerprint(event: Mapping[str, Any]) -> str:
    return canonical_sha256(dict(event))


def compute_lineage_input_hash(
    *,
    team_id: str,
    workflow_run_id: str,
    node_run_id: str,
    question_id: str,
    round_id: str,
    events: Sequence[Mapping[str, Any]],
) -> str:
    """Hash the full merged lineage body; identical bodies share one identity."""

    return canonical_sha256(
        {
            "teamId": _text(team_id),
            "workflowRunId": _text(workflow_run_id),
            "nodeRunId": _text(node_run_id),
            "questionId": _text(question_id),
            "roundId": _text(round_id),
            "events": [dict(event) for event in events],
        }
    )


def _binding_blockers(
    *,
    team_id: str,
    workflow_run_id: str,
    question_id: str,
    round_id: str,
) -> list[str]:
    required = {
        "teamId": team_id,
        "workflowRunId": workflow_run_id,
        "questionId": question_id,
        "roundId": round_id,
    }
    return [
        f"{field[0].lower() + field[1:]}_missing"
        for field, value in required.items()
        if not value
    ]


def _load_prior_events(
    *,
    team_id: str,
    workflow_run_id: str,
    question_id: str,
    round_id: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return the latest stored lineage events for the same scope (if any)."""

    rows = list_workflow_artifacts(
        team_id,
        kind=ARTIFACT_KIND,
        workflow_run_id=workflow_run_id,
    )
    scoped: list[dict[str, Any]] = []
    for row in rows:
        payload = _mapping(row.get("payload"))
        if (
            _text(payload.get("questionId")) == question_id
            and _text(payload.get("roundId")) == round_id
        ):
            scoped.append(payload)
    if not scoped:
        return [], []
    prior_events = _event_rows(scoped[-1].get("events"))
    if not prior_events:
        return [], ["evolution_lineage_prior_payload_invalid"]
    return prior_events, []


def _merge_events(
    prior_events: Sequence[Mapping[str, Any]],
    incoming_events: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Append incoming events onto prior ones, deduplicating by ``eventId``.

    An exact replay of an already-recorded event collapses to a no-op; the same
    ``eventId`` with different content is a fail-closed conflict, never an
    overwrite.
    """

    blockers: list[str] = []
    merged = [dict(event) for event in prior_events]
    by_event_id = {_text(event.get("eventId")): dict(event) for event in merged}
    appended = 0
    for raw in incoming_events:
        event = dict(raw)
        event_id = _text(event.get("eventId"))
        if not event_id:
            blockers.append("evolution_lineage_event_id_missing")
            continue
        existing = by_event_id.get(event_id)
        if existing is not None:
            if _event_fingerprint(existing) != _event_fingerprint(event):
                blockers.append("evolution_lineage_event_conflict")
            continue
        merged.append(event)
        by_event_id[event_id] = event
        appended += 1
    return merged, appended, blockers


def _artifact_descriptor(
    *,
    team_id: str,
    kind: str,
    source_collection_run_id: str,
    payload: Mapping[str, Any],
    record: Mapping[str, Any],
) -> dict[str, Any]:
    envelope = {
        "teamId": team_id,
        "kind": kind,
        "workflowRunId": _text(record.get("workflowRunId")),
        "sourceCollectionRunId": _text(record.get("sourceCollectionRunId"))
        or source_collection_run_id,
        "payload": dict(payload),
    }
    canonical_hash = canonical_sha256(envelope)
    return {
        "recordId": _text(record.get("recordId")),
        "kind": kind,
        "workflowRunId": _text(envelope["workflowRunId"]),
        "sourceCollectionRunId": _text(envelope["sourceCollectionRunId"]),
        "contentHash": _text(record.get("contentHash")),
        "canonicalHash": canonical_hash,
        "canonicalRef": build_canonical_ref(
            kind=kind,
            team_id=team_id,
            authority_run_id=_text(envelope["sourceCollectionRunId"]),
            content_hash=canonical_hash,
        ),
    }


def write_evolution_lineage_artifact(
    *,
    team_id: Any,
    workflow_run_id: Any,
    node_run_id: Any = "",
    question_id: Any,
    round_id: Any,
    events: Sequence[Mapping[str, Any]] | None = None,
    source_collection_run_id: Any = "",
) -> dict[str, Any]:
    """Project one event batch onto the lineage and store a validated snapshot.

    Pure projection + persistence: screenings, reviews, and revision forks are
    never re-executed.  Exact replay with the same inputs reuses the stored
    snapshot (idempotent); any blocker yields a structured ``NEEDS_CONTEXT``
    result without touching the artifact store.
    """

    team = _text(team_id)
    run = _text(workflow_run_id)
    node = _text(node_run_id)
    question = _text(question_id)
    scope_round = _text(round_id)
    source_run = _text(source_collection_run_id) or run
    binding = {
        "teamId": team,
        "workflowRunId": run,
        "nodeRunId": node,
        "questionId": question,
        "roundId": scope_round,
        "sourceCollectionRunId": source_run,
    }
    blockers = _binding_blockers(
        team_id=team,
        workflow_run_id=run,
        question_id=question,
        round_id=scope_round,
    )
    incoming = _event_rows(events)
    if not incoming:
        blockers.append("evolution_lineage_events_missing")

    lineage_result: dict[str, Any] | None = None
    if not blockers:
        prior_events, prior_blockers = _load_prior_events(
            team_id=team,
            workflow_run_id=run,
            question_id=question,
            round_id=scope_round,
        )
        blockers.extend(prior_blockers)
        if not blockers:
            merged_events, appended, merge_blockers = _merge_events(
                prior_events, incoming
            )
            blockers.extend(merge_blockers)
            if not blockers:
                payload = {
                    "schemaVersion": EVOLUTION_LINEAGE_SCHEMA_VERSION,
                    "artifactKind": ARTIFACT_KIND,
                    "lineageId": f"evolution-lineage:{question}:{scope_round}",
                    **binding,
                    "inputHash": compute_lineage_input_hash(
                        team_id=team,
                        workflow_run_id=run,
                        node_run_id=node,
                        question_id=question,
                        round_id=scope_round,
                        events=merged_events,
                    ),
                    "events": merged_events,
                }
                try:
                    lineage = EvolutionLineage.from_dict(payload)
                except ContractValidationError:
                    lineage = None
                    blockers.append("evolution_lineage_invalid")
                if lineage is not None:
                    record = put_workflow_artifact(
                        team,
                        kind=ARTIFACT_KIND,
                        workflow_run_id=run,
                        source_collection_run_id=source_run,
                        artifact_identity=(
                            f"{ARTIFACT_KIND}:{node}:{question}:{scope_round}"
                            f":{payload['inputHash']}"
                        ),
                        payload=payload,
                    )
                    summary = evolution_lineage_summary(lineage)
                    lineage_result = {
                        "artifact": _artifact_descriptor(
                            team_id=team,
                            kind=ARTIFACT_KIND,
                            source_collection_run_id=source_run,
                            payload=payload,
                            record=record,
                        ),
                        "eventCount": len(lineage.events),
                        "appendedEventCount": appended,
                        "revisionRoundCount": summary["revisionRoundCount"],
                        "mandatoryExceptionReview": bool(
                            summary["mandatoryExceptionReview"]
                        ),
                        "summary": summary,
                    }

    if blockers or lineage_result is None:
        return {
            "status": "blocked",
            "reason": "NEEDS_CONTEXT",
            "blockerCodes": list(dict.fromkeys(blockers)),
            "binding": binding,
            "evolutionLineage": None,
        }
    return {
        "status": "written",
        "reason": "",
        "blockerCodes": [],
        "binding": binding,
        "evolutionLineage": lineage_result,
    }


# A descriptive alias keeps callers independent from the storage verb.
write_lineage_artifact = write_evolution_lineage_artifact


__all__ = [
    "ARTIFACT_KIND",
    "SCHEMA_VERSION",
    "compute_lineage_input_hash",
    "write_evolution_lineage_artifact",
    "write_lineage_artifact",
]
