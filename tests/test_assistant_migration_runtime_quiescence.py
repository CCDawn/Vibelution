"""Joint barrier tests use only in-memory owners; no operator profile is opened."""

import asyncio
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import pytest

from fastapi.testclient import TestClient

from core.assistant_runtime.host import MigrationQuiescenceUnavailable, create_app, migration_runtime_quiescence


class Native:
    def __init__(self, busy=False):
        self.busy = busy
        self.held = False
        self.thread = None

    @contextmanager
    def session_quiescence(self):
        if self.busy:
            raise RuntimeError("session busy")
        self.thread = threading.get_ident()
        self.held = True
        try:
            yield
        finally:
            assert threading.get_ident() == self.thread
            self.held = False

    def bootstrap(self):
        return {"assistant": {"agentId": "agent", "directSessionId": "session"}}

    def submit(self, message, request_id):
        return {"accepted": True, "message": message, "requestId": request_id}

    def shutdown(self):
        pass


class Dispatch:
    def __init__(self, result):
        self.result = result
        self.held = False

    @asynccontextmanager
    async def drain_fence(self):
        self.held = True
        try:
            yield self
        finally:
            self.held = False

    async def observe(self):
        return self.result

    async def heartbeat(self):
        pass


def test_joint_fences_remain_held_until_scope_exits():
    async def run():
        native, dispatch = Native(), Dispatch({"drained": True})
        history = SimpleNamespace(_import_lock=threading.Lock())
        control = SimpleNamespace(_pending={}, _initial_tokens=set())
        async with migration_runtime_quiescence(native, dispatch, history, control):
            assert native.held and dispatch.held
            assert not history._import_lock.acquire(blocking=False)
        assert not native.held and not dispatch.held
        assert history._import_lock.acquire(blocking=False)
        history._import_lock.release()
    asyncio.run(run())


def test_private_barrier_rejects_unaccepted_writes_and_release_restores_same_id():
    native, dispatch = Native(), Dispatch({"drained": True})
    app = create_app(native=native, dispatch=dispatch, token="private-test-token", on_shutdown=lambda: None)
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        assert client.post("/api/assistant/migration-barrier/prepare", json={}).json()["state"] == "probing"
        for _ in range(100):
            if client.get("/api/assistant/migration-barrier/status").json()["state"] == "ready":
                break
            time.sleep(0.01)
        else:
            pytest.fail("barrier did not acquire")
        message = {"message": "保留原文", "requestId": "original-id"}
        assert client.post("/api/assistant/messages", json=message).status_code == 503
        assert client.post("/api/assistant/migration-barrier/release", json={}).json()["state"] == "idle"
        assert client.post("/api/assistant/messages", json=message).json()["requestId"] == "original-id"
        assert not native.held and not dispatch.held


def test_unknown_native_release_never_authorizes_shutdown():
    class BrokenNative(Native):
        @contextmanager
        def session_quiescence(self):
            yield
            raise RuntimeError("release not confirmed")

    stopped = []
    app = create_app(native=BrokenNative(), dispatch=Dispatch({"drained": True}), token="private-test-token",
                     on_shutdown=lambda: stopped.append(True))
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        client.post("/api/assistant/migration-barrier/prepare", json={})
        for _ in range(100):
            if client.get("/api/assistant/migration-barrier/status").json()["state"] == "ready":
                break
            time.sleep(0.01)
        else:
            pytest.fail("barrier did not acquire")
        assert client.post("/api/assistant/shutdown", json={}).status_code == 503
        assert stopped == []
        assert client.post("/api/assistant/messages", json={"message": "pending", "requestId": "id"}).status_code == 503


def test_real_dispatch_record_stays_running_until_terminal_without_cancel(tmp_path):
    from tests.test_assistant_dispatch_drain import Remote, service_for, start

    async def run():
        remote = Remote()
        service = service_for(tmp_path, remote)
        await start(service)
        native = Native()
        with pytest.raises(MigrationQuiescenceUnavailable):
            async with migration_runtime_quiescence(native, service, None, None):
                pytest.fail("running task cannot certify drain")
        assert any(name == "heartbeat" for name, _ in remote.calls)
        assert not any(name == "cancel" for name, _ in remote.calls)
        remote.status = "succeeded"
        async with migration_runtime_quiescence(native, service, None, None):
            assert native.held
        assert not any(name == "cancel" for name, _ in remote.calls)
        assert sum(name == "start" for name, _ in remote.calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize("case", ["running", "unknown", "history", "control"])
def test_unfinished_or_unknown_producers_never_certify(case):
    async def run():
        native = Native(busy=case == "running")
        dispatch = Dispatch({"drained": False} if case == "unknown" else {"drained": True})
        history = SimpleNamespace(_import_lock=threading.Lock())
        control = SimpleNamespace(_pending={"delivery": object()} if case == "control" else {}, _initial_tokens=set())
        if case == "history":
            history._import_lock.acquire()
        try:
            with pytest.raises(MigrationQuiescenceUnavailable):
                async with migration_runtime_quiescence(native, dispatch, history, control):
                    pytest.fail("busy or unknown evidence must not certify")
            assert not native.held and not dispatch.held
        finally:
            if case == "history":
                history._import_lock.release()
    asyncio.run(run())
