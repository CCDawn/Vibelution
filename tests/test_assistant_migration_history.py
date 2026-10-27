"""The PA archive is a retained, immutable view, never Session admission."""
import json
from pathlib import Path

import pytest

from core.assistant_runtime import migration_history as history


AGENT = "agent-pa"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def journal(workspace, sid, *, open_turn=False):
    path = workspace / "sessions" / sid / "turn_journal.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [dict(eventId=f"{sid}-e{i}", sessionId=sid, turnId="turn-1", sequence=i,
                 eventType=kind, payload=payload) for i, (kind, payload) in enumerate([
        ("turn_started", {}), ("user_message", {"content": "PRIVATE_PROMPT", "messageId": "msg-1",
          "attachments": [{"id": "asset-original", "url": "file:///private.png"}]}),
        ("assistant_message", {"content": "answer", "messageId": "msg-2"}),
        ("turn_completed", {}),
    ], 1)]
    if open_turn:
        rows.pop()
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def source(tmp_path, rows=None):
    workspace = tmp_path / "source/workspace"
    write_json(workspace / "agents/agents.json", {"agents": [{"agentId": AGENT,
        "directSessionId": "direct", "roleKey": "personal_assistant", "status": "active",
        "metadata": {"personalAssistantProfile": "personal_assistant_v1"}, "toolPolicy": {}}]})
    rows = rows if rows is not None else [{"id": "direct", "agent_id": AGENT}]
    write_json(workspace / "chat/chat_state.json", {"conversations": rows})
    for row in rows:
        journal(workspace, row["id"])
    return workspace


def discover(workspace, **kwargs):
    return history.discover_history(project_root=workspace.parent, workspace=workspace,
        project_id="project-1", instance_id="instance-1", assistant_agent_id=AGENT, **kwargs)


def test_retained_history_import_and_projection_are_read_only(tmp_path):
    workspace = source(tmp_path, [{"id": "direct", "agent_id": AGENT},
        {"id": "archived", "agentId": AGENT, "archived": True},
        {"id": "hidden", "parentSessionId": "direct", "hidden": True}])
    asset = workspace / "sessions/direct/artifacts/images/pic.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"png")
    before = {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    found = discover(workspace)
    assert found.report["historyComplete"] is True
    assert len(found.sessions) == 3
    assert "PRIVATE_PROMPT" not in json.dumps(found.report)
    result = history.import_history(found, tmp_path / "target", "migration-1")
    assert result["published"] is True
    listing = history.list_history(tmp_path / "target")
    assert len(listing) == 3 and "PRIVATE_PROMPT" not in json.dumps(listing)
    detail = history.history_detail(tmp_path / "target", listing[0]["historyId"])
    assert detail["readOnly"] and detail["untrustedContent"] and not detail["canContinue"]
    assert detail["events"][0]["eventId"].endswith("-e1")
    assert "PRIVATE_PROMPT" in json.dumps(detail)
    assert "file:///private.png" not in json.dumps(detail["messages"])
    assert before == {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}


def codes(found):
    return {row["code"] for row in found.report["issues"]}


def database(workspace, rows, *, root=True):
    from core.chat.conversation_store import runtime
    db = workspace / "chat/conversations.sqlite3"
    connection = runtime.connect(str(db))
    try:
        connection.execute("CREATE TABLE workspace_chat_state(id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE sessions(session_id TEXT, agent_id TEXT, parent_session_id TEXT)")
        connection.execute("CREATE TABLE session_runtime_state(session_id TEXT, payload_json TEXT)")
        if root:
            connection.execute("INSERT INTO workspace_chat_state VALUES (1)")
        for row in rows:
            connection.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                (row["id"], row.get("agent_id", AGENT), row.get("parent_session_id")))
            connection.execute("INSERT INTO session_runtime_state VALUES (?, ?)", (row["id"], json.dumps(row)))
    finally:
        connection.close()
    return db


def test_database_authority_keeps_archived_hidden_and_does_not_revive_legacy(tmp_path):
    workspace = source(tmp_path)
    rows = [{"id": "direct", "agent_id": AGENT},
            {"id": "archived", "agent_id": AGENT, "archived": True},
            {"id": "hidden", "agent_id": AGENT, "hidden": True}]
    for row in rows:
        journal(workspace, row["id"])
    database(workspace, rows)
    found = discover(workspace)
    assert found.report["historyComplete"] and found.report["authority"] == "sqlite"
    assert {s.session_id for s in found.sessions} == {"direct", "archived", "hidden"}
    # An initialized empty root is authoritative, even with stale JSON and a
    # retained orphan Journal. It must never be silently reimported.
    from core.chat.conversation_store import runtime
    conn = runtime.connect(str(workspace / "chat/conversations.sqlite3"))
    conn.execute("DELETE FROM sessions")
    conn.execute("DELETE FROM session_runtime_state")
    conn.close()
    empty = discover(workspace)
    assert empty.report["authority"] == "sqlite" and not empty.sessions
    assert empty.report["counts"]["orphanSessions"] == 3


def test_database_without_root_uses_legacy_and_tombstone_excludes_assets(tmp_path):
    workspace = source(tmp_path)
    database(workspace, [], root=False)
    marker = workspace / "sessions/direct/.session_deleted"
    marker.write_bytes(b"deleted")
    # Deliberately corrupt deleted content: excluded transcripts are not read.
    (marker.parent / "turn_journal.jsonl").write_bytes(b"bad")
    (marker.parent / "artifacts").mkdir()
    (marker.parent / "artifacts/secret").write_bytes(b"DELETED_ASSET")
    found = discover(workspace)
    assert found.report["historyComplete"] and found.report["authority"] == "legacy_json"
    assert not found.sessions and found.report["counts"]["deletedSessions"] == 1
    history.import_history(found, tmp_path / "target", "empty")
    assert history.list_history(tmp_path / "target") == []


def test_other_agent_excluded_and_unknown_owner_reported(tmp_path):
    workspace = source(tmp_path, [{"id": "direct", "agent_id": AGENT},
        {"id": "other", "agentId": "agent-other"}, {"id": "orphan"}])
    (workspace / "sessions/other/turn_journal.jsonl").write_bytes(b"NEVER_READ_OTHER_AGENT")
    found = discover(workspace)
    assert {s.session_id for s in found.sessions} == {"direct"}
    assert not found.report["historyComplete"]
    assert "history_orphan_ownership_unknown" in codes(found)
    assert "NEVER_READ_OTHER_AGENT" not in json.dumps(found.report)


@pytest.mark.parametrize("row", [
    {"id": "direct", "agent_id": "wrong"},
    {"id": "direct", "agent_id": AGENT, "agentId": "wrong"},
    {"id": "child", "agent_id": "wrong", "parentSessionId": "direct"},
    {"id": "child", "agent_id": AGENT, "parentSessionId": "foreign", "rootSessionId": "direct"},
])
def test_conflicting_ownership_fails_closed(tmp_path, row):
    rows = [row]
    if row["id"] != "direct":
        rows += [{"id": "direct", "agent_id": AGENT}, {"id": "foreign", "agent_id": "wrong"}]
    workspace = source(tmp_path, rows)
    found = discover(workspace)
    assert not found.report["historyComplete"] and not found.sessions


@pytest.mark.parametrize("mutation", ["bad_json", "duplicate_json_key", "missing_id", "duplicate_id",
    "wrong_session", "sequence_bool", "sequence_repeat", "truncated", "open_turn", "bad_payload"])
def test_journal_corruption_cannot_publish(tmp_path, mutation):
    workspace = source(tmp_path)
    path = workspace / "sessions/direct/turn_journal.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if mutation == "bad_json":
        raw = b"not-json\n"
    elif mutation == "duplicate_json_key":
        raw = b'{"eventId":"a","eventId":"b"}\n'
    elif mutation == "truncated":
        raw = path.read_bytes().rstrip(b"\n")
    else:
        if mutation == "missing_id": rows[0].pop("eventId")
        if mutation == "duplicate_id": rows[1]["eventId"] = rows[0]["eventId"]
        if mutation == "wrong_session": rows[0]["sessionId"] = "wrong"
        if mutation == "sequence_bool": rows[0]["sequence"] = True
        if mutation == "sequence_repeat": rows[1]["sequence"] = rows[0]["sequence"]
        if mutation == "open_turn": rows.pop()
        if mutation == "bad_payload": rows[0]["payload"] = []
        raw = "".join(json.dumps(row) + "\n" for row in rows).encode()
    path.write_bytes(raw)
    found = discover(workspace)
    assert not found.report["historyComplete"] and not found.sessions
    with pytest.raises(history.MigrationIOError, match="history_discovery_incomplete"):
        history.import_history(found, tmp_path / "target", "bad")
    assert not (tmp_path / "target").exists()


@pytest.mark.parametrize("limits", [{"max_files": 1}, {"max_rows": 1}, {"max_line_bytes": 2},
    {"max_file_bytes": 2}, {"max_total_bytes": 2}, {"max_sessions": 0}])
def test_limits_fail_closed(tmp_path, limits):
    found = discover(source(tmp_path), **limits)
    assert not found.report["historyComplete"] and not found.sessions


def test_nonempty_wal_refused_before_sqlite_and_source_not_written(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    db = database(workspace, [{"id": "direct", "agent_id": AGENT}])
    wal = Path(str(db) + "-wal")
    wal.write_bytes(b"uncheckpointed")
    monkeypatch.setattr(history, "_database_rows", lambda *a: pytest.fail("opened WAL source"))
    before = {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    found = discover(workspace)
    assert codes(found) == {"history_import_not_quiescent"}
    assert before == {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}


def test_import_is_idempotent_but_changed_source_and_target_are_rejected(tmp_path):
    workspace = source(tmp_path)
    found = discover(workspace)
    target = tmp_path / "target"
    history.import_history(found, target, "one")
    assert history.import_history(found, target, "one")["idempotent"]
    journal_path = workspace / "sessions/direct/turn_journal.jsonl"
    journal_path.write_bytes(journal_path.read_bytes().replace(b"answer", b"edited"))
    with pytest.raises(history.MigrationIOError, match="source_changed"):
        history.import_history(found, target, "one")
    with pytest.raises(history.MigrationIOError, match="history_migration_id_conflict"):
        history.import_history(discover(workspace), target, "one")
    archived = next(target.rglob("turn_journal.jsonl"))
    archived.write_bytes(b"tamper\n")
    with pytest.raises(history.MigrationIOError, match="history_archive_hash_mismatch"):
        history.list_history(target)


def append_turn(workspace, sid):
    path = workspace / "sessions" / sid / "turn_journal.jsonl"
    rows = [dict(eventId=f"{sid}-new-{i}", sessionId=sid, turnId="turn-2", sequence=i,
                 eventType=kind, payload={}) for i, kind in
            ((5, "turn_started"), (6, "turn_completed"))]
    with path.open("a", encoding="utf-8") as stream:
        stream.write("".join(json.dumps(row) + "\n" for row in rows))


def test_reimport_append_keeps_old_archive_and_selects_proven_extension(tmp_path):
    workspace = source(tmp_path)
    asset = workspace / "sessions/direct/artifacts/image.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"old")
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    old = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    append_turn(workspace, "direct")
    (asset.parent / "new.png").write_bytes(b"new")
    history.import_history(discover(workspace), target, "two")
    row, = history.list_history(target)
    assert row["migrationId"] == "two" and row["watermark"]["eventCount"] == 6
    detail = history.history_detail(target, row["historyId"])
    assert len(detail["events"]) == 6 and len(detail["attachments"]) == 2
    assert all((target / p).read_bytes() == data for p, data in old.items())


@pytest.mark.parametrize("change", ["rewrite", "truncate", "attachment_changed", "attachment_removed", "same_journal_new_asset"])
def test_reimport_rejects_non_append_or_changed_attachments_without_hiding_prior(tmp_path, change):
    workspace = source(tmp_path)
    asset = workspace / "sessions/direct/artifacts/image.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"old")
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    before = history.list_history(target)
    journal_path = workspace / "sessions/direct/turn_journal.jsonl"
    if change == "rewrite":
        journal_path.write_bytes(journal_path.read_bytes().replace(b"answer", b"edited"))
    elif change == "truncate":
        journal_path.write_bytes(b"")
    elif change == "same_journal_new_asset":
        (asset.parent / "new.png").write_bytes(b"new")
    else:
        append_turn(workspace, "direct")
        if change == "attachment_changed":
            asset.write_bytes(b"changed")
        else:
            asset.unlink()
    with pytest.raises(history.MigrationIOError, match="history_archive_identity_conflict"):
        history.import_history(discover(workspace), target, "two")
    assert history.list_history(target) == before
    assert history.history_detail(target, before[0]["historyId"])["migrationId"] == "one"


def test_existing_divergent_versions_are_isolated_to_their_history(tmp_path, monkeypatch):
    workspace = source(tmp_path, [{"id": "direct", "agent_id": AGENT},
                                  {"id": "other", "agent_id": AGENT}])
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    rows = history.list_history(target)
    ids = {row["sessionId"]: row["historyId"] for row in rows}
    path = workspace / "sessions/direct/turn_journal.jsonl"
    path.write_bytes(path.read_bytes().replace(b"answer", b"edited"))
    # Reproduce archives published by the old importer before this guard.
    monkeypatch.setattr(history, "_validate_history_extension", lambda *args, **kwargs: None)
    history.import_history(discover(workspace), target, "two")
    assert [row["sessionId"] for row in history.list_history(target)] == ["other"]
    assert history.history_detail(target, ids["other"])["sessionId"] == "other"
    with pytest.raises(history.MigrationIOError, match="history_archive_identity_conflict"):
        history.history_detail(target, ids["direct"])


def test_proven_chain_selection_does_not_depend_on_archive_iteration_order(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    append_turn(workspace, "direct")
    history.import_history(discover(workspace), target, "two")
    original = history._archives
    def reversed_archives(root, *, budget):
        yield from reversed(list(original(root, budget=budget)))
    monkeypatch.setattr(history, "_archives", reversed_archives)
    row, = history.list_history(target)
    assert row["migrationId"] == "two"
    assert len(history.history_detail(target, row["historyId"])["events"]) == 6


def test_newest_common_extension_does_not_hide_incomparable_older_versions(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    assets = workspace / "sessions/direct/artifacts"
    assets.mkdir(parents=True)
    (assets / "x").write_bytes(b"x")
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    hid = history.list_history(target)[0]["historyId"]
    validate = history._validate_history_extension
    monkeypatch.setattr(history, "_validate_history_extension", lambda *args, **kwargs: None)
    append_turn(workspace, "direct")
    (assets / "x").unlink()
    (assets / "y").write_bytes(b"y")
    history.import_history(discover(workspace), target, "two")
    (assets / "x").write_bytes(b"x")
    path = workspace / "sessions/direct/turn_journal.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        for sequence, kind in ((7, "turn_started"), (8, "turn_completed")):
            stream.write(json.dumps(dict(eventId=f"third-{sequence}", sessionId="direct",
                turnId="turn-3", sequence=sequence, eventType=kind, payload={})) + "\n")
    monkeypatch.setattr(history, "_validate_history_extension", validate)
    with pytest.raises(history.MigrationIOError, match="history_archive_identity_conflict"):
        history.import_history(discover(workspace), target, "three")
    monkeypatch.setattr(history, "_validate_history_extension", lambda *args, **kwargs: None)
    history.import_history(discover(workspace), target, "three")
    original = history._archives
    monkeypatch.setattr(history, "_archives", lambda root, *, budget: reversed(list(original(root, budget=budget))))
    assert history.list_history(target) == []
    with pytest.raises(history.MigrationIOError, match="history_archive_identity_conflict"):
        history.history_detail(target, hid)


@pytest.mark.parametrize("dimension", ["bytes", "files", "rows", "archives"])
def test_candidate_that_would_exceed_reader_budget_is_never_published(tmp_path, monkeypatch, dimension):
    workspace = source(tmp_path)
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    hid = history.list_history(target)[0]["historyId"]
    baseline = history._ArchiveBudget()
    list(history._archives(target, budget=baseline))
    default = history._ArchiveBudget.__init__.__defaults__
    remaining = (baseline.bytes_left, baseline.files_left, baseline.histories_left, baseline.archives_left)
    used = [limit - left for limit, left in zip(default, remaining)]
    index = {"bytes": 0, "files": 1, "rows": 2, "archives": 3}[dimension]
    limits = list(default)
    limits[index] = used[index] + (8 if dimension == "bytes" else 0)
    monkeypatch.setattr(history._ArchiveBudget.__init__, "__defaults__", tuple(limits))
    kwargs = dict(zip(("max_total_bytes", "max_files", "max_history_rows", "max_archives"), limits))
    append_turn(workspace, "direct")
    with pytest.raises(history.MigrationIOError, match="history_archive_limit"):
        history.import_history(discover(workspace), target, "two")
    assert not (target / "history_archive/migrations/.two.pending").exists()
    assert not (target / "history_archive/migrations/two").exists()
    assert history.list_history(target, **kwargs)[0]["historyId"] == hid
    assert history.history_detail(target, hid, **kwargs)["migrationId"] == "one"


def test_candidate_at_exact_reader_budget_remains_readable(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    first = discover(workspace)
    sample = tmp_path / "sample"
    history.import_history(first, sample, "one")
    append_turn(workspace, "direct")
    second = discover(workspace)
    history.import_history(second, sample, "two")
    budget = history._ArchiveBudget()
    list(history._archives(sample, budget=budget))
    default = history._ArchiveBudget.__init__.__defaults__
    remaining = (budget.bytes_left, budget.files_left, budget.histories_left, budget.archives_left)
    limits = tuple(limit - left for limit, left in zip(default, remaining))
    target = tmp_path / "target"
    # Restore the first snapshot as the source for its verified import.
    path = workspace / "sessions/direct/turn_journal.jsonl"
    full = path.read_bytes()
    path.write_bytes(first.sessions[0].journal.raw)
    history.import_history(discover(workspace), target, "one")
    path.write_bytes(full)
    monkeypatch.setattr(history._ArchiveBudget.__init__, "__defaults__", limits)
    history.import_history(discover(workspace), target, "two")
    kwargs = dict(zip(("max_total_bytes", "max_files", "max_history_rows", "max_archives"), limits))
    row, = history.list_history(target, **kwargs)
    assert row["migrationId"] == "two"
    assert history.history_detail(target, row["historyId"], **kwargs)["migrationId"] == "two"


def test_restart_resumes_exact_pending_copy_and_never_lists_it_early(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    found, target = discover(workspace), tmp_path / "target"
    real_write = history._write_new
    def interrupted(path, raw):
        if path.name == "manifest.json":
            raise InterruptedError("injected crash")
        return real_write(path, raw)
    monkeypatch.setattr(history, "_write_new", interrupted)
    with pytest.raises(history.MigrationIOError, match="target_namespace_unavailable"):
        history.import_history(found, target, "restart")
    assert history.list_history(target) == []
    monkeypatch.setattr(history, "_write_new", real_write)
    assert history.import_history(found, target, "restart")["published"]
    assert len(history.list_history(target)) == 1


def test_source_changes_during_copy_do_not_publish(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    found, target = discover(workspace), tmp_path / "target"
    real_write = history._write_new
    def changed(path, raw):
        real_write(path, raw)
        if path.name == "manifest.json":
            journal(workspace, "direct", open_turn=True)
    monkeypatch.setattr(history, "_write_new", changed)
    with pytest.raises(history.MigrationIOError, match="source_changed"):
        history.import_history(found, target, "changed")
    assert history.list_history(target) == []


@pytest.mark.parametrize("failure", ["source", "authority", "interrupted"])
def test_published_directory_stays_invisible_until_final_confirmation(tmp_path, monkeypatch, failure):
    workspace = source(tmp_path)
    found, target = discover(workspace), tmp_path / "target"
    publish = history.publish_directory
    final = target / "history_archive/migrations/one"
    observed = []
    def after_publish(pending, destination, identity):
        if destination.name == ".confirmed" and failure == "interrupted":
            raise InterruptedError("injected crash before confirmation")
        publish(pending, destination, identity)
        if destination == final:
            observed.append(history.list_history(target))
            if failure == "source":
                journal(workspace, "direct", open_turn=True)
    monkeypatch.setattr(history, "publish_directory", after_publish)
    def verify_authority():
        if failure == "authority" and final.exists():
            raise history.MigrationIOError("authority_changed")
    with pytest.raises((history.MigrationIOError, InterruptedError)):
        history.import_history(found, target, "one", authority_verify=verify_authority)
    assert observed == [[]]
    assert final.exists() and history.list_history(target) == []
    history_id = history._manifest(found, "one")[0]["histories"][0]["historyId"]
    with pytest.raises(history.MigrationIOError, match="history_not_found"):
        history.history_detail(target, history_id)
    if failure != "source":
        monkeypatch.setattr(history, "publish_directory", publish)
        if failure == "authority":
            with pytest.raises(history.MigrationIOError, match="authority_changed"):
                history.import_history(found, target, "one", authority_verify=verify_authority)
            assert history.list_history(target) == []
        checks = []
        def restored_authority():
            checks.append(True)
        assert history.import_history(found, target, "one", authority_verify=restored_authority)["idempotent"]
        assert checks
        assert len(history.list_history(target)) == 1


def test_v1_archives_remain_readable_and_idempotent(tmp_path):
    workspace = source(tmp_path)
    found, target = discover(workspace), tmp_path / "target"
    history.import_history(found, target, "one")
    archive = target / "history_archive/migrations/one"
    (archive / ".confirmed").rmdir()
    manifest_path = archive / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schemaVersion"] = 1
    manifest_path.write_bytes(history._encoded(manifest))
    assert len(history.list_history(target)) == 1
    assert history.import_history(found, target, "one")["idempotent"]


def test_process_crash_before_confirmation_stays_hidden_and_direct_retry_recovers(tmp_path):
    import subprocess
    import sys
    workspace = source(tmp_path)
    target = tmp_path / "target"
    code = """
import os, sys
from pathlib import Path
from core.assistant_runtime import migration_history as history
from tests.test_assistant_migration_history import discover
original = history.publish_directory
def crash(pending, final, identity):
    if final.name == '.confirmed':
        os._exit(42)
    return original(pending, final, identity)
history.publish_directory = crash
history.import_history(discover(Path(sys.argv[1])), Path(sys.argv[2]), 'one')
"""
    result = subprocess.run([sys.executable, "-c", code, str(workspace), str(target)],
                            check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 42
    assert history.list_history(target) == []
    assert history.import_history(discover(workspace), target, "one")["idempotent"]
    assert len(history.list_history(target)) == 1


def test_new_asset_or_tombstone_after_discovery_is_detected(tmp_path):
    workspace = source(tmp_path)
    assets = workspace / "sessions/direct/artifacts/nested"
    assets.mkdir(parents=True)
    (assets / "old").write_bytes(b"old")
    found = discover(workspace)
    (assets / "new").write_bytes(b"new")
    with pytest.raises(history.MigrationIOError, match="source_changed"):
        history.import_history(found, tmp_path / "target", "one")
    found = discover(workspace)
    (workspace / "sessions/direct/.session_deleted").write_bytes(b"deleted")
    with pytest.raises(history.MigrationIOError, match="source_changed"):
        history.import_history(found, tmp_path / "target", "one")


def test_target_cannot_overlap_source_or_accept_path_as_history_id(tmp_path):
    workspace = source(tmp_path)
    found = discover(workspace)
    with pytest.raises(history.MigrationIOError, match="history_target_overlaps_source"):
        history.import_history(found, workspace / "archive", "one")
    with pytest.raises(history.MigrationIOError, match="history_id_invalid"):
        history.history_detail(tmp_path / "target", "../source")


def test_hardlinked_source_is_rejected(tmp_path):
    import os
    workspace = source(tmp_path)
    path = workspace / "sessions/direct/turn_journal.jsonl"
    os.link(path, tmp_path / "hardlink")
    found = discover(workspace)
    assert not found.report["historyComplete"]
    assert "source_type_or_link_invalid" in codes(found)


def test_database_uses_only_readonly_copy_and_never_loads_native_state(tmp_path, monkeypatch):
    from core.chat.conversation_store import runtime
    import core.ui.chat_state
    workspace = source(tmp_path)
    db = database(workspace, [{"id": "direct", "agent_id": AGENT}])
    before = db.read_bytes()
    original = runtime.connect
    calls = []
    def readonly(database, **kwargs):
        assert kwargs.get("uri") is True and "mode=ro" in database
        assert str(db).replace("\\", "/") not in database
        calls.append(database)
        conn = original(database, **kwargs)
        execute = conn.execute
        def select(sql, parameters=()):
            assert sql.startswith("SELECT ")
            return execute(sql, parameters)
        conn.execute = select
        return conn
    monkeypatch.setattr(runtime, "connect", readonly)
    monkeypatch.setattr(core.ui.chat_state, "load_chat_state", lambda *a, **k: pytest.fail("native repair loader"))
    found = discover(workspace)
    assert found.report["historyComplete"] and calls and db.read_bytes() == before


def test_tool_item_and_message_event_ids_survive_native_projection(tmp_path):
    workspace = source(tmp_path)
    path = workspace / "sessions/direct/turn_journal.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows.insert(-1, dict(eventId="item-event", sessionId="direct", turnId="turn-1", sequence=4,
        eventType="assistant_item_committed", payload={"kind": "tool_call", "itemId": "item-1",
            "callId": "call-1", "revision": 0, "status": "completed", "text": "tool result"}))
    rows[-1]["sequence"] = 5
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    item = history.list_history(target)[0]
    detail = history.history_detail(target, item["historyId"])
    assert detail["turnItems"][0]["itemId"] == "item-1"
    assert "call-1" in json.dumps(detail["turnItems"])
    assert detail["events"][1]["payload"]["messageId"] == "msg-1"
    assert "PRIVATE_PROMPT" in detail["sourceBody"]


def test_symlinked_archive_and_sources_are_rejected(tmp_path):
    workspace = source(tmp_path)
    original = workspace / "sessions/direct/turn_journal.jsonl"
    moved = tmp_path / "original-journal"
    original.rename(moved)
    try:
        original.symlink_to(moved)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    found = discover(workspace)
    assert not found.report["historyComplete"] and "linked_source" in codes(found)


def test_published_extra_files_and_hardlinks_fail_integrity(tmp_path):
    import os
    workspace = source(tmp_path)
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    archive = target / "history_archive/migrations/one"
    extra = archive / "extra"
    extra.write_bytes(b"unmanifested")
    with pytest.raises(history.MigrationIOError, match="history_archive_file_mismatch"):
        history.list_history(target)
    extra.unlink()
    archived = next(archive.rglob("turn_journal.jsonl"))
    os.link(archived, tmp_path / "outside-hardlink")
    with pytest.raises(history.MigrationIOError, match="source_type_or_link_invalid"):
        history.list_history(target)


def test_database_ownership_disagreement_fails_closed(tmp_path):
    workspace = source(tmp_path)
    database(workspace, [{"id": "direct", "agent_id": AGENT, "agentId": "other"}])
    found = discover(workspace)
    assert not found.report["historyComplete"] and not found.sessions


def test_missing_authority_does_not_claim_empty_history(tmp_path):
    workspace = source(tmp_path)
    (workspace / "chat/chat_state.json").unlink()
    found = discover(workspace)
    assert not found.report["historyComplete"] and "history_authority_unavailable" in codes(found)


@pytest.mark.parametrize("operation", ["list", "detail"])
@pytest.mark.parametrize("limit", ["bytes", "files", "rows", "archives"])
def test_archive_read_budgets_are_shared_before_reading_next_archive(tmp_path, monkeypatch, operation, limit):
    workspace = source(tmp_path)
    target = tmp_path / "target"
    found = discover(workspace)
    history.import_history(found, target, "one")
    history_id = history.list_history(target)[0]["historyId"]
    archive = target / "history_archive/migrations/one"
    manifest_size = (archive / "manifest.json").stat().st_size
    single_bytes = sum(p.stat().st_size for p in archive.rglob("*") if p.is_file()) + 2 * manifest_size
    history.import_history(found, target, "two")
    kwargs = {"bytes": {"max_total_bytes": single_bytes + 10},
              "files": {"max_files": 10}, "rows": {"max_history_rows": 1},
              "archives": {"max_archives": 1}}[limit]
    from core.assistant_runtime import migration_io
    read = migration_io.read_stable_file
    read_bytes = 0
    def counted(*args, **kw):
        nonlocal read_bytes
        snapshot = read(*args, **kw)
        read_bytes += len(snapshot.raw)
        return snapshot
    monkeypatch.setattr(history, "read_stable_file", counted)
    monkeypatch.setattr(migration_io, "read_stable_file", counted)
    with pytest.raises(history.MigrationIOError, match="^history_archive_limit$"):
        if operation == "list":
            history.list_history(target, **kwargs)
        else:
            history.history_detail(target, history_id, **kwargs)
    if limit == "bytes":
        assert read_bytes <= kwargs["max_total_bytes"]


def test_archive_iterator_does_not_eagerly_read_later_archives(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    target = tmp_path / "target"
    found = discover(workspace)
    history.import_history(found, target, "one")
    history.import_history(found, target, "two")
    loaded = []
    original = history._load_archive
    def observed(path, **kwargs):
        loaded.append(path.name)
        return original(path, **kwargs)
    monkeypatch.setattr(history, "_load_archive", observed)
    iterator = history._archives(target, budget=history._ArchiveBudget())
    assert loaded == []
    next(iterator)
    assert len(loaded) == 1
    iterator.close()


def test_target_parent_alias_is_rejected_before_any_source_or_sibling_mutation(tmp_path):
    workspace = source(tmp_path)
    (workspace.parent / "staging").mkdir()
    found = discover(workspace)
    assert found.report["historyComplete"], found.report["issues"]
    target = workspace.parent / "staging" / ".." / workspace.name
    before = {str(p.relative_to(tmp_path)): (p.is_dir(), p.read_bytes() if p.is_file() else None)
              for p in tmp_path.rglob("*")}
    with pytest.raises(history.MigrationIOError, match="^source_path_alias$"):
        history.import_history(found, target, "alias")
    after = {str(p.relative_to(tmp_path)): (p.is_dir(), p.read_bytes() if p.is_file() else None)
             for p in tmp_path.rglob("*")}
    assert after == before


@pytest.mark.parametrize("name", ["target.", "target ", "target:stream"])
def test_target_windows_aliases_fail_before_mkdir(tmp_path, name):
    workspace = source(tmp_path)
    found = discover(workspace)
    before = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")}
    with pytest.raises(history.MigrationIOError, match="source_path_alias"):
        history.import_history(found, tmp_path / name, "alias")
    assert {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")} == before


def test_windows_writer_pins_parent_before_exclusive_file_creation(tmp_path, monkeypatch):
    import os
    if os.name != "nt":
        pytest.skip("archive writes require Windows verified directory leases")
    workspace = source(tmp_path)
    target = tmp_path / "target"
    original_open = Path.open
    attempts = []
    def try_replacing_parent(path, mode="r", *args, **kwargs):
        if mode == "xb" and path.name == "turn_journal.jsonl":
            # This is the write seam after checks and immediately before open.
            # A swapped ancestor would redirect this otherwise ordinary open.
            with pytest.raises(OSError):
                path.parent.rename(path.parent.with_name("swapped"))
            attempts.append(path.parent)
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", try_replacing_parent)
    result = history.import_history(discover(workspace), target, "pinned")
    assert result["published"] and attempts
    assert len(history.list_history(target)) == 1


def test_rebound_pending_directory_cannot_be_published_after_verification(tmp_path, monkeypatch):
    from core.assistant_runtime.migration_io import publish_directory
    workspace = source(tmp_path)
    found = discover(workspace)
    target = tmp_path / "target"
    before = {str(p.relative_to(workspace)): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    calls = []
    def replace_before_handle_publish(pending, final, expected_identity):
        # The verified pending directory's no-delete lease has just ended.
        # Preserve that object and rebound the same pathname to a new one.
        pending.rename(pending.with_name(".verified-original.pending"))
        pending.mkdir()
        calls.append(pending)
        return publish_directory(pending, final, expected_identity)
    monkeypatch.setattr(history, "publish_directory", replace_before_handle_publish, raising=False)
    with pytest.raises(history.MigrationIOError, match="^target_pending_changed$"):
        history.import_history(found, target, "rebound")
    assert calls
    assert not (target / "history_archive/migrations/rebound").exists()
    assert history.list_history(target) == []
    assert before == {str(p.relative_to(workspace)): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}


def test_leaf_mutation_at_publish_never_returns_success(tmp_path, monkeypatch):
    original = history.publish_directory
    workspace = source(tmp_path)
    def tamper(pending, final, identity):
        leaf = next(pending.rglob("turn_journal.jsonl"))
        leaf.write_bytes(b"tampered")
        original(pending, final, identity)
    monkeypatch.setattr(history, "publish_directory", tamper)
    with pytest.raises(history.MigrationIOError):
        history.import_history(discover(workspace), tmp_path / "target", "tampered")
