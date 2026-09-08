from dataclasses import replace
import json

import pytest

from core.research.workflow.ledger import OutboxRecord
from core.web.services.team_workflow.research_runtime.completion_dependency import (
    COMPLETION_PENDING, CompletionDependencyPending, bind_completion_resume,
    defer_completion, wake_receipt_completion,
)
from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import AgentActionAdapter
from core.web.services.team_workflow.research_runtime.budget_authority_adapter import (
    compensate_terminal_attempt_reservation_in_uow,
)
from core.web.services.team_workflow.research_runtime.challenge_turn_policy import challenge_task_deadline_scope
from core.web.services.team_workflow.research_runtime.domain_ports import AgentTaskHandle
from tests._support.adapter_fakes import FakeDomainPorts
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS
from tests.test_research_workflow_agent_anchor import _agent_action, _seed, _leased_outbox, _outbox_row


def _error(action):
    handle = AgentTaskHandle("session-1", 1, "task-1", "turn-1")
    error = CompletionDependencyPending("receipt pending", snapshot={"terminal": True, "terminalStatus": "completed"}, handle=handle)
    bind_completion_resume(error, action, handle, {"reservationId": "res-1"})
    return error


def _delivery(action, status):
    receipt = {"runId": action.run_id, "nodeRunId": action.node_run_id, "scope": {
        "formalNodeRunId": action.node_run_id, "sessionId": "session-1", "turnId": "turn-1", "taskId": "task-1",
    }}
    return OutboxRecord(
        action_id="receipt-delivery", run_id=action.run_id, command_id=None, node_run_id=None,
        action_kind="reconcile", idempotency_key="challenge_receipt:test",
        payload_json=json.dumps({"kind": "challenge_model_invocation_receipt_persist", "receipt": receipt}),
        status=status, attempt_count=0, available_at_ms=FIXED_NOW_MS, lease_owner=None,
        lease_expires_at_ms=None, last_problem_json=None, created_at_ms=FIXED_NOW_MS, updated_at_ms=FIXED_NOW_MS,
    ), receipt


def _budget_receipt_row(h, action):
    return h.store.submit(
        lambda u: u.repository.execute(
            "SELECT status, settled_json FROM budget_receipts WHERE reservation_id = ?",
            (f"reservation-{action.node_run_id}",),
        ).fetchone(),
        force_flush=True,
    ).result(timeout=10)


def _seed_reserved_receipt(h, action, *, settled_payload):
    """Live reservation-{node_run_id} receipt, mirroring reserve_budget_authority's columns."""

    def mutate(uow):
        uow.repository.insert_budget_receipt(
            receipt_id="budget-receipt-1",
            run_id=action.run_id,
            node_run_id=action.node_run_id,
            reservation_id=f"reservation-{action.node_run_id}",
            stage_id="knowledge_collection",
            policy_hash=action.budget_policy_hash or "",
            reserved_json=json.dumps(
                {
                    "reserved": {"estimatedTokens": 1_480_468, "tokens": 1_480_468},
                    "limits": {"tokens": 2_000_000},
                }
            ),
            created_at_ms=FIXED_NOW_MS,
        )
        uow.repository.update_budget_receipt(
            "budget-receipt-1",
            status="reserved",
            now_ms=FIXED_NOW_MS,
            settled_json=json.dumps(settled_payload, ensure_ascii=False),
        )

    h.store.submit(mutate, force_flush=True).result(timeout=10)


@pytest.mark.parametrize("delivery_status", ["pending", "leased", "succeeded"])
def test_delayed_receipt_requeues_original_completion_without_failure(tmp_path, delivery_status):
    h = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        h.seed_run(status="running")
        action = _agent_action()
        _seed(h, action, action.node_id)
        row, _ = _delivery(action, delivery_status)
        h.store.submit(lambda u: u.repository.insert_outbox(row), force_flush=True).result()
        outbox = _leased_outbox(h, action, attempt_count=99)
        defer_completion(h.store, outbox=outbox, action=action, error=_error(action), owner="adapter-worker", now_ms=FIXED_NOW_MS + 1)
        result = _outbox_row(h, outbox.action_id)
        assert result.status == "pending"
        assert result.attempt_count == 0
        problem = json.loads(result.last_problem_json)
        assert problem["executionStatus"] == "completed"
        assert problem["code"] == COMPLETION_PENDING
        assert h.store.get_run(action.run_id).status == "running"
    finally:
        h.close()


@pytest.mark.parametrize("change", [None, "other_turn", "cancelled", "new_attempt"])
def test_delivery_recovers_only_its_live_original_completion(tmp_path, change):
    h = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        h.seed_run(status="running")
        action = _agent_action()
        _seed(h, action, action.node_id)
        h.store.submit(lambda u: u.repository.update_attempt_status(action.node_run_id, "running", FIXED_NOW_MS), force_flush=True).result()
        outbox = _leased_outbox(h, action, attempt_count=9)
        defer_completion(h.store, outbox=outbox, action=action, error=_error(action), owner="adapter-worker", now_ms=FIXED_NOW_MS + 1)
        assert _outbox_row(h, outbox.action_id).status == "failed"
        assert h.store.get_run(action.run_id).status == "blocked"
        _, receipt = _delivery(action, "succeeded")
        if change == "other_turn":
            receipt["scope"]["turnId"] = "other"
        elif change == "cancelled":
            h.store.submit(lambda u: u.repository.update_run_status(action.run_id, u.repository.get_run(action.run_id).team_id, "cancelled", FIXED_NOW_MS + 2), force_flush=True).result()
        elif change == "new_attempt":
            from tests._support.workflow_ledger_helpers import build_attempt_record
            h.store.submit(lambda u: u.repository.insert_attempt(build_attempt_record(
                node_run_id="new-attempt", run_id=action.run_id, node_id=action.node_id, attempt=2,
                status="dispatching", command_id="cmd-driver")), force_flush=True).result()
        h.store.submit(lambda u: wake_receipt_completion(u, receipt=receipt, now_ms=FIXED_NOW_MS + 3), force_flush=True).result()
        assert _outbox_row(h, outbox.action_id).status == ("pending" if change is None else "failed")
        if change is None:
            assert h.store.get_run(action.run_id).status == "running"
            assert h.store.latest_attempt(action.run_id, action.node_id).attempt == 1
    finally:
        h.close()


def test_completion_resume_does_not_reserve_or_create_task(monkeypatch):
    action = _agent_action()
    ports = FakeDomainPorts()
    expected = AgentTaskHandle("session-1", 1, "task-1", "turn-1")
    observed = []
    def complete(*, action, handle):
        observed.append(handle)
        return []
    monkeypatch.setattr(ports, "execute_agent_turn", complete)
    error = _error(action)
    with challenge_task_deadline_scope(1, resume_problem={"code": COMPLETION_PENDING, "completionResume": error.resume}):
        result = AgentActionAdapter(ports).execute(action)
    assert observed == [expected]
    assert result.outcome == "succeeded"
    assert "reserve_budget" not in ports.calls
    assert "create_agent_task" not in ports.calls


def test_completion_cursor_cannot_cross_attempts():
    action = _agent_action()
    with challenge_task_deadline_scope(1, resume_problem={"code": COMPLETION_PENDING, "completionResume": _error(action).resume}):
        with pytest.raises(ValueError, match="original action"):
            AgentActionAdapter(FakeDomainPorts()).execute(replace(action, node_run_id="other"))


def test_receipt_resume_finishes_original_node_through_worker(tmp_path, monkeypatch):
    from core.web.services.team_workflow.research_runtime.action_registry import ActionRegistry
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import AdapterDispatchWorker
    from core.web.services.team_workflow.research_runtime.real_domain_ports import publish_agent_task_started_anchor
    h = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        h.seed_run(status="running")
        action = _agent_action()
        _seed(h, action, action.node_id)
        ports = FakeDomainPorts()
        original_execute = ports.execute_agent_turn
        delivered = False
        observed = []
        def complete(*, action, handle):
            observed.append(handle)
            if not delivered:
                publish_agent_task_started_anchor(h.store, action=action, binding=ports.resolve_binding(action), handle=handle)
                raise CompletionDependencyPending("receipt pending", snapshot={"terminal": True, "terminalStatus": "completed"})
            return original_execute(action=action, handle=handle)
        monkeypatch.setattr(ports, "execute_agent_turn", complete)
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        worker = AdapterDispatchWorker(store=h.store, registry=registry, ports=ports,
            successor_fn=lambda node: ("source_extraction",), now_provider=lambda: FIXED_NOW_MS + 1000)
        worker.run_once()
        assert h.store.get_run(action.run_id).status == "blocked"
        assert h.store.latest_attempt(action.run_id, action.node_id).status == "running"
        handle = observed[0]
        _, receipt = _delivery(action, "succeeded")
        receipt["scope"].update(sessionId=handle.session_id, turnId=handle.turn_id, taskId=handle.task_id)
        delivered = True
        h.store.submit(lambda u: wake_receipt_completion(u, receipt=receipt, now_ms=FIXED_NOW_MS + 1000), force_flush=True).result()
        worker.run_once()
        attempt = h.store.latest_attempt(action.run_id, action.node_id)
        assert attempt.status == "succeeded"
        assert attempt.attempt == 1
        assert observed == [handle, handle]
        assert ports.calls.count("reserve_budget") == 1
        assert ports.calls.count("create_agent_task") == 1
        assert ports.calls.count("settle_budget") == 1
        assert "read_back_artifact" in ports.calls
        assert _outbox_row(h, "adapter-outbox-" + action.action_id).status == "succeeded"
    finally:
        h.close()


def test_workflow_failure_does_not_overwrite_session_execution_projection():
    from types import SimpleNamespace
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import AdapterDispatchWorker
    payload = {"rootSession": {"sessionId": "root", "status": "completed"},
               "scopedSessions": [{"sessionId": "child", "status": "running"}]}
    stored = []
    row = [None] * 13 + [json.dumps(payload)]
    repository = SimpleNamespace(get_anchor_by_node_run=lambda node: row,
        update_anchor_by_node_run=lambda **values: stored.append(values))
    AdapterDispatchWorker._close_execution_anchor(SimpleNamespace(repository=repository),
        action=_agent_action(), status="failed", problem={"code": "artifact_verification_failed"})
    updated = json.loads(stored[0]["anchor_json"])
    assert stored[0]["status"] == "failed"
    assert updated["closure"]["status"] == "failed"
    assert updated["rootSession"] == payload["rootSession"]
    assert updated["scopedSessions"] == payload["scopedSessions"]


def test_delivery_during_leased_resume_gets_one_new_registry_read(tmp_path):
    from core.research.workflow.ledger.outbox import lease_ready_actions
    h = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        h.seed_run(status="running")
        action = _agent_action()
        _seed(h, action, action.node_id)
        row, _ = _delivery(action, "pending")
        h.store.submit(lambda u: u.repository.insert_outbox(row), force_flush=True).result()
        original = _leased_outbox(h, action, attempt_count=1)
        defer_completion(h.store, outbox=original, action=action, error=_error(action), owner="adapter-worker", now_ms=FIXED_NOW_MS)
        # Delivery wins after a resumed completion has read Registry, while
        # wake cannot touch its leased adapter row.
        h.store.submit(lambda u: u.repository.execute(
            "UPDATE outbox_actions SET status='succeeded', updated_at_ms=? WHERE action_id='receipt-delivery'",
            (FIXED_NOW_MS + 5000,)), force_flush=True).result()
        resumed = lease_ready_actions(h.store, owner="adapter-worker", now_ms=FIXED_NOW_MS + 5000, limit=1)[0]
        defer_completion(h.store, outbox=resumed, action=action, error=_error(action), owner="adapter-worker", now_ms=FIXED_NOW_MS + 5000)
        assert _outbox_row(h, original.action_id).status == "pending"
        # The same acknowledged delivery cannot produce an unbounded reread.
        resumed = lease_ready_actions(h.store, owner="adapter-worker", now_ms=FIXED_NOW_MS + 10000, limit=1)[0]
        defer_completion(h.store, outbox=resumed, action=action, error=_error(action), owner="adapter-worker", now_ms=FIXED_NOW_MS + 10000)
        assert _outbox_row(h, original.action_id).status == "failed"
    finally:
        h.close()


def test_unavailable_dependency_settles_reservation_with_observed_usage(tmp_path):
    """Terminal unavailable completion must settle at observed usage, not strand 'reserved'.

    Production incident: the turn's 1,066,138-token call really happened but its
    receipt readback was missing, so the attempt's 1,480,468 reservation stayed
    'reserved' and, added to a1's settled 519,532, permanently filled the
    2,000,000 stage limit (every later start_node rejected with
    budget_safety_limit_reached)."""
    h = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        h.seed_run(status="running")
        action = _agent_action()
        _seed(h, action, action.node_id)
        _seed_reserved_receipt(
            h,
            action,
            settled_payload={
                "usage": {"tokens": 1_066_138},
                "invocations": {"i1": {"tokens": 1_066_138}},
            },
        )
        outbox = _leased_outbox(h, action, attempt_count=9)
        defer_completion(h.store, outbox=outbox, action=action, error=_error(action), owner="adapter-worker", now_ms=FIXED_NOW_MS + 1)
        assert _outbox_row(h, outbox.action_id).status == "failed"
        status, settled_json = _budget_receipt_row(h, action)
        assert status == "settled"
        # The settle merge must keep the observed usage, not reset it.
        assert json.loads(settled_json)["usage"]["tokens"] == 1_066_138
    finally:
        h.close()


def test_unavailable_dependency_voids_unused_reservation(tmp_path):
    h = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        h.seed_run(status="running")
        action = _agent_action()
        _seed(h, action, action.node_id)
        _seed_reserved_receipt(h, action, settled_payload={})
        outbox = _leased_outbox(h, action, attempt_count=9)
        defer_completion(h.store, outbox=outbox, action=action, error=_error(action), owner="adapter-worker", now_ms=FIXED_NOW_MS + 1)
        assert _outbox_row(h, outbox.action_id).status == "failed"
        status, _ = _budget_receipt_row(h, action)
        assert status == "voided"
        # A terminal receipt makes compensation an idempotent no-op that
        # returns the receipt's own status.
        rerun = h.store.submit(
            lambda u: compensate_terminal_attempt_reservation_in_uow(
                u,
                run_id=action.run_id,
                node_run_id=action.node_run_id,
                reason="completion_dependency_unavailable_compensation",
                correlation_id=action.action_id,
                now_ms=FIXED_NOW_MS + 2,
            ),
            force_flush=True,
        ).result(timeout=10)
        assert rerun == "voided"
    finally:
        h.close()
