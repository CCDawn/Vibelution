from __future__ import annotations

import asyncio
from contextlib import contextmanager
from threading import Event, RLock
from types import SimpleNamespace

import pytest

from core.assistant_runtime import native, patrol
from core.agent_plugins.personal_assistant_dialogue import PERSONAL_ASSISTANT_DIALOGUE_RUNTIME_EXTENSION as extension
from core.infrastructure import native_runtime
from core.web.services.session import proactive, queued_turns, journal_bridge


def journal_events(token, event_id, terminal=None, visible=False):
    def event(kind, *, correlation="", payload=None, shown=False):
        return SimpleNamespace(event_type=kind, correlation_id=correlation, turn_id="turn-1",
                               payload=payload or {}, visible_in_model=shown, source_kind="personal-assistant-dialogue")
    result = [event("turn_started", correlation=token, payload={"agentId": "pa", "pluginId": "personal-assistant-dialogue"}),
        event("internal_turn_trigger", correlation=token, payload={"agentId": "pa", "bindingRevision": 1,
        "deliveryKind": "launcher_dispatch_receipt", "pluginId": "personal-assistant-dialogue",
        "triggerId": event_id, "deliveryToken": token})]
    if visible:
        result.append(event("assistant_message", payload={"content": "已汇报"}, shown=True))
    if terminal:
        result.append(event(terminal))
    return result


class Dispatch:
    def __init__(self, row):
        self.row = row
        self._dispatch_state = RLock()
        self.enabled = True

    def _admitted_projects(self):
        return {"project-a": "root"} if self.enabled else {}

    def _check_dispatch_unfenced(self):
        pass

    def list_dispatches(self, project_id):
        return [self.row]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    row = {"projectId": "project-a", "dispatchId": "dispatch-1", "nativeTaskId": "task-1",
           "lastError": None, "receipt": {"taskId": "task-1", "status": "succeeded"}}
    dispatch = Dispatch(row)
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    monkeypatch.setattr(native_runtime, "assistant_native_root", lambda: tmp_path)
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_OFFLINE_MIGRATION", False)
    monkeypatch.setattr(native, "_QUIESCING", False)
    monkeypatch.setattr(native, "_AGENT_ID", "pa")
    monkeypatch.setattr(native, "_SESSION_ID", "session")
    monkeypatch.setattr(native, "_projection", lambda: {"assistant": {"agentId": "pa", "directSessionId": "session"}})
    monkeypatch.setattr(native, "_STOP_REQUESTED", Event())
    monkeypatch.setattr(queued_turns, "session_queue_hold_active", lambda _: False)
    monkeypatch.setattr(journal_bridge, "load_session_conversation_events_cached", lambda *a, **kw: [])
    monkeypatch.delenv("VIBELUTION_PA_PATROL", raising=False)
    monkeypatch.delenv("VIBELUTION_PA_PATROL_WAKE", raising=False)

    @contextmanager
    def session_command():
        yield None, "session"

    monkeypatch.setattr(native, "_session_command", session_command)
    yield tmp_path, row, dispatch
    if patrol.owner() is not None:
        patrol.owner().close()


def test_receipt_is_persisted_before_native_wake_and_prompt_is_scoped(setup, monkeypatch):
    root, row, dispatch = setup
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    calls = []

    def submit(**kwargs):
        entry = runtime._state["entries"][0]
        assert entry["state"] == "reserved"
        assert entry["token"] in runtime._path.read_text(encoding="utf-8")
        assert extension.proactive_turn_is_current(agent_id="pa", binding_revision=1,
                                                   delivery_token=entry["token"])
        context = {"turn_id": "turn-1", "agent_id": "pa", "session_id": "session", "origin": "proactive_plugin",
                   "proactive_plugin": {"deliveryToken": entry["token"], "bindingRevision": 1,
                     "pluginId": "personal-assistant-dialogue", "sourceKind": "personal-assistant-dialogue",
                     "triggerId": entry["event"]["eventId"]}}
        with proactive._PROACTIVE_CONTEXTS_LOCK:
            proactive._PROACTIVE_CONTEXTS[entry["token"]] = context
        block = runtime.prompt("pa", "session", "turn-1")
        assert "dispatch_id=dispatch-1" in block
        assert "不要重派" in block
        assert runtime.prompt("other", "session", "turn-1") == ""
        calls.append(kwargs)
        return {"accepted": True, "turnId": "turn-1"}

    monkeypatch.setattr(proactive, "submit_session_proactive_turn", submit)
    assert runtime.inspect([row], now=10000)["wake"] == "accepted"
    assert runtime.inspect([row], now=20000)["wake"] == "none"
    assert len(calls) == 1
    item = runtime._state["entries"][0]
    monkeypatch.setattr(journal_bridge, "load_session_conversation_events_cached", lambda *a, **kw:
                        journal_events(item["token"], item["event"]["eventId"], "turn_completed", True))
    extension.finalize_proactive_delivery({"agent_id": "pa", "session_id": "session", "origin": "proactive_plugin",
        "proactive_plugin": {"deliveryToken": item["token"], "pluginId": "personal-assistant-dialogue",
                             "sourceKind": "personal-assistant-dialogue", "triggerId": item["event"]["eventId"]}})
    assert item["state"] == "completed"
    with proactive._PROACTIVE_CONTEXTS_LOCK:
        proactive._PROACTIVE_CONTEXTS.pop(item["token"], None)


def test_unknown_submission_is_reconciled_by_original_token_without_replay(setup, monkeypatch):
    root, row, dispatch = setup
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    calls = []

    def uncertain(**kwargs):
        calls.append(kwargs["delivery_token"])
        raise RuntimeError("lost reply")

    monkeypatch.setattr(proactive, "submit_session_proactive_turn", uncertain)
    assert runtime.inspect([row], now=10000)["wake"] == "unknown"
    runtime.close()
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    item = runtime._state["entries"][0]
    monkeypatch.setattr(journal_bridge, "load_session_conversation_events_cached",
                        lambda *a, **kw: journal_events(calls[0], item["event"]["eventId"]))
    assert runtime.reconcile()["observed"] == 1
    assert runtime.inspect([row], now=30000)["wake"] == "none"
    assert len(calls) == 1


def test_paused_session_or_revoked_project_never_schedules(setup, monkeypatch):
    root, row, dispatch = setup
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    monkeypatch.setattr(queued_turns, "session_queue_hold_active", lambda _: True)
    assert runtime.inspect([row], now=10000)["wake"] == "none"
    monkeypatch.setattr(queued_turns, "session_queue_hold_active", lambda _: False)
    dispatch.enabled = False
    assert runtime.inspect([row], now=10000)["wake"] == "none"
    assert runtime._state["entries"] == []


def test_pre_admission_cancel_resumes_same_token_only_after_context_exits(setup, monkeypatch):
    root, row, dispatch = setup
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    calls = []

    def submit(**kwargs):
        token = kwargs["delivery_token"]
        calls.append(token)
        with proactive._PROACTIVE_CONTEXTS_LOCK:
            proactive._PROACTIVE_CONTEXTS[token] = {"_proactive_admitted": False, "turn_id": "cancelled-turn"}
        return {"accepted": True}

    monkeypatch.setattr(proactive, "submit_session_proactive_turn", submit)
    assert runtime.inspect([row], now=10000)["wake"] == "accepted"
    token = calls[0]
    monkeypatch.setenv("VIBELUTION_PA_PATROL_WAKE", "0")
    assert not extension.proactive_turn_is_current(agent_id="pa", binding_revision=1, delivery_token=token)
    extension.cancel_proactive_attempt(agent_id="pa", delivery_token=token, reason="fenced")
    monkeypatch.delenv("VIBELUTION_PA_PATROL_WAKE")
    assert runtime.inspect([row], now=12000)["wake"] == "none"
    assert calls == [token]  # cancellation callback has not released the old context
    with proactive._PROACTIVE_CONTEXTS_LOCK:
        proactive._PROACTIVE_CONTEXTS.pop(token)
    from core.web.services import session_service as sessions
    scheduler = sessions._SESSION_TURN_SCHEDULER
    with scheduler._condition:
        scheduler._active_turn_ids_by_session["session:session"] = "cancelled-turn"
    try:
        assert runtime.inspect([row], now=12001)["wake"] == "none"
    finally:
        with scheduler._condition:
            scheduler._active_turn_ids_by_session.pop("session:session", None)
    assert runtime.inspect([row], now=12002)["wake"] == "accepted"
    assert calls == [token, token]
    with proactive._PROACTIVE_CONTEXTS_LOCK:
        proactive._PROACTIVE_CONTEXTS.pop(token, None)


@pytest.mark.parametrize("gate", ["hold", "switch", "registry"])
def test_native_precheck_gate_race_retries_original_token(setup, monkeypatch, gate):
    root, row, dispatch = setup
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    original_current = runtime.current
    count = 0

    def current(agent, revision, token):
        nonlocal count
        count += 1
        if count == 2:
            if gate == "hold":
                monkeypatch.setattr(queued_turns, "session_queue_hold_active", lambda _: True)
            elif gate == "switch":
                monkeypatch.setenv("VIBELUTION_PA_PATROL_WAKE", "0")
            else:
                dispatch.enabled = False
        return original_current(agent, revision, token)

    monkeypatch.setattr(runtime, "current", current)
    assert runtime.inspect([row], now=10000)["wake"] == "deferred"
    item = runtime._state["entries"][0]
    assert item["state"] == "cancelled_pre_admission" and item["cancelProof"] == "not_submitted"
    token = item["token"]
    monkeypatch.setattr(queued_turns, "session_queue_hold_active", lambda _: False)
    monkeypatch.delenv("VIBELUTION_PA_PATROL_WAKE", raising=False)
    dispatch.enabled = True
    submitted = []
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kwargs:
                        submitted.append(kwargs["delivery_token"]) or {"accepted": True})
    assert runtime.inspect([row], now=12000)["wake"] == "accepted"
    assert submitted == [token]


def test_native_precheck_contradictory_journal_stays_unknown(setup, monkeypatch):
    root, row, dispatch = setup
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    original_current = runtime.current
    tokens = []

    def current(agent, revision, token):
        tokens.append(token)
        return False if len(tokens) == 2 else original_current(agent, revision, token)

    monkeypatch.setattr(runtime, "current", current)
    monkeypatch.setattr(journal_bridge, "load_session_conversation_events_cached", lambda *a, **kw:
                        [SimpleNamespace(correlation_id=tokens[-1], event_type="turn_started", turn_id="turn-1")])
    assert runtime.inspect([row], now=10000)["wake"] == "unknown"
    assert runtime._state["entries"][0]["state"] == "unknown"


def test_similar_exception_after_context_registration_stays_unknown(setup, monkeypatch):
    from core.web.services import session_service as sessions
    root, row, dispatch = setup
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)

    def failed_scheduled_event(context):
        raise sessions.SessionValidationError("The proactive trigger is stale or no longer authorized.")

    monkeypatch.setattr(sessions, "_record_session_turn_scheduled_event", failed_scheduled_event)
    assert runtime.inspect([row], now=10000)["wake"] == "unknown"
    item = runtime._state["entries"][0]
    assert item["state"] == "unknown"
    with proactive._PROACTIVE_CONTEXTS_LOCK:
        proactive._PROACTIVE_CONTEXTS.pop(item["token"], None)


def test_terminal_failure_and_completed_without_visible_message_are_not_success(setup, monkeypatch):
    root, row, dispatch = setup
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kwargs: {"accepted": True})
    runtime.inspect([row], now=10000)
    item = runtime._state["entries"][0]
    token, event_id = item["token"], item["event"]["eventId"]
    monkeypatch.setattr(journal_bridge, "load_session_conversation_events_cached", lambda *a, **kw:
                        journal_events(token, event_id, "turn_failed"))
    assert runtime.reconcile()["failed"] == 1
    assert token not in runtime._active
    assert runtime.inspect([row], now=20000)["wake"] == "none"
    item["state"] = "unknown"
    monkeypatch.setattr(journal_bridge, "load_session_conversation_events_cached", lambda *a, **kw:
                        journal_events(token, event_id, "turn_completed", False))
    assert runtime.reconcile()["unknown"] == 1


def test_ledger_segments_allow_new_receipts_after_segment_fills(setup, monkeypatch):
    root, row, dispatch = setup
    monkeypatch.setattr(patrol, "_MAX_ENTRIES", 2)
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kwargs: {"accepted": True})
    for index in range(3):
        dispatch.row = {**row, "dispatchId": f"dispatch-{index}"}
        assert runtime.inspect([dispatch.row], now=10000 + index * 4000)["wake"] == "accepted"
    assert len(runtime._state["entries"]) == 3
    assert (root / "assistant_patrol" / "deliveries.00000001.json").is_file()
    runtime.close()
    reopened = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    assert len(reopened._state["entries"]) == 3


def test_error_marked_terminal_is_rechecked_via_original_native_task(setup, monkeypatch):
    from core.assistant_runtime.dispatch import DispatchError
    from tests.test_assistant_runtime_dispatch import ClientProbe, adapter, start
    root, _, _ = setup
    probe = ClientProbe()
    service = adapter(root, probe)
    runtime = patrol.LauncherPatrol(root, "pa", "session", service)
    submitted = []
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kwargs:
                        submitted.append(kwargs["trigger_id"]) or {"accepted": True})

    async def exercise():
        await start(service)
        await service.reconcile("dispatch-1")
        probe.get_error = True
        with pytest.raises(DispatchError):
            await service.reconcile("dispatch-1")
        rows = service.list_dispatches()
        assert rows[0]["receipt"]["status"] == "succeeded" and rows[0]["lastError"]
        assert await service.heartbeat() == []
        assert runtime.inspect(rows, now=10000)["wake"] == "none"
        assert (await runtime.refresh_stale_terminals(rows, now=100))["attempted"] == 1
        assert runtime.inspect(service.list_dispatches(), now=12000)["wake"] == "none"
        assert (await runtime.refresh_stale_terminals(rows, now=101))["attempted"] == 0
        probe.get_error = False
        before = len(probe.calls)
        assert (await runtime.refresh_stale_terminals(rows, now=161))["attempted"] == 1
        names = [name for name, _ in probe.calls[before:]]
        assert names == ["diagnostics", "get"]
        fresh = service.list_dispatches()
        assert fresh[0]["lastError"] is None and fresh[0]["receipt"]["taskId"] == "eat-1"
        assert runtime.inspect(fresh, now=12001)["wake"] == "accepted"
        assert len(submitted) == 1
        assert [name for name, _ in probe.calls].count("start") == 1
        assert not {"cancel", "shutdown"}.intersection(name for name, _ in probe.calls)

    asyncio.run(exercise())


def test_terminal_recheck_rejects_identity_mismatch_and_suspended_registry(setup):
    from core.assistant_runtime.dispatch import DispatchError
    from tests.test_assistant_runtime_dispatch import ClientProbe, adapter, start
    root, _, _ = setup
    probe = ClientProbe()
    service = adapter(root, probe)
    runtime = patrol.LauncherPatrol(root, "pa", "session", service)

    async def exercise():
        await start(service)
        await service.reconcile("dispatch-1")
        probe.get_error = True
        with pytest.raises(DispatchError):
            await service.reconcile("dispatch-1")
        stale = service.list_dispatches()
        probe.get_error = False

        def wrong_factory(*args, **kwargs):
            client = probe.factory(*args, **kwargs)
            async def wrong_get(**_kwargs):
                return {"taskId": "different-task", "status": "succeeded"}
            client.get_task = wrong_get
            return client

        service._client_factory = wrong_factory
        assert (await runtime.refresh_stale_terminals(stale, now=100))["attempted"] == 1
        rows = service.list_dispatches()
        assert rows[0]["receipt"]["taskId"] == "eat-1"
        assert rows[0]["lastError"]["code"] == "BACKEND_PROTOCOL_ERROR"
        assert runtime.inspect(rows, now=10000)["wake"] == "none"
        service.suspend_projects()
        before = len(probe.calls)
        with pytest.raises(DispatchError):
            await runtime.refresh_stale_terminals(rows, now=161)
        assert len(probe.calls) == before

    asyncio.run(exercise())


@pytest.mark.parametrize("resume", [False, True])
def test_terminal_recheck_revalidates_registry_after_diagnostics(setup, resume):
    from core.assistant_runtime.dispatch import DispatchError
    from tests.test_assistant_runtime_dispatch import ClientProbe, adapter, start
    root, _, _ = setup
    (root / "project").mkdir()
    probe = ClientProbe()
    service = adapter(root, probe)
    runtime = patrol.LauncherPatrol(root, "pa", "session", service)

    async def exercise():
        await start(service)
        await service.reconcile("dispatch-1")
        probe.get_error = True
        with pytest.raises(DispatchError):
            await service.reconcile("dispatch-1")
        stale = service.list_dispatches()
        probe.get_error = False
        entered, resume_diagnostics = asyncio.Event(), asyncio.Event()

        def delayed_factory(*args, **kwargs):
            client = probe.factory(*args, **kwargs)
            original = client.diagnostics
            async def diagnostics():
                entered.set()
                await resume_diagnostics.wait()
                return await original()
            client.diagnostics = diagnostics
            return client

        service._client_factory = delayed_factory
        before = len(probe.calls)
        task = asyncio.create_task(runtime.refresh_stale_terminals(stale, now=100))
        await entered.wait()
        service.suspend_projects()
        if resume:
            service.replace_projects({"schemaVersion": 1, "revision": 1,
                                      "projects": {"project-a": str(root / "project")}})
        resume_diagnostics.set()
        assert (await task)["attempted"] == 1
        assert [name for name, _ in probe.calls[before:]] == ["diagnostics"]
        row = service.list_dispatches()[0]
        assert row["lastError"]["code"] == "PROJECT_REGISTRY_RECONCILE_REQUIRED"
        assert runtime.inspect([row], now=10000)["wake"] == "none"

    asyncio.run(exercise())


def test_terminal_read_admitted_before_suspend_can_settle(setup):
    from core.assistant_runtime.dispatch import DispatchError
    from tests.test_assistant_runtime_dispatch import ClientProbe, adapter, start
    root, _, _ = setup
    probe = ClientProbe()
    service = adapter(root, probe)
    runtime = patrol.LauncherPatrol(root, "pa", "session", service)

    async def exercise():
        await start(service)
        await service.reconcile("dispatch-1")
        probe.get_error = True
        with pytest.raises(DispatchError):
            await service.reconcile("dispatch-1")
        stale = service.list_dispatches()
        probe.get_error = False
        entered, settle = asyncio.Event(), asyncio.Event()

        def delayed_factory(*args, **kwargs):
            client = probe.factory(*args, **kwargs)
            original = client.get_task
            async def get_task(**kwargs):
                entered.set()
                await settle.wait()
                return await original(**kwargs)
            client.get_task = get_task
            return client

        service._client_factory = delayed_factory
        task = asyncio.create_task(runtime.refresh_stale_terminals(stale, now=100))
        await entered.wait()
        service.suspend_projects()
        settle.set()
        assert (await task)["attempted"] == 1
        result = service.list_dispatches()[0]
        assert result["lastError"] is None and result["receipt"]["taskId"] == "eat-1"
        assert runtime.inspect([result], now=10000)["wake"] == "none"
        assert [name for name, _ in probe.calls].count("start") == 1

    asyncio.run(exercise())


def test_real_native_proactive_admission_in_isolated_process(tmp_path):
    from tests.test_assistant_runtime_native import _run, TEST_MODEL_CONFIG

    _run(tmp_path, r'''
        import os
        from pathlib import Path
        from threading import RLock
        from core.assistant_runtime import native
        from core.assistant_runtime.patrol import LauncherPatrol
        from core.agent_plugins.personal_assistant_dialogue import PERSONAL_ASSISTANT_DIALOGUE_RUNTIME_EXTENSION as extension
        from core.web.services import session_service as sessions
        from core.web.services.session import proactive
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        row = {'projectId': 'project-a', 'dispatchId': 'dispatch-1', 'nativeTaskId': 'task-1',
               'lastError': None, 'receipt': {'taskId': 'task-1', 'status': 'succeeded'}}
        class Dispatch:
            _dispatch_state = RLock()
            def _check_dispatch_unfenced(self): pass
            def _admitted_projects(self): return {'project-a': root}
            def list_dispatches(self, project_id): return [row]
        result = native.bootstrap(root)
        agent, sid = result['assistant']['agentId'], result['assistant']['directSessionId']
        runtime = LauncherPatrol(root, agent, sid, Dispatch())
        scheduled = []
        sessions._schedule_session_turn = lambda context: scheduled.append(context)
        try:
            assert runtime.inspect([row], now=10000)['wake'] == 'accepted'
            assert len(scheduled) == 1
            context = scheduled[0]
            assert context['origin'] == 'proactive_plugin'
            sessions._set_session_running(sid, True, turn_id='busy-turn')
            assert proactive.admit_session_proactive_turn(context) == 'defer'
            sessions._set_session_running(sid, False, turn_id='busy-turn')
            assert proactive.admit_session_proactive_turn(context) == 'admitted'
            segment = extension.build_prompt_segments(agent, session_id=sid, run_id=context['turn_id'])
            assert any('dispatch_id=dispatch-1' in item['block'] for item in segment)
            messages = native.get_detail(sid)['messages']
            assert not any(item.get('role') == 'user' for item in messages)
            proactive.cancel_proactive_turn_context(context, reason='test_finished')
        finally:
            runtime.close()
            native.shutdown()
    ''', config_text=TEST_MODEL_CONFIG)


def test_real_native_hold_and_restart_reconcile_use_original_journal_token(tmp_path):
    from tests.test_assistant_runtime_native import _run, TEST_MODEL_CONFIG

    common = r'''
from pathlib import Path
from threading import RLock
import os
from core.assistant_runtime import native
from core.assistant_runtime.patrol import LauncherPatrol
from core.web.services import session_service as sessions
from core.web.services.session import proactive, queued_turns
root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
row = {'projectId': 'project-a', 'dispatchId': 'dispatch-1', 'nativeTaskId': 'task-1',
       'lastError': None, 'receipt': {'taskId': 'task-1', 'status': 'succeeded'}}
class Dispatch:
    _dispatch_state = RLock()
    def _check_dispatch_unfenced(self): pass
    def _admitted_projects(self): return {'project-a': root}
    def list_dispatches(self, project_id): return [row]
'''
    _run(tmp_path, common + r'''
result = native.bootstrap(root)
agent, sid = result['assistant']['agentId'], result['assistant']['directSessionId']
runtime = LauncherPatrol(root, agent, sid, Dispatch())
scheduled = []
sessions._schedule_session_turn = lambda context: scheduled.append(context)
queued_turns.set_session_queue_hold(sid, turn_id='user-stopped')
assert runtime.inspect([row], now=10000)['wake'] == 'none'
assert queued_turns.session_queue_hold_active(sid) and not scheduled
with sessions._CHAT_STATE_LOCK:
    conversation = sessions.load_session_chat_state(root, sid)
    assert queued_turns.clear_session_queue_hold_in_conversation(conversation, sessions)
    sessions.save_session_chat_state(root, sid, conversation)
assert runtime.inspect([row], now=10000)['wake'] == 'accepted'
context = scheduled[0]
assert proactive.admit_session_proactive_turn(context) == 'admitted'
assert context['proactive_plugin']['deliveryToken'] == runtime._state['entries'][0]['token']
os._exit(0)
''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, common + r'''
sessions._schedule_session_turn = lambda context: None
result = native.bootstrap(root)
agent, sid = result['assistant']['agentId'], result['assistant']['directSessionId']
runtime = LauncherPatrol(root, agent, sid, Dispatch())
try:
    token = runtime._state['entries'][0]['token']
    assert runtime.reconcile()['observed'] == 1
    assert runtime._state['entries'][0]['token'] == token
    events = sessions._load_session_conversation_events_cached(sid)
    trigger = next(e for e in events if e.event_type == 'internal_turn_trigger' and e.correlation_id == token)
    sessions._append_session_conversation_event(sid, trigger.turn_id, sessions.EVENT_TURN_FAILED,
        status='failed', payload={'errorType': 'synthetic_failure'}, source='test')
    assert runtime.reconcile()['failed'] == 1
    assert runtime.inspect([row], now=20000)['wake'] == 'none'
finally:
    runtime.close()
    native.shutdown()
''', config_text=TEST_MODEL_CONFIG)


def test_real_pre_admission_hold_cancellation_can_resume_same_token(tmp_path):
    from tests.test_assistant_runtime_native import _run, TEST_MODEL_CONFIG

    _run(tmp_path, r'''
        import os
        from pathlib import Path
        from threading import RLock
        from core.assistant_runtime import native
        from core.assistant_runtime.patrol import LauncherPatrol
        from core.web.services import session_service as sessions
        from core.web.services.session import proactive, queued_turns
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        row = {'projectId': 'project-a', 'dispatchId': 'dispatch-1', 'nativeTaskId': 'task-1',
               'lastError': None, 'receipt': {'taskId': 'task-1', 'status': 'succeeded'}}
        class Dispatch:
            _dispatch_state = RLock()
            def _check_dispatch_unfenced(self): pass
            def _admitted_projects(self): return {'project-a': root}
            def list_dispatches(self, project_id): return [row]
        result = native.bootstrap(root)
        agent, sid = result['assistant']['agentId'], result['assistant']['directSessionId']
        runtime = LauncherPatrol(root, agent, sid, Dispatch())
        scheduled = []
        sessions._schedule_session_turn = lambda context: scheduled.append(context)
        try:
            assert runtime.inspect([row], now=10000)['wake'] == 'accepted'
            first = scheduled[0]
            token = first['proactive_plugin']['deliveryToken']
            queued_turns.set_session_queue_hold(sid, turn_id='user-stopped')
            assert proactive.admit_session_proactive_turn(first) == 'cancelled'
            assert runtime._state['entries'][0]['state'] == 'cancelled_pre_admission'
            assert runtime.inspect([row], now=12000)['wake'] == 'none'
            assert queued_turns.session_queue_hold_active(sid)
            with sessions._CHAT_STATE_LOCK:
                conversation = sessions.load_session_chat_state(root, sid)
                queued_turns.clear_session_queue_hold_in_conversation(conversation, sessions)
                sessions.save_session_chat_state(root, sid, conversation)
            assert runtime.inspect([row], now=12001)['wake'] == 'accepted'
            assert scheduled[1]['proactive_plugin']['deliveryToken'] == token
            os.environ['VIBELUTION_PA_PATROL_WAKE'] = '0'
            assert proactive.admit_session_proactive_turn(scheduled[1]) == 'cancelled'
            assert runtime.inspect([row], now=14000)['wake'] == 'none'
            del os.environ['VIBELUTION_PA_PATROL_WAKE']
            assert runtime.inspect([row], now=14001)['wake'] == 'accepted'
            assert scheduled[2]['proactive_plugin']['deliveryToken'] == token
            proactive.cancel_proactive_turn_context(scheduled[2], reason='test_finished')
        finally:
            runtime.close()
            native.shutdown()
    ''', config_text=TEST_MODEL_CONFIG)


def test_real_native_precheck_hold_race_preserves_original_token(tmp_path):
    from tests.test_assistant_runtime_native import _run, TEST_MODEL_CONFIG

    _run(tmp_path, r'''
        import os
        from pathlib import Path
        from threading import RLock
        from core.assistant_runtime import native
        from core.assistant_runtime.patrol import LauncherPatrol
        from core.web.services import session_service as sessions
        from core.web.services.session import proactive, queued_turns
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        row = {'projectId': 'project-a', 'dispatchId': 'dispatch-1', 'nativeTaskId': 'task-1',
               'lastError': None, 'receipt': {'taskId': 'task-1', 'status': 'succeeded'}}
        class Dispatch:
            _dispatch_state = RLock()
            def _check_dispatch_unfenced(self): pass
            def _admitted_projects(self): return {'project-a': root}
            def list_dispatches(self, project_id): return [row]
        result = native.bootstrap(root)
        agent, sid = result['assistant']['agentId'], result['assistant']['directSessionId']
        runtime = LauncherPatrol(root, agent, sid, Dispatch())
        scheduled = []
        sessions._schedule_session_turn = lambda context: scheduled.append(context)
        original = runtime.current
        calls = []
        def race(agent_id, revision, token):
            calls.append(token)
            if len(calls) == 2:
                queued_turns.set_session_queue_hold(sid, turn_id='user-stopped')
            return original(agent_id, revision, token)
        runtime.current = race
        try:
            assert runtime.inspect([row], now=10000)['wake'] == 'deferred'
            token = runtime._state['entries'][0]['token']
            assert runtime._state['entries'][0]['state'] == 'cancelled_pre_admission'
            assert queued_turns.session_queue_hold_active(sid) and not scheduled
            with sessions._CHAT_STATE_LOCK:
                conversation = sessions.load_session_chat_state(root, sid)
                queued_turns.clear_session_queue_hold_in_conversation(conversation, sessions)
                sessions.save_session_chat_state(root, sid, conversation)
            assert runtime.inspect([row], now=12000)['wake'] == 'accepted'
            assert scheduled[0]['proactive_plugin']['deliveryToken'] == token
            proactive.cancel_proactive_turn_context(scheduled[0], reason='test_finished')
        finally:
            runtime.close()
            native.shutdown()
    ''', config_text=TEST_MODEL_CONFIG)
