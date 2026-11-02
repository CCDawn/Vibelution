"""Opt-in native proof belongs to the original final config manifest only."""
import json
import tomllib

import pytest

from config import operator_config_transaction as transaction
from config.public_config import public_config_hash
from tests.test_operator_config_transaction import _write_config


def request(tmp_path, **changes):
    return {"projectRoot": str(tmp_path), "subjectType": "operator", "subjectId": "ops-" + "a" * 32,
        "action": "agent_dispatch_access_set", "requestKey": "b" * 64, "requestFingerprint": "c" * 64,
        "agentId": "agent-a", "enabled": True, **changes}


def prepare(path, binding=None):
    return transaction.prepare_operator_config_transaction(operation_kind="agent_dispatch_access_set",
        expected_base_hash=public_config_hash(tomllib.loads(path.read_text(encoding="utf-8"))),
        mutate_text=lambda text: transaction.append_toml_table(text, ("external_agent_gateway",),
            {"enabled": True, "allowed_agent_ids": ["agent-a"], "denied_agent_ids": []}),
        config_path=path, native_request=binding)


def test_default_transaction_keeps_schema1_and_native_proof_is_opt_in(tmp_path, monkeypatch):
    path, _before = _write_config(tmp_path)
    monkeypatch.setattr(transaction, "reload_config", lambda _path: None)
    prepared = prepare(path)
    transaction.apply_operator_config_transaction(prepared)
    record = json.loads(prepared.manifest_path.read_text())
    assert record["schemaVersion"] == 1 and "nativeRequest" not in record
    assert transaction.read_native_config_outcome(path, request(tmp_path)) is None


def test_completed_manifest_remains_original_proof_after_later_config_change(tmp_path, monkeypatch):
    path, _before = _write_config(tmp_path)
    binding = request(tmp_path)
    monkeypatch.setattr(transaction, "reload_config", lambda _path: None)
    prepared = prepare(path, binding)
    transaction.apply_operator_config_transaction(prepared)
    path.write_text(path.read_text() + '\n[unrelated]\nname="later edit"\n')
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.parent.rglob("*") if p.is_file()}
    proof = transaction.read_native_config_outcome(path, binding)
    assert proof["status"] == "completed" and proof["candidateHash"] == prepared.candidate_hash
    assert proof["candidateHash"] != public_config_hash(tomllib.loads(path.read_text()))
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.parent.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("field,value", [("requestFingerprint", "d" * 64), ("agentId", "agent-other"), ("enabled", False)])
def test_same_locator_cannot_bind_different_parameters_or_target(tmp_path, monkeypatch, field, value):
    path, _before = _write_config(tmp_path)
    binding = request(tmp_path)
    monkeypatch.setattr(transaction, "reload_config", lambda _path: None)
    prepared = prepare(path, binding)
    transaction.apply_operator_config_transaction(prepared)
    altered = {**binding, field: value}
    assert transaction.native_config_operation_id(path, binding) == transaction.native_config_operation_id(path, altered)
    with pytest.raises(ValueError, match="binding changed"):
        transaction.read_native_config_outcome(path, altered)


@pytest.mark.parametrize("change", [{"subjectId": "ops-" + "e" * 32}, {"requestKey": "f" * 64}, {"projectRoot": None}])
def test_foreign_identity_does_not_discover_original_proof(tmp_path, monkeypatch, change):
    path, _before = _write_config(tmp_path)
    binding = request(tmp_path)
    monkeypatch.setattr(transaction, "reload_config", lambda _path: None)
    transaction.apply_operator_config_transaction(prepare(path, binding))
    change = {key: str(tmp_path / "foreign") if value is None else value for key, value in change.items()}
    assert transaction.read_native_config_outcome(path, {**binding, **change}) is None


@pytest.mark.parametrize("tamper", ["backup", "duplicate_json", "version", "config_path", "backup_path", "extra", "bool_as_integer"])
def test_corrupt_proof_is_unavailable_without_reading_caller_selected_paths(tmp_path, monkeypatch, tamper):
    path, _before = _write_config(tmp_path)
    binding = request(tmp_path)
    monkeypatch.setattr(transaction, "reload_config", lambda _path: None)
    prepared = prepare(path, binding)
    transaction.apply_operator_config_transaction(prepared)
    record = json.loads(prepared.manifest_path.read_text())
    if tamper == "backup":
        from pathlib import Path
        Path(record["afterBackup"]).write_bytes(b"changed")
    elif tamper == "duplicate_json":
        prepared.manifest_path.write_text('{"schemaVersion":2,' + prepared.manifest_path.read_text()[1:])
    else:
        if tamper == "version": record["schemaVersion"] = True
        elif tamper == "config_path": record["configPath"] = str(tmp_path / "elsewhere")
        elif tamper == "backup_path": record["afterBackup"] = str(tmp_path / "elsewhere")
        elif tamper == "bool_as_integer": record["nativeRequest"]["enabled"] = 1
        else: record["proof"] = "forged"
        prepared.manifest_path.write_text(json.dumps(record))
    with pytest.raises((ValueError, UnicodeError)):
        transaction.read_native_config_outcome(path, binding)


def test_native_request_cannot_overwrite_prior_manifest_or_backups(tmp_path, monkeypatch):
    path, _before = _write_config(tmp_path)
    binding = request(tmp_path)
    monkeypatch.setattr(transaction, "reload_config", lambda _path: None)
    prepared = prepare(path, binding)
    transaction.apply_operator_config_transaction(prepared)
    snapshots = {p: p.read_bytes() for p in prepared.manifest_path.parent.iterdir()}
    # Simulate a caller preparing the same original ID against the new state.
    repeat = transaction.prepare_operator_config_transaction(operation_kind="agent_dispatch_access_set",
        expected_base_hash=public_config_hash(tomllib.loads(path.read_text())), mutate_text=lambda text: text,
        config_path=path, native_request=binding)
    with pytest.raises(ValueError, match="already exists"):
        transaction.apply_operator_config_transaction(repeat)
    assert {p: p.read_bytes() for p in prepared.manifest_path.parent.iterdir()} == snapshots


@pytest.mark.parametrize("published", [False, True])
def test_uncertain_final_manifest_ack_never_rolls_back_a_possible_commit_decision(tmp_path, monkeypatch, published):
    path, _before = _write_config(tmp_path)
    binding = request(tmp_path)
    monkeypatch.setattr(transaction, "reload_config", lambda _path: None)
    update = transaction._update_transaction_manifest
    def lose_completion(artifacts, **kwargs):
        if kwargs["status"] == "completed":
            if published: update(artifacts, **kwargs)
            raise OSError("completion acknowledgement unavailable")
        update(artifacts, **kwargs)
    monkeypatch.setattr(transaction, "_update_transaction_manifest", lose_completion)
    prepared = prepare(path, binding)
    with pytest.raises(transaction.OperatorConfigTransactionError) as failure:
        transaction.apply_operator_config_transaction(prepared)
    assert failure.value.status == "commit_unconfirmed"
    assert path.read_bytes() == prepared.after_bytes
    proof = transaction.read_native_config_outcome(path, binding)
    assert proof["status"] == ("completed" if published else "reloaded")


@pytest.mark.parametrize("change", [{"path": "elsewhere"}, {"enabled": "true"}, {"subjectType": "agent"},
    {"projectRoot": "relative"}, {"action": "config_update"}, {"requestKey": "invalid"}])
def test_native_binding_is_closed_not_a_generic_config_proxy(tmp_path, change):
    path, _before = _write_config(tmp_path)
    with pytest.raises(ValueError): prepare(path, request(tmp_path, **change))
    assert not (tmp_path / "backups").exists()
