"""Explicit operator upgrades retain their principal and never replay unknown writes."""
from copy import deepcopy
import secrets

import pytest

from core.web.services.external_management.authorization_upgrade import UpgradeOwner
from core.web.services.external_management.service import ManagementError, ManagementService, TargetIdentity
from core.web.services.external_management.store import Store, digest


OLD = sorted(["agents:avatar", "agents:create", "agents:read", "agents:update", "platform:describe",
              "sessions:read", "teams:read", "teams:run"])
READS = sorted(["teams:directory:read", "rooms:read", "sessions:parameters:read"])
BINDING = {"projectId": "project", "instanceId": "instance"}


class Harness:
    def __init__(self, root, scopes=OLD):
        self.store = Store(root)
        self.identity = TargetIdentity(deepcopy(BINDING), "authority")
        service = ManagementService(root, identity=lambda: self.identity, native=object())
        self.grant = service.bind({"client_id": "original-client", "expected_binding": BINDING, "scopes": scopes})
        self.subject, self.cap = self.grant["subject_id"], self.grant["subject_capability"]
        self.owner = self.restarted()

    def authorize(self, subject, capability, expected_binding=None):
        grant = self.store.read(self.store.path("subjects", subject))
        if not grant or not secrets.compare_digest(grant["subject_capability"], capability):
            raise ManagementError("SUBJECT_DENIED")
        if (grant["binding"] != self.identity.binding or grant["authority"] != self.identity.signature
            or expected_binding is not None and expected_binding != self.identity.binding):
            raise ManagementError("TARGET_BINDING_CHANGED", 409)
        return grant

    def restarted(self):
        return UpgradeOwner(self.store, self.authorize, lambda: self.identity)

    def invoke(self, **values):
        return self.owner.invoke(**{"subject": self.subject, "capability": self.cap, "request_id": "upgrade-1",
            "expected_binding": deepcopy(BINDING), "expected_scopes": OLD, "add_scopes": READS, **values})

    def persisted(self):
        return self.store.read(self.store.path("subjects", self.subject))


@pytest.fixture
def env(tmp_path):
    return Harness(tmp_path / "management")


@pytest.mark.parametrize("extra", [[], ["sessions:pin"], ["agents:archive", "sessions:pin"]])
def test_old_eight_nine_ten_only_receive_explicit_three_read_scopes(tmp_path, extra):
    env = Harness(tmp_path / "management", sorted(OLD + extra))
    old = deepcopy(env.persisted())
    old["opaqueTaskState"] = {"nativeTaskId": "unchanged", "nested": [False, 1, {"value": "opaque"}]}
    env.store.write(env.store.path("subjects", env.subject), old)
    clients_before = {path.name: path.read_bytes() for path in (env.store.root / "clients").glob("*.json")}
    result = env.invoke(expected_scopes=sorted(OLD + extra))
    authorization = result["authorization"]
    assert result == {"action": "authorization_upgrade", "requestId": "upgrade-1", "status": "completed",
                      "verified": True, "reused": False, "authorization": authorization}
    assert authorization == {"subjectId": env.subject, "previousScopes": sorted(OLD + extra), "addedScopes": READS,
                             "scopes": sorted(OLD + extra + READS), "grantRevision": 1}
    after = env.persisted()
    assert {key: value for key, value in after.items() if key not in {"scopes", "scopeUpgrades", "grantRevision"}} == {
        key: value for key, value in old.items() if key != "scopes"}
    assert after["subject_capability"] == env.cap and len(after["scopeUpgrades"]) == 1
    assert {path.name: path.read_bytes() for path in (env.store.root / "clients").glob("*.json")} == clients_before
    assert env.cap not in str(result) and "original-client" not in str(result)
    assert env.owner.current_subject(env.subject, env.cap) == {
        "subjectId": env.subject, "binding": BINDING, "scopes": after["scopes"], "grantRevision": 1}


@pytest.mark.parametrize("parameters", [
    {"add_scopes": None}, {"add_scopes": []}, {"add_scopes": [True]}, {"add_scopes": "rooms:read"},
    {"add_scopes": ["rooms:read", "rooms:read"]}, {"add_scopes": ["teams:directory:read", "rooms:read"]},
    {"add_scopes": ["unknown:scope"]}, {"add_scopes": ["agents:read"]},
    {"expected_scopes": []}, {"expected_scopes": OLD + [OLD[-1]]}, {"expected_scopes": list(reversed(OLD))},
    {"expected_scopes": [False]}, {"expected_binding": {**BINDING, "secret": "forbidden"}},
    {"request_id": True}, {"request_id": "bad/id"}, {"force": True}, {"revoke_scopes": ["agents:read"]},
])
def test_invalid_or_implicit_additions_are_rejected_before_intent(env, parameters):
    before = env.persisted()
    with pytest.raises(ManagementError) as rejected:
        env.invoke(**parameters)
    assert rejected.value.code == "INVALID_INPUT" and rejected.value.status_code == 422
    assert env.persisted() == before and not (env.store.root / "requests").exists()


def test_stale_expected_scopes_and_same_id_different_parameters_are_conflicts(env):
    with pytest.raises(ManagementError, match="AUTHORIZATION_CONFLICT"):
        env.invoke(expected_scopes=sorted(OLD + ["sessions:pin"]))
    first = env.invoke()
    with pytest.raises(ManagementError, match="IDEMPOTENCY_CONFLICT"):
        env.invoke(add_scopes=["rooms:read"])
    assert env.invoke() == {**first, "reused": True}
    assert env.owner.receipt(env.subject, env.cap, "upgrade-1") == {**first, "reused": True}


@pytest.mark.parametrize("change", ["capability", "subject", "binding", "authority"])
def test_wrong_principal_or_changed_target_cannot_read_or_upgrade(env, change):
    values = {}
    if change == "capability": values["capability"] = "x" * 48
    elif change == "subject": values["subject"] = "ops-" + "0" * 32
    elif change == "binding": env.identity = TargetIdentity({**BINDING, "instanceId": "new"}, "authority")
    else: env.identity = TargetIdentity(BINDING, "changed")
    before = env.persisted()
    with pytest.raises(ManagementError) as denied:
        env.invoke(**values)
    assert denied.value.code in {"SUBJECT_DENIED", "TARGET_BINDING_CHANGED"}
    assert env.persisted() == before


@pytest.mark.parametrize("failure", ["before-grant", "after-grant", "before-receipt", "after-receipt"])
def test_lost_ack_restart_only_reads_proof_never_replays_subject_write(env, monkeypatch, failure):
    original, writes = env.store.write, []
    def failing(path, value):
        if path.parent.name == "subjects":
            writes.append("subject")
            assert env.store.read(env.store.path("requests", digest([env.subject, "authorization_upgrade", "upgrade-1"])))
            if failure == "before-grant": raise OSError("secret filesystem detail")
            original(path, value)
            if failure == "after-grant": raise OSError("secret filesystem detail")
            return
        if value.get("receipt"):
            if failure == "before-receipt": raise OSError("secret filesystem detail")
            original(path, value)
            if failure == "after-receipt": raise OSError("secret filesystem detail")
            return
        original(path, value)
    monkeypatch.setattr(env.store, "write", failing)
    unknown = env.invoke()
    assert unknown["status"] == "unknown" and unknown["verified"] is False and "secret" not in str(unknown)
    monkeypatch.setattr(env.store, "write", original)
    env.owner = env.restarted()
    for result in (env.invoke(), env.owner.receipt(env.subject, env.cap, "upgrade-1")):
        assert result["status"] == ("unknown" if failure == "before-grant" else "completed")
        assert result["reused"] is True
    assert writes == ["subject"]


def test_later_upgrade_keeps_original_immutable_proof_and_historical_receipt(env):
    first = env.invoke()
    second = env.invoke(request_id="upgrade-2", expected_scopes=sorted(OLD + READS), add_scopes=["sessions:pin"])
    assert second["authorization"]["grantRevision"] == 2
    assert env.restarted().receipt(env.subject, env.cap, "upgrade-1") == {**first, "reused": True}
    current = env.owner.current_subject(env.subject, env.cap)
    assert current["grantRevision"] == 2 and "sessions:pin" in current["scopes"]
    assert "sessions:pin" not in first["authorization"]["scopes"] and len(env.persisted()["scopeUpgrades"]) == 2


def test_capacity_refuses_without_deleting_prior_upgrade_proofs(env):
    env.invoke(add_scopes=["rooms:read"])
    grant = env.persisted()
    proof = next(iter(grant["scopeUpgrades"].values()))
    grant["scopeUpgrades"] = {}
    for index in range(32):
        entry = deepcopy(proof)
        entry["requestId"] = f"history-{index}"
        entry["authorization"]["grantRevision"] = index + 1
        grant["scopeUpgrades"][digest([env.subject, "authorization_upgrade", entry["requestId"]])] = entry
    grant["grantRevision"] = 32
    env.store.write(env.store.path("subjects", env.subject), grant)
    with pytest.raises(ManagementError, match="AUTHORIZATION_UPGRADE_LIMIT"):
        env.invoke(request_id="next-upgrade", expected_scopes=sorted(OLD + ["rooms:read"]), add_scopes=["sessions:pin"])
    assert env.persisted() == grant


def test_subject_cas_serializes_competing_requests(env):
    from concurrent.futures import ThreadPoolExecutor
    def upgrade(value):
        try:
            return env.invoke(request_id=value.replace(":", "-"), add_scopes=[value])["status"]
        except ManagementError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(upgrade, ["rooms:read", "sessions:pin"]))
    assert sorted(outcomes) == ["AUTHORIZATION_CONFLICT", "completed"]
    assert env.persisted()["grantRevision"] == 1 and len(env.persisted()["scopeUpgrades"]) == 1


def test_unreadable_or_invalid_state_returns_fixed_codes_and_preserves_source(env):
    path = env.store.path("subjects", env.subject)
    grant = env.persisted()
    grant["grantRevision"] = True
    env.store.write(path, grant)
    before = path.read_bytes()
    with pytest.raises(ManagementError, match="AUTHORIZATION_STATE_INVALID"):
        env.invoke()
    assert path.read_bytes() == before
    grant.pop("grantRevision")
    env.store.write(path, grant)
    with pytest.raises(ManagementError, match="REQUEST_UNAVAILABLE"):
        env.owner.receipt(env.subject, env.cap, "unknown-request")


@pytest.mark.parametrize("persisted", [False, True])
def test_failed_intent_write_never_changes_subject_or_runs_upgrade(env, monkeypatch, persisted):
    before, write = env.persisted(), env.store.write
    def fail(path, value):
        assert path.parent.name == "requests"
        if persisted:
            write(path, value)
        raise OSError("private path SECRET")
    monkeypatch.setattr(env.store, "write", fail)
    if persisted:
        assert env.invoke()["status"] == "unknown"
    else:
        with pytest.raises(ManagementError, match="AUTHORIZATION_UNAVAILABLE"):
            env.invoke()
    assert env.persisted() == before
    monkeypatch.setattr(env.store, "write", write)
    if persisted:
        assert env.invoke()["status"] == "unknown" and env.persisted() == before


def test_lost_grant_ack_then_later_upgrade_still_recovers_original_history(env, monkeypatch):
    write = env.store.write
    def lost(path, value):
        write(path, value)
        if path.parent.name == "subjects":
            raise TimeoutError("lost ACK")
    monkeypatch.setattr(env.store, "write", lost)
    assert env.invoke()["status"] == "unknown"
    monkeypatch.setattr(env.store, "write", write)
    env.owner = env.restarted()
    second = env.invoke(request_id="upgrade-2", expected_scopes=sorted(OLD + READS), add_scopes=["agents:archive"])
    historical = env.owner.receipt(env.subject, env.cap, "upgrade-1")
    assert second["authorization"]["grantRevision"] == 2 and historical["authorization"]["grantRevision"] == 1
    assert historical["authorization"]["scopes"] == sorted(OLD + READS)
    assert "agents:archive" not in historical["authorization"]["scopes"]


def test_subject_mutation_requires_readback_proof_not_only_successful_write_call(env, monkeypatch):
    before, write = env.persisted(), env.store.write
    def missing(path, value):
        if path.parent.name != "subjects":
            write(path, value)
    monkeypatch.setattr(env.store, "write", missing)
    assert env.invoke()["status"] == "unknown" and env.persisted() == before
    monkeypatch.setattr(env.store, "write", write)
    assert env.invoke()["status"] == "unknown" and env.persisted() == before


@pytest.mark.parametrize("fault", ["missing-proof", "wrong-fingerprint", "wrong-revision", "extra-secret", "bad-receipt"])
def test_corrupted_history_never_authorizes_or_fabricates_a_receipt(env, fault):
    env.invoke()
    key = digest([env.subject, "authorization_upgrade", "upgrade-1"])
    grant, intent = env.persisted(), env.store.read(env.store.path("requests", key))
    if fault == "missing-proof": grant["scopeUpgrades"] = {}
    elif fault == "wrong-fingerprint": grant["scopeUpgrades"][key]["fingerprint"] = "0" * 64
    elif fault == "wrong-revision": grant["scopeUpgrades"][key]["authorization"]["grantRevision"] = True
    elif fault == "extra-secret": grant["scopeUpgrades"][key]["authorization"]["capability"] = "SECRET"
    else:
        intent["receipt"]["authorization"]["scopes"] = OLD
        env.store.write(env.store.path("requests", key), intent)
    env.store.write(env.store.path("subjects", env.subject), grant)
    before = env.persisted()
    with pytest.raises(ManagementError, match="AUTHORIZATION_STATE_INVALID"):
        env.owner.receipt(env.subject, env.cap, "upgrade-1")
    assert env.persisted() == before


def test_identity_is_checked_again_after_subject_lock_before_mutation(env, monkeypatch):
    authorize, calls = env.authorize, []
    def changed(subject, capability, expected_binding=None):
        calls.append(1)
        if len(calls) == 2:
            env.identity = TargetIdentity(BINDING, "changed-authority")
        return authorize(subject, capability, expected_binding)
    env.owner = UpgradeOwner(env.store, changed, lambda: env.identity)
    before = env.persisted()
    with pytest.raises(ManagementError, match="TARGET_BINDING_CHANGED"):
        env.invoke()
    assert len(calls) == 2 and env.persisted() == before


def test_same_result_scopes_from_other_request_do_not_prove_unknown_upgrade(env, monkeypatch):
    write = env.store.write
    def fail(path, value):
        if path.parent.name == "subjects":
            raise OSError("did not persist")
        write(path, value)
    monkeypatch.setattr(env.store, "write", fail)
    assert env.invoke()["status"] == "unknown"
    monkeypatch.setattr(env.store, "write", write)
    assert env.invoke(request_id="explicit-second-request")["status"] == "completed"
    assert env.owner.receipt(env.subject, env.cap, "upgrade-1")["status"] == "unknown"
    assert len(env.persisted()["scopeUpgrades"]) == 1


def test_record_size_limit_keeps_unknown_intent_without_replaying_or_dropping_opaque_state(env):
    import json
    grant = env.persisted()
    grant["opaque"] = "x" * (64 * 1024 - len(json.dumps(grant).encode()) - 120)
    env.store.write(env.store.path("subjects", env.subject), grant)
    assert env.invoke()["status"] == "unknown"
    assert env.invoke()["status"] == "unknown" and env.persisted() == grant


def test_callback_errors_are_bounded_and_public_reads_never_expose_credentials(env):
    def fail(*_args):
        raise ManagementError("SECRET_PATH_AND_CAPABILITY")
    owner = UpgradeOwner(env.store, fail, lambda: env.identity)
    with pytest.raises(ManagementError) as denied:
        owner.current_subject(env.subject, env.cap)
    assert denied.value.code == "AUTHORIZATION_UNAVAILABLE" and "SECRET" not in str(denied.value)
    current = env.owner.current_subject(env.subject, env.cap)
    assert current == {"subjectId": env.subject, "binding": BINDING, "scopes": OLD, "grantRevision": 0}
    assert "capability" not in str(current) and env.cap not in str(current)


def test_all_operations_reject_foreign_subject_or_capability_before_history_lookup(env, tmp_path):
    other = Harness(tmp_path / "other")
    env.invoke()
    for subject, capability in ((env.subject, other.cap), (other.subject, env.cap)):
        for operation in (lambda: env.owner.receipt(subject, capability, "upgrade-1"),
                          lambda: env.owner.current_subject(subject, capability)):
            with pytest.raises(ManagementError, match="SUBJECT_DENIED"):
                operation()


def _process_upgrade(root, subject, capability, scope, output):
    store = Store(root)
    identity = TargetIdentity(BINDING, "authority")
    def authorize(actor, secret, expected=None):
        row = store.read(store.path("subjects", actor))
        if not row or not secrets.compare_digest(row["subject_capability"], secret):
            raise ManagementError("SUBJECT_DENIED")
        return row
    owner = UpgradeOwner(store, authorize, lambda: identity)
    try:
        result = owner.invoke(subject, capability, scope.replace(":", "-"), BINDING, OLD, [scope])["status"]
    except ManagementError as exc:
        result = exc.code
    output.put(result)


def test_independent_processes_share_subject_cas_lock(env):
    import multiprocessing
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    processes = [context.Process(target=_process_upgrade, args=(env.store.root, env.subject, env.cap, scope, output))
                 for scope in ("rooms:read", "sessions:pin")]
    try:
        for process in processes:
            process.start()
        outcomes = [output.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        assert sorted(outcomes) == ["AUTHORIZATION_CONFLICT", "completed"]
        assert env.persisted()["grantRevision"] == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        output.close()
