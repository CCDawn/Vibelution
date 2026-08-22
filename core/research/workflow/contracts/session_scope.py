"""Versioned identity for workflow Agent sessions.

The physical execution attempt is deliberately kept out of this contract.  A
retry is another physical session for the same logical scope, while the scope
itself remains stable and can therefore be used for idempotent resolution.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._validation import ContractValidationError

SESSION_SCOPE_VERSION = 3
WORKFLOW_NODE_ROOT_SCOPE_KIND = "workflow_node_root"
WORKFLOW_CANDIDATE_SCOPE_KIND = "workflow_candidate"
SESSION_SCOPE_KINDS = frozenset(
    {
        WORKFLOW_NODE_ROOT_SCOPE_KIND,
        WORKFLOW_CANDIDATE_SCOPE_KIND,
    }
)


def _required_text(value: Any, field: str, *, limit: int = 160) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ContractValidationError(f"{field} is required")
    if len(normalized) > limit:
        raise ContractValidationError(f"{field} exceeds {limit} characters")
    if any(char in normalized for char in ("|", "\r", "\n")):
        raise ContractValidationError(f"{field} contains a reserved separator")
    return normalized


@dataclass(frozen=True, slots=True)
class WorkflowSessionScopeV3:
    """Canonical root or candidate scope used by the session resolver."""

    version: int
    kind: str
    teamId: str
    researchProjectId: str
    agentId: str
    workflowRunId: str
    workflowNodeId: str
    selectionId: str = ""
    candidateId: str = ""

    def __post_init__(self) -> None:
        try:
            version = int(self.version)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(
                "Workflow session scope version must be an integer"
            ) from exc
        if version != SESSION_SCOPE_VERSION:
            raise ContractValidationError(
                f"Workflow session scope version must be {SESSION_SCOPE_VERSION}"
            )
        normalized_kind = str(self.kind or "").strip()
        if normalized_kind not in SESSION_SCOPE_KINDS:
            raise ContractValidationError(
                "Workflow session scope kind must be workflow_node_root or workflow_candidate"
            )
        object.__setattr__(self, "version", SESSION_SCOPE_VERSION)
        object.__setattr__(self, "kind", normalized_kind)
        for field, limit in (
            ("teamId", 160),
            ("researchProjectId", 160),
            ("agentId", 160),
            ("workflowRunId", 160),
            ("workflowNodeId", 80),
        ):
            object.__setattr__(self, field, _required_text(getattr(self, field), field, limit=limit))
        selection_id = str(self.selectionId or "").strip()
        candidate_id = str(self.candidateId or "").strip()
        if normalized_kind == WORKFLOW_NODE_ROOT_SCOPE_KIND:
            if selection_id or candidate_id:
                raise ContractValidationError(
                    "workflow_node_root scope must not carry candidate fields"
                )
        elif not selection_id or not candidate_id:
            raise ContractValidationError(
                "workflow_candidate scope requires both selectionId and candidateId"
            )
        if len(selection_id) > 160 or len(candidate_id) > 160:
            raise ContractValidationError("selectionId and candidateId must be at most 160 characters")
        if any(char in selection_id for char in ("|", "\r", "\n")):
            raise ContractValidationError("selectionId contains a reserved separator")
        if any(char in candidate_id for char in ("|", "\r", "\n")):
            raise ContractValidationError("candidateId contains a reserved separator")
        object.__setattr__(self, "selectionId", selection_id)
        object.__setattr__(self, "candidateId", candidate_id)

    @classmethod
    def root(cls, **fields: Any) -> WorkflowSessionScopeV3:
        fields = _camelize_scope_fields(fields)
        return cls(
            version=SESSION_SCOPE_VERSION,
            kind=WORKFLOW_NODE_ROOT_SCOPE_KIND,
            **{
                key: value
                for key, value in fields.items()
                if key not in {"selectionId", "candidateId", "version", "kind"}
            },
        )

    @classmethod
    def candidate(cls, **fields: Any) -> WorkflowSessionScopeV3:
        fields = _camelize_scope_fields(fields)
        return cls(
            version=SESSION_SCOPE_VERSION,
            kind=WORKFLOW_CANDIDATE_SCOPE_KIND,
            **{
                key: value
                for key, value in fields.items()
                if key not in {"version", "kind"}
            },
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> WorkflowSessionScopeV3:
        if not isinstance(payload, Mapping):
            raise ContractValidationError("Workflow session scope must be an object")
        version = payload.get("version", SESSION_SCOPE_VERSION)
        try:
            version = int(version)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(
                "Workflow session scope version must be an integer"
            ) from exc
        return cls(
            version=version,
            kind=str(payload.get("kind") or "").strip(),
            teamId=payload.get("teamId"),
            researchProjectId=payload.get("researchProjectId"),
            agentId=payload.get("agentId"),
            workflowRunId=payload.get("workflowRunId"),
            workflowNodeId=payload.get("workflowNodeId"),
            selectionId=payload.get("selectionId") or "",
            candidateId=payload.get("candidateId") or "",
        )

    from_payload = from_mapping

    @property
    def is_candidate(self) -> bool:
        return self.kind == WORKFLOW_CANDIDATE_SCOPE_KIND

    @property
    def key(self) -> str:
        if self.is_candidate:
            return (
                f"v3|candidate|{self.agentId}|{self.workflowRunId}|"
                f"{self.workflowNodeId}|{self.selectionId}|{self.candidateId}"
            )
        return (
            f"v3|node|{self.agentId}|{self.workflowRunId}|{self.workflowNodeId}"
        )

    def to_dict(self) -> dict[str, str | int]:
        payload: dict[str, str | int] = {
            "version": SESSION_SCOPE_VERSION,
            "kind": self.kind,
            "teamId": self.teamId,
            "researchProjectId": self.researchProjectId,
            "agentId": self.agentId,
            "workflowRunId": self.workflowRunId,
            "workflowNodeId": self.workflowNodeId,
        }
        if self.is_candidate:
            payload["selectionId"] = self.selectionId
            payload["candidateId"] = self.candidateId
        return payload


def _camelize_scope_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Accept Python-friendly aliases without changing persisted field names."""

    aliases = {
        "team_id": "teamId",
        "research_project_id": "researchProjectId",
        "agent_id": "agentId",
        "workflow_run_id": "workflowRunId",
        "workflow_node_id": "workflowNodeId",
        "selection_id": "selectionId",
        "candidate_id": "candidateId",
    }
    return {aliases.get(key, key): value for key, value in fields.items()}


__all__ = [
    "SESSION_SCOPE_KINDS",
    "SESSION_SCOPE_VERSION",
    "WORKFLOW_CANDIDATE_SCOPE_KIND",
    "WORKFLOW_NODE_ROOT_SCOPE_KIND",
    "WorkflowSessionScopeV3",
]
