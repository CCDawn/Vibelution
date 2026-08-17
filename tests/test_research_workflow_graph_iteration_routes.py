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


def test_routed_successors_stop_goes_to_version_governance() -> None:
    from core.web.services.team_workflow.research_runtime.iteration_route import (
        routed_successors,
    )

    assert routed_successors("iteration_decision", "stop") == ("version_governance",)
    assert routed_successors("iteration_decision", "rerun_same_protocol") == (
        "controlled_run",
    )
    assert routed_successors("iteration_decision", "") == ()
    assert routed_successors("version_governance", "stop") == ("result_package",)
    assert routed_successors("version_governance", "promote_candidate") == (
        "candidate_promotion",
    )


def test_graph_and_worker_routes_share_iteration_decision_tables() -> None:
    from langgraph.graph import END

    from core.research.workflow.challenge_cup_graph import (
        compiled_iteration_route_map,
        route_after_iteration_decision as definition_route_after_iteration,
        route_after_version_governance as definition_route_after_governance,
    )
    from core.research.workflow.challenge_cup_runtime import (
        route_after_iteration_decision as runtime_route_after_iteration,
        route_after_version_governance as runtime_route_after_governance,
    )
    from core.research.workflow.iteration_decisions import (
        GOVERNANCE_ROUTE_TARGETS,
        ITERATION_ROUTE_TARGETS,
        IterationDecisionKind,
        route_target_after_governance,
        route_target_for_decision,
    )
    from core.web.services.team_workflow.research_runtime.iteration_route import (
        routed_successors,
    )

    assert compiled_iteration_route_map() == {
        kind.value: target for kind, target in ITERATION_ROUTE_TARGETS.items()
    }

    for kind in IterationDecisionKind:
        target = route_target_for_decision(kind)
        runtime = runtime_route_after_iteration({"branch_decision": kind.value})
        definition = definition_route_after_iteration(
            {"iteration_decision": {"decisionKind": kind.value}}
        )
        worker = routed_successors("iteration_decision", kind.value)
        if target is None:
            assert runtime == END
            assert definition == END
            assert worker == ()
        else:
            assert runtime == target
            assert definition == target
            assert worker == (target,)

        if kind in GOVERNANCE_ROUTE_TARGETS:
            governed = route_target_after_governance(kind)
            assert runtime_route_after_governance({"branch_decision": kind.value}) == governed
            assert (
                definition_route_after_governance(
                    {"iteration_decision": {"decisionKind": kind.value}}
                )
                == governed
            )
            assert routed_successors("version_governance", kind.value) == (governed,)
        else:
            assert routed_successors("version_governance", kind.value) == ()


def test_branch_decision_from_run_heals_compact_authority_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import json
    from types import SimpleNamespace

    from core.web.services.team_workflow.research_runtime import workflow_artifact_store
    from core.web.services.team_workflow.research_runtime.iteration_route import (
        branch_decision_from_run,
    )
    from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
        put_workflow_artifact,
    )

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    put_workflow_artifact(
        "research-team",
        kind="iteration_decision",
        workflow_run_id="run-317ed54cb838",
        source_collection_run_id="run-317ed54cb838",
        payload={
            "decisionKind": "stop",
            "terminalReason": "formal_runner_unavailable",
        },
    )
    run = SimpleNamespace(
        team_id="research-team",
        run_id="run-317ed54cb838",
        input_snapshot_json=json.dumps(
            {
                "teamId": "research-team",
                "sourceCollectionRunId": "sc-compact-drift",
            }
        ),
    )
    assert branch_decision_from_run(run) == "stop"


def test_stop_artifact_routes_when_graph_state_lacks_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import json

    from core.web.services.team_workflow.research_runtime import workflow_artifact_store
    from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
        put_workflow_artifact,
    )

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        decision = _walk_to("iteration_decision", harness)
        put_workflow_artifact(
            "research-team",
            kind="iteration_decision",
            workflow_run_id="run-test",
            source_collection_run_id="run-test",
            payload={
                "decisionKind": "stop",
                "terminalReason": "formal_runner_unavailable",
            },
        )

        def drift_snapshot(uow):
            uow.repository.execute(
                "UPDATE workflow_runs SET input_snapshot_json = ? WHERE run_id = ?",
                (
                    json.dumps(
                        {
                            "teamId": "research-team",
                            "sourceCollectionRunId": "sc-compact-drift",
                        }
                    ),
                    "run-test",
                ),
            )

        harness.commands.store.submit(drift_snapshot, force_flush=True).result(timeout=10)
        harness.resume(
            run_id="run-test",
            node_id="iteration_decision",
            attempt=int(decision["attempt"]),
            action_id=decision["actionId"],
        )
        harness.consume_adapter(harness.latest_adapter_pending().action_id)
        seen: list[str] = []
        last_action: str | None = None
        for _ in range(6):
            harness.worker.run_once()
            pending = harness.latest_adapter_pending()
            if pending is None:
                break
            payload = json.loads(pending.payload_json)
            if payload["actionId"] == last_action:
                break
            last_action = payload["actionId"]
            seen.append(payload["nodeId"])
            if payload["nodeId"] == "version_governance":
                break
            harness.resume(
                run_id="run-test",
                node_id=payload["nodeId"],
                attempt=int(payload["attempt"]),
                action_id=payload["actionId"],
            )
            harness.consume_adapter(pending.action_id)
        assert seen[:1] == ["version_governance"]
    finally:
        harness.close()


def test_graph_error_does_not_rewind_succeeded_iteration_attempt(tmp_path: Path) -> None:
    from tests._support.workflow_ledger_helpers import FIXED_NOW_MS

    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        decision = _walk_to("iteration_decision", harness)
        node_run_id = f"nr-run-test-iteration_decision-a{decision['attempt']}"

        def mark_succeeded(uow):
            uow.repository.update_attempt_status(
                node_run_id,
                "succeeded",
                FIXED_NOW_MS,
                finished_at_ms=FIXED_NOW_MS,
            )

        harness.commands.store.submit(mark_succeeded, force_flush=True).result(timeout=10)
        harness.resume(
            run_id="run-test",
            node_id="iteration_decision",
            attempt=int(decision["attempt"]),
            action_id=decision["actionId"],
            branch_decision="not_a_decision",
        )
        adapter = harness.latest_adapter_pending()
        if adapter is not None:
            harness.consume_adapter(adapter.action_id)
        harness.worker.run_once()
        attempts = harness.commands.store.list_attempts("run-test")
        decision_attempt = next(
            attempt for attempt in attempts if attempt.node_id == "iteration_decision"
        )
        assert decision_attempt.status == "succeeded"
        run = harness.commands.store.get_run("run-test")
        assert run is not None
        assert run.status != "blocked"
    finally:
        harness.close()


def test_repair_resumes_succeeded_iteration_interrupt_from_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import json

    from core.web.services.team_workflow.research_runtime import workflow_artifact_store
    from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
        put_workflow_artifact,
    )
    from tests._support.workflow_ledger_helpers import FIXED_NOW_MS

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        decision = _walk_to("iteration_decision", harness)
        node_run_id = f"nr-run-test-iteration_decision-a{decision['attempt']}"

        def mark_succeeded(uow):
            uow.repository.update_attempt_status(
                node_run_id,
                "succeeded",
                FIXED_NOW_MS,
                finished_at_ms=FIXED_NOW_MS,
            )
            uow.repository.execute(
                "UPDATE workflow_runs SET status = 'running' WHERE run_id = ?",
                ("run-test",),
            )

        harness.commands.store.submit(mark_succeeded, force_flush=True).result(timeout=10)
        harness.consume_adapter(harness.latest_adapter_pending().action_id)
        put_workflow_artifact(
            "research-team",
            kind="iteration_decision",
            workflow_run_id="run-test",
            source_collection_run_id="run-test",
            payload={
                "decisionKind": "stop",
                "terminalReason": "formal_runner_unavailable",
            },
        )

        def drift_snapshot(uow):
            uow.repository.execute(
                "UPDATE workflow_runs SET input_snapshot_json = ? WHERE run_id = ?",
                (
                    json.dumps(
                        {
                            "teamId": "research-team",
                            "sourceCollectionRunId": "sc-compact-drift",
                        }
                    ),
                    "run-test",
                ),
            )

        harness.commands.store.submit(drift_snapshot, force_flush=True).result(timeout=10)
        harness.worker.run_once()
        pending = harness.latest_adapter_pending()
        assert pending is not None
        payload = json.loads(pending.payload_json)
        assert payload["nodeId"] == "version_governance"
    finally:
        harness.close()


def _strand_iteration_at_end(harness: GraphHarness, decision: dict) -> None:
    """Consume the iteration_decision interrupt with no branch_decision.

    LangGraph still advances past the interrupt, then the router raises
    ``unknown iteration decision ''`` and leaves next=[] / pendingAction=null.
    """
    from core.research.workflow.challenge_cup_runtime import GraphDispatch
    from core.research.workflow.contracts import ExecutionReceipt
    from tests._support.workflow_ledger_helpers import FIXED_NOW_MS

    receipt = ExecutionReceipt(
        action_id=str(decision["actionId"]),
        node_run_id=f"nr-run-test-iteration_decision-a{decision['attempt']}",
        outcome="succeeded",
        artifact_receipt_ids=(),
        execution_anchor_id=None,
        budget_receipt_id=None,
        problem=None,
        completed_at_ms=FIXED_NOW_MS,
    )
    try:
        harness.coordinator.resume_action(
            GraphDispatch(
                action_id=str(decision["actionId"]),
                run_id="run-test",
                node_run_id=receipt.node_run_id,
                node_id="iteration_decision",
                attempt=int(decision["attempt"]),
                dispatch_kind="resume_action",
                team_id="research-team",
                input_snapshot_hash="a" * 64,
                receipt=receipt,
            )
        )
    except (ValueError, Exception):
        pass


def test_enter_node_after_empty_decision_lands_on_version_governance(
    tmp_path: Path,
) -> None:
    from core.research.workflow.challenge_cup_runtime import GraphDispatch

    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        decision = _walk_to("iteration_decision", harness)
        _strand_iteration_at_end(harness, decision)
        snap = harness.coordinator.snapshot("run-test")
        assert not snap.get("nextNodeIds")
        result = harness.coordinator.enter_node(
            GraphDispatch(
                action_id="act-enter-vg",
                run_id="run-test",
                node_run_id="nr-run-test-version_governance-a1",
                node_id="version_governance",
                attempt=1,
                dispatch_kind="start",
                team_id="research-team",
                input_snapshot_hash="a" * 64,
                state_update={"branch_decision": "stop"},
            )
        )
        assert result.pending_action is not None
        assert result.pending_action.node_id == "version_governance"
        snap2 = harness.coordinator.snapshot("run-test")
        assert (snap2.get("pendingAction") or {}).get("nodeId") == "version_governance"
    finally:
        harness.close()


def test_snapshot_heals_duplicate_run_id_pending_writes(tmp_path: Path) -> None:
    from core.research.workflow.challenge_cup_runtime import GraphDispatch
    from langgraph.types import Command

    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        decision = _walk_to("iteration_decision", harness)
        _strand_iteration_at_end(harness, decision)
        graph, stack = harness.coordinator._compile()
        try:
            graph.invoke(
                Command(
                    goto="version_governance",
                    update={
                        "run_id": "run-test",
                        "active_node_id": "version_governance",
                        "branch_decision": "stop",
                    },
                ),
                harness.coordinator._config("run-test"),
            )
        except Exception:
            pass
        finally:
            stack.close()
        snap = harness.coordinator.snapshot("run-test")
        assert snap.get("checkpointId")
        result = harness.coordinator.enter_node(
            GraphDispatch(
                action_id="act-heal-vg",
                run_id="run-test",
                node_run_id="nr-run-test-version_governance-a1",
                node_id="version_governance",
                attempt=1,
                dispatch_kind="start",
                team_id="research-team",
                input_snapshot_hash="a" * 64,
                state_update={"branch_decision": "stop"},
            )
        )
        assert result.pending_action is not None
        assert result.pending_action.node_id == "version_governance"
        assert harness.coordinator.snapshot("run-test").get("pendingAction")
    finally:
        harness.close()
