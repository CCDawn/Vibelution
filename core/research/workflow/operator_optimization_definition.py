"""Independent baseline and optimization-round graphs, without catalog gates."""
from __future__ import annotations

from dataclasses import replace
from itertools import pairwise

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

OPERATOR_WORKFLOW_ID = "operator-optimization"
OPERATOR_BASELINE_WORKFLOW_ID = "operator-optimization-baseline"

# Each artifact is produced and verified by its domain owner before handoff.
OPERATOR_NODES = (
    ("optimization_discussion", "优化讨论", ActorKind.AGENT, "experiment_planner", "optimization_hypothesis"),
    ("optimization_knowledge", "资料补齐", ActorKind.SYSTEM, "", "optimization_knowledge"),
    ("optimization_plan", "实验规划", ActorKind.AGENT, "experiment_planner", "optimization_plan"),
    ("operator_execution", "算子实验", ActorKind.SYSTEM, "", "operator_measurement"),
    ("operator_evaluation", "数值评价", ActorKind.SYSTEM, "", "operator_evaluation"),
    ("optimization_feedback", "反馈与下一轮", ActorKind.SYSTEM, "", "optimization_feedback"),
)

OPERATOR_ARTIFACT_KINDS = frozenset({
    "operator_environment",
    "operator_baseline",
    "operator_measurement_protocol",
    "operator_candidate",
    "optimization_discussion",
    "optimization_knowledge_request",
    *(row[4] for row in OPERATOR_NODES),
})


def build_operator_definition(*, baseline: bool = False) -> WorkflowDefinition:
    specs = (
        (("operator_baseline", "基线准备与测量", ActorKind.SYSTEM, "", "operator_baseline"),)
        if baseline else OPERATOR_NODES
    )
    stage = WorkflowStageId.EXECUTION_ITERATION
    nodes = tuple(WorkflowNodeSpec(
        nodeId=node_id, stageId=stage, label=label, actorKind=actor,
        primaryRoleKey=role, producesArtifactKinds=(artifact,),
    ) for node_id, label, actor, role, artifact in specs)
    edges = tuple(WorkflowEdgeSpec(
        edgeId=f"{left.nodeId}->{right.nodeId}", fromNodeId=left.nodeId,
        toNodeId=right.nodeId, label=left.label, gateKind=GateKind.AUTO,
        requiredArtifactKinds=left.producesArtifactKinds,
    ) for left, right in pairwise(nodes))
    definition = WorkflowDefinition(
        workflowId=OPERATOR_BASELINE_WORKFLOW_ID if baseline else OPERATOR_WORKFLOW_ID,
        schemaVersion="1.0.0", label="算子基线" if baseline else "算子优化实验",
        stages=(WorkflowStageSpec(stage, 1, "基线准备" if baseline else "优化实验", tuple(n.nodeId for n in nodes)),),
        nodes=nodes, edges=edges,
    )
    return replace(definition, structureHash=definition_structure_hash(definition))
