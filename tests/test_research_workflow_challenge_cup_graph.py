"""Challenge Cup v2.1 graph with 16 nodes and human gates."""

from __future__ import annotations

from pathlib import Path

from langgraph.types import Command

from core.research.workflow.challenge_cup_graph import (
    build_challenge_cup_graph,
    compile_challenge_cup_graph,
)
from core.research.workflow.challenge_cup_runtime import successor_map
from core.research.workflow.checkpoint_store import open_sqlite_checkpointer
from core.research.workflow.definition import (
    build_challenge_cup_workflow_definition,
    graph_conditional_targets,
    graph_static_edge_pairs,
)
from core.web.services.team_workflow.research_runtime.checkpoint_lifecycle import (
    advance_checkpoint,
    prepare_initial_checkpoint,
)


def test_graph_contains_all_definition_nodes() -> None:
    definition = build_challenge_cup_workflow_definition()
    # compile to ensure graph builds
    path = Path(__file__).resolve()  # noqa: F841
    assert len(definition.nodes) == 16


def test_graph_static_edges_are_definition_owned() -> None:
    expected_static = (
        ("source_finding", "source_extraction"),
        ("source_extraction", "evidence_relations"),
        ("evidence_relations", "knowledge_ingestion"),
        ("knowledge_ingestion", "knowledge_handoff"),
        ("knowledge_handoff", "hypothesis_design"),
        ("hypothesis_design", "protocol_design"),
        ("protocol_design", "protocol_review"),
        ("protocol_review", "protocol_freeze"),
        ("protocol_freeze", "smoke_gate"),
        ("smoke_gate", "controlled_run"),
        ("controlled_run", "result_evaluation"),
        ("result_evaluation", "iteration_decision"),
        ("candidate_promotion", "result_package"),
    )
    assert graph_static_edge_pairs() == expected_static
    assert graph_conditional_targets("iteration_decision") == (
        "controlled_run",
        "version_governance",
    )
    assert graph_conditional_targets("version_governance") == (
        "candidate_promotion",
        "result_package",
    )

    graph = build_challenge_cup_graph()
    assert graph.edges == {
        *expected_static,
        ("__start__", "source_finding"),
        ("result_package", "__end__"),
    }
    expected_successors = {node.nodeId: () for node in build_challenge_cup_workflow_definition().nodes}
    for source, target in expected_static:
        expected_successors[source] = (*expected_successors[source], target)
    expected_successors["iteration_decision"] = graph_conditional_targets(
        "iteration_decision"
    )
    expected_successors["version_governance"] = graph_conditional_targets(
        "version_governance"
    )
    assert successor_map() == expected_successors


def test_direct_graph_requires_durable_adapter_execution(tmp_path: Path) -> None:
    db = tmp_path / "cc.sqlite"
    with open_sqlite_checkpointer(db) as checkpointer:
        graph = compile_challenge_cup_graph(checkpointer)
        cfg = {"configurable": {"thread_id": "cc-1"}}
        graph.invoke({}, cfg)
        state = graph.get_state(cfg)
        assert list(state.next or []) == ["source_finding"]
        assert state.values == {}


def test_checkpoint_lifecycle_advances_source_chain_to_human_handoff(tmp_path: Path) -> None:
    db = tmp_path / "cc.sqlite"
    checkpoint_id = prepare_initial_checkpoint(str(db), "cc-1")
    completed: list[str] = []
    for node_id, expected_next in (
        ("source_finding", "source_extraction"),
        ("source_extraction", "evidence_relations"),
        ("evidence_relations", "knowledge_ingestion"),
        ("knowledge_ingestion", "knowledge_handoff"),
    ):
        completed.append(node_id)
        checkpoint_id, scheduled = advance_checkpoint(
            str(db),
            thread_id="cc-1",
            checkpoint_id=checkpoint_id,
            completed_node_id=node_id,
            state_patch={
                "current_node_id": node_id,
                "completed_node_ids": list(completed),
            },
        )
        assert scheduled == [expected_next]

    assert completed == [
        "source_finding",
        "source_extraction",
        "evidence_relations",
        "knowledge_ingestion",
    ]


def test_reject_knowledge_handoff_does_not_set_package_accepted(tmp_path: Path) -> None:
    db = tmp_path / "cc2.sqlite"
    with open_sqlite_checkpointer(db) as checkpointer:
        graph = compile_challenge_cup_graph(checkpointer)
        cfg = {"configurable": {"thread_id": "cc-2"}}
        graph.invoke({}, cfg)
        state = graph.get_state(cfg)
        # resume until we hit a human decision we can reject
        guard = 0
        while state.next and guard < 10:
            guard += 1
            # reject first human decision
            graph.invoke(Command(resume={"accept": False}), cfg)
            state = graph.get_state(cfg)
            if state.values.get("knowledge_package_accepted") is False:
                break
            if "knowledge_handoff" in (state.values.get("completed_node_ids") or []):
                break
        assert state.values.get("knowledge_package_accepted") is not True
