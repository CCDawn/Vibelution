"""Worker observability events on the runtime-scene stream.

Graph/adapter/delivery workers each leave structured best-effort scene
events at dispatch commit, terminal/blocked/requeue transitions, and
budget settlement, so formal-runtime stalls are diagnosable from the
event stream without replaying the Workflow Ledger.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow import challenge_question_runs
from core.web.services.team_workflow.research_runtime import workflow_artifact_store
from core.web.services.team_workflow.research_runtime.delivery_orchestration import (
    DELIVERY_OUTBOX_KIND,
    PROGRAM_CANDIDATE_HANDOFF_BLOCKED_CODE,
)
from core.web.services.team_workflow.research_runtime.delivery_worker import (
    DeliveryOrchestrationWorker,
)
from core.web.services.team_workflow.research_runtime.real_domain_ports import (
    RealDomainPorts,
)
from tests._support.command_helpers import CommandHarness
from tests._support.graph_helpers import ENTRY_NODE_ID, GraphHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


class _SceneEventRecorder:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.events: list[dict[str, object]] = []
        from core.web.services import runtime_scene_service

        monkeypatch.setattr(
            runtime_scene_service,
            "record_runtime_scene_event_quietly",
            self._capture,
        )

    def _capture(self, component, phase, event_code, **kwargs):
        self.events.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                **{key: value for key, value in kwargs.items()},
            }
        )

    def find(self, event_code: str, *, phase: str | None = None) -> dict[str, object] | None:
        return next(
            (
                event
                for event in self.events
                if event["eventCode"] == event_code
                and (phase is None or event["phase"] == phase)
            ),
            None,
        )


# ---------------------------------------------------------------------------
# Graph worker: committed / blocked / attempt_terminal
# ---------------------------------------------------------------------------


def test_graph_dispatch_commit_leaves_scene_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _SceneEventRecorder(monkeypatch)
    graph = GraphHarness(tmp_path)
    try:
        graph.seed(run_id="run-obs-commit")
        graph.enqueue_graph_dispatch("run-obs-commit", ENTRY_NODE_ID, 1)
        assert graph.worker.run_once() >= 1

        event = recorder.find("graph_dispatch.committed")
        assert event is not None
        assert event["component"] == "team_workflow_orchestration"
        assert event["phase"] == "graph_dispatch_worker"
        assert event["outcome"] == "committed"
        assert event["level"] == "info"
        assert event["fields"]["runId"] == "run-obs-commit"
        assert event["fields"]["nodeId"] == ENTRY_NODE_ID
        assert event["fields"]["dispatchKind"] == "start"
        assert event["fields"]["pendingNodeId"] == ENTRY_NODE_ID
        assert event["fields"]["completed"] is False
    finally:
        graph.close()


def test_graph_dispatch_node_mismatch_leaves_blocked_scene_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _SceneEventRecorder(monkeypatch)
    graph = GraphHarness(tmp_path)
    try:
        graph.seed(run_id="run-obs-blocked")
        # A start dispatch targeting a downstream node on a fresh run
        # interrupts at the entry node and is blocked as a node mismatch.
        graph.enqueue_graph_dispatch("run-obs-blocked", "source_finding", 1)
        assert graph.worker.run_once() >= 1

        event = recorder.find("graph_dispatch.blocked")
        assert event is not None
        assert event["outcome"] == "blocked"
        assert event["level"] == "warning"
        assert event["fields"]["runId"] == "run-obs-blocked"
        assert event["fields"]["nodeId"] == "source_finding"
        assert event["fields"]["problemCode"]
    finally:
        graph.close()


def test_graph_dispatch_failed_receipt_leaves_terminal_scene_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _SceneEventRecorder(monkeypatch)
    graph = GraphHarness(tmp_path)
    try:
        run_id = "run-obs-terminal"
        graph.seed(run_id=run_id)
        graph.enqueue_graph_dispatch(run_id, ENTRY_NODE_ID, 1)
        assert graph.worker.run_once() >= 1
        pending = graph.latest_adapter_pending(run_id)
        assert pending is not None
        payload = json.loads(pending.payload_json)

        graph.resume(
            run_id=run_id,
            node_id=str(payload["nodeId"]),
            attempt=int(payload["attempt"]),
            action_id=str(payload["actionId"]),
            outcome="failed",
        )
        assert graph.worker.run_once() >= 1

        event = recorder.find("graph_dispatch.attempt_terminal")
        assert event is not None
        assert event["outcome"] == "failed"
        assert event["fields"]["runId"] == run_id
        assert event["fields"]["receiptOutcome"] == "failed"
        assert event["fields"]["dispatchKind"] == "resume_action"
    finally:
        graph.close()


# ---------------------------------------------------------------------------
# Adapter worker: attempt_failed / attempt_blocked / requeued / budget events
# ---------------------------------------------------------------------------


def _adapter_action(node_id: str = "source_finding") -> PendingAction:
    return PendingAction(
        action_id="act-obs",
        run_id="run-test",
        node_run_id=f"nr-run-test-{node_id}-a1",
        node_id=node_id,
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="p-1",
    )


def _seed_adapter_outbox(harness: CommandHarness, action: PendingAction) -> None:
    from core.research.workflow.ledger import OutboxRecord
    from tests._support.workflow_ledger_helpers import (
        build_attempt_record,
        build_command_record,
    )

    def mutate(uow):
        if uow.repository.get_command("cmd-obs") is None:
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-obs",
                    run_id=action.run_id,
                    idempotency_key="cmd-obs",
                )
            )
        if uow.repository.get_attempt(action.node_run_id) is None:
            uow.repository.insert_attempt(
                build_attempt_record(
                    action.node_run_id,
                    run_id=action.run_id,
                    node_id=action.node_id,
                    attempt=1,
                    status="dispatching",
                    command_id="cmd-obs",
                    started_at_ms=FIXED_NOW_MS,
                )
            )
        uow.repository.insert_outbox(
            OutboxRecord(
                action_id=f"adapter-outbox-{action.action_id}",
                run_id=action.run_id,
                command_id="cmd-obs",
                node_run_id=action.node_run_id,
                action_kind="adapter_dispatch",
                idempotency_key=f"adapter:{action.action_id}",
                payload_json=json.dumps(action.to_dict()),
                status="pending",
                attempt_count=0,
                available_at_ms=FIXED_NOW_MS,
                lease_owner=None,
                lease_expires_at_ms=None,
                last_problem_json=None,
                created_at_ms=FIXED_NOW_MS,
                updated_at_ms=FIXED_NOW_MS,
            )
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _adapter_worker(harness: CommandHarness, adapter, ports) -> object:
    from core.web.services.team_workflow.research_runtime.action_registry import (
        ActionRegistry,
    )
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        AdapterDispatchWorker,
    )

    registry = ActionRegistry()
    registry.register(adapter)
    return AdapterDispatchWorker(
        store=harness.store,
        registry=registry,
        ports=ports,
        successor_fn=lambda _node: (),
    )


def test_adapter_failed_outcome_leaves_scene_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.action_registry import (
        AdapterPreflight,
        AdapterResult,
    )

    recorder = _SceneEventRecorder(monkeypatch)
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _adapter_action()
        _seed_adapter_outbox(harness, action)

        class _FailReturnAdapter:
            action_kind = "start_agent_task"

            def preflight(self, action: PendingAction) -> AdapterPreflight:
                return AdapterPreflight(ready=True)

            def execute(self, action: PendingAction) -> AdapterResult:
                return AdapterResult(
                    action_id=action.action_id,
                    outcome="failed",
                    problem={"code": "injected_execute_failed"},
                )

            def verify(self, action, result):  # pragma: no cover - must not run
                raise AssertionError("verify must not run after execute failure")

        worker = _adapter_worker(
            harness, _FailReturnAdapter(), RealDomainPorts(harness.store)
        )
        worker.run_once()

        event = recorder.find("adapter_dispatch.attempt_failed")
        assert event is not None
        assert event["component"] == "team_workflow_orchestration"
        assert event["phase"] == "adapter_dispatch_worker"
        assert event["outcome"] == "failed"
        assert event["level"] == "warning"
        assert event["fields"]["runId"] == action.run_id
        assert event["fields"]["nodeId"] == action.node_id
        assert event["fields"]["problemCode"] == "injected_execute_failed"
    finally:
        harness.close()


def test_adapter_verify_blocked_leaves_scene_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.action_registry import (
        AdapterPreflight,
        AdapterResult,
        VerifiedDomainResult,
    )

    recorder = _SceneEventRecorder(monkeypatch)
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _adapter_action()
        _seed_adapter_outbox(harness, action)
        ports = RealDomainPorts(harness.store)

        class _VerifyBlockedAdapter:
            action_kind = "start_agent_task"

            def preflight(self, action: PendingAction) -> AdapterPreflight:
                return AdapterPreflight(ready=True)

            def execute(self, action: PendingAction) -> AdapterResult:
                reservation = ports.reserve_budget(action=action, estimate_tokens=1000)
                return AdapterResult(
                    action_id=action.action_id,
                    outcome="succeeded",
                    reserved=dict(reservation),
                    usage={"tokens": 1},
                )

            def verify(
                self, action: PendingAction, result: AdapterResult
            ) -> VerifiedDomainResult:
                return VerifiedDomainResult(
                    action_id=action.action_id,
                    outcome="blocked",
                    artifact_receipts=(),
                    anchor=None,
                    budget_receipt=None,
                    problem={"code": "injected_verify_blocked", "detail": "no receipt"},
                )

        worker = _adapter_worker(harness, _VerifyBlockedAdapter(), ports)
        worker.run_once()

        event = recorder.find("adapter_dispatch.attempt_blocked")
        assert event is not None
        assert event["outcome"] == "blocked"
        assert event["fields"]["nodeId"] == action.node_id
        assert event["fields"]["problemCode"] == "injected_verify_blocked"
    finally:
        harness.close()


def test_adapter_turn_not_ready_leaves_requeued_scene_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.action_registry import (
        AdapterPreflight,
    )
    from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
        TurnNotReadyError,
    )

    recorder = _SceneEventRecorder(monkeypatch)
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _adapter_action()
        _seed_adapter_outbox(harness, action)

        class _TurnNotReadyAdapter:
            action_kind = "start_agent_task"

            def preflight(self, action: PendingAction) -> AdapterPreflight:
                return AdapterPreflight(ready=True)

            def execute(self, action: PendingAction):
                # Transient turn state: the worker must requeue instead of
                # failing the attempt.
                raise TurnNotReadyError("injected turn still running")

            def verify(self, action, result):  # pragma: no cover - must not run
                raise AssertionError("verify must not run after execute raise")

        worker = _adapter_worker(
            harness, _TurnNotReadyAdapter(), RealDomainPorts(harness.store)
        )
        worker.run_once()

        event = recorder.find("adapter_dispatch.requeued")
        assert event is not None
        assert event["outcome"] == "requeued"
        assert event["fields"]["runId"] == action.run_id
        assert event["fields"]["attemptCount"] >= 1
        assert "turn_not_ready" in str(event["fields"]["detail"])
    finally:
        harness.close()


def test_adapter_commit_success_leaves_scene_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.action_registry import (
        AdapterPreflight,
        AdapterResult,
        VerifiedDomainResult,
    )

    recorder = _SceneEventRecorder(monkeypatch)
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _adapter_action()
        _seed_adapter_outbox(harness, action)
        ports = RealDomainPorts(harness.store)

        class _SucceedAdapter:
            action_kind = "start_agent_task"

            def preflight(self, action: PendingAction) -> AdapterPreflight:
                return AdapterPreflight(ready=True)

            def execute(self, action: PendingAction) -> AdapterResult:
                reservation = ports.reserve_budget(action=action, estimate_tokens=1000)
                return AdapterResult(
                    action_id=action.action_id,
                    outcome="succeeded",
                    reserved=dict(reservation),
                    usage={"tokens": 1},
                )

            def verify(
                self, action: PendingAction, result: AdapterResult
            ) -> VerifiedDomainResult:
                return VerifiedDomainResult(
                    action_id=action.action_id,
                    outcome="succeeded",
                    artifact_receipts=(),
                    anchor=None,
                    budget_receipt=dict(result.reserved or {}),
                    problem=None,
                )

        worker = _adapter_worker(harness, _SucceedAdapter(), ports)
        worker.run_once()

        committed = recorder.find("adapter_dispatch.committed")
        assert committed is not None
        assert committed["component"] == "team_workflow_orchestration"
        assert committed["phase"] == "adapter_dispatch_worker"
        assert committed["outcome"] == "committed"
        assert committed["level"] == "info"
        assert committed["fields"]["runId"] == action.run_id
        assert committed["fields"]["nodeId"] == action.node_id
        assert committed["fields"]["actionKind"] == "start_agent_task"
        assert committed["fields"]["actorKind"] == "agent"
        assert committed["fields"]["budgetSettled"] is True

        settled = recorder.find("adapter_dispatch.budget_settled")
        assert settled is not None
        assert settled["outcome"] == "settled"
        assert settled["level"] == "info"
        assert settled["fields"]["reservationId"]
    finally:
        harness.close()


def test_adapter_budget_settle_failure_leaves_reconciliation_scene_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.action_registry import (
        ActionRegistry,
    )
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        AdapterDispatchWorker,
    )

    recorder = _SceneEventRecorder(monkeypatch)

    class _FailingSettlePorts(RealDomainPorts):
        def settle_budget(self, *, reservation, usage):  # type: ignore[no-untyped-def]
            raise RuntimeError("injected settle failure")

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(status="running")
        action = _adapter_action()
        _seed_adapter_outbox(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation = ports.reserve_budget(action=action, estimate_tokens=1000)

        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=ActionRegistry(),
            ports=_FailingSettlePorts(harness.store),
            successor_fn=lambda _node: (),
        )
        outbox = type("Outbox", (), {"action_id": "outbox-obs-settle"})()
        worker._settle_domain_budget(
            outbox, action, reservation, {"tokens": 10}
        )
        reconciled = recorder.find("adapter_dispatch.budget_settle_reconciliation")
        assert reconciled is not None
        assert reconciled["outcome"] == "reconciliation_required"
        assert reconciled["fields"]["errorType"] == "BudgetSettleFailed"
        assert reconciled["fields"]["reservationId"]
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# Delivery worker: terminal / requeued / invalid_action
# ---------------------------------------------------------------------------


@pytest.fixture()
def delivery_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        challenge_question_runs,
        "challenge_question_run_summary",
        lambda team_id: {
            "completedQuestionIds": ["SCI-001"],
            "approvedDeepExperimentQuestionIds": [],
        },
    )
    graph = GraphHarness(tmp_path)
    worker = DeliveryOrchestrationWorker(
        store=graph.commands.store,
        owner_id="delivery-worker-obs-test",
        now_provider=lambda: FIXED_NOW_MS + 5000,
    )
    try:
        yield graph, worker
    finally:
        graph.close()


def _close_run(graph: GraphHarness, run_id: str) -> None:
    graph.seed(run_id=run_id, status="running")
    _seed_succeeded(graph, run_id)
    assert graph.worker.run_once() >= 1
    run = graph.commands.store.get_run(run_id)
    assert run is not None and run.status == "succeeded"


def _seed_succeeded(graph: GraphHarness, run_id: str) -> None:
    from tests._support.workflow_ledger_helpers import (
        build_attempt_record,
        build_command_record,
    )

    def mutate(uow):
        uow.repository.execute(
            "UPDATE workflow_runs SET active_node_id = ? WHERE run_id = ?",
            ("result_package", run_id),
        )
        uow.repository.insert_command(
            build_command_record(
                command_id=f"cmd-{run_id}",
                run_id=run_id,
                node_id="result_package",
                command_kind="retry_node",
                idempotency_key=f"retry:result_package:{run_id}",
            )
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=f"nr-{run_id}-result_package-a2",
                run_id=run_id,
                node_id="result_package",
                attempt=2,
                actor_kind="system",
                status="succeeded",
                command_id=f"cmd-{run_id}",
                started_at_ms=FIXED_NOW_MS,
            )
        )

    graph.commands.store.submit(mutate, force_flush=True).result(timeout=10)


def test_delivery_terminal_leaves_scene_event(
    delivery_harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _SceneEventRecorder(monkeypatch)
    graph, worker = delivery_harness
    run_id = "run-obs-delivery"
    _close_run(graph, run_id)

    assert worker.run_once() == 1

    event = recorder.find("delivery.terminal")
    assert event is not None
    assert event["component"] == "team_workflow_orchestration"
    assert event["phase"] == "delivery_worker"
    assert event["outcome"] == "blocked"
    assert event["fields"]["runId"] == run_id
    assert event["fields"]["deliveryStatus"] == "blocked"
    assert event["fields"]["code"] == PROGRAM_CANDIDATE_HANDOFF_BLOCKED_CODE


def test_delivery_transient_failure_leaves_requeued_scene_event(
    delivery_harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _SceneEventRecorder(monkeypatch)
    graph, worker = delivery_harness
    run_id = "run-obs-delivery-requeue"
    _close_run(graph, run_id)

    from core.web.services.team_workflow.research_runtime import delivery_worker as dw

    def _boom(*_args, **_kwargs):
        raise RuntimeError("injected delivery boom")

    monkeypatch.setattr(dw, "run_delivery_orchestration", _boom)
    assert worker.run_once() == 1

    event = recorder.find("delivery.requeued")
    assert event is not None
    assert event["outcome"] == "requeued"
    assert event["fields"]["runId"] == run_id
    assert event["fields"]["attemptCount"] >= 1
    assert "injected delivery boom" in str(event["fields"]["detail"])


def test_delivery_action_without_run_id_leaves_invalid_scene_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _SceneEventRecorder(monkeypatch)
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        from core.research.workflow.ledger import OutboxRecord
        from tests._support.workflow_ledger_helpers import (
            build_attempt_record,
            build_command_record,
        )

        def mutate(uow):
            if uow.repository.get_command("cmd-obs-delivery") is None:
                uow.repository.insert_command(
                    build_command_record(
                        command_id="cmd-obs-delivery",
                        run_id="run-test",
                        idempotency_key="cmd-obs-delivery",
                    )
                )
            if uow.repository.get_attempt("nr-run-test-result_package-a2") is None:
                uow.repository.insert_attempt(
                    build_attempt_record(
                        "nr-run-test-result_package-a2",
                        run_id="run-test",
                        node_id="result_package",
                        attempt=2,
                        status="succeeded",
                        command_id="cmd-obs-delivery",
                        started_at_ms=FIXED_NOW_MS,
                    )
                )
            uow.repository.insert_outbox(
                OutboxRecord(
                    action_id="delivery-outbox-obs-invalid",
                    run_id="run-test",
                    command_id="cmd-obs-delivery",
                    node_run_id="nr-run-test-result_package-a2",
                    action_kind=DELIVERY_OUTBOX_KIND,
                    idempotency_key="delivery:obs-invalid",
                    payload_json=json.dumps({}),
                    status="pending",
                    attempt_count=0,
                    available_at_ms=FIXED_NOW_MS,
                    lease_owner=None,
                    lease_expires_at_ms=None,
                    last_problem_json=None,
                    created_at_ms=FIXED_NOW_MS,
                    updated_at_ms=FIXED_NOW_MS,
                )
            )

        harness.store.submit(mutate, force_flush=True).result(timeout=10)
        worker = DeliveryOrchestrationWorker(
            store=harness.store,
            owner_id="delivery-worker-obs-test",
            now_provider=lambda: FIXED_NOW_MS + 5000,
        )
        assert worker.run_once() == 1

        event = recorder.find("delivery.invalid_action")
        assert event is not None
        assert event["outcome"] == "failed"
        assert event["fields"]["code"] == "invalid_delivery_action"
        assert event["fields"]["actionId"] == "delivery-outbox-obs-invalid"
    finally:
        harness.close()


def test_adapter_contract_violation_keeps_dedicated_problem_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N3：turn 终结阶段的 fail-closed 契约违约以专用 problem code 失败，
    不再泛化成 adapter_execution_exception；节点仍 fail-closed。"""
    from core.web.services.team_workflow.research_runtime.action_registry import (
        AdapterPreflight,
    )
    from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
        SourceExtractionContractViolation,
    )

    recorder = _SceneEventRecorder(monkeypatch)
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _adapter_action(node_id="source_extraction")
        _seed_adapter_outbox(harness, action)

        class _ContractViolationAdapter:
            action_kind = "start_agent_task"

            def preflight(self, action: PendingAction) -> AdapterPreflight:
                return AdapterPreflight(ready=True)

            def execute(self, action: PendingAction):
                raise SourceExtractionContractViolation(
                    problem={
                        "code": "source_extraction_contract_violation",
                        "detail": (
                            "candidateExtractions[0] is missing explicit "
                            "retrieved_at; URL, summary and sourceKind are not "
                            "substitutes"
                        ),
                        "actionId": action.action_id,
                    }
                )

            def verify(self, action, result):  # pragma: no cover - must not run
                raise AssertionError("verify must not run after execute exception")

        worker = _adapter_worker(
            harness, _ContractViolationAdapter(), RealDomainPorts(harness.store)
        )
        worker.run_once()

        event = recorder.find("adapter_dispatch.attempt_failed")
        assert event is not None
        assert event["outcome"] == "failed"
        assert event["fields"]["nodeId"] == "source_extraction"
        # 专用 code 直达 problem 记录，不再包一层 adapter_execution_exception。
        assert event["fields"]["problemCode"] == (
            "source_extraction_contract_violation"
        )
    finally:
        harness.close()
