"""Stage-one truncated main-flow definition (``challenge-cup-research@2.2.0-stage-one``).

Product decision (挑战杯假说链第一阶段): the in-graph chain stops at
``hypothesis_design`` — the hypothesis set is the run's terminal deliverable.
The phase-two nodes (protocol_design/protocol_review/protocol_freeze/
smoke_gate and the whole execution_iteration stage) and every edge from
``hypothesis_design`` onward are removed, so ``hypothesis_design`` becomes a
terminal node and a successful stage-one closeout ends the run.

Like the knowledge-sideflow variants (``knowledge_sideflow_definition.py``),
this builder is pure: it derives a new pinned definition from the frozen
2.1.0 builder output without mutating it, and it is the only source of the
``challenge-cup-research@2.2.0-stage-one`` snapshot in ``definitions/``.
The 2.1.0 and 3.0.0 builders and their snapshots stay untouched; historical
runs keep their own pinned version identity through the registry.
"""

from __future__ import annotations

import dataclasses

from .definition import (
    build_challenge_cup_workflow_definition,
    definition_structure_hash,
)
from .definition_registry import (
    DefinitionIdentity,
    register_or_resolve,
)
from .models import WorkflowDefinition

STAGE_ONE_SCHEMA_VERSION = "2.2.0-stage-one"

# The seven retained nodes, in canonical 2.1.0 order: the six-node knowledge
# chain plus the hypothesis_design closure node.
STAGE_ONE_NODE_IDS: tuple[str, ...] = (
    "problem_understanding",
    "source_finding",
    "source_extraction",
    "evidence_relations",
    "knowledge_ingestion",
    "knowledge_handoff",
    "hypothesis_design",
)

# Edges retained from the 2.1.0 builder: the knowledge pipeline plus the
# cross-stage knowledge_handoff -> hypothesis_design edge.  ``e_hyp_proto``
# and every downstream edge are gone by construction (both endpoints must be
# retained nodes).
STAGE_ONE_EDGE_IDS: tuple[str, ...] = (
    "e_problem_find",
    "e_find_extract",
    "e_extract_rel",
    "e_rel_ingest",
    "e_ingest_handoff",
    "e_kc_hypothesis",
)


def build_stage_one_workflow_definition() -> WorkflowDefinition:
    """The stage-one truncated main flow: 2.1.0 minus everything after
    ``hypothesis_design``.

    Derived from the frozen 2.1.0 builder by keeping the seven stage-one
    nodes, the edges among them, and only the stages that still own nodes
    (``execution_iteration`` becomes empty and is dropped).  Fails closed if
    the 2.1.0 builder drifts away from the assumed stage-one shape.
    """
    base = build_challenge_cup_workflow_definition()
    kept = set(STAGE_ONE_NODE_IDS)
    missing = [
        node_id
        for node_id in STAGE_ONE_NODE_IDS
        if node_id not in {node.nodeId for node in base.nodes}
    ]
    if missing:
        raise ValueError(
            "main definition no longer carries the stage-one nodes; "
            f"missing={missing}"
        )
    nodes = tuple(node for node in base.nodes if node.nodeId in kept)
    edges = tuple(
        edge
        for edge in base.edges
        if edge.fromNodeId in kept and edge.toNodeId in kept
    )
    stages = tuple(
        dataclasses.replace(
            stage,
            nodeIds=tuple(node_id for node_id in stage.nodeIds if node_id in kept),
        )
        for stage in base.stages
    )
    stages = tuple(stage for stage in stages if stage.nodeIds)
    draft = WorkflowDefinition(
        workflowId=base.workflowId,
        schemaVersion=STAGE_ONE_SCHEMA_VERSION,
        label=base.label,
        stages=stages,
        nodes=nodes,
        edges=edges,
    )
    frozen = WorkflowDefinition(
        workflowId=draft.workflowId,
        schemaVersion=draft.schemaVersion,
        label=draft.label,
        stages=draft.stages,
        nodes=draft.nodes,
        edges=draft.edges,
        structureHash=definition_structure_hash(draft),
    )
    _assert_stage_one_shape(frozen)
    return frozen


def _assert_stage_one_shape(definition: WorkflowDefinition) -> None:
    """Fail closed when the derived graph is not the stage-one truncation."""
    node_ids = tuple(node.nodeId for node in definition.nodes)
    if node_ids != STAGE_ONE_NODE_IDS:
        raise ValueError(
            "stage-one definition node set drifted: "
            f"expected={STAGE_ONE_NODE_IDS} actual={node_ids}"
        )
    edge_ids = tuple(edge.edgeId for edge in definition.edges)
    if tuple(sorted(edge_ids)) != tuple(sorted(STAGE_ONE_EDGE_IDS)):
        raise ValueError(
            "stage-one definition edge set drifted: "
            f"expected={sorted(STAGE_ONE_EDGE_IDS)} actual={sorted(edge_ids)}"
        )
    sources = {edge.fromNodeId for edge in definition.edges}
    terminals = tuple(
        node.nodeId for node in definition.nodes if node.nodeId not in sources
    )
    if terminals != ("hypothesis_design",):
        raise ValueError(
            "stage-one definition must terminate at hypothesis_design; "
            f"terminals={terminals}"
        )


def stage_one_creation_definition() -> tuple[WorkflowDefinition, DefinitionIdentity]:
    """Definition + registered identity for hypothesis-first question runs.

    Run-creation entry point for the challenge-cup hypothesis chain: the
    truncated stage-one definition is registered (register-or-resolve) so the
    run's version identity is pinned before any checkpoint or ledger write.
    Historical 2.1.0/3.0.0 runs are always read through their own pinned
    registry identity; this choice only decides NEW question-run creation.
    """
    definition = build_stage_one_workflow_definition()
    return definition, register_or_resolve(definition)


__all__ = [
    "STAGE_ONE_EDGE_IDS",
    "STAGE_ONE_NODE_IDS",
    "STAGE_ONE_SCHEMA_VERSION",
    "build_stage_one_workflow_definition",
    "stage_one_creation_definition",
]
