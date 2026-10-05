"""Route contract tests for the runtime task query API (/aux backend).

The route layer is exercised against a real registry store on a tmp root (the
same造数方式 as tests/test_runtime_task_registry.py): snapshots are registered
through ``new_snapshot`` + ``register_task``, so the tests cover the actual
service + registry integration, not a fake ledger.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes import runtime_tasks as runtime_task_routes
from core.web.services import runtime_task_registry as registry
from core.web.services.runtime_task_query_service import RuntimeTaskQueryService


def _store(tmp_path):
    return registry.RuntimeTaskStore(
        tmp_path / "runtime_tasks", branch_generation_reader=lambda _session_id: 0
    )


def _register(store, *, task_id, kind, status, created_at="", started_at="", completed_at="",
              parent_session_id="", label="", output="", terminal_reason=""):
    snapshot = registry.new_snapshot(
        kind=kind,
        task_id=task_id,
        status=status,
        parent_session_id=parent_session_id,
        label=label,
        output=output,
    )
    if created_at:
        snapshot["createdAt"] = created_at
    if started_at:
        snapshot["startedAt"] = started_at
    if completed_at:
        snapshot["completedAt"] = completed_at
    if terminal_reason:
        snapshot["terminalReason"] = terminal_reason
    return store.register_task(snapshot)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    store = _store(tmp_path)
    app = FastAPI()
    app.include_router(runtime_task_routes.router, prefix="/api")
    test_service = RuntimeTaskQueryService(store)
    monkeypatch.setattr(
        runtime_task_routes, "default_query_service", lambda: test_service
    )
    return TestClient(app), store


# -- list shape -----------------------------------------------------------


def test_list_shape_running_and_ended(client):
    http, store = client
    _register(store, task_id="child-1", kind=registry.KIND_CHILD_SESSION,
              status="running", started_at="2026-10-01T01:00:00+00:00",
              parent_session_id="parent-1", label="帮忙整理笔记")
    _register(store, task_id="cli-1", kind=registry.KIND_CLI_AGENT,
              status="queued", started_at="2026-10-01T02:00:00+00:00",
              output="first line of cli output\nsecond line")
    _register(store, task_id="done-1", kind=registry.KIND_CLI_AGENT,
              status="completed", started_at="2026-10-01T00:00:00+00:00",
              completed_at="2026-10-01T00:05:00+00:00")
    _register(store, task_id="done-2", kind=registry.KIND_RESEARCH_TASK,
              status="failed", started_at="2026-09-30T10:00:00+00:00",
              completed_at="2026-09-30T10:01:00+00:00")

    response = http.get("/api/runtime-tasks")
    assert response.status_code == 200
    payload = response.json()

    assert payload["revision"].startswith("rev-")
    running = {card["taskId"]: card for card in payload["running"]}
    assert set(running) == {"child-1", "cli-1"}
    # Most recently started first.
    assert [card["taskId"] for card in payload["running"]] == ["cli-1", "child-1"]
    assert running["child-1"]["kind"] == "child_session"
    assert running["child-1"]["title"] == "帮忙整理笔记"
    assert running["child-1"]["parentSessionId"] == "parent-1"
    assert running["child-1"]["childSessionId"] == "child-1"
    assert running["child-1"]["endedAt"] == ""
    assert running["cli-1"]["title"] == "first line of cli output"
    assert "childSessionId" not in running["cli-1"]

    ended = payload["ended"]
    assert ended["total"] == 2
    assert [item["taskId"] for item in ended["items"]] == ["done-1", "done-2"]
    assert ended["items"][0]["endedAt"] == "2026-10-01T00:05:00+00:00"
    assert ended["items"][1]["kind"] == "research_task"
    assert ended["nextCursor"] == ""


def test_revision_changes_when_list_content_changes(client):
    http, store = client
    _register(store, task_id="task-a", kind=registry.KIND_CLI_AGENT,
              status="running", started_at="2026-10-01T01:00:00+00:00")

    first = http.get("/api/runtime-tasks").json()
    stable = http.get("/api/runtime-tasks").json()
    assert stable["revision"] == first["revision"]

    store.mark_task_terminal("task-a", status="completed", stop_initiator="user")
    second = http.get("/api/runtime-tasks").json()
    assert second["revision"] != first["revision"]
    assert second["running"] == []
    assert second["ended"]["total"] == 1


def test_list_filters_by_kind_and_parent(client):
    http, store = client
    _register(store, task_id="child-1", kind=registry.KIND_CHILD_SESSION,
              status="running", started_at="2026-10-01T01:00:00+00:00",
              parent_session_id="parent-1")
    _register(store, task_id="cli-1", kind=registry.KIND_CLI_AGENT,
              status="running", started_at="2026-10-01T01:30:00+00:00")
    _register(store, task_id="done-child", kind=registry.KIND_CHILD_SESSION,
              status="completed", started_at="2026-09-30T09:00:00+00:00",
              completed_at="2026-09-30T09:10:00+00:00",
              parent_session_id="parent-2")

    by_kind = http.get("/api/runtime-tasks", params={"kind": "child_session"}).json()
    assert [card["taskId"] for card in by_kind["running"]] == ["child-1"]
    assert [item["taskId"] for item in by_kind["ended"]["items"]] == ["done-child"]

    by_parent = http.get(
        "/api/runtime-tasks", params={"parent_session_id": "parent-1"}
    ).json()
    assert [card["taskId"] for card in by_parent["running"]] == ["child-1"]
    assert by_parent["ended"]["total"] == 0

    unknown_kind = http.get("/api/runtime-tasks", params={"kind": "nope"})
    assert unknown_kind.status_code == 400
    unknown_status = http.get("/api/runtime-tasks", params={"status": "bogus"})
    assert unknown_status.status_code == 400


def test_ended_pagination_follows_cursor_without_duplicates(client):
    http, store = client
    for index in range(5):
        _register(store, task_id=f"ended-{index}", kind=registry.KIND_CLI_AGENT,
                  status="completed", started_at="2026-09-30T00:00:00+00:00",
                  completed_at=f"2026-09-30T00:0{index}:00+00:00")

    seen: list[str] = []
    cursor = ""
    pages = 0
    while True:
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        payload = http.get("/api/runtime-tasks", params=params).json()
        assert len(payload["ended"]["items"]) <= 2
        seen.extend(item["taskId"] for item in payload["ended"]["items"])
        pages += 1
        cursor = payload["ended"]["nextCursor"]
        if not cursor:
            break
    assert pages == 3
    assert seen == [f"ended-{index}" for index in range(4, -1, -1)]
    assert payload["ended"]["total"] == 5


# -- detail ---------------------------------------------------------------


def test_detail_returns_card_and_timeline(client):
    http, store = client
    _register(store, task_id="child-9", kind=registry.KIND_CHILD_SESSION,
              status="running", created_at="2026-10-01T00:59:00+00:00",
              started_at="2026-10-01T01:00:00+00:00",
              parent_session_id="parent-9", label="调研任务")

    response = http.get("/api/runtime-tasks/child-9")
    assert response.status_code == 200
    detail = response.json()
    assert detail["taskId"] == "child-9"
    assert detail["childSessionId"] == "child-9"
    assert detail["title"] == "调研任务"
    assert detail["endedAt"] == ""
    events = [entry["event"] for entry in detail["timeline"]]
    assert events[0] == "created"
    assert "started" in events

    missing = http.get("/api/runtime-tasks/does-not-exist")
    assert missing.status_code == 404


def test_detail_terminal_task_carries_ended_fields(client):
    http, store = client
    _register(store, task_id="done-x", kind=registry.KIND_RESEARCH_TASK,
              status="failed", started_at="2026-09-30T08:00:00+00:00",
              completed_at="2026-09-30T08:03:00+00:00",
              terminal_reason="llm_error")

    detail = http.get("/api/runtime-tasks/done-x").json()
    assert detail["endedAt"] == "2026-09-30T08:03:00+00:00"
    completed_entries = [
        entry for entry in detail["timeline"] if entry["event"] == "completed"
    ]
    assert completed_entries and completed_entries[0]["detail"] == "llm_error"


# -- stop verb ------------------------------------------------------------


def test_stop_records_initiator_and_is_idempotent_on_terminal(client):
    http, store = client
    _register(store, task_id="live-1", kind=registry.KIND_CHILD_SESSION,
              status="running", started_at="2026-10-01T01:00:00+00:00")
    _register(store, task_id="settled-1", kind=registry.KIND_CLI_AGENT,
              status="completed", started_at="2026-09-30T01:00:00+00:00",
              completed_at="2026-09-30T01:05:00+00:00")

    stopped = http.post(
        "/api/runtime-tasks/live-1/stop", json={"initiator": "model"}
    )
    assert stopped.status_code == 200
    body = stopped.json()
    assert body == {
        "accepted": True,
        "taskId": "live-1",
        "status": "running",
        "stopInitiator": "model",
    }
    persisted = store.load_state("live-1")
    assert persisted["stopInitiator"] == "model"
    assert persisted["stopRequestedAt"]

    # Terminal tasks are never re-armed: idempotent refusal, no error.
    late = http.post("/api/runtime-tasks/settled-1/stop", json={})
    assert late.status_code == 200
    assert late.json() == {
        "accepted": False,
        "taskId": "settled-1",
        "status": "completed",
        "stopInitiator": None,
    }

    # A task that turns terminal after the stop intent keeps the intent and
    # stays terminal; a second stop is still an idempotent no-op.
    store.mark_task_terminal("live-1", status="stopped")
    after = http.post("/api/runtime-tasks/live-1/stop")
    assert after.status_code == 200
    assert after.json()["accepted"] is False
    assert after.json()["status"] == "stopped"


def test_stop_defaults_to_user_initiator(client):
    http, store = client
    _register(store, task_id="live-2", kind=registry.KIND_CLI_AGENT,
              status="running", started_at="2026-10-01T01:00:00+00:00")

    response = http.post("/api/runtime-tasks/live-2/stop")
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert store.load_state("live-2")["stopInitiator"] == "user"


def test_stop_unknown_task_returns_404(client):
    http, _store = client
    response = http.post("/api/runtime-tasks/nope/stop", json={"initiator": "user"})
    assert response.status_code == 404


def test_stop_rejects_unknown_initiator(client):
    http, store = client
    _register(store, task_id="live-3", kind=registry.KIND_CLI_AGENT,
              status="running", started_at="2026-10-01T01:00:00+00:00")
    response = http.post(
        "/api/runtime-tasks/live-3/stop", json={"initiator": "robot"}
    )
    assert response.status_code == 422
