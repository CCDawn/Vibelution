"""T4 RED: formal runner — interrupt/resume over all 17 nodes, deterministic
actionIds across checkpoint restarts, no side effects before interrupt."""

from __future__ import annotations

from pathlib import Path

from core.research.workflow.challenge_cup_runtime import (
    ChallengeCupGraphCoordinator,
    GraphDispatch,
    action_id_for,
)
from tests._support.graph_helpers import GraphHarness, NODE_ORDER


def test_start_dispatch_interrupts_with_pending_action(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "problem_understanding", 1)
        handled = harness.worker.run_once()
        assert handled == 1
        pending = harness.latest_adapter_pending()
        assert pending is not None
        import json

        payload = json.loads(pending.payload_json)
        assert payload["nodeId"] == "problem_understanding"
        assert payload["actorKind"] == "agent"
        assert payload["actionKind"] == "start_agent_task"
        assert payload["actionId"] == action_id_for("run-test", "problem_understanding", 1)
        assert pending.idempotency_key == f"adapter:{payload['actionId']}"
        attempt = harness.commands.store.latest_attempt("run-test", "problem_understanding")
        assert attempt is not None and attempt.status == "dispatching"
        assert attempt.pending_action_id == payload["actionId"]
    finally:
        harness.close()


def test_checkpoint_restart_yields_same_action_id(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "problem_understanding", 1)
        harness.worker.run_once()
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None

        # 重启 coordinator（新连接、同一 checkpoint 文件）。
        restarted = ChallengeCupGraphCoordinator(harness.tmp_path / "checkpoints.sqlite")
        snapshot = restarted.snapshot("run-test")
        values = snapshot["values"]
        from core.research.workflow.challenge_cup_runtime import build_pending_action

        pending = build_pending_action(values, "problem_understanding")
        import json

        assert pending.action_id == json.loads(first_pending.payload_json)["actionId"]
    finally:
        harness.close()


def test_full_17_node_walk_interrupts_every_node(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "problem_understanding", 1)
        seen: list[str] = []
        last_action: str | None = None
        for _ in range(40):
            handled = harness.worker.run_once()
            pending = harness.latest_adapter_pending()
            if pending is None:
                break
            import json

            payload = json.loads(pending.payload_json)
            if payload["actionId"] == last_action:
                break  # 卡住保护
            last_action = payload["actionId"]
            node_id = payload["nodeId"]
            if node_id not in seen:
                seen.append(node_id)
            branch = None
            if node_id in ("iteration_decision", "version_governance"):
                branch = "promote_candidate"
            harness.resume(
                run_id="run-test",
                node_id=node_id,
                attempt=int(payload["attempt"]),
                action_id=payload["actionId"],
                branch_decision=branch,
            )
            harness.consume_adapter(pending.action_id)
        assert seen == NODE_ORDER
        # 全部节点都有对应 attempt 行。
        attempts = harness.commands.store.list_attempts("run-test")
        assert {attempt.node_id for attempt in attempts} == set(NODE_ORDER)
    finally:
        harness.close()


def test_resume_requires_matching_action_id(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "problem_understanding", 1)
        harness.worker.run_once()
        pending = harness.latest_adapter_pending()
        import json

        payload = json.loads(pending.payload_json)
        harness.resume(
            run_id="run-test",
            node_id="problem_understanding",
            attempt=1,
            action_id="act-wrong-identity",
        )
        harness.worker.run_once()
        # 身份不匹配的 receipt 使节点失败而不是前进。
        attempts = harness.commands.store.list_attempts("run-test")
        assert {attempt.node_id for attempt in attempts} == {"problem_understanding"}
    finally:
        harness.close()


def test_node_fn_has_no_side_effect_before_interrupt(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        dispatch = GraphDispatch(
            action_id="act-driver",
            run_id="run-test",
            node_run_id="nr-run-test-problem_understanding-a1",
            node_id="problem_understanding",
            attempt=1,
            dispatch_kind="start",
            input_snapshot_hash="a" * 64,
            workflow_version_id="challenge-cup-research-v2.1.0",
            team_id="research-team",
        )
        result = harness.coordinator.start_attempt(dispatch)
        # interrupt 之前节点函数只读状态，不产生任何 Ledger 写入。
        assert harness.commands.store.latest_event_sequence("run-test") == 1
        assert harness.commands.store.list_attempts("run-test") == []
        assert result.pending_action is not None
    finally:
        harness.close()
