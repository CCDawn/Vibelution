"""Append-only Challenge Cup V3 scientific facts in the Workflow Ledger."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from core.research.workflow.contracts.challenge_cup_stage_one_v3 import (
    ScientificSemanticRecord,
)
from core.research.workflow.ledger import EventRecord, WorkflowLedgerStore


SCIENTIFIC_SEMANTIC_EVENT_TYPE = "scientific_semantic_recorded.v3"
SCIENTIFIC_SEMANTIC_CONTRACT_VERSION = "3.0.0"
CHALLENGE_CUP_WORKFLOW_ID = "challenge-cup-research"


class ScientificSemanticRecordConflict(RuntimeError):
    """One immutable record ref was reused for different scientific facts."""


def _required_ref(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _event_id(run_id: str, record_ref: str) -> str:
    identity = f"{run_id}\0{record_ref}".encode("utf-8")
    return "evt-semantic-v3-" + hashlib.sha256(identity).hexdigest()[:24]


def _payload(
    *,
    record_ref: str,
    subject_ref: str,
    semantic: ScientificSemanticRecord,
    recorded_at_ms: int,
) -> dict[str, Any]:
    if recorded_at_ms <= 0:
        raise ValueError("recorded_at_ms must be positive")
    semantic_payload = semantic.model_dump(
        mode="json",
        exclude_none=True,
        exclude_computed_fields=True,
    )
    if not any(semantic_payload.values()):
        raise ValueError("scientific semantic record must contain at least one object")
    return {
        "contractVersion": SCIENTIFIC_SEMANTIC_CONTRACT_VERSION,
        "recordRef": record_ref,
        "subjectRef": subject_ref,
        "semantic": semantic_payload,
        "recordedAtMs": int(recorded_at_ms),
    }


def _public_record(event: EventRecord) -> dict[str, Any]:
    payload = json.loads(event.payload_json)
    if not isinstance(payload, dict):
        raise ValueError("scientific semantic event payload must be an object")
    if payload.get("contractVersion") != SCIENTIFIC_SEMANTIC_CONTRACT_VERSION:
        raise ValueError("scientific semantic event contract version is invalid")
    semantic = ScientificSemanticRecord.model_validate(payload.get("semantic"))
    return {
        "eventId": event.event_id,
        "runId": event.run_id,
        "sequence": event.sequence,
        "runVersion": event.run_version,
        "recordRef": _required_ref(str(payload.get("recordRef") or ""), "recordRef"),
        "subjectRef": _required_ref(str(payload.get("subjectRef") or ""), "subjectRef"),
        "semantic": semantic.model_dump(
            mode="json",
            exclude_none=True,
            exclude_computed_fields=True,
        ),
        "recordedAtMs": int(payload.get("recordedAtMs") or 0),
        "actor": json.loads(event.actor_json),
    }


def append_scientific_semantic_record(
    store: WorkflowLedgerStore,
    *,
    run_id: str,
    record_ref: str,
    subject_ref: str,
    semantic: ScientificSemanticRecord,
    actor_type: Literal["person", "software_agent"],
    actor_ref: str,
    recorded_at_ms: int,
) -> dict[str, Any]:
    """Append one immutable V3 record, replaying only byte-identical facts."""

    normalized_run_id = _required_ref(run_id, "run_id")
    normalized_record_ref = _required_ref(record_ref, "record_ref")
    normalized_subject_ref = _required_ref(subject_ref, "subject_ref")
    normalized_actor_ref = _required_ref(actor_ref, "actor_ref")
    if actor_type not in {"person", "software_agent"}:
        raise ValueError("actor_type must be person or software_agent")
    normalized_semantic = ScientificSemanticRecord.model_validate(semantic)
    payload_json = _canonical_json(
        _payload(
            record_ref=normalized_record_ref,
            subject_ref=normalized_subject_ref,
            semantic=normalized_semantic,
            recorded_at_ms=recorded_at_ms,
        )
    )
    actor_json = _canonical_json(
        {"agentType": actor_type, "associatedAgentRef": normalized_actor_ref}
    )
    event_id = _event_id(normalized_run_id, normalized_record_ref)

    def mutate(uow: Any) -> EventRecord:
        existing = uow.repository.get_event_by_id(event_id)
        if existing is not None:
            if (
                existing.run_id == normalized_run_id
                and existing.event_type == SCIENTIFIC_SEMANTIC_EVENT_TYPE
                and existing.payload_json == payload_json
                and existing.actor_json == actor_json
            ):
                return existing
            raise ScientificSemanticRecordConflict(
                "semantic record ref already identifies different facts"
            )
        run = uow.repository.get_run(normalized_run_id)
        if run is None:
            raise ValueError("workflow run does not exist")
        if run.workflow_id != CHALLENGE_CUP_WORKFLOW_ID:
            raise ValueError("scientific semantics require a Challenge Cup workflow")
        sequence = uow.repository.advance_last_sequence(
            normalized_run_id, 1, recorded_at_ms
        )
        if sequence is None:
            raise ValueError("workflow run does not exist")
        event = EventRecord(
            run_id=normalized_run_id,
            sequence=sequence,
            event_id=event_id,
            run_version=run.run_version,
            event_type=SCIENTIFIC_SEMANTIC_EVENT_TYPE,
            actor_json=actor_json,
            correlation_id=normalized_record_ref,
            causation_id=None,
            payload_json=payload_json,
            occurred_at_ms=recorded_at_ms,
        )
        uow.repository.insert_event(event)
        return event

    event = store.submit(mutate, force_flush=True).result(timeout=30)
    return _public_record(event)


def list_scientific_semantic_records(
    store: WorkflowLedgerStore, run_id: str
) -> list[dict[str, Any]]:
    """Read and strictly validate all V3 semantic records for one run."""

    normalized_run_id = _required_ref(run_id, "run_id")
    events = store.read(
        lambda repository: repository.list_events(
            normalized_run_id, after_sequence=0, limit=1_000_000
        )
    )
    return [
        _public_record(event)
        for event in events
        if event.event_type == SCIENTIFIC_SEMANTIC_EVENT_TYPE
    ]


__all__ = [
    "CHALLENGE_CUP_WORKFLOW_ID",
    "SCIENTIFIC_SEMANTIC_CONTRACT_VERSION",
    "SCIENTIFIC_SEMANTIC_EVENT_TYPE",
    "ScientificSemanticRecordConflict",
    "append_scientific_semantic_record",
    "list_scientific_semantic_records",
]
