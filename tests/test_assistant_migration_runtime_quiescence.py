"""Joint barrier tests use only in-memory owners; no operator profile is opened."""

import asyncio
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import pytest

from fastapi.testclient import TestClient

from core.assistant_runtime.host import MigrationQuiescenceUnavailable, create_app, migration_runtime_quiescence
from core.assistant_runtime.native import AssistantSessionError


class Native:
    def __init__(self, busy=False):
        self.busy = busy
        self.held = False
        self.thread = None

    @contextmanager
    def session_quiescence(self):
        if self.busy:
            raise AssistantSessionError("ASSISTANT_QUIESCENCE_BUSY")
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


@pytest.mark.parametrize("case,stage,code", [
    ("running", "native_quiescence", "ASSISTANT_QUIESCENCE_BUSY"),
    ("unknown", "dispatch_observation", "records_unknown"),
    ("history", "history_import", "history_busy"),
    ("control", "main_control", "main_control_busy_or_unknown"),
])
def test_unfinished_or_unknown_producers_never_certify(case, stage, code, caplog):
    async def run():
        native = Native(busy=case == "running")
        dispatch = Dispatch({"drained": False, "reason": "records_unknown"} if case == "unknown" else {"drained": True})
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
    record = next(row for row in caplog.records if row.getMessage().startswith(
        f"assistant_migration_quiescence stage={stage} code={code} elapsed_ms="))
    assert type(record.args[-1]) is int and record.args[-1] >= 0


@pytest.mark.parametrize("stage", ["native_quiescence", "dispatch_fence", "dispatch_observation"])
def test_quiescence_failure_logs_never_include_exception_or_observation_text(stage, caplog):
    from core.assistant_runtime.dispatch import DispatchError

    private = "C:/private/draft.txt bearer-secret user-message"
    failure = DispatchError(private, code="DISPATCH_DRAIN_ADMISSION_BUSY")

    class BrokenNative(Native):
        @contextmanager
        def session_quiescence(self):
            raise RuntimeError(private)
            yield

    class BrokenDispatch(Dispatch):
        @asynccontextmanager
        async def drain_fence(self):
            raise failure
            yield

    async def run():
        native = BrokenNative() if stage == "native_quiescence" else Native()
        dispatch = BrokenDispatch(None) if stage == "dispatch_fence" else Dispatch({"drained": False, "reason": private})
        with pytest.raises(MigrationQuiescenceUnavailable if stage != "dispatch_fence" else DispatchError) as raised:
            async with migration_runtime_quiescence(native, dispatch, None, None):
                pytest.fail("failed proof cannot certify drain")
        if stage == "dispatch_fence":
            assert raised.value is failure
        else:
            assert str(raised.value) == ("session_release_unknown" if stage == "native_quiescence" else "dispatch_busy_or_unknown")
        assert not native.held and not dispatch.held

    asyncio.run(run())
    code = "DISPATCH_DRAIN_ADMISSION_BUSY" if stage == "dispatch_fence" else "unexpected"
    assert f"assistant_migration_quiescence stage={stage} code={code} elapsed_ms=" in caplog.text
    assert private not in caplog.text
    assert not any(row.exc_info for row in caplog.records)


@pytest.mark.parametrize("known_code", [True, False])
def test_barrier_source_permit_failure_is_logged_without_changing_busy_dto(monkeypatch, caplog, known_code):
    from core.assistant_runtime.migration_io import MigrationIOError
    from core.assistant_runtime.reminder_source_lease import ReminderSourceLeaseOwner

    private = "C:/private/source.txt bearer-secret user-message"

    def fail_revocation(self):
        raise MigrationIOError("reminder_lease_owner_closed" if known_code else private)

    monkeypatch.setattr(ReminderSourceLeaseOwner, "begin_revocation", fail_revocation)
    native, dispatch = Native(), Dispatch({"drained": True})
    history = SimpleNamespace(_preview=SimpleNamespace(_dispatch=dispatch), close=lambda: None)
    app = create_app(native=native, dispatch=dispatch, history_control=history,
                     token="private-test-token", on_shutdown=lambda: None)
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        assert client.post("/api/assistant/migration-barrier/prepare", json={}).json() == {"schemaVersion": 1, "state": "probing"}
        for _ in range(100):
            state = client.get("/api/assistant/migration-barrier/status").json()
            if state["state"] != "probing":
                break
            time.sleep(0.01)
        assert state == {"schemaVersion": 1, "state": "busy"}
        assert client.post("/api/assistant/messages", json={"message": "pending", "requestId": "id"}).status_code == 200
        assert client.post("/api/assistant/migration-barrier/release", json={}).json() == {"schemaVersion": 1, "state": "idle"}
    code = "reminder_lease_owner_closed" if known_code else "unexpected"
    record = next(row for row in caplog.records if row.getMessage().startswith(
        f"assistant_migration_barrier stage=source_permits code={code} elapsed_ms="))
    assert type(record.args[-1]) is int and record.args[-1] >= 0
    assert private not in caplog.text
    assert not any(row.exc_info for row in caplog.records)
