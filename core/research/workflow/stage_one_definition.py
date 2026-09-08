"""Pinned Challenge Cup stage-one workflow definition.

Stage one is a small main-flow definition.  Knowledge collection remains the
independent ``challenge-cup-knowledge-sideflow`` workflow; the main run only
joins that evidence at ``hypothesis_design`` and then closes by building the
result package.  The full 3.0.0 definition remains the default for callers
that explicitly create an experiment run.
"""

from __future__ import annotations

import dataclasses

from .definition import (
    build_challenge_cup_workflow_definition,
    definition_structure_hash,
)
from .definition_registry import DefinitionIdentity, register_or_resolve
from .models import WorkflowDefinition, WorkflowEdgeSpec

STAGE_ONE_SCHEMA_VERSION = "3.1.0-stage-one"

STAGE_ONE_NODE_IDS: tuple[str, ...] = (
    "problem_understanding",
    "hypothesis_design",
    "result_package",
)

STAGE_ONE_EDGE_IDS: tuple[str, ...] = (
    "e_problem_hypothesis",
    "e_hyp_result",
)


def build_stage_one_workflow_definition() -> WorkflowDefinition:
    """Build the immutable 3.1 stage-one main flow from the 3.0 node specs."""

    base = build_challenge_cup_workflow_definition()
    kept = set(STAGE_ONE_NODE_IDS)
    base_node_ids = {node.nodeId for node in base.nodes}
    missing = [node_id for node_id in STAGE_ONE_NODE_IDS if node_id not in base_node_ids]
    if missing:
        raise ValueError(
            "main definition no longer carries the stage-one nodes; "
            f"missing={missing}"
        )

    nodes = tuple(node for node in base.nodes if node.nodeId in kept)
    base_edges = {
        (edge.fromNodeId, edge.toNodeId): edge
        for edge in base.edges
    }
    problem_to_hypothesis = base_edges.get(
        ("problem_understanding", "hypothesis_design")
    )
    if problem_to_hypothesis is None:
        raise ValueError("main definition is missing problem_understanding -> hypothesis_design")
    hypothesis_to_result = WorkflowEdgeSpec(
        edgeId="e_hyp_result",
        fromNodeId="hypothesis_design",
        toNodeId="result_package",
        label="假设集",
        gateKind=problem_to_hypothesis.gateKind,
        requiredArtifactKinds=("hypothesis_set",),
    )
    edges = (problem_to_hypothesis, hypothesis_to_result)

    stages = tuple(
        dataclasses.replace(
            stage,
            label={"experiment_design": "假说形成", "execution_iteration": "结果核验"}.get(
                stage.stageId.value, stage.label
            ),
            nodeIds=tuple(node_id for node_id in stage.nodeIds if node_id in kept),
        )
        for stage in base.stages
        if any(node_id in kept for node_id in stage.nodeIds)
    )
    draft = WorkflowDefinition(
        workflowId=base.workflowId,
        schemaVersion=STAGE_ONE_SCHEMA_VERSION,
        label="挑战杯第一阶段科研流程",
        stages=stages,
        nodes=nodes,
        edges=edges,
    )
    frozen = dataclasses.replace(
        draft,
        structureHash=definition_structure_hash(draft),
    )
    _assert_stage_one_shape(frozen)
    return frozen


def _assert_stage_one_shape(definition: WorkflowDefinition) -> None:
    node_ids = tuple(node.nodeId for node in definition.nodes)
    if node_ids != STAGE_ONE_NODE_IDS:
        raise ValueError(
            "stage-one definition node set drifted: "
            f"expected={STAGE_ONE_NODE_IDS} actual={node_ids}"
        )
    edge_ids = tuple(edge.edgeId for edge in definition.edges)
    if edge_ids != STAGE_ONE_EDGE_IDS:
        raise ValueError(
            "stage-one definition edge set drifted: "
            f"expected={STAGE_ONE_EDGE_IDS} actual={edge_ids}"
        )
    pairs = tuple((edge.fromNodeId, edge.toNodeId) for edge in definition.edges)
    expected_pairs = (
        ("problem_understanding", "hypothesis_design"),
        ("hypothesis_design", "result_package"),
    )
    if pairs != expected_pairs:
        raise ValueError(
            "stage-one definition edge topology drifted: "
            f"expected={expected_pairs} actual={pairs}"
        )
    sources = {edge.fromNodeId for edge in definition.edges}
    terminals = tuple(
        node.nodeId for node in definition.nodes if node.nodeId not in sources
    )
    if terminals != ("result_package",):
        raise ValueError(
            "stage-one definition must terminate at result_package; "
            f"terminals={terminals}"
        )


def stage_one_creation_definition() -> tuple[WorkflowDefinition, DefinitionIdentity]:
    """Return and register the definition used by new question runs."""

    definition = build_stage_one_workflow_definition()
    return definition, register_or_resolve(definition)


def is_stage_one_workflow_version(workflow_version_id: str) -> bool:
    """Return whether a version id belongs to the pinned 3.1 stage-one flow."""

    _, identity = stage_one_creation_definition()
    return str(workflow_version_id or "").strip() == identity.workflowVersionId


__all__ = [
    "STAGE_ONE_EDGE_IDS",
    "STAGE_ONE_NODE_IDS",
    "STAGE_ONE_SCHEMA_VERSION",
    "build_stage_one_workflow_definition",
    "is_stage_one_workflow_version",
    "stage_one_creation_definition",
]
