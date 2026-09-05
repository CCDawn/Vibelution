"""Canonical independent knowledge-collection workflow."""

from __future__ import annotations

from .definition import definition_structure_hash
from .models import (
    ActorKind,
    GateKind,
    WorkflowDefinition,
    WorkflowEdgeSpec,
    WorkflowNodeSpec,
    WorkflowStageId,
    WorkflowStageSpec,
)

KNOWLEDGE_SIDEFLOW_WORKFLOW_ID = "challenge-cup-knowledge-sideflow"
KNOWLEDGE_SIDEFLOW_SCHEMA_VERSION = "1.0.0"
KNOWLEDGE_SIDEFLOW_LABEL = "挑战杯知识搜集子流程"

KNOWLEDGE_SIDEFLOW_NODE_IDS: tuple[str, ...] = (
    "source_finding",
    "source_extraction",
    "evidence_relations",
    "knowledge_ingestion",
    "knowledge_handoff",
)

_KNOWLEDGE_SIDEFLOW_NODES: tuple[WorkflowNodeSpec, ...] = (
    WorkflowNodeSpec(
        nodeId="source_finding",
        stageId=WorkflowStageId.KNOWLEDGE_COLLECTION,
        label="资料寻找",
        actorKind=ActorKind.AGENT,
        primaryRoleKey="source_finder",
        producesArtifactKinds=("source_candidate_batch",),
    ),
    WorkflowNodeSpec(
        nodeId="source_extraction",
        stageId=WorkflowStageId.KNOWLEDGE_COLLECTION,
        label="资料提炼",
        actorKind=ActorKind.AGENT,
        primaryRoleKey="source_extractor",
        producesArtifactKinds=("evidence_card_batch",),
    ),
    WorkflowNodeSpec(
        nodeId="evidence_relations",
        stageId=WorkflowStageId.KNOWLEDGE_COLLECTION,
        label="证据关系",
        actorKind=ActorKind.AGENT,
        primaryRoleKey="source_relation_mapper",
        producesArtifactKinds=("evidence_relation_graph",),
    ),
    WorkflowNodeSpec(
        nodeId="knowledge_ingestion",
        stageId=WorkflowStageId.KNOWLEDGE_COLLECTION,
        label="知识入库",
        actorKind=ActorKind.AGENT,
        primaryRoleKey="source_ingestor",
        producesArtifactKinds=("knowledge_package_draft",),
    ),
    WorkflowNodeSpec(
        nodeId="knowledge_handoff",
        stageId=WorkflowStageId.KNOWLEDGE_COLLECTION,
        label="知识包交接",
        actorKind=ActorKind.HUMAN,
        primaryRoleKey="research_owner",
        acceptsGateKinds=(GateKind.KNOWLEDGE_PACKAGE, GateKind.HUMAN),
        producesArtifactKinds=("knowledge_package",),
    ),
)


def _knowledge_sideflow_edges() -> tuple[WorkflowEdgeSpec, ...]:
    auto = GateKind.AUTO
    return (
        WorkflowEdgeSpec(
            "e_find_extract",
            "source_finding",
            "source_extraction",
            "候选资料",
            auto,
            ("source_candidate_batch",),
        ),
        WorkflowEdgeSpec(
            "e_extract_rel",
            "source_extraction",
            "evidence_relations",
            "证据卡",
            auto,
            ("evidence_card_batch",),
        ),
        WorkflowEdgeSpec(
            "e_rel_ingest",
            "evidence_relations",
            "knowledge_ingestion",
            "关系图",
            auto,
            ("evidence_relation_graph",),
        ),
        WorkflowEdgeSpec(
            "e_ingest_handoff",
            "knowledge_ingestion",
            "knowledge_handoff",
            "入库草稿",
            GateKind.HUMAN,
            ("knowledge_package_draft",),
            requiresHumanAccept=True,
        ),
    )


def build_knowledge_sideflow_workflow_definition() -> WorkflowDefinition:
    draft = WorkflowDefinition(
        workflowId=KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
        schemaVersion=KNOWLEDGE_SIDEFLOW_SCHEMA_VERSION,
        label=KNOWLEDGE_SIDEFLOW_LABEL,
        stages=(
            WorkflowStageSpec(
                stageId=WorkflowStageId.KNOWLEDGE_COLLECTION,
                index=1,
                label="知识搜集",
                nodeIds=KNOWLEDGE_SIDEFLOW_NODE_IDS,
            ),
        ),
        nodes=_KNOWLEDGE_SIDEFLOW_NODES,
        edges=_knowledge_sideflow_edges(),
    )
    return WorkflowDefinition(
        workflowId=draft.workflowId,
        schemaVersion=draft.schemaVersion,
        label=draft.label,
        stages=draft.stages,
        nodes=draft.nodes,
        edges=draft.edges,
        structureHash=definition_structure_hash(draft),
    )


__all__ = [
    "KNOWLEDGE_SIDEFLOW_LABEL",
    "KNOWLEDGE_SIDEFLOW_NODE_IDS",
    "KNOWLEDGE_SIDEFLOW_SCHEMA_VERSION",
    "KNOWLEDGE_SIDEFLOW_WORKFLOW_ID",
    "build_knowledge_sideflow_workflow_definition",
]
