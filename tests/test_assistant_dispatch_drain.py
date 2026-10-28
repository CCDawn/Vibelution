"""Dispatch drain uses real temporary records and a simulated native backend."""

import json
import threading

import anyio
import pytest

from core.assistant_runtime.dispatch import DispatchError, DispatchService
from core.external_agent.backend_client import BackendClientError


class Remote:
    def __init__(self):
        self.status = "running"
        self.calls = []
        self.fail = False
        self.start_entered = anyio.Event()
        self.start_release = anyio.Event()
        self.block_start = False

    def factory(self, *_args, **_kwargs):
        return self

    async def diagnostics(self):
        if self.fail:
            raise BackendClientError("unavailable", code="BACKEND_UNAVAILABLE")
        return {}

    async def start_task(self, **kwargs):
        self.calls.append(("start", kwargs))
        self.start_entered.set()
        if self.block_start:
            await self.start_release.wait()
        return {"taskId": "task-1", "status": "running"}

    async def get_task_for_request(self, **kwargs):
        self.calls.append(("lookup", kwargs))
        raise BackendClientError("unknown", code="UNKNOWN_REQUEST")

    async def heartbeat_task(self, **kwargs):
        self.calls.append(("heartbeat", kwargs))

    async def get_task(self, **kwargs):
        self.calls.append(("get", kwargs))
        return {"taskId": "task-1", "status": self.status}

    async def cancel_task(self, **kwargs):
        self.calls.append(("cancel", kwargs))
        raise AssertionError("drain must not cancel")


def service_for(tmp_path, remote):
    return DispatchService(tmp_path / "profile", {"project": tmp_path / "project"}, client_factory=remote.factory)


async def start(service, ident="original"):
    return await service.dispatch("project", agent_id="coder", task="original task", dispatch_id=ident)


@pytest.mark.anyio
async def test_fence_serializes_admission_retains_heartbeat_and_persists_terminal(tmp_path):
    remote = Remote()
    remote.block_start = True
    service = service_for(tmp_path, remote)
    fence_entered = anyio.Event()

    async def producer():
        await start(service)

    async def drainer():
        async with service.drain_fence() as fence:
            fence_entered.set()
            with pytest.raises(DispatchError, match="temporarily fenced"):
                await start(service, "new")
            with pytest.raises(DispatchError):
                service.replace_projects({"schemaVersion": 1, "revision": 1, "projects": {}})
            assert (await fence.observe())["drained"] is False
            assert any(name == "heartbeat" for name, _ in remote.calls)
            remote.status = "succeeded"
            assert await fence.observe() == {"drained": True, "recordCount": 1}
            persisted = json.loads(service._path("original").read_text(encoding="utf-8"))
            assert persisted["receipt"]["taskId"] == "task-1"
            assert persisted["receipt"]["status"] == "succeeded"
            assert persisted["clientRequestId"] == "launcher-assistant:original"
            with pytest.raises(DispatchError):
                await service.cancel("original")
            assert not service._path("new").exists()

    async with anyio.create_task_group() as group:
        group.start_soon(producer)
        await remote.start_entered.wait()
        group.start_soon(drainer)
        await anyio.sleep(0.05)
        assert not fence_entered.is_set()
        remote.start_release.set()
    assert fence_entered.is_set()
    assert not any(name == "cancel" for name, _ in remote.calls)


@pytest.mark.anyio
async def test_all_records_block_when_corrupt_unbound_or_unknown_and_healthy_renews(tmp_path):
    remote = Remote()
    service = service_for(tmp_path, remote)
    await start(service)
    record_dir = service._path("original").parent
    (record_dir / "broken.json").write_text("{broken", encoding="utf-8")
    async with service.drain_fence() as fence:
        assert (await fence.observe())["drained"] is False
        assert any(name == "heartbeat" for name, _ in remote.calls)
    assert (record_dir / "broken.json").read_text(encoding="utf-8") == "{broken"
    (record_dir / "broken.json").unlink()
    malformed = json.loads(service._path("original").read_text(encoding="utf-8"))
    malformed.update(dispatchId="malformed", clientRequestId="launcher-assistant:malformed", receipt=["invalid"])
    malformed_path = record_dir / "malformed.json"
    malformed_path.write_text(json.dumps(malformed), encoding="utf-8")
    before_malformed = malformed_path.read_bytes()
    before_heartbeats = sum(name == "heartbeat" for name, _ in remote.calls)
    async with service.drain_fence() as fence:
        assert (await fence.observe())["drained"] is False
    assert malformed_path.read_bytes() == before_malformed
    assert sum(name == "heartbeat" for name, _ in remote.calls) > before_heartbeats
    malformed_path.unlink()
    service.replace_projects({"schemaVersion": 1, "revision": 1, "projects": {}})
    assert service.list_dispatches() == []
    async with service.drain_fence() as fence:
        assert (await fence.observe())["drained"] is False
    assert service._path("original").exists()


@pytest.mark.anyio
async def test_unknown_remote_and_transport_failure_cannot_certify_drain(tmp_path):
    remote = Remote()
    service = service_for(tmp_path, remote)
    await start(service)
    path = service._path("original")
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(nativeTaskId="", receipt=None)
    path.write_text(json.dumps(record), encoding="utf-8")
    async with service.drain_fence() as fence:
        assert (await fence.observe())["drained"] is False
        assert any(name == "lookup" and kwargs["client_request_id"] == "launcher-assistant:original"
                   for name, kwargs in remote.calls)
        remote.fail = True
        assert (await fence.observe())["drained"] is False
    assert path.exists()
    assert sum(name == "start" for name, _ in remote.calls) == 1
    assert not any(name == "cancel" for name, _ in remote.calls)


@pytest.mark.anyio
async def test_source_admission_and_fence_are_serialized(tmp_path, monkeypatch):
    from core.assistant_runtime import native

    remote = Remote()
    service = service_for(tmp_path, remote)
    entered, release = threading.Event(), threading.Event()
    fence_entered = anyio.Event()
    runtime = {"agentId": "assistant", "sessionId": "session", "turnId": "turn"}
    def read_source(*_args, **_kwargs):
        entered.set()
        assert release.wait(5)
        return {**runtime, "eventId": "event", "content": "original task"}
    monkeypatch.setattr(native, "read_task_source", read_source)
    async def source():
        await service.dispatch_from_source("project", agent_id="coder", dispatch_id="source-id",
                                           runtime=runtime, task_source={})
    async def drain():
        async with service.drain_fence() as fence:
            fence_entered.set()
            assert (await fence.observe())["drained"] is False
            with pytest.raises(DispatchError, match="temporarily fenced"):
                await service.dispatch_from_source("project", agent_id="coder", dispatch_id="other",
                                                   runtime=runtime, task_source={})
    try:
        async with anyio.create_task_group() as group:
            group.start_soon(source)
            assert await anyio.to_thread.run_sync(entered.wait, 3)
            group.start_soon(drain)
            await anyio.sleep(0.05)
            assert not fence_entered.is_set()
            release.set()
    finally:
        release.set()
    assert fence_entered.is_set()
    assert service._path("source-id").exists() and not service._path("other").exists()
    assert sum(name == "start" for name, _ in remote.calls) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["queued", "awaiting_approval", "unknown"])
async def test_nonterminal_and_unknown_status_never_certify_drain(tmp_path, status):
    remote = Remote()
    service = service_for(tmp_path, remote)
    await start(service)
    remote.status = status
    async with service.drain_fence() as fence:
        assert (await fence.observe())["drained"] is False
    assert any(name == "heartbeat" for name, _ in remote.calls)


@pytest.mark.anyio
async def test_fence_heartbeat_resumes_after_concurrent_receipt_read_stalls(tmp_path, monkeypatch):
    import core.assistant_runtime.dispatch as dispatch_module

    monkeypatch.setattr(dispatch_module, "_DRAIN_RECORD_TIMEOUT", 0.15)
    monkeypatch.setattr(dispatch_module, "_DRAIN_HEARTBEAT_INTERVAL", 0.03)
    monkeypatch.setattr(dispatch_module, "_NATIVE_REQUEST_TIMEOUT", 0.15)

    class StalledRemote(Remote):
        def __init__(self):
            super().__init__()
            self.stall_once = True
        async def get_task(self, **kwargs):
            self.calls.append(("get", kwargs))
            if self.stall_once:
                self.stall_once = False
                await anyio.sleep_forever()
            return {"taskId": "task-1", "status": "running"}

    remote = StalledRemote()
    service = service_for(tmp_path, remote)
    await start(service)
    async with service.drain_fence() as fence:
        assert (await fence.observe())["drained"] is False
        with anyio.fail_after(2):
            while sum(name == "heartbeat" for name, _ in remote.calls) < 2:
                await anyio.sleep(0.02)
        assert (await fence.observe())["drained"] is False
    assert not any(name == "cancel" for name, _ in remote.calls)


@pytest.mark.anyio
async def test_fence_admission_timeout_preserves_a_hung_start(tmp_path, monkeypatch):
    import core.assistant_runtime.dispatch as dispatch_module

    monkeypatch.setattr(dispatch_module, "_DRAIN_ADMISSION_TIMEOUT", 0.1)
    remote = Remote()
    remote.block_start = True
    service = service_for(tmp_path, remote)
    completed = anyio.Event()
    async def producer():
        await start(service)
        completed.set()
    async with anyio.create_task_group() as group:
        group.start_soon(producer)
        await remote.start_entered.wait()
        with pytest.raises(DispatchError) as error:
            async with service.drain_fence():
                pytest.fail("fence passed an in-flight start")
        assert error.value.code == "DISPATCH_DRAIN_ADMISSION_BUSY"
        assert not completed.is_set()
        remote.start_release.set()
    assert completed.is_set()
    assert sum(name == "start" for name, _ in remote.calls) == 1
    assert not any(name == "cancel" for name, _ in remote.calls)


@pytest.mark.anyio
async def test_slow_heartbeat_is_not_cancelled_by_a_short_record_observation_budget(tmp_path, monkeypatch):
    import core.assistant_runtime.dispatch as dispatch_module

    monkeypatch.setattr(dispatch_module, "_DRAIN_RECORD_TIMEOUT", 0.05)
    monkeypatch.setattr(dispatch_module, "_DRAIN_HEARTBEAT_INTERVAL", 0.01)
    monkeypatch.setattr(dispatch_module, "_NATIVE_REQUEST_TIMEOUT", 1.0)
    class SlowRemote(Remote):
        async def diagnostics(self):
            await anyio.sleep(0.08)
            return await super().diagnostics()
        async def heartbeat_task(self, **kwargs):
            await anyio.sleep(0.08)
            return await super().heartbeat_task(**kwargs)
        async def get_task(self, **kwargs):
            await anyio.sleep(0.08)
            return await super().get_task(**kwargs)
    remote = SlowRemote()
    service = service_for(tmp_path, remote)
    await start(service)
    async with service.drain_fence() as fence:
        await anyio.sleep(0.02)
        assert (await fence.observe())["drained"] is False
        with anyio.fail_after(2):
            while not any(name == "get" for name, _ in remote.calls):
                await anyio.sleep(0.02)
        stored = json.loads(service._path("original").read_text(encoding="utf-8"))
        assert stored["receipt"]["status"] == "running"
        assert any(name == "heartbeat" for name, _ in remote.calls)
    assert not any(name == "cancel" for name, _ in remote.calls)


@pytest.mark.anyio
async def test_native_three_second_diagnostics_still_allows_lease_renewal(tmp_path):
    class SlowDiagnostics(Remote):
        slow = False
        async def diagnostics(self):
            if self.slow:
                await anyio.sleep(3.2)
            return await super().diagnostics()
    remote = SlowDiagnostics()
    service = service_for(tmp_path, remote)
    await start(service)
    remote.slow = True
    async with service.drain_fence():
        with anyio.fail_after(5):
            while not any(name == "get" for name, _ in remote.calls):
                await anyio.sleep(0.05)
        assert any(name == "heartbeat" for name, _ in remote.calls)


@pytest.mark.anyio
async def test_observe_has_one_overall_deadline_even_if_individual_budget_is_larger(tmp_path, monkeypatch):
    import core.assistant_runtime.dispatch as dispatch_module

    monkeypatch.setattr(dispatch_module, "_DRAIN_OBSERVE_TIMEOUT", 0.1)
    monkeypatch.setattr(dispatch_module, "_DRAIN_RECORD_TIMEOUT", 1.0)
    class SlowRemote(Remote):
        async def get_task(self, **_kwargs):
            await anyio.sleep_forever()
    remote = SlowRemote()
    service = service_for(tmp_path, remote)
    await start(service)
    async with service.drain_fence() as fence:
        with anyio.fail_after(0.5):
            assert (await fence.observe())["drained"] is False
    assert not any(name == "cancel" for name, _ in remote.calls)


@pytest.mark.anyio
async def test_unknown_start_wrong_terminal_receipt_id_is_never_persisted_or_drained(tmp_path):
    class WrongIdRemote(Remote):
        async def get_task_for_request(self, **kwargs):
            self.calls.append(("lookup", kwargs))
            return {"taskId": "task-X"}
        async def get_task(self, **kwargs):
            self.calls.append(("get", kwargs))
            return {"taskId": "task-Y", "status": "succeeded"}
    remote = WrongIdRemote()
    service = service_for(tmp_path, remote)
    await start(service)
    path = service._path("original")
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(nativeTaskId="", receipt=None)
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(DispatchError) as error:
        await service.reconcile("original")
    assert error.value.code == "BACKEND_PROTOCOL_ERROR"
    async with service.drain_fence() as fence:
        assert (await fence.observe())["drained"] is False
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["nativeTaskId"] == "" and stored["receipt"] is None
    assert stored["lastError"]["code"] == "BACKEND_PROTOCOL_ERROR"
    assert any(name == "get" and kwargs["task_id"] == "task-X" for name, kwargs in remote.calls)
    assert not any(name == "cancel" for name, _ in remote.calls)


@pytest.mark.anyio
async def test_four_real_native_tasks_keep_renewing_with_scaled_30_second_lease(tmp_path, monkeypatch):
    import time
    import httpx
    from datetime import datetime, timedelta, timezone
    import core.assistant_runtime.dispatch as dispatch_module
    from core.web.services.external_agent import store as native_store
    from tests.test_assistant_runtime_dispatch import native_adapter
    from tests.test_external_agent_task_service import FakeRuntime, _agent

    # 0.05 real seconds represent one contract second: each 3.2-second
    # network response takes 160ms, heartbeat cadence is 500ms, lease 1.5s.
    monkeypatch.setattr(dispatch_module, "_DRAIN_HEARTBEAT_INTERVAL", 0.5)
    runtime = FakeRuntime(agents=[_agent(f"coder-{n}") for n in range(4)])
    service, native, _, original_factory = native_adapter(tmp_path, runtime)
    task_ids = []
    for n in range(4):
        result = await service.dispatch("project-a", agent_id=f"coder-{n}", task="read",
                                        dispatch_id=f"dispatch-{n}")
        task_ids.append(result["nativeTaskId"])
    stamps = {task_id: [] for task_id in task_ids}

    class DelayedNativeTransport(httpx.AsyncBaseTransport):
        def __init__(self, base):
            self.base = base
        async def handle_async_request(self, request):
            await anyio.sleep(0.16)
            response = await self.base.handle_async_request(request)
            if request.url.path.endswith("/heartbeat") and response.status_code < 400:
                stamps[request.url.path.split("/")[-2]].append(time.monotonic())
            return response

    def delayed_factory(project_root, **kwargs):
        client = original_factory(project_root, **kwargs)
        client.transport = DelayedNativeTransport(client.transport)
        return client
    service._client_factory = delayed_factory
    before = {task_id: native.store.get_task(task_id)["revision"] for task_id in task_ids}
    credential_path = next((tmp_path / "profile" / "assistant_dispatch" / "credentials").glob("*.json"))
    original_credentials = json.loads(credential_path.read_text(encoding="utf-8"))
    base, origin = datetime.now(timezone.utc), time.monotonic()
    def scaled_clock():
        return base + timedelta(seconds=(time.monotonic() - origin) * 20)
    monkeypatch.setattr(native_store, "_utc_now", scaled_clock)
    async with service.drain_fence() as fence:
        assert (await fence.observe())["drained"] is False
        with anyio.fail_after(8):
            while any(len(stamps[task_id]) < 3 for task_id in task_ids):
                native.reconcile(now_iso=scaled_clock().isoformat())
                await anyio.sleep(0.05)
        native.reconcile(now_iso=scaled_clock().isoformat())
        for task_id in task_ids:
            assert max(b - a for a, b in zip(stamps[task_id], stamps[task_id][1:])) < 1.5
            assert native.store.get_task(task_id)["revision"] > before[task_id]
            assert native.store.get_task(task_id)["status"] == "running"
        refreshed_credentials = json.loads(credential_path.read_text(encoding="utf-8"))
        assert refreshed_credentials["requests"] == original_credentials["requests"]
        assert set(refreshed_credentials["tasks"]) == set(original_credentials["tasks"]) == set(task_ids)
    assert not runtime.stop_calls


@pytest.mark.anyio
async def test_one_hung_native_task_does_not_starve_same_project_peers(tmp_path, monkeypatch):
    import httpx
    import core.assistant_runtime.dispatch as dispatch_module
    from tests.test_assistant_runtime_dispatch import native_adapter
    from tests.test_external_agent_task_service import FakeRuntime, _agent

    monkeypatch.setattr(dispatch_module, "_DRAIN_HEARTBEAT_INTERVAL", 0.1)
    runtime = FakeRuntime(agents=[_agent(f"coder-{n}") for n in range(4)])
    service, _, _, original_factory = native_adapter(tmp_path, runtime)
    task_ids = []
    for n in range(4):
        row = await service.dispatch("project-a", agent_id=f"coder-{n}", task="read", dispatch_id=f"task-{n}")
        task_ids.append(row["nativeTaskId"])
    slow_started = anyio.Event()
    peers = {task_id: 0 for task_id in task_ids[1:]}
    class DelayedNativeTransport(httpx.AsyncBaseTransport):
        def __init__(self, base):
            self.base = base
        async def handle_async_request(self, request):
            if request.url.path.endswith("/heartbeat"):
                task_id = request.url.path.split("/")[-2]
                if task_id == task_ids[0]:
                    slow_started.set()
                    await anyio.sleep_forever()
                await anyio.sleep(0.03)
                response = await self.base.handle_async_request(request)
                if response.status_code < 400:
                    peers[task_id] += 1
                return response
            return await self.base.handle_async_request(request)
    def delayed_factory(project_root, **kwargs):
        client = original_factory(project_root, **kwargs)
        client.transport = DelayedNativeTransport(client.transport)
        return client
    service._client_factory = delayed_factory
    async with service.drain_fence():
        await slow_started.wait()
        with anyio.fail_after(2):
            while min(peers.values()) < 3:
                await anyio.sleep(0.02)
    assert not runtime.stop_calls


@pytest.mark.anyio
async def test_preexisting_hung_reconcile_does_not_starve_peer_leases(tmp_path, monkeypatch):
    import time
    from datetime import datetime, timedelta, timezone
    import httpx
    import core.assistant_runtime.dispatch as dispatch_module
    from core.web.services.external_agent import store as native_store
    from tests.test_assistant_runtime_dispatch import native_adapter
    from tests.test_external_agent_task_service import FakeRuntime, _agent

    monkeypatch.setattr(dispatch_module, "_DRAIN_HEARTBEAT_INTERVAL", 0.15)
    monkeypatch.setattr(dispatch_module, "_DRAIN_OBSERVE_TIMEOUT", 0.2)
    runtime = FakeRuntime(agents=[_agent(f"coder-{n}") for n in range(4)])
    service, native, _, original_factory = native_adapter(tmp_path, runtime)
    task_ids = []
    for n in range(4):
        row = await service.dispatch("project-a", agent_id=f"coder-{n}", task="read", dispatch_id=f"task-{n}")
        task_ids.append(row["nativeTaskId"])
    credentials = next((tmp_path / "profile" / "assistant_dispatch" / "credentials").glob("*.json"))
    before = json.loads(credentials.read_text(encoding="utf-8"))
    stuck, release = anyio.Event(), anyio.Event()
    renewals = {task_id: [] for task_id in task_ids}
    connections = []

    class DelayedNativeTransport(httpx.AsyncBaseTransport):
        def __init__(self, base):
            self.base = base
        async def handle_async_request(self, request):
            path = request.url.path
            if request.method == "GET" and path.endswith("/tasks/" + task_ids[0]):
                connections.append(request.headers["X-Vibelution-External-Agent-Connection"])
                stuck.set()
                await release.wait()
            if path.endswith("/heartbeat"):
                await anyio.sleep(0.04)
                response = await self.base.handle_async_request(request)
                if response.status_code < 400:
                    renewals[path.split("/")[-2]].append(time.monotonic())
                    connections.append(request.headers["X-Vibelution-External-Agent-Connection"])
                return response
            return await self.base.handle_async_request(request)

    def delayed_factory(project_root, **kwargs):
        client = original_factory(project_root, **kwargs)
        client.transport = DelayedNativeTransport(client.transport)
        return client
    service._client_factory = delayed_factory
    base, origin = datetime.now(timezone.utc), time.monotonic()
    def scaled_clock():
        return base + timedelta(seconds=(time.monotonic() - origin) * 20)
    monkeypatch.setattr(native_store, "_utc_now", scaled_clock)
    completed = anyio.Event()
    async def existing_reconcile():
        await service.reconcile("task-0")
        completed.set()
    try:
        async with anyio.create_task_group() as group:
            group.start_soon(existing_reconcile)
            await stuck.wait()
            async with service.drain_fence() as fence:
                assert (await fence.observe())["drained"] is False
                with anyio.fail_after(4):
                    while time.monotonic() - origin < 1.7 or min(len(v) for v in renewals.values()) < 3:
                        native.reconcile(now_iso=scaled_clock().isoformat())
                        await anyio.sleep(0.05)
                assert not completed.is_set()
                assert not runtime.stop_calls
                assert all(native.store.get_task(task_id)["status"] == "running" for task_id in task_ids)
                assert len(set(connections)) == 1
            release.set()
    finally:
        release.set()
    assert completed.is_set()
    after = json.loads(credentials.read_text(encoding="utf-8"))
    assert after["requests"] == before["requests"]
    assert set(after["tasks"]) == set(before["tasks"]) == set(task_ids)


@pytest.mark.anyio
async def test_project_client_cannot_be_replaced_while_borrowed_heartbeat_is_writing(tmp_path, monkeypatch):
    import httpx
    import core.assistant_runtime.dispatch as dispatch_module
    from tests.test_assistant_runtime_dispatch import native_adapter
    from tests.test_external_agent_task_service import FakeRuntime, _agent

    monkeypatch.setattr(dispatch_module, "_DRAIN_HEARTBEAT_INTERVAL", 0.1)
    runtime = FakeRuntime(agents=[_agent("a"), _agent("b")])
    service, _, _, original_factory = native_adapter(tmp_path, runtime)
    a = (await service.dispatch("project-a", agent_id="a", task="read", dispatch_id="a"))["nativeTaskId"]
    b = (await service.dispatch("project-a", agent_id="b", task="read", dispatch_id="b"))["nativeTaskId"]
    get_started, release_get = anyio.Event(), anyio.Event()
    heartbeat_started, release_heartbeat = anyio.Event(), anyio.Event()
    original_finished = anyio.Event()
    class DelayedNativeTransport(httpx.AsyncBaseTransport):
        def __init__(self, base):
            self.base = base
        async def handle_async_request(self, request):
            path = request.url.path
            if request.method == "GET" and path.endswith("/tasks/" + a):
                get_started.set()
                await release_get.wait()
            if path.endswith("/tasks/" + b + "/heartbeat"):
                heartbeat_started.set()
                await release_heartbeat.wait()
            return await self.base.handle_async_request(request)
    def delayed_factory(project_root, **kwargs):
        client = original_factory(project_root, **kwargs)
        client.transport = DelayedNativeTransport(client.transport)
        return client
    service._client_factory = delayed_factory
    async def original():
        await service.reconcile("a")
        original_finished.set()
    try:
        async with anyio.create_task_group() as group:
            group.start_soon(original)
            await get_started.wait()
            async with service.drain_fence():
                with anyio.fail_after(2):
                    await heartbeat_started.wait()
                release_get.set()
                await anyio.sleep(0.05)
                assert not original_finished.is_set()
                assert service._project_locks["project-a"].locked()
                release_heartbeat.set()
                with anyio.fail_after(2):
                    await original_finished.wait()
    finally:
        release_get.set()
        release_heartbeat.set()
    assert not runtime.stop_calls


@pytest.mark.anyio
async def test_staggered_borrows_drain_then_resume_without_starving_project_lock(tmp_path, monkeypatch):
    import httpx
    import core.assistant_runtime.dispatch as dispatch_module
    from tests.test_assistant_runtime_dispatch import native_adapter
    from tests.test_external_agent_task_service import FakeRuntime, _agent

    monkeypatch.setattr(dispatch_module, "_DRAIN_HEARTBEAT_INTERVAL", 0.03)
    runtime = FakeRuntime(agents=[_agent("a"), _agent("b"), _agent("c")])
    service, _, _, original_factory = native_adapter(tmp_path, runtime)
    task_ids = {}
    for agent in ("a", "b", "c"):
        row = await service.dispatch("project-a", agent_id=agent, task="read", dispatch_id=agent)
        task_ids[agent] = row["nativeTaskId"]
    credentials = next((tmp_path / "profile" / "assistant_dispatch" / "credentials").glob("*.json"))
    original_requests = json.loads(credentials.read_text(encoding="utf-8"))["requests"]
    get_started, release_get = anyio.Event(), anyio.Event()
    started = {key: anyio.Event() for key in ("b", "c")}
    released = {key: anyio.Event() for key in ("b", "c")}
    calls = {key: 0 for key in ("b", "c")}
    finished = anyio.Event()

    class DelayedNativeTransport(httpx.AsyncBaseTransport):
        def __init__(self, base):
            self.base = base
        async def handle_async_request(self, request):
            path = request.url.path
            if request.method == "GET" and path.endswith("/tasks/" + task_ids["a"]):
                get_started.set()
                await release_get.wait()
            for agent in ("b", "c"):
                if path.endswith("/tasks/" + task_ids[agent] + "/heartbeat"):
                    calls[agent] += 1
                    if calls[agent] == 1:
                        started[agent].set()
                        await released[agent].wait()
            return await self.base.handle_async_request(request)

    def delayed_factory(project_root, **kwargs):
        client = original_factory(project_root, **kwargs)
        client.transport = DelayedNativeTransport(client.transport)
        return client
    service._client_factory = delayed_factory
    async def original():
        await service.reconcile("a")
        finished.set()
    try:
        async with anyio.create_task_group() as group:
            group.start_soon(original)
            await get_started.wait()
            async with service.drain_fence():
                with anyio.fail_after(2):
                    await started["b"].wait()
                    await started["c"].wait()
                slot = service._active_project_clients["project-a"]
                assert slot.borrowers >= 2
                release_get.set()
                with anyio.fail_after(2):
                    while not slot.closing:
                        await anyio.sleep(0.01)
                released["b"].set()
                await anyio.sleep(0.15)
                assert not finished.is_set() and calls["b"] == 1
                assert service._project_locks["project-a"].locked()
                released["c"].set()
                with anyio.fail_after(2):
                    await finished.wait()
                    while (min(calls.values()) < 2
                           or service._active_project_clients["project-a"].closing):
                        await anyio.sleep(0.02)
    finally:
        release_get.set()
        released["b"].set()
        released["c"].set()
    assert json.loads(credentials.read_text(encoding="utf-8"))["requests"] == original_requests
    assert not runtime.stop_calls


@pytest.mark.anyio
async def test_preexisting_hung_diagnostics_uses_prior_verified_client_for_lease_only(tmp_path, monkeypatch):
    import time
    from datetime import datetime, timedelta, timezone
    import httpx
    import core.assistant_runtime.dispatch as dispatch_module
    from core.web.services.external_agent import store as native_store
    from tests.test_assistant_runtime_dispatch import native_adapter
    from tests.test_external_agent_task_service import FakeRuntime, _agent

    monkeypatch.setattr(dispatch_module, "_DRAIN_HEARTBEAT_INTERVAL", 0.15)
    monkeypatch.setattr(dispatch_module, "_DRAIN_OBSERVE_TIMEOUT", 0.2)
    runtime = FakeRuntime(agents=[_agent(f"coder-{n}") for n in range(4)])
    service, native, _, original_factory = native_adapter(tmp_path, runtime)
    stuck, release = anyio.Event(), anyio.Event()
    delay_diagnostics = False
    renewals = {}
    connections = []

    class DelayedNativeTransport(httpx.AsyncBaseTransport):
        def __init__(self, base):
            self.base = base
        async def handle_async_request(self, request):
            path = request.url.path
            if path == "/api/control-token" and delay_diagnostics:
                stuck.set()
                await release.wait()
            if path.endswith("/heartbeat"):
                await anyio.sleep(0.04)
                response = await self.base.handle_async_request(request)
                if response.status_code < 400:
                    renewals.setdefault(path.split("/")[-2], []).append(time.monotonic())
                    connections.append(request.headers["X-Vibelution-External-Agent-Connection"])
                return response
            return await self.base.handle_async_request(request)

    def delayed_factory(project_root, **kwargs):
        client = original_factory(project_root, **kwargs)
        client.transport = DelayedNativeTransport(client.transport)
        return client
    service._client_factory = delayed_factory
    task_ids = []
    for n in range(4):
        row = await service.dispatch("project-a", agent_id=f"coder-{n}", task="read", dispatch_id=f"task-{n}")
        task_ids.append(row["nativeTaskId"])
    previous_connection = service._active_project_clients["project-a"].client.adapter_connection_id
    credentials = next((tmp_path / "profile" / "assistant_dispatch" / "credentials").glob("*.json"))
    before = json.loads(credentials.read_text(encoding="utf-8"))
    base, origin = datetime.now(timezone.utc), time.monotonic()
    def scaled_clock():
        return base + timedelta(seconds=(time.monotonic() - origin) * 20)
    monkeypatch.setattr(native_store, "_utc_now", scaled_clock)
    delay_diagnostics = True
    completed = anyio.Event()
    async def existing_reconcile():
        await service.reconcile("task-0")
        completed.set()
    try:
        async with anyio.create_task_group() as group:
            group.start_soon(existing_reconcile)
            await stuck.wait()
            async with service.drain_fence() as fence:
                assert (await fence.observe())["drained"] is False
                with anyio.fail_after(4):
                    while time.monotonic() - origin < 1.7 or min(len(renewals.get(tid, [])) for tid in task_ids) < 3:
                        native.reconcile(now_iso=scaled_clock().isoformat())
                        await anyio.sleep(0.05)
                assert not completed.is_set() and not runtime.stop_calls
                assert all(native.store.get_task(tid)["status"] == "running" for tid in task_ids)
                assert set(connections) == {previous_connection}
            # The verifier loaded its snapshot before the old SDK wrote this.
            # Its later task-status write must preserve the newer snapshot.
            prior = service._active_project_clients["project-a"].client
            async with prior._state_lock:
                prior._state["requests"]["newer-request"] = {"taskId": task_ids[1]}
                prior._save_state_locked()
            release.set()
    finally:
        release.set()
    assert completed.is_set()
    after = json.loads(credentials.read_text(encoding="utf-8"))
    assert after["requests"] == {**before["requests"], "newer-request": {"taskId": task_ids[1]}}
    assert set(after["tasks"]) == set(before["tasks"]) == set(task_ids)


@pytest.mark.anyio
async def test_cached_client_refuses_changed_task_credentials_or_runtime_binding(tmp_path, monkeypatch):
    from tests.test_assistant_runtime_dispatch import native_adapter
    from tests.test_external_agent_task_service import FakeRuntime

    service, _, _, _ = native_adapter(tmp_path, FakeRuntime())
    result = await service.dispatch("project-a", agent_id="coder", task="read", dispatch_id="original")
    task_id = result["nativeTaskId"]
    slot = service._active_project_clients["project-a"]
    assert await service._borrowed_lease_identity_current("project-a", task_id, slot)
    path = slot.client.state_path
    original = path.read_text(encoding="utf-8")
    altered = json.loads(original)
    altered["tasks"][task_id]["taskCapability"] = "revoked-or-replaced"
    path.write_text(json.dumps(altered), encoding="utf-8")
    assert not await service._borrowed_lease_identity_current("project-a", task_id, slot)
    path.write_text(original, encoding="utf-8")
    descriptor = slot.client._runtime_descriptor()
    monkeypatch.setattr(slot.client, "_runtime_descriptor", lambda: {**descriptor, "baseUrl": "http://127.0.0.1:1"})
    assert not await service._borrowed_lease_identity_current("project-a", task_id, slot)


@pytest.mark.anyio
async def test_first_verification_hung_cannot_renew_or_prove_drain_then_recovers(tmp_path, monkeypatch):
    import httpx
    import core.assistant_runtime.dispatch as dispatch_module
    from tests.test_assistant_runtime_dispatch import native_adapter
    from tests.test_external_agent_task_service import FakeRuntime

    monkeypatch.setattr(dispatch_module, "_DRAIN_HEARTBEAT_INTERVAL", 0.1)
    monkeypatch.setattr(dispatch_module, "_DRAIN_OBSERVE_TIMEOUT", 0.15)
    runtime = FakeRuntime()
    initial, _, _, original_factory = native_adapter(tmp_path, runtime)
    await initial.dispatch("project-a", agent_id="coder", task="read", dispatch_id="original")
    started, release, completed = anyio.Event(), anyio.Event(), anyio.Event()
    renewals = []
    class DelayedNativeTransport(httpx.AsyncBaseTransport):
        def __init__(self, base):
            self.base = base
        async def handle_async_request(self, request):
            if request.url.path == "/api/control-token":
                started.set()
                await release.wait()
            response = await self.base.handle_async_request(request)
            if request.url.path.endswith("/heartbeat"):
                renewals.append(response.status_code)
            return response
    def delayed_factory(project_root, **kwargs):
        client = original_factory(project_root, **kwargs)
        client.transport = DelayedNativeTransport(client.transport)
        return client
    # A fresh host has no previously verified client even though records exist.
    service = DispatchService(tmp_path / "profile", {"project-a": tmp_path / "project"}, client_factory=delayed_factory)
    async def reconcile():
        await service.reconcile("original")
        completed.set()
    try:
        async with anyio.create_task_group() as group:
            group.start_soon(reconcile)
            await started.wait()
            async with service.drain_fence() as fence:
                assert (await fence.observe())["drained"] is False
                assert not renewals and not completed.is_set()
                release.set()
                with anyio.fail_after(2):
                    await completed.wait()
                assert renewals and all(code < 400 for code in renewals)
                assert (await fence.observe())["drained"] is False
    finally:
        release.set()
    assert not runtime.stop_calls
