"""Domain enums and value objects for research workflow runs.

selectedNodeId is intentionally absent — it is UI-only state (ADR 0006).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping


class ActorKind(str, Enum):
    AGENT = "agent"
    SYSTEM = "system"
    HUMAN = "human"


class WorkflowStageId(str, Enum):
    KNOWLEDGE_COLLECTION = "knowledge_collection"
    EXPERIMENT_DESIGN = "experiment_design"
    EXECUTION_ITERATION = "execution_iteration"


class WorkflowRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class NodeRunStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    STALE = "stale"
    CANCELLED = "cancelled"


class HandoffStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    WAITING_HUMAN = "waiting_human"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class HumanTaskStatus(str, Enum):
    PENDING = "pending"
    RESOLVED_ACCEPT = "resolved_accept"
    RESOLVED_REJECT = "resolved_reject"
    RESOLVED_REVISE = "resolved_revise"
    CANCELLED = "cancelled"


class GateKind(str, Enum):
    AUTO = "auto"
    HUMAN = "human"
    KNOWLEDGE_PACKAGE = "knowledge_package"
    FROZEN_PROTOCOL = "frozen_protocol"
    SMOKE = "smoke"
    PROMOTION = "promotion"


class NodeSessionScopePolicy(str, Enum):
    NODE_SHARED = "node_shared"
    CANDIDATE_FAN_OUT = "candidate_fan_out"
    ROUND_SHARED = "round_shared"


# Allowed NodeRun transitions (from -> to). Used by runtime; pure data for Task 1.
NODE_RUN_TRANSITIONS: dict[NodeRunStatus, frozenset[NodeRunStatus]] = {
    NodeRunStatus.PENDING: frozenset({NodeRunStatus.READY, NodeRunStatus.SKIPPED, NodeRunStatus.CANCELLED}),
    NodeRunStatus.READY: frozenset(
        {
            NodeRunStatus.RUNNING,
            NodeRunStatus.BLOCKED,
            NodeRunStatus.SKIPPED,
            NodeRunStatus.CANCELLED,
            NodeRunStatus.STALE,
        }
    ),
    NodeRunStatus.RUNNING: frozenset(
        {
            NodeRunStatus.WAITING_HUMAN,
            NodeRunStatus.SUCCEEDED,
            NodeRunStatus.FAILED,
            NodeRunStatus.CANCELLED,
        }
    ),
    NodeRunStatus.WAITING_HUMAN: frozenset(
        {
            NodeRunStatus.RUNNING,
            NodeRunStatus.SUCCEEDED,
            NodeRunStatus.FAILED,
            NodeRunStatus.BLOCKED,
            NodeRunStatus.CANCELLED,
        }
    ),
    NodeRunStatus.SUCCEEDED: frozenset({NodeRunStatus.STALE}),
    NodeRunStatus.FAILED: frozenset({NodeRunStatus.READY, NodeRunStatus.STALE, NodeRunStatus.CANCELLED}),
    NodeRunStatus.BLOCKED: frozenset({NodeRunStatus.READY, NodeRunStatus.CANCELLED, NodeRunStatus.STALE}),
    NodeRunStatus.SKIPPED: frozenset({NodeRunStatus.STALE}),
    NodeRunStatus.STALE: frozenset({NodeRunStatus.READY, NodeRunStatus.SKIPPED, NodeRunStatus.CANCELLED}),
    NodeRunStatus.CANCELLED: frozenset(),
}


def can_transition_node_run(current: NodeRunStatus, nxt: NodeRunStatus) -> bool:
    if current == nxt:
        return True
    return nxt in NODE_RUN_TRANSITIONS.get(current, frozenset())


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifactId: str
    kind: str
    version: str
    contentHash: str
    uri: str = ""
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkflowNodeSpec:
    nodeId: str
    stageId: WorkflowStageId
    label: str
    actorKind: ActorKind
    primaryRoleKey: str
    description: str = ""
    collaboratorRoleKeys: tuple[str, ...] = ()
    acceptsGateKinds: tuple[GateKind, ...] = ()
    producesArtifactKinds: tuple[str, ...] = ()
    sessionScopePolicy: NodeSessionScopePolicy = NodeSessionScopePolicy.NODE_SHARED

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodeId": self.nodeId,
            "stageId": self.stageId.value,
            "label": self.label,
            "actorKind": self.actorKind.value,
            "primaryRoleKey": self.primaryRoleKey,
            "description": self.description,
            "collaboratorRoleKeys": list(self.collaboratorRoleKeys),
            "acceptsGateKinds": [g.value for g in self.acceptsGateKinds],
            "producesArtifactKinds": list(self.producesArtifactKinds),
            "sessionScopePolicy": self.sessionScopePolicy.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorkflowNodeSpec:
        return cls(
            nodeId=str(data["nodeId"]),
            stageId=WorkflowStageId(str(data["stageId"])),
            label=str(data["label"]),
            actorKind=ActorKind(str(data["actorKind"])),
            primaryRoleKey=str(data["primaryRoleKey"]),
            description=str(data.get("description") or ""),
            collaboratorRoleKeys=tuple(str(k) for k in data.get("collaboratorRoleKeys") or ()),
            acceptsGateKinds=tuple(GateKind(str(g)) for g in data.get("acceptsGateKinds") or ()),
            producesArtifactKinds=tuple(str(k) for k in data.get("producesArtifactKinds") or ()),
            sessionScopePolicy=NodeSessionScopePolicy(
                str(data.get("sessionScopePolicy") or NodeSessionScopePolicy.NODE_SHARED.value)
            ),
        )


@dataclass(frozen=True, slots=True)
class WorkflowStageSpec:
    stageId: WorkflowStageId
    index: int
    label: str
    nodeIds: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stageId": self.stageId.value,
            "index": self.index,
            "label": self.label,
            "nodeIds": list(self.nodeIds),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorkflowStageSpec:
        return cls(
            stageId=WorkflowStageId(str(data["stageId"])),
            index=int(data["index"]),
            label=str(data["label"]),
            nodeIds=tuple(str(n) for n in data.get("nodeIds") or ()),
        )


@dataclass(frozen=True, slots=True)
class WorkflowEdgeSpec:
    edgeId: str
    fromNodeId: str
    toNodeId: str
    label: str
    gateKind: GateKind
    requiredArtifactKinds: tuple[str, ...] = ()
    requiresHumanAccept: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "edgeId": self.edgeId,
            "fromNodeId": self.fromNodeId,
            "toNodeId": self.toNodeId,
            "label": self.label,
            "gateKind": self.gateKind.value,
            "requiredArtifactKinds": list(self.requiredArtifactKinds),
            "requiresHumanAccept": self.requiresHumanAccept,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorkflowEdgeSpec:
        return cls(
            edgeId=str(data["edgeId"]),
            fromNodeId=str(data["fromNodeId"]),
            toNodeId=str(data["toNodeId"]),
            label=str(data["label"]),
            gateKind=GateKind(str(data["gateKind"])),
            requiredArtifactKinds=tuple(str(k) for k in data.get("requiredArtifactKinds") or ()),
            requiresHumanAccept=bool(data.get("requiresHumanAccept") or False),
        )


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    workflowId: str
    schemaVersion: str
    label: str
    stages: tuple[WorkflowStageSpec, ...]
    nodes: tuple[WorkflowNodeSpec, ...]
    edges: tuple[WorkflowEdgeSpec, ...]
    structureHash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflowId": self.workflowId,
            "schemaVersion": self.schemaVersion,
            "label": self.label,
            "structureHash": self.structureHash,
            "stages": [s.to_dict() for s in self.stages],
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorkflowDefinition:
        """Parse a definition dict (e.g. a registry snapshot payload).

        Unknown enum values or missing keys raise ``ValueError``/``KeyError``
        so a corrupted snapshot fails closed instead of parsing loosely.
        """
        return cls(
            workflowId=str(data["workflowId"]),
            schemaVersion=str(data["schemaVersion"]),
            label=str(data["label"]),
            stages=tuple(WorkflowStageSpec.from_dict(item) for item in data.get("stages") or ()),
            nodes=tuple(WorkflowNodeSpec.from_dict(item) for item in data.get("nodes") or ()),
            edges=tuple(WorkflowEdgeSpec.from_dict(item) for item in data.get("edges") or ()),
            structureHash=str(data.get("structureHash") or ""),
        )


@dataclass(frozen=True, slots=True)
class NodeHandoffRecord:
    handoffId: str
    workflowId: str
    workflowVersionId: str
    runId: str
    fromNodeId: str
    fromNodeRunId: str
    toNodeId: str
    gateKind: GateKind
    outputArtifactRefs: tuple[ArtifactRef, ...]
    inputSnapshotHash: str
    status: HandoffStatus
    offeredAt: str
    toNodeRunId: str = ""
    acceptedAt: str = ""
    acceptedBy: str = ""
    rejectionReason: str = ""
    supersedesHandoffId: str = ""
    humanTaskId: str = ""

    def is_consumable(self) -> bool:
        return self.status is HandoffStatus.ACCEPTED


@dataclass(frozen=True, slots=True)
class RunAgentBindingSnapshot:
    """Frozen at WorkflowRun creation / rebind; history must not re-read live config."""

    snapshotId: str
    workflowId: str
    workflowVersionId: str
    runId: str
    nodeId: str
    agentId: str
    roleKey: str
    actorKind: ActorKind
    resolvedFrom: str  # workflow_default | stage_override | node_override | rebind
    displayName: str = ""
    modelProfileId: str = ""
    capturedAt: str = ""


@dataclass(frozen=True, slots=True)
class NodeAgentSessionBinding:
    bindingId: str
    workflowId: str
    workflowVersionId: str
    runId: str
    nodeId: str
    nodeRunId: str
    nodeAttempt: int
    agentId: str
    roleKey: str
    sessionId: str
    sessionAttempt: int
    taskId: str
    turnId: str
    checkpointId: str
    status: str
    boundAt: str
    supersedesBindingId: str = ""


@dataclass(frozen=True, slots=True)
class AgentBindingLayers:
    """Config-time layers only; not run history."""

    workflowDefaults: dict[str, str] = field(default_factory=dict)  # roleKey -> agentId
    stageOverrides: dict[str, dict[str, str]] = field(default_factory=dict)  # stageId -> roleKey -> agentId
    nodeOverrides: dict[str, str] = field(default_factory=dict)  # nodeId -> agentId
