"""Domain service ports for adapters (real wiring lands with T7 routes;
tests inject fakes that assert ordering and idempotency)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from core.research.workflow.contracts import PendingAction


@dataclass(frozen=True)
class ReadBackVerdict:
    ok: bool
    detail: str = ""
    revision_vector: dict[str, str] | None = None


@dataclass(frozen=True)
class AgentTaskHandle:
    session_id: str
    session_attempt: int
    task_id: str
    turn_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "sessionAttempt": self.session_attempt,
            "taskId": self.task_id,
            "turnId": self.turn_id,
        }


@dataclass(frozen=True)
class HumanTaskHandle:
    task_id: str


@dataclass(frozen=True)
class ArtifactReadBack:
    canonical_ref: str
    version: str
    content_hash: str
    domain_revision: str


class DomainPorts(Protocol):
    def read_back_input(self, action: PendingAction) -> ReadBackVerdict: ...

    def reserve_budget(
        self, *, action: PendingAction, estimate_tokens: int
    ) -> dict[str, Any]: ...

    def settle_budget(self, *, reservation: dict[str, Any], usage: dict[str, Any]) -> None: ...

    def create_agent_task(self, *, action: PendingAction) -> AgentTaskHandle: ...

    def execute_agent_turn(self, *, action: PendingAction, handle: AgentTaskHandle) -> list[dict[str, str]]: ...

    def read_back_artifact(self, canonical_ref: str) -> ArtifactReadBack | None: ...

    def create_human_task(self, *, action: PendingAction) -> HumanTaskHandle: ...

    def execute_system_action(
        self, *, action: PendingAction
    ) -> tuple[list[dict[str, str]], dict[str, Any]]: ...
