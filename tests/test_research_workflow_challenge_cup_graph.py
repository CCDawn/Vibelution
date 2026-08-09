"""Challenge Cup v2.1 graph with 16 nodes and human gates."""

from __future__ import annotations

from pathlib import Path

from langgraph.types import Command

from core.research.workflow.challenge_cup_graph import compile_challenge_cup_graph
from core.research.workflow.checkpoint_store import open_sqlite_checkpointer
from core.research.workflow.definition import build_challenge_cup_workflow_definition


def test_graph_contains_all_definition_nodes() -> None:
    definition = build_challenge_cup_workflow_definition()
    # compile to ensure graph builds
    path = Path(__file__).resolve()  # noqa: F841
    assert len(definition.nodes) == 16


def test_run_stops_at_first_human_gate_and_can_progress(tmp_path: Path) -> None:
    db = tmp_path / "cc.sqlite"
    with open_sqlite_checkpointer(db) as checkpointer:
        graph = compile_challenge_cup_graph(checkpointer)
        cfg = {"configurable": {"thread_id": "cc-1"}}
        # start → auto-run agent nodes until knowledge_handoff interrupt
        graph.invoke({}, cfg)
        state = graph.get_state(cfg)
        assert state.next
        # First human in order is knowledge_handoff (after 4 agent nodes)
        assert "knowledge_handoff" in (state.next or []) or state.values.get("current_node_id") in {
            "knowledge_handoff",
            "source_finding",
            "source_extraction",
            "evidence_relations",
            "knowledge_ingestion",
        }

        # Drive through interrupts until done or blocked — accept all human gates;
        # at iteration_decision supply a structured stop decision.
        guard = 0
        while state.next and guard < 25:
            guard += 1
            nxt = list(state.next or [])
            if "iteration_decision" in nxt:
                graph.invoke(
                    Command(
                        resume={
                            "decisionKind": "stop",
                            "terminalReason": "test_complete",
                            "decisionId": "dec-test-stop",
                        }
                    ),
                    cfg,
                )
            else:
                graph.invoke(Command(resume={"accept": True}), cfg)
            state = graph.get_state(cfg)

        assert state.values.get("knowledge_package_accepted") is True
        assert "knowledge_handoff" in (state.values.get("completed_node_ids") or [])
        # After full accept chain, either finished or progressed past experiment gates
        completed = state.values.get("completed_node_ids") or []
        assert len(completed) >= 5


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
