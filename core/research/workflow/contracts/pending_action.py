"""PendingAction / ExecutionReceipt: LangGraph interrupt contract (spec 5.5)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from core.research.workflow.models import ActorKind, ArtifactRef

from .workflow_problem import WorkflowProblem


@dataclass(frozen=True, slots=True)
class PendingAction:
    action_id: str
    run_id: str
    node_run_id: str
    node_id: str
    attempt: int
    actor_kind: ActorKind
    action_kind: str
    input_snapshot_hash: str
    input_artifact_refs: tuple[ArtifactRef, ...]
    binding_snapshot_id: str | None
    budget_policy_hash: str

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "actionId": self.action_id,
            "runId": self.run_id,
            "nodeRunId": self.node_run_id,
            "nodeId": self.node_id,
            "attempt": self.attempt,
            "actorKind": self.actor_kind.value,
            "actionKind": self.action_kind,
            "inputSnapshotHash": self.input_snapshot_hash,
            "inputArtifactRefs": [ref.to_dict() for ref in self.input_artifact_refs],
            "budgetPolicyHash": self.budget_policy_hash,
        }
        if self.binding_snapshot_id:
            payload["bindingSnapshotId"] = self.binding_snapshot_id
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PendingAction:
        return cls(
            action_id=str(payload.get("actionId") or ""),
            run_id=str(payload.get("runId") or ""),
            node_run_id=str(payload.get("nodeRunId") or ""),
            node_id=str(payload.get("nodeId") or ""),
            attempt=int(payload.get("attempt") or 0),
            actor_kind=ActorKind(str(payload.get("actorKind") or "")),
            action_kind=str(payload.get("actionKind") or ""),
            input_snapshot_hash=str(payload.get("inputSnapshotHash") or ""),
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
            binding_snapshot_id=payload.get("bindingSnapshotId"),
            budget_policy_hash=str(payload.get("budgetPolicyHash") or ""),
        )


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    action_id: str
    node_run_id: str
    outcome: Literal["succeeded", "failed", "blocked", "cancelled"]
    artifact_receipt_ids: tuple[str, ...]
    execution_anchor_id: str | None
    budget_receipt_id: str | None
    problem: WorkflowProblem | None
    completed_at_ms: int

    def assert_matches(self, action_id: str, node_run_id: str) -> None:
        if self.action_id != action_id or self.node_run_id != node_run_id:
            raise ValueError(
                "execution receipt identity mismatch: "
                f"expected ({action_id}, {node_run_id}), got "
                f"({self.action_id}, {self.node_run_id})"
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "actionId": self.action_id,
            "nodeRunId": self.node_run_id,
            "outcome": self.outcome,
            "artifactReceiptIds": list(self.artifact_receipt_ids),
            "completedAtMs": self.completed_at_ms,
        }
        if self.execution_anchor_id:
            payload["executionAnchorId"] = self.execution_anchor_id
        if self.budget_receipt_id:
            payload["budgetReceiptId"] = self.budget_receipt_id
        if self.problem:
            payload["problem"] = self.problem.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExecutionReceipt:
        problem_payload = payload.get("problem")
        return cls(
            action_id=str(payload.get("actionId") or ""),
            node_run_id=str(payload.get("nodeRunId") or ""),
            outcome=payload.get("outcome") or "failed",
            artifact_receipt_ids=tuple(str(item) for item in payload.get("artifactReceiptIds") or []),
            execution_anchor_id=payload.get("executionAnchorId"),
            budget_receipt_id=payload.get("budgetReceiptId"),
            problem=(
                WorkflowProblem.from_dict(problem_payload) if problem_payload else None
            ),
            completed_at_ms=int(payload.get("completedAtMs") or 0),
        )
