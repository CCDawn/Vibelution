"""Real native grant-store reductions, immutable history and exact revoke recovery."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from core.web.services.external_management.authorization_reduction import ReductionOwner
from core.web.services.external_management.authorization_reduction_contracts import (
    AuthorizationReduce, AuthorizationRevoke, AuthorizationReductionResponse,
)
from core.web.services.external_management.service import ManagementError, ManagementService, TargetIdentity
from core.web.services.external_management.store import digest
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope

BINDING = {"projectId": "project", "instanceId": "instance"}
SCOPES = sorted(["agents:read", "agents:update", "sessions:read", "teams:read"])
REMAINING = sorted(set(SCOPES) - {"agents:update"})


class Harness:
    def __init__(self, root):
        self.root = root
        self.identity = TargetIdentity(deepcopy(BINDING), "authority")
        self.service = ManagementService(root, identity=lambda: self.identity, native=object())
        self.store = self.service.store
        grant = self.service.bind({"client_id": "original-client", "expected_binding": BINDING, "scopes": SCOPES})
        self.subject, self.cap = grant["subject_id"], grant["subject_capability"]
        self.owner = self.restart()

    def restart(self):
        return ReductionOwner(self.store, lambda subject, capability, expected=None:
            self.service._authorize(subject, capability, None, expected), lambda: self.identity)

    def invoke(self, *, action="authorization_reduce", request_id="reduce-1", **parameters):
        if action == "authorization_reduce":
            parameters = {"remove_scopes": ["agents:update"], **parameters}
        values = {"expected_scopes": SCOPES, "expected_grant_revision": 0, **parameters}
        with server_operator_scope("operator-test", roles=("operator",)):
            return self.service.invoke(self.subject, self.cap, action, {"request_id": request_id,
                "expected_binding": BINDING, "parameters": values})

    def receipt(self, action="authorization_reduce", request_id="reduce-1", **credentials):
        with server_operator_scope(credentials.pop("operator_id", "operator-test"), roles=("operator",)):
            return self.service.receipt(credentials.pop("subject", self.subject), credentials.pop("capability", self.cap), action, request_id)

    def upgrade(self, expected=SCOPES, additions=None, request_id="upgrade-1"):
        with server_operator_scope("operator-test", roles=("operator",)):
            return self.service.invoke(self.subject, self.cap, "authorization_upgrade", {"request_id": request_id,
                "expected_binding": BINDING, "parameters": {"expected_scopes": expected,
                    "add_scopes": ["rooms:read"] if additions is None else additions}})

    def persisted(self):
        return self.store.read(self.store.path("subjects", self.subject))


@pytest.fixture
def env(tmp_path):
    return Harness(tmp_path / "management")


def test_reduce_is_one_atomic_native_subject_write_with_exact_scopes_revision_and_receipt(env, monkeypatch):
    old = env.persisted()
    old["opaqueTaskState"] = {"task": "native-task", "secret": "private state retained"}
    env.store.write(env.store.path("subjects", env.subject), old)
    clients = {path.name: path.read_bytes() for path in (env.root / "clients").glob("*.json")}
    original, writes = env.store.write, []
    def observe(path, value):
        writes.append(path)
        assert path == env.store.path("subjects", env.subject)
        assert value["scopes"] == REMAINING and value["grantRevision"] == 1
        assert len(value["scopeReductions"]) == 1
        assert next(iter(value["scopeReductions"].values()))["receipt"]["status"] == "completed"
        return original(path, value)
    monkeypatch.setattr(env.store, "write", observe)
    result = env.invoke()
    assert result["authorization"] == {"subjectId": env.subject, "previousScopes": SCOPES,
        "removedScopes": ["agents:update"], "scopes": REMAINING, "grantRevision": 1, "revoked": False}
    assert result["status"] == "completed" and result["verified"] and not result["reused"]
    assert len(writes) == 1 and not list((env.root / "requests").glob("*.json"))
    after = env.persisted()
    assert after["scopes"] == REMAINING and after["subject_capability"] == env.cap
    assert after["opaqueTaskState"] == old["opaqueTaskState"]
    assert {path.name: path.read_bytes() for path in (env.root / "clients").glob("*.json")} == clients
    with pytest.raises(ManagementError, match="SCOPE_DENIED"):
        env.service._authorize(env.subject, env.cap, "agents:update")
    assert env.service._authorize(env.subject, env.cap, "agents:read")["scopes"] == REMAINING
    assert env.cap not in json.dumps(result) and "private state" not in json.dumps(result)


@pytest.mark.parametrize("parameters", [{"subject_id": "another"}, {"actor": "operator"}, {"force": True},
    {"expected_grant_revision": True}, {"expected_grant_revision": -1}, {"remove_scopes": []},
    {"remove_scopes": SCOPES}, {"expected_scopes": []}, {"remove_scopes": ["unknown:scope"]},
    {"remove_scopes": ["rooms:read"]}, {"remove_scopes": ["agents:update", "agents:update"]},
    {"expected_scopes": list(reversed(SCOPES))}, {"remove_scopes": [True]}])
def test_closed_sorted_nonempty_schema_rejects_implicit_all_scope_or_foreign_actor(env, parameters):
    before = env.persisted()
    with pytest.raises(ManagementError) as rejected:
        env.invoke(**parameters)
    assert rejected.value.code == "INVALID_INPUT" and rejected.value.status_code == 422
    assert env.persisted() == before


def test_native_server_operator_context_is_required_for_mutation_and_receipt(env):
    for operation in (lambda: env.owner.invoke(env.subject, env.cap, "authorization_reduce", "r",
            expected_binding=BINDING, expected_scopes=SCOPES, expected_grant_revision=0, remove_scopes=["agents:update"]),
            lambda: env.owner.receipt(env.subject, env.cap, "authorization_reduce", "r")):
        with pytest.raises(ManagementError, match="OPERATOR_CONTROL_REQUIRED"):
            operation()
        with server_operator_scope("unprivileged", roles=("reader",)):
            with pytest.raises(ManagementError, match="OPERATOR_CONTROL_REQUIRED"):
                operation()
    assert env.persisted()["scopes"] == SCOPES


def test_revision_scope_cas_and_same_key_parameter_conflicts_preserve_prior_result(env):
    for values in ({"expected_grant_revision": 1}, {"expected_scopes": sorted(SCOPES + ["rooms:read"])}):
        with pytest.raises(ManagementError, match="AUTHORIZATION_CONFLICT"):
            env.invoke(**values)
    first = env.invoke()
    assert env.invoke() == {**first, "reused": True}
    env.owner = env.restart()
    assert env.receipt() == {**first, "reused": True}
    with pytest.raises(ManagementError, match="IDEMPOTENCY_CONFLICT"):
        env.invoke(remove_scopes=["sessions:read"])
    with pytest.raises(ManagementError, match="AUTHORIZATION_CONFLICT"):
        env.invoke(request_id="new-with-stale-state")
    assert env.persisted()["scopes"] == REMAINING and env.persisted()["grantRevision"] == 1


def test_revoke_seals_original_grant_and_only_exact_original_revoke_receipt_can_recover(env):
    reduction = env.invoke()
    old = env.persisted()
    revoked = env.invoke(action="authorization_revoke", request_id="revoke-1", expected_scopes=REMAINING, expected_grant_revision=1)
    after = env.persisted()
    assert after["revoked"] is True and after["scopes"] == REMAINING and after["grantRevision"] == 2
    assert after["scopeReductions"].keys() >= old["scopeReductions"].keys()
    assert revoked["authorization"]["scopes"] == [] and revoked["authorization"]["revoked"] is True
    env.service = ManagementService(env.root, identity=lambda: env.identity, native=object())
    env.store = env.service.store
    env.owner = env.restart()
    assert env.receipt("authorization_revoke", "revoke-1") == {**revoked, "reused": True}
    for operation in (lambda: env.invoke(), lambda: env.upgrade(), lambda: env.service.authorization_status(env.subject, env.cap),
            lambda: env.receipt(), lambda: env.receipt("authorization_revoke", "other-key"),
            lambda: env.receipt("authorization_revoke", "revoke-1", capability="x" * 48),
            lambda: env.receipt("authorization_revoke", "revoke-1", operator_id="other-operator")):
        with pytest.raises(ManagementError, match="SUBJECT_(DENIED|REVOKED)"):
            operation()
    assert env.persisted() == after
    for scope in (None, *SCOPES):
        with pytest.raises(ManagementError, match="SUBJECT_REVOKED"):
            env.service._authorize(env.subject, env.cap, scope)
    assert env.cap not in str(revoked) and env.cap not in str(reduction)


@pytest.mark.parametrize("change", ["capability", "subject", "binding", "authority"])
def test_original_capability_and_current_project_binding_are_mandatory(env, change):
    env.invoke(action="authorization_revoke", request_id="revoke-1")
    credentials = {}
    if change == "capability": credentials["capability"] = "x" * 48
    elif change == "subject": credentials["subject"] = "ops-" + "0" * 32
    elif change == "binding": env.identity = TargetIdentity({**BINDING, "instanceId": "new"}, "authority")
    else: env.identity = TargetIdentity(BINDING, "new-authority")
    with pytest.raises(ManagementError) as denied:
        env.receipt("authorization_revoke", "revoke-1", **credentials)
    assert denied.value.code in {"SUBJECT_DENIED", "TARGET_BINDING_CHANGED"}


def test_upgrade_reduce_old_upgrade_receipt_and_replay_never_restore_removed_scopes(env):
    first = env.upgrade()
    augmented = sorted(SCOPES + ["rooms:read"])
    reduced = env.invoke(expected_scopes=augmented, expected_grant_revision=1, remove_scopes=["rooms:read"])
    before = deepcopy(env.persisted())
    assert env.service.receipt(env.subject, env.cap, "authorization_upgrade", "upgrade-1") == {**first, "reused": True}
    assert env.upgrade() == {**first, "reused": True}
    assert env.persisted() == before and env.service.authorization_status(env.subject, env.cap)["scopes"] == SCOPES
    third = env.upgrade(request_id="upgrade-2", additions=["sessions:pin"])
    assert third["authorization"]["grantRevision"] == 3
    assert env.service.authorization_status(env.subject, env.cap)["scopes"] == sorted(SCOPES + ["sessions:pin"])
    assert env.receipt() == {**reduced, "reused": True}


@pytest.mark.parametrize("after_commit", [False, True])
def test_failed_subject_write_never_splits_authorization_revision_and_receipt(env, monkeypatch, after_commit):
    before, write = env.persisted(), env.store.write
    writes = []
    def fail(path, value):
        writes.append(path)
        if after_commit:
            write(path, value)
        raise OSError("SECRET native path")
    monkeypatch.setattr(env.store, "write", fail)
    if after_commit:
        first = env.invoke()
        assert first["status"] == "completed"
        assert env.persisted()["scopes"] == REMAINING
    else:
        with pytest.raises(ManagementError, match="AUTHORIZATION_UNAVAILABLE"):
            env.invoke()
        assert env.persisted() == before
    assert len(writes) == 1 and not list((env.root / "requests").glob("*.json"))
    monkeypatch.setattr(env.store, "write", write)
    if after_commit:
        assert env.receipt() == {**first, "reused": True}


def test_lost_commit_readback_is_unknown_then_restart_recovers_same_proof_without_write(env, monkeypatch):
    write, read = env.store.write, env.store.read
    committed = False
    def persisted(path, value):
        nonlocal committed
        write(path, value)
        committed = True
    def unavailable(path):
        if committed:
            raise OSError("SECRET read path")
        return read(path)
    monkeypatch.setattr(env.store, "write", persisted)
    monkeypatch.setattr(env.store, "read", unavailable)
    unknown = env.invoke(action="authorization_revoke", request_id="revoke-lost")
    assert unknown["status"] == "unknown" and not unknown["verified"] and "SECRET" not in str(unknown)
    monkeypatch.setattr(env.store, "read", read)
    monkeypatch.setattr(env.store, "write", lambda *_args: pytest.fail("receipt recovery wrote grant state"))
    env.owner = env.restart()
    recovered = env.receipt("authorization_revoke", "revoke-lost")
    assert recovered["status"] == "completed" and recovered["verified"] and recovered["authorization"]["revoked"]


def test_concurrent_upgrade_and_reduce_serialize_on_the_native_subject_cas(env):
    def operation(name):
        try:
            return (env.invoke() if name == "reduce" else env.upgrade())["status"]
        except ManagementError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(operation, ["reduce", "upgrade"]))
    assert sorted(outcomes) == ["AUTHORIZATION_CONFLICT", "completed"]
    assert env.persisted()["grantRevision"] == 1


@pytest.mark.parametrize("fault", ["scopes", "fingerprint", "capabilityHash", "revision", "receipt-subject", "recovery"])
def test_corrupt_reduction_proofs_fail_closed_without_repairing_history(env, fault):
    env.invoke(action="authorization_revoke" if fault == "recovery" else "authorization_reduce")
    grant = env.persisted()
    proof = next(iter(grant["scopeReductions"].values()))
    if fault == "scopes": grant["scopes"] = SCOPES
    elif fault == "fingerprint": proof["fingerprint"] = "0" * 64
    elif fault == "capabilityHash": proof["capabilityHash"] = "0" * 64
    elif fault == "revision": grant["grantRevision"] = True
    elif fault == "receipt-subject": proof["receipt"]["authorization"]["subjectId"] = "ops-" + "0" * 32
    else: grant["revocationRecovery"]["requestKey"] = "0" * 64
    env.store.write(env.store.path("subjects", env.subject), grant)
    with pytest.raises(ManagementError, match="AUTHORIZATION_STATE_INVALID"):
        env.receipt("authorization_revoke" if fault == "recovery" else "authorization_reduce")
    assert env.persisted() == grant


def test_contracts_describe_registered_scopes_and_exclude_identity_or_approval_flags(env):
    from core.web.services.external_management.contracts import SCOPES as registered
    for model in (AuthorizationReduce, AuthorizationRevoke):
        schema = model.model_json_schema()
        assert schema["additionalProperties"] is False
        assert schema["properties"]["expected_scopes"]["items"]["enum"] == list(registered)
        assert not {"actor", "subject", "subject_id", "force", "confirmed"} & schema["properties"].keys()
    receipt = env.invoke()
    assert AuthorizationReductionResponse.model_validate(receipt).model_dump(exclude_none=True) == receipt
    with pytest.raises(ValidationError):
        AuthorizationReductionResponse.model_validate({**receipt, "subject_capability": env.cap})


def test_missing_historical_proof_cannot_turn_reduced_state_into_valid_authority(env):
    env.upgrade()
    env.invoke(expected_scopes=sorted(SCOPES + ["rooms:read"]), expected_grant_revision=1)
    grant = env.persisted()
    grant["scopeUpgrades"] = {}
    env.store.write(env.store.path("subjects", env.subject), grant)
    with pytest.raises(ManagementError, match="AUTHORIZATION_STATE_INVALID"):
        env.service.authorization_status(env.subject, env.cap)
    assert env.persisted() == grant


def test_subject_size_limit_is_safe_without_losing_prior_native_state_or_receipts(env):
    grant = env.persisted()
    grant["opaque"] = "x" * (64 * 1024 - len(json.dumps(grant).encode()) - 120)
    env.store.write(env.store.path("subjects", env.subject), grant)
    with pytest.raises(ManagementError, match="AUTHORIZATION_UNAVAILABLE"):
        env.invoke()
    assert env.persisted() == grant


def test_http_native_operator_reduce_revoke_and_exact_receipt_recovery(env, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes import launcher_assistant_management as route
    monkeypatch.setattr(route, "_SERVICE", env.service)
    app = FastAPI()
    app.include_router(route.router)
    prefix = "/v1/launcher-assistant-management"
    headers = {CONTROL_TOKEN_HEADER: get_control_token(), route.SUBJECT_HEADER: env.subject, route.CAPABILITY_HEADER: env.cap}
    reduce_payload = {"request_id": "http-reduce", "expected_binding": BINDING, "parameters": {
        "expected_scopes": SCOPES, "expected_grant_revision": 0, "remove_scopes": ["agents:update"]}}
    with TestClient(app) as client:
        # No control authentication is never sufficient, even with capability.
        denied = client.post(prefix + "/actions/authorization_reduce", headers={route.SUBJECT_HEADER: env.subject,
            route.CAPABILITY_HEADER: env.cap}, json=reduce_payload)
        assert denied.status_code == 403
        reduced = client.post(prefix + "/actions/authorization_reduce", headers=headers, json=reduce_payload)
        assert reduced.status_code == 200, reduced.text
        assert reduced.json()["authorization"]["scopes"] == REMAINING
        revoked = client.post(prefix + "/actions/authorization_revoke", headers=headers, json={
            "request_id": "http-revoke", "expected_binding": BINDING, "parameters": {
                "expected_scopes": REMAINING, "expected_grant_revision": 1}})
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["authorization"]["scopes"] == []
        recovered = client.get(prefix + "/actions/authorization_revoke/requests/http-revoke", headers=headers)
        assert recovered.status_code == 200, recovered.text
        assert recovered.json() == {**revoked.json(), "reused": True}
        for path in ("/authorization", "/actions/authorization_reduce/requests/http-reduce",
                "/actions/authorization_revoke/requests/foreign-request"):
            result = client.get(prefix + path, headers=headers)
            assert result.status_code == 403, result.text
        rejected = client.post(prefix + "/actions/authorization_reduce", headers=headers, json=reduce_payload)
        assert rejected.status_code == 403 and rejected.json()["detail"]["code"] == "SUBJECT_REVOKED"
        assert env.cap not in recovered.text and "capabilityHash" not in recovered.text
