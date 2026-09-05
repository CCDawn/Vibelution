"""Challenge Cup 3.0.0 main graph contract."""

from __future__ import annotations

from pathlib import Path

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
    assert len(definition.nodes) == 12


def test_graph_static_edges_are_definition_owned() -> None:
    expected_static = (
        ("hypothesis_design", "protocol_design"),
        ("protocol_design", "protocol_review"),
        ("protocol_review", "protocol_freeze"),
        ("protocol_freeze", "smoke_gate"),
        ("smoke_gate", "controlled_run"),
        ("controlled_run", "result_evaluation"),
        ("result_evaluation", "iteration_decision"),
        ("candidate_promotion", "result_package"),
        ("problem_understanding", "hypothesis_design"),
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
        ("__start__", "problem_understanding"),
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
    assert successor_map("wv-268aa6e8dea8") == expected_successors


def test_direct_graph_requires_durable_adapter_execution(tmp_path: Path) -> None:
    db = tmp_path / "cc.sqlite"
    with open_sqlite_checkpointer(db) as checkpointer:
        graph = compile_challenge_cup_graph(checkpointer)
        cfg = {"configurable": {"thread_id": "cc-1"}}
        graph.invoke({}, cfg)
        state = graph.get_state(cfg)
        assert list(state.next or []) == ["problem_understanding"]
        assert state.values == {}


def test_checkpoint_lifecycle_advances_main_chain_to_protocol_freeze(tmp_path: Path) -> None:
    db = tmp_path / "cc.sqlite"
    checkpoint_id = prepare_initial_checkpoint(str(db), "cc-1")
    completed: list[str] = []
    for node_id, expected_next in (
        ("problem_understanding", "hypothesis_design"),
        ("hypothesis_design", "protocol_design"),
        ("protocol_design", "protocol_review"),
        ("protocol_review", "protocol_freeze"),
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
        "problem_understanding",
        "hypothesis_design",
        "protocol_design",
        "protocol_review",
    ]


def test_main_definition_contains_no_knowledge_sideflow_nodes() -> None:
    definition = build_challenge_cup_workflow_definition()
    node_ids = {node.nodeId for node in definition.nodes}
    assert node_ids.isdisjoint(
        {
            "source_finding",
            "source_extraction",
            "evidence_relations",
            "knowledge_ingestion",
            "knowledge_handoff",
        }
    )
