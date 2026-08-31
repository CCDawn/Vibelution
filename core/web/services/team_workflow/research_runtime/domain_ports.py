"""Domain service ports for adapters.

Tests inject fakes that assert ordering and idempotency; the production
composition root injects :class:`RealDomainPorts` (real binding snapshot
resolution, real Agent session/task/turn creation, and real budget
reservation/settlement against the Workflow Ledger budget_receipts).
"""

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
    # ``hypothesis_design`` is a node-level execution with a container session
    # plus one child Task/Turn per selected candidate. For fan-out, the scalar
    # fields above describe the root (task/turn stay empty); candidate task/turn
    # values only live in ``scoped_handles``.
    root_session_id: str | None = None
    root_session_attempt: int | None = None
    root_status: str = "running"
    scoped_handles: tuple[ScopedAgentTaskHandle, ...] = ()
    observation_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "sessionId": self.session_id,
            "sessionAttempt": self.session_attempt,
            "taskId": self.task_id,
            "turnId": self.turn_id,
        }
        if self.root_session_id:
            payload["rootSession"] = {
                "scopeKind": "workflow_node_root",
                "sessionId": self.root_session_id,
                "sessionAttempt": self.root_session_attempt or self.session_attempt,
                "taskId": self.task_id or None,
                "turnId": self.turn_id or None,
                "status": self.root_status,
            }
        if self.scoped_handles:
            payload["scopedSessions"] = [item.to_dict() for item in self.scoped_handles]
        if self.observation_only:
            payload["observationOnly"] = True
        return payload


@dataclass(frozen=True)
class ScopedAgentTaskHandle:
    """One candidate-scoped canonical Session/Task/Turn handle."""

    candidate_id: str
    selection_id: str
    session_id: str
    session_attempt: int
    task_id: str
    turn_id: str
    subtask_id: str | None = None
    status: str = "running"
    parent_session_id: str | None = None
    root_session_id: str | None = None
    fragment_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "scopeKind": "workflow_candidate",
            "candidateId": self.candidate_id,
            "selectionId": self.selection_id,
            "sessionId": self.session_id,
            "sessionAttempt": self.session_attempt,
            "taskId": self.task_id,
            "turnId": self.turn_id,
            "status": self.status,
            "parentSessionId": self.parent_session_id,
            "rootSessionId": self.root_session_id,
            "fragmentRefs": list(self.fragment_refs),
        }
        if self.subtask_id:
            payload["subtaskId"] = self.subtask_id
        return payload


@dataclass(frozen=True)
class AgentTurnResult:
    """Agent outputs plus the final, post-write canonical anchor handles."""

    materialized_refs: tuple[dict[str, str], ...]
    handle: AgentTaskHandle
    usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class HumanTaskHandle:
    task_id: str


@dataclass(frozen=True)
class ArtifactReadBack:
    canonical_ref: str
    version: str
    content_hash: str
    domain_revision: str


@dataclass(frozen=True)
class BindingResolution:
    agent_id: str
    role_key: str
    binding_snapshot_id: str | None = None
    session_scope: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "agentId": self.agent_id,
            "roleKey": self.role_key,
        }
        if self.binding_snapshot_id:
            payload["bindingSnapshotId"] = self.binding_snapshot_id
        if self.session_scope:
            payload["scope"] = dict(self.session_scope)
        return payload


class DomainPorts(Protocol):
    def required_artifact_kinds(self, action: PendingAction) -> tuple[str, ...]: ...

    def read_back_input(self, action: PendingAction) -> ReadBackVerdict: ...

    def resolve_binding(self, action: PendingAction) -> BindingResolution: ...

    def reserve_budget(
        self, *, action: PendingAction, estimate_tokens: int
    ) -> dict[str, Any]: ...

    def settle_budget(self, *, reservation: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]: ...

    def create_agent_task(self, *, action: PendingAction) -> AgentTaskHandle: ...

    def execute_agent_turn(
        self, *, action: PendingAction, handle: AgentTaskHandle
    ) -> list[dict[str, str]] | AgentTurnResult: ...

    def read_back_artifact(self, canonical_ref: str) -> ArtifactReadBack | None: ...

    def create_human_task(self, *, action: PendingAction) -> HumanTaskHandle: ...

    def execute_system_action(
        self, *, action: PendingAction
    ) -> tuple[list[dict[str, str]], dict[str, Any]]: ...
