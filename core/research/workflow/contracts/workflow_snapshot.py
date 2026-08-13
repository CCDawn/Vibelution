"""ResearchWorkflowSnapshot contract — formal server read projection (spec 11.3).

UI-only state (selected node, panel, viewport, hover, dialog, URL) is forbidden.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .workflow_command import CommandOffer


@dataclass(frozen=True, slots=True)
class WorkflowRunSummary:
    run_id: str
    team_id: str
    workflow_id: str
    workflow_version_id: str
    thread_id: str
    project_id: str
    question_id: str
    status: str
    run_version: int
    input_snapshot_hash: str
    binding_snapshot_set_id: str
    active_node_id: str | None
    parent_run_id: str | None
    forked_from_checkpoint_id: str | None
    completion_kind: str | None
    terminal_reason: str | None
    created_at_ms: int
    updated_at_ms: int
    completed_at_ms: int | None
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "teamId": self.team_id,
            "workflowId": self.workflow_id,
            "workflowVersionId": self.workflow_version_id,
            "threadId": self.thread_id,
            "projectId": self.project_id,
            "questionId": self.question_id,
            "status": self.status,
            "runVersion": self.run_version,
            "inputSnapshotHash": self.input_snapshot_hash,
            "bindingSnapshotSetId": self.binding_snapshot_set_id,
            "activeNodeId": self.active_node_id,
            "parentRunId": self.parent_run_id,
            "forkedFromCheckpointId": self.forked_from_checkpoint_id,
            "completionKind": self.completion_kind,
            "terminalReason": self.terminal_reason,
            "blockedReason": self.blocked_reason,
            "createdAtMs": self.created_at_ms,
            "updatedAtMs": self.updated_at_ms,
            "completedAtMs": self.completed_at_ms,
        }


@dataclass(frozen=True, slots=True)
class NodeAttemptSummary:
    node_run_id: str
    node_id: str
    attempt: int
    actor_kind: str
    status: str
    command_id: str
    binding_snapshot_id: str | None
    input_snapshot_hash: str
    execution_anchor_id: str | None
    started_at_ms: int
    updated_at_ms: int
    finished_at_ms: int | None
    problem: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodeRunId": self.node_run_id,
            "nodeId": self.node_id,
            "attempt": self.attempt,
            "actorKind": self.actor_kind,
            "status": self.status,
            "commandId": self.command_id,
            "bindingSnapshotId": self.binding_snapshot_id,
            "inputSnapshotHash": self.input_snapshot_hash,
            "executionAnchorId": self.execution_anchor_id,
            "startedAtMs": self.started_at_ms,
            "updatedAtMs": self.updated_at_ms,
            "finishedAtMs": self.finished_at_ms,
            "problem": dict(self.problem) if self.problem else None,
        }


@dataclass(frozen=True, slots=True)
class HumanTaskSummary:
    task_id: str
    run_id: str
    node_run_id: str
    task_kind: str
    status: str
    created_at_ms: int
    node_id: str | None = None
    handoff_id: str | None = None
    resolved_at_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "runId": self.run_id,
            "nodeRunId": self.node_run_id,
            "nodeId": self.node_id,
            "handoffId": self.handoff_id,
            "taskKind": self.task_kind,
            "status": self.status,
            "createdAtMs": self.created_at_ms,
            "resolvedAtMs": self.resolved_at_ms,
        }


@dataclass(frozen=True, slots=True)
class HandoffRefSummary:
    status: str
    handoff_id: str | None = None
    to_node_id: str | None = None
    from_node_id: str | None = None
    from_node_run_id: str | None = None
    input_snapshot_hash: str | None = None
    output_artifact_refs: tuple[Mapping[str, Any], ...] = ()
    offered_at_ms: int | None = None
    accepted_at_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "handoffId": self.handoff_id,
            "fromNodeId": self.from_node_id,
            "fromNodeRunId": self.from_node_run_id,
            "toNodeId": self.to_node_id,
            "status": self.status,
            "inputSnapshotHash": self.input_snapshot_hash,
            "outputArtifactRefs": [dict(item) for item in self.output_artifact_refs],
            "offeredAtMs": self.offered_at_ms,
            "acceptedAtMs": self.accepted_at_ms,
        }


@dataclass(frozen=True, slots=True)
class HandoffSummary:
    counts_by_status: Mapping[str, int]
    refs: tuple[HandoffRefSummary, ...]
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "countsByStatus": dict(self.counts_by_status),
            "refs": [item.to_dict() for item in self.refs],
            "count": self.count,
        }


@dataclass(frozen=True, slots=True)
class AgentBindingRef:
    node_id: str
    agent_id: str
    role_key: str
    resolved_from: str
    snapshot_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodeId": self.node_id,
            "agentId": self.agent_id,
            "roleKey": self.role_key,
            "resolvedFrom": self.resolved_from,
            "snapshotId": self.snapshot_id,
        }


@dataclass(frozen=True, slots=True)
class AgentBindingSummary:
    binding_snapshot_set_id: str
    binding_snapshot_ids: tuple[str, ...]
    count: int
    bindings: tuple[AgentBindingRef, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "bindingSnapshotSetId": self.binding_snapshot_set_id,
            "bindingSnapshotIds": list(self.binding_snapshot_ids),
            "count": self.count,
            "bindings": [item.to_dict() for item in self.bindings],
        }


@dataclass(frozen=True, slots=True)
class BudgetReceiptRef:
    receipt_id: str | None = None
    node_run_id: str | None = None
    status: str | None = None
    policy_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "receiptId": self.receipt_id,
            "nodeRunId": self.node_run_id,
            "status": self.status,
            "policyHash": self.policy_hash,
        }


@dataclass(frozen=True, slots=True)
class BudgetSummary:
    safety_limits: Any
    receipt_refs: tuple[BudgetReceiptRef, ...]
    receipt_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "safetyLimits": self.safety_limits,
            "receiptRefs": [item.to_dict() for item in self.receipt_refs],
            "receiptCount": self.receipt_count,
        }


@dataclass(frozen=True, slots=True)
class ResearchWorkflowNodeDetail:
    run_id: str
    team_id: str
    node_id: str
    run_version: int
    actor_kind: str
    primary_role_key: str
    label: str
    runtime_current: bool
    status: str | None
    attempts: tuple[NodeAttemptSummary, ...]
    command_offers: tuple[CommandOffer, ...]
    latest_event_sequence: int
    generated_at: str
    binding_snapshot_id: str | None = None
    latest_attempt: NodeAttemptSummary | None = None
    agent_id: str | None = None
    display_name: str = ""
    resolved_from: str = "unbound"
    session_id: str | None = None
    task_id: str | None = None
    turn_id: str | None = None
    session_attempt: int | None = None
    chat_deep_link: str | None = None
    session_anchor_degraded: bool = False
    blocked_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "teamId": self.team_id,
            "nodeId": self.node_id,
            "runVersion": self.run_version,
            "actorKind": self.actor_kind,
            "primaryRoleKey": self.primary_role_key,
            "label": self.label,
            "runtimeCurrent": self.runtime_current,
            "status": self.status,
            "bindingSnapshotId": self.binding_snapshot_id,
            "latestAttempt": (
                self.latest_attempt.to_dict() if self.latest_attempt is not None else None
            ),
            "attempts": [item.to_dict() for item in self.attempts],
            "commandOffers": [offer.to_dict() for offer in self.command_offers],
            "latestEventSequence": self.latest_event_sequence,
            "generatedAt": self.generated_at,
            "agentId": self.agent_id,
            "displayName": self.display_name,
            "resolvedFrom": self.resolved_from,
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "turnId": self.turn_id,
            "sessionAttempt": self.session_attempt,
            "chatDeepLink": self.chat_deep_link,
            "sessionAnchorDegraded": self.session_anchor_degraded,
            "blockedReason": self.blocked_reason,
            "nodeAttempt": self.latest_attempt.attempt if self.latest_attempt else 0,
        }


@dataclass(frozen=True, slots=True)
class ResearchWorkflowSnapshot:
    run: WorkflowRunSummary
    definition: Mapping[str, Any]
    node_attempts: Mapping[str, tuple[NodeAttemptSummary, ...]]
    active_node_ids: tuple[str, ...]
    pending_human_tasks: tuple[HumanTaskSummary, ...]
    command_offers: tuple[CommandOffer, ...]
    handoff_summary: HandoffSummary
    agent_binding_summary: AgentBindingSummary
    budget_summary: BudgetSummary
    latest_event_sequence: int
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": self.run.to_dict(),
            "definition": dict(self.definition),
            "nodeAttempts": {
                node_id: [item.to_dict() for item in attempts]
                for node_id, attempts in self.node_attempts.items()
            },
            "activeNodeIds": list(self.active_node_ids),
            "pendingHumanTasks": [item.to_dict() for item in self.pending_human_tasks],
            "commandOffers": [offer.to_dict() for offer in self.command_offers],
            "handoffSummary": self.handoff_summary.to_dict(),
            "agentBindingSummary": self.agent_binding_summary.to_dict(),
            "budgetSummary": self.budget_summary.to_dict(),
            "latestEventSequence": int(self.latest_event_sequence),
            "generatedAt": self.generated_at,
        }
