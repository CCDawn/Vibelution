"""Handoff consumability rules — downstream only accepts accepted handoffs."""

from __future__ import annotations

from .definition import build_challenge_cup_workflow_definition
from .models import GateKind, HandoffStatus, NodeHandoffRecord, WorkflowEdgeSpec


def edge_for(from_node_id: str, to_node_id: str) -> WorkflowEdgeSpec | None:
    definition = build_challenge_cup_workflow_definition()
    for edge in definition.edges:
        if edge.fromNodeId == from_node_id and edge.toNodeId == to_node_id:
            return edge
    return None


def can_consume_handoff(record: NodeHandoffRecord | None) -> bool:
    if record is None:
        return False
    return record.status is HandoffStatus.ACCEPTED and bool(record.inputSnapshotHash)


def is_cross_stage_edge(edge: WorkflowEdgeSpec) -> bool:
    return edge.gateKind in {
        GateKind.KNOWLEDGE_PACKAGE,
        GateKind.FROZEN_PROTOCOL,
        GateKind.SMOKE,
    }


def experiment_entry_unlocked(
    *,
    knowledge_package_handoff: NodeHandoffRecord | None,
) -> bool:
    """Hypothesis may not start on mere 'sources exist' — needs accepted package."""
    if not can_consume_handoff(knowledge_package_handoff):
        return False
    if knowledge_package_handoff is None:
        return False
    if knowledge_package_handoff.fromNodeId != "knowledge_handoff":
        return False
    if knowledge_package_handoff.toNodeId != "hypothesis_design":
        return False
    kinds = {ref.kind for ref in knowledge_package_handoff.outputArtifactRefs}
    return "knowledge_package" in kinds


def controlled_run_unlocked(
    *,
    smoke_handoff: NodeHandoffRecord | None,
    frozen_protocol_present: bool,
) -> bool:
    """Controlled run needs frozen protocol + accepted smoke release — not just a plan."""
    if not frozen_protocol_present:
        return False
    if not can_consume_handoff(smoke_handoff):
        return False
    if smoke_handoff is None:
        return False
    if smoke_handoff.fromNodeId != "smoke_gate" or smoke_handoff.toNodeId != "controlled_run":
        return False
    kinds = {ref.kind for ref in smoke_handoff.outputArtifactRefs}
    return "smoke_release" in kinds or "frozen_protocol" in kinds


def progress_alone_does_not_unlock_experiment(
    *,
    has_sources: bool,
    has_knowledge_package_accepted: bool,
) -> bool:
    """Characterization of product rule: sources alone never unlock experiment."""
    if has_sources and not has_knowledge_package_accepted:
        return False
    return has_knowledge_package_accepted


def plan_alone_does_not_unlock_controlled_run(
    *,
    has_experiment_plan: bool,
    has_frozen_protocol: bool,
    has_smoke_accept: bool,
) -> bool:
    if has_experiment_plan and not (has_frozen_protocol and has_smoke_accept):
        return False
    return has_frozen_protocol and has_smoke_accept
