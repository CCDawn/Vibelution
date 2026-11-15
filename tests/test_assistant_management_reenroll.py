"""Launcher re-enrollment is exact, recoverable and isolated from old requests."""
from types import SimpleNamespace

import pytest

from core.assistant_runtime.dispatch import DispatchError
from core.assistant_runtime.management import ManagementAdapter
from core.web.services.external_management.recovery import RecoverSubject, RecoveryIdentity, recover
from core.web.services.external_management.service import ManagementError, ManagementService, TargetIdentity


@pytest.fixture
def grants(tmp_path):
    binding = {"projectId": "isolated", "instanceId": "same-instance"}
    service = ManagementService(tmp_path / "management", identity=lambda: TargetIdentity(binding, "authority"), native=None)
    client = "retained-old-client-identity"
    old = service.bind({"client_id": client, "expected_binding": binding, "scopes": ["agents:read", "rooms:read"]})
    identity = RecoveryIdentity(client_id=client, subject_id=old["subject_id"], expected_binding=binding)
    return SimpleNamespace(service=service, identity=identity, old=old,
        subject=service.store.path("subjects", old["subject_id"]), index=service.store.path("clients", client))


@pytest.mark.parametrize("state, code", [
    ("present", "ORIGINAL_GRANT_PRESENT"), ("subject_missing", "ORIGINAL_GRANT_PRESENT"),
    ("index_missing", "ORIGINAL_GRANT_PRESENT"), ("revoked", "SUBJECT_REVOKED"),
])
def test_recovery_does_not_treat_denial_or_partial_records_as_loss(grants, state, code):
    if state == "subject_missing":
        grants.subject.unlink()
    if state == "index_missing":
        grants.index.unlink()
    if state == "revoked":
        grants.service.store.write(grants.subject, {**grants.service.store.read(grants.subject), "revoked": True})
    with pytest.raises(ManagementError) as failure:
        recover(grants.service, grants.identity, launcher_capability="trusted-launcher")
    assert failure.value.code == code


def test_recovery_retries_exact_approved_subject_after_missing_ack(grants, monkeypatch):
    grants.subject.unlink()
    grants.index.unlink()
    assert recover(grants.service, grants.identity, launcher_capability="trusted-launcher") == {"available": True}
    request = RecoverSubject(**grants.identity.model_dump(), request_id="one-consent",
                             scopes=["agents:directory:read", "teams:directory:read"])
    store = grants.service.store
    write = store.write

    def fail_index(path, value):
        if path.parent.name == "clients":
            raise OSError("index write interrupted")
        write(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(store, "write", fail_index)
        with pytest.raises(OSError):
            recover(grants.service, request, launcher_capability="trusted-launcher")
    assert recover(grants.service, grants.identity, launcher_capability="trusted-launcher") == {"available": False}
    result = recover(grants.service, request, launcher_capability="trusted-launcher")
    assert recover(grants.service, request, launcher_capability="trusted-launcher") == result
    assert result["subject_id"] != grants.old["subject_id"]
    assert result["scopes"] == request.scopes
    assert not grants.subject.exists() and not grants.index.exists()
    for changed, token in [(request.model_copy(update={"request_id": "new-request"}), "trusted-launcher"),
                           (request.model_copy(update={"scopes": ["rooms:read"]}), "trusted-launcher"),
                           (request, "other-launcher")]:
        with pytest.raises(ManagementError, match="RECOVERY_CONFLICT"):
            recover(grants.service, changed, launcher_capability=token)


@pytest.mark.asyncio
async def test_old_management_reference_cannot_execute_under_new_subject(tmp_path):
    writes, reads = [], []

    class Client:
        management_epoch = ""

        async def management_action(self, **arguments):
            writes.append(arguments)
            return {"status": "unknown"}

        async def management_receipt(self, **arguments):
            reads.append(arguments)
            return {"status": "unknown"}

    client = Client()

    async def call(_project, method):
        return await method(client)

    adapter = ManagementAdapter(tmp_path, {"p": tmp_path / "p"}, call)
    original = {"action": "agent_create", "request_id": "old", "parameters": {"name": "Example"}}
    await adapter.invoke("p", **original)
    client.management_epoch = "recovered"
    with pytest.raises(DispatchError) as failure:
        await adapter.invoke("p", **original)
    assert failure.value.code == "ORIGINAL_MANAGEMENT_IDENTITY_UNAVAILABLE"
    with pytest.raises(DispatchError, match="原请求"):
        await adapter.receipt("p", action="agent_create", request_id="old")
    assert not reads and len(writes) == 1
    await adapter.invoke("p", **{**original, "request_id": "fresh"})
    assert len(writes) == 2


@pytest.mark.asyncio
async def test_recovery_plan_holds_proof_privately_and_only_for_the_original_turn(tmp_path):
    scopes = ["agents:directory:read", "teams:directory:read"]
    submitted = []

    class Client:
        async def management_authorization_status(self, *, planned_scopes):
            assert planned_scopes == scopes
            return {"status": "recovery_required", "scopes": [], "recovery_challenge": "private-proof"}

        async def management_recover(self, **values):
            submitted.append(values)
            return {"status": "completed", "scopes": values["scopes"]}

    async def call(_project, method):
        return await method(Client())

    adapter = ManagementAdapter(tmp_path, {"p": tmp_path / "p"}, call)
    plan = await adapter.authorization_status("p", planned_scopes=scopes, turn_id="current")
    assert plan == {"status": "recovery_required", "scopes": [], "recoveryPlanAvailable": True, "projectId": "p"}
    for turn, consent_scopes in [("different", scopes), ("current", [*scopes, "source:read"])]:
        with pytest.raises(DispatchError) as failure:
            await adapter.recover("p", turn_id=turn, scopes=consent_scopes, request_id="one-consent")
        assert failure.value.code == "RECOVERY_PLAN_UNAVAILABLE"
    assert not submitted
    assert (await adapter.recover("p", turn_id="current", scopes=scopes, request_id="one-consent"))["status"] == "completed"
    assert submitted == [{"request_id": "one-consent", "scopes": scopes, "challenge": "private-proof"}]
