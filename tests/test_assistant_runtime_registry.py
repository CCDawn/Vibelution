"""Private main snapshots revoke queued calls without rebuilding the chat owner."""
import asyncio

import pytest

from core.assistant_runtime.dispatch import DispatchError, DispatchService


def snapshot(revision, projects):
    return {"schemaVersion": 1, "revision": revision, "projects": {key: str(value) for key, value in projects.items()}}


@pytest.mark.anyio
async def test_authorized_snapshot_is_shared_with_management_and_removal_retains_receipts(tmp_path):
    from tests.test_assistant_runtime_management import Probe
    probe = Probe()
    service = DispatchService(tmp_path / "profile", {"old:epoch-1": tmp_path / "project"}, client_factory=probe.factory)
    params = {"display_name": "Worker", "model_id": "p/m"}
    await service.management.invoke("old:epoch-1", action="agent_create", request_id="stable", parameters=params)
    before = next((tmp_path / "profile/assistant_management").glob("*.json")).read_bytes()
    service.replace_projects(snapshot(1, {}))
    assert service.project_ids() == ()
    with pytest.raises(DispatchError) as removed:
        await service.management.receipt("old:epoch-1", action="agent_create", request_id="stable")
    assert removed.value.code == "PROJECT_NOT_AUTHORIZED" and len(probe.writes) == 1
    assert next((tmp_path / "profile/assistant_management").glob("*.json")).read_bytes() == before
    with pytest.raises(DispatchError) as resurrected:
        service.replace_projects(snapshot(2, {"old:epoch-1": tmp_path / "project"}))
    assert resurrected.value.code == "PROJECT_REGISTRY_REVOKED"
    service.replace_projects(snapshot(2, {"old:epoch-2": tmp_path / "project"}))
    assert service.project_ids() == ("old:epoch-2",)
    await service.management.invoke("old:epoch-2", action="agent_create", request_id="new", parameters=params)
    assert len(probe.writes) == 2


def test_registry_rejects_stale_conflicting_and_relative_snapshots_atomically(tmp_path):
    service = DispatchService(tmp_path, {"p:one": tmp_path / "project"})
    first = snapshot(5, {"p:one": tmp_path / "project"})
    assert service.replace_projects(first)["revision"] == 5
    assert service.replace_projects(first)["revision"] == 5
    for invalid in (snapshot(4, {}), snapshot(5, {}), snapshot(6, {"p:one": tmp_path / "other"}),
                    {"schemaVersion": 1, "revision": 6, "projects": {"relative": "../other"}},
                    {"schemaVersion": 1, "revision": True, "projects": {}}, {**first, "extra": True}):
        with pytest.raises(DispatchError):
            service.replace_projects(invalid)
        assert service.project_ids() == ("p:one",)


def test_revision_zero_initial_nonempty_snapshot_is_installed_before_native_startup(tmp_path):
    service = DispatchService(tmp_path, {})
    initial = snapshot(0, {"p:initial": tmp_path / "project"})
    assert service.replace_projects(initial) == {"schemaVersion": 1, "revision": 0, "projectCount": 1}
    assert service.project_ids() == ("p:initial",)
    with pytest.raises(DispatchError) as conflict:
        service.replace_projects(snapshot(0, {}))
    assert conflict.value.code == "PROJECT_REGISTRY_CONFLICT"


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ["lock_wait", "diagnostics"])
async def test_revocation_fences_calls_waiting_for_project_lock_or_handshake(tmp_path, phase):
    entered, release = asyncio.Event(), asyncio.Event()
    writes = []
    def factory(*args, **kwargs):
        class Client:
            async def diagnostics(self):
                if phase == "diagnostics":
                    entered.set()
                    await release.wait()
            async def list_agents(self, **kwargs):
                writes.append(True)
                return {"agents": []}
        return Client()
    service = DispatchService(tmp_path, {"p:one": tmp_path / "project"}, client_factory=factory)
    if phase == "lock_wait":
        import anyio
        lock = service._project_locks.setdefault("p:one", anyio.Lock())
        await lock.acquire()
    task = asyncio.create_task(service.discover("p:one"))
    if phase == "diagnostics":
        await entered.wait()
    else:
        await asyncio.sleep(0)
    service.replace_projects(snapshot(1, {}))
    if phase == "lock_wait":
        lock.release()
    else:
        release.set()
    with pytest.raises(DispatchError) as denied:
        await task
    assert denied.value.code == "PROJECT_NOT_AUTHORIZED" and writes == []
