"""Platform observations feed the existing native patrol, without control writes."""
from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy

import pytest

from core.assistant_runtime import patrol, runtime_watch
from core.web.services.session import proactive
from tests.test_assistant_runtime_patrol import setup as dispatch_setup
from tests.test_launcher_assistant_runtime_operations import env as native_runtime_env, write


def operation(kind="external_task", resource="external-1", status="running", revision="1"):
    return {"kind": kind, "resourceId": resource, "status": status, "revision": revision,
            "sessionId": "session-1" if kind in {"session_turn", "session_queue"} else "",
            "teamId": "team-1" if kind in {"team_run", "research_run"} else "",
            "flowId": "flow-1" if kind in {"team_run", "research_run"} else ""}


class Management:
    def __init__(self):
        self.rows = {kind: [] for kind in runtime_watch.KINDS}
        self.fail = set()
        self.coverage = {}
        self.calls = []
        self.requests = []
        self.command = None
        self.after_read = None

    async def runtime(self, project, mode, **query):
        self.calls.append((project, mode, deepcopy(query)))
        kind = query["kind"]
        if kind in self.fail:
            raise RuntimeError("SECRET failure payload")
        rows = deepcopy(self.rows[kind])
        if mode == "get":
            return {"projectId": project, "operation": next(row for row in rows if row["resourceId"] == query["resource_id"])}
        offset, limit = query["offset"], query["limit"]
        snapshot = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        if query.get("expected_snapshot", snapshot) != snapshot:
            error = RuntimeError("snapshot changed")
            error.code = "RUNTIME_SNAPSHOT_CHANGED"
            raise error
        end = min(offset + limit, len(rows))
        state = self.coverage.get(kind, "available")
        if self.after_read:
            self.after_read()
        return {"projectId": project, "operations": rows[offset:end], "offset": offset, "total": len(rows),
                "nextOffset": end if end < len(rows) else None, "snapshot": snapshot,
                "coverage": [{"source": kind, "state": state, "complete": state == "available"}],
                "complete": state == "available"}

    def list_requests(self, *, project_id, action, offset, limit):
        assert action == ""
        rows = self.requests[offset:offset + limit]
        end = offset + len(rows)
        return {"requests": rows, "offset": offset, "total": len(self.requests),
                "nextOffset": end if end < len(self.requests) else None}

    async def receipt(self, project, *, action, request_id):
        return {"projectId": project, "action": action, "requestId": request_id,
                "verified": True, "status": "completed", "operation": deepcopy(self.command)}


@pytest.fixture
def platform(dispatch_setup, monkeypatch):
    root, _, dispatch = dispatch_setup
    dispatch.management = Management()
    dispatch.project_ids = lambda: ("project-a",)
    dispatch._project_read_binding = lambda project: (1, root) if dispatch.enabled else (_ for _ in ()).throw(ValueError("revoked"))
    monkeypatch.setattr(runtime_watch, "_CALLS", len(runtime_watch.KINDS) + 1)
    runtime = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    return root, dispatch, runtime


def refresh(runtime, now):
    return asyncio.run(runtime._runtime.refresh(now=now))


def test_non_assistant_external_failure_uses_native_patrol_and_restart_dedup(platform, monkeypatch):
    root, dispatch, runtime = platform
    dispatch.management.rows["external_task"] = [operation(status="failed")]
    calls = []
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kw: calls.append(kw) or {"accepted": True})
    events = refresh(runtime, 10000)
    assert events[0]["runtimeKind"] == "external_task" and events[0]["issue"] == "terminal"
    assert runtime.inspect(events, now=10000)["wake"] == "accepted"
    assert calls[0]["source_kind"] == "personal-assistant-dialogue"
    assert runtime.inspect(refresh(runtime, 14000), now=14000)["wake"] == "none"
    runtime.close()
    restarted = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    assert restarted.inspect(refresh(restarted, 18000), now=18000)["wake"] == "none"
    assert len(calls) == 1
    persisted = restarted._runtime._path.read_text(encoding="utf-8")
    assert "SECRET" not in persisted and "commands\": [" not in persisted
    assert restarted._state["schemaVersion"] == 2


def test_running_progress_resets_stall_clock_and_human_wait_is_not_blocked(platform):
    _, dispatch, runtime = platform
    row = operation()
    dispatch.management.rows["external_task"] = [row]
    assert refresh(runtime, 10000) == []
    assert refresh(runtime, 14000) == []
    row["progressFingerprint"] = "2" * 64
    assert refresh(runtime, 18000) == []
    assert refresh(runtime, 22000) == []
    events = refresh(runtime, 26000)
    assert any(event["issue"] == "no_progress" for event in events)
    assert {event["eventId"] for event in refresh(runtime, 30000)} == {event["eventId"] for event in events}
    row["status"] = "awaiting_approval"
    assert refresh(runtime, 34000) == []
    assert all(e["issue"] == "attention_required" for e in refresh(runtime, 50000))
    row["status"] = "waiting_human"
    assert refresh(runtime, 70000) == []


def test_explicit_blocked_and_repeated_read_failure_are_stable_episodes(platform):
    root, dispatch, runtime = platform
    dispatch.management.rows["research_run"] = [operation("research_run", status="blocked")]
    assert refresh(runtime, 10000) == []
    assert any(event["issue"] == "attention_required" and event["status"] == "blocked" for event in refresh(runtime, 10301))
    dispatch.management.fail.add("external_task")
    assert not any(e["issue"] == "read_failed" for e in refresh(runtime, 11000))
    assert not any(e["issue"] == "read_failed" for e in refresh(runtime, 11061))
    events = refresh(runtime, 11122)
    read = next(event for event in events if event["issue"] == "read_failed")
    runtime.close()
    restarted = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    again = next(e for e in refresh(restarted, 11200) if e["issue"] == "read_failed")
    assert again["eventId"] == read["eventId"]
    dispatch.management.fail.clear()
    refresh(restarted, 11500)
    dispatch.management.fail.add("external_task")
    refresh(restarted, 12000)
    refresh(restarted, 12061)
    later = next(e for e in refresh(restarted, 12122) if e["issue"] == "read_failed")
    assert later["eventId"] != read["eventId"]


def test_coverage_loss_and_disappearance_never_settle_a_running_task(platform):
    _, dispatch, runtime = platform
    dispatch.management.rows["external_task"] = [operation()]
    assert refresh(runtime, 10000) == []
    dispatch.management.rows["external_task"] = []
    dispatch.management.coverage["external_task"] = "partial"
    assert refresh(runtime, 11000) == []
    assert refresh(runtime, 11061) == []
    events = refresh(runtime, 11122)
    assert [event["issue"] for event in events] == ["coverage_unavailable"]
    assert all(event["issue"] != "terminal" for event in events)
    assert any(row["status"] == "running" for row in runtime._runtime._state["rows"].values())
    assert runtime.platform_observation["state"] == "partial"


def test_revocation_drops_observation_immediately_and_invalidates_old_prompt(platform, monkeypatch):
    _, dispatch, runtime = platform
    dispatch.management.rows["external_task"] = [operation(status="failed")]
    events = refresh(runtime, 10000)
    assert runtime._runtime.current(events[0])
    calls = []
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kw: calls.append(kw) or {"accepted": True})
    assert runtime.inspect(events, now=10000)["wake"] == "accepted"
    item = runtime._state["entries"][0]
    with proactive._PROACTIVE_CONTEXTS_LOCK:
        proactive._PROACTIVE_CONTEXTS[item["token"]] = {"turn_id": "report-turn", "session_id": "session", "agent_id": "pa",
            "origin": "proactive_plugin", "proactive_plugin": {"deliveryToken": item["token"], "bindingRevision": 1,
            "pluginId": "personal-assistant-dialogue", "sourceKind": "personal-assistant-dialogue", "triggerId": item["event"]["eventId"]}}
    try:
        assert "runtime_get" in runtime.prompt("pa", "session", "report-turn")
        dispatch.enabled = False
        assert not runtime._runtime.current(events[0])
        assert runtime.prompt("pa", "session", "report-turn") == ""
        assert runtime.reconcile()["unknown"] == 0
        assert runtime.delivery_escalations["unresolved"] == 0
        assert refresh(runtime, 12000) == []
        assert not runtime._runtime._state["rows"] and not runtime._runtime._state["sources"]
        assert len(calls) == 1
    finally:
        with proactive._PROACTIVE_CONTEXTS_LOCK:
            proactive._PROACTIVE_CONTEXTS.pop(item["token"], None)


def test_bounded_fair_pages_resume_checkpoint_and_snapshot_changes_do_not_starve_tail(platform, monkeypatch):
    root, dispatch, runtime = platform
    monkeypatch.setattr(runtime_watch, "_CALLS", 1)
    dispatch.management.rows["external_task"] = [operation(resource=f"external-{i}") for i in range(8)]
    for i in range(runtime_watch.KINDS.index("external_task") + 1):
        refresh(runtime, 10000 + i)
    first = next(call for call in dispatch.management.calls if call[2]["kind"] == "external_task")
    assert first[2]["offset"] == 0
    runtime.close()
    restarted = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    dispatch.management.rows["external_task"][0]["revision"] = "2"
    for i in range(2 * (len(runtime_watch.KINDS) + 1)):
        before = len(dispatch.management.calls)
        refresh(restarted, 11000 + i)
        assert len(dispatch.management.calls) - before <= 1
    pages = [call[2] for call in dispatch.management.calls if call[2]["kind"] == "external_task"]
    assert pages[1]["offset"] == 3 and "expected_snapshot" in pages[1]
    assert pages[2]["offset"] == 3 and "expected_snapshot" not in pages[2]
    assert any(row["ref"]["resourceId"] == "external-5" for row in restarted._runtime._state["rows"].values())
    assert not any(source.get("failures") for source in restarted._runtime._state["sources"].values())


def test_control_ack_is_followed_to_actual_owner_state(platform):
    _, dispatch, runtime = platform
    dispatch.management.rows["external_task"] = [operation(status="running")]
    dispatch.management.requests = [{"projectId": "project-a", "action": "runtime_command", "requestId": "control-1"}]
    dispatch.management.command = {"operation": operation(status="cancelled"), "command": "stop", "accepted": True, "stopRequested": True}
    events = refresh(runtime, 10000) + refresh(runtime, 10010)
    assert not any(e["issue"] == "control_settled" for e in events)
    dispatch.management.rows["external_task"][0]["status"] = "cancelled"
    events = refresh(runtime, 12000)
    assert any(e["issue"] == "control_settled" and e["status"] == "cancelled" for e in events)
    assert any(mode == "get" for _, mode, _ in dispatch.management.calls)
    assert all(mode in {"list", "get"} for _, mode, _ in dispatch.management.calls)


def test_authorization_change_during_read_discards_all_old_metadata(platform):
    _, dispatch, runtime = platform
    dispatch.management.rows["external_task"] = [operation(status="failed")]
    dispatch.management.after_read = lambda: setattr(dispatch, "enabled", False)
    assert refresh(runtime, 10000) == []
    assert not runtime._runtime._state["rows"]
    assert not runtime._runtime._state["sources"]


def test_heartbeat_control_revisions_do_not_claim_business_progress(platform):
    _, dispatch, runtime = platform
    row = operation()
    dispatch.management.rows["external_task"] = [row]
    assert refresh(runtime, 10000) == []
    row["revision"] = "2"
    assert refresh(runtime, 14000) == []
    row["revision"] = "3"
    assert any(event["issue"] == "no_progress" for event in refresh(runtime, 18000))


def test_native_external_task_failure_from_other_entry_wakes_without_dispatch_record(platform, native_runtime_env, monkeypatch):
    from core.web.services.external_management import runtime_operations
    _, dispatch, runtime = platform
    env = native_runtime_env
    write(env.external / "eat-outside-task.json", {"taskId": "eat-outside-task", "status": "failed", "revision": 1,
        "prompt": "SECRET task body", "summary": "SECRET result", "credential": "SECRET token"})

    async def read_native(project, mode, **query):
        assert mode == "list"
        return {**runtime_operations.read_operations(env.gateway, query), "projectId": project}

    dispatch.management.runtime = read_native
    page = runtime_operations.read_operations(env.gateway, {"kind": "external_task", "state": "all", "offset": 0, "limit": 3})
    assert page["operations"] and "snapshot" in page, page
    calls = []
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kw: calls.append(kw) or {"accepted": True})
    events = refresh(runtime, 10000)
    native_event = next(event for event in events if event["resourceId"] == "eat-outside-task")
    assert native_event["status"] == "failed" and native_event["runtimeKind"] == "external_task"
    assert runtime.inspect([native_event], now=10000)["wake"] == "accepted"
    assert len(calls) == 1
    assert "SECRET" not in runtime._runtime._path.read_text(encoding="utf-8")
    assert "SECRET" not in runtime._path.read_text(encoding="utf-8")


def test_stale_dispatch_error_reports_read_failure_without_using_cached_terminal(platform):
    _, dispatch, runtime = platform
    stale = {"projectId": "project-a", "dispatchId": "dispatch-1", "nativeTaskId": "task-1",
             "receipt": {"taskId": "task-1", "status": "succeeded"}, "lastError": {"code": "READ_FAILED"}}
    assert patrol._event(stale) is None
    async def observe(now):
        return await runtime._runtime.refresh(now=now, dispatch_rows=[stale])
    assert asyncio.run(observe(10000)) == []
    assert asyncio.run(observe(10061)) == []
    events = asyncio.run(observe(10122))
    assert [event["issue"] for event in events] == ["read_failed"]
    assert events[0]["resourceId"] == "task-1" and events[0]["status"] == "unavailable"


def test_bounded_read_timeout_is_a_persistent_failure_episode(platform, monkeypatch):
    _, dispatch, runtime = platform
    monkeypatch.setattr(runtime_watch, "_BUDGET", 0.01)
    original = dispatch.management.runtime

    async def hung(project, mode, **query):
        if query["kind"] == "external_task":
            await asyncio.Event().wait()
        return await original(project, mode, **query)

    dispatch.management.runtime = hung
    events = []
    for now in (10000, 10100, 10200, 10300, 10400):
        events.extend(refresh(runtime, now))
    assert any(event["issue"] == "read_failed" and event["runtimeKind"] == "external_task" for event in events)


def test_host_registry_generation_change_does_not_create_new_durable_episode(platform):
    root, dispatch, runtime = platform
    dispatch.management.rows["external_task"] = [operation(status="failed")]
    first = next(e for e in refresh(runtime, 10000) if e["resourceId"] == "external-1")
    dispatch._project_read_binding = lambda project: (73, root)
    assert not runtime._runtime.current(first)
    second = next(e for e in refresh(runtime, 11000) if e["resourceId"] == "external-1")
    assert second["eventId"] == first["eventId"]
    runtime.close()
    dispatch._project_read_binding = lambda project: (1, root)
    restarted = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    third = next(e for e in refresh(restarted, 12000) if e["resourceId"] == "external-1")
    assert third["eventId"] == first["eventId"]
