"""Adapter recovery tests; in-process native services are not model acceptance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import anyio
import pytest

from core.assistant_runtime.dispatch import DispatchError, DispatchService
from core.external_agent.backend_client import BackendClientError, ManagedAgentBackendClient
from core.external_agent.contracts import API_PROTOCOL_VERSION, SERVER_VERSION
from core.web.services.external_agent.service import ExternalAgentTaskError
from tests.test_external_agent_backend_client import _runtime_state
from tests.test_external_agent_task_service import FakeRuntime, _agent, _service


class ClientProbe:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.instances: list[dict[str, Any]] = []
        self.get_error = False
        self.start_error = False

    def factory(self, project_root: Path, **kwargs: Any):
        probe = self
        self.instances.append({"project_root": project_root, **kwargs})

        class Client:
            async def diagnostics(self):
                probe.calls.append(("diagnostics", {}))
                return {"status": "healthy"}

            async def list_agents(self, **kwargs):
                probe.calls.append(("list", kwargs))
                return {"agents": [{"agentId": "coder"}], "count": 1}

            async def start_task(self, **kwargs):
                probe.calls.append(("start", kwargs))
                if probe.start_error:
                    raise BackendClientError("secret transport detail", code="BACKEND_UNAVAILABLE")
                return {"taskId": "eat-1", "status": "running", "pollAfterMs": 500}

            async def get_task(self, **kwargs):
                probe.calls.append(("get", kwargs))
                if probe.get_error:
                    raise BackendClientError("secret transport detail", code="BACKEND_UNAVAILABLE")
                return {"taskId": "eat-1", "status": "succeeded", "resultSummary": "native result"}

            async def get_task_for_request(self, **kwargs):
                probe.calls.append(("lookup", kwargs))
                raise BackendClientError("request not accepted", code="TASK_NOT_FOUND")

            async def heartbeat_once(self):
                probe.calls.append(("heartbeat", {}))

            async def heartbeat_task(self, *, task_id):
                probe.calls.append(("heartbeat", {"task_id": task_id}))

            async def resolve_approval(self, **kwargs):
                probe.calls.append(("approval", kwargs))
                return {"taskId": "eat-1", "status": "ok", "decision": kwargs["decision"]}

            async def cancel_task(self, **kwargs):
                probe.calls.append(("cancel", kwargs))
                return {"taskId": "eat-1", "status": "stop_unconfirmed"}

            async def shutdown(self):
                raise AssertionError("ordinary adapter operations must never shut down native tasks")

            def lifecycle(self):
                raise AssertionError("MCP lifecycle implicitly cancels tasks")

        return Client()


def adapter(tmp_path: Path, probe: ClientProbe) -> DispatchService:
    return DispatchService(tmp_path / "profile", {"project-a": tmp_path / "project"}, client_factory=probe.factory)


@pytest.mark.anyio
async def test_project_discovery_skips_offline_and_stale_backends_without_starting_tasks(tmp_path):
    calls = []

    def factory(root, **_kwargs):
        class Client:
            async def diagnostics(self):
                calls.append(root.name)
                reason = {"offline": "runtime_descriptor_missing", "stale": "runtime_revision_mismatch"}.get(root.name)
                if reason:
                    raise BackendClientError("private token and path", code=(
                        "BACKEND_UNAVAILABLE" if root.name == "offline" else "RUNTIME_IDENTITY_MISMATCH"), reason=reason)
                return {"status": "healthy"}
        return Client()

    projects = {key: tmp_path / key for key in ("online", "offline", "stale")}
    for root in projects.values():
        root.mkdir()
    service = DispatchService(tmp_path / "profile", projects, client_factory=factory)
    result = await service.available_projects()
    assert result["projects"] == [{"projectId": "online"}]
    skipped = {row["projectId"]: row for row in result["skippedProjects"]}
    assert set(skipped) == {"offline", "stale"}
    assert skipped["offline"]["code"] == "BACKEND_UNAVAILABLE"
    assert "未发现" in skipped["offline"]["message"]
    assert "后台仍在运行其他版本" in skipped["stale"]["message"]
    # Only identity drift carries the backend-free restart path; an offline
    # backend has nothing a Launcher-side restart could prove.
    assert "recovery" not in skipped["offline"]
    assert skipped["stale"]["recovery"] == {
        "action": "project_lifecycle", "operation": "restart", "projectId": "stale",
        "tool": "personal_assistant_manage_tool", "receiptAction": "project_lifecycle_receipt",
        "bypassesProjectBackend": True}
    assert "project_lifecycle" in skipped["stale"]["message"]
    assert "private" not in json.dumps(result)
    assert sorted(calls) == ["offline", "online", "stale"]
    assert service.list_dispatches() == []


@pytest.mark.anyio
async def test_project_discovery_bounds_slow_checks_and_keeps_healthy_projects(tmp_path, monkeypatch):
    from core.assistant_runtime import dispatch
    monkeypatch.setattr(dispatch, "_PROJECT_DISCOVERY_SECONDS", 0.05)

    def factory(root, **_kwargs):
        class Client:
            async def diagnostics(self):
                if root.name == "slow":
                    await anyio.sleep_forever()
                return {"status": "healthy"}
        return Client()

    projects = {key: tmp_path / key for key in ("healthy", "slow")}
    for root in projects.values():
        root.mkdir()
    service = DispatchService(tmp_path / "profile", projects, client_factory=factory)
    with anyio.fail_after(1):
        result = await service.available_projects()
    assert result["projects"] == [{"projectId": "healthy"}]
    assert result["skippedProjects"][0]["projectId"] == "slow"
    assert result["skippedProjects"][0]["code"] == "PROJECT_CHECK_TIMEOUT"


@pytest.mark.anyio
async def test_untrusted_backend_message_does_not_become_a_diagnostic_reason(tmp_path):
    def factory(*_args, **_kwargs):
        class Client:
            async def diagnostics(self):
                raise BackendClientError("private token and path", code="RUNTIME_IDENTITY_MISMATCH")
        return Client()

    root = tmp_path / "project"
    root.mkdir()
    service = DispatchService(tmp_path / "profile", {"project": root}, client_factory=factory)
    with pytest.raises(DispatchError) as error:
        await service.discover("project")
    assert "版本或项目身份校验失败" in str(error.value)
    assert "后台仍在运行其他版本" not in str(error.value)
    assert "private" not in str(error.value)
    # A code-only identity failure still points at the same backend-free restart.
    assert error.value.recovery == {
        "action": "project_lifecycle", "operation": "restart", "projectId": "project",
        "tool": "personal_assistant_manage_tool", "receiptAction": "project_lifecycle_receipt",
        "bypassesProjectBackend": True}


@pytest.mark.anyio
async def test_identity_drift_error_names_the_backend_free_restart_but_other_failures_do_not(tmp_path):
    """Every backend-bound action is rejected on drift; the error must name the one exit.

    ``project_lifecycle`` reaches Electron main over the host transport and never
    opens a project-backend client, so it stays callable while this adapter's own
    diagnostics gate refuses. Other failures get no recovery hint: a restart would
    prove nothing for an offline backend or an unauthorized project.
    """
    failure = {"code": "RUNTIME_IDENTITY_MISMATCH", "reason": "runtime_revision_mismatch"}

    def factory(*_args, **_kwargs):
        class Client:
            async def diagnostics(self):
                raise BackendClientError("private token and path", **failure)

            async def list_agents(self, **_kwargs):
                raise AssertionError("a drifted backend must be refused before any management call")
        return Client()

    root = tmp_path / "project"
    root.mkdir()
    service = DispatchService(tmp_path / "profile", {"project-a": root}, client_factory=factory)
    with pytest.raises(DispatchError) as drift:
        await service.discover("project-a")
    assert drift.value.code == "RUNTIME_IDENTITY_MISMATCH"
    assert drift.value.recovery == {
        "action": "project_lifecycle", "operation": "restart", "projectId": "project-a",
        "tool": "personal_assistant_manage_tool", "receiptAction": "project_lifecycle_receipt",
        "bypassesProjectBackend": True}
    message = str(drift.value)
    assert "后台仍在运行其他版本" in message
    for needle in ("project_lifecycle", "operation=restart", "project_lifecycle_receipt", "原 ID 重试"):
        assert needle in message
    assert "private" not in message and "token" not in message
    # The receipt path is keyed by the same opaque IDs the model already holds;
    # nothing in the hint reveals a path, credential or backend URL.
    assert all(isinstance(value, (str, bool)) for value in drift.value.recovery.values())

    failure.update(code="BACKEND_UNAVAILABLE", reason="runtime_descriptor_missing")
    with pytest.raises(DispatchError) as offline:
        await service.discover("project-a")
    assert offline.value.code == "BACKEND_UNAVAILABLE"
    assert offline.value.recovery is None
    assert "project_lifecycle" not in str(offline.value)

    with pytest.raises(DispatchError) as unauthorized:
        await service.discover("project-b")
    assert unauthorized.value.code == "PROJECT_NOT_AUTHORIZED"
    assert unauthorized.value.recovery is None


@pytest.mark.anyio
async def test_project_discovery_drops_authorization_revoked_after_a_successful_check(tmp_path):
    entered = anyio.Event()
    finish = anyio.Event()

    def factory(root, **_kwargs):
        class Client:
            async def diagnostics(self):
                if root.name == "slow":
                    entered.set()
                    await finish.wait()
                return {"status": "healthy"}
        return Client()

    projects = {key: tmp_path / key for key in ("healthy", "slow")}
    for root in projects.values():
        root.mkdir()
    service = DispatchService(tmp_path / "profile", projects, client_factory=factory)

    async def revoke():
        await entered.wait()
        service.replace_projects({"schemaVersion": 1, "revision": 0, "projects": {"slow": str(projects["slow"])}})
        finish.set()

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(revoke)
        result = await service.available_projects()
    assert result["projects"] == [{"projectId": "slow"}]
    assert result["skippedProjects"][0]["code"] == "PROJECT_BINDING_CHANGED"


@pytest.mark.anyio
async def test_project_discovery_does_not_rotate_or_drain_a_borrowed_task_client(tmp_path):
    from types import SimpleNamespace
    probe = ClientProbe()
    root = tmp_path / "project"
    root.mkdir()
    service = DispatchService(tmp_path / "profile", {"project": root}, client_factory=probe.factory)
    borrowed = SimpleNamespace(borrowers=1, closing=False, drained=anyio.Event())
    service._active_project_clients["project"] = borrowed
    with anyio.fail_after(1):
        result = await service.available_projects()
    assert result["projects"] == [{"projectId": "project"}]
    assert service._active_project_clients["project"] is borrowed
    assert borrowed.closing is False and borrowed.borrowers == 1


@pytest.mark.anyio
async def test_project_discovery_pages_large_registries_within_the_model_budget(tmp_path):
    from tests.test_assistant_runtime_actions import _through_native_model_budget
    projects = {}
    for index in range(128):
        root = tmp_path / str(index)
        root.mkdir()
        projects[f"project-{index:03d}-" + "x" * 148] = root
    service = DispatchService(tmp_path / "profile", projects)
    first = await service.available_projects()
    assert first["projects"] == []
    assert len(first["skippedProjects"]) == 8
    assert first["nextOffset"] == 8 and first["total"] == 128
    assert "未发现" in first["message"]
    raw, outcome, facts, _rendered = _through_native_model_budget(first)
    assert len(raw) < 4000 and outcome is None and not facts.truncated
    last = await service.available_projects(offset=120, expected_revision=first["registryRevision"])
    assert len(last["skippedProjects"]) == 8 and last["nextOffset"] is None
    assert {r["projectId"] for r in first["skippedProjects"]}.isdisjoint(
        {r["projectId"] for r in last["skippedProjects"]})
    service.replace_projects({"schemaVersion": 1, "revision": 0,
                              "projects": {key: str(root) for key, root in list(projects.items())[1:]}})
    with pytest.raises(DispatchError) as changed:
        await service.available_projects(offset=8, expected_revision=first["registryRevision"])
    assert changed.value.code == "PROJECT_REGISTRY_CHANGED"
    with pytest.raises(DispatchError):
        await service.available_projects(offset=8)


@pytest.mark.anyio
async def test_project_discovery_does_not_publish_arbitrary_backend_error_codes(tmp_path):
    def factory(*_args, **_kwargs):
        class Client:
            async def diagnostics(self):
                raise BackendClientError("PRIVATE_TOKEN", code="PRIVATE_TOKEN")
        return Client()

    root = tmp_path / "project"
    root.mkdir()
    service = DispatchService(tmp_path / "profile", {"project": root}, client_factory=factory)
    result = await service.available_projects()
    assert result["skippedProjects"][0]["code"] == "BACKEND_ERROR"
    assert "PRIVATE_TOKEN" not in json.dumps(result)


async def start(service: DispatchService, **kwargs):
    return await service.dispatch(
        "project-a", agent_id="coder", task="private original task", dispatch_id="dispatch-1", **kwargs
    )


@pytest.mark.anyio
async def test_registry_is_the_only_path_authority_and_credentials_are_separate(tmp_path):
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    assert service.project_ids() == ("project-a",)
    with pytest.raises(DispatchError) as rejected:
        await service.discover(str(tmp_path / "unregistered"))
    assert rejected.value.code == "PROJECT_NOT_AUTHORIZED"
    assert probe.instances == []
    await service.discover("project-a")
    await start(service)
    for instance in probe.instances:
        assert instance["project_root"] == (tmp_path / "project").resolve()
        assert instance["state_path"].is_relative_to((tmp_path / "profile").resolve())
        assert "mcp" not in instance["state_path"].parts


@pytest.mark.anyio
async def test_dispatch_refs_survive_restart_without_prompt_or_duplicate_start(tmp_path):
    probe = ClientProbe()
    first = await start(adapter(tmp_path, probe))
    assert first["nativeTaskId"] == "eat-1"
    service = adapter(tmp_path, probe)
    replay = await start(service)
    receipt = await service.reconcile("dispatch-1")
    assert replay["clientRequestId"] == first["clientRequestId"]
    assert receipt["receipt"]["status"] == "succeeded"
    assert receipt["completionEvidence"]["businessAcceptance"] == "not_evaluated"
    assert [name for name, _ in probe.calls].count("start") == 1
    assert len(probe.instances) == 2  # recreated and revalidated on reconnect
    assert [name for name, _ in probe.calls].count("diagnostics") == 2
    serialized = "".join(path.read_text(encoding="utf-8") for path in (tmp_path / "profile").rglob("*.json"))
    assert "private original task" not in serialized
    assert service.list_dispatches()[0]["receipt"]["resultSummary"] == "native result"


@pytest.mark.anyio
async def test_changed_payload_or_rebound_project_cannot_reuse_dispatch(tmp_path):
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    await start(service)
    with pytest.raises(DispatchError) as conflict:
        await service.dispatch("project-a", agent_id="coder", task="different", dispatch_id="dispatch-1")
    assert conflict.value.code == "DISPATCH_CONFLICT"
    rebound = DispatchService(tmp_path / "profile", {"project-a": tmp_path / "other"}, client_factory=probe.factory)
    with pytest.raises(DispatchError) as changed:
        await rebound.reconcile("dispatch-1")
    assert changed.value.code == "PROJECT_BINDING_CHANGED"


@pytest.mark.anyio
async def test_known_task_transport_failure_is_recorded_and_never_redispatched(tmp_path):
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    await start(service)
    probe.get_error = True
    with pytest.raises(DispatchError) as failure:
        await service.reconcile("dispatch-1")
    assert failure.value.code == "BACKEND_UNAVAILABLE"
    assert "secret" not in str(failure.value)
    stored = service.list_dispatches()[0]
    assert stored["nativeTaskId"] == "eat-1"
    assert stored["lastError"]["code"] == "BACKEND_UNAVAILABLE"
    probe.get_error = False
    recovered = await adapter(tmp_path, probe).reconcile("dispatch-1")
    assert recovered["lastError"] is None
    assert [name for name, _ in probe.calls].count("start") == 1
    assert not {"shutdown", "cancel"}.intersection(name for name, _ in probe.calls)


@pytest.mark.anyio
async def test_unconfirmed_start_needs_explicit_original_dispatch_retry(tmp_path):
    probe = ClientProbe()
    probe.start_error = True
    service = adapter(tmp_path, probe)
    with pytest.raises(DispatchError):
        await start(service)
    first_request = next(args["client_request_id"] for name, args in probe.calls if name == "start")
    recovered = await adapter(tmp_path, probe).reconcile("dispatch-1")
    assert recovered["nativeTaskId"] == ""
    assert [name for name, _ in probe.calls].count("start") == 1
    probe.start_error = False
    await start(adapter(tmp_path, probe))
    assert [args["client_request_id"] for name, args in probe.calls if name == "start"] == [first_request] * 2


@pytest.mark.anyio
async def test_approval_cancel_and_heartbeat_are_explicit_native_operations(tmp_path):
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    await start(service)
    await service.heartbeat()
    approved = await service.resolve_approval("dispatch-1", approval_id="approval-1", decision="accept", expected_revision="revision-1")
    assert approved["receipt"]["status"] == "succeeded"
    assert next(args for name, args in probe.calls if name == "approval") == {
        "task_id": "eat-1", "approval_id": "approval-1", "decision": "accept", "expected_revision": "revision-1", "reason": ""
    }
    cancelled = await service.cancel("dispatch-1")
    assert cancelled["receipt"]["status"] == "stop_unconfirmed"
    assert [name for name, _ in probe.calls].count("cancel") == 1
    assert any(name == "heartbeat" for name, _ in probe.calls)


@pytest.mark.anyio
async def test_bound_preview_is_ephemeral_and_decision_preserves_exact_identity(tmp_path):
    probe = ClientProbe()
    preview = {"taskId": "eat-1", "requestId": "approval-1", "agentId": "coder", "toolName": "exec_command",
               "revision": "a" * 64, "argumentsJson": '{"secret":"private-fixture"}', "executionArgumentsJson": "{}"}
    def factory(project_root, **kwargs):
        client = probe.factory(project_root, **kwargs)
        async def get_preview(**payload):
            probe.calls.append(("preview", payload))
            return dict(preview)
        async def decide(**payload):
            probe.calls.append(("bound-decision", payload))
            return {"status": "ok", "taskId": payload["task_id"], "approvalId": payload["approval_id"], "decision": payload["decision"]}
        client.preview_bound_approval, client.resolve_bound_approval = get_preview, decide
        return client
    service = DispatchService(tmp_path / "profile", {"project-a": tmp_path / "project"}, client_factory=factory)
    await start(service)
    result = await service.preview_bound_approval("dispatch-1", task_id="eat-1", approval_id="approval-1")
    assert result["argumentsJson"] == preview["argumentsJson"]
    assert "private-fixture" not in "".join(path.read_text(encoding="utf-8") for path in (tmp_path / "profile").rglob("*.json"))
    with pytest.raises(DispatchError):
        await service.decide_bound_approval("dispatch-1", task_id="wrong", approval_id="approval-1", revision="a" * 64, decision="accept")
    with pytest.raises(DispatchError):
        await service.decide_bound_approval("dispatch-1", task_id="eat-1", approval_id="approval-1", revision="", decision="accept")
    result = await service.decide_bound_approval("dispatch-1", task_id="eat-1", approval_id="approval-1", revision="a" * 64, decision="accept")
    assert result["decision"] == "accept" and result["dispatchId"] == "dispatch-1"
    assert [payload for name, payload in probe.calls if name == "bound-decision"] == [{"task_id": "eat-1", "approval_id": "approval-1", "decision": "accept", "expected_revision": "a" * 64}]
    preview["agentId"] = "other"
    with pytest.raises(DispatchError):
        await service.preview_bound_approval("dispatch-1", task_id="eat-1", approval_id="approval-1")


@pytest.fixture
def journal_source(monkeypatch):
    from copy import deepcopy
    from core.assistant_runtime import native
    runtime = {"agentId": "assistant-a", "sessionId": "own-session", "turnId": "turn-a"}
    original = {**runtime, "eventId": "user-a", "content": "只回复 E3_RECEIPT_3E159D2DFC294ED1"}
    current = dict(original)
    def read(caller, *, source_ref=None):
        return deepcopy(original if source_ref is not None else current)
    monkeypatch.setattr(native, "read_task_source", read)
    return runtime, original, current


@pytest.mark.anyio
async def test_original_native_span_retries_after_restart_without_recopy_or_new_task(tmp_path, journal_source):
    runtime, original, current = journal_source
    probe = ClientProbe()
    probe.start_error = True
    service = adapter(tmp_path, probe)
    with pytest.raises(DispatchError):
        await service.dispatch_from_source("project-a", agent_id="coder", dispatch_id="anchored", runtime=runtime, task_source={})
    stored = json.loads(service._path("anchored").read_text(encoding="utf-8"))
    assert stored["sourceRef"]["eventId"] == "user-a"
    assert original["content"] not in json.dumps(stored, ensure_ascii=False)
    runtime["turnId"] = "turn-new"
    current.update(turnId="turn-new", eventId="user-new", content="查询或恢复原任务")
    probe.start_error = False
    restarted = adapter(tmp_path, probe)
    recovered = await restarted.dispatch_from_source("project-a", agent_id="coder", dispatch_id="anchored", runtime=runtime, task_source={})
    await restarted.dispatch_from_source("project-a", agent_id="coder", dispatch_id="anchored", runtime=runtime, task_source={})
    starts = [args for name, args in probe.calls if name == "start"]
    assert [args["task"] for args in starts] == [original["content"], original["content"]]
    assert [args["client_request_id"] for args in starts] == ["launcher-assistant:anchored"] * 2
    assert starts[1]["require_existing_capability"] is True
    assert recovered["nativeTaskId"] == "eat-1" and "sourceRef" not in recovered


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["selector", "raw", "agent", "title", "corrupt_ref"])
async def test_changed_model_source_or_task_parameters_cannot_reuse_original_dispatch(tmp_path, journal_source, change):
    runtime, original, _ = journal_source
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    params = {"agent_id": "coder", "dispatch_id": "anchored", "runtime": runtime, "task_source": {}}
    await service.dispatch_from_source("project-a", **params)
    if change == "selector":
        params["task_source"] = {"start_after": "只回复 "}
    elif change == "raw":
        params.pop("task_source")
        params["task"] = original["content"]
    elif change in {"agent", "title"}:
        params["agent_id" if change == "agent" else "title"] = "changed"
    else:
        record = json.loads(service._path("anchored").read_text(encoding="utf-8"))
        record["sourceRef"]["contentHash"] = "0" * 64
        service._path("anchored").write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(DispatchError) as conflict:
        await adapter(tmp_path, probe).dispatch_from_source("project-a", **params)
    assert conflict.value.code == "DISPATCH_CONFLICT"
    assert [name for name, _ in probe.calls].count("start") == 1


@pytest.mark.anyio
async def test_raw_original_source_and_corrupt_ref_receipt_stay_separate(tmp_path, journal_source):
    runtime, original, current = journal_source
    probe = ClientProbe()
    probe.start_error = True
    service = adapter(tmp_path, probe)
    params = {"agent_id": "coder", "dispatch_id": "raw-source", "runtime": runtime, "task": original["content"]}
    with pytest.raises(DispatchError):
        await service.dispatch_from_source("project-a", **params)
    runtime["turnId"] = "next"
    current.update(turnId="next", eventId="user-next", content="恢复")
    probe.start_error = False
    await adapter(tmp_path, probe).dispatch_from_source("project-a", **params)
    record = json.loads(service._path("raw-source").read_text(encoding="utf-8"))
    record["sourceRef"] = {"damaged": True}
    service._path("raw-source").write_text(json.dumps(record), encoding="utf-8")
    assert (await adapter(tmp_path, probe).reconcile("raw-source"))["receipt"]["status"] == "succeeded"
    assert [name for name, _ in probe.calls].count("start") == 2


@pytest.mark.anyio
async def test_write_dispatch_is_exact_source_bound_and_reuses_original_request(tmp_path, journal_source):
    runtime, original, current = journal_source
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    params = {"agent_id": "coder", "dispatch_id": "write-a", "runtime": runtime, "task": original["content"]}
    probe.start_error = True
    with pytest.raises(DispatchError):
        await service.dispatch_write_from_source("project-a", **params)
    record = json.loads(service._path("write-a").read_text(encoding="utf-8"))
    assert original["content"] not in json.dumps(record, ensure_ascii=False)
    probe.start_error = False
    restarted = adapter(tmp_path, probe)
    await restarted.dispatch_write_from_source("project-a", **params)
    await restarted.dispatch_write_from_source("project-a", **params)
    starts = [args for name, args in probe.calls if name == "start"]
    assert [call["permission_profile"] for call in starts] == ["workspace_write"] * 2
    assert [call["task"] for call in starts] == [original["content"]] * 2
    assert [call["client_request_id"] for call in starts] == ["launcher-assistant:write-a"] * 2
    assert starts[1]["require_existing_capability"] is True
    runtime["turnId"] = "turn-new"
    current.update(turnId="turn-new", eventId="user-new", content="查询原请求")
    with pytest.raises(DispatchError) as stale:
        await restarted.dispatch_write_from_source("project-a", **params)
    assert stale.value.code == "TASK_SOURCE_MISMATCH"
    assert [name for name, _ in probe.calls].count("start") == 2


@pytest.mark.anyio
@pytest.mark.parametrize("content,task", [
    ("不要修改文件", "修改文件"),
    ("修改文件，但不要提交", "修改文件"),
    ("修改文件，但不要提交", "但不要提交"),
])
async def test_write_dispatch_rejects_omitted_current_message_constraints(tmp_path, journal_source, content, task):
    runtime, original, current = journal_source
    original["content"] = current["content"] = content
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    with pytest.raises(DispatchError) as error:
        await service.dispatch_write_from_source("project-a", agent_id="coder", dispatch_id="write-a", runtime=runtime, task=task)
    assert error.value.code == "TASK_SOURCE_MISMATCH"
    assert not service._path("write-a").exists() and not probe.calls


@pytest.mark.anyio
async def test_write_dispatch_only_normalizes_complete_message_outer_whitespace(tmp_path, journal_source):
    runtime, original, current = journal_source
    original["content"] = current["content"] = " \n  修改文件，但不要提交  \n"
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    await service.dispatch_write_from_source("project-a", agent_id="coder", dispatch_id="write-a", runtime=runtime, task="修改文件，但不要提交")
    assert next(kwargs for name, kwargs in probe.calls if name == "start")["task"] == "修改文件，但不要提交"


@pytest.mark.anyio
async def test_long_write_source_refuses_partial_message_instead_of_truncating(tmp_path, journal_source):
    runtime, original, current = journal_source
    original["content"] = current["content"] = "x" * 12001
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    with pytest.raises(DispatchError) as error:
        await service.dispatch_write_from_source("project-a", agent_id="coder", dispatch_id="write-a", runtime=runtime, task="x" * 12000)
    assert error.value.code == "TASK_SOURCE_TOO_LONG"
    assert not service._path("write-a").exists() and not probe.calls


@pytest.mark.anyio
async def test_read_only_dispatch_retains_existing_substring_semantics(tmp_path, journal_source):
    runtime, original, current = journal_source
    original["content"] = current["content"] = "先查询，然后修改文件，但不要提交"
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    await service.dispatch_from_source("project-a", agent_id="coder", dispatch_id="read-a", runtime=runtime, task="先查询")
    start_args = next(kwargs for name, kwargs in probe.calls if name == "start")
    assert start_args["task"] == "先查询" and start_args["permission_profile"] == "read_only"


@pytest.mark.anyio
async def test_write_dispatch_rejects_unverified_or_changed_task_before_start(tmp_path, journal_source):
    runtime, original, _ = journal_source
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    for task in (original["content"] + " 并修改文件", " " + original["content"]):
        with pytest.raises(DispatchError):
            await service.dispatch_write_from_source("project-a", agent_id="coder", dispatch_id="write-a", runtime=runtime, task=task)
    assert not service._path("write-a").exists()
    assert not probe.calls


@pytest.mark.anyio
async def test_write_and_read_dispatch_cannot_share_an_id(tmp_path, journal_source):
    runtime, original, _ = journal_source
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    params = {"agent_id": "coder", "dispatch_id": "same-a", "runtime": runtime, "task": original["content"]}
    await service.dispatch_from_source("project-a", **params)
    with pytest.raises(DispatchError) as conflict:
        await service.dispatch_write_from_source("project-a", **params)
    assert conflict.value.code == "DISPATCH_CONFLICT"
    assert [name for name, _ in probe.calls].count("start") == 1


@pytest.mark.anyio
async def test_unknown_legacy_model_retry_denied_but_known_raw_repeat_is_read_only(tmp_path, journal_source):
    runtime, _, _ = journal_source
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    probe.start_error = True
    with pytest.raises(DispatchError):
        await start(service)
    before = len(probe.calls)
    with pytest.raises(DispatchError) as denied:
        await service.dispatch_from_source("project-a", agent_id="coder", dispatch_id="dispatch-1", runtime=runtime,
            task="private original task")
    assert denied.value.code == "TASK_SOURCE_UNAVAILABLE" and len(probe.calls) == before
    probe.start_error = False
    await start(service)
    before = len(probe.calls)
    result = await service.dispatch_from_source("project-a", agent_id="coder", dispatch_id="dispatch-1", runtime=runtime,
        task="private original task")
    assert result["nativeTaskId"] == "eat-1" and len(probe.calls) == before


@pytest.mark.anyio
async def test_concurrent_retries_and_invalid_ids_do_not_duplicate_or_escape_records(tmp_path):
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    async with anyio.create_task_group() as group:
        for _ in range(4):
            group.start_soon(start, service)
    assert [name for name, _ in probe.calls].count("start") == 1
    with pytest.raises(DispatchError) as invalid:
        await service.dispatch("project-a", agent_id="coder", task="read", dispatch_id="../outside")
    assert invalid.value.code == "INVALID_DISPATCH"
    assert len(service.list_dispatches()) == 1


@pytest.mark.anyio
async def test_corrupted_reference_is_retained_and_never_recreated(tmp_path):
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    await start(service)
    path = next((tmp_path / "profile" / "assistant_dispatch" / "records").glob("*.json"))
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(DispatchError) as corrupt:
        await start(service)
    assert corrupt.value.code == "DISPATCH_STATE_CORRUPT"
    assert path.read_text(encoding="utf-8") == "{broken"
    assert [name for name, _ in probe.calls].count("start") == 1


@pytest.mark.anyio
async def test_slow_project_does_not_block_other_project_heartbeats(tmp_path):
    probe = ClientProbe()
    other_project_queried = anyio.Event()

    def factory(project_root, **kwargs):
        client = probe.factory(project_root, **kwargs)
        get_task = client.get_task

        async def read(**arguments):
            if project_root.name == "slow":
                await other_project_queried.wait()
                raise BackendClientError("offline", code="BACKEND_UNAVAILABLE")
            other_project_queried.set()
            return await get_task(**arguments)

        client.get_task = read
        return client

    service = DispatchService(tmp_path / "profile", {"slow": tmp_path / "slow", "fast": tmp_path / "fast"}, client_factory=factory)
    for project in ("slow", "fast"):
        await service.dispatch(project, agent_id="coder", task="read", dispatch_id=f"dispatch-{project}")
    with anyio.fail_after(2):
        results = await service.heartbeat()
    by_project = {item["projectId"]: item for item in results}
    assert by_project["slow"]["lastError"]["code"] == "BACKEND_UNAVAILABLE"
    assert by_project["fast"]["receipt"]["status"] == "succeeded"


def native_adapter(tmp_path: Path, runtime: FakeRuntime, *, drop_first_start=False):
    """Real client + native task service/policy/store, with no live model or backend."""
    root = tmp_path / "project"
    _runtime_state(root)
    service = _service(tmp_path / "native-task-store", runtime)
    calls: list[httpx.Request] = []
    dropped = False

    def handler(request: httpx.Request):
        nonlocal dropped
        calls.append(request)
        path = request.url.path
        if path == "/api/control-token":
            return httpx.Response(200, json={"header": "X-Vibelution-Control-Token", "controlToken": "test-control"})
        if path.endswith("/info"):
            return httpx.Response(200, json={"apiProtocolVersion": API_PROTOCOL_VERSION, "serverVersion": SERVER_VERSION, "projectRoot": str(root.resolve()), "runtimeSourceRevision": "rev-1"})
        owner = request.headers.get("X-Vibelution-External-Agent-Task-Capability", "")
        connection = request.headers.get("X-Vibelution-External-Agent-Connection", "")
        payload = json.loads(request.content) if request.content else {}
        try:
            if path.endswith("/agents"):
                result = service.list_agents()
            elif path.endswith("/task-request"):
                result = service.get_task_for_request(owner_id=owner,
                    client_request_id=request.url.params["client_request_id"], include_private=True)
            elif path.endswith("/tasks"):
                result = service.start_task(owner_id=owner, adapter_connection_id=connection, capabilities=set(), runtime_revision="rev-1", include_private=True, **payload)
                if drop_first_start and not dropped:
                    dropped = True
                    raise httpx.ReadError("response lost after commit", request=request)
            elif path.endswith("/heartbeat"):
                result = service.heartbeat(owner_id=owner, task_id=path.split("/")[-2], adapter_connection_id=connection, **payload)
            elif path.endswith("/preview"):
                parts = path.split("/")
                result = service.preview_task_approval(owner_id=owner, task_id=parts[-4], approval_id=parts[-2])
            elif path.endswith("/resolve-bound"):
                parts = path.split("/")
                result = service.resolve_task_approval_bound(owner_id=owner, task_id=parts[-4], approval_id=parts[-2],
                    decision=payload["decision"], expected_revision=payload["expected_revision"])
            elif path.endswith("/resolve"):
                parts = path.split("/")
                result = service.resolve_approval(owner_id=owner, capabilities=set(), task_id=parts[-4],
                    approval_id=parts[-2], decision=payload["decision"],
                    expected_revision=payload["expected_revision"], reason=payload["reason"])
            elif path.endswith("/cancel"):
                result = service.cancel_task(owner_id=owner, task_id=path.split("/")[-2])
            else:
                result = service.get_task(owner_id=owner, task_id=path.rsplit("/", 1)[-1])
        except ExternalAgentTaskError as exc:
            return httpx.Response(404, json={"detail": {"code": exc.code, "message": str(exc)}})
        return httpx.Response(200, json=result)

    transport = httpx.MockTransport(handler)
    factory = lambda project_root, **kwargs: ManagedAgentBackendClient(project_root, transport=transport, **kwargs)
    adapter_service = DispatchService(tmp_path / "profile", {"project-a": root}, client_factory=factory)
    return adapter_service, service, calls, factory


@pytest.mark.anyio
async def test_bound_preview_and_accept_cross_real_client_and_task_service(tmp_path):
    from dataclasses import replace
    runtime = FakeRuntime(agents=[_agent(configRevision=1, configHash="config-hash")])
    adapter_service, native_service, calls, _ = native_adapter(tmp_path, runtime)
    decisions = []
    def preview(**identity):
        return {"taskId": identity["task_id"], "sessionId": identity["session_id"], "agentId": identity["agent_id"],
                "requestId": identity["request_id"], "turnId": identity["turn_id"], "callId": "call-1", "toolName": "write_file_tool",
                "revision": "a" * 64, "approval": "always", "risk": "write", "permissionPreset": "request_approval",
                "decisionFingerprint": "policy", "configRevision": 1, "configHash": "config-hash",
                "argumentsJson": '{"content":"private-fixture"}', "executionArgumentsJson": '{"content":"private-fixture"}'}
    def resolve(**kwargs):
        if kwargs["expected_revision"] != "a" * 64:
            raise ValueError("stale")
        decisions.append(kwargs)
    native_service.dependencies = replace(native_service.dependencies, preview_bound_approval=preview, resolve_bound_approval=resolve)
    started = await start(adapter_service)
    preview_result = await adapter_service.preview_bound_approval("dispatch-1", task_id=started["nativeTaskId"], approval_id="approval-1")
    assert preview_result["argumentsJson"] == '{"content":"private-fixture"}'
    result = await adapter_service.decide_bound_approval("dispatch-1", task_id=started["nativeTaskId"], approval_id="approval-1", revision=preview_result["revision"], decision="accept")
    assert result["decision"] == "accept" and decisions[0]["session_id"] == "session-1" and decisions[0]["turn_id"] == "turn-1"
    assert len([request for request in calls if request.url.path.endswith("/resolve-bound")]) == 1
    assert "private-fixture" not in "".join(path.read_text(encoding="utf-8") for path in (tmp_path / "profile").rglob("*.json"))


@pytest.mark.anyio
@pytest.mark.parametrize("decision", ["accept", "decline"])
async def test_bound_decision_reaches_live_native_waiter_without_persisting_preview(tmp_path, decision, monkeypatch):
    import threading
    import time
    from dataclasses import replace
    from core.web.services.session import tool_approvals
    from core.web.services.external_agent.approval_binding import freeze_arguments, register_external_session, unregister_external_session
    from core.web.services import agent_directory_service, agent_config_authority
    runtime = FakeRuntime(agents=[_agent(configRevision=1, configHash="config-hash")])
    monkeypatch.setattr(agent_directory_service, "load_agent_record", lambda *_args, **_kwargs: runtime.agents[0])
    monkeypatch.setattr(agent_config_authority, "agent_config_hash", lambda _agent: "config-hash")
    adapter_service, native_service, _, factory = native_adapter(tmp_path, runtime)
    workers, outcome = [], {}
    args = {"cmd": "echo private-fixture"}
    def submit(session_id, content, **kwargs):
        def wait():
            outcome["value"] = tool_approvals.authorize_or_wait(session_id=session_id, turn_id="turn-1", agent_id="coder",
                call_id="call-1", tool_name="exec_command", tool_args=args, approval="always", risk="execute",
                decision_fingerprint="policy", config_revision=1, config_hash="config-hash", permission_preset="request_approval",
                timeout_seconds=10, external_task_id=kwargs["message_metadata"]["taskId"],
                external_arguments_json=freeze_arguments(args), external_execution_arguments_json=freeze_arguments(args))
        worker = threading.Thread(target=wait)
        workers.append(worker)
        worker.start()
        return {"turnId": "turn-1"}
    native_service.dependencies = replace(native_service.dependencies, submit_message=submit,
        register_approval_session=register_external_session, unregister_approval_session=unregister_external_session,
        list_approvals=tool_approvals.list_tool_approval_requests,
        preview_bound_approval=tool_approvals.preview_external_task_approval,
        resolve_bound_approval=tool_approvals.resolve_external_task_approval)
    task_id = ""
    try:
        started = await start(adapter_service)
        task_id = started["nativeTaskId"]
        deadline = time.monotonic() + 3
        while not tool_approvals.list_tool_approval_requests("session-1", status="pending"):
            assert time.monotonic() < deadline
            await anyio.sleep(0.01)
        request = tool_approvals.list_tool_approval_requests("session-1", status="pending")[0]
        restored = DispatchService(tmp_path / "profile", {"project-a": tmp_path / "project"}, client_factory=factory)
        preview = await restored.preview_bound_approval("dispatch-1", task_id=task_id, approval_id=request["requestId"])
        assert json.loads(preview["executionArgumentsJson"]) == args
        try:
            await restored.decide_bound_approval("dispatch-1", task_id=task_id, approval_id=request["requestId"], revision=preview["revision"], decision=decision)
        except DispatchError as exc:
            pytest.fail(f"native approval failed: {exc.code}")
        workers[0].join(timeout=3)
        assert not workers[0].is_alive() and outcome["value"].allowed == (decision == "accept")
        assert "private-fixture" not in "".join(path.read_text(encoding="utf-8") for path in (tmp_path / "profile").rglob("*.json"))
    finally:
        tool_approvals.reset_tool_approval_state(clear_durable=False)
        for worker in workers:
            worker.join(timeout=3)
        if task_id:
            unregister_external_session(task_id=task_id, session_id="session-1", agent_id="coder")


@pytest.mark.anyio
async def test_presented_decline_stays_bound_to_original_task_turn_and_request_after_restart(tmp_path):
    runtime = FakeRuntime()
    adapter_service, native_service, calls, factory = native_adapter(tmp_path, runtime)
    started = await start(adapter_service)
    task = native_service.store.get_task(started["nativeTaskId"])
    session, turn = task["sessionId"], task["turnId"]
    runtime.approvals[session] = [
        {"requestId": "approval-other-turn", "turnId": "other", "status": "pending", "toolName": "exec_command", "argumentSummary": {"commandPreview": "other"}, "decisionFingerprint": "fp-other"},
        {"requestId": "approval-1", "turnId": turn, "status": "pending", "toolName": "write_file_tool", "argumentSummary": {"pathPreview": "example.txt"}, "decisionFingerprint": "fp-1"},
    ]
    observed = await adapter_service.reconcile("dispatch-1")
    assert [a["approvalId"] for a in observed["receipt"]["pendingApprovals"]] == ["approval-1"]
    restored = DispatchService(tmp_path / "profile", {"project-a": tmp_path / "project"}, client_factory=factory)
    runtime.approvals[session][1]["decisionFingerprint"] = ""
    empty = await restored.reconcile("dispatch-1")
    assert empty["receipt"]["pendingApprovals"][0]["revision"] == ""
    for revision in ("", " ", "fp-1\n"):
        with pytest.raises(DispatchError):
            await restored.decline_presented_approval("dispatch-1", task_id=started["nativeTaskId"], approval_id="approval-1", expected_revision=revision)
    assert runtime.resolve_calls == []
    runtime.approvals[session][1]["decisionFingerprint"] = "fp-1"
    for task_id, approval_id, revision in [("wrong-task", "approval-1", "fp-1"),
                                           (started["nativeTaskId"], "approval-other-turn", "fp-other"),
                                           (started["nativeTaskId"], "approval-1", "stale")]:
        with pytest.raises(DispatchError):
            await restored.decline_presented_approval("dispatch-1", task_id=task_id, approval_id=approval_id, expected_revision=revision)
    assert runtime.resolve_calls == []
    result = await restored.decline_presented_approval("dispatch-1", task_id=started["nativeTaskId"], approval_id="approval-1", expected_revision="fp-1")
    assert result["dispatchId"] == "dispatch-1" and result["nativeTaskId"] == started["nativeTaskId"]
    assert runtime.resolve_calls == [(session, "approval-1", "decline")]
    assert len([r for r in calls if r.url.path.endswith("/tasks") and r.method == "POST"]) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("ceiling", ["read_only", "workspace_write"])
async def test_write_source_dispatch_preserves_native_effective_permission(tmp_path, journal_source, ceiling):
    caller, original, _ = journal_source
    runtime = FakeRuntime(agents=[_agent(externalMaximumPermissionProfile=ceiling)])
    service, _, calls, _ = native_adapter(tmp_path, runtime)
    result = await service.dispatch_write_from_source("project-a", agent_id="coder", dispatch_id="write-ceiling",
        runtime=caller, task=original["content"])
    request = next(request for request in calls if request.method == "POST" and request.url.path.endswith("/tasks"))
    assert json.loads(request.content)["permission_profile"] == "workspace_write"
    assert result["receipt"]["effectivePermissionProfile"] == ceiling
    assert len(runtime.create_calls) == len(runtime.submit_calls) == 1


@pytest.mark.anyio
async def test_native_response_loss_recovers_same_capability_task_and_hidden_session(tmp_path):
    runtime = FakeRuntime()
    service, native, calls, factory = native_adapter(tmp_path, runtime, drop_first_start=True)
    with pytest.raises(DispatchError):
        await start(service, permission_profile="full_access")
    recovered = DispatchService(tmp_path / "profile", {"project-a": tmp_path / "project"}, client_factory=factory)
    receipt = await start(recovered, permission_profile="full_access")
    await recovered.reconcile("dispatch-1")
    starts = [request for request in calls if request.method == "POST" and request.url.path.endswith("/tasks")]
    assert len(starts) == 2
    assert starts[0].headers["X-Vibelution-External-Agent-Task-Capability"] == starts[1].headers["X-Vibelution-External-Agent-Task-Capability"]
    assert len(runtime.create_calls) == len(runtime.submit_calls) == 1
    assert runtime.create_calls[0]["conversation_index_kind"] == "hidden"
    assert runtime.create_calls[0]["activate"] is False
    assert receipt["receipt"]["effectivePermissionProfile"] == "workspace_write"
    assert native.store.get_task(receipt["nativeTaskId"])["taskDigest"]
    assert not runtime.stop_calls


@pytest.mark.anyio
async def test_native_ack_loss_reconnect_finds_task_without_original_prompt(tmp_path):
    runtime = FakeRuntime()
    service, native, calls, factory = native_adapter(tmp_path, runtime, drop_first_start=True)
    with pytest.raises(DispatchError):
        await start(service)
    resumed = DispatchService(tmp_path / "profile", {"project-a": tmp_path / "project"}, client_factory=factory)
    receipt = await resumed.reconcile("dispatch-1")
    assert receipt["nativeTaskId"]
    assert len(runtime.create_calls) == len(runtime.submit_calls) == 1
    assert sum(request.method == "POST" and request.url.path.endswith("/tasks") for request in calls) == 1
    assert not runtime.stop_calls


@pytest.mark.anyio
async def test_native_team_hidden_and_disabled_restrictions_remain_authoritative(tmp_path):
    runtime = FakeRuntime(agents=[_agent(), _agent("team", conversationIndexKind="team_agent"), _agent("hidden", conversationIndexKind="hidden")])
    service, native, _, _ = native_adapter(tmp_path, runtime)
    assert [row["agentId"] for row in (await service.discover("project-a"))["agents"]] == ["coder"]
    for agent_id in ("team", "hidden"):
        with pytest.raises(DispatchError) as blocked:
            await service.dispatch("project-a", agent_id=agent_id, task="read", dispatch_id=f"dispatch-{agent_id}")
        assert blocked.value.code == "AGENT_NOT_FOUND"
    native.enabled = False
    with pytest.raises(DispatchError) as disabled:
        await start(service)
    assert disabled.value.code == "GATEWAY_NOT_READY"
    assert runtime.create_calls == []


@pytest.mark.anyio
async def test_native_expired_lease_reconcile_reports_stop_instead_of_redispatch(tmp_path):
    runtime = FakeRuntime()
    service, native, calls, _ = native_adapter(tmp_path, runtime)
    receipt = await start(service)
    record = native.store.get_task(receipt["nativeTaskId"])
    native.store.transition(record["taskId"], status="running", fields={"leaseExpiresAt": "2000-01-01T00:00:00Z"})
    native.reconcile()
    stopped = await service.reconcile("dispatch-1")
    assert stopped["receipt"]["status"] == "stop_unconfirmed"
    runtime.details[record["sessionId"]]["phase"] = "stopped"
    native.reconcile()
    final = await service.reconcile("dispatch-1")
    assert final["receipt"]["status"] == "timed_out"
    assert runtime.stop_calls == [(record["sessionId"], record["turnId"])]
    assert len([request for request in calls if request.method == "POST" and request.url.path.endswith("/tasks")]) == 1


@pytest.mark.anyio
async def test_native_missing_credentials_cannot_take_over_or_restart_known_task(tmp_path):
    runtime = FakeRuntime()
    service, _, calls, _ = native_adapter(tmp_path, runtime)
    receipt = await start(service)
    credentials = next((tmp_path / "profile" / "assistant_dispatch" / "credentials").glob("*.json"))
    credentials.unlink()
    with pytest.raises(DispatchError) as missing:
        await service.reconcile("dispatch-1")
    assert missing.value.code == "TASK_NOT_FOUND"
    assert service.list_dispatches()[0]["nativeTaskId"] == receipt["nativeTaskId"]
    assert len(runtime.create_calls) == 1
    assert len([request for request in calls if request.method == "POST" and request.url.path.endswith("/tasks")]) == 1
    assert not runtime.stop_calls


@pytest.mark.anyio
@pytest.mark.parametrize("corrupt", [False, True])
async def test_lost_ack_and_lost_credentials_cannot_create_another_task(tmp_path, corrupt):
    runtime = FakeRuntime()
    service, native, calls, _ = native_adapter(tmp_path, runtime, drop_first_start=True)
    with pytest.raises(DispatchError):
        await start(service)
    record = native.store.list_nonterminal()[0]
    runtime.details[record["sessionId"]]["phase"] = "ready"
    native.get_task(owner_id=next(request.headers["X-Vibelution-External-Agent-Task-Capability"]
        for request in calls if request.method == "POST" and request.url.path.endswith("/tasks")), task_id=record["taskId"])
    credentials = next((tmp_path / "profile/assistant_dispatch/credentials").glob("*.json"))
    if corrupt:
        credentials.write_text("{broken", encoding="utf-8")
    else:
        credentials.unlink()
    with pytest.raises(DispatchError) as denied:
        await start(service)
    assert denied.value.code == "UNKNOWN_REQUEST"
    assert len(runtime.create_calls) == len(runtime.submit_calls) == 1
    assert sum(request.method == "POST" and request.url.path.endswith("/tasks") for request in calls) == 1


@pytest.mark.anyio
async def test_corrupt_reference_does_not_stop_healthy_task_renewal(tmp_path):
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    await start(service)
    broken = tmp_path / "profile/assistant_dispatch/records/broken.json"
    broken.write_text("{broken", encoding="utf-8")
    results = await service.heartbeat()
    assert any((row.get("receipt") or {}).get("status") == "succeeded" for row in results)
    failure = next(row for row in service.list_dispatches() if row["dispatchId"] == "broken")
    assert failure["lastError"]["code"] == "DISPATCH_STATE_CORRUPT"
    assert broken.read_text(encoding="utf-8") == "{broken"


@pytest.mark.anyio
async def test_three_dispatches_renew_each_native_task_once(tmp_path):
    runtime = FakeRuntime(agents=[_agent("a"), _agent("b"), _agent("c")])
    service, _, calls, _ = native_adapter(tmp_path, runtime)
    for agent in ("a", "b", "c"):
        await service.dispatch("project-a", agent_id=agent, task="read", dispatch_id=f"dispatch-{agent}")
    await service.heartbeat()
    renewals = [request for request in calls if request.url.path.endswith("/heartbeat")]
    assert len(renewals) == 3


@pytest.mark.anyio
async def test_project_suspension_blocks_sdk_and_intents_but_retains_history(tmp_path):
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    await start(service)
    before = service._path("dispatch-1").read_bytes()
    calls = len(probe.instances)
    assert service.suspend_projects()["projectsSuspended"] is True
    for operation in (
        service.discover("project-a"),
        service.dispatch("project-a", agent_id="coder", task="read", dispatch_id="new"),
        service.reconcile("dispatch-1"),
        service.cancel("dispatch-1"),
        service.management.invoke("project-a", action="agent_create", request_id="new", parameters={}),
        service.management.receipt("project-a", action="agent_create", request_id="new"),
        service.management.authorization_status("project-a"),
    ):
        with pytest.raises(DispatchError) as denied:
            await operation
        assert denied.value.code == "PROJECT_REGISTRY_RECONCILE_REQUIRED"
    assert len(probe.instances) == calls
    assert not service._path("new").exists()
    assert not (tmp_path / "profile/assistant_management").exists()
    assert service._path("dispatch-1").read_bytes() == before
    assert service.list_dispatches("project-a")[0]["nativeTaskId"] == "eat-1"
    assert service.project_ids() == ("project-a",)


@pytest.mark.anyio
@pytest.mark.parametrize("queue", ["dispatch", "management", "sdk"])
async def test_project_suspension_rechecks_queued_admission_before_effects(tmp_path, queue):
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    if queue == "dispatch":
        lock = service._dispatch_lock("queued")
        operation = lambda: service.dispatch("project-a", agent_id="coder", task="read", dispatch_id="queued")
    elif queue == "management":
        key = service.management._key("project-a", "agent_create", "queued")
        lock = service.management._locks.setdefault(key, anyio.Lock())
        operation = lambda: service.management.invoke("project-a", action="agent_create", request_id="queued", parameters={})
    else:
        lock = service._project_locks.setdefault("project-a", anyio.Lock())
        operation = lambda: service.discover("project-a")
    entered = anyio.Event()
    async def queued():
        entered.set()
        with pytest.raises(DispatchError) as denied:
            await operation()
        assert denied.value.code == "PROJECT_REGISTRY_RECONCILE_REQUIRED"
    await lock.acquire()
    async with anyio.create_task_group() as group:
        group.start_soon(queued)
        await entered.wait()
        await anyio.sleep(0)
        service.suspend_projects()
        lock.release()
    assert probe.instances == []
    assert not service._path("queued").exists()
    assert not (tmp_path / "profile/assistant_management").exists()


@pytest.mark.anyio
async def test_project_snapshot_resume_requires_complete_valid_physical_roots(tmp_path):
    probe = ClientProbe()
    project = tmp_path / "project"
    missing = tmp_path / "missing"
    project.mkdir()
    non_directory = tmp_path / "file"
    non_directory.write_text("retained", encoding="utf-8")
    snapshot = {"schemaVersion": 1, "revision": 7, "projects": {"a": str(project), "b": str(missing)}}
    service = DispatchService(tmp_path / "profile", {}, client_factory=probe.factory, projects_suspended=True)
    service.replace_projects(snapshot, retain_suspension=True)
    assert service.project_ids() == ("a", "b")
    for invalid in (
        snapshot,
        {**snapshot, "revision": 6},
        {**snapshot, "projects": {"a": str(project)}},
        {**snapshot, "revision": 8, "projects": {"a": str(tmp_path / "other"), "b": str(missing)}},
        {**snapshot, "revision": 8, "projects": {"a": str(project), "new": str(non_directory)}},
        {**snapshot, "unexpected": True},
    ):
        with pytest.raises(DispatchError):
            service.replace_projects(invalid)
        with pytest.raises(DispatchError) as denied:
            await service.discover("a")
        assert denied.value.code == "PROJECT_REGISTRY_RECONCILE_REQUIRED"
        assert service.project_ids() == ("a", "b")
        assert service._revoked_projects == set()
        assert service._seen_projects == {"a": project.resolve(), "b": missing.resolve()}
    missing.mkdir()
    service.replace_projects(snapshot)
    await service.discover("a")
    assert len(probe.instances) == 1


def test_project_snapshot_root_alias_cannot_clear_suspension(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    service = DispatchService(tmp_path / "profile", {}, projects_suspended=True)
    snapshot = {"schemaVersion": 1, "revision": 7, "projects": {"a": str(root), "b": str(root)}}
    service.replace_projects(snapshot, retain_suspension=True)
    with pytest.raises(DispatchError) as denied:
        service.replace_projects(snapshot)
    assert denied.value.code == "PROJECT_REGISTRY_RECONCILE_REQUIRED"
    assert service.suspend_projects() == {"schemaVersion": 1, "revision": 7, "projectsSuspended": True}


def test_project_snapshot_symlink_alias_cannot_clear_suspension(tmp_path):
    root = tmp_path / "project"
    alias = tmp_path / "alias"
    root.mkdir()
    try:
        alias.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable on this test platform")
    service = DispatchService(tmp_path / "profile", {}, projects_suspended=True)
    snapshot = {"schemaVersion": 1, "revision": 7, "projects": {"a": str(alias)}}
    service.replace_projects(snapshot, retain_suspension=True)
    assert service._projects["a"] == alias
    with pytest.raises(DispatchError) as denied:
        service.replace_projects(snapshot)
    assert denied.value.code == "PROJECT_REGISTRY_RECONCILE_REQUIRED"
    with pytest.raises(DispatchError) as conflict:
        service.replace_projects({**snapshot, "projects": {"a": str(root)}})
    assert conflict.value.code == "PROJECT_REGISTRY_CONFLICT"
    alias.unlink()
    alias.mkdir()
    assert service.replace_projects(snapshot) == {"schemaVersion": 1, "revision": 7, "projectCount": 1}
    assert not service._projects_suspended.is_set()


@pytest.mark.anyio
async def test_suspended_bootstrap_retains_original_root_binding_and_dispatch_history(tmp_path):
    probe = ClientProbe()
    root = tmp_path / "project"
    root.mkdir()
    first = adapter(tmp_path, probe)
    await start(first)
    before = first._path("dispatch-1").read_bytes()
    target = tmp_path / "rebound-target"
    target.mkdir()
    root.rmdir()
    try:
        root.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable on this test platform")
    service = DispatchService(tmp_path / "profile", {}, projects_suspended=True, client_factory=probe.factory)
    snapshot = {"schemaVersion": 1, "revision": 7, "projects": {"project-a": str(root)}}
    service.replace_projects(snapshot, retain_suspension=True)
    assert service._projects["project-a"] == root
    assert service.list_dispatches()[0]["nativeTaskId"] == "eat-1"
    with pytest.raises(DispatchError) as denied:
        service.replace_projects(snapshot)
    assert denied.value.code == "PROJECT_REGISTRY_RECONCILE_REQUIRED"
    root.unlink()
    root.mkdir()
    service.replace_projects(snapshot)
    await service.discover("project-a")
    assert probe.instances[-1]["project_root"] == root
    assert service._path("dispatch-1").read_bytes() == before
    assert [name for name, _ in probe.calls].count("start") == 1


@pytest.mark.anyio
async def test_project_suspension_allows_already_admitted_transaction_to_settle(tmp_path):
    admitted, settle = anyio.Event(), anyio.Event()
    class Client:
        async def diagnostics(self):
            admitted.set()
            await settle.wait()
        async def list_agents(self):
            return {"agents": []}
    service = DispatchService(tmp_path / "profile", {"a": tmp_path / "project"}, client_factory=lambda *args, **kwargs: Client())
    async def operate():
        assert await service._call("a", lambda client: client.list_agents()) == {"agents": []}
    async with anyio.create_task_group() as group:
        group.start_soon(operate)
        await admitted.wait()
        service.suspend_projects()
        settle.set()


def _timeout_management_client(calls: list, receipt):
    class Client:
        async def diagnostics(self):
            return {"status": "healthy"}

        async def management_action(self, **kwargs):
            calls.append(("POST", kwargs))
            error = BackendClientError(
                "managed backend did not answer in time; the request may have been executed: ReadTimeout",
                code="BACKEND_TIMEOUT")
            # Mirror ManagedAgentBackendClient.management_action, which tags
            # sent-but-unacknowledged writes with their reconciliation identity.
            error.management_action = kwargs["action"]
            error.management_request_id = kwargs["request_id"]
            raise error

        async def management_receipt(self, **kwargs):
            calls.append(("GET", kwargs))
            if isinstance(receipt, Exception):
                raise receipt
            return receipt
    return Client()


@pytest.mark.anyio
async def test_management_write_timeout_reconciles_completed_receipt_without_new_approval(tmp_path):
    from core.assistant_runtime.dispatch import _BACKEND_CODE_MESSAGES
    calls = []
    receipt = {"status": "completed", "action": "agent_create", "requestId": "create-1",
               "verified": True, "reused": False, "agent": {"agentId": "native-agent"}}
    service = DispatchService(tmp_path / "profile", {"project-a": tmp_path / "project"},
                              client_factory=lambda *args, **kwargs: _timeout_management_client(calls, receipt))
    result = await service.management.invoke("project-a", action="agent_create", request_id="create-1", parameters={})
    assert result["reconciledAfterTimeout"] is True
    assert result["status"] == "completed" and result["requestId"] == "create-1"
    assert result["projectId"] == "project-a"
    # Exactly one approved write and one read-only receipt query; the write is
    # never replayed and the request_id never changes.
    assert [name for name, _ in calls] == ["POST", "GET"]
    assert calls[1][1] == {"action": "agent_create", "request_id": "create-1"}
    assert _BACKEND_CODE_MESSAGES["BACKEND_TIMEOUT"]


@pytest.mark.anyio
@pytest.mark.parametrize("receipt", [
    BackendClientError("Original request receipt is unavailable.", code="REQUEST_UNAVAILABLE"),
    {"status": "unknown", "action": "agent_create", "requestId": "create-1",
     "verified": False, "code": "OPERATION_UNCONFIRMED"},
], ids=["missing", "unknown"])
async def test_management_write_timeout_without_confirmed_receipt_raises_timeout_with_guidance(tmp_path, receipt):
    from core.assistant_runtime.dispatch import _BACKEND_CODE_MESSAGES
    calls = []
    service = DispatchService(tmp_path / "profile", {"project-a": tmp_path / "project"},
                              client_factory=lambda *args, **kwargs: _timeout_management_client(calls, receipt))
    with pytest.raises(DispatchError) as failure:
        await service.management.invoke("project-a", action="agent_create", request_id="create-1", parameters={})
    assert failure.value.code == "BACKEND_TIMEOUT"
    assert str(failure.value) == _BACKEND_CODE_MESSAGES["BACKEND_TIMEOUT"]
    assert "请用原 request_id 查询回执确认" in str(failure.value)
    assert "不要更换 ID 重发" in str(failure.value)
    # Even on an unconfirmed outcome the write itself is never replayed here.
    assert [name for name, _ in calls] == ["POST", "GET"]


@pytest.mark.anyio
async def test_backend_timeout_without_management_identity_is_not_reconciled(tmp_path):
    from core.assistant_runtime.dispatch import _BACKEND_CODE_MESSAGES
    calls = []
    class Client:
        async def diagnostics(self):
            return {"status": "healthy"}

        async def list_agents(self, **kwargs):
            calls.append("list")
            raise BackendClientError("native request timed out.", code="BACKEND_TIMEOUT")

        async def management_receipt(self, **kwargs):
            calls.append("receipt")
            return {"status": "completed"}
    service = DispatchService(tmp_path / "profile", {"project-a": tmp_path / "project"},
                              client_factory=lambda *args, **kwargs: Client())
    with pytest.raises(DispatchError) as failure:
        await service.discover("project-a")
    assert failure.value.code == "BACKEND_TIMEOUT"
    assert str(failure.value) == _BACKEND_CODE_MESSAGES["BACKEND_TIMEOUT"]
    assert calls == ["list"]


@pytest.mark.anyio
async def test_confirmed_dismiss_archives_corrupt_record_and_frees_the_list(tmp_path):
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    records = tmp_path / "profile/assistant_dispatch/records"
    records.mkdir(parents=True, exist_ok=True)
    corrupt = records / "dispatch-1.json"
    corrupt.write_text("{broken", encoding="utf-8")
    sidecar = records / "dispatch-1.json.lock"
    sidecar.write_bytes(b"\0")
    with pytest.raises(DispatchError) as unconfirmed:
        await service.dismiss_corrupt("dispatch-1", confirmed=False)
    assert unconfirmed.value.code == "DISMISS_CONFIRMATION_REQUIRED"
    assert corrupt.read_text(encoding="utf-8") == "{broken"
    result = await service.dismiss_corrupt("dispatch-1", confirmed=True, reason="operator cleanup")
    assert result["dismissed"] is True and result["invalidCode"] == "DISPATCH_STATE_CORRUPT"
    assert result["lockSidecarRemoved"] is True
    corrupt_dir = tmp_path / "profile/assistant_dispatch/records-corrupt"
    archived = corrupt_dir / "dispatch-1.json"
    assert archived.read_bytes() == b"{broken"
    assert not corrupt.exists() and not sidecar.exists()
    audit = json.loads((corrupt_dir / "dispatch-1.dismiss-audit.json").read_text(encoding="utf-8"))
    assert audit["kind"] == "dispatch_corrupt_dismissal" and audit["dispatchId"] == "dispatch-1"
    assert audit["originalPath"] == "records/dispatch-1.json"
    assert audit["archivePath"] == "records-corrupt/dispatch-1.json"
    assert audit["invalidCode"] == "DISPATCH_STATE_CORRUPT" and audit["reason"] == "operator cleanup"
    assert audit["sizeBytes"] == 7 and audit["lockSidecarPresent"] is True
    assert audit["contentDigest"] == hashlib.sha256(b"{broken").hexdigest()
    assert audit["dismissedAt"]
    assert service.list_dispatches() == []
    assert [name for name, _ in probe.calls] == []
    with pytest.raises(DispatchError) as gone:
        await service.dismiss_corrupt("dispatch-1", confirmed=True)
    assert gone.value.code == "DISPATCH_NOT_FOUND"
    # Dismissal is a forensic archive, not a permanent fence: the identity is
    # reusable and the native layer dedupes by client_request_id.
    await start(service)
    assert service.list_dispatches()[0]["nativeTaskId"] == "eat-1"


@pytest.mark.anyio
async def test_shape_invalid_record_reports_shape_code_and_is_dismissible(tmp_path):
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    records = tmp_path / "profile/assistant_dispatch/records"
    records.mkdir(parents=True, exist_ok=True)
    (records / "mismatched.json").write_text(
        json.dumps({"schemaVersion": 1, "dispatchId": "other", "projectId": "project-a"}), encoding="utf-8")
    (records / "notobject.json").write_text("[1, 2]", encoding="utf-8")
    rows = {row["dispatchId"]: row for row in service.list_dispatches()}
    assert rows["mismatched"]["stateInvalid"] is True
    assert rows["mismatched"]["lastError"]["code"] == "DISPATCH_STATE_SHAPE_INVALID"
    assert rows["notobject"]["lastError"]["code"] == "DISPATCH_STATE_SHAPE_INVALID"
    result = await service.dismiss_corrupt("mismatched", confirmed=True)
    assert result["invalidCode"] == "DISPATCH_STATE_SHAPE_INVALID"
    archived = tmp_path / "profile/assistant_dispatch/records-corrupt/mismatched.json"
    assert json.loads(archived.read_text(encoding="utf-8"))["dispatchId"] == "other"
    remaining = {row["dispatchId"] for row in service.list_dispatches()}
    assert remaining == {"notobject"}


@pytest.mark.anyio
async def test_dismiss_refuses_healthy_records_even_when_confirmed(tmp_path):
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    await start(service)
    record = service._path("dispatch-1").read_text(encoding="utf-8")
    with pytest.raises(DispatchError) as refused:
        await service.dismiss_corrupt("dispatch-1", confirmed=True)
    assert refused.value.code == "DISPATCH_DISMISS_REFUSED"
    assert service._path("dispatch-1").read_text(encoding="utf-8") == record
    rows = service.list_dispatches()
    assert len(rows) == 1 and not rows[0].get("stateInvalid")
    assert not (tmp_path / "profile/assistant_dispatch/records-corrupt").exists()


@pytest.mark.anyio
async def test_refresh_reports_corrupt_shape_and_binding_change_instead_of_unknown(tmp_path):
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    await start(service)
    records = tmp_path / "profile/assistant_dispatch/records"
    records.mkdir(parents=True, exist_ok=True)
    (records / "broken.json").write_text("{broken", encoding="utf-8")
    (records / "mismatched.json").write_text(
        json.dumps({"schemaVersion": 1, "dispatchId": "other"}), encoding="utf-8")
    results = {row["dispatchId"]: row["lastError"]["code"]
               for row in await service._refresh_batch(["broken", "mismatched"], include_terminal=False)}
    assert results == {"broken": "DISPATCH_STATE_CORRUPT", "mismatched": "DISPATCH_STATE_SHAPE_INVALID"}
    # A drifted registry binding is a readable reference, not a corrupt one:
    # the same profile read through a differently-bound registry must stay
    # distinguishable from the two file defects above.
    rebound = DispatchService(tmp_path / "profile", {"project-a": tmp_path / "elsewhere"}, client_factory=probe.factory)
    binding = await rebound._refresh_batch(["dispatch-1"], include_terminal=False)
    assert binding[0]["lastError"]["code"] == "PROJECT_BINDING_CHANGED"
