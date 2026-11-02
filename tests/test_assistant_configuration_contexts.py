"""Only a finished native configuration scope can recover an uncertain lease."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from core.assistant_runtime import configuration_contexts as contexts
from core.assistant_runtime.configuration_control import NativeRegistryLease
from core.assistant_runtime.configuration_references import ConfigurationReferenceError
from core.assistant_runtime.host import create_app
from core.infrastructure.model_reference_fence import model_reference_fence


def context():
    return "cfg-" + uuid4().hex


@pytest.fixture(autouse=True)
def isolate_contexts(monkeypatch):
    monkeypatch.setattr(contexts, "_CONTEXTS", {})
    monkeypatch.setattr(contexts, "_ACKNOWLEDGED", {})


def test_active_fence_foreign_broker_and_foreign_thread_cannot_publish_completion(tmp_path, monkeypatch):
    monkeypatch.setattr("config.paths.resolve_config_path", lambda: tmp_path / "config.toml")
    broker, other, key = object(), object(), context()
    contexts.register(broker, key)
    assert contexts.state(broker, key)["known"] is True
    assert contexts.state(broker, key)["workComplete"] is False
    assert contexts.state(other, key)["known"] is False
    assert contexts.acknowledge(broker, key)["acknowledged"] is False
    with model_reference_fence():
        assert contexts.complete(broker, key, released=False) is False
    with ThreadPoolExecutor(1) as worker:
        assert worker.submit(contexts.complete, broker, key, released=False).result() is False
    assert contexts.complete(other, key, released=False) is False
    assert contexts.complete(broker, key, released=False) is True
    assert contexts.state(broker, key)["workComplete"] is True
    assert contexts.acknowledge(other, key)["acknowledged"] is False
    assert contexts.acknowledge(broker, key)["acknowledged"] is True
    assert contexts.state(broker, key)["known"] is False
    assert contexts.acknowledge(broker, key)["acknowledged"] is True
    assert contexts.acknowledge(other, key)["acknowledged"] is False
    with pytest.raises(ValueError):
        contexts.register(broker, key)


def test_recovery_budget_never_evicts_active_or_unreleased_unknown_scopes(monkeypatch):
    monkeypatch.setattr(contexts, "_LIMIT", 2)
    broker, active, pending = object(), context(), context()
    contexts.register(broker, active)
    contexts.register(broker, pending)
    contexts.complete(broker, pending, released=False)
    with pytest.raises(RuntimeError):
        contexts.register(broker, context())
    assert contexts.state(broker, active)["known"]
    assert contexts.state(broker, pending)["workComplete"]
    contexts.acknowledge(broker, pending)
    closed = context()
    contexts.register(broker, closed)
    contexts.complete(broker, closed, released=True)
    contexts.register(broker, context())
    assert not contexts.state(broker, closed)["known"]
    assert contexts.acknowledge(broker, closed)["acknowledged"]
    assert contexts.state(broker, active)["known"]


def test_known_busy_refusals_do_not_exhaust_recovery_but_unknown_acquire_stays_pinned(monkeypatch):
    monkeypatch.setattr(contexts, "_LIMIT", 2)
    broker = object()
    unknown = NativeRegistryLease(broker, None, {"turnId": "trusted"})
    monkeypatch.setattr(unknown, "_send", lambda _action: {"complete": False, "code": "unavailable"})
    with pytest.raises(ConfigurationReferenceError):
        unknown.__enter__()
    assert contexts.state(broker, unknown.context_id)["workComplete"]
    for _ in range(4):
        refused = NativeRegistryLease(broker, None, {"turnId": "trusted"})
        monkeypatch.setattr(refused, "_send", lambda _action: {"complete": False, "code": "busy"})
        with pytest.raises(ConfigurationReferenceError):
            refused.__enter__()
        assert refused.closed
        assert contexts.state(broker, unknown.context_id)["known"]


@pytest.mark.parametrize("failure", ["acquire", "release", "body"])
def test_lease_finally_publishes_only_after_worker_scope_exits(monkeypatch, tmp_path, failure):
    monkeypatch.setattr("config.paths.resolve_config_path", lambda: tmp_path / "config.toml")
    monkeypatch.setattr("core.infrastructure.native_runtime.assistant_native_root", lambda: tmp_path)
    broker, sent = object(), []
    lease = NativeRegistryLease(broker, None, {"turnId": "trusted-turn"})

    def send(action):
        sent.append(action)
        assert contexts.state(broker, lease.context_id)["workComplete"] is False
        if action.endswith("acquire"):
            if failure == "acquire":
                raise RuntimeError("lost control ack")
            return {"complete": True, "nativeAssistantRoot": str(tmp_path)}
        if failure == "release":
            raise RuntimeError("lost release ack")
        return {"released": True}

    monkeypatch.setattr(lease, "_send", send)
    with pytest.raises((ConfigurationReferenceError, RuntimeError)):
        with lease:
            with model_reference_fence():
                assert contexts.state(broker, lease.context_id)["workComplete"] is False
                with pytest.raises(ConfigurationReferenceError):
                    lease.close()
            if failure == "body":
                raise RuntimeError("native operation failed")
    assert contexts.state(broker, lease.context_id)["workComplete"] is True
    assert lease.closed is (failure == "body")
    assert len(sent) == {"acquire": 1, "release": 3, "body": 2}[failure]


def test_foreign_thread_cannot_release_an_active_native_lease(monkeypatch, tmp_path):
    monkeypatch.setattr("core.infrastructure.native_runtime.assistant_native_root", lambda: tmp_path)
    lease = NativeRegistryLease(object(), None, {"turnId": "trusted-turn"})
    sent = []
    monkeypatch.setattr(lease, "_send", lambda action: sent.append(action) or
                        ({"complete": True, "nativeAssistantRoot": str(tmp_path)} if action.endswith("acquire") else {"released": True}))
    with lease:
        with ThreadPoolExecutor(1) as worker:
            with pytest.raises(ConfigurationReferenceError):
                worker.submit(lease.close).result()
        assert len(sent) == 1
    assert lease.closed


def test_private_completion_endpoints_are_closed_authenticated_and_broker_scoped():
    async def scenario():
        broker, other, key = SimpleNamespace(configuration_enabled=True), object(), context()
        contexts.register(broker, key)
        app = create_app(native=object(), token="private-config-context-test-token", main_control=broker)
        path = "/api/assistant/configuration-reference/contexts/" + key
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            assert (await client.get(path)).status_code == 401
            client.headers["Authorization"] = "Bearer private-config-context-test-token"
            assert (await client.get(path, headers={"Origin": "http://localhost"})).status_code == 403
            assert (await client.get(path)).json() == {"schemaVersion": 1, "contextId": key, "known": True, "workComplete": False}
            assert (await client.post(path + "/ack", json={"schemaVersion": 1})).json()["acknowledged"] is False
            assert (await client.get(path + "?foreign=1")).status_code == 422
            assert (await client.get(path.replace(key, "invalid"))).status_code == 422
            for body in ['{"schemaVersion":true}', '{"schemaVersion":1,"schemaVersion":1}',
                         '{"schemaVersion":1,"complete":true}', '[]', 'null']:
                assert (await client.post(path + "/ack", content=body)).status_code == 422
            assert contexts.complete(other, key, released=False) is False
            assert contexts.complete(broker, key, released=False)
            assert (await client.get(path)).json()["workComplete"] is True
            assert (await client.post(path + "/ack", json={"schemaVersion": 1})).json() == {
                "schemaVersion": 1, "contextId": key, "acknowledged": True}
            assert (await client.get(path)).json()["known"] is False
        old = create_app(native=object(), token="private-config-context-test-token", main_control=SimpleNamespace(configuration_enabled=False))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=old), base_url="http://127.0.0.1",
                                    headers={"Authorization": "Bearer private-config-context-test-token"}) as client:
            assert (await client.get(path)).status_code == 404
    asyncio.run(scenario())
