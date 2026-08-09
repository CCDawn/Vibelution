"""Task 1: research workflow domain contract tests."""

from __future__ import annotations

from core.research.workflow.bindings import (
    agent_id_from_run_snapshot,
    build_run_binding_snapshots,
    resolve_effective_agent_id,
)
from core.research.workflow.definition import (
    CHALLENGE_CUP_WORKFLOW_ID,
    build_challenge_cup_workflow_definition,
    definition_structure_hash,
)
from core.research.workflow.handoff import (
    can_consume_handoff,
    controlled_run_unlocked,
    experiment_entry_unlocked,
    plan_alone_does_not_unlock_controlled_run,
    progress_alone_does_not_unlock_experiment,
)
from core.research.workflow.iteration_decisions import (
    ITERATION_DEFINITION_EDGE_IDS,
    IterationDecisionKind,
)
from core.research.workflow.models import (
    ActorKind,
    AgentBindingLayers,
    ArtifactRef,
    GateKind,
    HandoffStatus,
    NodeHandoffRecord,
    NodeRunStatus,
    can_transition_node_run,
)
from core.research.workflow.projection import build_canvas_projection


def test_definition_hash_is_stable() -> None:
    a = build_challenge_cup_workflow_definition()
    b = build_challenge_cup_workflow_definition()
    assert a.structureHash == b.structureHash
    assert a.structureHash == definition_structure_hash(a)
    assert len(a.structureHash) == 64
    assert a.workflowId == CHALLENGE_CUP_WORKFLOW_ID


def test_definition_has_three_stages_and_sixteen_nodes() -> None:
    d = build_challenge_cup_workflow_definition()
    assert len(d.stages) == 3
    assert len(d.nodes) == 16
    assert {s.stageId.value for s in d.stages} == {
        "knowledge_collection",
        "experiment_design",
        "execution_iteration",
    }
    node_ids = [n.nodeId for n in d.nodes]
    assert node_ids == [
        "source_finding",
        "source_extraction",
        "evidence_relations",
        "knowledge_ingestion",
        "knowledge_handoff",
        "hypothesis_design",
        "protocol_design",
        "protocol_review",
        "protocol_freeze",
        "smoke_gate",
        "controlled_run",
        "result_evaluation",
        "iteration_decision",
        "version_governance",
        "candidate_promotion",
        "result_package",
    ]


def test_actor_kinds_match_adr0007() -> None:
    by_id = {n.nodeId: n for n in build_challenge_cup_workflow_definition().nodes}
    assert by_id["source_finding"].actorKind is ActorKind.AGENT
    assert by_id["knowledge_handoff"].actorKind is ActorKind.HUMAN
    assert by_id["protocol_freeze"].actorKind is ActorKind.HUMAN
    assert by_id["smoke_gate"].actorKind is ActorKind.HUMAN
    assert by_id["controlled_run"].actorKind is ActorKind.SYSTEM
    assert by_id["result_package"].actorKind is ActorKind.SYSTEM
    assert by_id["version_governance"].actorKind is ActorKind.AGENT
    assert by_id["candidate_promotion"].actorKind is ActorKind.HUMAN


def test_iteration_outcomes_have_distinct_definition_edges() -> None:
    definition = build_challenge_cup_workflow_definition()
    edges = {edge.edgeId: edge for edge in definition.edges}
    expected = {
        IterationDecisionKind.RERUN_SAME_PROTOCOL: "e_decision_rerun",
        IterationDecisionKind.PROMOTE_CANDIDATE: "e_decision_promote",
        IterationDecisionKind.ROLLBACK_CANDIDATE: "e_decision_rollback",
        IterationDecisionKind.STOP: "e_decision_stop",
    }

    assert {kind: ITERATION_DEFINITION_EDGE_IDS[kind] for kind in expected} == expected
    for edge_id in expected.values():
        edge = edges[edge_id]
        assert edge.fromNodeId == "iteration_decision"
    assert edges["e_decision_rerun"].toNodeId == "controlled_run"
    assert edges["e_decision_promote"].toNodeId == "version_governance"
    assert edges["e_decision_rollback"].toNodeId == "version_governance"
    assert edges["e_decision_stop"].toNodeId == "version_governance"


def test_binding_resolution_order_node_over_stage_over_workflow() -> None:
    d = build_challenge_cup_workflow_definition()
    node = next(n for n in d.nodes if n.nodeId == "source_finding")
    layers = AgentBindingLayers(
        workflowDefaults={"source_finder": "agent-workflow"},
        stageOverrides={"knowledge_collection": {"source_finder": "agent-stage"}},
        nodeOverrides={"source_finding": "agent-node"},
    )
    agent_id, source = resolve_effective_agent_id(node, layers)
    assert agent_id == "agent-node"
    assert source == "node_override"

    layers2 = AgentBindingLayers(
        workflowDefaults={"source_finder": "agent-workflow"},
        stageOverrides={"knowledge_collection": {"source_finder": "agent-stage"}},
    )
    agent_id2, source2 = resolve_effective_agent_id(node, layers2)
    assert agent_id2 == "agent-stage"
    assert source2 == "stage_override"

    layers3 = AgentBindingLayers(workflowDefaults={"source_finder": "agent-workflow"})
    agent_id3, source3 = resolve_effective_agent_id(node, layers3)
    assert agent_id3 == "agent-workflow"
    assert source3 == "workflow_default"


def test_run_snapshot_not_rewritten_by_live_config_change() -> None:
    layers = AgentBindingLayers(workflowDefaults={"source_finder": "agent-a"})
    snaps = build_run_binding_snapshots(
        run_id="run-1",
        workflow_version_id="wv-1",
        layers=layers,
        captured_at="2026-08-07T00:00:00Z",
    )
    by_node = {s.nodeId: s for s in snaps}
    assert by_node["source_finding"].agentId == "agent-a"

    # Live config would now point elsewhere — history still reads snapshot.
    live = AgentBindingLayers(workflowDefaults={"source_finder": "agent-b"})
    assert resolve_effective_agent_id(
        next(n for n in build_challenge_cup_workflow_definition().nodes if n.nodeId == "source_finding"),
        live,
    )[0] == "agent-b"
    assert agent_id_from_run_snapshot(by_node, "source_finding") == "agent-a"


def test_handoff_only_accepted_is_consumable() -> None:
    base = {
        "handoffId": "h1",
        "workflowId": CHALLENGE_CUP_WORKFLOW_ID,
        "workflowVersionId": "wv-1",
        "runId": "run-1",
        "fromNodeId": "knowledge_handoff",
        "fromNodeRunId": "nr-1",
        "toNodeId": "hypothesis_design",
        "gateKind": GateKind.KNOWLEDGE_PACKAGE,
        "outputArtifactRefs": (
            ArtifactRef(
                artifactId="a1",
                kind="knowledge_package",
                version="1",
                contentHash="abc",
            ),
        ),
        "inputSnapshotHash": "abc",
        "offeredAt": "2026-08-07T00:00:00Z",
    }
    pending = NodeHandoffRecord(**base, status=HandoffStatus.PENDING)
    accepted = NodeHandoffRecord(**base, status=HandoffStatus.ACCEPTED)
    rejected = NodeHandoffRecord(**base, status=HandoffStatus.REJECTED)
    assert can_consume_handoff(pending) is False
    assert can_consume_handoff(accepted) is True
    assert can_consume_handoff(rejected) is False


def test_sources_alone_do_not_unlock_experiment() -> None:
    assert progress_alone_does_not_unlock_experiment(has_sources=True, has_knowledge_package_accepted=False) is False
    assert progress_alone_does_not_unlock_experiment(has_sources=True, has_knowledge_package_accepted=True) is True
    assert experiment_entry_unlocked(knowledge_package_handoff=None) is False


def test_plan_alone_does_not_unlock_controlled_run() -> None:
    assert (
        plan_alone_does_not_unlock_controlled_run(
            has_experiment_plan=True,
            has_frozen_protocol=False,
            has_smoke_accept=False,
        )
        is False
    )
    assert (
        plan_alone_does_not_unlock_controlled_run(
            has_experiment_plan=True,
            has_frozen_protocol=True,
            has_smoke_accept=True,
        )
        is True
    )
    assert controlled_run_unlocked(smoke_handoff=None, frozen_protocol_present=True) is False


def test_projection_never_includes_selected_node_id() -> None:
    proj = build_canvas_projection(
        run_id="run-1",
        runtime_current_node_ids=["source_extraction"],
    )
    raw = str(proj)
    assert "selectedNodeId" not in raw
    assert "selected_node" not in raw
    assert proj["run"]["runtimeCurrentNodeIds"] == ["source_extraction"]
    assert proj["definition"]["workflowId"] == CHALLENGE_CUP_WORKFLOW_ID


def test_node_run_transitions_block_illegal_jumps() -> None:
    assert can_transition_node_run(NodeRunStatus.PENDING, NodeRunStatus.READY) is True
    assert can_transition_node_run(NodeRunStatus.SUCCEEDED, NodeRunStatus.RUNNING) is False
    assert can_transition_node_run(NodeRunStatus.FAILED, NodeRunStatus.READY) is True
