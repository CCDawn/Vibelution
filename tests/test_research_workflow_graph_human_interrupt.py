"""T4 RED: human interrupt — human nodes interrupt with human_task actions
and resume only through typed human decision receipts."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.challenge_cup_runtime import (
    ChallengeCupGraphCoordinator,
    GraphDispatch,
)
from core.research.workflow.contracts import ExecutionReceipt
from tests._support.graph_helpers import GraphHarness, NODE_ORDER


def test_human_node_interrupts_with_human_task_action(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        # 走到 knowledge_handoff（第 5 个节点，human）。
        harness.enqueue_graph_dispatch("run-test", "problem_understanding", 1)
        last_action: str | None = None
        for _ in range(30):
            harness.worker.run_once()
            pending = harness.latest_adapter_pending()
            if pending is None:
                break
            import json

            payload = json.loads(pending.payload_json)
            if payload["actionId"] == last_action:
                break
            last_action = payload["actionId"]
            if payload["nodeId"] == "knowledge_handoff":
                break
            harness.resume(
                run_id="run-test",
                node_id=payload["nodeId"],
                attempt=int(payload["attempt"]),
                action_id=payload["actionId"],
            )
            harness.consume_adapter(pending.action_id)
        # 最后一个 pending 是 knowledge_handoff。
        pending = harness.latest_adapter_pending()
        assert pending is not None
        import json

        payload = json.loads(pending.payload_json)
        assert payload["nodeId"] == "knowledge_handoff"
        assert payload["actorKind"] == "human"
        assert payload["actionKind"] == "human_task:knowledge_handoff"
    finally:
        harness.close()


def test_human_accept_resume_proceeds_to_next_node(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "problem_understanding", 1)
        last_action: str | None = None
        for _ in range(40):
            harness.worker.run_once()
            pending = harness.latest_adapter_pending()
            if pending is None:
                break
            import json

            payload = json.loads(pending.payload_json)
            if payload["actionId"] == last_action:
                break
            last_action = payload["actionId"]
            harness.resume(
                run_id="run-test",
                node_id=payload["nodeId"],
                attempt=int(payload["attempt"]),
                action_id=payload["actionId"],
            )
            harness.consume_adapter(pending.action_id)
        attempts = harness.commands.store.list_attempts("run-test")
        attempt_nodes = {attempt.node_id for attempt in attempts}
        assert "knowledge_handoff" in attempt_nodes
        # 人工接受后进入 hypothesis_design。
        assert "hypothesis_design" in attempt_nodes
    finally:
        harness.close()


def test_human_reject_marker_stops_advance(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "problem_understanding", 1)
        last_action: str | None = None
        for _ in range(30):
            harness.worker.run_once()
            pending = harness.latest_adapter_pending()
            if pending is None:
                break
            import json

            payload = json.loads(pending.payload_json)
            if payload["actionId"] == last_action:
                break
            last_action = payload["actionId"]
            if payload["nodeId"] == "knowledge_handoff":
                break
            harness.resume(
                run_id="run-test",
                node_id=payload["nodeId"],
                attempt=int(payload["attempt"]),
                action_id=payload["actionId"],
            )
            harness.consume_adapter(pending.action_id)

        pending = harness.latest_adapter_pending()
        assert pending is not None
        import json

        payload = json.loads(pending.payload_json)
        assert payload["nodeId"] == "knowledge_handoff"

        # 人工拒绝：failed receipt 不推进到 hypothesis_design。
        harness.resume(
            run_id="run-test",
            node_id="knowledge_handoff",
            attempt=int(payload["attempt"]),
            action_id=payload["actionId"],
            outcome="failed",
        )
        harness.worker.run_once()
        harness.consume_adapter(pending.action_id)
        # 拒绝后没有新的 adapter pending（图不再前进）。
        harness.worker.run_once()
        next_pending = harness.latest_adapter_pending()
        assert next_pending is None
        attempts = harness.commands.store.list_attempts("run-test")
        handoff_attempt = next(
            attempt for attempt in attempts if attempt.node_id == "knowledge_handoff"
        )
        assert handoff_attempt.status == "failed"
    finally:
        harness.close()
