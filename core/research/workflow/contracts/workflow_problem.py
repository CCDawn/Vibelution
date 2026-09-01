"""WorkflowProblem: stable error code and remediation contract (architecture 11)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class WorkflowProblemCategory(str, Enum):
    TRANSIENT = "transient"
    LLM_RECOVERABLE = "llm_recoverable"
    USER_FIXABLE = "user_fixable"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    STALE_VERSION = "stale_version"
    HISTORICAL_MISSING = "historical_missing"
    NON_RECOVERABLE = "non_recoverable"


class RemediationKind(str, Enum):
    NAVIGATE_NODE = "navigate_node"
    RETRY = "retry"
    REVISE = "revise"
    FORK_RUN = "fork_run"
    REFRESH_SNAPSHOT = "refresh_snapshot"
    CREATE_RUN = "create_run"
    VIEW_DIAGNOSTICS = "view_diagnostics"
    RESOLVE_HUMAN = "resolve_human"
    REBIND_AGENT = "rebind_agent"
    # Operator raises this run's own budget ceiling (safety limits only
    # widen, never the global default) through the existing extend_budget
    # command; the blocked run keeps going instead of being discarded.
    EXTEND_BUDGET = "extend_budget"


@dataclass(frozen=True, slots=True)
class Remediation:
    kind: RemediationKind
    label: str
    target_node_id: str | None = None
    target_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind.value, "label": self.label}
        if self.target_node_id:
            payload["targetNodeId"] = self.target_node_id
        if self.target_run_id:
            payload["targetRunId"] = self.target_run_id
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Remediation:
        return cls(
            kind=RemediationKind(str(payload.get("kind") or "")),
            label=str(payload.get("label") or ""),
            target_node_id=payload.get("targetNodeId"),
            target_run_id=payload.get("targetRunId"),
        )


@dataclass(frozen=True, slots=True)
class WorkflowProblem:
    code: str
    category: WorkflowProblemCategory
    title: str
    detail: str
    retryable: bool
    scope: Mapping[str, str]
    remediation: Remediation | None = None
    technical_summary: str | None = None
    correlation_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "category": self.category.value,
            "title": self.title,
            "detail": self.detail,
            "retryable": self.retryable,
            "scope": dict(self.scope),
        }
        if self.remediation:
            payload["remediation"] = self.remediation.to_dict()
        if self.technical_summary:
            payload["technicalSummary"] = self.technical_summary
        if self.correlation_id:
            payload["correlationId"] = self.correlation_id
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorkflowProblem:
        remediation_payload = payload.get("remediation")
        return cls(
            code=str(payload.get("code") or ""),
            category=WorkflowProblemCategory(str(payload.get("category") or "")),
            title=str(payload.get("title") or ""),
            detail=str(payload.get("detail") or ""),
            retryable=bool(payload.get("retryable")),
            scope=dict(payload.get("scope") or {}),
            remediation=(
                Remediation.from_dict(remediation_payload) if remediation_payload else None
            ),
            technical_summary=payload.get("technicalSummary"),
            correlation_id=str(payload.get("correlationId") or ""),
        )
