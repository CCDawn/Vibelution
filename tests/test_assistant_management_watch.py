"""Original management refs join patrol without replaying any mutation."""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import pytest

from core.assistant_runtime import patrol, runtime_watch
from core.assistant_runtime.management import ManagementAdapter
from core.web.services.session import proactive
from tests.test_assistant_platform_watch import Management, operation
from tests.test_assistant_runtime_patrol import setup as dispatch_setup


class Remote:
    def __init__(self):
        self.metadata = Management()
        self.states, self.calls = {}, []
        self.after_read = None

    async def management_runtime(self, mode, **query):
        self.calls.append(("runtime", mode, deepcopy(query)))
        return await self.metadata.runtime("project-a", mode, **query)

    async def management_receipt(self, *, action, request_id):
        self.calls.append(("receipt", action, request_id))
        item = self.states[action, request_id]
        if item.get("hang"):
            await asyncio.Event().wait()
        if item.get("fail"):
            raise OSError("SECRET remote failure")
        result = {"action": action, "requestId": request_id, "status": item["receipt"],
                  "verified": item["receipt"] == "completed", "reused": True}
        if item.get("command"):
            result["operation"] = deepcopy(item["command"])
        if self.after_read:
            self.after_read("receipt")
        return result

    async def management_reconciliation(self, *, action, request_id):
        self.calls.append(("reconciliation", action, request_id))
        item = self.states[action, request_id]
        state = item["proof"]
        if item.get("confirm_receipt"):
            item["receipt"] = "completed"
        if self.after_read:
            self.after_read("reconciliation")
        return {"action": action, "requestId": request_id, "state": state,
                "evidence": "native_outcome" if state == "confirmed" else "none",
                "code": {"confirmed": "NATIVE_OUTCOME_CONFIRMED", "requires_review": "NATIVE_OUTCOME_REQUIRES_REVIEW",
                         "unavailable": "NATIVE_OUTCOME_UNAVAILABLE"}[state],
                "verified": state == "confirmed", "requiresReview": state != "confirmed",
                "target": {"agent_id": "PRIVATE-target-metadata"}, "untrustedContent": True}


@pytest.fixture
def watch(dispatch_setup, monkeypatch):
    root, _, dispatch = dispatch_setup
    remote = Remote()
    dispatch.project_ids = lambda: ("project-a",) if dispatch.enabled else ()
    dispatch._project_read_binding = lambda project: (1, root) if dispatch.enabled else (_ for _ in ()).throw(ValueError("revoked"))

    async def call(project, callback):
        assert project == "project-a" and dispatch.enabled
        return await callback(remote)

    adapter = ManagementAdapter(root, lambda: {"project-a": root} if dispatch.enabled else {}, call,
                                read_binding=dispatch._project_read_binding)
    adapter._root.mkdir()
    dispatch.management = adapter
    monkeypatch.setattr(runtime_watch, "_CALLS", len(runtime_watch.KINDS) + 1)
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)

    def add(action="team_update", request="asset-original", **state):
        ref = {"projectId": "project-a", "action": action, "requestId": request}
        path = adapter._root / (adapter._key("project-a", action, request) + ".json")
        path.write_text(json.dumps({"schemaVersion": 1, "fingerprint": "a" * 64, "reference": ref}), encoding="utf-8")
        remote.states[action, request] = {"receipt": "unknown", "proof": "requires_review", **state}
        return ref

    return root, dispatch, remote, runtime, add


def refresh(runtime, now):
    return asyncio.run(runtime._runtime.refresh(now=now))


def install_context(runtime, monkeypatch):
    calls = []

    def submit(**kwargs):
        calls.append(kwargs)
        item = runtime._state["entries"][-1]
        with proactive._PROACTIVE_CONTEXTS_LOCK:
            proactive._PROACTIVE_CONTEXTS[item["token"]] = {"turn_id": "report-turn", "session_id": "session", "agent_id": "pa",
                "origin": "proactive_plugin", "proactive_plugin": {"deliveryToken": item["token"], "bindingRevision": 1,
                "pluginId": "personal-assistant-dialogue", "sourceKind": "personal-assistant-dialogue",
                "triggerId": item["event"]["eventId"]}}
        return {"accepted": True, "turnId": "report-turn"}

    monkeypatch.setattr(proactive, "submit_session_proactive_turn", submit)
    return calls


@pytest.mark.parametrize("action", ["team_update", "agent_purge"])
def test_unknown_asset_or_purge_wakes_once_by_original_ref_without_object_or_post(watch, monkeypatch, action):
    root, dispatch, remote, runtime, add = watch
    ref = add(action)
    calls = install_context(runtime, monkeypatch)
    try:
        events = refresh(runtime, 10000)
        assert len(events) == 1
        event = events[0]
        assert event == {"schemaVersion": 2, "kind": "management_request", **ref, "issue": "requires_review",
                         "status": "unknown", "episode": event["episode"], "eventId": event["eventId"]}
        assert runtime.inspect(events, now=10000)["wake"] == "accepted"
        prompt = runtime.prompt("pa", "session", "report-turn")
        assert "management_reconcile" in prompt and "management_receipt" in prompt
        assert f"action={action} request_id=asset-original" in prompt and "不要自动重试写操作" in prompt
        assert "runtime_get" not in prompt and "PRIVATE" not in prompt
        assert runtime.inspect(refresh(runtime, 14000), now=14000)["wake"] == "none"
        runtime.close()
        restarted = patrol.LauncherPatrol(root, "pa", "session", dispatch)
        assert restarted.inspect(refresh(restarted, 18000), now=18000)["wake"] == "none"
        assert len(calls) == 1 and restarted._state["schemaVersion"] == 2
        persisted = restarted._runtime._path.read_text(encoding="utf-8") + restarted._path.read_text(encoding="utf-8")
        assert all(value not in persisted for value in ("SECRET", "PRIVATE-target"))
        assert {call[0] for call in remote.calls} == {"runtime", "receipt", "reconciliation"}
    finally:
        with proactive._PROACTIVE_CONTEXTS_LOCK:
            proactive._PROACTIVE_CONTEXTS.clear()


def test_confirmed_proof_rereads_receipt_then_clears_pending_prompt_and_skips_completed_asset(watch, monkeypatch):
    _, _, remote, runtime, add = watch
    ref = add()
    install_context(runtime, monkeypatch)
    try:
        old = refresh(runtime, 10000)[0]
        runtime.inspect([old], now=10000)
        item = remote.states[ref["action"], ref["requestId"]]
        item.update(proof="confirmed", confirm_receipt=True)
        before = len(remote.calls)
        assert refresh(runtime, 11000) == []
        assert [row[0] for row in remote.calls[before:] if row[0] != "runtime"] == ["receipt", "reconciliation", "receipt"]
        assert not runtime._runtime.current(old) and runtime.prompt("pa", "session", "report-turn") == ""
        before = len(remote.calls)
        assert refresh(runtime, 15000) == []
        assert all(row[0] == "runtime" for row in remote.calls[before:])
    finally:
        with proactive._PROACTIVE_CONTEXTS_LOCK:
            proactive._PROACTIVE_CONTEXTS.clear()


def test_reconciliation_metadata_without_confirmed_receipt_never_claims_success(watch):
    _, _, remote, runtime, add = watch
    add(proof="confirmed")
    assert refresh(runtime, 10000) == []
    assert refresh(runtime, 10061) == []
    events = refresh(runtime, 10122)
    assert [event["kind"] for event in events] == ["management_request"]
    assert events[0]["status"] == "unknown"
    assert all(row["status"] != "confirmed" for row in runtime._runtime._state["rows"].values())


@pytest.mark.parametrize("failure", [{"proof": "unavailable"}, {"fail": True}])
def test_unreadable_original_request_is_debounced_and_restart_stable(watch, monkeypatch, failure):
    root, dispatch, _, runtime, add = watch
    add(**failure)
    calls = []
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kw: calls.append(kw) or {"accepted": True})
    assert refresh(runtime, 10000) == []
    assert refresh(runtime, 10061) == []
    events = refresh(runtime, 10122)
    assert len(events) == 1 and events[0]["kind"] == "management_request"
    assert runtime.inspect(events, now=10122)["wake"] == "accepted"
    runtime.close()
    restarted = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    assert refresh(restarted, 10200) == events
    assert restarted.inspect(events, now=15000)["wake"] == "none" and len(calls) == 1


def test_revocation_filters_original_event_prompt_ledger_counts_and_checkpoint(watch, monkeypatch):
    _, dispatch, _, runtime, add = watch
    add()
    install_context(runtime, monkeypatch)
    try:
        events = refresh(runtime, 10000)
        runtime.inspect(events, now=10000)
        dispatch.enabled = False
        assert not runtime._runtime.current(events[0])
        assert runtime.prompt("pa", "session", "report-turn") == ""
        assert not any(runtime.reconcile().values())
        assert runtime.delivery_escalations["unresolved"] == 0
        assert runtime.inspect(events, now=15000)["wake"] == "none"
        assert refresh(runtime, 16000) == []
        assert not runtime._runtime._state["rows"] and not runtime._runtime._state["sources"]
    finally:
        with proactive._PROACTIVE_CONTEXTS_LOCK:
            proactive._PROACTIVE_CONTEXTS.clear()


def test_binding_change_during_reconciliation_discards_old_metadata(watch):
    _, dispatch, remote, runtime, add = watch
    add()
    remote.after_read = lambda stage: setattr(dispatch, "enabled", False) if stage == "reconciliation" else None
    assert refresh(runtime, 10000) == []
    assert not runtime._runtime._state["rows"] and not runtime._runtime._state["sources"]


def test_paginated_directory_skips_special_owners_and_completed_refs_without_starving_unknown_tail(watch):
    _, _, remote, runtime, add = watch
    for action in ("agent_archive", "authorization_reduce", "authorization_revoke", "authorization_upgrade", "team_run"):
        add(action, request="first", receipt="completed")
    add("team_update", request="last")
    events = []
    for now in range(10000, 10006):
        before = len(remote.calls)
        events.extend(refresh(runtime, now))
        assert len(remote.calls) - before <= len(runtime_watch.KINDS) + 2
    assert len(events) == 1 and events[0]["requestId"] == "last"
    assert not any(row[1].startswith("authorization_") or row[1] == "team_run"
                   for row in remote.calls if row[0] != "runtime")
    archive_reads = sum(row[:2] == ("receipt", "agent_archive") for row in remote.calls)
    for now in range(11000, 11006):
        refresh(runtime, now)
    assert sum(row[:2] == ("receipt", "agent_archive") for row in remote.calls) == archive_reads == 1


def test_timed_out_head_advances_persisted_cursor_and_does_not_starve_other_requests(watch, monkeypatch):
    root, dispatch, _, runtime, add = watch
    add("agent_archive", request="head", hang=True)
    add("team_update", request="tail")
    monkeypatch.setattr(runtime_watch, "_BUDGET", 0.02)
    assert refresh(runtime, 10000) == []
    runtime.close()
    restarted = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    events = refresh(restarted, 10100)
    assert len(events) == 1 and events[0]["requestId"] == "tail"
    for now in (10200, 10300, 10400, 10500):
        events.extend(refresh(restarted, now))
    assert any(row["requestId"] == "head" and row["kind"] == "management_request" for row in events)


def test_unknown_control_is_reconciled_then_waits_for_actual_target_terminal(watch):
    _, _, remote, runtime, add = watch
    add("runtime_command", request="stop-original", proof="confirmed", confirm_receipt=True,
        command={"operation": operation(status="stopping"), "command": "stop", "accepted": True, "stopRequested": True})
    remote.metadata.rows["external_task"] = [operation(status="running")]
    assert refresh(runtime, 10000) == []
    assert [row[0] for row in remote.calls if row[0] != "runtime"] == ["receipt", "reconciliation", "receipt"]
    remote.metadata.rows["external_task"][0]["status"] = "cancelled"
    events = refresh(runtime, 12000)
    assert sum(row["issue"] == "control_settled" for row in events) == 1
    assert all(row["kind"] == "platform_runtime" for row in events)
    assert any(row[0:2] == ("runtime", "get") for row in remote.calls)


def test_atomic_queue_withdrawal_settles_from_exact_native_ack_without_guessing_absence(watch):
    _, _, remote, runtime, add = watch
    add("runtime_command", request="withdraw-original", receipt="completed",
        command={"operation": operation(kind="session_queue", resource="queued-a", status="cancelled"),
            "command": "stop", "accepted": True, "stopRequested": False, "revisionCheck": "native_cas"})
    events = refresh(runtime, 10000)
    assert len(events) == 1 and events[0]["issue"] == "control_settled"
    assert events[0]["runtimeKind"] == "session_queue" and events[0]["status"] == "cancelled"
    assert not any(row[0:2] == ("runtime", "get") for row in remote.calls)


def test_new_closed_event_cannot_smuggle_object_identity_or_unsupported_owner(watch):
    _, _, _, runtime, add = watch
    add()
    event = refresh(runtime, 10000)[0]
    assert patrol._event(event) == event
    assert "runtimeKind" not in patrol._event({**event, "runtimeKind": "runtime_task", "resourceId": "forged"})
    assert patrol._event({**event, "action": "authorization_upgrade"}) is None
    assert patrol._event({**event, "action": "team_run"}) is None
    assert patrol._event({**event, "requestId": "bad.request"}) is None


def test_unavailable_to_review_is_one_unresolved_episode(watch):
    _, _, remote, runtime, add = watch
    add(proof="unavailable")
    refresh(runtime, 10000)
    refresh(runtime, 10061)
    event = refresh(runtime, 10122)[0]
    remote.states["team_update", "asset-original"]["proof"] = "requires_review"
    assert refresh(runtime, 10200) == [event]
    remote.states["team_update", "asset-original"]["proof"] = "unavailable"
    assert refresh(runtime, 10300) == [event]


def test_directory_unavailable_does_not_invent_request_or_runtime_identity(watch, monkeypatch):
    _, dispatch, _, runtime, _ = watch

    def unreadable(**query):
        raise OSError("SECRET directory error")

    monkeypatch.setattr(dispatch.management, "list_requests", unreadable)
    for now in (10000, 10061, 10122):
        assert refresh(runtime, now) == []
    assert runtime.platform_observation["state"] == "partial"
    assert not runtime._runtime._state["rows"]


def test_schema_one_checkpoint_and_delivery_keep_old_proofs_alongside_new_management_event(watch, monkeypatch):
    root, dispatch, remote, runtime, add = watch
    remote.metadata.rows["external_task"] = [operation(status="failed")]
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kw: {"accepted": True})
    old = refresh(runtime, 10000)[0]
    assert runtime.inspect([old], now=10000)["wake"] == "accepted"
    runtime.close()
    legacy = json.loads(runtime._path.read_text(encoding="utf-8"))
    legacy["schemaVersion"] = 1
    runtime._path.write_text(json.dumps(legacy), encoding="utf-8")
    assert json.loads(runtime._runtime._path.read_text(encoding="utf-8"))["schemaVersion"] == 1
    add()
    restarted = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    events = refresh(restarted, 18000)
    assert restarted.inspect(events, now=18000)["wake"] == "accepted"
    stored = json.loads(restarted._path.read_text(encoding="utf-8"))
    assert stored["schemaVersion"] == 2
    assert stored["entries"][0]["event"] == old
    assert stored["entries"][1]["event"]["kind"] == "management_request"
