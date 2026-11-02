"""Reporting retries require proof about the original native turn."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.assistant_runtime import patrol
from core.web.services.session import journal_bridge, proactive
from tests.test_assistant_runtime_patrol import setup, journal_events


@pytest.mark.parametrize("terminal", ["turn_failed", "turn_interrupted"])
def test_report_failure_recovers_after_restart_with_new_token_at_most_twice(setup, monkeypatch, terminal):
    root, row, dispatch = setup
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    calls, journal = [], []
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kw: calls.append(kw) or {"accepted": True})
    monkeypatch.setattr(journal_bridge, "load_session_conversation_events_cached", lambda *a, **kw: journal)
    assert runtime.inspect([row], now=10000)["wake"] == "accepted"
    for attempt in range(3):
        item = runtime._state["entries"][0]
        token = item["token"]
        journal[:] = journal_events(token, item["event"]["eventId"], terminal)
        runtime.close()
        runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
        result = runtime.inspect([row], now=20000 + attempt * 10000)
        if attempt < 2:
            assert result["wake"] == "accepted"
            assert runtime._state["entries"][0]["token"] != token
        else:
            assert result["wake"] == "none"
    assert len(calls) == 3 and len({call["delivery_token"] for call in calls}) == 3
    assert len(runtime._state["entries"]) == 1
    assert len(runtime._state["entries"][0]["history"]) == 2
    assert runtime.delivery_escalations["state"] == "requires_review"
    assert runtime._state["entries"][0]["escalation"] == "recovery_exhausted"


def test_failed_report_with_visible_output_never_repeats_content(setup, monkeypatch):
    root, row, dispatch = setup
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    calls = []
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kw: calls.append(kw) or {"accepted": True})
    runtime.inspect([row], now=10000)
    item = runtime._state["entries"][0]
    events = journal_events(item["token"], item["event"]["eventId"], "turn_failed", True)
    monkeypatch.setattr(journal_bridge, "load_session_conversation_events_cached", lambda *a, **kw: events)
    assert runtime.inspect([row], now=20000)["wake"] == "none"
    runtime.close()
    reopened = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    assert reopened.inspect([row], now=30000)["wake"] == "none"
    assert len(calls) == 1
    assert reopened._state["entries"][0]["escalation"] == "delivery_already_visible"


def test_unknown_delivery_has_persistent_safe_escalation_without_replaying(setup, monkeypatch):
    root, row, dispatch = setup
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    calls = []

    def uncertain(**kw):
        calls.append(kw)
        raise RuntimeError("acceptance was lost")

    monkeypatch.setattr(proactive, "submit_session_proactive_turn", uncertain)
    assert runtime.inspect([row], now=10000)["wake"] == "unknown"
    token = calls[0]["delivery_token"]
    runtime.close()
    reopened = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    assert reopened.inspect([row], now=20000)["wake"] == "none"
    assert reopened._state["entries"][0]["token"] == token
    assert reopened.delivery_escalations["unresolved"] == 1
    assert "不会重放" in reopened.delivery_escalations["notice"]
    assert len(calls) == 1
    dispatch.enabled = False
    assert reopened.delivery_escalations == {"state": "clear", "unresolved": 0, "notice": ""}
    assert not any(reopened.reconcile().values())


def test_recovery_waits_for_both_proactive_context_and_native_scheduler_release(setup, monkeypatch):
    from core.web.services import session_service as sessions
    root, row, dispatch = setup
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    calls = []
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kw: calls.append(kw) or {"accepted": True})
    runtime.inspect([row], now=10000)
    item = runtime._state["entries"][0]
    token = item["token"]
    events = journal_events(token, item["event"]["eventId"], "turn_failed")
    monkeypatch.setattr(journal_bridge, "load_session_conversation_events_cached", lambda *a, **kw: events)
    with proactive._PROACTIVE_CONTEXTS_LOCK:
        proactive._PROACTIVE_CONTEXTS[token] = {"turn_id": "turn-1"}
    try:
        assert runtime.inspect([row], now=20000)["wake"] == "none"
    finally:
        with proactive._PROACTIVE_CONTEXTS_LOCK:
            proactive._PROACTIVE_CONTEXTS.pop(token, None)
    scheduler = sessions._SESSION_TURN_SCHEDULER
    with scheduler._condition:
        scheduler._active_turn_ids_by_session["recovery-test-session"] = "turn-1"
    try:
        assert runtime.inspect([row], now=20001)["wake"] == "none"
    finally:
        with scheduler._condition:
            scheduler._active_turn_ids_by_session.pop("recovery-test-session", None)
    assert runtime.inspect([row], now=20002)["wake"] == "accepted"
    assert len(calls) == 2


def test_schema_one_terminal_failure_uses_original_journal_before_migration(setup, monkeypatch):
    root, row, dispatch = setup
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kw: {"accepted": True})
    runtime.inspect([row], now=10000)
    item = runtime._state["entries"][0]
    original_token = item["token"]
    journal = journal_events(original_token, item["event"]["eventId"], "turn_failed")
    legacy = json.loads(runtime._path.read_text(encoding="utf-8"))
    legacy["schemaVersion"] = 1
    legacy["entries"][0]["state"] = "failed"
    legacy["entries"][0].pop("projectBinding", None)
    runtime._path.write_text(json.dumps(legacy), encoding="utf-8")
    runtime.close()
    monkeypatch.setattr(journal_bridge, "load_session_conversation_events_cached", lambda *a, **kw: journal)
    reopened = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    assert reopened.inspect([row], now=20000)["wake"] == "accepted"
    assert reopened._state["entries"][0]["history"][0]["token"] == original_token
    assert json.loads(reopened._path.read_text(encoding="utf-8"))["schemaVersion"] == 2
    assert not list(reopened._path.parent.glob("*recovery*"))


def test_same_registration_rebound_to_another_root_hides_old_delivery_metadata(setup, monkeypatch):
    root, row, dispatch = setup
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kw: {"accepted": True})
    runtime.inspect([row], now=10000)
    runtime.reconcile()
    assert runtime.delivery_escalations["unresolved"] == 1
    dispatch._admitted_projects = lambda: {"project-a": str(root / "another-target")}
    assert runtime.delivery_escalations["unresolved"] == 0
    assert not any(runtime.reconcile().values())
    assert runtime.inspect([row], now=20000)["wake"] == "none"


@pytest.mark.parametrize("kind,payload", [
    ("assistant_delta_committed", {"content": "partial visible report"}),
    ("assistant_item_committed", {"kind": "assistant_message", "channel": "answer", "phase": "commentary", "text": "partial visible report"}),
])
def test_partial_visible_output_also_prevents_automatic_repeat(setup, monkeypatch, kind, payload):
    root, row, dispatch = setup
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    calls = []
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kw: calls.append(kw) or {"accepted": True})
    runtime.inspect([row], now=10000)
    item = runtime._state["entries"][0]
    journal = journal_events(item["token"], item["event"]["eventId"], "turn_failed")
    journal.insert(2, SimpleNamespace(event_type=kind, turn_id="turn-1", correlation_id="", payload=payload, visible_in_model=True))
    monkeypatch.setattr(journal_bridge, "load_session_conversation_events_cached", lambda *a, **kw: journal)
    assert runtime.inspect([row], now=20000)["wake"] == "none"
    assert len(calls) == 1
    assert item["visibleReport"] is True and item["escalation"] == "delivery_already_visible"
