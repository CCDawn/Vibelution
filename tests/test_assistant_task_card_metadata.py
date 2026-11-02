"""Optional Launcher task labels cannot become identity or transcript authority."""
from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from types import SimpleNamespace

import anyio
import pytest

from core.assistant_runtime import task_card_metadata as metadata
from core.assistant_runtime.dispatch_approval import DispatchWrite, dispatch_write_approval_summary
from core.assistant_runtime.local_project_client import LocalAssistantBackendClient
from core.external_agent.backend_client import BackendClientError, ManagedAgentBackendClient
from tests.test_assistant_delegation import child, setup_goal


def enrich(dispatch, rows):
    return anyio.run(metadata.enrich_dispatch_cards, dispatch, rows)


def label_dispatch(tmp_path, reader):
    return SimpleNamespace(management=SimpleNamespace(agent=reader),
        _project_read_binding=lambda project: (1, tmp_path / project))


def test_verified_public_labels_are_bounded_deduplicated_and_rows_copied(tmp_path):
    calls = []

    async def agent(project_id, *, agent_id):
        calls.append((project_id, agent_id))
        return {"projectId": project_id, "agent": {"agentId": agent_id,
            "displayName": "  研发\n组\x00\u202e " + "中" * 180, "prompt": "private"}}

    dispatch = label_dispatch(tmp_path, agent)
    rows = [{"projectId": "project-a", "agentId": "worker", "dispatchId": str(i),
             "createdAt": "created", "updatedAt": "updated", "receipt": {"status": "running"}}
            for i in range(3)]
    before = deepcopy(rows)
    cards = enrich(dispatch, rows)
    assert rows == before and cards is not rows and cards[0]["receipt"] is not rows[0]["receipt"]
    assert calls == [("project-a", "worker")]
    assert all(row["agentName"] == ("研发 组 " + "中" * 180)[:160] for row in cards)
    assert all(row["projectName"] == "project-a" and row["createdAt"] == "created"
               and row["updatedAt"] == "updated" for row in cards)
    assert "private" not in json.dumps(cards)
    assert all("title" not in row for row in cards)  # No task-body-derived title for old rows.


@pytest.mark.parametrize("fault", ["project", "agent", "missing", "scope", "timeout", "name"])
def test_optional_directory_failures_keep_native_rows_and_verified_project_label(tmp_path, fault):
    async def agent(project_id, *, agent_id):
        if fault == "scope":
            raise PermissionError("private capability denied")
        if fault == "timeout":
            await anyio.sleep(10)
        return {"projectId": "other" if fault == "project" else project_id,
                "agent": {"agentId": "other" if fault == "agent" else None if fault == "missing" else agent_id,
                          "displayName": {} if fault == "name" else "worker"}}

    row = {"projectId": "project-a", "agentId": "worker", "receipt": {"status": "running"}}
    started = time.monotonic()
    result = enrich(label_dispatch(tmp_path, agent), [row])
    assert time.monotonic() - started < 1.0
    assert result == [{**row, "projectName": "project-a"}]


def test_binding_change_discards_only_optional_labels(tmp_path):
    binding = [1]

    async def agent(project_id, *, agent_id):
        binding[0] += 1
        return {"projectId": project_id, "agent": {"agentId": agent_id, "displayName": "worker"}}

    dispatch = label_dispatch(tmp_path, agent)
    dispatch._project_read_binding = lambda project: (binding[0], tmp_path / project)
    rows = [{"projectId": "project-a", "agentId": "worker", "receipt": {"status": "running"}}]
    assert enrich(dispatch, rows) == rows


def test_missing_metadata_capability_keeps_legacy_host_mocks_usable():
    rows = [{"dispatchId": "old", "receipt": {"status": "running"}}]
    assert enrich(SimpleNamespace(), rows) == rows


@pytest.mark.parametrize("busy", ["borrowers", "closing", "guard"])
def test_busy_native_task_control_skips_optional_name_lookup(tmp_path, busy):
    async def forbidden(*args, **kwargs):
        pytest.fail("display metadata cannot contend with active task control")

    dispatch = label_dispatch(tmp_path, forbidden)
    dispatch._active_project_clients = {"project-a": SimpleNamespace(
        borrowers=1 if busy == "borrowers" else 0, closing=busy == "closing")}
    dispatch._project_locks = {"project-a": SimpleNamespace(locked=lambda: busy == "guard")}
    row = {"projectId": "project-a", "agentId": "worker", "receipt": {"status": "running"}}
    assert enrich(dispatch, [row]) == [{**row, "projectName": "project-a"}]


def test_lookup_concurrency_and_page_budget_preserve_healthy_projects(tmp_path, monkeypatch):
    active = peak = 0
    monkeypatch.setattr(metadata, "_LOOKUP_BUDGET", 0.08)
    monkeypatch.setattr(metadata, "_PAGE_BUDGET", 0.15)

    async def agent(project_id, *, agent_id):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await anyio.sleep(10 if project_id == "slow" else 0.002)
            return {"projectId": project_id, "agent": {"agentId": agent_id, "displayName": "healthy"}}
        finally:
            active -= 1

    rows = [{"projectId": "slow" if i == 0 else f"project-{i}", "agentId": "worker"} for i in range(16)]
    started = time.monotonic()
    result = enrich(label_dispatch(tmp_path, agent), rows)
    assert time.monotonic() - started < 0.5 and peak == 4 and active == 0
    assert "agentName" not in result[0]
    assert all(row["agentName"] == "healthy" for row in result[1:])


def test_write_title_is_optional_and_bound_in_exact_approval_summary():
    values = {"project_id": "project-a", "agent_id": "worker", "dispatch_id": "dispatch-1",
              "task": "修改文件\n保留其他内容。"}
    assert DispatchWrite.model_validate(values).title == ""
    summary = dispatch_write_approval_summary({**values, "title": "修复任务卡展示"})
    assert summary["assistantTitle"] == "修复任务卡展示" and summary["assistantTask"] == values["task"]
    assert summary["assistantTargets"] == {key: values[key] for key in ("project_id", "agent_id", "dispatch_id")}
    assert "任务名称" in DispatchWrite.model_json_schema()["properties"]["title"]["description"]


@pytest.mark.parametrize("title", [" leading", "trailing ", "two\nlines", "two\rlines", "tab\tname",
                                  "bidi\u202e", "line\u2028break", "x" * 161, None])
def test_write_title_rejects_unsafe_or_unbounded_display_text(title):
    with pytest.raises(ValueError):
        DispatchWrite.model_validate({"project_id": "project-a", "agent_id": "worker",
            "dispatch_id": "dispatch-1", "task": "exact task", "title": title})


def test_derived_title_reaches_native_dispatch_and_approval_and_preserves_old_child_hash(setup_goal):
    from core.assistant_runtime.delegation import _hash, approval_summary

    owner, dispatch, runtime, goal, *_ = setup_goal
    owner.create(goal, runtime)
    old = child()
    identity = _hash({key: value for key, value in old.items() if key != "dispatch_id"})
    row = owner._read(goal["goal_id"])
    row["children"][old["dispatch_id"]] = identity
    owner._save(goal["goal_id"], row)
    anyio.run(owner.derived, old, runtime)
    assert owner.get(goal["goal_id"], runtime)["usedTasks"] == 1
    titled = child(dispatch_id="child-2", task="New exact task", title="修复任务卡")
    anyio.run(owner.derived, titled, runtime)
    assert dispatch.calls[-1][1]["title"] == titled["title"]
    summary = approval_summary("dispatch_derived", titled)
    assert summary["assistantTitle"] == titled["title"] and summary["assistantTask"] == titled["task"]


def test_exact_write_title_is_persisted_and_restored_without_storing_task_body(tmp_path, monkeypatch):
    from core.assistant_runtime import native
    from tests.test_assistant_runtime_dispatch import ClientProbe, adapter

    runtime = {"agentId": "assistant", "sessionId": "session", "turnId": "turn"}
    task, title = "修改任务卡元数据，不要保留这段完整任务正文。", "修复任务卡展示"
    monkeypatch.setattr(native, "read_task_source", lambda caller, source_ref=None: {
        **runtime, "eventId": "event-a", "content": task})
    probe = ClientProbe()
    service = adapter(tmp_path, probe)

    async def scenario():
        return await service.dispatch_write_from_source("project-a", agent_id="coder",
            dispatch_id="titled-write", runtime=runtime, task=task, title=title)

    result = anyio.run(scenario)
    assert result["title"] == title
    raw = service._path("titled-write").read_text(encoding="utf-8")
    assert task not in raw and json.loads(raw)["title"] == title
    assert adapter(tmp_path, probe).list_dispatches()[0]["title"] == title
    sent = next(arguments for operation, arguments in probe.calls if operation == "start")
    summary = dispatch_write_approval_summary({"project_id": "project-a", "agent_id": "coder",
        "dispatch_id": "titled-write", "task": task, "title": title})
    assert sent["title"] == summary["assistantTitle"] == title and sent["task"] == summary["assistantTask"]


def test_old_unnamed_dispatch_stays_empty_without_inferring_title_from_receipt(tmp_path):
    from tests.test_assistant_runtime_dispatch import ClientProbe, adapter

    probe = ClientProbe()
    service = adapter(tmp_path, probe)

    async def scenario():
        await service.dispatch("project-a", agent_id="coder", dispatch_id="legacy",
            task="private original task body")

    anyio.run(scenario)
    record = service._read("legacy")
    record.pop("title", None)
    record["receipt"]["resultSummary"] = "private result body must not become the title"
    service._save(record)
    assert adapter(tmp_path, probe).list_dispatches()[0]["title"] == ""


def cleanup_client(namespace="local", authority="authority"):
    client = LocalAssistantBackendClient.__new__(LocalAssistantBackendClient)
    capability = "task-capability"
    client._launcher_capability = authority
    client._state_lock = anyio.Lock()
    client._state = {"tasks": {"task/1": {"taskCapability": capability}}, "transportNamespaces": {
        hashlib.sha256(capability.encode()).hexdigest(): namespace} if namespace else {}}
    return client


def test_cleanup_uses_original_local_task_capability_and_adapter_routing(monkeypatch):
    calls = []

    async def request(self, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True}

    monkeypatch.setattr(ManagedAgentBackendClient, "_request_json", request)
    client = cleanup_client()

    async def scenario():
        assert await client.preview_task_cleanup("task/1") == {"ok": True}
        assert await client.cleanup_task("task/1", "revision-1", "a" * 64) == {"ok": True}

    anyio.run(scenario)
    assert [row[:2] for row in calls] == [
        ("POST", "/api/local-assistant/v1/external-agent/tasks/task%2F1/cleanup/preview"),
        ("POST", "/api/local-assistant/v1/external-agent/tasks/task%2F1/cleanup")]
    assert all(row[2]["task_capability"] == "task-capability" and
               row[2]["management_auth"] == ("launcher-local", "authority") for row in calls)
    assert calls[0][2]["json_payload"] == {}
    assert calls[1][2]["json_payload"] == {"revision": "revision-1", "fingerprint": "a" * 64}


@pytest.mark.parametrize("namespace,authority,code", [("external", "authority", "TASK_CLEANUP_UNAVAILABLE"),
    ("", "authority", "TASK_CLEANUP_UNAVAILABLE"), ("local", "", "LAUNCHER_AUTHORITY_REQUIRED")])
def test_cleanup_rejects_external_legacy_and_missing_authority_without_network(monkeypatch, namespace, authority, code):
    async def forbidden(*args, **kwargs):
        pytest.fail("cleanup must not fall back to ordinary external routes")

    monkeypatch.setattr(ManagedAgentBackendClient, "_request_json", forbidden)
    client = cleanup_client(namespace, authority)
    for operation in (client.preview_task_cleanup, lambda task: client.cleanup_task(task, "r", "f")):
        with pytest.raises(BackendClientError) as error:
            anyio.run(operation, "task/1")
        assert error.value.code == code
