"""T4 RED: iteration routes — rerun / promote / stop / revise / unknown."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    GraphDecisionError,
)
from tests._support.graph_helpers import GraphHarness, NODE_ORDER


def _walk_to(node_id: str, harness: GraphHarness) -> dict:
    """推进到指定节点中断，返回其 pending payload。"""
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
        if payload["nodeId"] == node_id:
            return payload
        branch = None
        if payload["nodeId"] in ("iteration_decision", "version_governance"):
            branch = "promote_candidate"
        harness.resume(
            run_id="run-test",
            node_id=payload["nodeId"],
            attempt=int(payload["attempt"]),
            action_id=payload["actionId"],
            branch_decision=branch,
        )
        harness.consume_adapter(pending.action_id)
    raise AssertionError(f"未能推进到 {node_id}")


def test_rerun_same_protocol_creates_new_controlled_run_attempt(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        decision = _walk_to("iteration_decision", harness)
        harness.resume(
            run_id="run-test",
            node_id="iteration_decision",
            attempt=int(decision["attempt"]),
            action_id=decision["actionId"],
            branch_decision="rerun_same_protocol",
        )
        harness.consume_adapter(harness.latest_adapter_pending().action_id)
        # rerun 路由回 controlled_run，且以新 attempt 中断。
        for _ in range(3):
            harness.worker.run_once()
            pending = harness.latest_adapter_pending()
            if pending is not None:
                import json

                payload = json.loads(pending.payload_json)
                if payload["nodeId"] == "controlled_run":
                    assert int(payload["attempt"]) == 2
                    return
        raise AssertionError("rerun 未回到 controlled_run 的新 attempt")
    finally:
        harness.close()


def test_promote_candidate_routes_through_governance_to_package(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        decision = _walk_to("iteration_decision", harness)
        harness.resume(
            run_id="run-test",
            node_id="iteration_decision",
            attempt=int(decision["attempt"]),
            action_id=decision["actionId"],
            branch_decision="promote_candidate",
        )
        harness.consume_adapter(harness.latest_adapter_pending().action_id)
        # iteration_decision -> version_governance -> candidate_promotion -> result_package。
        seen: list[str] = []
        last_action: str | None = None
        for _ in range(10):
            harness.worker.run_once()
            pending = harness.latest_adapter_pending()
            if pending is None:
                break
            import json

            payload = json.loads(pending.payload_json)
            if payload["actionId"] == last_action:
                break
            last_action = payload["actionId"]
            seen.append(payload["nodeId"])
            branch = "promote_candidate" if payload["nodeId"] == "version_governance" else None
            harness.resume(
                run_id="run-test",
                node_id=payload["nodeId"],
                attempt=int(payload["attempt"]),
                action_id=payload["actionId"],
                branch_decision=branch,
            )
            harness.consume_adapter(pending.action_id)
        assert seen[:3] == ["version_governance", "candidate_promotion", "result_package"]
    finally:
        harness.close()


def test_stop_routes_to_result_package_without_promotion(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        decision = _walk_to("iteration_decision", harness)
        harness.resume(
            run_id="run-test",
            node_id="iteration_decision",
            attempt=int(decision["attempt"]),
            action_id=decision["actionId"],
            branch_decision="stop",
        )
        harness.consume_adapter(harness.latest_adapter_pending().action_id)
        seen: list[str] = []
        last_action: str | None = None
        for _ in range(10):
            harness.worker.run_once()
            pending = harness.latest_adapter_pending()
            if pending is None:
                break
            import json

            payload = json.loads(pending.payload_json)
            if payload["actionId"] == last_action:
                break
            last_action = payload["actionId"]
            seen.append(payload["nodeId"])
            harness.resume(
                run_id="run-test",
                node_id=payload["nodeId"],
                attempt=int(payload["attempt"]),
                action_id=payload["actionId"],
                branch_decision="stop",
            )
            harness.consume_adapter(pending.action_id)
        assert "candidate_promotion" not in seen
        assert "result_package" in seen
    finally:
        harness.close()


def test_revise_protocol_ends_graph_for_fork(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        decision = _walk_to("iteration_decision", harness)
        harness.resume(
            run_id="run-test",
            node_id="iteration_decision",
            attempt=int(decision["attempt"]),
            action_id=decision["actionId"],
            branch_decision="revise_protocol",
        )
        harness.consume_adapter(harness.latest_adapter_pending().action_id)
        harness.worker.run_once()
        # revise_protocol 结束图：不再有新的 adapter pending。
        assert harness.latest_adapter_pending() is None
        snapshot = harness.coordinator.snapshot("run-test")
        assert snapshot["nextNodeIds"] == []
    finally:
        harness.close()


def test_unknown_decision_blocks_run(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        decision = _walk_to("iteration_decision", harness)
        harness.resume(
            run_id="run-test",
            node_id="iteration_decision",
            attempt=int(decision["attempt"]),
            action_id=decision["actionId"],
            branch_decision="not_a_decision",
        )
        harness.consume_adapter(harness.latest_adapter_pending().action_id)
        harness.worker.run_once()
        # 图不前进：iteration_decision attempt 被标记 blocked。
        attempts = harness.commands.store.list_attempts("run-test")
        decision_attempt = next(
            attempt for attempt in attempts if attempt.node_id == "iteration_decision"
        )
        assert decision_attempt.status == "blocked"
    finally:
        harness.close()
