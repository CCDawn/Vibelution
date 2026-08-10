"""Execution envelope and worker lease contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from ._validation import (
    ContractValidationError,
    require_int,
    require_keys,
    require_sha256,
    require_text,
)


class TaskLeaseStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    STUCK = "stuck"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class NodeExecutionEnvelope:
    runId: str
    nodeRunId: str
    nodeId: str
    attempt: int
    actorType: str
    agentId: str
    taskId: str
    sessionId: str
    inputSnapshotHash: str
    idempotencyKey: str
    leaseOwner: str
    leaseExpiresAt: str
    heartbeatAt: str
    deadlineAt: str
    budgetReservationRef: str
    status: TaskLeaseStatus
    commandReceiptRef: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> NodeExecutionEnvelope:
        required = tuple(
            field for field in cls.__dataclass_fields__ if field != "commandReceiptRef"
        )
        require_keys(payload, required)
        status_raw = require_text(payload, "status")
        try:
            status = TaskLeaseStatus(status_raw)
        except ValueError as exc:
            raise ContractValidationError(
                f"unsupported execution status: {status_raw}"
            ) from exc
        return cls(
            runId=require_text(payload, "runId"),
            nodeRunId=require_text(payload, "nodeRunId"),
            nodeId=require_text(payload, "nodeId"),
            attempt=require_int(payload, "attempt", minimum=1),
            actorType=require_text(payload, "actorType"),
            agentId=str(payload.get("agentId") or "").strip(),
            taskId=str(payload.get("taskId") or "").strip(),
            sessionId=str(payload.get("sessionId") or "").strip(),
            inputSnapshotHash=require_sha256(payload, "inputSnapshotHash"),
            idempotencyKey=require_text(payload, "idempotencyKey"),
            leaseOwner=require_text(payload, "leaseOwner"),
            leaseExpiresAt=require_text(payload, "leaseExpiresAt"),
            heartbeatAt=require_text(payload, "heartbeatAt"),
            deadlineAt=require_text(payload, "deadlineAt"),
            budgetReservationRef=require_text(payload, "budgetReservationRef"),
            status=status,
            commandReceiptRef=str(payload.get("commandReceiptRef") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


@dataclass(frozen=True, slots=True)
class TaskLease:
    runId: str
    nodeRunId: str
    attempt: int
    idempotencyKey: str
    leaseOwner: str
    leaseExpiresAt: str
    heartbeatAt: str
    deadlineAt: str
    status: TaskLeaseStatus

    @classmethod
    def from_envelope(cls, envelope: NodeExecutionEnvelope) -> TaskLease:
        return cls(
            runId=envelope.runId,
            nodeRunId=envelope.nodeRunId,
            attempt=envelope.attempt,
            idempotencyKey=envelope.idempotencyKey,
            leaseOwner=envelope.leaseOwner,
            leaseExpiresAt=envelope.leaseExpiresAt,
            heartbeatAt=envelope.heartbeatAt,
            deadlineAt=envelope.deadlineAt,
            status=envelope.status,
        )
