"""Fixed Challenge Cup research workflow definition and structure hash."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import (
    ActorKind,
    GateKind,
    NodeSessionScopePolicy,
    WorkflowDefinition,
    WorkflowEdgeSpec,
    WorkflowNodeSpec,
    WorkflowStageId,
    WorkflowStageSpec,
)

CHALLENGE_CUP_WORKFLOW_ID = "challenge-cup-research"
SCHEMA_VERSION = "2.1.0"

# Canonical fixed node order within each stage (ADR 0006 / PRD / ADR 0007).
_KNOWLEDGE_NODES: tuple[WorkflowNodeSpec, ...] = (
    WorkflowNodeSpec(
        nodeId="problem_understanding",
        stageId=WorkflowStageId.KNOWLEDGE_COLLECTION,
        label="问题理解",
        actorKind=ActorKind.AGENT,
        primaryRoleKey="source_finder",
        producesArtifactKinds=("problem_understanding",),
    ),
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

_EXPERIMENT_NODES: tuple[WorkflowNodeSpec, ...] = (
    WorkflowNodeSpec(
        nodeId="hypothesis_design",
        stageId=WorkflowStageId.EXPERIMENT_DESIGN,
        label="假设设计",
        actorKind=ActorKind.AGENT,
        primaryRoleKey="experiment_planner",
        acceptsGateKinds=(GateKind.KNOWLEDGE_PACKAGE,),
        producesArtifactKinds=("hypothesis_set",),
        sessionScopePolicy=NodeSessionScopePolicy.CANDIDATE_FAN_OUT,
    ),
    WorkflowNodeSpec(
        nodeId="protocol_design",
        stageId=WorkflowStageId.EXPERIMENT_DESIGN,
        label="协议设计",
        actorKind=ActorKind.AGENT,
        primaryRoleKey="experiment_planner",
        producesArtifactKinds=("research_plan", "protocol_draft"),
    ),
    WorkflowNodeSpec(
        nodeId="protocol_review",
        stageId=WorkflowStageId.EXPERIMENT_DESIGN,
        label="协议评审",
        actorKind=ActorKind.AGENT,
        primaryRoleKey="experiment_ledger",
        producesArtifactKinds=("protocol_review_report",),
    ),
    WorkflowNodeSpec(
        nodeId="protocol_freeze",
        stageId=WorkflowStageId.EXPERIMENT_DESIGN,
        label="协议冻结",
        actorKind=ActorKind.HUMAN,
        primaryRoleKey="research_owner",
        acceptsGateKinds=(GateKind.HUMAN,),
        producesArtifactKinds=("frozen_protocol",),
    ),
    WorkflowNodeSpec(
        nodeId="smoke_gate",
        stageId=WorkflowStageId.EXPERIMENT_DESIGN,
        label="试跑放行",
        actorKind=ActorKind.HUMAN,
        primaryRoleKey="research_owner",
        acceptsGateKinds=(GateKind.SMOKE, GateKind.HUMAN, GateKind.FROZEN_PROTOCOL),
        producesArtifactKinds=("smoke_evidence", "smoke_release"),
    ),
)

_ITERATION_NODES: tuple[WorkflowNodeSpec, ...] = (
    WorkflowNodeSpec(
        nodeId="controlled_run",
        stageId=WorkflowStageId.EXECUTION_ITERATION,
        label="受控运行",
        actorKind=ActorKind.SYSTEM,
        primaryRoleKey="formal_runner",
        acceptsGateKinds=(GateKind.FROZEN_PROTOCOL, GateKind.SMOKE),
        producesArtifactKinds=("run_artifacts",),
    ),
    WorkflowNodeSpec(
        nodeId="result_evaluation",
        stageId=WorkflowStageId.EXECUTION_ITERATION,
        label="结果评价",
        actorKind=ActorKind.AGENT,
        primaryRoleKey="experiment_ledger",
        producesArtifactKinds=("evaluation_report",),
    ),
    WorkflowNodeSpec(
        nodeId="iteration_decision",
        stageId=WorkflowStageId.EXECUTION_ITERATION,
        label="迭代决策",
        actorKind=ActorKind.AGENT,
        primaryRoleKey="iteration_planner",
        producesArtifactKinds=("iteration_decision",),
    ),
    WorkflowNodeSpec(
        nodeId="version_governance",
        stageId=WorkflowStageId.EXECUTION_ITERATION,
        label="版本治理",
        actorKind=ActorKind.AGENT,
        primaryRoleKey="iteration_versioning",
        producesArtifactKinds=("version_governance_record",),
    ),
    WorkflowNodeSpec(
        nodeId="candidate_promotion",
        stageId=WorkflowStageId.EXECUTION_ITERATION,
        label="候选晋升",
        actorKind=ActorKind.HUMAN,
        primaryRoleKey="iteration_versioning",
        acceptsGateKinds=(GateKind.PROMOTION, GateKind.HUMAN),
        producesArtifactKinds=("promotion_proposal",),
    ),
    WorkflowNodeSpec(
        nodeId="result_package",
        stageId=WorkflowStageId.EXECUTION_ITERATION,
        label="结果打包",
        actorKind=ActorKind.SYSTEM,
        primaryRoleKey="package_builder",
        producesArtifactKinds=("research_result_package",),
    ),
)


def _edges() -> tuple[WorkflowEdgeSpec, ...]:
    auto = GateKind.AUTO
    return (
        # Knowledge pipeline
        WorkflowEdgeSpec(
            "e_problem_find",
            "problem_understanding",
            "source_finding",
            "问题理解",
            auto,
            ("problem_understanding",),
        ),
        WorkflowEdgeSpec("e_find_extract", "source_finding", "source_extraction", "候选资料", auto, ("source_candidate_batch",)),
        WorkflowEdgeSpec("e_extract_rel", "source_extraction", "evidence_relations", "证据卡", auto, ("evidence_card_batch",)),
        WorkflowEdgeSpec("e_rel_ingest", "evidence_relations", "knowledge_ingestion", "关系图", auto, ("evidence_relation_graph",)),
        WorkflowEdgeSpec(
            "e_ingest_handoff",
            "knowledge_ingestion",
            "knowledge_handoff",
            "入库草稿",
            GateKind.HUMAN,
            ("knowledge_package_draft",),
            requiresHumanAccept=True,
        ),
        # Cross-stage: knowledge -> experiment
        WorkflowEdgeSpec(
            "e_kc_hypothesis",
            "knowledge_handoff",
            "hypothesis_design",
            "知识包",
            GateKind.KNOWLEDGE_PACKAGE,
            ("knowledge_package",),
            requiresHumanAccept=True,
        ),
        # Experiment pipeline
        WorkflowEdgeSpec("e_hyp_proto", "hypothesis_design", "protocol_design", "假设集", auto, ("hypothesis_set",)),
        WorkflowEdgeSpec("e_proto_review", "protocol_design", "protocol_review", "协议草稿", auto, ("protocol_draft",)),
        WorkflowEdgeSpec(
            "e_review_freeze",
            "protocol_review",
            "protocol_freeze",
            "评审通过",
            GateKind.HUMAN,
            ("protocol_review_report",),
            requiresHumanAccept=True,
        ),
        WorkflowEdgeSpec(
            "e_freeze_smoke",
            "protocol_freeze",
            "smoke_gate",
            "冻结协议",
            GateKind.FROZEN_PROTOCOL,
            ("frozen_protocol",),
        ),
        # Cross-stage: experiment -> iteration
        WorkflowEdgeSpec(
            "e_smoke_run",
            "smoke_gate",
            "controlled_run",
            "试跑放行",
            GateKind.SMOKE,
            ("smoke_release", "frozen_protocol"),
            requiresHumanAccept=True,
        ),
        # Iteration pipeline
        WorkflowEdgeSpec("e_run_eval", "controlled_run", "result_evaluation", "运行产物", auto, ("run_artifacts",)),
        WorkflowEdgeSpec("e_eval_decision", "result_evaluation", "iteration_decision", "评价报告", auto, ("evaluation_report",)),
        # Conditional routes from iteration_decision (must match LangGraph conditional edges).
        # revise_protocol forks a child WorkflowRun — no in-run edge.
        WorkflowEdgeSpec(
            "e_decision_rerun",
            "iteration_decision",
            "controlled_run",
            "同协议重跑",
            auto,
            ("iteration_decision", "frozen_protocol"),
        ),
        WorkflowEdgeSpec(
            "e_decision_promote",
            "iteration_decision",
            "version_governance",
            "晋升版本",
            auto,
            ("iteration_decision",),
        ),
        WorkflowEdgeSpec(
            "e_decision_rollback",
            "iteration_decision",
            "version_governance",
            "回滚版本",
            auto,
            ("iteration_decision",),
        ),
        WorkflowEdgeSpec(
            "e_decision_stop",
            "iteration_decision",
            "version_governance",
            "停止迭代",
            auto,
            ("iteration_decision",),
        ),
        WorkflowEdgeSpec(
            "e_version_promotion",
            "version_governance",
            "candidate_promotion",
            "晋升提案",
            GateKind.PROMOTION,
            ("version_governance_record",),
            requiresHumanAccept=True,
        ),
        WorkflowEdgeSpec(
            "e_version_package",
            "version_governance",
            "result_package",
            "停止并打包",
            auto,
            ("version_governance_record",),
        ),
        WorkflowEdgeSpec(
            "e_promo_package",
            "candidate_promotion",
            "result_package",
            "确认晋升/回滚",
            GateKind.HUMAN,
            ("promotion_proposal",),
            requiresHumanAccept=True,
        ),
    )


# LangGraph represents these edges with ``add_edge``.  The two decision nodes
# below are represented with conditional branches instead, so their outgoing
# edge specs are consumed by ``graph_conditional_targets``.  Keeping the
# filtering here makes this definition the only source of the graph topology;
# the executable graph must not maintain a second hand-written edge list.
_CONDITIONAL_GRAPH_SOURCES = frozenset({"iteration_decision", "version_governance"})


def graph_static_edge_pairs() -> tuple[tuple[str, str], ...]:
    """Return definition edges installed as ordinary LangGraph edges."""

    return tuple(
        (edge.fromNodeId, edge.toNodeId)
        for edge in _edges()
        if edge.fromNodeId not in _CONDITIONAL_GRAPH_SOURCES
    )


def graph_conditional_targets(source_node_id: str) -> tuple[str, ...]:
    """Return unique conditional destinations for one graph decision node."""

    if source_node_id not in _CONDITIONAL_GRAPH_SOURCES:
        raise ValueError(f"{source_node_id!r} is not a conditional graph source")
    return tuple(
        dict.fromkeys(
            edge.toNodeId
            for edge in _edges()
            if edge.fromNodeId == source_node_id
        )
    )


def _canonical_payload(definition: WorkflowDefinition) -> dict[str, Any]:
    """Stable JSON shape for hashing — excludes structureHash itself."""
    return {
        "workflowId": definition.workflowId,
        "schemaVersion": definition.schemaVersion,
        "label": definition.label,
        "stages": [s.to_dict() for s in definition.stages],
        "nodes": [n.to_dict() for n in definition.nodes],
        "edges": [e.to_dict() for e in definition.edges],
    }


def definition_structure_hash(definition: WorkflowDefinition) -> str:
    payload = _canonical_payload(definition)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_challenge_cup_workflow_definition() -> WorkflowDefinition:
    stages = (
        WorkflowStageSpec(
            stageId=WorkflowStageId.KNOWLEDGE_COLLECTION,
            index=1,
            label="知识搜集",
            nodeIds=tuple(n.nodeId for n in _KNOWLEDGE_NODES),
        ),
        WorkflowStageSpec(
            stageId=WorkflowStageId.EXPERIMENT_DESIGN,
            index=2,
            label="实验设计",
            nodeIds=tuple(n.nodeId for n in _EXPERIMENT_NODES),
        ),
        WorkflowStageSpec(
            stageId=WorkflowStageId.EXECUTION_ITERATION,
            index=3,
            label="执行迭代",
            nodeIds=tuple(n.nodeId for n in _ITERATION_NODES),
        ),
    )
    nodes = _KNOWLEDGE_NODES + _EXPERIMENT_NODES + _ITERATION_NODES
    edges = _edges()
    draft = WorkflowDefinition(
        workflowId=CHALLENGE_CUP_WORKFLOW_ID,
        schemaVersion=SCHEMA_VERSION,
        label="挑战杯科研流程",
        stages=stages,
        nodes=nodes,
        edges=edges,
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


def node_by_id(definition: WorkflowDefinition | None = None) -> dict[str, WorkflowNodeSpec]:
    d = definition or build_challenge_cup_workflow_definition()
    return {n.nodeId: n for n in d.nodes}
