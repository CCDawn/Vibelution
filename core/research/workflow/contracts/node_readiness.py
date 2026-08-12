"""NodeReadiness: the single executable-ability contract (architecture 8.1)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from core.research.workflow.models import ArtifactRef

from .workflow_problem import Remediation, RemediationKind


@dataclass(frozen=True, slots=True)
class ReadinessBlocker:
    code: str
    title: str
    detail: str
    category: str = "dependency"
    remediation: Remediation | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "title": self.title,
            "detail": self.detail,
            "category": self.category,
        }
        if self.remediation:
            payload["remediation"] = self.remediation.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class ActorReadiness:
    configured: bool
    resolvable: bool
    binding_snapshot_id: str | None
    agent_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "configured": self.configured,
            "resolvable": self.resolvable,
            "bindingSnapshotId": self.binding_snapshot_id,
        }
        if self.agent_id:
            payload["agentId"] = self.agent_id
        return payload


@dataclass(frozen=True, slots=True)
class BudgetReadiness:
    policy_hash: str
    available: bool
    reason: str
    estimated_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "policyHash": self.policy_hash,
            "available": self.available,
            "reason": self.reason,
            "estimatedTokens": self.estimated_tokens,
        }


@dataclass(frozen=True, slots=True)
class NodeReadiness:
    run_id: str
    team_id: str
    node_id: str
    run_version: int
    ready: bool
    evaluated_at_ms: int
    domain_revision_vector: Mapping[str, str]
    accepted_handoff_ids: tuple[str, ...]
    input_artifact_refs: tuple[ArtifactRef, ...]
    actor: ActorReadiness
    budget: BudgetReadiness
    blockers: tuple[ReadinessBlocker, ...] = field(default_factory=tuple)

    def cache_key(self) -> tuple[str, str, int, str, str]:
        vector = ",".join(
            f"{key}={value}" for key, value in sorted(self.domain_revision_vector.items())
        )
        return (self.team_id, self.run_id, self.run_version, self.node_id, vector)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "teamId": self.team_id,
            "nodeId": self.node_id,
            "runVersion": self.run_version,
            "ready": self.ready,
            "evaluatedAtMs": self.evaluated_at_ms,
            "domainRevisionVector": dict(self.domain_revision_vector),
            "acceptedHandoffIds": list(self.accepted_handoff_ids),
            "inputArtifactRefs": [ref.to_dict() for ref in self.input_artifact_refs],
            "actor": self.actor.to_dict(),
            "budget": self.budget.to_dict(),
            "blockers": [blocker.to_dict() for blocker in self.blockers],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> NodeReadiness:
        return cls(
            run_id=str(payload.get("runId") or ""),
            team_id=str(payload.get("teamId") or ""),
            node_id=str(payload.get("nodeId") or ""),
            run_version=int(payload.get("runVersion") or 0),
            ready=bool(payload.get("ready")),
            evaluated_at_ms=int(payload.get("evaluatedAtMs") or 0),
            domain_revision_vector=dict(payload.get("domainRevisionVector") or {}),
            accepted_handoff_ids=tuple(str(item) for item in payload.get("acceptedHandoffIds") or []),
            input_artifact_refs=tuple(
                ArtifactRef(
                    artifactId=str(ref.get("artifactId") or ""),
                    kind=str(ref.get("kind") or ""),
                    version=str(ref.get("version") or ""),
                    contentHash=str(ref.get("contentHash") or ""),
                    uri=str(ref.get("uri") or ""),
                    summary=str(ref.get("summary") or ""),
                )
                for ref in payload.get("inputArtifactRefs") or []
            ),
            actor=ActorReadiness(
                configured=bool(payload.get("actor", {}).get("configured")),
                resolvable=bool(payload.get("actor", {}).get("resolvable")),
                binding_snapshot_id=payload.get("actor", {}).get("bindingSnapshotId"),
                agent_id=payload.get("actor", {}).get("agentId"),
            ),
            budget=BudgetReadiness(
                policy_hash=str(payload.get("budget", {}).get("policyHash") or ""),
                available=bool(payload.get("budget", {}).get("available")),
                reason=str(payload.get("budget", {}).get("reason") or ""),
                estimated_tokens=int(payload.get("budget", {}).get("estimatedTokens") or 0),
            ),
            blockers=tuple(
                ReadinessBlocker(
                    code=str(blocker.get("code") or ""),
                    title=str(blocker.get("title") or ""),
                    detail=str(blocker.get("detail") or ""),
                    category=str(blocker.get("category") or "dependency"),
                    remediation=(
                        Remediation(
                            kind=RemediationKind(str(blocker["remediation"].get("kind") or "")),
                            label=str(blocker["remediation"].get("label") or ""),
                            target_node_id=blocker["remediation"].get("targetNodeId"),
                            target_run_id=blocker["remediation"].get("targetRunId"),
                        )
                        if blocker.get("remediation")
                        else None
                    ),
                )
                for blocker in payload.get("blockers") or []
            ),
        )
