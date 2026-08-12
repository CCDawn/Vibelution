"""WorkflowEventEnvelope and the event payload registry (spec 12.1)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class WorkflowEventType(str, Enum):
    RUN_CREATED = "run_created"
    COMMAND_ACCEPTED = "command_accepted"
    COMMAND_FAILED = "command_failed"
    NODE_STARTING = "node_starting"
    NODE_RUNNING = "node_running"
    NODE_WAITING_HUMAN = "node_waiting_human"
    NODE_SUCCEEDED = "node_succeeded"
    NODE_FAILED = "node_failed"
    NODE_BLOCKED = "node_blocked"
    HANDOFF_READY = "handoff_ready"
    HANDOFF_ACCEPTED = "handoff_accepted"
    HANDOFF_REJECTED = "handoff_rejected"
    BUDGET_RESERVED = "budget_reserved"
    BUDGET_SETTLED = "budget_settled"
    EXECUTION_ANCHOR_BOUND = "execution_anchor_bound"
    ARTIFACT_VERIFIED = "artifact_verified"
    RUN_FORKED = "run_forked"
    RUN_BLOCKED = "run_blocked"
    RUN_SUCCEEDED = "run_succeeded"
    RECONCILIATION_REQUIRED = "reconciliation_required"


@dataclass(frozen=True, slots=True)
class WorkflowEventEnvelope:
    event_id: str
    sequence: int
    team_id: str
    workflow_id: str
    workflow_version_id: str
    run_id: str
    run_version: int
    event_type: WorkflowEventType
    actor: Mapping[str, str]
    correlation_id: str
    causation_id: str | None
    payload: Mapping[str, Any]
    occurred_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "eventId": self.event_id,
            "sequence": self.sequence,
            "teamId": self.team_id,
            "workflowId": self.workflow_id,
            "workflowVersionId": self.workflow_version_id,
            "runId": self.run_id,
            "runVersion": self.run_version,
            "type": self.event_type.value,
            "actor": dict(self.actor),
            "correlationId": self.correlation_id,
            "occurredAtMs": self.occurred_at_ms,
            "payload": dict(self.payload),
        }
        if self.causation_id:
            payload["causationId"] = self.causation_id
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorkflowEventEnvelope:
        return cls(
            event_id=str(payload.get("eventId") or ""),
            sequence=int(payload.get("sequence") or 0),
            team_id=str(payload.get("teamId") or ""),
            workflow_id=str(payload.get("workflowId") or ""),
            workflow_version_id=str(payload.get("workflowVersionId") or ""),
            run_id=str(payload.get("runId") or ""),
            run_version=int(payload.get("runVersion") or 0),
            event_type=WorkflowEventType(str(payload.get("type") or "")),
            actor=dict(payload.get("actor") or {}),
            correlation_id=str(payload.get("correlationId") or ""),
            causation_id=payload.get("causationId"),
            payload=dict(payload.get("payload") or {}),
            occurred_at_ms=int(payload.get("occurredAtMs") or 0),
        )
