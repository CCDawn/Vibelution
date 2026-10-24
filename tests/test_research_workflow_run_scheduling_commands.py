"""Operator scheduling holds preserve execution identity and durable redrive."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from core.research.workflow.contracts import ActorRef, WorkflowCommandKind
from core.research.workflow.ledger import CommandNotAllowedError, RunVersionConflictError
from core.web.services.team_workflow.research_runtime.command_service import CommandForbiddenError
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS, build_outbox_record


def _command(harness, kind, *, version, key=None):
    return harness.request(
        command=WorkflowCommandKind(kind), node_id=None,
        expected_run_version=version, idempotency_key=key or kind,
    )


def _started(harness):
    harness.seed_run()
    return harness.service.submit(harness.request())


def test_pause_resume_replays_receipts_without_new_attempts(tmp_path: Path):
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _started(harness)
        attempts = harness.store.list_attempts("run-test")
        pause = _command(harness, "pause_run", version=2)
        paused = harness.service.submit(pause)
        assert paused.accepted_run_version == 3
        assert harness.store.get_run("run-test").status == "paused"
        assert harness.service.submit(pause).to_dict() == paused.to_dict()
        resume = _command(harness, "resume_run", version=3)
        resumed = harness.service.submit(resume)
        assert resumed.accepted_run_version == 4
        assert harness.service.submit(resume).to_dict() == resumed.to_dict()
        run = harness.store.get_run("run-test")
        assert run.status == "running" and run.blocked_problem_json is None
        assert harness.store.list_attempts("run-test") == attempts
        events = harness.store.list_events("run-test")
        assert [e.event_type for e in events].count("run_paused") == 1
        assert [e.event_type for e in events].count("run_resumed") == 1
        assert [e.sequence for e in events] == list(range(1, len(events) + 1))
        assert paused.latest_event_sequence == 5
        assert resumed.latest_event_sequence == 7
    finally:
        harness.close()


@pytest.mark.parametrize("kind", ["pause_run", "resume_run"])
@pytest.mark.parametrize("roles", [None, (), ("agent",)])
def test_scheduling_control_needs_privileged_server_operator(tmp_path, kind, roles):
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _started(harness)
        request = dataclasses.replace(
            _command(harness, kind, version=2),
            requested_by=ActorRef("agent", "forged-operator"),
        )
        if roles is None:
            with pytest.raises(CommandForbiddenError):
                harness.command_service.submit(request)
        else:
            with server_operator_scope("server-reader", roles=roles):
                with pytest.raises(CommandForbiddenError):
                    harness.command_service.submit(request)
        assert harness.store.get_run("run-test").run_version == 2
    finally:
        harness.close()


@pytest.mark.parametrize("status", ["created", "blocked", "failed", "succeeded", "cancelled", "archived"])
def test_manual_pause_rejects_runs_without_live_scheduling(tmp_path, status):
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(status=status)
        with pytest.raises(CommandNotAllowedError):
            harness.service.submit(_command(harness, "pause_run", version=1))
        assert harness.store.get_run("run-test").run_version == 1
    finally:
        harness.close()


def test_resume_only_redrives_pause_deferred_pending_actions(tmp_path):
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        started = _started(harness)
        harness.service.submit(_command(harness, "pause_run", version=2))
        def seed(uow):
            for action_id, status, problem, kind in (
                ("deferred-graph", "pending", "run_paused", "graph_dispatch"),
                ("deferred-adapter", "pending", "run_paused", "adapter_dispatch"),
                ("backoff", "pending", "transient", "graph_dispatch"),
                ("leased", "leased", "run_paused", "graph_dispatch"),
            ):
                uow.repository.insert_outbox(dataclasses.replace(
                    build_outbox_record(action_id, run_id="run-test", status=status),
                    action_kind=kind, available_at_ms=FIXED_NOW_MS + 90_000,
                    command_id=started.command_id,
                    lease_owner="other-worker" if status == "leased" else None,
                    lease_expires_at_ms=FIXED_NOW_MS + 120_000 if status == "leased" else None,
                    last_problem_json=json.dumps({"code": problem}), attempt_count=2,
                ))
        harness.store.submit(seed, force_flush=True).result(timeout=10)
        before = {key: harness.store.read(lambda repo, key=key: repo.get_outbox(key))
                  for key in ("backoff", "leased")}
        harness.service.submit(_command(harness, "resume_run", version=3))
        for key in ("deferred-graph", "deferred-adapter"):
            row = harness.store.read(lambda repo, key=key: repo.get_outbox(key))
            assert row.available_at_ms == FIXED_NOW_MS + 1000
            assert row.status == "pending" and row.attempt_count == 2
        for key, row in before.items():
            assert harness.store.read(lambda repo, key=key: repo.get_outbox(key)) == row
        assert harness.wake_count == 2  # start + resume; pause is a hold
    finally:
        harness.close()


def test_pause_resume_cas_and_offer_projection(tmp_path):
    from core.web.services.team_workflow.research_runtime.command_offers import build_command_offers
    from core.research.workflow.definition import build_challenge_cup_workflow_definition
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _started(harness)
        def offers():
            return {offer.command.value: offer for offer in build_command_offers(
                readiness_service=harness.readiness, context=harness.context,
                team_id="research-team", run=harness.store.get_run("run-test"),
                definition=build_challenge_cup_workflow_definition(),
                attempts=harness.store.list_attempts("run-test"),
            )}
        assert offers()["pause_run"].available
        assert not offers()["resume_run"].available
        with pytest.raises(RunVersionConflictError):
            harness.service.submit(_command(harness, "pause_run", version=1))
        harness.service.submit(_command(harness, "pause_run", version=2))
        assert offers()["resume_run"].available
        assert not offers()["pause_run"].available
        from core.web.services.team_workflow.research_runtime.query_service import WorkflowQueryService
        query = WorkflowQueryService(store=harness.store,
            readiness_service=harness.readiness, readiness_context=lambda: harness.context)
        detail = query.get_node_detail(team_id="research-team", run_id="run-test",
            node_id="problem_understanding")
        assert {o.command.value for o in detail.command_offers} >= {"pause_run", "resume_run"}
    finally:
        harness.close()


@pytest.mark.parametrize("kind", ["pause_run", "resume_run"])
def test_scheduling_commands_reject_wrong_team_without_writes(tmp_path, kind):
    from core.web.services.team_workflow.research_runtime.command_service import TeamScopeMismatchError
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _started(harness)
        before = harness.store.get_run("run-test")
        request = dataclasses.replace(_command(harness, kind, version=2), team_id="other-team")
        with pytest.raises(TeamScopeMismatchError):
            harness.service.submit(request)
        assert harness.store.get_run("run-test") == before
        assert harness.store.get_command_by_idempotency("run-test", kind) is None
    finally:
        harness.close()


@pytest.mark.parametrize("kind", ["pause_run", "resume_run"])
def test_scheduling_transaction_rolls_back_events_version_and_wake(tmp_path, monkeypatch, kind):
    from core.research.workflow.ledger.repository import WorkflowLedgerRepository
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _started(harness)
        if kind == "resume_run":
            harness.service.submit(_command(harness, "pause_run", version=2))
        before = harness.store.get_run("run-test")
        events = harness.store.list_events("run-test")
        wake_count = harness.wake_count
        insert = WorkflowLedgerRepository.insert_event
        def fail_governance_event(self, record):
            if record.event_type == ("run_paused" if kind == "pause_run" else "run_resumed"):
                raise RuntimeError("test governance event write failed")
            return insert(self, record)
        monkeypatch.setattr(WorkflowLedgerRepository, "insert_event", fail_governance_event)
        with pytest.raises(RuntimeError, match="event write failed"):
            harness.service.submit(_command(harness, kind, version=before.run_version))
        assert harness.store.get_run("run-test") == before
        assert harness.store.list_events("run-test") == events
        assert harness.store.get_command_by_idempotency("run-test", kind) is None
        assert harness.wake_count == wake_count
    finally:
        harness.close()


def test_resume_retains_pending_human_gate(tmp_path):
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _started(harness)
        attempt = harness.store.latest_attempt("run-test", "problem_understanding")
        def seed(uow):
            uow.repository.insert_human_task(task_id="pending-gate", run_id="run-test",
                node_run_id=attempt.node_run_id, handoff_id=None, task_kind="knowledge_gate",
                prompt_json="{}", created_at_ms=FIXED_NOW_MS)
            uow.repository.update_run_status("run-test", "research-team", "waiting_human", FIXED_NOW_MS)
        harness.store.submit(seed, force_flush=True).result(timeout=10)
        harness.service.submit(_command(harness, "pause_run", version=2))
        harness.service.submit(_command(harness, "resume_run", version=3))
        assert harness.store.get_run("run-test").status == "waiting_human"
        assert len(harness.store.read(lambda repo: repo.list_pending_human_tasks("run-test"))) == 1
    finally:
        harness.close()


def _adapter(harness, ports):
    from core.web.services.team_workflow.research_runtime.action_registry import ActionRegistry
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import AgentActionAdapter
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import AdapterDispatchWorker
    registry = ActionRegistry()
    registry.register(AgentActionAdapter(ports))
    return AdapterDispatchWorker(store=harness.store, registry=registry, ports=ports,
        now_provider=lambda: FIXED_NOW_MS + 1000)


def test_adapter_waits_for_resume_then_executes_original_action(tmp_path):
    from tests._support.graph_helpers import GraphHarness
    from tests._support.adapter_fakes import FakeDomainPorts
    graph = GraphHarness(tmp_path)
    harness = graph.commands
    try:
        _started(harness)
        assert graph.worker.run_claim_one()
        queued = graph.latest_adapter_pending()
        ports = FakeDomainPorts()
        worker = _adapter(harness, ports)
        harness.service.submit(_command(harness, "pause_run", version=2))
        assert worker.run_claim_one()
        assert ports.calls == []
        held = harness.store.read(lambda repo: repo.get_outbox(queued.action_id))
        assert held.status == "pending"
        assert held.attempt_count == 0  # a scheduling hold is not a failed execution
        assert harness.store.latest_attempt("run-test", "problem_understanding").status == "dispatching"
        harness.service.submit(_command(harness, "resume_run", version=3))
        assert worker.run_claim_one()
        assert ports.calls.count("create_agent_task") == 1
        resume = _command(harness, "resume_run", version=3)
        harness.service.submit(resume)
        assert not worker.run_claim_one()
        assert ports.calls.count("create_agent_task") == 1
        assert harness.store.read(lambda repo: repo.get_outbox(queued.action_id)).status == "succeeded"
    finally:
        graph.close()


def test_paused_graph_start_retains_original_attempt_until_resume(tmp_path):
    from tests._support.graph_helpers import GraphHarness
    graph = GraphHarness(tmp_path)
    harness = graph.commands
    try:
        _started(harness)
        before = harness.store.list_attempts("run-test")
        action = next(row for row in harness.store.list_pending_outbox("run-test")
                      if row.action_kind == "graph_dispatch")
        harness.service.submit(_command(harness, "pause_run", version=2))
        assert graph.worker.run_claim_one()
        assert harness.store.list_attempts("run-test") == before
        assert graph.latest_adapter_pending() is None
        harness.service.submit(_command(harness, "resume_run", version=3))
        assert graph.worker.run_claim_one()
        assert harness.store.read(lambda repo: repo.get_outbox(action.action_id)).status == "succeeded"
        assert graph.latest_adapter_pending().node_run_id == before[0].node_run_id
    finally:
        graph.close()


def test_existing_completion_cursor_settles_while_run_stays_paused(tmp_path):
    from core.research.workflow.contracts import PendingAction
    from core.web.services.team_workflow.research_runtime.completion_dependency import (
        COMPLETION_PENDING, CompletionDependencyPending, bind_completion_resume,
    )
    from core.web.services.team_workflow.research_runtime.real_domain_ports import publish_agent_task_started_anchor
    from tests._support.adapter_fakes import FakeDomainPorts
    from tests._support.graph_helpers import GraphHarness
    graph = GraphHarness(tmp_path)
    harness = graph.commands
    try:
        _started(harness)
        graph.worker.run_claim_one()
        queued = graph.latest_adapter_pending()
        action = PendingAction.from_dict(json.loads(queued.payload_json))
        ports = FakeDomainPorts()
        handle = ports.create_agent_task(action=action)
        error = CompletionDependencyPending("receipt pending", snapshot={"terminal": True})
        reservation = ports.reserve_budget(action=action, estimate_tokens=1)
        bind_completion_resume(error, action, handle, reservation)
        publish_agent_task_started_anchor(harness.store, action=action,
            binding=ports.resolve_binding(action), handle=handle)
        harness.store.submit(lambda uow: uow.repository.execute(
            "UPDATE outbox_actions SET last_problem_json=? WHERE action_id=?",
            (json.dumps({"code": COMPLETION_PENDING, "completionResume": error.resume}), queued.action_id),
        ), force_flush=True).result(timeout=10)
        harness.service.submit(_command(harness, "pause_run", version=2))
        worker = _adapter(harness, ports)
        assert worker.run_claim_one()
        assert harness.store.latest_attempt("run-test", "problem_understanding").status == "succeeded"
        assert harness.store.get_run("run-test").status == "paused"
        assert ports.calls.count("create_agent_task") == 1
        assert ports.calls.count("reserve_budget") == 1
        assert graph.worker.run_claim_one()  # graph continuation is held
        harness.service.submit(_command(harness, "resume_run", version=3))
        assert graph.worker.run_claim_one()
        assert harness.store.read(lambda repo: repo.get_outbox(queued.action_id)).status == "succeeded"
        assert ports.calls.count("create_agent_task") == 1
    finally:
        graph.close()


@pytest.mark.parametrize("fails", [False, True])
def test_inflight_adapter_settles_without_cancellation_or_implicit_resume(tmp_path, fails):
    from tests._support.graph_helpers import GraphHarness
    from tests._support.adapter_fakes import FakeDomainPorts
    graph = GraphHarness(tmp_path)
    harness = graph.commands
    class Ports(FakeDomainPorts):
        def execute_agent_turn(self, *, action, handle):
            harness.service.submit(_command(harness, "pause_run", version=2))
            if fails:
                raise RuntimeError("observed adapter execution failure")
            return super().execute_agent_turn(action=action, handle=handle)
    try:
        _started(harness)
        graph.worker.run_claim_one()
        ports = Ports()
        assert _adapter(harness, ports).run_claim_one()
        assert harness.store.get_run("run-test").status == ("blocked" if fails else "paused")
        assert harness.store.latest_attempt("run-test", "problem_understanding").status == ("failed" if fails else "succeeded")
        assert ports.calls.count("create_agent_task") == 1
    finally:
        graph.close()


def test_successor_pause_race_retains_action_and_does_not_invoke_graph_twice(tmp_path, monkeypatch):
    from tests._support.graph_helpers import GraphHarness
    from tests._support.adapter_fakes import FakeDomainPorts
    graph = GraphHarness(tmp_path)
    harness = graph.commands
    try:
        _started(harness)
        graph.worker.run_claim_one()
        assert _adapter(harness, FakeDomainPorts()).run_claim_one()
        invoke = graph.coordinator.resume_action
        calls = []
        def resume_and_pause(dispatch):
            calls.append(dispatch.action_id)
            result = invoke(dispatch)
            harness.service.submit(_command(harness, "pause_run", version=2))
            return result
        monkeypatch.setattr(graph.coordinator, "resume_action", resume_and_pause)
        assert graph.worker.run_claim_one()
        held = [row for row in harness.store.list_pending_outbox("run-test") if row.action_kind == "graph_dispatch"]
        assert len(held) == 1
        assert json.loads(held[0].last_problem_json)["code"] == "run_paused"
        assert harness.store.latest_attempt("run-test", "hypothesis_design") is None
        harness.service.submit(_command(harness, "resume_run", version=3))
        assert graph.worker.run_claim_one()
        assert len(calls) == 1
        assert harness.store.latest_attempt("run-test", "hypothesis_design").status == "dispatching"
        assert harness.store.read(lambda repo: repo.get_outbox(held[0].action_id)).status == "succeeded"
    finally:
        graph.close()
