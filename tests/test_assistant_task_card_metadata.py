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
from core.assistant_runtime.dispatch import DispatchError
from core.assistant_runtime.dispatch_approval import DispatchWrite, dispatch_write_approval_summary
from core.assistant_runtime.local_project_client import LocalAssistantBackendClient
from core.external_agent.backend_client import BackendClientError, ManagedAgentBackendClient
from tests.test_assistant_delegation import child, setup_goal


def enrich(dispatch, rows):
    return anyio.run(metadata.enrich_dispatch_cards, dispatch, rows)


def label_dispatch(tmp_path, reader):
    return SimpleNamespace(management=SimpleNamespace(agent=reader),
        _project_read_binding=lambda project: (1, tmp_path / project), _task_card_agent_labels={})


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


def test_verified_name_survives_slow_refresh_and_updates_from_each_new_read(tmp_path, monkeypatch):
    monkeypatch.setattr(metadata, "_LOOKUP_BUDGET", 0.01)
    calls = []
    names = iter(["Original", None, "Renamed", None])

    async def agent(project_id, *, agent_id):
        calls.append((project_id, agent_id))
        name = next(names)
        if name is None:
            await anyio.sleep(10)
        return {"projectId": project_id, "agent": {"agentId": agent_id, "displayName": name}}

    dispatch = label_dispatch(tmp_path, agent)
    rows = [{"dispatchId": "stable-task", "projectId": "project-a", "agentId": "worker",
             "title": "", "receipt": {"status": "running"}}]
    before = deepcopy(rows)
    assert [enrich(dispatch, rows)[0]["agentName"] for _ in range(4)] == [
        "Original", "Original", "Renamed", "Renamed"]
    assert calls == [("project-a", "worker")] * 4 and rows == before


@pytest.mark.parametrize("change", ["generation", "root"])
def test_cached_names_are_isolated_by_project_and_complete_binding(tmp_path, monkeypatch, change):
    monkeypatch.setattr(metadata, "_LOOKUP_BUDGET", 0.01)
    slow = False
    bindings = {project: (1, tmp_path / project) for project in ("project-a", "project-b")}

    async def agent(project_id, *, agent_id):
        if slow:
            await anyio.sleep(10)
        return {"projectId": project_id, "agent": {"agentId": agent_id, "displayName": project_id}}

    dispatch = label_dispatch(tmp_path, agent)
    dispatch._project_read_binding = bindings.get
    rows = [{"projectId": project, "agentId": "worker"} for project in bindings]
    assert [row["agentName"] for row in enrich(dispatch, rows)] == list(bindings)
    old = bindings["project-a"]
    bindings["project-a"] = (2, old[1]) if change == "generation" else (old[0], tmp_path / "new-root")
    slow = True
    cards = enrich(dispatch, rows)
    assert "agentName" not in cards[0] and cards[1]["agentName"] == "project-b"
    # A previous binding cannot become a label source again after invalidation.
    bindings["project-a"] = old
    assert "agentName" not in enrich(dispatch, rows)[0]


@pytest.mark.parametrize("denial", ["missing", "exception", "during-read"])
def test_revoked_binding_discards_cached_labels_before_reauthorization(tmp_path, monkeypatch, denial):
    monkeypatch.setattr(metadata, "_LOOKUP_BUDGET", 0.01)
    allowed, revoke_during_read, slow = True, False, False

    def binding(project):
        if not allowed:
            if denial == "exception":
                raise PermissionError("project access revoked")
            return None
        return 1, tmp_path / project

    async def agent(project_id, *, agent_id):
        nonlocal allowed
        if slow:
            await anyio.sleep(10)
        if revoke_during_read:
            allowed = False
        return {"projectId": project_id, "agent": {"agentId": agent_id, "displayName": "Verified"}}

    dispatch = label_dispatch(tmp_path, agent)
    dispatch._project_read_binding = binding
    rows = [{"projectId": "project-a", "agentId": "worker"}]
    assert enrich(dispatch, rows)[0]["agentName"] == "Verified"
    if denial == "during-read":
        revoke_during_read = True
    else:
        allowed = False
    assert enrich(dispatch, rows) == rows and dispatch._task_card_agent_labels == {}
    allowed, revoke_during_read, slow = True, False, True
    assert "agentName" not in enrich(dispatch, rows)[0]


@pytest.mark.parametrize("error_type,code", [
    (error_type, code) for error_type in (BackendClientError, DispatchError)
    for code in ("SCOPE_DENIED", "SUBJECT_DENIED", "SUBJECT_REVOKED", "TARGET_BINDING_CHANGED",
                 "UNKNOWN_MANAGEMENT_SUBJECT", "MANAGEMENT_IDENTITY_ROTATED", "RUNTIME_IDENTITY_MISMATCH")
] + [(PermissionError, None)])
def test_source_authority_denial_clears_project_labels_with_unchanged_binding(
        tmp_path, monkeypatch, error_type, code):
    monkeypatch.setattr(metadata, "_LOOKUP_BUDGET", 0.01)
    mode, calls = "success", []

    async def agent(project_id, *, agent_id):
        calls.append((project_id, agent_id))
        if mode == "slow":
            await anyio.sleep(10)
        if mode == "denied" and project_id == "project-a" and agent_id == "second":
            if error_type is PermissionError:
                raise PermissionError("public Agent reads denied")
            raise error_type("public Agent reads denied", code=code)
        return {"projectId": project_id, "agent": {"agentId": agent_id, "displayName": "Verified"}}

    dispatch = label_dispatch(tmp_path, agent)
    rows = [{"projectId": "project-a", "agentId": name} for name in ("first", "second", "third")]
    rows.append({"projectId": "project-b", "agentId": "second"})
    assert all(row["agentName"] == "Verified" for row in enrich(dispatch, rows))
    binding = dispatch._project_read_binding("project-a")
    mode, calls = "denied", []
    cards = enrich(dispatch, rows)
    assert all("agentName" not in row for row in cards[:3])
    assert cards[3]["agentName"] == "Verified"
    assert dispatch._project_read_binding("project-a") == binding
    assert not any(key[0] == "project-a" for key in dispatch._task_card_agent_labels)
    assert ("project-a", "third") not in calls  # No later sibling can restore a denied page.
    mode = "slow"
    assert all("agentName" not in row for row in enrich(dispatch, rows)[:3])


@pytest.mark.parametrize("mismatch", ["project", "agent", "missing"])
def test_source_identity_mismatch_discards_only_target_agent_label(tmp_path, monkeypatch, mismatch):
    monkeypatch.setattr(metadata, "_LOOKUP_BUDGET", 0.01)
    mode = "success"

    async def agent(project_id, *, agent_id):
        if mode == "slow":
            await anyio.sleep(10)
        if mode == "mismatch" and agent_id == "target":
            return {"projectId": "other" if mismatch == "project" else project_id, "agent": {
                "agentId": "other" if mismatch == "agent" else None if mismatch == "missing" else agent_id,
                "displayName": "Wrong"}}
        return {"projectId": project_id, "agent": {"agentId": agent_id, "displayName": "Verified"}}

    dispatch = label_dispatch(tmp_path, agent)
    rows = [{"projectId": "project-a", "agentId": name} for name in ("target", "sibling", "target")]
    assert all(row["agentName"] == "Verified" for row in enrich(dispatch, rows))
    mode = "mismatch"
    cards = enrich(dispatch, rows)
    assert "agentName" not in cards[0] and "agentName" not in cards[2]
    assert cards[1]["agentName"] == "Verified"
    mode = "slow"
    cards = enrich(dispatch, rows)
    assert "agentName" not in cards[0] and "agentName" not in cards[2]
    assert cards[1]["agentName"] == "Verified"


@pytest.mark.parametrize("error", [
    BackendClientError("temporary", code="BACKEND_UNAVAILABLE"),
    DispatchError("temporary", code="BACKEND_TIMEOUT"),
    RuntimeError("SCOPE_DENIED"),
])
def test_temporary_or_untyped_source_failures_keep_verified_label(tmp_path, error):
    denied = False

    async def agent(project_id, *, agent_id):
        if denied:
            raise error
        return {"projectId": project_id, "agent": {"agentId": agent_id, "displayName": "Verified"}}

    dispatch = label_dispatch(tmp_path, agent)
    rows = [{"projectId": "project-a", "agentId": "worker"}]
    first = enrich(dispatch, rows)
    denied = True
    assert enrich(dispatch, rows) == first


@pytest.mark.parametrize("busy", ["borrowers", "closing", "guard"])
def test_busy_task_control_keeps_previously_verified_name_without_another_read(tmp_path, busy):
    calls = []

    async def agent(project_id, *, agent_id):
        calls.append(agent_id)
        return {"projectId": project_id, "agent": {"agentId": agent_id, "displayName": "Verified"}}

    dispatch = label_dispatch(tmp_path, agent)
    rows = [{"projectId": "project-a", "agentId": "worker"}]
    first = enrich(dispatch, rows)
    dispatch._active_project_clients = {"project-a": SimpleNamespace(
        borrowers=1 if busy == "borrowers" else 0, closing=busy == "closing")}
    dispatch._project_locks = {"project-a": SimpleNamespace(locked=lambda: busy == "guard")}
    assert enrich(dispatch, rows) == first and calls == ["worker"]


def test_label_cache_is_bounded_and_never_shared_by_dispatch_owners(tmp_path):
    calls = []

    async def agent(project_id, *, agent_id):
        calls.append(agent_id)
        return {"projectId": project_id, "agent": {"agentId": agent_id, "displayName": agent_id}}

    dispatch = label_dispatch(tmp_path, agent)
    rows = [{"projectId": "project-a", "agentId": f"worker-{i}"} for i in range(129)]
    enrich(dispatch, rows[:128])
    enrich(dispatch, rows[128:])
    assert len(dispatch._task_card_agent_labels) == 128 and len(calls) == 129
    dispatch._project_locks = {"project-a": SimpleNamespace(locked=lambda: True)}
    cards = enrich(dispatch, [rows[0], rows[-1]])
    assert "agentName" not in cards[0] and cards[1]["agentName"] == "worker-128"
    other = label_dispatch(tmp_path, agent)
    other._project_locks = dispatch._project_locks
    assert "agentName" not in enrich(other, rows[-1:])[0] and len(calls) == 129


@pytest.mark.parametrize("change", ["suspend", "revoke", "generation"])
def test_dispatch_owner_invalidates_labels_when_registry_authority_changes(tmp_path, change):
    from tests.test_assistant_runtime_dispatch import ClientProbe, adapter

    async def agent(project_id, *, agent_id):
        return {"projectId": project_id, "agent": {"agentId": agent_id, "displayName": "Verified"}}

    service = adapter(tmp_path, ClientProbe())
    service.management = SimpleNamespace(agent=agent)
    rows = [{"projectId": "project-a", "agentId": "worker"}]
    assert enrich(service, rows)[0]["agentName"] == "Verified"
    assert service._task_card_agent_labels
    if change == "suspend":
        service.suspend_projects()
    else:
        projects = {} if change == "revoke" else {"project-a": str(tmp_path / "project")}
        service.replace_projects({"schemaVersion": 1, "revision": 0, "projects": projects})
    assert service._task_card_agent_labels == {}


def test_agent_labels_in_one_project_do_not_skip_each_other(tmp_path):
    async def scenario():
        calls = []

        async def agent(project_id, *, agent_id):
            guard = dispatch._project_locks.setdefault(project_id, anyio.Lock())
            async with guard:
                calls.append(agent_id)
                await anyio.sleep(0)
                return {"projectId": project_id, "agent": {"agentId": agent_id,
                    "displayName": "Name " + agent_id}}

        dispatch = label_dispatch(tmp_path, agent)
        dispatch._project_locks = {}
        agents = ["researcher", "developer", "reviewer"]
        rows = [{"projectId": "same-project", "agentId": name} for name in agents]
        cards = await metadata.enrich_dispatch_cards(dispatch, rows)
        assert set(calls) == set(agents) and len(calls) == len(agents)
        assert [row.get("agentName") for row in cards] == ["Name " + name for name in agents]
        assert all("agentName" not in row for row in rows)

    anyio.run(scenario)


def test_task_control_claimed_between_labels_keeps_priority(tmp_path):
    calls = []
    busy = False

    async def agent(project_id, *, agent_id):
        nonlocal busy
        calls.append(agent_id)
        # Task control acquires the project after the first metadata read.
        busy = True
        return {"projectId": project_id, "agent": {"agentId": agent_id, "displayName": "First"}}

    dispatch = label_dispatch(tmp_path, agent)
    dispatch._project_locks = {"same-project": SimpleNamespace(locked=lambda: busy)}
    rows = [{"projectId": "same-project", "agentId": name} for name in ["first", "second"]]
    cards = enrich(dispatch, rows)
    assert calls == ["first"]
    assert cards[0]["agentName"] == "First" and "agentName" not in cards[1]


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


@pytest.mark.parametrize("namespace", ["local", "external", ""])
def test_cleanup_uses_original_task_capability_and_private_adapter_routing(monkeypatch, namespace):
    calls = []

    async def request(self, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True}

    monkeypatch.setattr(ManagedAgentBackendClient, "_request_json", request)
    client = cleanup_client(namespace)

    async def scenario():
        assert await client.preview_task_cleanup("task/1") == {"ok": True}
        assert await client.cleanup_task("task/1", "revision-1", "a" * 64) == {"ok": True}

    anyio.run(scenario)
    prefix = "/api/local-assistant/v1/external-agent/" + ("tasks" if namespace == "local" else "legacy-tasks")
    assert [row[:2] for row in calls] == [
        ("POST", prefix + "/task%2F1/cleanup/preview"), ("POST", prefix + "/task%2F1/cleanup")]
    assert all(row[2]["task_capability"] == "task-capability" and
               row[2]["management_auth"] == ("launcher-local", "authority") for row in calls)
    assert calls[0][2]["json_payload"] == {}
    assert calls[1][2]["json_payload"] == {"revision": "revision-1", "fingerprint": "a" * 64}


@pytest.mark.parametrize("namespace", ["local", "external", ""])
def test_cleanup_rejects_missing_authority_without_network(monkeypatch, namespace):
    async def forbidden(*args, **kwargs):
        pytest.fail("cleanup must not fall back to ordinary external routes")

    monkeypatch.setattr(ManagedAgentBackendClient, "_request_json", forbidden)
    client = cleanup_client(namespace, "")
    for operation in (client.preview_task_cleanup, lambda task: client.cleanup_task(task, "r", "f")):
        with pytest.raises(BackendClientError) as error:
            anyio.run(operation, "task/1")
        assert error.value.code == "LAUNCHER_AUTHORITY_REQUIRED"


def test_cleanup_translates_a_lost_local_capability_without_calling_the_source(monkeypatch):
    """A lost local capability ledger entry is its own stage: it must stay
    distinguishable from the source's authenticated 404 (a confirmed absence)."""
    async def forbidden(*args, **kwargs):
        pytest.fail("a lost local capability must never reach the source")

    monkeypatch.setattr(ManagedAgentBackendClient, "_request_json", forbidden)
    client = cleanup_client()
    client._state = {"tasks": {}, "transportNamespaces": {}}
    for operation in (client.preview_task_cleanup, lambda task: client.cleanup_task(task, "r", "f")):
        with pytest.raises(BackendClientError) as error:
            anyio.run(operation, "task/1")
        assert error.value.code == "TASK_CAPABILITY_UNAVAILABLE"
