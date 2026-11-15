"""Launcher re-enrollment is exact, recoverable and isolated from old requests."""
from types import SimpleNamespace

import pytest

from core.assistant_runtime.dispatch import DispatchError
from core.assistant_runtime.local_project_client import LocalAssistantBackendClient
from core.assistant_runtime.management import ManagementAdapter
from core.assistant_runtime.migration_io import MigrationIOError
from core.external_agent.backend_client import BackendClientError
from core.infrastructure.file_lock import lock_path_for
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


@pytest.mark.parametrize("location", ["directory", "lock"])
def test_recovery_refuses_an_unsafe_namespace_before_taking_locks(grants, monkeypatch, location):
    original = type(grants.subject).lstat
    unsafe = grants.subject.parent if location == "directory" else lock_path_for(grants.subject.with_suffix(".lock"))
    if location == "lock":
        unsafe.touch()

    def lstat(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if path == unsafe:
            return SimpleNamespace(st_mode=value.st_mode, st_file_attributes=0x400)
        return value

    monkeypatch.setattr(type(unsafe), "lstat", lstat)
    monkeypatch.setattr(grants.service.store, "lock", lambda *_: pytest.fail("unsafe namespace must not be locked"))
    with pytest.raises(MigrationIOError, match="linked_source"):
        recover(grants.service, grants.identity, launcher_capability="trusted-launcher")


def test_recovery_transport_requires_launcher_and_privileged_operator(grants, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.infrastructure import launcher_assistant_authority
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes import launcher_assistant_management as route
    from core.web.services.team_workflow.research_runtime.operator_authorization import CONTROL_OPERATOR_ROLES_ENV

    monkeypatch.setattr(route, "_SERVICE", grants.service)
    monkeypatch.setattr(launcher_assistant_authority, "verify_launcher_authority", lambda key: key == "launcher-proof")
    grants.subject.unlink()
    grants.index.unlink()
    app = FastAPI()
    app.include_router(route.router, prefix="/api")
    url = "/api/v1/launcher-assistant-management/subjects/recovery/check"
    headers = {CONTROL_TOKEN_HEADER: get_control_token(), route.SUBJECT_HEADER: "launcher-local",
               route.CAPABILITY_HEADER: "launcher-proof"}
    with TestClient(app) as http:
        assert http.post(url, json=grants.identity.model_dump()).status_code == 403
        weak = {**headers, route.CAPABILITY_HEADER: "untrusted"}
        assert http.post(url, json=grants.identity.model_dump(), headers=weak).json()["detail"]["code"] == "LAUNCHER_AUTHORITY_REQUIRED"
        monkeypatch.setenv(CONTROL_OPERATOR_ROLES_ENV, "viewer")
        assert http.post(url, json=grants.identity.model_dump(), headers=headers).json()["detail"]["code"] == "OPERATOR_CONTROL_REQUIRED"
        monkeypatch.setenv(CONTROL_OPERATOR_ROLES_ENV, "operator")
        assert http.post(url, json=grants.identity.model_dump(), headers=headers).json() == {"available": True}
    assert not any("/subjects/recovery/" in path for path in app.openapi()["paths"])


@pytest.mark.asyncio
async def test_corrupt_enrollment_ack_remains_resumable_after_restart(grants, tmp_path, monkeypatch):
    launcher_key = "x" * 43
    project = tmp_path / "p"
    state_path = tmp_path / "state.json"
    scopes = ["agents:directory:read", "teams:directory:read"]
    enroll_calls = []

    async def request(_method, path, management_auth=None, json_payload=None):
        try:
            if path.endswith("/binding"):
                return grants.service.binding()
            if path.endswith("/authorization"):
                return grants.service.authorization_status(*management_auth)
            if path.endswith("/check"):
                return recover(grants.service, RecoveryIdentity.model_validate(json_payload),
                               launcher_capability=launcher_key)
            assert path.endswith("/enroll")
            result = recover(grants.service, RecoverSubject.model_validate(json_payload), launcher_capability=launcher_key)
            enroll_calls.append(result["subject_id"])
            if len(enroll_calls) <= 2:
                raise BackendClientError("Malformed or missing response", code="BACKEND_PROTOCOL_ERROR")
            return result
        except ManagementError as exc:
            raise BackendClientError(str(exc), code=exc.code) from None

    client = LocalAssistantBackendClient(project, capability=launcher_key, state_path=state_path)
    client._state["management"] = {"clientId": grants.identity.client_id, "subjectId": grants.old["subject_id"],
        "capability": grants.old["subject_capability"], "binding": grants.old["binding"], "scopes": grants.old["scopes"]}
    client._save_state_locked()
    grants.subject.unlink()
    grants.index.unlink()
    monkeypatch.setattr(client, "_request_json", request)
    plan = await client.management_authorization_status(planned_scopes=scopes)
    with pytest.raises(BackendClientError) as failure:
        await client.management_recover(request_id="original-consent", scopes=scopes, challenge=plan["recovery_challenge"])
    assert failure.value.code == "BACKEND_PROTOCOL_ERROR"

    restarted = LocalAssistantBackendClient(project, capability=launcher_key, state_path=state_path)
    monkeypatch.setattr(restarted, "_request_json", request)
    status = await restarted.management_authorization_status()
    assert status["scopes"] == scopes
    assert "pendingRecovery" not in restarted._state["management"]
    assert enroll_calls == [status["subjectId"]] * 3


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

        async def management_reconciliation(self, **arguments):
            reads.append(arguments)
            return {"status": "unavailable"}

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
    with pytest.raises(DispatchError, match="原请求"):
        await adapter.reconciliation("p", action="agent_create", request_id="old")
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
