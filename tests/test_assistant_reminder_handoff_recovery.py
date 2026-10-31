import hashlib
import json
import os

import pytest

from core.assistant_runtime import reminder_handoff_intent as handoff
from core.assistant_runtime.migration_io import MigrationIOError


pytestmark = pytest.mark.skipif(os.name != "nt", reason="native pinned target writes require Windows")


class Token:
    def check(self):
        pass

    def publish(self, commit):
        return commit()


def binding():
    project = "registered:1"
    identity = {"device": "1", "inode": "2", "birthtimeNs": "3"}
    return {"schemaVersion": 1, "registeredProjectId": project,
            "sourceScope": {"projectId": "source", "instanceId": "main", "agentId": "agent"},
            "category": "reminder_handoff", "turnId": "first", "operationId": handoff.handoff_id(project),
            "syncId": handoff.sync_id(project), "revision": 1, "sourceIdentityDigest": "a" * 64,
            "registryDigest": "b" * 64, "targetIdentityDigest": "c" * 64,
            "projectDirectory": identity, "workspaceDirectory": identity, "targetDirectory": identity,
            "targetAgentId": "target", "targetSessionId": "session", "authority": "native_policy_admitted",
            "baselineId": None, "baselineState": "unknown", "readyForCutover": False}


def base(tmp_path):
    initial = binding()
    handoff.publish_handoff_intent(tmp_path, initial, Token(), lambda: None)
    row, head = handoff.read_handoff_authorization(tmp_path, initial["registeredProjectId"])
    return row, head


def refresh(tmp_path, row, head, **kwargs):
    candidate = {**row, "turnId": "second", "revision": 2, "registryDigest": "d" * 64, **kwargs}
    return handoff.publish_handoff_intent(tmp_path, candidate, Token(), lambda: None,
                                           expected_head=head, owner_check=lambda: True)


def test_refresh_preserves_base_and_keeps_original_ids(tmp_path):
    original, head = base(tmp_path)
    path = tmp_path / "reminder_handoff_intents" / hashlib.sha256(original["operationId"].encode()).hexdigest() / "intent.json"
    raw = path.read_bytes()
    updated = refresh(tmp_path, original, head)
    effective, new_head = handoff.read_handoff_authorization(tmp_path, original["registeredProjectId"])
    assert path.read_bytes() == raw
    assert effective == handoff.read_handoff_intent(tmp_path, original["registeredProjectId"]) == updated
    assert new_head != head and effective["operationId"] == original["operationId"] and effective["syncId"] == original["syncId"]
    with pytest.raises(MigrationIOError):
        refresh(tmp_path, original, head)
    final = {**effective, "turnId": "third", "revision": 3, "registryDigest": "e" * 64}
    handoff.publish_handoff_intent(tmp_path, final, Token(), lambda: None,
                                   expected_head=new_head, owner_check=lambda: True)
    assert handoff.read_handoff_intent(tmp_path, original["registeredProjectId"]) == final
    assert path.read_bytes() == raw


@pytest.mark.parametrize("field,value", [("targetSessionId", "other"), ("sourceIdentityDigest", "e" * 64),
                                         ("targetIdentityDigest", "e" * 64), ("registryDigest", "b" * 64)])
def test_refresh_rejects_changed_identity_or_unchanged_registry(tmp_path, field, value):
    row, head = base(tmp_path)
    with pytest.raises(MigrationIOError):
        refresh(tmp_path, row, head, **{field: value})
    assert handoff.read_handoff_authorization(tmp_path, row["registeredProjectId"]) == (row, head)


def test_refresh_requires_expected_head_and_owner(tmp_path):
    row, head = base(tmp_path)
    changed = {**row, "registryDigest": "d" * 64}
    for options in ({}, {"expected_head": head}, {"expected_head": head, "owner_check": lambda: False},
                    {"expected_head": "0" * 64, "owner_check": lambda: True}):
        with pytest.raises(MigrationIOError):
            handoff.publish_handoff_intent(tmp_path, changed, Token(), lambda: None, **options)
    assert handoff.read_handoff_authorization(tmp_path, row["registeredProjectId"]) == (row, head)


def test_unrelated_daily_receipts_do_not_authorize_or_block_refresh(tmp_path):
    row, head = base(tmp_path)
    receipts = tmp_path / "reminder_receipts" / "20260101"
    receipts.mkdir(parents=True)
    (receipts / "reminders.sqlite3").write_bytes(b"unrelated")
    updated = refresh(tmp_path, row, head)
    assert updated["readyForCutover"] is False
    assert (receipts / "reminders.sqlite3").read_bytes() == b"unrelated"


@pytest.mark.parametrize("failure", ["cancelled", "owner_lost", "artifact_appears", "publication_unknown", "response_lost"])
def test_refresh_publication_failure_is_not_replayed(tmp_path, monkeypatch, failure):
    row, head = base(tmp_path)
    candidate = {**row, "turnId": "second", "revision": 2, "registryDigest": "d" * 64}
    checks = 0
    def owner():
        nonlocal checks
        checks += 1
        return failure != "owner_lost" or checks < 3
    class InterruptingToken:
        def check(self):
            pass
        def publish(self, commit):
            if failure == "cancelled":
                raise ValueError("cancelled")
            if failure == "artifact_appears":
                digest = hashlib.sha256(row["syncId"].encode()).hexdigest()
                path = tmp_path / "reminder_offline_operations" / (digest + ".intent.json")
                path.parent.mkdir()
                path.write_text("claim", encoding="utf-8")
            commit()
            if failure == "response_lost":
                raise ValueError("response lost")
    if failure == "publication_unknown":
        monkeypatch.setattr(handoff, "publish_directory", lambda *args: (_ for _ in ()).throw(ValueError("unknown")))
    with pytest.raises((MigrationIOError, ValueError)):
        handoff.publish_handoff_intent(tmp_path, candidate, InterruptingToken(), lambda: None,
                                       expected_head=head, owner_check=owner)
    if failure == "publication_unknown":
        with pytest.raises(MigrationIOError):
            handoff.read_handoff_authorization(tmp_path, row["registeredProjectId"])
    else:
        current, current_head = handoff.read_handoff_authorization(tmp_path, row["registeredProjectId"])
        assert (current, current_head) == ((candidate, current_head) if failure == "response_lost" else (row, head))
        if failure == "response_lost":
            assert current_head != head
            with pytest.raises(MigrationIOError):
                refresh(tmp_path, row, head)


def test_refresh_rechecks_original_binding_before_publication(tmp_path):
    row, head = base(tmp_path)
    intent = tmp_path / "reminder_handoff_intents" / hashlib.sha256(row["operationId"].encode()).hexdigest() / "intent.json"
    altered = {**row, "turnId": "changed-by-other-owner"}
    class ChangedToken:
        def check(self):
            pass
        def publish(self, commit):
            intent.write_text(json.dumps(altered), encoding="ascii")
            return commit()
    with pytest.raises(MigrationIOError):
        handoff.publish_handoff_intent(tmp_path, {**row, "registryDigest": "d" * 64}, ChangedToken(), lambda: None,
                                       expected_head=head, owner_check=lambda: True)
    assert handoff.read_handoff_intent(tmp_path, row["registeredProjectId"]) == altered


@pytest.mark.parametrize("artifact", ["claim", "sync-intent", "initial-claim", "archive", "archive-pending", "record", "receipt", "baseline-receipt", "preparation", "config"])
def test_existing_original_artifacts_block_refresh(tmp_path, artifact):
    row, head = base(tmp_path)
    digest = hashlib.sha256(row["syncId"].encode()).hexdigest()
    paths = {"claim": f"reminder_offline_operations/{digest}.intent.json",
             "sync-intent": f"reminder_offline_operations/{digest}.sync-intent.json",
             "initial-claim": f"initial_migration_claims/{row['operationId']}",
             "archive": f"history_sources/migrations/{row['syncId']}",
             "archive-pending": f"history_sources/migrations/.pending-{row['syncId']}",
             "record": f"affairs_conflicts/{digest}.json", "receipt": f"affairs_sync_receipts/{digest}.json",
             "baseline-receipt": f"affairs_migrations/{digest}.json",
             "preparation": "reminder_handoff_preparations/unknown.intent.json",
             "config": f".initial-migration-models-v1-{row['operationId']}-{row['registryDigest']}.toml"}
    path = tmp_path / paths[artifact]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("evidence", encoding="utf-8")
    with pytest.raises(MigrationIOError):
        refresh(tmp_path, row, head)
    assert path.read_text(encoding="utf-8") == "evidence"


@pytest.mark.parametrize("failure", ["pending", "bad_hash", "orphan", "fork"])
def test_refresh_chain_damage_is_rejected(tmp_path, failure):
    row, head = base(tmp_path)
    refresh(tmp_path, row, head)
    chain = tmp_path / "reminder_handoff_intent_refreshes" / hashlib.sha256(row["operationId"].encode()).hexdigest()
    record_path = next(chain.iterdir())
    record = json.loads((record_path / "intent.json").read_text(encoding="ascii"))
    if failure == "pending":
        (chain / (".pending-" + "a" * 32)).mkdir()
    elif failure == "bad_hash":
        (record_path / "intent.json").write_text("{}", encoding="ascii")
    else:
        record["parentSha256"] = "0" * 64 if failure == "orphan" else head
        record["binding"]["turnId"] = "third"
        raw = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
        extra = chain / hashlib.sha256(raw).hexdigest()
        extra.mkdir()
        (extra / "intent.json").write_bytes(raw)
    with pytest.raises(MigrationIOError):
        handoff.read_handoff_authorization(tmp_path, row["registeredProjectId"])
