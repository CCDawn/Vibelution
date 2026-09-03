"""WorkflowCommand contract: CommandRequest / CommandReceipt / CommandOffer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ._canonical import sha256_hex


class WorkflowCommandKind(str, Enum):
    START_NODE = "start_node"
    RETRY_NODE = "retry_node"
    CANCEL_NODE = "cancel_node"
    RESOLVE_HUMAN_TASK = "resolve_human_task"
    REBIND_NODE = "rebind_node"
    FORK_REVISION = "fork_revision"
    EXTEND_BUDGET = "extend_budget"
    CANCEL_RUN = "cancel_run"
    ARCHIVE_RUN = "archive_run"
    RECONCILE_RUN = "reconcile_run"
    # Knowledge sideflow facade (plan §4.6): team-authorized sessions may
    # request/inspect a knowledge collection at allowed nodes.  Deliberately
    # NOT operator-only — the privileged-command set is unchanged.
    ENSURE_KNOWLEDGE_COLLECTION = "ensure_knowledge_collection"
    INSPECT_KNOWLEDGE_COLLECTION = "inspect_knowledge_collection"
    # Stage-one G1 closeout operator commands (Challenge Program flow).  Both
    # are ledger-authoritative first-class commands: the build registers the
    # canonical result package, the finalize promotes the pending closeout
    # after a fresh approved Program readback.
    BUILD_STAGE_ONE_PACKAGE = "build_stage_one_package"
    FINALIZE_STAGE_ONE = "finalize_stage_one"


@dataclass(frozen=True, slots=True)
class ActorRef:
    actor_type: str
    actor_id: str

    def to_dict(self) -> dict[str, Any]:
        return {"actorType": self.actor_type, "actorId": self.actor_id}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ActorRef:
        return cls(
            actor_type=str(payload.get("actorType") or ""),
            actor_id=str(payload.get("actorId") or ""),
        )


@dataclass(frozen=True, slots=True)
class CommandRequest:
    command_id: str
    run_id: str
    team_id: str
    command: WorkflowCommandKind
    node_id: str | None
    expected_run_version: int
    idempotency_key: str
    payload: Mapping[str, Any]
    requested_by: ActorRef
    requested_at_ms: int

    def request_hash(self) -> str:
        """Client-supplied body minus server time and commandId (spec 5.6)."""
        body: dict[str, Any] = {
            "teamId": self.team_id,
            "runId": self.run_id,
            "command": self.command.value,
        }
        if self.node_id:
            body["nodeId"] = self.node_id
        body["expectedRunVersion"] = self.expected_run_version
        body["idempotencyKey"] = self.idempotency_key
        body["payload"] = dict(self.payload)
        body["requestedBy"] = self.requested_by.to_dict()
        return sha256_hex(body)


@dataclass(frozen=True, slots=True)
class ConfirmationContract:
    title: str
    body: str
    confirm_label: str
    cancel_label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "body": self.body,
            "confirmLabel": self.confirm_label,
            "cancelLabel": self.cancel_label,
        }


@dataclass(frozen=True, slots=True)
class CommandOffer:
    command: WorkflowCommandKind
    node_id: str | None
    available: bool
    label: str
    reason_code: str
    blocker_ids: tuple[str, ...]
    idempotency_key: str
    expected_run_version: int
    payload: Mapping[str, Any] = field(default_factory=dict)
    destructive: bool = False
    confirmation: ConfirmationContract | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "command": self.command.value,
            "nodeId": self.node_id,
            "available": self.available,
            "label": self.label,
            "reasonCode": self.reason_code,
            "blockerIds": list(self.blocker_ids),
            "idempotencyKey": self.idempotency_key,
            "expectedRunVersion": self.expected_run_version,
            "payload": dict(self.payload),
            "destructive": self.destructive,
        }
        if self.confirmation:
            payload["confirmation"] = self.confirmation.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    command_id: str
    run_id: str
    status: str
    accepted_run_version: int | None
    idempotency_key: str
    latest_event_sequence: int
    problem: Any | None = None
    # Optional command-specific result payload (e.g. knowledge invocation
    # facts).  ``None`` keeps the historical wire shape byte-identical.
    result: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "commandId": self.command_id,
            "runId": self.run_id,
            "status": self.status,
            "acceptedRunVersion": self.accepted_run_version,
            "idempotencyKey": self.idempotency_key,
            "latestEventSequence": self.latest_event_sequence,
            "problem": self.problem,
        }
        if self.result is not None:
            payload["result"] = dict(self.result)
        return payload
