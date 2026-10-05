from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from threading import Event
import json

import pytest

from core.web.services.agent_perception.policy import (
    agent_perception_policy_fingerprint,
    default_agent_perception_policy,
    normalize_agent_perception_policy,
)
from core.web.services.agent_perception.runtime import (
    AgentPerceptionBudgetExceeded,
    AgentPerceptionRuntime,
    AgentPerceptionRuntimeError,
    _lifecycle_snapshot,
    bind_perception_turn,
    cap_perception_output,
    charge_perception_tool_call,
    consume_agent_perception_calls,
    current_perception_budget,
    reserve_perception_input_tokens,
    begin_agent_perception_lifecycle,
    stop_agent_perception_scheduler,
)
from core.web.services.agent_perception.store import AgentPerceptionStore


def _enabled_policy(*, daily_max_runs: int = 2, max_calls: int = 2) -> dict:
    policy = default_agent_perception_policy()
    policy["enabled"] = True
    policy["background"].update(
        {
            "enabled": True,
            "intervalMinutes": 60,
            "dailyMaxRuns": daily_max_runs,
            "maxCallsPerRun": max_calls,
            "maxInputTokensPerRun": 100,
            "maxResultChars": 12,
            "topics": ["用户提供的主题"],
        }
    )
    return normalize_agent_perception_policy(policy)


def _stable_knowledge_access_snapshot(_agent: dict, _policy: dict) -> tuple:
    """Keep test adapters behind the runtime's before/after ACL recheck."""
    return (
        "memory-policy-v1",
        (("team:team-1:base-1", "team", "team-1", True, ("knowledge",)),),
    )


class _FakeSessions:
    CONVERSATION_INDEX_KIND_HIDDEN = "hidden"

    def __init__(self) -> None:
        self.created: list[dict] = []
        self.submitted: list[dict] = []
        self.stopped: list[dict] = []
        self.running: dict[str, str] = {}

    def create_chat_session(self, **kwargs):
        self.created.append(dict(kwargs))
        session_id = f"session-{len(self.created)}"
        self.running[session_id] = ""
        return {"id": session_id, "agentId": kwargs.get("agent_id", "")}

    def submit_session_message(self, session_id, content, **kwargs):
        self.submitted.append({"session_id": session_id, "content": content, **kwargs})
        turn_id = f"turn-{len(self.submitted)}"
        self.running[session_id] = turn_id
        return {"id": session_id, "startedTurnId": turn_id, "currentPhase": "running"}

    def request_stop_session_turn(self, session_id, **kwargs):
        self.stopped.append({"session_id": session_id, **kwargs})
        return {"id": session_id, "currentPhase": "stopping"}

    def get_session_detail(self, session_id, **_kwargs):
        turn_id = self.running.get(session_id, "")
        return {
            "id": session_id,
            "activeTurnId": turn_id,
            "currentPhase": "running" if turn_id else "completed",
            "messages": [{"role": "user"}] if turn_id else [],
        }


class _BlockingSubmitSessions(_FakeSessions):
    def __init__(self) -> None:
        super().__init__()
        self.submit_entered = Event()
        self.submit_release = Event()

    def submit_session_message(self, session_id, content, **kwargs):
        self.submitted.append({"session_id": session_id, "content": content, **kwargs})
        turn_id = f"turn-{len(self.submitted)}"
        # Simulate an accepted native turn whose response is delayed.
        self.running[session_id] = turn_id
        self.submit_entered.set()
        if not self.submit_release.wait(timeout=5):
            raise TimeoutError("test did not release the native submit barrier")
        return {"id": session_id, "startedTurnId": turn_id, "currentPhase": "running"}


class _BlockingCreateSessions(_FakeSessions):
    def __init__(self) -> None:
        super().__init__()
        self.create_entered = Event()
        self.create_release = Event()

    def create_chat_session(self, **kwargs):
        self.created.append(dict(kwargs))
        self.create_entered.set()
        if not self.create_release.wait(timeout=5):
            raise TimeoutError("test did not release the native create barrier")
        session_id = f"session-{len(self.created)}"
        self.running[session_id] = ""
        return {"id": session_id, "agentId": kwargs.get("agent_id", "")}


class _RetryStopSessions(_FakeSessions):
    def __init__(self) -> None:
        super().__init__()
        self.stop_failures_remaining = 1
        self.terminal_phases: dict[str, str] = {}

    def request_stop_session_turn(self, session_id, **kwargs):
        self.stopped.append({"session_id": session_id, **kwargs})
        if self.stop_failures_remaining:
            self.stop_failures_remaining -= 1
            raise RuntimeError("transient stop failure")
        return {"id": session_id, "currentPhase": "stopping", "stopRequested": True}

    def get_session_detail(self, session_id, **_kwargs):
        turn_id = self.running.get(session_id, "")
        return {
            "id": session_id,
            "activeTurnId": turn_id,
            "currentPhase": "running" if turn_id else self.terminal_phases.get(session_id, "completed"),
            "messages": [],
        }


@pytest.fixture
def runtime(tmp_path):
    policy = _enabled_policy()
    agent = {"agentId": "agent-test", "status": "active", "workspacePath": "workspace/agents/agent-test"}
    sessions = _FakeSessions()
    store = AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / "agent-test" / "events" / "perception.json")
    runtime = AgentPerceptionRuntime(
        store=store,
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (deepcopy(policy), agent_perception_policy_fingerprint(policy)),
        session_service=sessions,
        clock=lambda: "2026-10-05T12:00:00Z",
    )
    return runtime, store, sessions, agent, lambda: policy


def test_background_run_uses_hidden_native_session_and_enforces_per_run_budgets(runtime):
    service, _store, sessions, _agent, _policy = runtime

    result = service.run_agent("agent-test")

    assert result["started"] is True
    created = sessions.created[0]
    assert created["activate"] is False
    assert created["conversation_index_kind"] == "hidden"
    assert created["session_metadata"]["source"] == "agent_perception"
    assert sessions.submitted[0]["message_source"] == "agent_perception"
    assert sessions.submitted[0]["include_started_turn_id"] is True

    with bind_perception_turn("session-1", "turn-1", required=True):
        budget = current_perception_budget()
        assert budget["callsRemaining"] == 2
        assert consume_agent_perception_calls(2) is True
        assert consume_agent_perception_calls(1) is False
        assert reserve_perception_input_tokens(70) is True
        assert reserve_perception_input_tokens(31) is False
        assert cap_perception_output("abcdefghijklmnop") == "abcdefghijkl"
        assert cap_perception_output("more") == ""

    # The caller's message/session transcript remains native; the runtime store has no body.
    state = _store.load({"agentId": "agent-test", "workspacePath": "workspace/agents/agent-test"})
    assert "content" not in repr(state)


def test_cancel_stops_only_the_recorded_native_turn(runtime):
    service, _store, sessions, _agent, _policy = runtime
    service.run_agent("agent-test")

    cancelled = service.cancel_agent("agent-test", reason="operator")

    assert cancelled["cancelled"] is False
    assert cancelled["stopRequested"] is True
    assert sessions.stopped == [
        {"session_id": "session-1", "expected_turn_id": "turn-1", "cascade": False}
    ]


def test_cancel_during_submit_is_responsive_and_does_not_bind_a_cancelled_turn(tmp_path):
    policy = _enabled_policy()
    fingerprint = agent_perception_policy_fingerprint(policy)
    agent = {"agentId": "agent-race", "status": "active", "workspacePath": "workspace/agents/agent-race"}
    sessions = _BlockingSubmitSessions()
    service = AgentPerceptionRuntime(
        store=AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / "race.json"),
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (deepcopy(policy), fingerprint),
        session_service=sessions,
        clock=lambda: "2026-10-05T12:00:00Z",
    )
    policy_read_entered = Event()
    policy_read_release = Event()

    def racing_policy_loader(_agent):
        policy_read_entered.set()
        if not policy_read_release.wait(timeout=5):
            raise TimeoutError("test did not release the policy read barrier")
        return deepcopy(policy), fingerprint

    def bind_turn():
        try:
            with bind_perception_turn("session-1", "turn-1", required=True):
                return "bound"
        except AgentPerceptionRuntimeError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as workers:
        dispatch = workers.submit(service.run_agent, "agent-race")
        assert sessions.submit_entered.wait(timeout=2)

        # The turn binder has observed an unrecorded native turn but has not
        # yet acquired the durable turn binding when cancellation arrives.
        service._policy_loader = racing_policy_loader
        binder = workers.submit(bind_turn)
        assert policy_read_entered.wait(timeout=2)
        cancelled = service.cancel_agent("agent-race", reason="operator")
        assert cancelled["stopRequested"] is True
        assert cancelled["cancelled"] is False
        assert sessions.stopped == []

        policy_read_release.set()
        assert binder.result(timeout=2) == "rejected"
        sessions.submit_release.set()
        result = dispatch.result(timeout=2)

    assert result["reason"] == "cancelled_during_submit"
    assert sessions.stopped == [
        {"session_id": "session-1", "expected_turn_id": "turn-1", "cascade": False}
    ]


def test_lifecycle_close_during_create_fences_submit_and_reopen_starts_new_work(tmp_path):
    begin_agent_perception_lifecycle()
    policy = _enabled_policy()
    agent = {"agentId": "agent-lifecycle-create", "status": "active", "workspacePath": "workspace/agents/agent-lifecycle-create"}
    sessions = _BlockingCreateSessions()
    service = AgentPerceptionRuntime(
        store=AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / "lifecycle-create.json"),
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (deepcopy(policy), agent_perception_policy_fingerprint(policy)),
        session_service=sessions,
        clock=lambda: "2026-10-05T12:00:00Z",
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            dispatch = workers.submit(service.run_agent, "agent-lifecycle-create")
            assert sessions.create_entered.wait(timeout=2)
            assert stop_agent_perception_scheduler(wait=False)["closed"] is True
            sessions.create_release.set()
            result = dispatch.result(timeout=2)

        assert result["reason"] == "cancelled_before_submit"
        assert sessions.submitted == []
        with pytest.raises(AgentPerceptionRuntimeError):
            with bind_perception_turn("session-1", "turn-1", required=True):
                pass
        assert service.run_agent("agent-lifecycle-create")["reason"] == "lifecycle_closed"

        begin_agent_perception_lifecycle()
        reopened = service.run_agent("agent-lifecycle-create")
        assert reopened["started"] is True
        with bind_perception_turn("session-2", "turn-1", required=True):
            assert current_perception_budget() is not None
            stop_agent_perception_scheduler(wait=False)
            with pytest.raises(AgentPerceptionBudgetExceeded):
                charge_perception_tool_call()
            begin_agent_perception_lifecycle()
            assert current_perception_budget() is None
    finally:
        sessions.create_release.set()
        begin_agent_perception_lifecycle()


def test_lifecycle_close_during_native_submit_stops_exact_late_turn(tmp_path):
    begin_agent_perception_lifecycle()
    policy = _enabled_policy()
    agent = {"agentId": "agent-lifecycle-submit", "status": "active", "workspacePath": "workspace/agents/agent-lifecycle-submit"}
    sessions = _BlockingSubmitSessions()
    service = AgentPerceptionRuntime(
        store=AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / "lifecycle-submit.json"),
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (deepcopy(policy), agent_perception_policy_fingerprint(policy)),
        session_service=sessions,
        clock=lambda: "2026-10-05T12:00:00Z",
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            dispatch = workers.submit(service.run_agent, "agent-lifecycle-submit")
            assert sessions.submit_entered.wait(timeout=2)
            assert stop_agent_perception_scheduler(wait=False)["closed"] is True
            with pytest.raises(AgentPerceptionRuntimeError):
                with bind_perception_turn("session-1", "turn-1", required=True):
                    pass
            sessions.submit_release.set()
            result = dispatch.result(timeout=2)

        assert result["reason"] == "cancelled_during_submit"
        assert sessions.stopped == [
            {"session_id": "session-1", "expected_turn_id": "turn-1", "cascade": False}
        ]
    finally:
        sessions.submit_release.set()
        begin_agent_perception_lifecycle()


def test_recovery_retries_exact_failed_stop_clears_terminal_run_and_reschedules(monkeypatch, tmp_path):
    from core.web.services import agent_directory_service
    from core.web.services.agent_perception import runtime as runtime_module

    begin_agent_perception_lifecycle()
    policy = _enabled_policy()
    fingerprint = agent_perception_policy_fingerprint(policy)
    agent = {
        "agentId": "agent-stop-recovery",
        "status": "active",
        "workspacePath": "workspace/agents/agent-stop-recovery",
        "metadata": {"perceptionPolicy": deepcopy(policy)},
    }
    sessions = _RetryStopSessions()
    sessions.running["unrelated-session"] = "unrelated-turn"
    store = AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / "stop-recovery.json")
    runtime = AgentPerceptionRuntime(
        store=store,
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (deepcopy(policy), fingerprint),
        session_service=sessions,
        clock=lambda: "2026-10-05T12:00:00Z",
        knowledge_snapshot_loader=lambda _agent, _policy: [],
    )
    try:
        assert runtime.run_agent("agent-stop-recovery")["started"] is True
        cancelled = runtime.cancel_agent("agent-stop-recovery", reason="operator")
        assert cancelled["stopRequested"] is False
        assert runtime.recover_agent("agent-stop-recovery")["activeRun"]["status"] == "stopping"
        exact_stop = {"session_id": "session-1", "expected_turn_id": "turn-1", "cascade": False}
        assert sessions.stopped == [exact_stop, exact_stop]

        sessions.running.pop("session-1")
        sessions.terminal_phases["session-1"] = "stopped"
        state = store.load(agent)
        state["nextRunAt"] = "2026-10-05T11:00:00Z"
        store.save(agent, state)

        class _OnePassStop:
            stopped = False

            def is_set(self):
                return self.stopped

            def wait(self, _seconds):
                self.stopped = True
                return True

        monkeypatch.setattr(agent_directory_service, "list_agents", lambda **_kwargs: [deepcopy(agent)])
        monkeypatch.setattr(runtime_module, "_get_default_runtime", lambda: runtime)
        runtime_module._scheduler_loop(_OnePassStop(), 1.0)

        recovered = store.load(agent)
        assert recovered["lastRun"]["status"] == "stopped"
        assert recovered["activeRun"]["sessionId"] == "session-2"
        assert len(sessions.created) == 2
        assert len(sessions.submitted) == 2
        assert sessions.stopped == [exact_stop, exact_stop]
    finally:
        begin_agent_perception_lifecycle()


def test_daily_run_pruning_keeps_today_and_a_bounded_past_window():
    from core.web.services.agent_perception.runtime import _prune_daily_runs

    today = date(2026, 10, 5)
    old_day = (today - timedelta(days=31)).isoformat()
    recent_day = (today - timedelta(days=30)).isoformat()
    daily_runs = {
        today.isoformat(): 2,
        old_day: 5,
        recent_day: 3,
        "invalid-day": 8,
    }

    pruned = _prune_daily_runs(daily_runs, today)

    assert pruned[today.isoformat()] == 2
    assert pruned[recent_day] == 3
    assert old_day not in pruned
    assert "invalid-day" not in pruned
    assert len(pruned) <= 31


def test_policy_fingerprint_change_revokes_active_run(runtime):
    service, _store, sessions, _agent, current_policy = runtime
    service.run_agent("agent-test")
    changed = current_policy()
    changed["background"]["intervalMinutes"] = 120
    service._policy_loader = lambda _agent: (
        normalize_agent_perception_policy(changed),
        agent_perception_policy_fingerprint(changed),
    )

    service.on_policy_saved("agent-test")

    assert sessions.stopped[0]["expected_turn_id"] == "turn-1"
    assert service.get_agent_perception_runtime("agent-test")["status"] == "stopping"


def test_policy_save_clears_disabled_schedule_and_reenable_uses_new_interval(runtime):
    service, store, _sessions, agent, current_policy = runtime
    state = store.load(agent)
    state["nextRunAt"] = "2026-10-12T12:00:00Z"
    state["scheduleFingerprint"] = "v1:enabled:10080"
    store.save(agent, state)
    policy = current_policy()
    policy["background"]["intervalMinutes"] = 10_080
    policy["background"]["enabled"] = False

    disabled = service.on_policy_saved("agent-test")

    assert disabled["enabled"] is False
    assert disabled["nextRunAt"] == ""
    assert store.load(agent)["scheduleFingerprint"] == "v1:disabled"

    policy["background"]["enabled"] = True
    policy["background"]["intervalMinutes"] = 15
    enabled = service.on_policy_saved("agent-test")

    assert enabled["enabled"] is True
    assert enabled["nextRunAt"] == "2026-10-05T12:15:00Z"
    assert store.load(agent)["scheduleFingerprint"] == "v1:enabled:15"


def test_policy_save_recalculates_interval_but_not_unrelated_changes(runtime):
    service, store, _sessions, agent, current_policy = runtime
    state = store.load(agent)
    state["nextRunAt"] = "2026-10-05T13:00:00Z"
    state["scheduleFingerprint"] = "v1:enabled:60"
    store.save(agent, state)
    policy = current_policy()
    policy["background"]["topics"] = ["另一个主题"]

    topic_update = service.on_policy_saved("agent-test")

    assert topic_update["nextRunAt"] == "2026-10-05T13:00:00Z"

    policy["background"]["intervalMinutes"] = 25
    interval_update = service.on_policy_saved("agent-test")

    assert interval_update["nextRunAt"] == "2026-10-05T12:25:00Z"
    assert store.load(agent)["scheduleFingerprint"] == "v1:enabled:25"


def test_zero_daily_budget_never_creates_a_queued_or_hidden_session(runtime):
    _service, store, sessions, _agent, _current_policy = runtime
    policy = _enabled_policy(daily_max_runs=0)
    service = AgentPerceptionRuntime(
        store=store,
        agent_loader=lambda _agent_id: {"agentId": "agent-test", "status": "active", "workspacePath": "workspace/agents/agent-test"},
        policy_loader=lambda _agent: (policy, agent_perception_policy_fingerprint(policy)),
        session_service=sessions,
        clock=lambda: "2026-10-05T12:00:00Z",
    )

    result = service.run_agent("agent-test")

    assert result["started"] is False
    assert result["reason"] == "daily_budget_zero"
    assert sessions.created == []


def test_recovery_adopts_exact_running_native_turn_without_duplicate_submit(runtime):
    from core.web.services.agent_perception import runtime as runtime_module

    _old, store, sessions, agent, current_policy = runtime
    policy = current_policy()
    fingerprint = agent_perception_policy_fingerprint(policy)
    sessions.running["session-existing"] = "turn-existing"
    state = store.load(agent)
    state["activeRun"] = {
        "runId": "run-existing",
        "topicId": "topic-1",
        "topicHash": "hash-1",
        "status": "running",
        "sessionId": "session-existing",
        "turnId": "turn-existing",
        "policyFingerprint": fingerprint,
        "startedAt": "2026-10-05T11:00:00Z",
        "toolCallsUsed": 1,
        "inputTokensUsed": 20,
        "outputCharsUsed": 3,
        "lifecycleGeneration": _lifecycle_snapshot()[1],
        "bootEpoch": runtime_module._BOOT_EPOCH,
    }
    state["policyFingerprint"] = fingerprint
    store.save(agent, state)
    service = AgentPerceptionRuntime(
        store=store,
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (policy, fingerprint),
        session_service=sessions,
        clock=lambda: "2026-10-05T12:00:00Z",
    )

    recovered = service.recover_agent("agent-test")

    assert recovered["status"] == "running"
    assert recovered["activeRun"]["turnId"] == "turn-existing"
    assert sessions.created == []
    assert sessions.submitted == []


def test_recovery_fences_previous_boot_run_without_touching_native_sessions(monkeypatch, tmp_path):
    from core.web.services.agent_perception import runtime as runtime_module

    policy = _enabled_policy(daily_max_runs=1)
    fingerprint = agent_perception_policy_fingerprint(policy)
    agent = {
        "agentId": "agent-previous-boot",
        "status": "active",
        "workspacePath": "workspace/agents/agent-previous-boot",
    }

    class _ObservedSessions(_FakeSessions):
        def __init__(self):
            super().__init__()
            self.inspected: list[str] = []

        def get_session_detail(self, session_id, **kwargs):
            self.inspected.append(session_id)
            return super().get_session_detail(session_id, **kwargs)

    sessions = _ObservedSessions()
    sessions.running.update({
        "session-previous-boot": "turn-previous-boot",
        "ordinary-session": "ordinary-turn",
    })
    store = AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / "previous-boot.json")
    state = store.load(agent)
    state["dailyRuns"] = {"2026-10-05": 1}
    state["topicCursor"] = 1
    state["activeRun"] = {
        "runId": "run-previous-boot",
        "topicId": "topic-1",
        "status": "running",
        "sessionId": "session-previous-boot",
        "turnId": "turn-previous-boot",
        "policyFingerprint": fingerprint,
        "startedAt": "2026-10-05T11:00:00Z",
        "toolCallsUsed": 1,
        "inputTokensUsed": 20,
        "outputCharsUsed": 3,
        "lifecycleGeneration": _lifecycle_snapshot()[1],
        "bootEpoch": "previous-process-epoch",
    }
    state["policyFingerprint"] = fingerprint
    store.save(agent, state)
    monkeypatch.setattr(runtime_module, "_BOOT_EPOCH", "current-process-epoch")
    runtime = AgentPerceptionRuntime(
        store=store,
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (deepcopy(policy), fingerprint),
        session_service=sessions,
        clock=lambda: "2026-10-05T12:00:00Z",
    )

    recovered = runtime.recover_agent("agent-previous-boot")
    persisted = store.load(agent)

    assert recovered["activeRun"] is None
    assert persisted["lastRun"]["runId"] == "run-previous-boot"
    assert persisted["lastRun"]["bootEpoch"] == "previous-process-epoch"
    assert persisted["lastRun"]["status"] == "interrupted"
    assert persisted["lastRun"]["reason"] == "boot_epoch_changed"
    assert persisted["dailyRuns"] == {"2026-10-05": 1}
    assert persisted["topicCursor"] == 1
    assert sessions.inspected == []
    assert sessions.stopped == []
    assert sessions.created == []
    assert sessions.submitted == []
    assert sessions.running == {
        "session-previous-boot": "turn-previous-boot",
        "ordinary-session": "ordinary-turn",
    }


def test_non_perception_turn_has_no_perception_budget():
    with bind_perception_turn("ordinary-session", "turn-ordinary"):
        assert current_perception_budget() is None
        assert consume_agent_perception_calls(1) is True
        assert reserve_perception_input_tokens(100000) is True
        assert cap_perception_output("ordinary output") == "ordinary output"


def test_tool_and_source_read_budgets_are_independent_at_one_call_each(tmp_path):
    policy = _enabled_policy(max_calls=1)
    agent = {"agentId": "agent-budget", "status": "active", "workspacePath": "workspace/agents/agent-budget"}
    sessions = _FakeSessions()
    runtime = AgentPerceptionRuntime(
        store=AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / "budget.json"),
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (policy, agent_perception_policy_fingerprint(policy)),
        session_service=sessions,
        clock=lambda: "2026-10-05T12:00:00Z",
    )
    assert runtime.run_agent("agent-budget")["started"] is True

    with bind_perception_turn("session-1", "turn-1", required=True):
        charge_perception_tool_call()
        assert consume_agent_perception_calls(1) is True
        with pytest.raises(AgentPerceptionBudgetExceeded):
            charge_perception_tool_call()


def test_knowledge_revision_cursor_baselines_then_notifies_without_storing_body(tmp_path):
    policy = _enabled_policy()
    policy["notifications"]["mode"] = "all"
    policy["sources"]["knowledge"].update(
        {"mode": "auto", "knowledgeBaseIds": ["team:team-1:base-1"]}
    )
    policy["sources"]["knowledge"]["triggers"]["update"] = True
    policy = normalize_agent_perception_policy(policy)
    agent = {"agentId": "agent-kb", "status": "active", "workspacePath": "workspace/agents/agent-kb"}
    items = [{
        "knowledgeBaseId": "team:team-1:base-1",
        "knowledgeItemId": "item-1",
        "sources": ["team", "knowledge"],
        "revision": "1",
        "contentHash": "hash-v1",
        "title": "计划",
        "content": "private body v1",
    }]
    store = AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / "knowledge.json")
    runtime = AgentPerceptionRuntime(
        store=store,
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (deepcopy(policy), agent_perception_policy_fingerprint(policy)),
        session_service=_FakeSessions(),
        clock=lambda: "2026-10-05T12:00:00Z",
        knowledge_snapshot_loader=lambda _agent, _policy: deepcopy(items),
        knowledge_access_snapshot_loader=_stable_knowledge_access_snapshot,
    )

    assert runtime.scan_knowledge_updates("agent-kb")["changed"] == 0
    items[0].update({"revision": "2", "contentHash": "hash-v2", "content": "private body v2"})
    result = runtime.scan_knowledge_updates("agent-kb")

    assert result["changed"] == 1
    assert result["notified"] == 1
    state = store.load(agent)
    assert state["notifications"][0]["revision"] == "2"
    assert state["notifications"][0]["source"] == "knowledge"
    assert "private body" not in repr(state)


def test_quiet_knowledge_scan_advances_cursor_and_counts_suppressed_changes(tmp_path):
    policy = _enabled_policy()
    policy["notifications"]["mode"] = "quiet"
    agent = {"agentId": "agent-quiet", "status": "active", "workspacePath": "workspace/agents/agent-quiet"}
    items = [{"knowledgeBaseId": "kb-1", "knowledgeItemId": "item-1", "revision": "1", "contentHash": "hash-1"}]
    store = AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / "quiet.json")
    runtime = AgentPerceptionRuntime(
        store=store,
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (deepcopy(policy), agent_perception_policy_fingerprint(policy)),
        session_service=_FakeSessions(),
        clock=lambda: "2026-10-05T12:00:00Z",
        knowledge_snapshot_loader=lambda _agent, _policy: deepcopy(items),
        knowledge_access_snapshot_loader=_stable_knowledge_access_snapshot,
    )
    runtime.scan_knowledge_updates("agent-quiet")
    items[0].update({"revision": "2", "contentHash": "hash-2"})

    result = runtime.scan_knowledge_updates("agent-quiet")

    state = store.load(agent)
    assert result["suppressed"] == 1
    assert state["suppressedNotificationCount"] == 1
    assert state["knowledgeCursors"]["kb-1"]["items"]["item-1"]["revision"] == "2"
    assert state["notifications"] == []


def test_incomplete_knowledge_snapshot_preserves_existing_cursor_and_notifications(tmp_path):
    policy = _enabled_policy()
    agent = {"agentId": "agent-partial", "status": "active", "workspacePath": "workspace/agents/agent-partial"}
    store = AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / "partial.json")
    state = store.load(agent)
    state["knowledgeCursors"] = {
        "kb-1": {"items": {"item-1": {"revision": "1", "contentHash": "hash-v1"}}, "scannedAt": "prior-scan"}
    }
    state["notifications"] = [{
        "notificationId": "pending",
        "knowledgeBaseId": "kb-1",
        "knowledgeItemId": "item-1",
        "revision": "1",
        "contentHash": "hash-v1",
        "delivered": False,
    }]
    state["knowledgeScan"] = {"basesScanned": 1, "pendingCount": 1, "scannedAt": "prior-scan"}
    store.save(agent, state)
    before = store.load(agent)
    runtime = AgentPerceptionRuntime(
        store=store,
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (deepcopy(policy), agent_perception_policy_fingerprint(policy)),
        session_service=_FakeSessions(),
        clock=lambda: "2026-10-05T12:00:00Z",
        knowledge_snapshot_loader=lambda _agent, _policy: {
            "rows": [{
                "knowledgeBaseId": "kb-1", "knowledgeItemId": "item-1",
                "revision": "2", "contentHash": "hash-v2",
            }],
            "complete": False,
        },
        knowledge_access_snapshot_loader=_stable_knowledge_access_snapshot,
    )

    result = runtime.scan_knowledge_updates("agent-partial")

    assert result == {"basesScanned": 0, "changed": 0, "notified": 0, "suppressed": 0}
    assert store.load(agent) == before


def test_knowledge_acl_revocation_during_scan_discards_the_entire_batch(tmp_path):
    policy = _enabled_policy()
    policy["background"]["enabled"] = False
    policy["notifications"]["mode"] = "all"
    policy["sources"]["knowledge"].update({
        "mode": "auto",
        "knowledgeBaseIds": ["team:team-1:base-1"],
    })
    policy["sources"]["knowledge"]["triggers"]["update"] = True
    policy = normalize_agent_perception_policy(policy)
    agent = {"agentId": "agent-acl-revoked", "status": "active", "workspacePath": "workspace/agents/agent-acl-revoked"}
    store = AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / "acl-revoked.json")
    state = store.load(agent)
    state["knowledgeCursors"] = {
        "team:team-1:base-1": {
            "items": {"item-1": {"revision": "1", "contentHash": "hash-v1"}},
            "scannedAt": "prior-scan",
        },
    }
    state["notifications"] = [{
        "notificationId": "pending-before-revocation",
        "knowledgeBaseId": "team:team-1:base-1",
        "knowledgeItemId": "item-1",
        "revision": "1",
        "contentHash": "hash-v1",
        "delivered": False,
    }]
    state["knowledgeScan"] = {"basesScanned": 1, "pendingCount": 1, "scannedAt": "prior-scan"}
    store.save(agent, state)
    before = store.load(agent)

    access = {
        "memoryPolicy": "enabled-v1",
        "visibleBases": (("team:team-1:base-1", "team", "team-1", True, ("knowledge",)),),
    }
    access_calls = []
    rows = [{
        "knowledgeBaseId": "team:team-1:base-1",
        "knowledgeItemId": "item-1",
        "sources": ["knowledge"],
        "revision": "2",
        "contentHash": "hash-v2",
    }]

    def load_access_snapshot(_agent, _policy):
        access_calls.append((access["memoryPolicy"], access["visibleBases"]))
        return access["memoryPolicy"], access["visibleBases"]

    def load_knowledge_snapshot(_agent, _policy):
        # Revoke the source after the bytes are read but before the runtime's
        # pre-commit authorization recheck.
        access["memoryPolicy"] = "disabled-v2"
        access["visibleBases"] = ()
        return deepcopy(rows)

    runtime = AgentPerceptionRuntime(
        store=store,
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (deepcopy(policy), agent_perception_policy_fingerprint(policy)),
        session_service=_FakeSessions(),
        clock=lambda: "2026-10-05T12:00:00Z",
        knowledge_snapshot_loader=load_knowledge_snapshot,
        knowledge_access_snapshot_loader=load_access_snapshot,
    )

    result = runtime.scan_knowledge_updates("agent-acl-revoked")

    assert result == {"basesScanned": 0, "changed": 0, "notified": 0, "suppressed": 0}
    assert len(access_calls) == 2
    assert access_calls[0] != access_calls[1]
    assert store.load(agent) == before


def test_update_scan_is_independent_of_background_budgets(tmp_path):
    policy = _enabled_policy(daily_max_runs=0, max_calls=1)
    policy["background"].update({
        "enabled": False,
        "intervalMinutes": 10_080,
        "maxResultChars": 1,
    })
    policy["sources"]["knowledge"].update({
        "mode": "auto",
        "knowledgeBaseIds": ["team:team-1:base-1"],
    })
    policy["sources"]["knowledge"]["triggers"]["update"] = True
    policy = normalize_agent_perception_policy(policy)
    agent = {"agentId": "agent-update-only", "status": "active", "workspacePath": "workspace/agents/agent-update-only"}
    rows = [{
        "knowledgeBaseId": "team:team-1:base-1",
        "knowledgeItemId": "item-1",
        "revision": "1",
        "contentHash": "hash-v1",
    }]
    store = AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / "update-only.json")
    runtime = AgentPerceptionRuntime(
        store=store,
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (deepcopy(policy), agent_perception_policy_fingerprint(policy)),
        session_service=_FakeSessions(),
        clock=lambda: "2026-10-05T12:00:00Z",
        knowledge_snapshot_loader=lambda _agent, _policy: deepcopy(rows),
        knowledge_access_snapshot_loader=_stable_knowledge_access_snapshot,
    )

    result = runtime.scan_knowledge_updates("agent-update-only")

    assert result["basesScanned"] == 1
    assert store.load(agent)["knowledgeCursors"]["team:team-1:base-1"]["items"]["item-1"]["revision"] == "1"
    assert runtime.run_agent("agent-update-only")["reason"] == "background_disabled"


@pytest.mark.parametrize("source", ["knowledge", "projects"])
def test_scheduler_scans_update_subscription_at_five_minutes_and_requires_saved_policy(monkeypatch, source):
    from core.web.services import agent_directory_service
    from core.web.services.agent_perception import runtime as runtime_module

    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    policy = _enabled_policy(daily_max_runs=0, max_calls=1)
    policy["background"].update({"enabled": False, "intervalMinutes": 10_080, "maxResultChars": 1})
    if source == "knowledge":
        policy["sources"]["knowledge"].update({
            "mode": "auto",
            "knowledgeBaseIds": ["team:team-1:base-1"],
        })
        policy["sources"]["knowledge"]["triggers"]["update"] = True
    else:
        policy["sources"]["projects"].update({"mode": "auto"})
        policy["sources"]["projects"]["triggers"]["update"] = True
    policy = normalize_agent_perception_policy(policy)
    configured = {
        "agentId": "agent-configured",
        "status": "active",
        "metadata": {"perceptionPolicy": policy},
    }
    unconfigured = {"agentId": "agent-legacy", "status": "active", "metadata": {}}
    calls = {"recovered": [], "scanned": [], "run": []}

    class _OnePassStop:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, _seconds):
            self.stopped = True
            return True

    class _Runtime:
        def _now(self):
            return now

        def recover_agent(self, agent_id):
            calls["recovered"].append(agent_id)
            return {"activeRun": None, "nextRunAt": "2099-01-01T00:00:00Z"}

        def _agent(self, agent_id):
            return configured

        def _policy(self, _agent):
            return policy, agent_perception_policy_fingerprint(policy)

        class _Store:
            def load(self, _agent):
                return {"knowledgeScan": {"scannedAt": "2026-10-05T11:54:00Z"}}

        _store = _Store()

        def scan_knowledge_updates(self, agent_id):
            calls["scanned"].append(agent_id)
            return {"basesScanned": 0, "changed": 0, "notified": 0, "suppressed": 0}

        def run_agent(self, agent_id):
            calls["run"].append(agent_id)

    monkeypatch.setattr(agent_directory_service, "list_agents", lambda **_kwargs: [unconfigured, configured])
    monkeypatch.setattr(runtime_module, "_get_default_runtime", lambda: _Runtime())
    runtime_module._scheduler_loop(_OnePassStop(), 1.0)

    assert calls["recovered"] == ["agent-configured"]
    assert calls["scanned"] == ["agent-configured"]
    assert calls["run"] == []


def test_project_governance_registry_baselines_then_notifies_head_and_card_changes(tmp_path, monkeypatch):
    from core.web.services import github_project_governance_catalog, github_project_library_service

    policy = _enabled_policy(daily_max_runs=0)
    policy["background"]["enabled"] = False
    policy["notifications"]["mode"] = "all"
    policy["sources"]["projects"].update({"mode": "auto"})
    policy["sources"]["projects"]["triggers"]["update"] = True
    policy = normalize_agent_perception_policy(policy)
    agent = {"agentId": "agent-projects", "status": "active", "workspacePath": "workspace/agents/agent-projects"}
    registry_path = tmp_path / "registry.json"
    project = {
        "projectId": "openai__codex", "fullName": "openai/codex", "headSha": "head-v1",
        "status": "ready", "hasSubmodules": False,
    }

    def write_registry():
        registry_path.write_text(json.dumps({"schemaVersion": 1, "projects": [project]}), encoding="utf-8")

    card = {
        "capabilities": ["工具审批"],
        "useCases": ["策略判决与执行分离"],
        "governanceReview": {"status": "static_reviewed", "borrowedSlice": "按策略分离执行"},
    }
    write_registry()
    monkeypatch.setattr(github_project_library_service, "github_project_library_root", lambda **_kwargs: tmp_path)
    monkeypatch.setattr(github_project_governance_catalog, "governance_metadata", lambda _root, _project: deepcopy(card))

    store = AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / "projects.json")
    runtime = AgentPerceptionRuntime(
        store=store,
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (deepcopy(policy), agent_perception_policy_fingerprint(policy)),
        session_service=_FakeSessions(),
        clock=lambda: "2026-10-05T12:00:00Z",
        knowledge_snapshot_loader=lambda _agent, _policy: [],
    )

    assert runtime.scan_knowledge_updates("agent-projects")["changed"] == 0
    assert store.load(agent)["knowledgeCursors"]["local-project-governance"]["items"]["openai__codex"]["revision"] == "head-v1"

    project["headSha"] = "head-v2"
    write_registry()
    head_change = runtime.scan_knowledge_updates("agent-projects")
    assert head_change["changed"] == 1
    assert head_change["notified"] == 1
    state = store.load(agent)
    first_notification = state["notifications"][-1]
    assert first_notification["knowledgeBaseId"] == "local-project-governance"
    assert first_notification["source"] == "projects"
    assert first_notification["revision"] == "head-v2"
    assert state["pendingKnowledgeCandidates"][-1]["source"] == "projects"

    old_card_hash = first_notification["contentHash"]
    card["governanceReview"]["borrowedSlice"] = "复核后的治理卡片"
    card_change = runtime.scan_knowledge_updates("agent-projects")
    assert card_change["changed"] == 1
    assert card_change["notified"] == 1
    latest_notification = store.load(agent)["notifications"][-1]
    assert latest_notification["revision"] == "head-v2"
    assert latest_notification["contentHash"] != old_card_hash


def test_invalid_notification_source_is_omitted_from_notification_and_pending_candidate(tmp_path):
    policy = _enabled_policy()
    policy["background"]["enabled"] = False
    policy["notifications"]["mode"] = "all"
    policy["sources"]["knowledge"].update({"mode": "auto", "knowledgeBaseIds": ["team:team-1:base-1"]})
    policy["sources"]["knowledge"]["triggers"]["update"] = True
    policy = normalize_agent_perception_policy(policy)
    agent = {"agentId": "agent-invalid-source", "status": "active", "workspacePath": "workspace/agents/agent-invalid-source"}
    rows = [{
        "knowledgeBaseId": "team:team-1:base-1", "knowledgeItemId": "item-1",
        "sources": ["unknown"], "revision": "1", "contentHash": "hash-v1",
    }]
    store = AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / "invalid-source.json")
    runtime = AgentPerceptionRuntime(
        store=store,
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (deepcopy(policy), agent_perception_policy_fingerprint(policy)),
        session_service=_FakeSessions(),
        clock=lambda: "2026-10-05T12:00:00Z",
        knowledge_snapshot_loader=lambda _agent, _policy: deepcopy(rows),
        knowledge_access_snapshot_loader=_stable_knowledge_access_snapshot,
    )

    runtime.scan_knowledge_updates("agent-invalid-source")
    rows[0]["revision"] = "2"
    rows[0]["contentHash"] = "hash-v2"
    runtime.scan_knowledge_updates("agent-invalid-source")

    state = store.load(agent)
    assert state["notifications"]
    assert "source" not in state["notifications"][-1]
    assert "source" not in state["pendingKnowledgeCandidates"][-1]


@pytest.mark.parametrize("bound", [
    "registry_bytes", "registry_items", "governance_card", "schema_bool",
    "schema_float", "duplicate_trimmed_project_ids", "head_sha_type", "registry_json_depth",
])
def test_project_governance_snapshot_fails_closed_at_existing_bounds(tmp_path, monkeypatch, bound):
    from core.web.services import github_project_governance_catalog, github_project_library_service
    from core.web.services.agent_perception import runtime as runtime_module

    monkeypatch.setattr(github_project_library_service, "github_project_library_root", lambda **_kwargs: tmp_path)
    if bound == "registry_bytes":
        monkeypatch.setattr(runtime_module, "_MAX_PROJECT_REGISTRY_BYTES", 32)
        (tmp_path / "registry.json").write_text("{" + (" " * 40) + "}", encoding="utf-8")
    elif bound == "registry_json_depth":
        nested = "[" * 2_000 + "0" + "]" * 2_000
        (tmp_path / "registry.json").write_text(
            '{"schemaVersion":1,"projects":[' + nested + "]}", encoding="utf-8",
        )
    else:
        projects = [
            {"projectId": f"project-{index}", "headSha": "head", "status": "ready", "hasSubmodules": False}
            for index in range(2 if bound == "registry_items" else 1)
        ]
        schema_version = 1
        if bound == "schema_bool":
            schema_version = True
        elif bound == "schema_float":
            schema_version = 1.0
        elif bound == "duplicate_trimmed_project_ids":
            projects = [
                {"projectId": "project-1", "headSha": "head", "status": "ready", "hasSubmodules": False},
                {"projectId": " project-1 ", "headSha": "head", "status": "ready", "hasSubmodules": False},
            ]
        elif bound == "head_sha_type":
            projects[0]["headSha"] = 7
        (tmp_path / "registry.json").write_text(
            json.dumps({"schemaVersion": schema_version, "projects": projects}), encoding="utf-8",
        )
        if bound == "registry_items":
            monkeypatch.setattr(runtime_module, "_MAX_PROJECT_REGISTRY_ITEMS", 1)
        elif bound == "governance_card":
            monkeypatch.setattr(
                github_project_governance_catalog, "governance_metadata",
                lambda _root, _project: {"governanceReview": {"borrowedSlice": "x" * 4_001}},
            )
        else:
            monkeypatch.setattr(
                github_project_governance_catalog, "governance_metadata",
                lambda _root, _project: {},
            )

    agent = {"agentId": "agent-bounded-projects"}
    result = AgentPerceptionRuntime()._load_project_governance_snapshot(agent, _enabled_policy())

    assert result == {"rows": [], "complete": False}


def test_project_governance_snapshot_never_reads_registered_project_source(tmp_path, monkeypatch):
    from pathlib import Path

    from core.web.services import github_project_library_service
    from core.web.services.agent_perception import runtime as runtime_module

    library_root = tmp_path / "github-projects"
    repo_root = library_root / "repos" / "openai__codex"
    source_path = repo_root / "codex-rs" / "core" / "src" / "exec_policy.rs"
    workflow_path = repo_root / ".github" / "workflows" / "rust-ci.yml"
    source_path.parent.mkdir(parents=True)
    workflow_path.parent.mkdir(parents=True)
    source_path.write_text("source-body-must-not-be-read", encoding="utf-8")
    workflow_path.write_text("workflow-body-must-not-be-read", encoding="utf-8")
    (library_root / "registry.json").write_text(json.dumps({
        "schemaVersion": 1,
        "projects": [{
            "projectId": "openai__codex",
            "fullName": "openai/codex",
            "headSha": "536f86e5cc9ec1ff38457d099bf320b9d08eeeba",
            "license": "Apache-2.0",
            "defaultBranch": "main",
            "language": "Rust",
            "status": "ready",
            "hasSubmodules": False,
            "topics": [],
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(github_project_library_service, "github_project_library_root", lambda **_kwargs: library_root)
    original_open = Path.open

    def guarded_open(path, mode="r", *args, **kwargs):
        if library_root.joinpath("repos") in path.resolve().parents and "r" in mode:
            raise AssertionError("project source reads are outside the snapshot boundary")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    result = AgentPerceptionRuntime()._load_project_governance_snapshot(
        {"agentId": "agent-source-boundary"}, _enabled_policy(),
    )

    assert result["complete"] is True
    assert result["rows"][1]["knowledgeItemId"] == "openai__codex"
    assert "source-body-must-not-be-read" not in repr(result)
    assert "workflow-body-must-not-be-read" not in repr(result)


@pytest.mark.parametrize("revocation", ["memory_policy", "visible_acl"])
def test_knowledge_access_revocation_during_scan_discards_entire_batch(tmp_path, monkeypatch, revocation):
    from core.web.services import agent_directory_service
    from core.web.services.agent_perception import service as perception_service

    policy = _enabled_policy(daily_max_runs=0)
    policy["background"]["enabled"] = False
    policy["sources"]["team"].update({"mode": "auto", "teamIds": ["team-1"]})
    policy["sources"]["team"]["triggers"]["update"] = True
    policy = normalize_agent_perception_policy(policy)
    agent = {"agentId": "agent-acl-race", "status": "active", "workspacePath": "workspace/agents/agent-acl-race"}
    memory_policy = {"enabled": True, "readKnowledgeBaseIds": ["team:team-1:base-1"]}
    visible = [{
        "scopedKnowledgeBaseId": "team:team-1:base-1",
        "ownerType": "team",
        "ownerId": "team-1",
        "permissions": {"canRead": True},
    }]
    rows = [{
        "knowledgeBaseId": "team:team-1:base-1",
        "knowledgeItemId": "item-1",
        "sources": ["team"],
        "revision": "2",
        "contentHash": "hash-v2",
    }]
    monkeypatch.setattr(perception_service, "_visible_bases", lambda _agent: deepcopy(visible))
    monkeypatch.setattr(agent_directory_service, "resolve_memory_policy_for_agent", lambda _agent_id: deepcopy(memory_policy))

    store = AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / f"revoked-{revocation}.json")
    runtime = AgentPerceptionRuntime(
        store=store,
        agent_loader=lambda _agent_id: deepcopy(agent),
        policy_loader=lambda _agent: (deepcopy(policy), agent_perception_policy_fingerprint(policy)),
        session_service=_FakeSessions(),
        clock=lambda: "2026-10-05T12:00:00Z",
    )

    def load_snapshot(_agent, _policy):
        if revocation == "memory_policy":
            memory_policy["readKnowledgeBaseIds"] = []
        else:
            visible.clear()
        return {"rows": deepcopy(rows), "complete": True}

    runtime._load_knowledge_snapshot = load_snapshot
    before = store.load(agent)

    result = runtime.scan_knowledge_updates("agent-acl-race")

    assert result == {"basesScanned": 0, "changed": 0, "notified": 0, "suppressed": 0}
    assert store.load(agent) == before


def test_readable_sources_distinguish_task_only_private_base_and_episodic_memory(runtime, monkeypatch):
    service, _store, _sessions, agent, current_policy = runtime
    from core.web.services import agent_directory_service
    from core.web.services.agent_perception import service as perception_service

    policy = current_policy()
    policy["sources"]["personal"].update({
        "mode": "auto",
        "triggers": {"task": True, "update": False, "background": False},
    })
    policy = normalize_agent_perception_policy(policy)
    monkeypatch.setattr(perception_service, "_visible_bases", lambda _agent: [
        {"ownerType": "agent", "ownerId": "agent-test", "scopedKnowledgeBaseId": "agent:agent-test:private"}
    ])
    monkeypatch.setattr(agent_directory_service, "resolve_memory_policy_for_agent", lambda _agent_id: {"enabled": True})
    monkeypatch.setattr(agent_directory_service, "list_current_episodic_events", lambda _agent_id, *, limit: [])

    task_only = next(row for row in service._readable_sources(agent, policy) if row["source"] == "personal")

    assert task_only["selectedCount"] == 1
    assert task_only["readableCount"] == 1
    assert task_only["triggers"] == {"task": True, "update": False, "background": False}

    monkeypatch.setattr(perception_service, "_visible_bases", lambda _agent: [])
    monkeypatch.setattr(agent_directory_service, "list_current_episodic_events", lambda _agent_id, *, limit: [{"eventId": "episode-1"}])

    episodic_only = next(row for row in service._readable_sources(agent, policy) if row["source"] == "personal")

    assert episodic_only["selectedCount"] == 1
    assert episodic_only["readableCount"] == 1
