"""Knowledge sideflow contracts: invocation states and the cross-run event.

The producer (knowledge_sideflow child run) and the consumer (parent run)
exchange exactly one typed payload through the durable ``event_publish``
outbox: ``knowledge_result_available``.  Delivery is at-least-once, so the
consumer deduplicates on
``knowledge-result:<invocationId>:<packageContentHash>``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ._validation import ContractValidationError, require_sha256, require_text

KNOWLEDGE_RESULT_AVAILABLE_EVENT_TYPE = "knowledge_result_available"


class KnowledgeInvocationStatus(str, Enum):
    """Lifecycle of one knowledge-collection invocation."""

    PENDING = "pending"
    CHILD_CREATED = "child_created"
    RUNNING = "running"
    AWAITING_HANDOFF = "awaiting_handoff"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


KNOWLEDGE_INVOCATION_TERMINAL_STATUSES = frozenset(
    {
        KnowledgeInvocationStatus.COMPLETED.value,
        KnowledgeInvocationStatus.FAILED.value,
        KnowledgeInvocationStatus.CANCELLED.value,
    }
)


class KnowledgeHandoffState(str, Enum):
    """Cross-run handoff consumption state of the produced package.

    Deliberately NOT spelled ``handoffStatus``: that spelling belongs to the
    hypothesis-first projection layer, where ``collection_request_state`` now
    emits a real ``handoffStatus`` (accepted/pending/failed/needs_context)
    derived from its own child-run and handoff facts.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class KnowledgeResultAvailablePayload:
    """Typed payload carried by one ``event_publish`` outbox action."""

    producerRunId: str
    consumerRunId: str
    invocationId: str
    knowledgePackageRef: str
    packageContentHash: str
    sourceManifestRef: str
    handoffDecisionRef: str
    correlationId: str

    @property
    def eventType(self) -> str:
        return KNOWLEDGE_RESULT_AVAILABLE_EVENT_TYPE

    @property
    def dedupKey(self) -> str:
        return knowledge_result_dedup_key(
            self.invocationId, self.packageContentHash
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "eventType": self.eventType,
            "producerRunId": self.producerRunId,
            "consumerRunId": self.consumerRunId,
            "invocationId": self.invocationId,
            "knowledgePackageRef": self.knowledgePackageRef,
            "packageContentHash": self.packageContentHash,
            "sourceManifestRef": self.sourceManifestRef,
            "handoffDecisionRef": self.handoffDecisionRef,
            "correlationId": self.correlationId,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> KnowledgeResultAvailablePayload:
        if not isinstance(payload, Mapping):
            raise ContractValidationError("payload must be a JSON object")
        event_type = str(payload.get("eventType") or "").strip()
        if event_type != KNOWLEDGE_RESULT_AVAILABLE_EVENT_TYPE:
            raise ContractValidationError(
                f"eventType must be {KNOWLEDGE_RESULT_AVAILABLE_EVENT_TYPE!r}, "
                f"got {event_type!r}"
            )
        package_hash = require_sha256(payload, "packageContentHash")
        correlation = require_text(payload, "correlationId")
        return cls(
            producerRunId=require_text(payload, "producerRunId"),
            consumerRunId=require_text(payload, "consumerRunId"),
            invocationId=require_text(payload, "invocationId"),
            knowledgePackageRef=require_text(payload, "knowledgePackageRef"),
            packageContentHash=package_hash,
            sourceManifestRef=str(payload.get("sourceManifestRef") or "").strip(),
            handoffDecisionRef=str(payload.get("handoffDecisionRef") or "").strip(),
            correlationId=correlation,
        )


def knowledge_result_dedup_key(
    invocation_id: str, package_content_hash: str
) -> str:
    """Consumer-side idempotency key: one absorption per package content."""
    return f"knowledge-result:{invocation_id}:{package_content_hash}"


def knowledge_result_event_id(
    invocation_id: str, package_content_hash: str
) -> str:
    """Deterministic parent-run event id powering crash-safe dedup."""
    return f"evt-{knowledge_result_dedup_key(invocation_id, package_content_hash)}"
