"""Knowledge-collection sideflow and main-flow v3.0.0 workflow definitions.

Two pinned ``WorkflowDefinition`` variants live here so
``definition.py`` keeps its frozen 2.1.0 default untouched:

- ``challenge-cup-knowledge-sideflow`` (schema 1.0.0): the five knowledge
  nodes as an independent child workflow (source_finding → … →
  knowledge_handoff HUMAN gate).  Knowledge collection runs as its own
  ``WorkflowRun``; results cross back to a parent run through the durable
  ``event_publish`` outbox instead of an in-graph edge.
- ``challenge-cup-research`` (schema 3.0.0): the main chain without the
  five in-graph knowledge nodes; ``problem_understanding`` feeds
  ``hypothesis_design`` directly and the ``e_kc_hypothesis`` edge is gone.
  It is NOT the default for new runs — rollout is a separate task.

Both builders are pure: they never mutate the 2.1.0 builder output and are
the only sources of the snapshots in ``definitions/``.
"""

from __future__ import annotations

import dataclasses

from .definition import (
    CHALLENGE_CUP_WORKFLOW_ID,
    definition_structure_hash,
)
from .models import (
    GateKind,
    WorkflowDefinition,
    WorkflowEdgeSpec,
    WorkflowStageId,
    WorkflowStageSpec,
)

KNOWLEDGE_SIDEFLOW_WORKFLOW_ID = "challenge-cup-knowledge-sideflow"
KNOWLEDGE_SIDEFLOW_SCHEMA_VERSION = "1.0.0"
KNOWLEDGE_SIDEFLOW_LABEL = "挑战杯知识搜集子流程"

CHALLENGE_CUP_RESEARCH_SCHEMA_VERSION_V3 = "3.0.0"

# Node ids of the five-node knowledge chain, in canonical order.
KNOWLEDGE_SIDEFLOW_NODE_IDS: tuple[str, ...] = (
    "source_finding",
    "source_extraction",
    "evidence_relations",
    "knowledge_ingestion",
    "knowledge_handoff",
)


def _frozen_definition(draft: WorkflowDefinition) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflowId=draft.workflowId,
        schemaVersion=draft.schemaVersion,
        label=draft.label,
        stages=draft.stages,
        nodes=draft.nodes,
        edges=draft.edges,
        structureHash=definition_structure_hash(draft),
    )


def build_knowledge_sideflow_workflow_definition() -> WorkflowDefinition:
    """The independent five-node knowledge collection child workflow.

    Node specs intentionally mirror the same-named nodes of the main 2.1.0
    definition (same stage/actor/role/artifact kinds) so downstream adapters
    and readiness evaluators stay definition-agnostic.  The definition is
    built explicitly (not derived at import time from the 2.1.0 builder) so
    later drift in the main definition can never silently re-shape an
    already-pinned sideflow version.
    """
    from .definition import _KNOWLEDGE_NODES  # noqa: PLC2701 - single-source specs

    by_id = {node.nodeId: node for node in _KNOWLEDGE_NODES}
    missing = [node_id for node_id in KNOWLEDGE_SIDEFLOW_NODE_IDS if node_id not in by_id]
    if missing:
        raise ValueError(
            "main definition no longer carries sideflow nodes; "
            f"missing={missing}"
        )
    nodes = tuple(by_id[node_id] for node_id in KNOWLEDGE_SIDEFLOW_NODE_IDS)
    stages = (
        WorkflowStageSpec(
            stageId=WorkflowStageId.KNOWLEDGE_COLLECTION,
            index=1,
            label="知识搜集",
            nodeIds=KNOWLEDGE_SIDEFLOW_NODE_IDS,
        ),
    )
    main = _KNOWLEDGE_NODES
    main_ids = {node.nodeId for node in main}
    edges = tuple(
        edge
        for edge in _sideflow_candidate_edges()
        if edge.fromNodeId in main_ids and edge.toNodeId in main_ids
    )
    draft = WorkflowDefinition(
        workflowId=KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
        schemaVersion=KNOWLEDGE_SIDEFLOW_SCHEMA_VERSION,
        label=KNOWLEDGE_SIDEFLOW_LABEL,
        stages=stages,
        nodes=nodes,
        edges=edges,
    )
    return _frozen_definition(draft)


def _sideflow_candidate_edges() -> tuple[WorkflowEdgeSpec, ...]:
    """Edges among the five knowledge nodes, copied from the 2.1.0 builder.

    Re-declared here (same identity fields) instead of importing the private
    ``_edges`` so the sideflow stays an explicit, reviewable topology.
    """
    from .definition import _edges  # noqa: PLC2701 - identity reuse, not drift

    sideflow_ids = set(KNOWLEDGE_SIDEFLOW_NODE_IDS)
    return tuple(
        edge for edge in _edges() if edge.fromNodeId in sideflow_ids and edge.toNodeId in sideflow_ids
    )


def build_challenge_cup_workflow_definition_v3() -> WorkflowDefinition:
    """Main flow 3.0.0: knowledge collection leaves the in-graph chain.

    Derived from the frozen 2.1.0 builder by removing the five knowledge
    nodes and every edge touching them, then connecting
    ``problem_understanding`` directly to ``hypothesis_design``.  Rollout as
    the default run definition is explicitly out of scope here.
    """
    base = _frozen_definition(_v3_base_draft())
    kept_node_ids = {node.nodeId for node in base.nodes}
    edges = [
        edge
        for edge in base.edges
        if edge.fromNodeId in kept_node_ids and edge.toNodeId in kept_node_ids
    ]
    edges.append(
        WorkflowEdgeSpec(
            "e_problem_hypothesis",
            "problem_understanding",
            "hypothesis_design",
            "问题理解",
            GateKind.AUTO,
            ("problem_understanding",),
        )
    )
    draft = WorkflowDefinition(
        workflowId=CHALLENGE_CUP_WORKFLOW_ID,
        schemaVersion=CHALLENGE_CUP_RESEARCH_SCHEMA_VERSION_V3,
        label=base.label,
        stages=base.stages,
        nodes=base.nodes,
        edges=tuple(edges),
    )
    return _frozen_definition(draft)


def _v3_base_draft() -> WorkflowDefinition:
    """2.1.0 definition minus the five sideflow knowledge nodes.

    ``problem_understanding`` is the 3.0.0 entry.  Knowledge collection has
    left the main flow, so the entry no longer sits in a
    ``knowledge_collection`` stage: the first stage is renamed to
    ``problem_understanding`` (label ``问题理解``) to keep stage naming
    consistent with that semantics.  The five sideflow nodes (and every edge
    touching them) are gone.
    """
    from .definition import build_challenge_cup_workflow_definition

    base = build_challenge_cup_workflow_definition()
    sideflow_ids = set(KNOWLEDGE_SIDEFLOW_NODE_IDS)
    nodes = tuple(node for node in base.nodes if node.nodeId not in sideflow_ids)
    stages = tuple(
        dataclasses.replace(
            stage,
            nodeIds=tuple(n for n in stage.nodeIds if n not in sideflow_ids),
        )
        for stage in base.stages
    )
    stages = tuple(stage for stage in stages if stage.nodeIds)
    # 知识搜集已移出主流程：3.0.0 首阶段改为独立的问题理解语义。
    nodes = tuple(
        dataclasses.replace(node, stageId=WorkflowStageId.PROBLEM_UNDERSTANDING)
        if node.nodeId == "problem_understanding"
        else node
        for node in nodes
    )
    stages = tuple(
        dataclasses.replace(
            stage,
            stageId=WorkflowStageId.PROBLEM_UNDERSTANDING,
            label="问题理解",
        )
        if stage.stageId == WorkflowStageId.KNOWLEDGE_COLLECTION
        else stage
        for stage in stages
    )
    return WorkflowDefinition(
        workflowId=base.workflowId,
        schemaVersion=base.schemaVersion,
        label=base.label,
        stages=stages,
        nodes=nodes,
        edges=base.edges,
    )
