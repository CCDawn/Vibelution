from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.research.workflow.transitions import RunStatus, is_terminal_run
from core.web.services import session_service
from core.web.services.team_workflow.research_runtime import real_domain_ports as module
from core.web.services.team_workflow.research_runtime.cancel_run_cleanup import CancelRunCleanupWorker
from core.web.services.team_workflow.research_runtime.domain_ports import AgentTaskHandle, BindingResolution, ScopedAgentTaskHandle
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import build_attempt_record, build_command_record
from tests.test_research_workflow_formal_hypothesis_fanout import (
    _action,
    _ready_hypothesis_input,
    _start_hypothesis_attempt,
)


@pytest.mark.parametrize("interleave", ["before_fanout_draft", "empty_draft", "between_candidates", "inside_start", "inside_start_lost_response"])
def test_cancel_fences_fanout_and_cleanup_waits_for_unpublished_children(tmp_path, monkeypatch, interleave):
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    entered, release = Event(), Event()
    turns = {}
    starts = []
    try:
        harness.seed_run(run_id="run-1")
        attempt = _start_hypothesis_attempt(harness, "start-fenced")
        action = _action(node_run_id=attempt.node_run_id)
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_project_hypothesis_context.build_hypothesis_input_context",
            lambda *_args, **_kwargs: _ready_hypothesis_input(),
        )
        def resolve_root(**_kwargs):
            if interleave == "before_fanout_draft":
                pause()
            return {"sessionId": "root-1"}

        monkeypatch.setattr(module, "_resolve_formal_node_root_session", resolve_root)
        monkeypatch.setattr(module, "_verify_node_root_session", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(module, "_record_hypothesis_scope_event", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(session_service, "_WORK_RUN_STORE", SimpleNamespace(
            load_snapshot=lambda _kind, turn_id: dict(turns[turn_id]),
            load_run_index=lambda _kind: {},
        ))
        monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: True)

        def stop_turn(session_id, turn_id, **_kwargs):
            turns[turn_id].update(status="cancelled", finishedAt="now")
            return dict(turns[turn_id])

        monkeypatch.setattr(session_service, "request_stop_session_turn", lambda session_id, expected_turn_id: stop_turn(session_id, expected_turn_id))

        def pause():
            entered.set()
            assert release.wait(10), "test driver did not release producer"

        def start_candidate(**kwargs):
            candidate = kwargs["candidate_id"]
            starts.append(candidate)
            turns[f"turn-{candidate}"] = {"turnId": f"turn-{candidate}", "sessionId": f"child-{candidate}", "status": "running"}
            if interleave.startswith("inside_start") and candidate == "H1":
                pause()
                if interleave == "inside_start_lost_response":
                    raise module._HypothesisAuthorityUnavailable("native start response lost")
            return {"candidateId": candidate}

        monkeypatch.setattr(module, "_resolve_or_start_formal_candidate_task", start_candidate)
        monkeypatch.setattr(module, "_scoped_handle_from_started", lambda started, **kwargs: ScopedAgentTaskHandle(
            selection_id=kwargs["selection_id"], candidate_id=kwargs["candidate_id"],
            session_id=f"child-{started['candidateId']}", session_attempt=1,
            task_id=f"task-{started['candidateId']}", turn_id=f"turn-{started['candidateId']}",
            parent_session_id="root-1", root_session_id="root-1",
        ))
        ports = module.RealDomainPorts(harness.store)
        persist = ports._persist_hypothesis_anchor_draft
        paused = False

        def persist_at_barrier(**kwargs):
            nonlocal paused
            result = persist(**kwargs)
            expected_handles = 0 if interleave == "empty_draft" else 1
            if interleave in {"empty_draft", "between_candidates"} and not paused and len(kwargs["handles"]) == expected_handles:
                paused = True
                pause()
            return result

        monkeypatch.setattr(ports, "_persist_hypothesis_anchor_draft", persist_at_barrier)

        def create():
            admission = None
            if interleave == "before_fanout_draft":
                admission = {"status": "creating", "actionId": action.action_id, "admissionId": "outer-admission"}
                ports._persist_agent_task_admission(action, admission)
            return ports._create_hypothesis_fan_out(
                action=action, binding=BindingResolution(agent_id="agent-1", role_key="hypothesis_designer"),
                snapshot={"teamId": "research-team", "projectId": "project-1"},
                fan_out={"selectionId": "selection-1", "selectedCandidateIds": ["H1", "H2"]},
                challenge_task_contract={}, model_invocation_receipt_binding={},
                execution_admission=admission,
            )

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(create)
            try:
                if not entered.wait(10):
                    future.result(timeout=1)
                    pytest.fail("producer did not reach controlled interleave")
                harness.service.submit(harness.request(
                    command=WorkflowCommandKind.CANCEL_RUN, node_id=None, run_id="run-1",
                    expected_run_version=harness.store.get_run("run-1").run_version,
                    idempotency_key="cancel-fenced",
                ))
                worker = CancelRunCleanupWorker(store=harness.store, retry_delay_ms=0)
                worker.run_once()
                row = harness.store.read(lambda repo: repo.execute(
                    "SELECT status FROM outbox_actions WHERE idempotency_key = ?", ("cancel_run_cleanup:run-1",),
                ).fetchone())
                assert row[0] == "pending", "cleanup acknowledged while candidate admission remained in flight"
            finally:
                release.set()
            with pytest.raises(RuntimeError, match="cancelled|terminal|response lost"):
                future.result(timeout=10)

        expected = [] if interleave in {"before_fanout_draft", "empty_draft"} else ["H1"]
        assert starts == expected
        payload = json.loads(harness.store.read(lambda repo: repo.get_anchor_by_node_run(attempt.node_run_id))[13])
        if interleave == "inside_start_lost_response":
            assert payload["executionAdmission"]["status"] == "creating"
            worker.run_once()
            assert harness.store.read(lambda repo: repo.execute(
                "SELECT status FROM outbox_actions WHERE idempotency_key='cancel_run_cleanup:run-1'",
            ).fetchone())[0] == "pending"
            return
        assert payload["executionAdmission"]["status"] == "closed"
        recorded = {item["turnId"] for item in payload["scopedSessions"] if item.get("turnId")}
        assert recorded == set(turns)
        worker.run_once()
        assert all(turn["status"] == "cancelled" for turn in turns.values())
        row = harness.store.read(lambda repo: repo.execute(
            "SELECT status FROM outbox_actions WHERE idempotency_key = ?", ("cancel_run_cleanup:run-1",),
        ).fetchone())
        assert row[0] == "succeeded"
    finally:
        release.set()
        harness.close()


@pytest.mark.parametrize("execution", ["scalar", "meeting"])
def test_public_factory_cancel_before_return_preserves_native_identity(tmp_path, monkeypatch, execution):
    from core.web.services import chat_room_service
    from core.web.services.team_workflow.operator_optimization import discussion_task

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    entered, release = Event(), Event()
    node_id = "optimization_discussion" if execution == "meeting" else "problem_understanding"
    action = replace(_action(), node_id=node_id)
    participants = tuple({
        "participantId": seat, "agentId": agent, "sessionId": f"session-{seat}",
        "turnId": f"chat-room:round-1:{seat}", "taskId": f"task-{seat}",
    } for seat, agent in (("a", "agent-a"), ("b", "agent-b")))
    handle = AgentTaskHandle(
        session_id=participants[0]["sessionId"] if execution == "meeting" else "session-1",
        session_attempt=1, task_id=participants[0]["taskId"] if execution == "meeting" else "task-1",
        turn_id=participants[0]["turnId"] if execution == "meeting" else "turn-1",
        meeting_room_id="room-1" if execution == "meeting" else "",
        meeting_round_id="round-1" if execution == "meeting" else "",
        meeting_participants=participants if execution == "meeting" else (),
    )
    binding = {"workflowRunId": action.run_id, "nodeRunId": action.node_run_id}
    round_state = {"roundId": "round-1", "config": binding, "status": "running", "finishedAt": ""}
    room = {"roomId": "room-1", "activeRoundId": "round-1", "rounds": [round_state],
        "config": {**binding, "operatorDiscussionAuthority": {**binding, "participants": list(participants)}},
        "participants": list(participants)}
    native = {"status": "running", "finishedAt": "", "roomId": "room-1", "roundId": "round-1"}
    stopped = []
    monkeypatch.setattr(chat_room_service, "get_chat_room_detail", lambda *_args, **_kwargs: room)
    monkeypatch.setattr(chat_room_service, "_work_run_store", lambda: SimpleNamespace(
        load_snapshot=lambda *_args: dict(native), load_run_index=lambda *_args: {},
    ))
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", SimpleNamespace(
        load_snapshot=lambda *_args: dict(native), load_run_index=lambda *_args: {},
    ))
    monkeypatch.setattr(session_service, "_is_session_running", lambda *_args: True)

    def stop_round(room_id, *, expected_round_id, **_kwargs):
        assert (room_id, expected_round_id) == ("room-1", "round-1")
        stopped.append((room_id, expected_round_id))
        round_state.update(status="stopped", finishedAt="now")
        native.update(status="stopped", finishedAt="now")
        room["activeRoundId"] = ""

    def stop_turn(session_id, *, expected_turn_id):
        assert (session_id, expected_turn_id) == ("session-1", "turn-1")
        stopped.append((session_id, expected_turn_id))
        native.update(status="stopped", finishedAt="now")

    monkeypatch.setattr(chat_room_service, "stop_chat_room_round", stop_round)
    monkeypatch.setattr(session_service, "request_stop_session_turn", stop_turn)

    def start(*_args, **_kwargs):
        # The native execution now exists, before the adapter receives its handle.
        entered.set()
        assert release.wait(10)
        return handle

    monkeypatch.setattr(discussion_task, "create_discussion_task", start)
    monkeypatch.setattr(module, "_create_real_agent_task", start)
    monkeypatch.setattr(module, "_bounded_agent_node_can_complete", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "_require_canonical_session", lambda **_kwargs: None)
    ports = module.RealDomainPorts(harness.store)
    monkeypatch.setattr(ports, "resolve_binding", lambda _action: BindingResolution("agent-1", "role-1"))
    monkeypatch.setattr(ports, "_run_input_snapshot", lambda _run_id: {})
    try:
        harness.seed_run(run_id="run-1", status="running")

        def seed(uow):
            uow.repository.insert_command(build_command_record("cmd-1", run_id="run-1", node_id=node_id))
            uow.repository.insert_attempt(build_attempt_record(action.node_run_id,
                run_id="run-1", node_id=node_id, command_id="cmd-1", status="dispatching"))

        harness.store.submit(seed, force_flush=True).result(timeout=10)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(ports.create_agent_task, action=action)
            try:
                if not entered.wait(10):
                    future.result(timeout=1)
                    pytest.fail("factory did not reach the native start")
                with pytest.raises(RuntimeError, match="already creating"):
                    ports.create_agent_task(action=action)
                harness.service.submit(harness.request(command=WorkflowCommandKind.CANCEL_RUN,
                    node_id=None, run_id="run-1", idempotency_key="cancel-created"))
                worker = CancelRunCleanupWorker(store=harness.store, retry_delay_ms=0)
                worker.run_once()
                assert harness.store.read(lambda repo: repo.execute(
                    "SELECT status FROM outbox_actions WHERE idempotency_key='cancel_run_cleanup:run-1'",
                ).fetchone())[0] == "pending"
                cancelled_attempt_status = harness.store.read(lambda repo: repo.get_attempt(action.node_run_id)).status
            finally:
                release.set()
            assert future.result(timeout=10) == handle
        anchor = harness.store.read(lambda repo: repo.get_anchor_by_node_run(action.node_run_id))
        payload = json.loads(anchor[13])
        assert payload["executionAdmission"]["status"] == "closed"
        assert anchor[5] == handle.session_id and anchor[8] == handle.turn_id
        assert harness.store.read(lambda repo: repo.get_attempt(action.node_run_id)).status == cancelled_attempt_status
        assert harness.store.get_run("run-1").status == "cancelled"
        if execution == "meeting":
            assert payload["meeting"]["roundId"] == "round-1"
        worker.run_once()
        # A real stop may be asynchronous; one more tick verifies its terminal record.
        worker.run_once()
        assert stopped
        assert harness.store.read(lambda repo: repo.execute(
            "SELECT status FROM outbox_actions WHERE idempotency_key='cancel_run_cleanup:run-1'",
        ).fetchone())[0] == "succeeded"
    finally:
        release.set()
        harness.close()


def test_cancel_commits_before_admission_without_starting_a_factory(tmp_path, monkeypatch):
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1", status="cancelled")
        ports = module.RealDomainPorts(harness.store)
        monkeypatch.setattr(ports, "_create_agent_task", lambda **_kwargs: pytest.fail("cancelled run started execution"))
        with pytest.raises(RuntimeError, match="terminal|cancelled"):
            ports.create_agent_task(action=_action())
        assert harness.store.read(lambda repo: repo.get_anchor_by_node_run("node-1")) is None
    finally:
        harness.close()


def test_unknown_native_start_failure_keeps_admission_pending(tmp_path, monkeypatch):
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1", status="running")
        attempt = _start_hypothesis_attempt(harness, "start-unknown")
        action = _action(node_run_id=attempt.node_run_id)
        ports = module.RealDomainPorts(harness.store)

        def unknown_start(**_kwargs):
            raise module._HypothesisAuthorityUnavailable("native start response lost")

        monkeypatch.setattr(ports, "_create_agent_task", unknown_start)
        with pytest.raises(module._HypothesisAuthorityUnavailable):
            ports.create_agent_task(action=action)
        payload = json.loads(harness.store.read(lambda repo: repo.get_anchor_by_node_run(attempt.node_run_id))[13])
        assert payload["executionAdmission"]["status"] == "creating"
        harness.service.submit(harness.request(command=WorkflowCommandKind.CANCEL_RUN,
            node_id=None, run_id="run-1", expected_run_version=harness.store.get_run("run-1").run_version,
            idempotency_key="cancel-unknown"))
        CancelRunCleanupWorker(store=harness.store, retry_delay_ms=0).run_once()
        assert harness.store.read(lambda repo: repo.execute(
            "SELECT status FROM outbox_actions WHERE idempotency_key='cancel_run_cleanup:run-1'",
        ).fetchone())[0] == "pending"
    finally:
        harness.close()


def test_paused_run_allows_an_already_dispatched_factory_to_finish(tmp_path, monkeypatch):
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-1", status="paused")
        def seed(uow):
            uow.repository.insert_command(build_command_record("cmd-paused", run_id="run-1", node_id="problem_understanding"))
            uow.repository.insert_attempt(build_attempt_record("node-1", run_id="run-1",
                node_id="problem_understanding", command_id="cmd-paused", status="dispatching"))
        harness.store.submit(seed, force_flush=True).result(timeout=10)
        ports = module.RealDomainPorts(harness.store)
        handle = AgentTaskHandle("", 1, "", "", observation_only=True)
        monkeypatch.setattr(ports, "_create_agent_task", lambda **_kwargs: handle)
        monkeypatch.setattr(ports, "resolve_binding", lambda _action: BindingResolution("agent-1", "role-1"))
        assert ports.create_agent_task(action=replace(_action(), node_id="problem_understanding")) == handle
        payload = json.loads(harness.store.read(lambda repo: repo.get_anchor_by_node_run("node-1"))[13])
        assert payload["executionAdmission"]["status"] == "closed"
        assert harness.store.get_run("run-1").status == "paused"
    finally:
        harness.close()


@pytest.mark.parametrize("status", [item.value for item in RunStatus] + ["invalid-run-status"])
def test_execution_admission_uses_the_canonical_run_terminal_contract(status):
    run = SimpleNamespace(status=status)
    if status == "invalid-run-status" or is_terminal_run(RunStatus(status)):
        with pytest.raises(RuntimeError, match="terminal|invalid"):
            module.RealDomainPorts._require_run_execution_admission(run)
    else:
        module.RealDomainPorts._require_run_execution_admission(run)


def test_native_admission_busy_retries_same_action_through_real_wrapper_and_worker(tmp_path, monkeypatch):
    from core.web.services.session import admission_lock
    from core.web.services.team_workflow.research_runtime.action_registry import ActionRegistry
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import AdapterDispatchWorker
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import AgentActionAdapter
    from tests._support.adapter_fakes import FakeDomainPorts
    from tests._support.workflow_ledger_helpers import FIXED_NOW_MS
    from tests.test_research_workflow_t51_task_adapters import _seed_dispatching

    class BusyLock:
        def __enter__(self):
            raise TimeoutError("session admission is occupied")

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(admission_lock, "cross_process_file_lock", lambda *_args, **_kwargs: BusyLock())
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    action = replace(_action(), node_id="problem_understanding")
    calls, native_starts = [], []
    try:
        _seed_dispatching(harness, action)
        ports = module.RealDomainPorts(harness.store)
        fake = FakeDomainPorts()
        for name in ("read_back_input", "resolve_binding", "reserve_budget", "settle_budget",
                     "execute_agent_turn", "read_back_artifact", "required_artifact_kinds"):
            monkeypatch.setattr(ports, name, getattr(fake, name))
        monkeypatch.setattr(ports, "_run_input_snapshot", lambda _run_id: {})
        monkeypatch.setattr(module, "_require_canonical_session", lambda **_kwargs: None)

        def start(*_args, **_kwargs):
            calls.append(action.action_id)
            if len(calls) == 1:
                admission_lock.SessionAdmissionLock(tmp_path, "session-busy").acquire()
            native_starts.append(action.action_id)
            return AgentTaskHandle("session-1", 1, "task-1", "turn-1")

        monkeypatch.setattr(module, "_create_real_agent_task", start)
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        clock = [FIXED_NOW_MS + 1000]
        worker = AdapterDispatchWorker(store=harness.store, registry=registry, ports=ports,
            successor_fn=lambda _node: (), now_provider=lambda: clock[0])
        worker.run_once()
        row = harness.store.read(lambda repo: repo.execute(
            "SELECT status,available_at_ms,last_problem_json FROM outbox_actions WHERE action_kind='adapter_dispatch'",
        ).fetchone())
        assert row[0] == "pending" and "session_busy" in row[2]
        payload = json.loads(harness.store.read(lambda repo: repo.get_anchor_by_node_run(action.node_run_id))[13])
        assert payload["executionAdmission"]["status"] == "closed"
        clock[0] = int(row[1]) + 1
        worker.run_once()
        assert harness.store.read(lambda repo: repo.execute(
            "SELECT status FROM outbox_actions WHERE action_kind='adapter_dispatch'",
        ).fetchone())[0] == "succeeded"
        assert calls == [action.action_id, action.action_id]
        assert native_starts == [action.action_id]
        assert harness.store.read(lambda repo: repo.get_attempt(action.node_run_id)).status == "succeeded"
    finally:
        harness.close()


@pytest.mark.parametrize("known_rejection", [True, False])
def test_busy_during_later_candidate_preserves_earlier_child_and_only_retries_proven_rejection(tmp_path, monkeypatch, known_rejection):
    from core.web.services.session import admission_lock

    class BusyLock:
        def __enter__(self):
            raise TimeoutError("session admission is occupied")

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(admission_lock, "cross_process_file_lock", lambda *_args, **_kwargs: BusyLock())
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    native_tasks, starts = {}, []
    refused = False
    try:
        harness.seed_run(run_id="run-1")
        attempt = _start_hypothesis_attempt(harness, "start-busy-sibling")
        action = _action(node_run_id=attempt.node_run_id)
        binding = BindingResolution("agent-1", "hypothesis_designer")
        ports = module.RealDomainPorts(harness.store)
        monkeypatch.setattr(ports, "resolve_binding", lambda _action: binding)
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_project_hypothesis_context.build_hypothesis_input_context",
            lambda *_args, **_kwargs: _ready_hypothesis_input(),
        )
        monkeypatch.setattr(module, "_resolve_formal_node_root_session", lambda **_kwargs: {"sessionId": "root-1"})
        monkeypatch.setattr(module, "_verify_node_root_session", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(module, "_record_hypothesis_scope_event", lambda *_args, **_kwargs: None)

        def resolve_or_start(**kwargs):
            nonlocal refused
            candidate = kwargs["candidate_id"]
            if candidate in native_tasks:
                return native_tasks[candidate]
            if candidate == "H2" and not refused:
                refused = True
                try:
                    if known_rejection:
                        admission_lock.SessionAdmissionLock(tmp_path, "candidate-H2").acquire()
                    else:
                        raise session_service.SessionBusyError("unknown business phase")
                except session_service.SessionBusyError as exc:
                    # Formal candidate authority retains the original cause.
                    raise module._HypothesisAuthorityUnavailable("candidate unavailable") from exc
            starts.append(candidate)
            native_tasks[candidate] = {"candidateId": candidate}
            return native_tasks[candidate]

        monkeypatch.setattr(module, "_resolve_or_start_formal_candidate_task", resolve_or_start)
        monkeypatch.setattr(module, "_scoped_handle_from_started", lambda started, **kwargs: ScopedAgentTaskHandle(
            selection_id=kwargs["selection_id"], candidate_id=kwargs["candidate_id"],
            session_id=f"child-{started['candidateId']}", session_attempt=1,
            task_id=f"task-{started['candidateId']}", turn_id=f"turn-{started['candidateId']}",
            parent_session_id="root-1", root_session_id="root-1",
        ))

        def fanout(*, action, execution_admission):
            return ports._create_hypothesis_fan_out(action=action, binding=binding,
                snapshot={"teamId": "research-team", "projectId": "project-1"},
                fan_out={"selectionId": "selection-1", "selectedCandidateIds": ["H1", "H2"]},
                challenge_task_contract={}, model_invocation_receipt_binding={},
                execution_admission=execution_admission)

        monkeypatch.setattr(ports, "_create_agent_task", fanout)
        with pytest.raises(module._HypothesisAuthorityUnavailable):
            ports.create_agent_task(action=action)
        payload = json.loads(harness.store.read(lambda repo: repo.get_anchor_by_node_run(action.node_run_id))[13])
        assert [item["turnId"] for item in payload["scopedSessions"] if item.get("turnId")] == ["turn-H1"]
        assert payload["executionAdmission"]["status"] == ("closed" if known_rejection else "creating")
        if known_rejection:
            handle = ports.create_agent_task(action=action)
            assert [child.turn_id for child in handle.scoped_handles] == ["turn-H1", "turn-H2"]
            assert starts == ["H1", "H2"]
        else:
            with pytest.raises(RuntimeError, match="already creating"):
                ports.create_agent_task(action=action)
            assert starts == ["H1"]
    finally:
        harness.close()
