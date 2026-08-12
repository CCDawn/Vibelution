"""ExecutionAnchor: Agent/System/Human anchor contract (architecture 8.3, ADR 0007)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core.research.workflow.models import ActorKind


@dataclass(frozen=True, slots=True)
class ExecutionAnchor:
    anchor_id: str
    node_run_id: str
    actor_kind: ActorKind
    agent_id: str | None = None
    role_key: str | None = None
    session_id: str | None = None
    session_attempt: int | None = None
    task_id: str | None = None
    turn_id: str | None = None
    system_action_id: str | None = None
    human_task_id: str | None = None
    checkpoint_id: str | None = None
    status: str = "bound"
    created_at_ms: int = 0

    def is_complete(self) -> bool:
        if self.actor_kind == ActorKind.AGENT:
            return bool(
                self.agent_id
                and self.session_id
                and self.session_attempt is not None
                and self.task_id
                and self.turn_id
            )
        if self.actor_kind == ActorKind.SYSTEM:
            return bool(self.system_action_id)
        if self.actor_kind == ActorKind.HUMAN:
            return bool(self.human_task_id)
        return False

    def missing_fields(self) -> tuple[str, ...]:
        if self.actor_kind == ActorKind.AGENT:
            required = (
                ("agent_id", self.agent_id),
                ("session_id", self.session_id),
                ("session_attempt", self.session_attempt is not None),
                ("task_id", self.task_id),
                ("turn_id", self.turn_id),
            )
            return tuple(name for name, value in required if not value)
        if self.actor_kind == ActorKind.SYSTEM:
            return () if self.system_action_id else ("system_action_id",)
        if self.actor_kind == ActorKind.HUMAN:
            return () if self.human_task_id else ("human_task_id",)
        return ("actor_kind",)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "anchorId": self.anchor_id,
            "nodeRunId": self.node_run_id,
            "actorKind": self.actor_kind.value,
            "status": self.status,
            "createdAtMs": self.created_at_ms,
        }
        for name in (
            "agent_id",
            "role_key",
            "session_id",
            "task_id",
            "turn_id",
            "system_action_id",
            "human_task_id",
            "checkpoint_id",
        ):
            value = getattr(self, name)
            if value is not None:
                payload[_camel(name)] = value
        if self.session_attempt is not None:
            payload["sessionAttempt"] = self.session_attempt
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExecutionAnchor:
        return cls(
            anchor_id=str(payload.get("anchorId") or ""),
            node_run_id=str(payload.get("nodeRunId") or ""),
            actor_kind=ActorKind(str(payload.get("actorKind") or "")),
            agent_id=payload.get("agentId"),
            role_key=payload.get("roleKey"),
            session_id=payload.get("sessionId"),
            session_attempt=payload.get("sessionAttempt"),
            task_id=payload.get("taskId"),
            turn_id=payload.get("turnId"),
            system_action_id=payload.get("systemActionId"),
            human_task_id=payload.get("humanTaskId"),
            checkpoint_id=payload.get("checkpointId"),
            status=str(payload.get("status") or "bound"),
            created_at_ms=int(payload.get("createdAtMs") or 0),
        )


def _camel(name: str) -> str:
    head, _, tail = name.partition("_")
    return head + tail.capitalize() if tail else head
