"""Real configuration mutations under all-registration/native reference proofs."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import tomllib

import pytest

from core.assistant_runtime import configuration_contexts as contexts
from core.assistant_runtime import configuration_control as control
from core.infrastructure.model_reference_fence import model_reference_fence_owned
from tests.test_assistant_global_model_references import bind_store, env as reference_env, write_json


RUNTIME = {"agentId": "native-assistant", "sessionId": "native-session", "turnId": "native-turn"}
CASES = [
    pytest.param("model_remove", {"model_id": "alpha/spare"}, "model", "alpha/spare", id="model-remove"),
    pytest.param("model_update", {"model_id": "alpha/spare", "updates": {"enabled": False}}, "model", "alpha/spare", id="model-disable"),
    pytest.param("provider_update", {"provider_id": "alpha", "enabled": False}, "provider", "alpha", id="provider-disable"),
]


def files(root):
    """Compare bounded fixture metadata, without displaying config/Journal bodies."""
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


@pytest.fixture
def env(reference_env, monkeypatch):
    fixture = reference_env
    fixture.leases, fixture.sent = [], []
    fixture.expire_on_validate = None
    monkeypatch.setattr(contexts, "_CONTEXTS", {})
    monkeypatch.setattr("core.infrastructure.native_runtime.assistant_native_root", lambda: fixture.native.resolve())
    broker = object()

    def inventory():
        snapshot = fixture.provider()
        return {"schemaVersion": 1, "leaseId": "fixture-private-registry-lease", "revision": snapshot["revision"],
                "snapshotDigest": snapshot["authorityDigest"], "complete": snapshot["complete"],
                "projects": [{"registrationId": row["projectId"], "baseProjectId": "fixture-project",
                              "root": row["root"], "active": row["active"]} for row in snapshot["projects"]],
                "nativeAssistantRoot": snapshot["nativeAssistantRoot"]}

    def lease(runtime):
        assert runtime == RUNTIME
        native = control.NativeRegistryLease(broker, None, runtime)
        fixture.leases.append(native)
        validations = 0

        def send(action):
            nonlocal validations
            fixture.sent.append(action)
            assert not contexts.state(broker, native.context_id)["workComplete"]
            if action == "configuration_reference_acquire":
                return inventory()
            if action == "configuration_reference_validate":
                validations += 1
                if validations == fixture.expire_on_validate:
                    registry = json.loads(fixture.registry.read_text(encoding="utf-8"))
                    registry["revision"] += 1
                    write_json(fixture.registry, registry)
                current = inventory()
                return {"valid": current == native.inventory, "revision": current["revision"]}
            assert action == "configuration_reference_release"
            assert not model_reference_fence_owned()
            return {"released": True}

        # Only the private Electron bridge is replaced. Lease lifecycle,
        # reference guard, native config action, and transaction remain real.
        monkeypatch.setattr(native, "_send", send)
        return native

    monkeypatch.setattr(control, "_lease", lease)
    fixture.broker = broker
    return fixture


def assert_released(env):
    assert env.leases and all(lease.closed for lease in env.leases)
    assert env.sent.count("configuration_reference_acquire") == len(env.leases)
    assert env.sent.count("configuration_reference_release") == len(env.leases)
    assert not model_reference_fence_owned()
    for lease in env.leases:
        assert contexts.state(env.broker, lease.context_id) == {
            "schemaVersion": 1, "contextId": lease.context_id, "known": True, "workComplete": True}


def config(env):
    return tomllib.loads(env.config.read_text(encoding="utf-8"))


def assert_no_configuration_write(env, before):
    after = files(env.config.parent)
    assert {key: after.get(key) for key in before} == before
    # The shared cross-process fence may initialize its stable one-byte lock
    # file. It must not create config backups, retirement proofs, or repairs.
    assert set(after) - set(before) <= {env.config.name + ".model-references.lock"}


@pytest.mark.parametrize("action,parameters,kind,reference", CASES)
def test_zero_reference_inspect_then_real_native_disable_or_remove(env, action, parameters, kind, reference):
    from config.public_config import public_config_hash, read_existing_config_snapshot

    initial = files(env.config.parent)
    proof = control.inspect({"kind": kind, "reference": reference}, RUNTIME)
    assert proof["ok"] and proof["status"] == "observed"
    assert proof["coverage"] == "complete" and proof["liveReferenceCount"] == 0
    assert proof["projectCount"] == 3 and proof["blocking"] is False
    assert files(env.config.parent) == initial
    before = config(env)
    expected = deepcopy(before)
    if action == "model_remove":
        del expected["llm"]["providers"]["alpha"]["models"]["spare"]
    elif action == "model_update":
        expected["llm"]["providers"]["alpha"]["models"]["spare"]["enabled"] = False
    else:
        expected["llm"]["providers"]["alpha"]["enabled"] = False

    result = control.mutate(action, parameters, RUNTIME, governed=True)

    assert result["ok"] and result["status"] == "applied" and result["verified"] is True
    assert result["resultHash"] == public_config_hash(expected)
    assert config(env) == expected
    assert public_config_hash(read_existing_config_snapshot(env.config)) == result["resultHash"]
    assert before != expected
    assert_released(env)


def test_zero_reference_empty_provider_real_native_remove(env):
    from config.operator_config_transaction import remove_toml_table_tree
    from config.public_config import public_config_hash

    # A provider must be empty before the existing native owner permits removal.
    env.config.write_text(remove_toml_table_tree(env.config.read_text(encoding="utf-8"),
        ("llm", "providers", "beta", "models", "spare")), encoding="utf-8")
    expected = config(env)
    del expected["llm"]["providers"]["beta"]
    proof = control.inspect({"kind": "provider", "reference": "beta"}, RUNTIME)
    assert proof["coverage"] == "complete" and proof["liveReferenceCount"] == 0
    result = control.mutate("provider_remove", {"provider_id": "beta"}, RUNTIME, governed=True)
    assert result["ok"] and result["verified"] is True
    assert config(env) == expected and result["resultHash"] == public_config_hash(expected)
    assert_released(env)


@pytest.mark.parametrize("action,parameters,kind,reference", CASES)
@pytest.mark.parametrize("owner", ["inactive-registration", "native-assistant", "old-session-pin"])
def test_other_registration_native_and_pinned_session_references_prevent_writes(env, action, parameters, kind, reference, owner):
    if owner == "native-assistant":
        path, session_model = env.native_workspace / "chat" / "conversations.sqlite3", None
    else:
        path = env.paths[1].workspace / "chat" / "conversations.sqlite3"
        session_model = "alpha/spare" if owner == "old-session-pin" else None
    bind_store(path, "gamma/default" if session_model else "alpha/spare", session_model=session_model)
    initial = files(env.config.parent)
    proof = control.inspect({"kind": kind, "reference": reference}, RUNTIME)
    assert proof["coverage"] == "complete" and proof["liveReferenceCount"] == 1 and proof["blocking"]
    result = control.mutate(action, parameters, RUNTIME, governed=True)
    assert result["ok"] is False and result["error"] == "LIVE_MODEL_REFERENCES"
    assert result["referenceCheck"]["liveReferenceCount"] == 1
    assert_no_configuration_write(env, initial)
    assert "PRIVATE PROMPT" not in json.dumps([proof, result])
    assert_released(env)


@pytest.mark.parametrize("failure", ["missing-db", "corrupt-db", "offline-registration", "missing-native-db", "incomplete-inventory"])
def test_unavailable_reference_coverage_cannot_authorize_native_mutation(env, failure, monkeypatch):
    if failure == "missing-db":
        (env.paths[1].workspace / "chat" / "conversations.sqlite3").unlink()
    elif failure == "corrupt-db":
        (env.paths[1].workspace / "chat" / "conversations.sqlite3").write_bytes(b"broken fixture authority")
    elif failure == "offline-registration":
        registry = json.loads(env.registry.read_text(encoding="utf-8"))
        registry["registrations"][1]["root"] = str(env.roots[1] / "offline")
        write_json(env.registry, registry)
    elif failure == "missing-native-db":
        (env.native_workspace / "chat" / "conversations.sqlite3").unlink()
    else:
        provider = env.provider
        # The private bridge may report incomplete coverage; do not turn it
        # into an empty/zero-reference inventory or proceed to the writer.
        monkeypatch.setattr(env, "provider", lambda: {**provider(), "complete": False})
    initial = files(env.config.parent)
    proof = control.inspect({"kind": "model", "reference": "alpha/spare"}, RUNTIME)
    if failure == "incomplete-inventory":
        assert proof["ok"] is False and proof["status"] == "unavailable"
    else:
        assert proof["coverage"] == "unavailable" and proof["liveReferenceCount"] is None
        assert proof["blocking"] is True
    result = control.mutate("model_remove", {"model_id": "alpha/spare"}, RUNTIME, governed=True)
    assert result["ok"] is False
    assert result["error"] == ("REFERENCE_REGISTRY_LEASE_UNAVAILABLE" if failure == "incomplete-inventory"
                               else "REFERENCE_COVERAGE_UNAVAILABLE")
    assert_no_configuration_write(env, initial)
    if failure == "incomplete-inventory":
        assert env.sent.count("configuration_reference_release") == 0
        assert all(contexts.state(env.broker, lease.context_id)["workComplete"] for lease in env.leases)
    else:
        assert_released(env)


@pytest.mark.parametrize("validate_number", [1, 2, 3])
def test_registry_revision_expiring_before_native_mutation_is_rejected(env, validate_number):
    env.expire_on_validate = validate_number
    before = env.config.read_bytes(), env.config.stat().st_mtime_ns
    result = control.mutate("model_remove", {"model_id": "alpha/spare"}, RUNTIME, governed=True)
    assert result["ok"] is False and result["error"] == "REFERENCE_REGISTRY_LEASE_UNAVAILABLE"
    assert (env.config.read_bytes(), env.config.stat().st_mtime_ns) == before
    assert not (env.config.parent / ".model-reference-retirements").exists()
    assert json.loads(env.registry.read_text(encoding="utf-8"))["revision"] == 4
    assert_released(env)


def test_real_native_transaction_reload_exception_releases_lease_and_fence(env, monkeypatch):
    from config import operator_config_transaction as transaction
    before = env.config.read_bytes()
    observed = []

    def reload(path):
        assert str(env.config) == path
        observed.append("spare" in config(env)["llm"]["providers"]["alpha"]["models"])
        assert model_reference_fence_owned()
        if len(observed) == 1:
            raise OSError("fixture reload failure after real native write")

    monkeypatch.setattr(transaction, "reload_config", reload)
    result = control.mutate("model_remove", {"model_id": "alpha/spare"}, RUNTIME, governed=True)
    assert result["ok"] is False and result["status"] == "unknown"
    assert result["error"] == "config_operation_failed"
    assert observed == [False, True]  # The real transaction wrote and rolled back.
    assert env.config.read_bytes() == before
    assert_released(env)


@pytest.mark.parametrize("governed", [False, None, 1, "true"])
def test_missing_native_governance_cannot_acquire_lease_or_write(env, governed):
    before = files(env.config.parent)
    result = control.mutate("model_remove", {"model_id": "alpha/spare"}, RUNTIME, governed=governed)
    assert result["ok"] is False and result["status"] == "approval_required"
    assert env.leases == [] and env.sent == []
    assert files(env.config.parent) == before
