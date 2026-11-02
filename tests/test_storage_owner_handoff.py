"""Real temporary Windows filesystem tests for opt-in owner authority."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import vibelution_storage as storage
from config import paths as config_paths
from core.infrastructure import storage_owner_handoff as handoff

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows pinned owner authority")


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def owner(tmp_path, monkeypatch):
    root = tmp_path / "current"
    (root / ".vibelution").mkdir(parents=True)
    (root / ".git").mkdir()
    identity = root / storage.PROJECT_IDENTITY_RELATIVE_PATH
    identity.write_text('{"schemaVersion":1,"projectId":"owner-test"}', encoding="utf-8")
    config = tmp_path / "operator" / "config.toml"
    config.parent.mkdir()
    monkeypatch.setenv(config_paths.CONFIG_PATH_ENV, str(config))
    monkeypatch.delenv(config_paths.DATA_HOME_ENV, raising=False)
    monkeypatch.setenv(storage.PROJECTS_HOME_ENV, str(tmp_path / "projects"))
    target = storage.resolve_project_storage_paths(root)
    old_root = tmp_path / "old-checkout-no-longer-present"
    old_id = storage.instance_id_for_project(old_root)
    source = target.project_home / "instances" / old_id / "data"
    workspace = source / "workspace"
    workspace.mkdir(parents=True)
    config.write_text('[storage]\ndata_home = ' + json.dumps(str(source)) + '\n', encoding="utf-8")
    marker = source.parent / storage.STORAGE_MIGRATION_STATE_NAME
    marker.write_text(json.dumps({"schemaVersion": 1, "status": "completed", "projectId": target.project_id,
        "instanceId": old_id, "projectRoot": str(old_root), "targetRoot": str(source.parent)}), encoding="utf-8")
    secret = source / "do-not-read.db"
    secret.write_bytes(b"PRIVATE BODY AND SECRET MUST NOT APPEAR")
    return SimpleNamespace(root=root, identity=identity, config=config, target=target, source=source,
        workspace=workspace, marker=marker, old_root=old_root, tmp=tmp_path,
        proof=target.instance_home / handoff.RECORD_NAME)


def commit(owner, request="handoff-1", plan=None):
    plan = plan or handoff.plan_storage_owner_handoff(owner.root)
    return handoff.apply_storage_owner_handoff(owner.root, plan_digest=plan["planDigest"],
        confirm_relocated_data=True, request_id=request)


def test_plan_is_existing_only_and_does_not_certify_migration_coverage(owner):
    before = files(owner.tmp)
    plan = handoff.plan_storage_owner_handoff(owner.root)
    assert plan["status"] == "planned" and plan["dataWrites"] is False
    assert plan["binding"]["sourceDataRoot"] == str(owner.source)
    assert plan["binding"]["projectRoot"] == str(owner.root)
    assert plan["recordPath"] == str(owner.proof)
    assert "no recursive inventory" in plan["coverage"]
    assert "PRIVATE" not in json.dumps(plan) and files(owner.tmp) == before
    assert not owner.target.instance_home.exists()


@pytest.mark.parametrize("change", ["unconfirmed", "digest", "request", "source-change"])
def test_unapproved_or_stale_plan_never_creates_metadata(owner, change):
    plan = handoff.plan_storage_owner_handoff(owner.root)
    if change == "source-change":
        owner.marker.write_text(owner.marker.read_text(encoding="utf-8") + " ", encoding="utf-8")
    before = files(owner.tmp)
    with pytest.raises(ValueError):
        handoff.apply_storage_owner_handoff(owner.root, plan_digest="0" * 64 if change == "digest" else plan["planDigest"],
            confirm_relocated_data=change != "unconfirmed", request_id="../request" if change == "request" else "apply-1")
    assert files(owner.tmp) == before and not owner.target.instance_home.exists()


def test_commit_only_writes_current_metadata_and_does_not_change_native_resolution(owner):
    before = files(owner.tmp)
    native = storage.resolve_active_project_storage_paths(owner.root)
    result = commit(owner)
    assert result["outcome"] == "committed" and result["action"] == "apply"
    after = files(owner.tmp)
    assert all(after[key] == value for key, value in before.items())
    assert set(after) - set(before) == {str(owner.proof.relative_to(owner.tmp)), str(owner.proof.relative_to(owner.tmp)) + ".lock"}
    assert not storage.storage_migration_state_path(owner.target).exists()
    assert storage.resolve_active_project_storage_paths(owner.root) == native and not native.migrated
    with handoff.pinned_storage_owner_handoff(owner.root) as route:
        assert route == native and route.workspace == owner.workspace


def replace_config(path, text):
    """Model the native config transaction's atomic file replacement."""
    before = path.stat().st_ino
    pending = path.with_name("config-transaction-pending.toml")
    pending.write_text(text, encoding="utf-8")
    os.replace(pending, path)
    assert path.stat().st_ino != before


def other_owner_source(owner):
    old_root = owner.tmp / "different-former-checkout"
    old_id = storage.instance_id_for_project(old_root)
    source = owner.target.project_home / "instances" / old_id / "data"
    (source / "workspace").mkdir(parents=True)
    (source.parent / storage.STORAGE_MIGRATION_STATE_NAME).write_text(json.dumps({
        "schemaVersion": 1, "status": "completed", "projectId": owner.target.project_id,
        "instanceId": old_id, "projectRoot": str(old_root), "targetRoot": str(source.parent)}), encoding="utf-8")
    return source


def test_unrelated_config_and_new_workspace_files_do_not_invalidate_owner_or_plan(owner):
    plan = handoff.plan_storage_owner_handoff(owner.root)
    replace_config(owner.config, owner.config.read_text(encoding="utf-8") + '\n[llm]\nprovider="changed"\n[assistant]\ndispatch_allowlist=["new"]\n')
    (owner.workspace / "added-later.txt").write_text("new ordinary file", encoding="utf-8")
    assert handoff.plan_storage_owner_handoff(owner.root)["planDigest"] == plan["planDigest"]
    commit(owner, plan=plan)
    replace_config(owner.config, owner.config.read_text(encoding="utf-8").replace('"changed"', '"changed-again"'))
    with handoff.pinned_storage_owner_handoff(owner.root):
        pass


@pytest.mark.parametrize("initial_explicit", [False, True])
def test_equivalent_native_environment_route_keeps_same_binding(owner, monkeypatch, initial_explicit):
    if initial_explicit:
        monkeypatch.setenv(config_paths.DATA_HOME_ENV, str(owner.source))
    plan = handoff.plan_storage_owner_handoff(owner.root)
    commit(owner, plan=plan)
    if initial_explicit:
        monkeypatch.delenv(config_paths.DATA_HOME_ENV)
    else:
        monkeypatch.setenv(config_paths.DATA_HOME_ENV, str(owner.source).swapcase())
    with handoff.pinned_storage_owner_handoff(owner.root) as active:
        assert active.data == owner.source
    assert handoff.plan_storage_owner_handoff(owner.root)["planDigest"] == plan["planDigest"]


@pytest.mark.parametrize("representation", ["forward-slashes", "expanded-variable"])
def test_equivalent_config_representation_does_not_revoke_binding(owner, monkeypatch, representation):
    plan = handoff.plan_storage_owner_handoff(owner.root)
    commit(owner, plan=plan)
    if representation == "expanded-variable":
        monkeypatch.setenv("HANDOFF_TEST_DATA_ROUTE", str(owner.source))
        raw = "%HANDOFF_TEST_DATA_ROUTE%"
    else:
        raw = owner.source.as_posix()
    replace_config(owner.config, '[storage]\ndata_home=' + json.dumps(raw) + '\n')
    with handoff.pinned_storage_owner_handoff(owner.root):
        pass
    assert handoff.plan_storage_owner_handoff(owner.root)["planDigest"] == plan["planDigest"]


def test_equivalent_environment_change_inside_one_read_is_still_rejected(owner, monkeypatch):
    commit(owner)
    with pytest.raises(ValueError, match="native_route_changed"):
        with handoff.pinned_storage_owner_handoff(owner.root):
            monkeypatch.setenv(config_paths.DATA_HOME_ENV, str(owner.source))


def test_expanded_config_variable_change_inside_one_read_is_rejected(owner, monkeypatch):
    other = other_owner_source(owner)
    monkeypatch.setenv("HANDOFF_TEST_DATA_ROUTE", str(owner.source))
    replace_config(owner.config, '[storage]\ndata_home="%HANDOFF_TEST_DATA_ROUTE%"\n')
    commit(owner)
    with pytest.raises(ValueError, match="native_route_changed"):
        with handoff.pinned_storage_owner_handoff(owner.root):
            monkeypatch.setenv("HANDOFF_TEST_DATA_ROUTE", str(other))


def test_ack_lost_is_recovered_by_readonly_original_request_without_reexecution(owner, monkeypatch):
    plan = handoff.plan_storage_owner_handoff(owner.root)
    original = handoff.atomic_write_json
    calls = []
    def lost_ack(*args, **kwargs):
        calls.append(args[0])
        original(*args, **kwargs)
        raise OSError("simulated acknowledgement loss")
    monkeypatch.setattr(handoff, "atomic_write_json", lost_ack)
    with pytest.raises((OSError, ValueError)):
        commit(owner, plan=plan)
    before = files(owner.tmp)
    def forbidden(*args, **kwargs):
        pytest.fail("receipt or same-request recovery attempted a write")
    monkeypatch.setattr(handoff, "_writer", forbidden)
    recovered = handoff.read_storage_owner_handoff_receipt(owner.root, request_id="handoff-1")
    assert recovered == commit(owner, plan=plan) and len(calls) == 1
    assert recovered["planDigest"] == plan["planDigest"] and files(owner.tmp) == before
    with pytest.raises(ValueError):
        commit(owner, request="another-request", plan=plan)
    with pytest.raises(ValueError):
        commit(owner, plan={"planDigest": "0" * 64})


@pytest.mark.parametrize("field,value", [("schemaVersion", True), ("status", "pending"),
    ("projectId", "other-project"), ("instanceId", "00000000"), ("targetRoot", "D:/wrong"),
    ("projectRoot", "D:/another-checkout")])
def test_marker_owner_must_strictly_match_native_source(owner, field, value):
    marker = json.loads(owner.marker.read_bytes())
    marker[field] = value
    owner.marker.write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(ValueError):
        handoff.plan_storage_owner_handoff(owner.root)


@pytest.mark.parametrize("drift", ["source-marker", "data-route", "current-identity", "workspace", "data", "current-root", "canonical-marker", "revoked"])
def test_proof_rejects_authority_drift(owner, drift, monkeypatch):
    commit(owner)
    if drift == "source-marker":
        owner.marker.write_text(owner.marker.read_text(encoding="utf-8") + " ", encoding="utf-8")
    elif drift == "data-route":
        monkeypatch.setenv(config_paths.DATA_HOME_ENV, str(other_owner_source(owner)))
    elif drift == "current-identity":
        owner.identity.write_text('{"schemaVersion":1,"projectId":"other-test"}', encoding="utf-8")
    elif drift in {"workspace", "data", "current-root"}:
        path = {"workspace": owner.workspace, "data": owner.source, "current-root": owner.root}[drift]
        saved = path.with_name(path.name + "-saved")
        path.rename(saved)
        path.mkdir()
        if drift == "data":
            (path / "workspace").mkdir()
        elif drift == "current-root":
            (path / ".vibelution").mkdir()
            (path / ".git").mkdir()
            owner.identity.write_bytes((saved / storage.PROJECT_IDENTITY_RELATIVE_PATH).read_bytes())
    elif drift == "canonical-marker":
        storage.storage_migration_state_path(owner.target).write_text("{}", encoding="utf-8")
    else:
        digest = handoff.plan_storage_owner_handoff(owner.root)["recordDigest"]
        handoff.revoke_storage_owner_handoff(owner.root, record_digest=digest, request_id="revoke-1")
    with pytest.raises(ValueError):
        with handoff.pinned_storage_owner_handoff(owner.root):
            pytest.fail("invalid proof admitted")


@pytest.mark.parametrize("leaf", ["identity", "config", "marker", "proof"])
def test_hardlinked_authority_is_rejected(owner, leaf):
    if leaf == "proof":
        commit(owner)
    path = getattr(owner, leaf)
    os.link(path, path.with_name(path.name + ".alias"))
    with pytest.raises(ValueError):
        if leaf == "proof":
            with handoff.pinned_storage_owner_handoff(owner.root):
                pass
        else:
            handoff.plan_storage_owner_handoff(owner.root)


def test_junction_source_and_project_alias_are_rejected_before_resolve(owner):
    import subprocess
    alias = owner.tmp / "alias"
    result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(alias), str(owner.root)],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    if result.returncode:
        pytest.skip("temporary junction unavailable")
    try:
        with pytest.raises(ValueError):
            handoff.plan_storage_owner_handoff(alias)
    finally:
        alias.rmdir()


def test_revocation_retains_original_receipt_and_can_revoke_after_source_loss(owner, monkeypatch):
    applied = commit(owner)
    original = json.loads(owner.proof.read_bytes())
    owner.marker.unlink()
    digest = handoff.read_storage_owner_handoff_receipt(owner.root, request_id="handoff-1")["currentRecordDigest"]
    revoked = handoff.revoke_storage_owner_handoff(owner.root, record_digest=digest, request_id="revoke-1")
    record = json.loads(owner.proof.read_bytes())
    assert record["binding"] == original["binding"] and record["apply"] == original["apply"]
    assert record["status"] == "revoked" and record["revocation"]["recordDigest"] == digest
    before = files(owner.tmp)
    assert handoff.read_storage_owner_handoff_receipt(owner.root, request_id="revoke-1") == revoked
    receipt = handoff.read_storage_owner_handoff_receipt(owner.root, request_id="handoff-1")
    assert receipt["committedAt"] == applied["committedAt"] and receipt["currentProofStatus"] == "revoked"
    assert handoff.revoke_storage_owner_handoff(owner.root, record_digest=digest, request_id="revoke-1") == revoked
    assert files(owner.tmp) == before


def test_receipt_for_missing_record_never_creates_write_lock_or_directories(owner):
    before = files(owner.tmp)
    with pytest.raises(ValueError):
        handoff.read_storage_owner_handoff_receipt(owner.root, request_id="unknown")
    with pytest.raises(ValueError):
        handoff.revoke_storage_owner_handoff(owner.root, record_digest="0" * 64, request_id="unknown")
    assert files(owner.tmp) == before and not owner.target.instance_home.exists()


def test_plan_changed_while_waiting_for_writer_lock_never_publishes_proof(owner, monkeypatch):
    from contextlib import contextmanager
    plan = handoff.plan_storage_owner_handoff(owner.root)
    original = handoff._writer
    @contextmanager
    def delayed(path):
        with original(path):
            owner.marker.write_text(owner.marker.read_text(encoding="utf-8") + " ", encoding="utf-8")
            yield
    monkeypatch.setattr(handoff, "_writer", delayed)
    with pytest.raises(ValueError):
        commit(owner, plan=plan)
    assert not owner.proof.exists()


def test_concurrent_same_request_converges_to_one_atomic_commit(owner, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    plan = handoff.plan_storage_owner_handoff(owner.root)
    original = handoff.atomic_write_json
    calls = []
    def counted(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(handoff, "atomic_write_json", counted)
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: commit(owner, plan=plan), range(2)))
    assert outcomes[0] == outcomes[1] and calls == [owner.proof]


@pytest.mark.parametrize("leaf", ["data", "workspace", "config-parent", "metadata-parent"])
def test_reparse_routes_are_rejected_without_following_the_link(owner, leaf, monkeypatch):
    import subprocess
    path = {"data": owner.source, "workspace": owner.workspace,
            "config-parent": owner.config.parent, "metadata-parent": owner.target.instance_home}[leaf]
    saved = path.with_name(path.name + "-physical")
    if path.exists():
        path.rename(saved)
    else:
        saved.mkdir(parents=True)
    result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(path), str(saved)],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    if result.returncode:
        pytest.skip("temporary junction unavailable")
    try:
        with pytest.raises(ValueError):
            handoff.plan_storage_owner_handoff(owner.root)
        assert not (saved / handoff.RECORD_NAME).exists()
    finally:
        path.rmdir()


def test_source_outside_same_project_home_is_never_admitted(owner, monkeypatch):
    other_projects = owner.tmp / "other-projects"
    other = other_projects / "another-project" / "instances" / owner.source.parent.name / "data"
    (other / "workspace").mkdir(parents=True)
    owner.config.write_text('[storage]\ndata_home = ' + json.dumps(str(other)) + '\n', encoding="utf-8")
    with pytest.raises(ValueError, match="source_outside_project_instance"):
        handoff.plan_storage_owner_handoff(owner.root)


def test_metadata_sidecar_hardlink_cannot_be_used_as_a_write_lock(owner):
    plan = handoff.plan_storage_owner_handoff(owner.root)
    owner.target.instance_home.mkdir()
    lock = owner.proof.with_name(owner.proof.name + ".lock")
    lock.write_bytes(b"PRIVATE LOCK TARGET")
    alias = lock.with_name("lock-hardlink")
    os.link(lock, alias)
    before = files(owner.tmp)
    with pytest.raises(ValueError):
        commit(owner, plan=plan)
    assert files(owner.tmp) == before and not owner.proof.exists()


def test_instance_id_collision_cannot_borrow_another_physical_roots_proof(owner, monkeypatch):
    commit(owner)
    other = owner.tmp / "colliding-root"
    (other / ".vibelution").mkdir(parents=True)
    (other / ".git").mkdir()
    (other / storage.PROJECT_IDENTITY_RELATIVE_PATH).write_bytes(owner.identity.read_bytes())
    native = storage.instance_id_for_project
    monkeypatch.setattr(storage, "instance_id_for_project", lambda root: owner.target.instance_id if root == other else native(root))
    assert storage.resolve_project_storage_paths(other).instance_home == owner.target.instance_home
    with pytest.raises(ValueError, match="handoff_binding_invalid"):
        with handoff.pinned_storage_owner_handoff(other):
            pass
    with pytest.raises(ValueError, match="record_owner_mismatch"):
        handoff.read_storage_owner_handoff_receipt(other, request_id="handoff-1")


def test_failed_revocation_cas_and_request_collision_preserve_proof(owner):
    applied = commit(owner)
    before = files(owner.tmp)
    for digest, request in [("0" * 64, "revocation"), (applied["currentRecordDigest"], "handoff-1")]:
        with pytest.raises(ValueError):
            handoff.revoke_storage_owner_handoff(owner.root, record_digest=digest, request_id=request)
    assert files(owner.tmp) == before


def test_record_readonly_queries_reject_mutated_native_receipt(owner):
    commit(owner)
    data = json.loads(owner.proof.read_bytes())
    data["apply"]["planDigest"] = "0" * 64
    owner.proof.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid_handoff_plan_receipt"):
        handoff.read_storage_owner_handoff_receipt(owner.root, request_id="handoff-1")


def test_active_read_pins_file_authorities_and_rechecks_current_marker(owner):
    commit(owner)
    with pytest.raises(ValueError, match="canonical_migration_marker_present"):
        with handoff.pinned_storage_owner_handoff(owner.root):
            for path in (owner.identity, owner.config, owner.marker, owner.proof):
                with pytest.raises(PermissionError):
                    path.write_bytes(b"mutate")
            storage.storage_migration_state_path(owner.target).write_text("{}", encoding="utf-8")


def test_same_global_config_other_root_cannot_borrow_owner_proof(owner):
    commit(owner)
    other = owner.tmp / "different-current"
    (other / ".vibelution").mkdir(parents=True)
    (other / ".git").mkdir()
    (other / storage.PROJECT_IDENTITY_RELATIVE_PATH).write_bytes(owner.identity.read_bytes())
    with pytest.raises(ValueError):
        with handoff.pinned_storage_owner_handoff(other):
            pass


def test_cli_plan_receipt_are_readonly_and_no_arbitrary_source_argument(owner, capsys):
    from scripts.project_storage_owner import main
    before = files(owner.tmp)
    assert main(["plan", "--project-root", str(owner.root)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "planned" and files(owner.tmp) == before
    assert main(["receipt", "--project-root", str(owner.root), "--request-id", "unknown"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False and files(owner.tmp) == before
    with pytest.raises(SystemExit):
        main(["plan", "--project-root", str(owner.root), "--data-home", str(owner.source)])


def test_cli_never_prints_malformed_config_values(owner, capsys):
    from scripts.project_storage_owner import main
    owner.config.write_text('[storage]\ndata_home = "PRIVATE INVALID CONFIG SECRET', encoding="utf-8")
    assert main(["plan", "--project-root", str(owner.root)]) == 2
    output = capsys.readouterr().out
    assert "PRIVATE" not in output and json.loads(output)["error"] == "owner_authority_unavailable"
